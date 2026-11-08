"""Safe Nemotron calls: every agent talks to the model through this module.

Guarantees, so a bad model response never reaches the user as a blank screen or a crash:
  * a hard overall timeout on every request and a 40-requests/minute limiter (NVIDIA free tier);
  * retries (default 1 extra attempt) on timeouts, HTTP 429/5xx and unusable output;
  * tool calls are FORCED by name (`tool_choice`), because the fast model skipped the tool
    ~1 time in 3 when left to choose; the arguments are still validated afterwards;
  * thinking mode is off by default (faster); pass thinking=True for the rare step that needs it;
  * if every attempt fails, the caller's canned `fallback` is returned with used_fallback=True;
  * a circuit breaker: after `llm_breaker_failures` network/server failures in a row we stop calling
    NVIDIA for `llm_breaker_cooldown_seconds` and answer from the canned fallbacks immediately, so a
    dead network costs seconds, not 30 s per agent.

Callers pass messages built from a FactPack (see engine_firewall.firewall); this module does
not inspect content. All HTTP goes through make_client(), so each request is logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from .config import settings
from .http_log import make_client

log = logging.getLogger("llm")

Role = Literal["planner", "explainer", "action", "critic"]
_FAST_ROLES = {"planner", "critic"}
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class RateLimiter:
    """Allow at most `limit` calls in any rolling `window` seconds; extra callers wait."""

    def __init__(self, limit: int, window: float = 60.0, clock=time.monotonic, sleep=asyncio.sleep):
        self.limit, self.window, self._clock, self._sleep = limit, window, clock, sleep
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= self.window:
                    self._stamps.popleft()
                if len(self._stamps) < self.limit:
                    self._stamps.append(now)
                    return
                await self._sleep(self.window - (now - self._stamps[0]))


@dataclass
class LLMResult:
    data: Any  # parsed JSON / tool arguments, or the fallback when used_fallback
    used_fallback: bool = False
    error: str = ""
    model: str = ""
    seconds: float = 0.0
    attempts: int = 0


class OutputRejected(Exception):
    """The model answered, but not in a usable form."""


def model_for(role: Role) -> str:
    return settings.nemotron_lightning_model if role in _FAST_ROLES else settings.nemotron_super_model


def tool_spec(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _strip(text: str) -> str:
    text = text.split("</think>")[-1].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


class LLM:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        limiter: RateLimiter | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._client = client
        self._limiter = limiter or RateLimiter(settings.llm_requests_per_minute)
        self._clock = clock
        self._failures = 0  # consecutive network/server failures
        self._open_until = 0.0  # breaker is open (calls skipped) until this time

    def breaker_open(self) -> bool:
        return self._clock() < self._open_until

    def _record(self, ok: bool) -> None:
        if ok:
            self._failures = 0
            return
        self._failures += 1
        if self._failures >= settings.llm_breaker_failures:
            self._open_until = self._clock() + settings.llm_breaker_cooldown_seconds
            self._failures = 0
            log.error("llm breaker open for %gs", settings.llm_breaker_cooldown_seconds)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_client(
                base_url=settings.llm_base_url,
                headers={"Authorization": f"Bearer {settings.nvidia_api_key.get_secret_value()}"},
                timeout=settings.llm_timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _post(self, body: dict) -> dict:
        await self._limiter.acquire()
        # httpx timeouts apply per phase; wait_for caps the whole request (a slow trickle could
        # otherwise run for minutes). The limiter wait above is deliberately not counted.
        try:
            r = await asyncio.wait_for(
                self._get_client().post("/chat/completions", json=body), settings.llm_timeout_seconds
            )
        except asyncio.TimeoutError as e:
            raise httpx.ReadTimeout(f"no answer within {settings.llm_timeout_seconds:g}s") from e
        if r.status_code != 200:
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
        return r.json()["choices"][0]["message"]

    def _body(self, role: Role, messages: list[dict], thinking: bool, max_tokens: int, **extra) -> dict:
        body = {
            "model": model_for(role),
            "messages": messages,
            "temperature": settings.llm_temperature_precise if role in _FAST_ROLES else settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "max_tokens": max_tokens,
            **extra,
        }
        if not thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        return body

    async def _run(self, role: Role, body: dict, parse: Callable[[dict], Any], fallback: Any) -> LLMResult:
        started = time.perf_counter()
        error = ""
        attempts = 1 + max(0, settings.llm_retries)
        attempt = 0
        for attempt in range(1, attempts + 1):
            if self.breaker_open():
                error = "NVIDIA unreachable (circuit open); using the canned answer"
                break
            try:
                message = await self._post(body)
                self._record(True)
                data = parse(message)
                return LLMResult(data, False, "", body["model"], time.perf_counter() - started, attempt)
            except httpx.HTTPStatusError as e:
                error = f"{e}"
                if e.response.status_code not in _RETRY_STATUS:
                    break  # 401/404/400: retrying will not help
                self._record(False)
            except httpx.TransportError as e:  # timeouts, connection resets, DNS
                error = f"{type(e).__name__}: {e}"
                self._record(False)
            except (OutputRejected, ValueError, KeyError, TypeError) as e:
                error = f"bad output: {e}"
            log.warning("llm %s attempt %d/%d failed: %s", role, attempt, attempts, error)
        log.error("llm %s used fallback after %d attempt(s): %s", role, attempt, error)
        return LLMResult(fallback, True, error, body["model"], time.perf_counter() - started, attempt)

    async def call_tool(
        self,
        role: Role,
        messages: list[dict],
        tool: dict,
        fallback: Any,
        validate: Callable[[dict], dict] | None = None,
        thinking: bool = False,
        max_tokens: int = 512,
    ) -> LLMResult:
        """Force `tool` to be called; data = its validated arguments dict."""
        name = tool["function"]["name"]
        body = self._body(
            role, messages, thinking, max_tokens,
            tools=[tool], tool_choice={"type": "function", "function": {"name": name}},
        )

        def parse(message: dict) -> dict:
            calls = message.get("tool_calls") or []
            if not calls or calls[0]["function"]["name"] != name:
                raise OutputRejected(f"no {name} tool call")
            args = json.loads(calls[0]["function"]["arguments"])
            if not isinstance(args, dict):
                raise OutputRejected("tool arguments are not an object")
            return validate(args) if validate else args

        return await self._run(role, body, parse, fallback)

    async def call_json(
        self,
        role: Role,
        messages: list[dict],
        fallback: Any,
        validate: Callable[[dict], Any] | None = None,
        thinking: bool = False,
        max_tokens: int = 1024,
    ) -> LLMResult:
        """Ask for a JSON object; data = validate(parsed) (e.g. a Pydantic model_validate)."""
        body = self._body(role, messages, thinking, max_tokens, response_format={"type": "json_object"})

        def parse(message: dict) -> Any:
            obj = json.loads(_strip(message.get("content") or ""))
            if not isinstance(obj, dict):
                raise OutputRejected("answer is not a JSON object")
            return validate(obj) if validate else obj

        return await self._run(role, body, parse, fallback)
