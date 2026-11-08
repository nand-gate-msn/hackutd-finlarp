import json
import logging

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .actions import ActionError, accept_savings_transfer, revert_to, undo_rule
from .agents import nodes
from .agents.graph import AGENTS, stream_flow
from .agents.present import present, present_health
from .agents.state import merge_update
from .config import SERVER_DIR, settings
from .db import work_db
from .graph_api import build_graph, build_metrics
from .overview import build_overview, is_loaded
from .health import health as run_health
from .tools import NONE_SCENARIO, ScenarioInput, ToolError, simulate

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("api")

app = FastAPI(title="Cash Flow Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    out = {"status": "ok", "data_loaded": is_loaded()}
    if out["data_loaded"]:
        with work_db() as w:
            loaded_end = w.execute("SELECT value FROM meta WHERE key = 'end'").fetchone()
        out["data_end"] = loaded_end[0] if loaded_end else None
        # the demo must run on the pinned date; say so loudly if the loaded data is from another day
        if settings.demo_end_date and out["data_end"] != settings.demo_end_date:
            out["warning"] = (f"loaded data ends {out['data_end']} but DEMO_END_DATE is {settings.demo_end_date}; "
                              "run: python scripts/load_customer.py")
    return out


@app.get("/api/overview")
def overview(days: int = Query(90, ge=7, le=730)):
    """Anonymized snapshot of the loaded customer, read from SQLite."""
    if not is_loaded():
        raise HTTPException(503, "No customer data loaded. Run: python scripts/load_customer.py")
    return build_overview(days)


@app.get("/api/graph")
def graph(days: int = Query(90, ge=7, le=730), coverage: bool = False):
    """Aggregated money-flow graph: income -> accounts -> bills/categories (+ transfers)."""
    if not is_loaded():
        raise HTTPException(503, "No customer data loaded. Run: python scripts/load_customer.py")
    return build_graph(days, coverage)


@app.get("/api/metrics")
def metrics():
    """Overall financial-health score, pillar scores and per-indicator values."""
    if not is_loaded():
        raise HTTPException(503, "No customer data loaded. Run: python scripts/load_customer.py")
    return build_metrics()


_deps: nodes.Deps | None = None


def get_deps() -> nodes.Deps:
    """One shared model client for the whole app, so the 40-requests/minute limit is global.
    Tests replace this with a fake via app.dependency_overrides."""
    global _deps
    if _deps is None:
        _deps = nodes.default_deps()
    return _deps


class AdviseRequest(BaseModel):
    request: str = Field(min_length=1, max_length=500, examples=["Can I afford a car?"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/advise")
async def advise(req: AdviseRequest, deps: nodes.Deps = Depends(get_deps)):
    """Run the agent workflow and stream progress as Server-Sent Events.

    Events: `start` (agent list), one `progress` per finished agent (a send-back to Action shows up
    as another action/critic pair), then `result` (everything the screen needs), or `error`.
    """
    if not is_loaded():
        raise HTTPException(503, "No customer data loaded. Run: python scripts/load_customer.py")

    async def events():
        state: dict = {}
        yield _sse("start", {"agents": list(AGENTS)})
        try:
            async for agent, changes in stream_flow(req.request, deps):
                state = merge_update(state, changes)
                yield _sse("progress", {
                    "agent": agent,
                    "message": changes["events"][-1] if changes.get("events") else agent,
                    "fallback": agent in changes.get("fallbacks", []),
                })
            yield _sse("result", present(state))
        except Exception:  # never leave the stream hanging; details stay in the server log
            log.exception("advise failed")
            yield _sse("error", {"message": "Something went wrong while preparing advice. Please try again."})

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # no proxy buffering
    )


class AcceptRequest(BaseModel):
    from_alias: str = Field(examples=["acct_A"])
    to_alias: str = Field(examples=["acct_B"])
    percent: float = Field(examples=[5])
    # the what-if the customer was looking at, so the forecast is re-run for the same question
    scenario: ScenarioInput | None = None


class UndoRequest(BaseModel):
    scenario: ScenarioInput | None = None


class RevertRequest(BaseModel):
    # keep this accepted change and everything before it; null = back to the start (no accepted changes)
    to_rule_id: int | None = None
    scenario: ScenarioInput | None = None


def _rerun(scenario: ScenarioInput | None, change):
    """Run `change()` and return its result plus the forecast AND overall health before and after it."""
    sc = scenario or NONE_SCENARIO
    try:
        before, health_before = simulate(sc), run_health(sc)
        result = change()
        after, health_after = simulate(sc), run_health(sc)
    except ToolError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        **result,
        "forecast": {"before": before.model_dump(mode="json"), "after": after.model_dump(mode="json")},
        "health": {
            "before": present_health(health_before, sc)["after"],
            "after": present_health(health_after, sc)["after"],
            "change": round(health_after.after.score - health_before.after.score, 1),
        },
    }


@app.post("/api/accept")
def accept(req: AcceptRequest):
    """Accept: code (not the AI) saves the rule, then re-runs the forecast with it applied."""
    try:
        return _rerun(req.scenario, lambda: accept_savings_transfer(req.from_alias, req.to_alias, req.percent))
    except ActionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/undo/{rule_id}")
def undo(rule_id: int, req: UndoRequest | None = None):
    try:
        return _rerun(req.scenario if req else None, lambda: undo_rule(rule_id))
    except ActionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/revert")
def revert(req: RevertRequest):
    """Rewind finances to a checkpoint: later accepted changes are undone, and the forecast and health re-run."""
    try:
        return _rerun(req.scenario, lambda: revert_to(req.to_rule_id))
    except ActionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.get("/api/rules")
def rules():
    return build_overview(7)["rules"]


# Serve the built React app from this same process (production only: client/dist
# exists once you've run `npm run build`). Mounted last so /api/* and /health win.
_DIST = SERVER_DIR.parent / "client" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="client")
