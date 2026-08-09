from __future__ import annotations

from dataclasses import dataclass

from crawl.config_loader import load_json


@dataclass
class CleanResult:
    decision: str  # pass | drop | review
    reason: str


def _filter_cfg() -> dict:
    return load_json("config/relevance_filter.json")


def clean_title(title: str) -> CleanResult:
    cfg = _filter_cfg()
    title = title or ""
    positives = cfg.get("positive_stems") or []
    negatives = cfg.get("negative_terms") or []
    for neg in negatives:
        if neg and neg in title:
            return CleanResult("drop", f"negative:{neg}")
    if cfg.get("require_positive_stem", True):
        if not any(p in title for p in positives):
            return CleanResult("drop", "no_positive_stem")
    return CleanResult("pass", "ok")


def clean_notice(title: str, manual_label: str | None = None) -> CleanResult:
    if manual_label == "irrelevant":
        return CleanResult("drop", "manual:irrelevant")
    if manual_label == "relevant":
        return CleanResult("pass", "manual:relevant")
    return clean_title(title)
