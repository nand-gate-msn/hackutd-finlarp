#!/usr/bin/env bash
# Daily SQLite backup. Keeps the last 14. Install: crontab -e ->
#   0 3 * * * /home/ubuntu/app/deploy/backup.sh
set -euo pipefail
DATA=/home/ubuntu/app/server/data
OUT=/home/ubuntu/backups
mkdir -p "$OUT"
stamp=$(date +%F)
for db in copilot private; do
  sqlite3 "$DATA/$db.db" ".backup '$OUT/$db-$stamp.db'"
done
ls -1t "$OUT"/copilot-*.db | tail -n +15 | xargs -r rm
ls -1t "$OUT"/private-*.db | tail -n +15 | xargs -r rm
