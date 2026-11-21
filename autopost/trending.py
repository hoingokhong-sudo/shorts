"""Gom tag/từ khoá đang lên ở Việt Nam từ nguồn miễn phí. Mọi nguồn đều tuỳ chọn, lỗi thì bỏ qua.

Nguồn:
- YouTube "Trending" (videos.list chart=mostPopular, regionCode=VN)
- Google Trends RSS (geo=VN)
TikTok Creative Center không có API công khai nên không scrape (dễ vỡ, vi phạm điều khoản).
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

from . import net

TAG_RE = re.compile(r"#([^\W_][\w]{1,29})", re.UNICODE)
STOP = {"shorts", "short", "video", "viral", "fyp", "foryou", "foryoupage", "xuhuong", "trending", "youtube", "tiktok", "reels"}


def youtube_trending(cfg: dict, access_token: str | None, api_key: str | None) -> list[str]:
    t = cfg["trending"]
    if not (access_token or api_key):
        return []
    params = {"part": "snippet", "chart": "mostPopular", "regionCode": t["region"], "maxResults": 50}
    if t.get("youtube_category_id"):
        params["videoCategoryId"] = str(t["youtube_category_id"])
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    else:
        params["key"] = api_key
    try:
        r = net.request("GET", "https://www.googleapis.com/youtube/v3/videos", params=params, headers=headers, retries=1)
        if r.status_code != 200:
            print(f"[trending] YouTube trending HTTP {r.status_code}, bỏ qua", file=sys.stderr)
            return []
        cnt: Counter = Counter()
        for it in r.json().get("items", []):
            sn = it.get("snippet", {})
            for tag in TAG_RE.findall((sn.get("title") or "") + " " + (sn.get("description") or "")[:600]):
                cnt[tag.lower()] += 2
            for tag in (sn.get("tags") or [])[:8]:
                tag = re.sub(r"[^\w]", "", tag, flags=re.UNICODE).lower()
                if 2 <= len(tag) <= 30:
                    cnt[tag] += 1
        return [f"#{t}" for t, _ in cnt.most_common(60) if t not in STOP and not t.isdigit()][:40]
    except Exception as e:  # noqa: BLE001
        print(f"[trending] YouTube lỗi: {e}", file=sys.stderr)
        return []


def google_trends(geo: str = "VN") -> list[str]:
    try:
        r = net.request("GET", "https://trends.google.com/trending/rss", params={"geo": geo}, retries=1, timeout=20)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        return [(i.findtext("title") or "").strip() for i in root.iter("item") if (i.findtext("title") or "").strip()][:25]
    except Exception as e:  # noqa: BLE001
        print(f"[trending] Google Trends lỗi: {e}", file=sys.stderr)
        return []


def collect(cfg: dict, access_token: str | None = None, api_key: str | None = None) -> dict:
    if not cfg["trending"]["enabled"]:
        return {"hashtags": [], "keywords": []}
    return {
        "hashtags": youtube_trending(cfg, access_token, api_key),
        "keywords": google_trends(cfg["trending"]["region"]) if cfg["trending"]["google_trends"] else [],
    }
