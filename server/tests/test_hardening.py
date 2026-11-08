"""Step 8: the whole workflow under pressure. Privacy canaries end to end, dead networks, determinism."""

import asyncio
import hashlib
import json
import logging
import time
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ingest, main
from app import llm as llm_mod
from app.agents import graph, nodes
from app.agents.present import present
from app.agents.privacy import REDACTED, scrub_request
from app.config import settings
from app.datagen import PERSONAS, generate
from app.db import private_db, work_db
from app.http_log import make_client

from tests.test_firewall import CANARIES, plant_canaries
from tests.test_nodes import CAR, GOOD_SUMMARY, FakeNemotron, json_reply, proposals_reply, tool_reply

END = date(2026, 11, 7)
SECRET_KEY = "nvapi-SUPERSECRETKEY-0123456789"
CANARY_ID = "9999000011112222"
CANARY_EMAIL = "zelda@canary.example"
PROPOSAL = proposals_reply(("acct_A", "acct_B", 3, "A gentle step"))


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "nemotron_lightning_model", "fast-model")
    monkeypatch.setattr(settings, "nemotron_super_model", "strong-model")
    monkeypatch.setattr(settings, "nvidia_api_key", SECRET_KEY)
    monkeypatch.setattr(settings, "llm_retries", 1)
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=END))


