"""Tạo tiêu đề, caption, hashtag cho từng nền tảng.

- Có GEMINI_API_KEY: Gemini (free tier) viết caption và chọn tag trending hợp với clip.
- Không có / lỗi: luật cơ bản (tag của mày + tag niche + tag trending khớp niche).
Tag của mày luôn được ưu tiên giữ, AI chỉ chiếm `ai.trending_slots` chỗ trong giới hạn từng nền tảng.
"""
from __future__ import annotations

import json
import re
import sys

from . import clips as C
from . import net

GEMINI = "https://generativelanguage.googleapis.com/v1beta"
SKIP_MODEL = ("image", "tts", "audio", "live", "embedding", "robotics", "computer", "imagen", "veo", "gemma", "thinking", "learnlm")


def norm_tag(t: str) -> str | None:
    t = re.sub(r"[^\w]", "", str(t).lstrip("#"), flags=re.UNICODE)
    return f"#{t}" if 2 <= len(t) <= 30 and not t.isdigit() else None


def dedupe(tags) -> list[str]:
    seen, out = set(), []
    for t in tags:
        n = norm_tag(t)
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def pick_model(key: str, pref: str = "auto") -> list[str]:
    """Danh sách model thử lần lượt. Tự dò vì tên model Gemini đổi liên tục."""
    if pref and pref != "auto":
        return [pref]
    try:
        r = net.request("GET", f"{GEMINI}/models", params={"pageSize": 200}, headers={"x-goog-api-key": key}, retries=1)
        names = []
        for m in r.json().get("models", []):
            n = m["name"].split("/")[-1]
            if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n and not any(s in n for s in SKIP_MODEL):
                names.append(n)

        def rank(n: str):
            ver = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", n)[:1]] or [0]
            return (0 if "lite" in n else 1, 1 if ("preview" in n or "exp" in n) else 0, -ver[0], n)

        return sorted(names, key=rank)[:4]
    except Exception as e:  # noqa: BLE001
        print(f"[ai] không liệt kê được model: {e}", file=sys.stderr)
        return []


PROMPT = """Mày là người làm content short-form (TikTok, Instagram Reels, YouTube Shorts) cho thị trường Việt Nam.
Viết nội dung đăng cho 1 clip.

Thông tin clip:
- Tên file: {name}
- Tiêu đề do chủ clip đặt: {title}
- Ghi chú của chủ clip: {note}
- Tag chủ clip đã chọn (giữ nguyên, ưu tiên cao nhất): {user_tags}
- Ngách/từ khoá kênh: {niche}

Ứng viên đang lên ở Việt Nam (chỉ chọn nếu THẬT SỰ liên quan nội dung clip, không ép):
- Hashtag trending: {trend_tags}
- Từ khoá Google Trends: {trend_kw}

Yêu cầu:
- Ngôn ngữ: tiếng Việt tự nhiên, ngắn, không sáo rỗng, không nói quá sự thật về nội dung clip.
- title: tối đa 70 ký tự, có hook, chứa từ khoá chính ở đầu. Không hashtag trong title.
- caption: 1-2 câu ngắn (tối đa 220 ký tự), câu đầu là hook, câu cuối là câu hỏi mở để kéo bình luận. Không hashtag trong caption.
- hashtags: danh sách xếp theo độ ưu tiên, tối đa 10, bắt đầu bằng toàn bộ tag chủ clip (nếu có), sau đó là {slots} tag thêm vào (ưu tiên trending liên quan, nếu không có thì tag ngách cụ thể). Không dùng tag chung chung vô nghĩa như #fyp #viral #xuhuong.
- Không bịa tag trending không có trong danh sách nếu nó không liên quan.
{extra}
Chỉ trả JSON đúng dạng: {{"title": "...", "caption": "...", "hashtags": ["#a", "#b"]}}"""


