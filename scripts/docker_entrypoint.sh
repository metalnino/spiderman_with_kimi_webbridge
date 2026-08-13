#!/bin/sh
set -e
cd /app

echo "[entry] migrate ops tables..."
python scripts/migrate_ops.py || echo "[entry] migrate_ops warn (continue)"

echo "[entry] start ledger on ${LEDGER_HOST:-0.0.0.0}:${LEDGER_PORT:-8765}"
python scripts/jobs/serve_ledger.py --host "${LEDGER_HOST:-0.0.0.0}" --port "${LEDGER_PORT:-8765}" &
LEDGER_PID=$!

# 可选：启动后先跑一轮增量（CRAWL_ON_START=1）
if [ "${CRAWL_ON_START:-0}" = "1" ]; then
  echo "[entry] crawl once on start..."
  python scripts/jobs/run_incremental.py --pages "${CRAWL_PAGES:-1}" || true
fi

HOURS="${CRAWL_INTERVAL_HOURS:-2}"
echo "[entry] scheduler loop every ${HOURS}h (ledger pid=${LEDGER_PID})"
exec python -c "
from crawl.scheduler import start_interval_loop
import os
start_interval_loop(hours=float(os.environ.get('CRAWL_INTERVAL_HOURS','2')))
"
