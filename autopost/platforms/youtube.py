"""YouTube Shorts qua YouTube Data API v3 (resumable upload, chỉ dùng requests)."""
from __future__ import annotations

import re
from pathlib import Path

from .. import net
from .base import Job, PlatformError, Result

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 16 * 1024 * 1024  # bội số của 256KiB như API yêu cầu


class YouTube:
    name = "youtube"

    def __init__(self, cfg, tokens, env):
        self.cfg, self.tokens, self.env = cfg, tokens, env
        self._access = None

    def configured(self) -> bool:
        return all(self.env.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))

    def access_token(self) -> str:
        if self._access:
            return self._access
        r = net.request(
            "POST",
            TOKEN_URL,
            data={
                "client_id": self.env["YT_CLIENT_ID"],
                "client_secret": self.env["YT_CLIENT_SECRET"],
                "refresh_token": self.env["YT_REFRESH_TOKEN"],
                "grant_type": "refresh_token",
            },
        )
        j = _json(r)
        if r.status_code != 200 or "access_token" not in j:
            err = j.get("error_description") or j.get("error") or r.text[:200]
            hint = ""
            if j.get("error") == "invalid_grant":
                hint = " (refresh token hết hạn/bị thu hồi: nếu app Google ở chế độ Testing thì token chỉ sống 7 ngày, hãy Publish app rồi chạy lại setup)"
            raise PlatformError(f"YouTube không lấy được access token: {err}{hint}", retryable=False)
        self._access = j["access_token"]
        return self._access

    def publish(self, job: Job) -> Result:
        cfg, yt = self.cfg, self.cfg["youtube"]
        txt = job.meta["text"]["youtube"]
        tags = [t.lstrip("#") for t in job.meta["tags"]["youtube"]]
        body = {
            "snippet": {
                "title": re.sub(r"[<>]", "", txt["title"])[:100],
                "description": txt["description"][:4900],
                "tags": tags[:15],
                "categoryId": str(yt["category_id"]),
                "defaultLanguage": cfg["language"],
                "defaultAudioLanguage": cfg["language"],
            },
            "status": {
                "privacyStatus": yt["privacy"],
                "selfDeclaredMadeForKids": bool(yt["made_for_kids"]),
                "containsSyntheticMedia": bool(yt["ai_generated"]),
                "embeddable": True,
                "publicStatsViewable": True,
            },
        }
        path: Path = job.path
        size = path.stat().st_size
        ctype = "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"
        token = self.access_token()
        r = net.request(
            "POST",
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "true"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": ctype,
            },
            json=body,
        )
        if r.status_code in (401, 403):
            msg = _json(r).get("error", {}).get("message", r.text[:200])
            raise PlatformError(f"YouTube từ chối ({r.status_code}): {msg}", retryable=False)
        if r.status_code != 200 or not r.headers.get("Location"):
            raise PlatformError(f"YouTube khởi tạo upload lỗi {r.status_code}: {r.text[:300]}")
        session = r.headers["Location"]

        resp = self._upload(session, path, size, ctype)
        vid = resp.get("id")
        if not vid:
            raise PlatformError(f"YouTube trả về không có id: {str(resp)[:200]}")
        res = Result(id=vid, url=f"https://www.youtube.com/shorts/{vid}")
        got = (resp.get("status") or {}).get("privacyStatus")
        if got and got != yt["privacy"]:
            res.warnings.append(f"YouTube đặt video ở chế độ '{got}' dù yêu cầu '{yt['privacy']}', vào YouTube Studio chỉnh sang Công khai")
        return res

    def _upload(self, session: str, path: Path, size: int, ctype: str) -> dict:
        sent = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                end = sent + len(chunk) - 1
                r = None
                for attempt in range(4):
                    r = net.request(
                        "PUT",
                        session,
                        headers={"Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{end}/{size}", "Content-Type": ctype},
                        data=chunk,
                        timeout=300,
                        retries=0,
                    )
                    if r.status_code in (200, 201, 308):
                        break
                    if r.status_code in (500, 502, 503, 504):
                        continue
                    raise PlatformError(f"YouTube upload lỗi {r.status_code}: {r.text[:300]}")
                else:
                    raise PlatformError(f"YouTube upload lỗi {r.status_code} sau nhiều lần thử")
                if r.status_code in (200, 201):
                    return _json(r)
                sent = end + 1
                if sent >= size:
                    raise PlatformError("YouTube nhận đủ dữ liệu nhưng chưa trả kết quả")


def _json(r) -> dict:
    try:
        j = r.json()
        return j if isinstance(j, dict) else {}
    except ValueError:
        return {}
