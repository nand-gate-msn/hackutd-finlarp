# Cash Flow Copilot

Cash Flow Copilot is a financial what-if demo built for HackUTD. It generates a synthetic customer history, visualizes cash flow, forecasts financial decisions, and suggests savings changes that the user can preview, accept, and undo. It uses React + Vite, FastAPI, SQLite, and a four-agent LangGraph workflow with NVIDIA Nemotron.

## How it works

1. **Generate and ingest:** the demo loader creates a reproducible customer history and loads anonymized accounts, transactions, and obligations into SQLite. The alias-to-name lookup stays in a separate private database.
2. **Explore:** the dashboard shows accounts, a money-flow graph, and financial-health metrics calculated by the backend.
3. **Ask a what-if question:** try “Can I afford a car?” or “What if my rent goes up?” The API streams progress through these agents:
   - **Planner:** turns the request into a validated scenario; backend code calculates forecasts, risk, and health.
   - **Explainer:** explains the results using placeholders that the server fills with calculated numbers.
   - **Action:** proposes up to three savings moves; backend code evaluates each proposal.
   - **Critic:** applies code checks and model review, returning weak proposals to Action within a bounded retry limit (two retries by default).
4. **Preview and accept:** inspect projected changes on the graph and forecast, or request fixes for a flagged problem. Accepting a savings rule saves it locally and recalculates the forecast and health. Changes can be undone individually or reverted to an earlier checkpoint.

Blocked requests end after the Explainer with a fixed response. Model failures use standard fallback responses, which the UI marks in the progress display.

Financial calculations run in Python. Model prompts use a filtered FactPack with aliases, ratios, and bands; typed requests are scrubbed for known private names, IDs, emails, and long numeric identifiers before being sent to a model. Accepted rules affect the demo simulation; they do not initiate bank transfers.

## Local setup

Prerequisites:

- Python 3.11+ (NumPy 2.3 requires Python 3.11 or newer).
- Node.js 20.19+ on the Node 20 line, or Node.js 22.12+; npm is used with the committed lockfile.
- An NVIDIA API key and configured model IDs for live AI responses. The dashboard and calculations work without a key; advice falls back to standard responses when model calls fail.

Run these commands from the repository root unless a step changes directories.

### 1. Configure the backend

```bash
python3 -m venv server/.venv
server/.venv/bin/python -m pip install -r server/requirements-dev.txt
cp .env.example server/.env
```

The backend reads **`server/.env`**. Edit that file before starting the server:

| Variable | Purpose |
| --- | --- |
| `NVIDIA_API_KEY` | Credentials for the hosted model endpoint. |
| `LLM_BASE_URL` | Model endpoint; the example uses NVIDIA's hosted API. |
| `NEMOTRON_SUPER_MODEL` | Model for Explainer and Action. |
| `NEMOTRON_LIGHTNING_MODEL` | Model for Planner and Critic; the example leaves this blank, so set it for live responses from those agents. |
| `DEMO_PERSONA` | `alex` (tight budget), `jordan` (saver), or `sam` (gig income). |
| `DEMO_END_DATE` | Last day of generated history. Keep it pinned for reproducible demos; the example uses `2026-11-07`. |
| `RANDOM_SEED` | Seed for data generation and Monte Carlo calculations. |
| `MONTE_CARLO_RUNS` | Number of simulation runs; defaults to `5000`. |
| `SQLITE_PATH` / `PRIVATE_DB_PATH` | Working and private database paths, resolved relative to `server/`. |
| `FRONTEND_ORIGIN` | Allowed browser origin; defaults to `http://localhost:5173`. |

Keep `server/.env` and generated files under `server/data/` out of version control; both are ignored by Git.

### 2. Load the demo and start the API

In the first terminal:

```bash
cd server
.venv/bin/python scripts/load_customer.py
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The loader generates 24 months of history by default. It creates `server/data/copilot.db`, `server/data/private.db`, and `server/data/ground_truth.json` with the default configuration.

Check `http://localhost:8000/health`: `data_loaded` should be `true`, and `data_end` should match your pinned date. Interactive API docs are at `http://localhost:8000/docs`.

### 3. Start the frontend

In a second terminal, starting from the repository root:

```bash
cd client
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` requests to FastAPI on port `8000`; check `/health` directly on the backend port.

## Reset or change the demo customer

Run from `server/`:

```bash
# Preview generated history without writing files.
.venv/bin/python scripts/load_customer.py --persona sam --months 18 --seed 7 --dry-run

# Replace the loaded customer with the configuration from server/.env.
.venv/bin/python scripts/load_customer.py

# Load a different customer with an explicit date.
.venv/bin/python scripts/load_customer.py --persona jordan --months 18 --seed 7 --end 2026-11-07
```

Loading replaces the previous customer, clears accepted rules, and rewrites ground truth. Refresh the browser afterward. To keep teammates' demos consistent, use the same persona, history length, seed, and end date. Without `DEMO_END_DATE` or `--end`, history ends on the current date and changes daily.

## Development checks

Backend tests run with fake model dependencies and isolated temporary databases:

```bash
cd server
.venv/bin/python -m pytest
```

Frontend checks, from a separate terminal at the repository root:

```bash
cd client
npm run lint
npm run build
```

For live model verification, run from `server/` after configuring the key and model IDs:

```bash
.venv/bin/python scripts/smoke_nemotron.py
.venv/bin/python scripts/rehearse.py --question "Can I afford a car?" --quick
```

The smoke test checks text, JSON, and tool-call responses. Rehearsal generates the configured customer in temporary databases, runs the real agent workflow, and flags fallback responses, missing values, and other demo issues without changing your loaded customer or accepted rules. Both commands make real model requests. Omit `--question` to rehearse all scripted questions.

## Production build and deployment

Build the frontend with `npm ci` and `npm run build` from `client/`. Then start FastAPI from `server/`:

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

When `client/dist/` exists at backend startup, FastAPI serves the built UI and API from the same process at `http://localhost:8000`. Restart the backend if the build directory was created after startup. Production dependencies are in `server/requirements.txt`.

See [DEPLOY.md](DEPLOY.md) for the EC2/systemd setup, port 80 service, backups, and update procedure. Deployment files assume the repository is at `/home/ubuntu/app`.

## Repository layout

| Path | Contents |
| --- | --- |
| `client/src/` | Dashboard, graph, forecasts, advice, and accepted-change UI. |
| `server/app/main.py` | API routes, streamed advice, and production static-file serving. |
| `server/app/agents/` | LangGraph workflow, prompts, request scrubbing, and proposal review. |
| `server/app/engine_firewall/` | Financial calculations, Monte Carlo simulation, and FactPack filtering. |
| `server/app/datagen/` | Synthetic personas and transaction-history generator. |
| `server/scripts/` | Customer loading, model smoke tests, and demo rehearsal. |
| `server/tests/` | Backend tests. |
| `deploy/` | systemd service and SQLite backup script. |
| `docs/` | Implementation plans and UI audits. |
