# Running and deploying

Everything runs from one process plus one SQLite file. No external database or bank API.

## Local
```
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp ../.env.example .env                      # then fill in NVIDIA_API_KEY later; nothing else is needed yet
.venv/bin/python scripts/load_customer.py    # generates the demo customer into data/copilot.db
.venv/bin/uvicorn app.main:app --reload --port 8000

cd client && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```
Reset the demo (also clears accepted rules): re-run `scripts/load_customer.py`.
Set `DEMO_END_DATE` in `.env` (as in `.env.example`) so reloads are identical; without it the history ends
today and the data changes daily.
Try another customer: `--persona jordan|sam`, `--months 18`, `--seed 7`. Add `--dry-run` to preview.

## EC2 (t3.small, no Docker)
1. SSH in, clone the repo, `python3 -m venv server/.venv && server/.venv/bin/pip install -r server/requirements.txt`.
2. Build the site on your laptop (`cd client && npm run build`) and copy `client/dist/` to the server.
   Building on a 2 GB box can run out of memory.
3. Copy `server/.env` over `scp` (never commit it) and run `server/.venv/bin/python server/scripts/load_customer.py`.
4. Run **one** uvicorn worker under systemd (`--workers 1`; SQLite allows a single writer):
   `ExecStart=/home/ubuntu/app/server/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`,
   `WorkingDirectory=/home/ubuntu/app/server`.
5. Caddy in front: serve `client/dist` and `reverse_proxy /api/* 127.0.0.1:8000`. Open only ports 22, 80, 443.
6. Back up `server/data/` (it holds accepted rules): EBS snapshots, or `sqlite3 data/copilot.db ".backup backup.db"`.

## Inspect the data
`sqlite3 server/data/copilot.db` then `.tables`, `select * from obligations;`. The alias lookup is in
`server/data/private.db` and should never leave the server.
