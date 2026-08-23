from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from crawl.stage import classify_stage, project_key


@dataclass
class Notice:
    source_id: str
    source_name: str
    title: str
    external_id: Optional[str] = None
    publish_date: Optional[str] = None
    open_time: Optional[str] = None
    deadline: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    region_text: Optional[str] = None
    keyword: Optional[str] = None
    bid_status: Optional[str] = None
    amount: Optional[float] = None
    amount_text: Optional[str] = None
    buyer: Optional[str] = None
    agency: Optional[str] = None
    project_code: Optional[str] = None
    notice_type: Optional[str] = None
    detail_url: Optional[str] = None
    official_url: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        # 稳定哈希：同一 source+external_id 不因标题微调冲突
        eid = self.external_id or ""
        if eid:
            key = f"{self.source_id}|{eid}"
        else:
            key = f"{self.source_id}|{self.title}|{self.detail_url or ''}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def ensure_external_id(self):
        if not self.external_id:
            key = f"{self.source_id}|{self.title}|{self.detail_url or ''}"
            self.external_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:32]

    def to_row(self) -> dict:
        self.ensure_external_id()
        d = asdict(self)
        raw = d.pop("raw", {}) or {}
        d["content_hash"] = self.content_hash()
        d["raw_json"] = json.dumps(raw, ensure_ascii=False) if raw else None
        stage, rank = classify_stage(self.title, self.notice_type)
        pkey, core = project_key(self.title, self.city)
        d["notice_stage"] = stage
        d["stage_rank"] = rank
        d["project_key"] = pkey
        d["project_name"] = core[:500] if core else None
        # MySQL DATETIME: accept 'YYYY-MM-DD' or full; empty -> None
        for k in ("publish_date", "open_time", "deadline"):
            v = d.get(k)
            if not v:
                d[k] = None
            else:
                d[k] = str(v).replace("T", " ")[:19]
        return d
