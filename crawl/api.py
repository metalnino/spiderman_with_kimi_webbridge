"""FastAPI ledger API. Read-only GET + captcha POST. Serves ledger_app.html.

Replaces the stdlib http.server version (crawl/ledger_server.py).
API contract kept unchanged so the front-end needs no modification.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import ledger_data as data  # noqa: E402
from crawl.actions import trigger_crawl, update_notice_lead  # noqa: E402
from crawl.backfill import backfill_notice  # noqa: E402
from crawl.captcha_flow import open_for_human, resolve_todo  # noqa: E402
from crawl.keywords import add_keyword, delete_keyword, set_keyword_enabled, sync_config_keywords  # noqa: E402

SHELL = ROOT / "data" / "web" / "ledger_app.html"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

app = FastAPI(title="绿植招采运营台 API", version="1.0", description="本机只读台账 + 验证码人工解")


class CaptchaPayload(BaseModel):
    id: int | None = None
    todo_id: int | None = None
    cookie: str | None = None
    note: str | None = None


def _todo_id(p: CaptchaPayload) -> int:
    return int(p.id or p.todo_id or 0)


@app.get("/")
@app.get("/index.html")
@app.get("/ledger")
@app.get("/dashboard.html")
def index():
    if not SHELL.exists():
        return JSONResponse(status_code=500, content={"ok": False, "error": "shell_missing", "path": str(SHELL)})
    return FileResponse(SHELL, media_type="text/html")


@app.get("/api/health")
def health():
    from crawl.sources import source_config_drift

    return {
        "ok": True,
        "mode": "localhost_ledger",
        "bind": os.environ.get("LEDGER_HOST", DEFAULT_HOST),
        "source_config_drift": source_config_drift(),
        "write_allow": [
            "/api/captcha/open",
            "/api/captcha/done",
            "/api/notices/{id}/backfill",
        ],
    }


@app.get("/api/meta")
def meta():
    return data.meta()


@app.get("/api/summary")
def summary():
    return data.summary()


@app.get("/api/notices")
def notices(
    source_id: str | None = None,
    province: str | None = None,
    city: str | None = None,
    clean_status: str | None = None,
    only_pass: bool = False,
    q: str | None = None,
    lead_status: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    sort: str = "publish",
    limit: int = 50,
    offset: int = 0,
    target_only: bool = False,
    stage: str | None = None,
    actionable: bool = False,
):
    return data.notices(
        source_id=source_id,
        province=province,
        city=city,
        clean_status=clean_status,
        only_pass=only_pass,
        q=q,
        lead_status=lead_status,
        amount_min=amount_min,
        amount_max=amount_max,
        sort=sort,
        limit=limit,
        offset=offset,
        target_only=target_only,
        stage=stage,
        actionable=actionable,
    )


@app.get("/api/notices/export")
def notices_export(
    source_id: str | None = None,
    province: str | None = None,
    city: str | None = None,
    clean_status: str | None = None,
    only_pass: bool = False,
    q: str | None = None,
    lead_status: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    sort: str = "publish",
    target_only: bool = False,
    stage: str | None = None,
    actionable: bool = False,
):
    csv_text = data.export_csv(
        source_id=source_id, province=province, city=city, clean_status=clean_status,
        only_pass=only_pass, q=q, lead_status=lead_status,
        amount_min=amount_min, amount_max=amount_max, sort=sort, target_only=target_only,
        stage=stage, actionable=actionable,
    )
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=notices.csv"},
    )


@app.get("/api/notices/{notice_id}")
def notice_detail(notice_id: int):
    out = data.notice_detail(notice_id)
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    return out


@app.post("/api/notices/{notice_id}/backfill")
def notice_backfill(notice_id: int):
    out = backfill_notice(notice_id)
    return JSONResponse(status_code=200 if out.get("ok") else 400, content=out)


@app.get("/api/notices/{notice_id}/tenderfile")
def notice_tenderfile(notice_id: int):
    rel = data.tenderfile_path_for(notice_id)
    if not rel:
        return JSONResponse(status_code=404, content={"ok": False, "error": "no_tenderfile"})
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT.resolve())):
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad_path"})
    if not p.is_file():
        return JSONResponse(status_code=404, content={"ok": False, "error": "file_missing"})
    return FileResponse(p)


@app.post("/api/notices/{notice_id}/lead")
def notice_lead(notice_id: int, payload: dict = Body(default={})):
    out = update_notice_lead(
        notice_id,
        read=bool(payload.get("read")),
        lead_status=payload.get("lead_status"),
        amount_status=payload.get("amount_status"),
        remark=payload.get("remark"),
    )
    return JSONResponse(status_code=200 if out.get("ok") else 400, content=out)


@app.post("/api/crawl/run")
def crawl_run(payload: dict = Body(default={})):
    try:
        pages = int(payload.get("pages") or 1)
    except (TypeError, ValueError):
        pages = 1
    sources = payload.get("sources")
    if isinstance(sources, str):
        sources = [s for s in sources.split(",") if s]
    out = trigger_crawl(pages=pages, sources=sources or None)
    return JSONResponse(status_code=200 if out.get("ok") else 400, content=out)


@app.post("/api/keywords")
def keyword_add(payload: dict = Body(default={})):
    return add_keyword(payload.get("keyword") or "")


@app.post("/api/keywords/{kw}/toggle")
def keyword_toggle(kw: str, payload: dict = Body(default={})):
    enabled = bool(payload.get("enabled", True))
    set_keyword_enabled(kw, enabled)
    sync_config_keywords()
    return {"ok": True, "keyword": kw, "enabled": enabled}


@app.delete("/api/keywords/{kw}")
def keyword_delete(kw: str):
    return delete_keyword(kw)


@app.get("/api/runs")
def runs(limit: int = 40):
    return data.runs(limit=limit)


@app.get("/api/clean/stats")
def clean_stats():
    return data.clean_stats()


@app.get("/api/keywords")
def keywords():
    return data.keywords()


@app.get("/api/captcha")
def captcha(limit: int = 40):
    return data.captcha(limit=limit)


@app.get("/api/entities")
def entities(limit: int = 100):
    return data.entities(limit=limit)


@app.post("/api/captcha/open")
def captcha_open(payload: CaptchaPayload):
    todo_id = _todo_id(payload)
    if todo_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad_id"})
    out = open_for_human(todo_id)
    return JSONResponse(status_code=200 if out.get("ok") else 400, content=out)


@app.post("/api/captcha/done")
def captcha_done(payload: CaptchaPayload):
    todo_id = _todo_id(payload)
    if todo_id <= 0:
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad_id"})
    out = resolve_todo(todo_id, cookie_header=payload.cookie, note=payload.note)
    return JSONResponse(status_code=200 if out.get("ok") else 400, content=out)
