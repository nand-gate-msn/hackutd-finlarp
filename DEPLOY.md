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

## EC2 (t3.small, Ubuntu, no Docker, no proxy)
One uvicorn process serves both the API and the built React app (`client/dist`), directly on port 80.
Security group: inbound 22, 80 only (add 443 later if you put Caddy in front for a domain).

1. On the box: `sudo apt update && sudo apt install -y python3-venv sqlite3 git`
2. `git clone <repo> ~/app && cd ~/app && git checkout agentic-workflow`
3. `python3 -m venv server/.venv && server/.venv/bin/pip install -r server/requirements.txt`
4. Fresh env file (never reuse an old one): `cp .env.example server/.env`, set `DEMO_PERSONA=alex`,
   `DEMO_END_DATE=2026-11-07`. `FRONTEND_ORIGIN` can stay as is (same origin in production).
5. `cd server && .venv/bin/python scripts/load_customer.py`
6. On your laptop: `cd client && npm run build && scp -r dist ubuntu@<ip>:~/app/client/`
   (building on a 2 GB box can run out of memory).
7. `sudo cp ~/app/deploy/finlarp.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now finlarp`
8. Backup: `chmod +x ~/app/deploy/backup.sh`, then `crontab -e` and add `0 3 * * * /home/ubuntu/app/deploy/backup.sh`.
9. Check: `curl http://<ip>/health` -> `{"status":"ok","data_loaded":true}`, then open `http://<ip>/` in a browser.

Update later: `git pull`, rebuild/`scp` the client if it changed, `sudo systemctl restart finlarp`.
Logs: `journalctl -u finlarp -f`.

## Inspect the data
`sqlite3 server/data/copilot.db` then `.tables`, `select * from obligations;`. The alias lookup is in
`server/data/private.db` and should never leave the server.