def _gemini(cfg: dict, key: str, prompt: str) -> dict | None:
    for model in pick_model(key, cfg["ai"]["model"]):
        try:
            r = net.request(
                "POST",
                f"{GEMINI}/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
                },
                retries=1,
                timeout=90,
            )
            if r.status_code != 200:
                print(f"[ai] {model} HTTP {r.status_code}: {r.text[:160]}", file=sys.stderr)
                continue
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
            data = json.loads(txt)
            if isinstance(data, list) and data:
                data = data[0]
            if isinstance(data, dict) and data.get("caption") is not None:
                return data
        except Exception as e:  # noqa: BLE001
            print(f"[ai] {model} lỗi: {e}", file=sys.stderr)
    return None


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0].rstrip(",.;:-") + "…"


def build(cfg: dict, name: str, sidecar: dict, trending: dict, gemini_key: str | None, use_ai: bool = True) -> dict:
    """Trả về meta: title, caption, tags theo nền tảng, text hoàn chỉnh theo nền tảng."""
    niche_kw = cfg["niche"]["keywords"]
    always = dedupe(cfg["niche"]["always_tags"])
    user = dedupe(sidecar["tags"])
    stem = name.rsplit(".", 1)[0]
    title = sidecar["title"] or C.prettify(stem)
    ai = None
    if use_ai and cfg["ai"]["enabled"] and gemini_key:
        ai = _gemini(
            cfg,
            gemini_key,
            PROMPT.format(
                name=stem,
                title=sidecar["title"] or "(không có)",
                note=sidecar["note"] or "(không có)",
                user_tags=" ".join(user) or "(không có)",
                niche=", ".join(niche_kw) or "(chưa khai báo)",
                trend_tags=" ".join(trending.get("hashtags", [])[:40]) or "(không lấy được)",
                trend_kw=", ".join(trending.get("keywords", [])[:20]) or "(không lấy được)",
                slots=cfg["ai"]["trending_slots"],
                extra=cfg["ai"]["extra_instructions"],
            ),
        )
    if ai:
        ai_title = _clip(str(ai.get("title") or ""), 70)
        title = sidecar["title"] or ai_title or title
        caption = _clip(str(ai.get("caption") or ""), 220)
        extra_tags = dedupe(ai.get("hashtags") or [])
        source = "gemini"
    else:
        caption = _clip(sidecar["note"], 220) or title
        # fallback: tag trending khớp niche hoặc khớp tag/tên clip
        words = {w.lower() for w in re.findall(r"\w+", stem + " " + sidecar["note"], flags=re.UNICODE) if len(w) > 2}
        words |= {k.lower() for k in niche_kw}
        extra_tags = [t for t in trending.get("hashtags", []) if any(w in t.lower() for w in words)]
        source = "rule"

    def merge(limit: int) -> list[str]:
        slots = min(cfg["ai"]["trending_slots"], limit)
        pool_extra = [t for t in dedupe(extra_tags + always) if t.lower() not in {u.lower() for u in user}]
        keep_user = user[: max(limit - min(slots, len(pool_extra)), 0)]
        out = keep_user + pool_extra
        out = dedupe(out)[:limit]
        if len(out) < limit:  # còn chỗ thì bù tag của mày
            out = dedupe(out + user)[:limit]
        return out

    L = cfg["limits"]
    tags = {"youtube": merge(L["hashtags_youtube"]), "tiktok": merge(L["hashtags_tiktok"]), "instagram": merge(L["hashtags_instagram"])}
    yt_tags = list(tags["youtube"])
    if cfg["youtube"]["add_shorts_tag"] and "#shorts" not in {t.lower() for t in yt_tags}:
        yt_tags.append("#Shorts")
    text = {
        "youtube": {"title": _clip(title, 95), "description": (caption + "\n\n" + " ".join(yt_tags)).strip()},
        "tiktok": _clip_total(caption, tags["tiktok"], 2200),
        "instagram": _clip_total(caption, tags["instagram"], 2200, sep="\n\n"),
    }
    return {"title": title, "caption": caption, "tags": tags, "text": text, "source": source}


def _clip_total(caption: str, tags: list[str], limit: int, sep: str = " ") -> str:
    s = (caption + sep + " ".join(tags)).strip()
    return s if len(s) <= limit else s[:limit]
