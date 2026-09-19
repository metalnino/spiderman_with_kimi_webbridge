from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402

from crawl.models import Notice


UPSERT_SQL = """
INSERT INTO notices (
  source_id, source_name, external_id, title, publish_date, open_time, deadline,
  province, city, region_text, keyword, bid_status, amount, amount_text,
  buyer, agency, project_code, notice_type, detail_url, official_url,
  raw_json, content_hash, notice_stage, stage_rank, project_key, project_name
) VALUES (
  %(source_id)s, %(source_name)s, %(external_id)s, %(title)s, %(publish_date)s,
  %(open_time)s, %(deadline)s, %(province)s, %(city)s, %(region_text)s,
  %(keyword)s, %(bid_status)s, %(amount)s, %(amount_text)s, %(buyer)s,
  %(agency)s, %(project_code)s, %(notice_type)s, %(detail_url)s, %(official_url)s,
  %(raw_json)s, %(content_hash)s, %(notice_stage)s, %(stage_rank)s, %(project_key)s, %(project_name)s
)
ON DUPLICATE KEY UPDATE
  title=VALUES(title),
  publish_date=VALUES(publish_date),
  province=VALUES(province),
  city=IFNULL(VALUES(city), city),
  region_text=VALUES(region_text),
  keyword=VALUES(keyword),
  amount=IFNULL(VALUES(amount), amount),
  amount_text=IFNULL(VALUES(amount_text), amount_text),
  buyer=IFNULL(VALUES(buyer), buyer),
  agency=IFNULL(VALUES(agency), agency),
  detail_url=IFNULL(VALUES(detail_url), detail_url),
  official_url=IFNULL(VALUES(official_url), official_url),
  notice_stage=VALUES(notice_stage),
  stage_rank=VALUES(stage_rank),
  project_key=VALUES(project_key),
  project_name=VALUES(project_name),
  raw_json=VALUES(raw_json),
  updated_at=CURRENT_TIMESTAMP
"""


def upsert_notices(notices: Iterable[Notice]) -> dict:
    rows = [n.to_row() for n in notices]
    if not rows:
        return {"attempted": 0, "affected": 0}
    conn = connect(autocommit=True)
    affected = 0
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(UPSERT_SQL, row)
                affected += cur.rowcount
    finally:
        conn.close()
    return {"attempted": len(rows), "affected": affected}


def start_run(source_id: str) -> int:
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            # 上一轮异常中断会遗留 status=running 的僵尸记录：先标记为中断，保证状态可闭环
            cur.execute(
                "UPDATE crawl_runs SET finished_at=%s, status='failed', note='orphaned: 进程中断未闭环' "
                "WHERE source_id=%s AND status='running'",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source_id),
            )
            cur.execute(
                "INSERT INTO crawl_runs (source_id, started_at, status, item_count) "
                "VALUES (%s, %s, %s, 0)",
                (source_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "running"),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def finish_run(run_id: int, *, status: str, item_count: int, note: str | None = None):
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crawl_runs SET finished_at=%s, status=%s, item_count=%s, note=%s WHERE id=%s",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    status,
                    item_count,
                    (note or "")[:500],
                    run_id,
                ),
            )
    finally:
        conn.close()


ORPHAN_NOTE = "orphaned: 进程被外部中断（未闭环），已由下轮全局清扫标记"


def sweep_orphan_runs(*, max_age_hours: float = 3.0) -> list[dict]:
    """全局兜底：把仍挂在 running、却明显不会再有进程收尾的历史行闭环，返回被清扫的行。

    为什么需要：进程被外部强杀（掉电/被 kill/任务被终结）时 finish_run 永远不执行，
    行会永久停在 running —— 台账看上去就是「卡死」，既不是站点的错也不可自证。
    实证：2026-09-19 00:39 那轮采到 jiangsu_zhaobiao 时进程被杀，行 739 一直挂着 running。
    start_run() 只在「同一个源下次再跑」时顺带清扫；若被杀的恰好是最后一个源，要等下一
    整轮（十几小时）才闭环。所以在每轮采集开始时做一次全局兜底。
    阈值默认 3 小时：本机单轮全站约 1.5~2 小时，正常在跑的源不可能挂 3 小时。
    """
    cutoff = (datetime.now() - timedelta(hours=max_age_hours)).strftime("%Y-%m-%d %H:%M:%S")
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, started_at FROM crawl_runs "
                "WHERE status='running' AND started_at < %s ORDER BY id",
                (cutoff,),
            )
            rows = cur.fetchall() or []
            if not rows:
                return []
            ids = [int(r["id"]) for r in rows]
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                "UPDATE crawl_runs SET finished_at=%s, status='failed', note=%s WHERE id IN (" + placeholders + ")",
                tuple([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ORPHAN_NOTE] + ids),
            )
        return [
            {"id": int(r["id"]), "source_id": r["source_id"], "started_at": str(r["started_at"])}
            for r in rows
        ]
    finally:
        conn.close()


def count_notices(source_id: str | None = None) -> int:
    conn = connect()
    try:
        with conn.cursor() as cur:
            if source_id:
                cur.execute("SELECT COUNT(*) AS c FROM notices WHERE source_id=%s", (source_id,))
            else:
                cur.execute("SELECT COUNT(*) AS c FROM notices")
            return int(cur.fetchone()["c"])
    finally:
        conn.close()
