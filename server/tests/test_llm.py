"""Offline tests for app.llm: no network, a fake transport plays the model."""

import asyncio
import json

import httpx
import pytest

from app import llm as llm_mod
from app.config import settings

TOOL = llm_mod.tool_spec(
    "simulate", "forecast",
    {"type": "object", "properties": {"kind": {"type": "string"}}, "required": ["kind"]},
)
FALLBACK = {"kind": "none"}


@pytest.fixture(autouse=True)
def _models(monkeypatch):
    monkeypatch.setattr(settings, "nemotron_lightning_model", "fast-model")
    monkeypatch.setattr(settings, "nemotron_super_model", "strong-model")
    monkeypatch.setattr(settings, "llm_retries", 1)


def tool_reply(name="simulate", args=None):
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"function": {"name": name, "arguments": json.dumps(args if args is not None else {"kind": "car_loan"})}}]}}]}


def text_reply(text):
    return {"choices": [{"message": {"content": text}}]}


def make_llm(handler, limiter=None):
    sent = []

    def wrapped(request: httpx.Request):
        sent.append(json.loads(request.content))
        return handler(len(sent), request)

    client = httpx.AsyncClient(base_url="https://x/v1", transport=httpx.MockTransport(wrapped))
    return llm_mod.LLM(client, limiter or llm_mod.RateLimiter(1000)), sent


def run(coro):
    return asyncio.run(coro)


def call(llm, **kw):
    return run(llm.call_tool("planner", [{"role": "user", "content": "hi"}], TOOL, FALLBACK, **kw))


def test_tool_call_is_forced_by_name_and_thinking_is_off():
    llm, sent = make_llm(lambda n, r: httpx.Response(200, json=tool_reply()))
    res = call(llm)
    assert res.data == {"kind": "car_loan"} and not res.used_fallback
    body = sent[0]
    assert body["tool_choice"] == {"type": "function", "function": {"name": "simulate"}}
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["model"] == "fast-model"


def test_roles_pick_the_right_model_and_thinking_can_be_enabled():
    llm, sent = make_llm(lambda n, r: httpx.Response(200, json=text_reply('{"a": 1}')))
    res = run(llm.call_json("explainer", [{"role": "user", "content": "x"}], {}, thinking=True))
    assert res.data == {"a": 1}
    assert sent[0]["model"] == "strong-model" and "chat_template_kwargs" not in sent[0]


def test_missing_tool_call_is_retried_then_succeeds():
    def handler(n, r):
        return httpx.Response(200, json=text_reply("I'd rather chat") if n == 1 else tool_reply())

    llm, sent = make_llm(handler)
    res = call(llm)
    assert res.data == {"kind": "car_loan"} and res.attempts == 2 and not res.used_fallback


def test_wrong_tool_name_and_invalid_arguments_fall_back():
    llm, _ = make_llm(lambda n, r: httpx.Response(200, json=tool_reply(name="other")))
    assert call(llm).used_fallback

    def validate(args):
        raise ValueError("kind not allowed")

    llm, _ = make_llm(lambda n, r: httpx.Response(200, json=tool_reply()))
    res = call(llm, validate=validate)
    assert res.used_fallback and res.data == FALLBACK and "kind not allowed" in res.error


def test_garbled_tool_arguments_fall_back():
    bad = {"choices": [{"message": {"tool_calls": [{"function": {"name": "simulate", "arguments": "{oops"}}]}}]}
    llm, _ = make_llm(lambda n, r: httpx.Response(200, json=bad))
    assert call(llm).used_fallback


def test_timeout_then_429_then_success(monkeypatch):
    def handler(n, r):
        if n == 1:
            raise httpx.ReadTimeout("slow", request=r)
        return httpx.Response(429 if n == 2 else 200, json=tool_reply())

    monkeypatch.setattr(settings, "llm_retries", 2)
    llm, sent = make_llm(handler)
    res = call(llm)
    assert res.attempts == 3 and not res.used_fallback and len(sent) == 3


def test_auth_error_is_not_retried():
    llm, sent = make_llm(lambda n, r: httpx.Response(401, json={"detail": "bad key"}))
    res = call(llm)
    assert res.used_fallback and len(sent) == 1 and "401" in res.error


def test_server_errors_exhaust_retries_and_return_fallback():
    llm, sent = make_llm(lambda n, r: httpx.Response(503, text="down"))
    res = call(llm)
    assert res.used_fallback and res.data == FALLBACK and len(sent) == 2


def test_json_fences_think_blocks_and_validation():
    reply = text_reply('<think>hmm</think>\n```json\n{"risk_level": "high"}\n```')
    llm, _ = make_llm(lambda n, r: httpx.Response(200, json=reply))
    res = run(llm.call_json("critic", [{"role": "user", "content": "x"}], {}))
    assert res.data == {"risk_level": "high"}

    llm, _ = make_llm(lambda n, r: httpx.Response(200, json=text_reply("[1, 2]")))
    assert run(llm.call_json("critic", [{"role": "user", "content": "x"}], {"f": 1})).used_fallback


def test_rate_limiter_blocks_the_call_over_the_limit():
    now = [0.0]
    waits = []

    async def fake_sleep(s):
        waits.append(s)
        now[0] += s

    limiter = llm_mod.RateLimiter(2, 60.0, clock=lambda: now[0], sleep=fake_sleep)

    async def go():
        for _ in range(3):
            await limiter.acquire()

    run(go())
    assert waits == [60.0]  # the 3rd call waited out the window


def test_overall_timeout_caps_a_slow_request(monkeypatch):
    monkeypatch.setattr(settings, "llm_timeout_seconds", 0.05)
    monkeypatch.setattr(settings, "llm_retries", 0)

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=tool_reply())

    client = httpx.AsyncClient(base_url="https://x/v1", transport=httpx.MockTransport(slow))
    llm = llm_mod.LLM(client, llm_mod.RateLimiter(1000))
    res = call(llm)
    assert res.used_fallback and "ReadTimeout" in res.error and res.seconds < 0.5


def test_canned_fallbacks_fill_from_a_fact_pack():
    import json as _json
    from pathlib import Path

    from app import fallbacks
    from app.factpack_schema import FactPack

    pack = FactPack.model_validate_json(Path("app/factpack_sample.json").read_text())
    text = fallbacks.EXPLAINER["summary"].format(**pack.slots())
    assert "{" not in text and fallbacks.DISCLAIMER in text
