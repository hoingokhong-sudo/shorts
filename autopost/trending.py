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
from datetime import datetime, timedelta, timezone
from math import log10

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


# tag quá rộng: không dùng làm từ khoá tìm kiếm (kết quả sẽ lạc đề)
BROAD = {"game", "games", "gaming", "gamer", "livestream", "stream", "highlight", "highlights"}
GENERIC = STOP | {"shortvideo", "youtubeshorts", "ytshorts", "xuhuongtiktok", "xuhuongyoutube", "viralvideo", "viralshorts", "trend"}


def related_tags(cfg: dict, user_tags: list[str], access_token: str | None, api_key: str | None) -> list[str]:
    """Hashtag đang được dùng ở video mới + nhiều view cùng chủ đề với tag của mày.

    Chỉ lấy tag có thật, xuất hiện ở ít nhất 2 kênh khác nhau. Mỗi từ khoá tốn ~202 quota (free 10.000/ngày).
    """
    if not (access_token or api_key):
        return []
    words = [t.lstrip("#") for t in user_tags if t.lstrip("#").lower() not in GENERIC]
    seeds = [w for w in words if w.lower() not in BROAD][:3] or words[:1]
    if not seeds:
        return []
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    auth = {} if access_token else {"key": api_key}
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    api = "https://www.googleapis.com/youtube/v3"
    own = {t.lstrip("#").lower() for t in user_tags}
    score: Counter = Counter()
    channels: dict[str, set] = {}
    try:
        ids: list[str] = []
        for seed, order in [(s, o) for s in seeds for o in ("viewCount", "relevance")]:
            r = net.request("GET", f"{api}/search", headers=headers, retries=1, params={
                "part": "id", "type": "video", "q": f"#{seed}", "order": order, "publishedAfter": since,
                "regionCode": cfg["trending"]["region"], "relevanceLanguage": cfg["language"], "maxResults": 50, **auth})
            if r.status_code != 200:
                print(f"[trending] tìm '{seed}' HTTP {r.status_code}, bỏ qua", file=sys.stderr)
                continue
            ids += [i["id"]["videoId"] for i in r.json().get("items", []) if i["id"]["videoId"] not in ids]
        for start in range(0, len(ids), 50):
            r = net.request("GET", f"{api}/videos", headers=headers, retries=1,
                            params={"part": "snippet,statistics", "id": ",".join(ids[start:start + 50]), **auth})
            if r.status_code != 200:
                continue
            for it in r.json().get("items", []):
                sn = it.get("snippet", {})
                found = {t.lower() for t in TAG_RE.findall((sn.get("title") or "") + " " + (sn.get("description") or "")[:800])}
                weight = log10(int(it.get("statistics", {}).get("viewCount", 0)) + 10)
                for t in found:
                    score[t] += weight
                    channels.setdefault(t, set()).add(sn.get("channelId"))
    except Exception as e:  # noqa: BLE001
        print(f"[trending] tag liên quan lỗi: {e}", file=sys.stderr)
    return [f"#{t}" for t, _ in score.most_common()
            if len(channels[t]) >= 2 and t not in own and t not in GENERIC and not t.isdigit()][:20]


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
