"""Detailed logging of every outgoing HTTP request made through httpx.

Build clients with `make_client()` and each request/response is logged:
method, URL, headers, body, status, timing and a response body preview.
Secrets (API keys in query strings, Authorization headers) are redacted.
The same hook is the natural place to later plug in the privacy canary check.
"""

import json
import logging
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .config import settings

log = logging.getLogger("outgoing")

SECRET_PARAMS = {"key", "api_key", "apikey", "token", "access_token"}
SECRET_HEADERS = {"authorization", "x-api-key", "api-key", "cookie", "set-cookie"}


def _redact_url(url: httpx.URL) -> str:
    parts = urlsplit(str(url))
    query = [
        (k, "***" if k.lower() in SECRET_PARAMS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(query, safe="*")))


def _redact_headers(headers: httpx.Headers) -> dict:
    return {k: "***" if k.lower() in SECRET_HEADERS else v for k, v in headers.items()}


def _preview(raw: bytes) -> str:
    if not raw:
        return "<empty>"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<{len(raw)} bytes binary>"
    try:  # compact JSON
        text = json.dumps(json.loads(text), separators=(",", ":"))
    except ValueError:
        pass
    limit = settings.log_body_max_chars
    return text if len(text) <= limit else f"{text[:limit]}… (+{len(text) - limit} chars)"


async def _on_request(request: httpx.Request) -> None:
    request.extensions["started"] = time.perf_counter()
    log.info(
        "→ %s %s\n    headers: %s\n    body: %s",
        request.method,
        _redact_url(request.url),
        _redact_headers(request.headers),
        _preview(request.content),
    )


async def _on_response(response: httpx.Response) -> None:
    await response.aread()
    started = response.request.extensions.get("started")
    ms = f"{(time.perf_counter() - started) * 1000:.0f}ms" if started else "?"
    level = logging.INFO if response.status_code < 400 else logging.WARNING
    log.log(
        level,
        "← %s %s %s (%s, %d bytes)\n    body: %s",
        response.status_code,
        response.request.method,
        _redact_url(response.request.url),
        ms,
        len(response.content),
        _preview(response.content),
    )


def make_client(**kwargs) -> httpx.AsyncClient:
    hooks = {"request": [_on_request], "response": [_on_response]}
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)
