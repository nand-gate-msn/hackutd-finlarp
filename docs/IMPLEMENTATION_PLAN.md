# Plan: fix review findings and ship a working prototype

## Context
The codebase today is a FastAPI + SQLite backend with a React/Vite client. It has a synthetic data generator, an ingest step that anonymizes data (work db vs private alias db), a keyword categorizer, a per-account overview, and accept/undo savings rules. The code review found that the project's core feature, the transaction graph, doesn't exist. It also found no engines, no LLM layer and no firewall, plus several correctness and privacy bugs in the existing code. Nessie and Supabase are dropped (no auth).

Goal: a working end-to-end prototype ASAP: generate data, build the graph and metrics, forecast, ask the agents "buy a car?", see the result stream to the UI, accept a rule, and deploy it. Anything that doesn't serve that demo is cut or deferred.

Review finding numbers (#1 to #10) refer to the code-review list above.

## Role changes (read first)
The CS #1 / CS #2 split in the brief puts roughly 80% of the work on CS #1 and leaves CS #2 blocked on it. Proposed changes:

| Item | Brief | Now | Why |
|---|---|---|---|
| FactPack Pydantic model (schema only) | CS #1 | **CS #2, day 0** | It is the contract between the engines and the agents. CS #2 writes it plus a hand-written `factpack_sample.json`, so both sides code against it from hour one. CS #1 only has to fill it. |
| Backtest (skill score, 80% coverage, Brier) | CS #1 | **Cut to stretch** | Not needed for the demo. It only matters once the forecast runs. |
| Category classifier rework (#2) | (nobody) | **CS #2** | Self-contained and cheap, and it takes load off CS #1. It must land before graph category nodes are built. |
| API/cleanup fixes (#5, #7, #8, #9, #10) | (nobody) | **CS #2** | They are all in `main.py`, `actions.py`, `db.py` and config, which CS #2 touches for the SSE wiring anyway. |
| Graph tables and builder (#1) | CS #1 | CS #1 (unchanged) | It sits on the critical path. If CS #1 falls behind, hand the frontend graph view to CS #2 and keep only builder logic with CS #1. |
| Firewall function | CS #1 | CS #1, but **CS #2 reviews it** | No real prompt may reach NVIDIA before it exists. CS #2 develops against the hand-written pack, so it isn't blocked. |
| EC2 hello-world | CS #2 | CS #2, **first** | De-risks deploy early. |

## Who does what, and in what order
Phases run top to bottom. Within a phase, the two columns run in parallel. "Waits on" shows what blocks a task.

| Phase | CS #1 (engines, data, firewall) | CS #2 (agents, API, UI, deploy) | Waits on |
|---|---|---|---|
| **0: Contracts** (about 1 hr) | Data-layer fixes #3, #4, #6. Agree the FactPack fields with CS #2. | **Goes first on the schema:** write `FactPack` and `factpack_sample.json`. Start the EC2 hello-world deploy. | CS #1 needs CS #2's schema by the end of the phase. |
| **1: Foundations** | Graph tables and builder, `/api/graph`. 7 metrics, with placeholder thresholds. | Cleanup (#10, #9, #7, #8, #5), classifier rework (#2), NVIDIA client wrapper. | The graph builder needs the classifier's new categories, so CS #2 ships the classifier first (about 1 hr). |
| **2: Engines vs agents** | Monte Carlo forecast. FactPack builder. **Firewall and canary test (hard gate).** | LangGraph workflow (Planner, Explainer, Action, Critic) on the stub fact pack with a stubbed `simulate` tool. SSE endpoint. | The firewall is CS #1's. CS #2 reviews it and does not send a real prompt until it passes. |
| **3: Integration** | Hands over the real FactPack, `simulate` and metrics. Fix whatever the agents surface. | Swap the stub for the real engines. Wire Accept to the existing rule code and re-run the forecast. First real NVIDIA call, **only after the canary test passes**. | Needs all of CS #1's phase 2. |
| **4: Demo path** | Backtest (stretch). Help with graph rendering. | Frontend: scenario box, streaming agent panels, graph view, Accept/Undo. Deploy to EC2, backup cron. | Needs phase 3. |

Order of who goes first: CS #2 starts the critical contract (FactPack) and the deploy risk. CS #1 starts the data and graph work that everything else reads. CS #1 then owns the firewall gate. CS #2 integrates and ships.

## CS #1: data core, engines and firewall (order matters)
1. **Data-layer fixes** (small, do first because everything builds on these):
   - #3 Store `merchant_category` per transaction. `ingest.py` already writes `category` on each transaction row, so stop deriving it from the per-merchant map and drop the last-write-wins `h.merchants` dependence.
   - #4 Atomic alias commit. Write the work db first inside the same `with`, and commit the private db last (or add a "persona/seed matches" check on load). Don't prune aliases until the work db commit succeeds.
   - #6 Make `overview.py` apply the `(start, end]` window to `paychecks` and `late_by_ob`. Keep all-history stats as clearly named separate fields.
2. **Graph tables** (#1), in `db.py` `WORK_SCHEMA` + new `app/graph.py`:
   - `graph_nodes(id, type, alias, label_band, tag)` and `graph_edges(src, dst, type, amount_cents, tag)`. `tag` is `observed|simulated|proposed`. Node types: income, account, obligation, category (group). Edge types: funds, pays, transfers.
   - `build_graph()` is called at the end of `load_history` (alias-only data, so no privacy change). Bill matching: each deposit pays the earliest unpaid bills in due-date order.
   - Expose `GET /api/graph`.
3. **7 metrics** in `app/metrics.py`: pure functions over `transactions` returning `{value, status, formula}`. Thresholds come from Finance #1. Use placeholder constants in one dict until they arrive.
4. **Monte Carlo** in `app/forecast.py`. Add `numpy` to `requirements.txt`. Detect recurring items (same payee, ~5% amount, regular cadence). Resample the customer's own weekly spending for variable categories. 5,000 paths, 30-90 days, report p10/p50/p90 and share of paths below zero. A scenario is one extra scheduled payment on the same RNG draws (seeded). The baseline/scenario difference must be exactly the scenario.
5. **FactPack builder + firewall** in `app/factpack.py` and `app/firewall.py`:
   - Fill CS #2's `FactPack` (`extra="forbid"`) from engine outputs only: ratios, category totals, aliases, value bands.
   - `firewall.send(pack: FactPack) -> prompt` is the only function that builds prompts.
   - Canary test: plant fake name, account number and merchant in the data (the `CANARY_*` env vars already exist). Route all outgoing requests through `http_log.make_client`, and fail if a canary appears in any request body. Put a `canary_log` list on the client for this.
6. **Stretch:** backtest (skill score vs "same as last month" and "3-month average", 80% interval coverage, Brier).

## CS #2: agents, API, UI and deploy
1. **Day 0:** write `FactPack` (`app/factpack_schema.py`, `extra="forbid"`) and `factpack_sample.json`. Hand the schema to CS #1.
2. **EC2 hello-world** following `DEPLOY.md`: venv, `.env`, `load_customer.py`, systemd with `--workers 1`, Caddy. Add a backup cron using `sqlite3 .backup`.
3. **Cleanup** (before agent work builds on it):
   - #10 Delete `supabase/schema.sql`. Prune `.env.example` of NESSIE/SUPABASE keys. **Rotate the Nessie key and the Supabase service_role/anon keys found in the untracked `server/.env`**, then delete that file. Remove `http_log.py` only if unused after step 5 of CS #1.
   - #9 Create the schema once at startup (FastAPI lifespan) and move the `executescript` / WAL pragma out of `_open`. Put the setup inside the `try` so the connection always closes.
   - #7 `/api/rules` becomes a direct `SELECT * FROM rules` and returns 503 when no customer is loaded.
   - #8 Make accept idempotent: reject (409) if an active rule with the same from/to pair exists, or cap the total active percent at `MAX_PERCENT`. Wire the frontend to `/api/accept` and `/api/undo`. Rules are consumed by the forecast (the "re-run forecast" step below).
   - #5 Split `build_overview` into an anonymized view (aliases/bands, the only one that feeds the graph/agents) and a labelled view for the UI only. Call out the labelled endpoint as UI-only in the code.
4. **Classifier** (#2) in `categories.py`:
   - Add keywords for gas/fuel, pharmacy/clinic, cinema, and a new **Education/School** group (tuition, bookstore, campus).
   - Use word-boundary regexes and specific phrases instead of bare `market`, `water`, `energy` and `insurance`. Put the most specific rules first.
   - Unknown categories fall back to `uncategorized`/`Other`, not their own group.
   - Add parametrized tests for the false positives named in the review.
5. **NVIDIA client** `app/llm.py`: one async function over the OpenAI-compatible endpoint, with a 40 rpm limiter, a timeout, 1-2 retries, JSON-mode output and a canned fallback. It uses the logging client from `http_log.py`.
6. **LangGraph workflow** `app/agents/`: state (fact pack, scenario, proposals, critic verdict, retries) and the Planner, Explainer (`{housing_share}`-style slots filled server-side), Action (up to 3 percentage proposals) and Critic (code checks first, then an AI pass). The conditional edge sends weak proposals back to Action at most twice. Add `langgraph` and the SQLite checkpointer to `requirements.txt`. Develop against `factpack_sample.json` with a stubbed `simulate` tool until CS #1's forecast lands.
7. **SSE endpoint** `POST/GET /api/agent/run` streaming one event per agent. Accept calls the existing `accept_savings_transfer` and then re-runs the forecast.
8. **Frontend:** a scenario box, streaming agent panels, a basic graph view (reuse `/api/graph`), and Accept/Undo buttons.

## Milestones
1. Hour 0-2: FactPack schema and sample JSON (CS #2), hello-world deploy (CS #2), data-layer fixes #3/#4/#6 (CS #1).
2. Next: graph + metrics (CS #1); cleanup, classifier, NVIDIA client (CS #2).
3. Next: Monte Carlo + FactPack builder + firewall + canary test (CS #1); LangGraph + SSE (CS #2) running on the stub.
4. Integration: swap the stub for the real engines. **Gate: the canary test passes before the first real NVIDIA call.**
5. Frontend demo path, deploy to EC2, backup. Backtest only if time remains.

## Critical files
- `server/app/db.py`, `ingest.py`, `overview.py`, `categories.py`, `actions.py`, `main.py`, `http_log.py`, `config.py`
- New: `graph.py`, `metrics.py`, `forecast.py`, `factpack.py`, `firewall.py`, `llm.py`, `agents/`
- `server/requirements.txt` (numpy, langgraph), `.env.example`, `DEPLOY.md`, `client/src/App.jsx`

## Verification
- `cd server && pytest`: existing tests plus new ones: per-transaction category, windowed overview stats, atomic reload, classifier false positives, idempotent accept, graph invariants (every bill has a payer edge or is flagged unpaid), metrics on the alex persona, a forecast determinism test (same seed gives the same paths) and a check that baseline and scenario differ only by the scenario.
- Canary test passes (no planted name, account number or merchant in any logged request body).
- Run `scripts/load_customer.py --persona alex`, start uvicorn and the Vite dev server, run "buy a car" in the UI, and watch the agent events stream in. Accept a rule and check the forecast re-runs and the rule appears under `/api/rules`. Undo it.
- On EC2: `curl https://<host>/health`, then the same flow through Caddy.
