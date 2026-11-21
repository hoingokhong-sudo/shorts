"""Đọc config.yml, gộp với giá trị mặc định."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("AUTOPOST_ROOT") or Path(__file__).resolve().parent.parent)

DEFAULTS: dict = {
    "timezone": "Asia/Ho_Chi_Minh",
    "language": "vi",
    "dirs": {"clips": "clips", "state": "state", "failed": "failed"},
    "platforms": {"youtube": True, "tiktok": True, "instagram": True},
    "schedule": {
        "two_per_day_when_queue_over": 7,
        "double_days": [],
        "slots_1_per_day": ["20:00"],
        "slots_2_per_day": ["12:00", "20:00"],
        "late_window_hours": 3,
        "min_spacing_hours": 4,
        "post_immediately": True,
        "immediate_window_hours": 6,
        "quiet_hours": ["00:30", "06:30"],
        "max_attempts": 3,
        "retry_cooldown_minutes": 20,
    },
    "niche": {"keywords": [], "always_tags": []},
    "ai": {
        "enabled": True,
        "model": "auto",
        "trending_slots": 2,
        "write_caption": False,
        "extra_instructions": "",
    },
    "trending": {
        "enabled": True,
        "region": "VN",
        "youtube_category_id": "",
        "google_trends": True,
    },
    "social": {"enabled": False, "heading": "", "links": {}, "donate": "", "donate_on": ["youtube", "instagram"]},
    "hosting": {"mode": "pages", "public_base_url": "", "wait_minutes": 8},
    "youtube": {
        "privacy": "public",
        "category_id": "22",
        "made_for_kids": False,
        "ai_generated": False,
        "add_shorts_tag": True,
    },
    "tiktok": {
        # draft  = đẩy vào hộp thư TikTok, mày mở app bấm Đăng (không cần tài khoản riêng tư)
        # direct = đăng thẳng qua API (app chưa audit: bài SELF_ONLY và tài khoản phải để riêng tư)
        # manual = không gọi API, chỉ gửi caption + link clip để mày tự up
        "mode": "draft",
        "privacy": "SELF_ONLY",
        "disable_comment": False,
        "disable_duet": False,
        "disable_stitch": False,
        "ai_generated": False,
        "cover_ms": 1000,
    },
    "instagram": {"api_version": "", "share_to_feed": True},
    "limits": {"hashtags_youtube": 3, "hashtags_tiktok": 5, "hashtags_instagram": 5},
    "checks": {"min_seconds": 5, "warn_over_seconds": 90, "max_seconds": 180, "max_mb": 95},
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | os.PathLike | None = None) -> dict:
    p = Path(path) if path else ROOT / "config.yml"
    data = {}
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return _merge(DEFAULTS, data)