class RequestLog(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def request_log():
    handler, logger = RequestLog(), logging.getLogger("outgoing")
    old = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(old)


def logged_deps(transport_handler, **llm_kwargs) -> nodes.Deps:
    """Real LLM wrapper + real make_client logging; only the wire is faked."""
    client = make_client(
        base_url="https://nvidia.test/v1",
        headers={"Authorization": f"Bearer {SECRET_KEY}"},
        transport=httpx.MockTransport(transport_handler),
    )
    return nodes.default_deps(llm_mod.LLM(client, llm_mod.RateLimiter(10_000), **llm_kwargs))


def healthy_fake() -> FakeNemotron:
    return FakeNemotron(planner=[tool_reply(CAR)], explainer=[json_reply({"summary": GOOD_SUMMARY})],
                        action=[PROPOSAL], critic=[json_reply({"ok": True, "issues": []})])


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ canary, whole flow

def plant_everywhere():
    """Real-looking identity data in every place it could leak from."""
    with work_db() as w:
        plant_canaries(w)
    with private_db() as p:
        p.execute("UPDATE alias_map SET real_name = ?, real_id = ? WHERE alias = 'acct_A'",
                  (CANARIES[0], CANARIES[1]))
        p.execute("UPDATE alias_map SET real_name = ? WHERE alias = 'bill_1'", (CANARIES[2],))


def test_canaries_never_leave_through_any_agent_or_log(request_log):
    plant_everywhere()
    fake = healthy_fake()
    typed = (f"Can I afford a car? I bank at {CANARIES[0].lower()} (account {CANARY_ID}), "
             f"rent goes to {CANARIES[2]}, email me at {CANARY_EMAIL}")
    deps = logged_deps(fake)
    state = run(graph.run_flow(typed, deps))

    sent = [l for l in request_log.lines if l.startswith("→ POST")]
    assert len(sent) >= 4  # all four agents really went out through the logging client
    everything = "\n".join(request_log.lines) + json.dumps(fake.calls)
    for secret in (*CANARIES, CANARY_ID, CANARY_EMAIL, SECRET_KEY):
        assert secret not in everything, f"leaked: {secret}"
    planner_text = fake.calls["planner"][0]["messages"][1]["content"]
    assert planner_text.startswith("Can I afford a car?") and REDACTED in planner_text

    # ...but the customer's own screen gets the real name back
    shown = present(state)["proposals"][0]
    assert shown["from_label"] == CANARIES[0] and shown["from_alias"] == "acct_A"


def test_a_canary_hiding_in_the_database_is_refused_not_forwarded(request_log):
    """A planted name in an alias column makes the pack invalid: the flow fails closed."""
    with work_db() as w:
        w.execute("UPDATE obligations SET alias = ? WHERE alias = 'bill_1'", (CANARIES[2],))
    with pytest.raises(Exception):
        run(graph.run_flow("Can I afford a car?", logged_deps(healthy_fake())))
    assert not [l for l in request_log.lines if l.startswith("→ POST")]  # nothing was sent


# ------------------------------------------------------------------ scrubbing the typed request

def test_scrub_removes_private_names_ids_emails_and_long_numbers():
    out = scrub_request("Move from everyday checking, pay OAKWOOD APARTMENTS, mail a@b.co, card 4111 1111 1111 1111")
    for gone in ("everyday checking", "OAKWOOD", "a@b.co", "4111"):
        assert gone.lower() not in out.lower()
    assert out.count(REDACTED) == 4


@pytest.mark.parametrize("text", [
    "Can I afford a car?", "What if my rent goes up?", "a 60 month loan at 12% of my income",
    "I lost 20 hours", "new subscription for 15 dollars",
])
def test_scrub_leaves_ordinary_questions_alone(text):
    assert scrub_request(text) == text


# ------------------------------------------------------------------ dead network

def refuse(request):
    raise httpx.ConnectError("network is down", request=request)


def assert_canned_answer(state):
    assert set(state["fallbacks"]) == {"planner", "explainer", "action", "critic"}
    assert state["scenario"].kind == "none" and state["proposals"] == []
    assert state["explanation"].used_fallback and "educational estimate" in state["explanation"].text
    assert "{" not in state["explanation"].text and state["verdict"].ok


def test_dead_network_still_gives_a_complete_answer_and_stops_hammering():
    calls = []

    def handler(request):
        calls.append(1)
        refuse(request)

    started = time.perf_counter()
    state = run(graph.run_flow("Can I afford a car?", logged_deps(handler)))
    assert_canned_answer(state)
    assert time.perf_counter() - started < 5
    assert len(calls) == settings.llm_breaker_failures  # the breaker stopped further attempts


def test_a_closed_port_on_a_real_socket_behaves_the_same():
    """No mock: a genuine connection-refused from the operating system."""
    client = make_client(base_url="http://127.0.0.1:9/v1", timeout=2)
    deps = nodes.default_deps(llm_mod.LLM(client, llm_mod.RateLimiter(10_000)))
    state = run(graph.run_flow("Can I afford a car?", deps))
    assert_canned_answer(state)


def test_the_breaker_reopens_after_the_cooldown():
    now = [0.0]
    healthy = {"on": False}
    fake = healthy_fake()

    def handler(request):
        return fake(request) if healthy["on"] else refuse(request)

    client = httpx.AsyncClient(base_url="https://x/v1", transport=httpx.MockTransport(handler))
    llm = llm_mod.LLM(client, llm_mod.RateLimiter(10_000), clock=lambda: now[0])
    tool = nodes.SIMULATE_SPEC
    msgs = [{"role": "system", "content": "You turn a customer's request"}, {"role": "user", "content": "car"}]
    ask = lambda: run(llm.call_tool("planner", msgs, tool, {"kind": "none"}))

    assert ask().used_fallback and ask().used_fallback  # 3 failed attempts open the breaker
    assert llm.breaker_open() and "circuit open" in ask().error
    healthy["on"], now[0] = True, settings.llm_breaker_cooldown_seconds + 1
    assert not llm.breaker_open() and not ask().used_fallback  # back to normal
    assert llm._failures == 0


def test_a_slow_start_does_not_trip_the_breaker_when_calls_succeed():
    llm_ok = healthy_fake()
    state = run(graph.run_flow("buy a car", logged_deps(llm_ok)))
    assert state["fallbacks"] == [] and state["verdict"].ok


def test_the_api_returns_a_result_even_when_the_network_is_down():
    main.app.dependency_overrides[main.get_deps] = lambda: logged_deps(refuse)
    try:
        with TestClient(main.app).stream("POST", "/api/advise", json={"request": "Can I afford a car?"}) as r:
            events = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
    finally:
        main.app.dependency_overrides.clear()
    result = events[-1]
    assert result["explanation"]["canned"] and sorted(result["fallbacks"]) == ["action", "critic", "explainer", "planner"]
    assert "educational estimate" in result["explanation"]["text"]


# ------------------------------------------------------------------ the pinned demo

def fingerprint(history) -> str:
    return hashlib.sha256(json.dumps([repr(e) for e in history.events]).encode()).hexdigest()


def test_the_pinned_demo_data_is_identical_every_time():
    a = generate(PERSONAS["alex"], seed=42, months=24, end=END)
    b = generate(PERSONAS["alex"], seed=42, months=24, end=END)
    assert fingerprint(a) == fingerprint(b) and a.final_cents == b.final_cents


def test_the_same_question_gives_the_same_numbers():
    first = run(graph.run_flow("Can I afford a car?", logged_deps(healthy_fake())))
    second = run(graph.run_flow("Can I afford a car?", logged_deps(healthy_fake())))
    assert first["simulation"] == second["simulation"] and first["risk"] == second["risk"]
    assert first["explanation"].text == second["explanation"].text
    assert [p.outcome for p in first["proposals"]] == [p.outcome for p in second["proposals"]]
