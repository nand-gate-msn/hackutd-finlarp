"""/api/advise (streamed), Accept and Undo re-running the forecast. Offline: fake Nemotron, real tools."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import ingest, main
from app.config import settings
from app.datagen import PERSONAS, generate
from app.db import private_db

from tests.test_nodes import CAR, GOOD_SUMMARY, FakeNemotron, deps_for, json_reply, proposals_reply, tool_reply

SMALL = proposals_reply(("acct_A", "acct_B", 3, "A gentle step"))
APPROVE = json_reply({"ok": True, "issues": []})


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "nemotron_lightning_model", "fast-model")
    monkeypatch.setattr(settings, "nemotron_super_model", "strong-model")
    monkeypatch.setattr(settings, "llm_retries", 0)
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=date(2026, 11, 7)))


@pytest.fixture
def client():
    fake = FakeNemotron(planner=[tool_reply(CAR)], explainer=[json_reply({"summary": GOOD_SUMMARY})],
                        action=[SMALL], critic=[APPROVE])
    main.app.dependency_overrides[main.get_deps] = lambda: deps_for(fake)
    c = TestClient(main.app)
    c.fake = fake
    yield c
    main.app.dependency_overrides.clear()


def read_sse(response) -> list[tuple[str, dict]]:
    events, name = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            events.append((name, json.loads(line[6:])))
    return events


def advise(client, text="Can I afford a car?"):
    with client.stream("POST", "/api/advise", json={"request": text}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        return read_sse(r)


def test_stream_reports_each_agent_then_the_result(client):
    events = advise(client)
    assert [e for e, _ in events] == ["start", "progress", "progress", "progress", "progress", "result"]
    assert [d["agent"] for e, d in events if e == "progress"] == ["planner", "explainer", "action", "critic"]
    assert events[0][1]["agents"] == ["planner", "explainer", "action", "critic"]


def test_result_has_everything_the_screen_needs(client):
    result = advise(client)[-1][1]
    assert result["scenario"]["kind"] == "car_loan"
    assert result["forecast"]["scenario"]["share_below_zero"] >= result["forecast"]["baseline"]["share_below_zero"]
    assert result["risk"]["overall"] in ("ok", "watch", "risk")
    assert "educational estimate" in result["explanation"]["text"] and not result["explanation"]["canned"]
    [p] = result["proposals"]
    assert p["percent"] == 3 and p["forecast"] is not None and p["reason"]
    h = result["health"]
    assert h["what_if"] and h["after"]["score"] < h["before"]["score"] and h["change"] < 0
    assert h["drivers"][0]["label"] == "Housing and debt load" and h["drivers"][0]["effect"] == "worse"
    assert p["health"]["score"] > h["after"]["score"] and p["health"]["change_vs_scenario"] > 0
    assert result["verdict"]["ok"] and result["retries"] == 0 and result["fallbacks"] == []
    assert "fact_pack" not in result  # what the model saw is not echoed back


def test_a_send_back_shows_up_in_the_stream(client):
    client.fake.replies["action"] = [proposals_reply(("acct_A", "acct_B", 30, "Aggressive")), SMALL]
    agents = [d["agent"] for e, d in advise(client) if e == "progress"]
    assert agents == ["planner", "explainer", "action", "critic", "action", "critic"]


def test_real_names_are_restored_for_the_customer_only(client):
    with private_db() as p:
        p.execute("UPDATE alias_map SET real_name = 'Everyday Checking' WHERE alias = 'acct_A'")
    [p] = advise(client)[-1][1]["proposals"]
    assert p["from_label"] == "Everyday Checking" and p["from_alias"] == "acct_A"
    assert "Everyday Checking" not in json.dumps(client.fake.calls)  # the model never saw it


def test_the_customers_words_reach_the_planner_and_explainer_but_not_action_or_critic(client):
    advise(client, "Can I afford a car? My name is Zelda Canary")
    for role in ("action", "critic"):
        assert "Zelda" not in json.dumps(client.fake.calls[role])
    assert "Zelda" in json.dumps(client.fake.calls["planner"])  # a first name is not a known private name...
    assert "Can I afford a car?" in json.dumps(client.fake.calls["explainer"])  # ...and the question is explained


def test_dead_model_still_streams_a_complete_result(client):
    for role in ("planner", "explainer", "action", "critic"):
        client.fake.replies[role] = [None]
    events = advise(client)
    assert events[-1][0] == "result"
    assert all(d["fallback"] for e, d in events if e == "progress")
    assert events[-1][1]["explanation"]["canned"]


def test_bad_requests_are_rejected_before_any_model_call(client):
    assert client.post("/api/advise", json={"request": ""}).status_code == 422
    assert client.post("/api/advise", json={"request": "x" * 501}).status_code == 422
    assert client.post("/api/advise", json={}).status_code == 422
    assert sum(len(c) for c in client.fake.calls.values()) == 0


def test_unloaded_database_returns_a_clear_503(client, monkeypatch):
    monkeypatch.setattr(main, "is_loaded", lambda: False)
    r = client.post("/api/advise", json={"request": "hi"})
    assert r.status_code == 503 and "load_customer" in r.json()["detail"]


def test_an_unexpected_crash_becomes_an_error_event_not_a_hung_stream(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("secret internals")
        yield  # pragma: no cover

    monkeypatch.setattr(main, "stream_flow", boom)
    events = advise(client)
    assert events[-1][0] == "error" and "secret internals" not in json.dumps(events)


# ------------------------------------------------------------------ accept / undo

def accept(client, percent=20.0, scenario=CAR):
    return client.post("/api/accept", json={"from_alias": "acct_A", "to_alias": "acct_B",
                                            "percent": percent, "scenario": scenario})


def test_accept_saves_the_rule_and_reruns_the_forecast_with_it(client):
    r = accept(client)
    assert r.status_code == 200
    body = r.json()
    before, after = body["forecast"]["before"], body["forecast"]["after"]
    assert body["rule_id"] and before["kind"] == after["kind"] == "car_loan"
    assert after["baseline"] != before["baseline"]  # the saved rule is now part of the forecast
    health = body["health"]
    assert health["after"]["score"] > health["before"]["score"] and health["change"] > 0  # saving lifts the score
    rules = client.get("/api/rules").json()
    assert [(x["from_alias"], x["percent"], x["status"]) for x in rules] == [("acct_A", 20.0, "active")]


def test_undo_reruns_the_forecast_and_restores_the_original(client):
    first = accept(client).json()
    r = client.post(f"/api/undo/{first['rule_id']}", json={"scenario": CAR})
    assert r.status_code == 200 and r.json()["status"] == "undone"
    assert r.json()["forecast"]["after"] == first["forecast"]["before"]
    assert r.json()["health"]["after"] == first["health"]["before"]  # undo restores the old score too
    assert client.post(f"/api/undo/{first['rule_id']}").status_code == 409  # already undone


def test_accept_without_a_scenario_still_works(client):
    r = client.post("/api/accept", json={"from_alias": "acct_A", "to_alias": "acct_B", "percent": 5})
    assert r.status_code == 200 and r.json()["forecast"]["before"]["kind"] == "none"


@pytest.mark.parametrize("body", [
    {"from_alias": "acct_A", "to_alias": "acct_B", "percent": 50},
    {"from_alias": "acct_B", "to_alias": "acct_A", "percent": 5},
    {"from_alias": "acct_A", "to_alias": "acct_Z", "percent": 5},
])
def test_bad_accepts_are_refused_and_save_nothing(client, body):
    assert client.post("/api/accept", json=body).status_code in (400, 404, 422)
    assert client.get("/api/rules").json() == []


def test_a_rule_the_customer_accepted_appears_in_later_advice(client):
    accept(client, percent=4.0)
    result = advise(client)[-1][1]
    assert result["forecast"]["baseline"]  # forecast includes the rule
    pack_prompt = json.dumps(client.fake.calls["explainer"][0]["messages"])
    assert '\\"percent\\":4.0' in pack_prompt and "acct_B" in pack_prompt


def test_health_warns_when_the_loaded_data_is_not_the_pinned_demo_date(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_end_date", "2026-11-07")
    ok = client.get("/health").json()
    assert ok["data_end"] == "2026-11-07" and "warning" not in ok
    monkeypatch.setattr(settings, "demo_end_date", "2026-11-09")
    assert "load_customer" in client.get("/health").json()["warning"]


def test_the_pages_gauge_and_the_copilot_agree_on_todays_score(client):
    gauge = client.get("/api/metrics").json()["overallFinHealth"]
    result = advise(client)[-1][1]
    assert result["health"]["before"]["score"] == gauge
    accept(client, percent=15.0)
    assert client.get("/api/metrics").json()["overallFinHealth"] > gauge  # accepting moved the gauge


# ------------------------------------------------------------------ rewind to a checkpoint

def accept_many(client, percents=(3.0, 5.0, 8.0)):
    return [accept(client, percent=p).json()["rule_id"] for p in percents]


def test_rules_carry_a_title_and_real_account_names_for_the_screen(client):
    with private_db() as p:
        p.execute("UPDATE alias_map SET real_name = 'Everyday Checking' WHERE alias = 'acct_A'")
    accept(client, percent=5.0)
    [rule] = client.get("/api/rules").json()
    assert rule["title"] == "Save 5% of each paycheck" and rule["from_label"] == "Everyday Checking"
    assert rule["created_at"] and rule["status"] == "active"


def test_revert_keeps_the_checkpoint_and_everything_before_it(client):
    first, second, third = accept_many(client)
    r = client.post("/api/revert", json={"to_rule_id": second, "scenario": CAR})
    assert r.status_code == 200 and r.json()["reverted"] == [third]
    status = {x["id"]: x["status"] for x in client.get("/api/rules").json()}
    assert status == {first: "active", second: "active", third: "undone"}


def test_revert_to_the_start_undoes_everything_and_restores_the_original_numbers(client):
    original = client.post("/api/accept", json={"from_alias": "acct_A", "to_alias": "acct_B", "percent": 3}).json()
    before = original["forecast"]["before"]
    accept_many(client, (5.0, 8.0))
    r = client.post("/api/revert", json={"to_rule_id": None, "scenario": {"kind": "none"}})
    assert r.status_code == 200 and len(r.json()["reverted"]) == 3
    assert not [x for x in client.get("/api/rules").json() if x["status"] == "active"]
    assert r.json()["forecast"]["after"]["baseline"] == before["baseline"]  # the finances are as they were
    assert r.json()["health"]["after"]["score"] == original["health"]["before"]["score"]


def test_revert_returns_the_forecast_and_health_before_and_after(client):
    _, second, _ = accept_many(client)
    body = client.post("/api/revert", json={"to_rule_id": second, "scenario": CAR}).json()
    assert body["forecast"]["after"] != body["forecast"]["before"]
    assert body["health"]["after"]["score"] < body["health"]["before"]["score"]  # fewer savings rules, lower score


def test_revert_to_a_missing_or_undone_change_is_refused_and_changes_nothing(client):
    first, second = accept_many(client, (3.0, 5.0))
    client.post(f"/api/undo/{first}", json={})
    assert client.post("/api/revert", json={"to_rule_id": 9999}).status_code == 404
    assert client.post("/api/revert", json={"to_rule_id": first}).status_code == 409
    status = {x["id"]: x["status"] for x in client.get("/api/rules").json()}
    assert status[second] == "active"


def test_reverting_to_the_latest_change_is_a_harmless_no_op(client):
    *_, last = accept_many(client)
    body = client.post("/api/revert", json={"to_rule_id": last}).json()
    assert body["reverted"] == [] and body["forecast"]["after"] == body["forecast"]["before"]
