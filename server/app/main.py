import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .actions import ActionError, accept_savings_transfer, undo_rule
from .config import SERVER_DIR, settings
from .overview import build_overview, is_loaded

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="Cash Flow Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "data_loaded": is_loaded()}


@app.get("/api/overview")
def overview(days: int = Query(90, ge=7, le=730)):
    """Anonymized snapshot of the loaded customer, read from SQLite."""
    if not is_loaded():
        raise HTTPException(503, "No customer data loaded. Run: python scripts/load_customer.py")
    return build_overview(days)


class AcceptRequest(BaseModel):
    from_alias: str = Field(examples=["acct_A"])
    to_alias: str = Field(examples=["acct_B"])
    percent: float = Field(examples=[5])


@app.post("/api/accept")
def accept(req: AcceptRequest):
    """User clicked Accept on 'move X% of each paycheck to savings'."""
    try:
        return accept_savings_transfer(req.from_alias, req.to_alias, req.percent)
    except ActionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.post("/api/undo/{rule_id}")
def undo(rule_id: int):
    try:
        return undo_rule(rule_id)
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
