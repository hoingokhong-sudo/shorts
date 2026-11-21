"""State dạng JSON, commit lại vào repo sau mỗi lần chạy."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EMPTY = {"version": 1, "clips": {}, "posts": [], "history": [], "credit_until": None}


def load(path: Path) -> dict:
    if path.exists():
        try:
            st = json.loads(path.read_text(encoding="utf-8"))
            for k, v in EMPTY.items():
                st.setdefault(k, type(v)() if isinstance(v, (dict, list)) else v)
            return st
        except json.JSONDecodeError:
            raise SystemExit(f"{path} bị hỏng JSON, sửa tay hoặc xoá rồi chạy lại")
    return json.loads(json.dumps(EMPTY))


def save(path: Path, st: dict) -> None:
    st["posts"] = st["posts"][-120:]
    st["history"] = st["history"][-200:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
