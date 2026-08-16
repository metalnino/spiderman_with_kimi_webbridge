#!/bin/sh
set -e
cd /app

# 强制容器内上海时区（定时 8/12/18/22 以此为准）
export TZ="${TZ:-Asia/Shanghai}"

echo "[entry] migrate ops tables..."
python scripts/migrate_ops.py || echo "[entry] migrate_ops warn (continue)"

echo "[entry] start ledger on ${LEDGER_HOST:-0.0.0.0}:${LEDGER_PORT:-8765}"
python scripts/jobs/serve_ledger.py --host "${LEDGER_HOST:-0.0.0.0}" --port "${LEDGER_PORT:-8765}" &
LEDGER_PID=$!

# 可选：启动后先跑一轮增量（CRAWL_ON_START=1）
if [ "${CRAWL_ON_START:-0}" = "1" ]; then
  echo "[entry] crawl once on start..."
  python scripts/jobs/run_incremental.py --pages "${CRAWL_PAGES:-1}" || true
  python scripts/jobs/build_crm_db.py || true
fi

SLOTS="${CRAWL_CRON_HOURS:-8,12,18,22}"
echo "[entry] scheduler cron hours=${SLOTS} TZ=${TZ} (ledger pid=${LEDGER_PID})"
exec python -c "
from crawl.scheduler import start_cron_loop, parse_slots
import os
slots = parse_slots(os.environ.get('CRAWL_CRON_HOURS', '8,12,18,22'))
start_cron_loop(slots, run_immediately=False)
"
