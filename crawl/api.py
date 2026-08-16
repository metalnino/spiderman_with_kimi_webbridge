"""FastAPI ledger API. Read-only GET + captcha POST. Serves ledger_app.html.

Replaces the stdlib http.server version (crawl/ledger_server.py).
API contract kept unchanged so the front-end needs no modification.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import ledger_data as data  # noqa: E402
from crawl.captcha_flow import open_for_human, resolve_todo  # noqa: E402

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
    return {
        "ok": True,
        "mode": "localhost_ledger",
        "bind": os.environ.get("LEDGER_HOST", DEFAULT_HOST),
        "write_allow": ["/api/captcha/open", "/api/captcha/done"],
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
    limit: int = 50,
    offset: int = 0,
):
    return data.notices(
        source_id=source_id,
        province=province,
        city=city,
        clean_status=clean_status,
        only_pass=only_pass,
        q=q,
        limit=limit,
        offset=offset,
    )


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
