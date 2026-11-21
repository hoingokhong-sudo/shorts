"""TikTok Content Posting API.

mode:
  draft  - /inbox/video/init: clip vào hộp thư TikTok, mày mở app bấm Đăng (API không nhận caption ở chế độ này,
           nên caption được gửi kèm thông báo để dán).
  direct - /video/init: đăng thẳng kèm caption. App chưa audit => SELF_ONLY và tài khoản phải để riêng tư.
  manual - không gọi API.
Refresh token của TikTok bị XOAY VÒNG mỗi lần refresh nên luôn lưu lại bản mới vào TokenStore.
"""
from __future__ import annotations

import time

from .. import net
from .base import Job, PlatformError, Result

API = "https://open.tiktokapis.com/v2"
SINGLE_MAX = 64 * 1024 * 1024
BIG_CHUNK = 32 * 1024 * 1024


def plan_chunks(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) theo quy tắc TikTok: chunk 5-64MB, chunk cuối tối đa 128MB."""
    if size <= SINGLE_MAX:
        return size, 1
    return BIG_CHUNK, size // BIG_CHUNK


class TikTok:
    name = "tiktok"

    def __init__(self, cfg, tokens, env, sleep=None):
        self.cfg, self.tokens, self.env, self._sleep = cfg, tokens, env, sleep
        self.mode = cfg["tiktok"]["mode"]
        self._access = None

    def sleep(self, s: float) -> None:
        (self._sleep or time.sleep)(s)

    def configured(self) -> bool:
        if self.mode == "manual":
            return True
        return all(self.env.get(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")) and self.tokens.enabled

    def access_token(self) -> str:
        if self._access:
            return self._access
        refresh = self.tokens.get("tiktok_refresh", "TIKTOK_REFRESH_TOKEN")
        r = net.request(
            "POST",
            f"{API}/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": self.env["TIKTOK_CLIENT_KEY"],
                "client_secret": self.env["TIKTOK_CLIENT_SECRET"],
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            retries=0,
        )
        j = _json(r)
        j = j.get("data", j) if isinstance(j.get("data"), dict) else j
        if r.status_code != 200 or "access_token" not in j:
            raise PlatformError(
                f"TikTok refresh token lỗi: {j.get('error_description') or j.get('error') or r.text[:200]}. Chạy lại tools/setup_wizard.py để cấp token mới.",
                retryable=False,
            )
        if j.get("refresh_token") and j["refresh_token"] != refresh:
            self.tokens.set("tiktok_refresh", "TIKTOK_REFRESH_TOKEN", j["refresh_token"])  # lưu NGAY
        self._access = j["access_token"]
        return self._access

    def _post(self, path: str, token: str, body: dict) -> dict:
        r = net.request(
            "POST",
            f"{API}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json=body,
        )
        j = _json(r)
        err = j.get("error") or {}
        if r.status_code != 200 or (err.get("code") not in (None, "ok")):
            code = err.get("code", r.status_code)
            msg = f"TikTok {path} lỗi {code}: {err.get('message') or r.text[:200]}"
            fatal = code in ("access_token_invalid", "scope_not_authorized", "unaudited_client_can_only_post_to_private_accounts", "url_ownership_unverified", "privacy_level_option_mismatch", "spam_risk_user_banned_from_posting")
            raise PlatformError(msg, retryable=not fatal)
        return j.get("data") or {}

    def publish(self, job: Job) -> Result:
        text = job.meta["text"]["tiktok"]
        if self.mode == "manual":
            return Result(note="manual", manual=_manual_text(job, text))
        token = self.access_token()
        size = job.path.stat().st_size
        chunk, total = plan_chunks(size)
        tk = self.cfg["tiktok"]
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}
        warnings: list[str] = []
        if self.mode == "draft":
            data = self._post("/post/publish/inbox/video/init/", token, {"source_info": source})
        else:
            info = self._post("/post/publish/creator_info/query/", token, {})
            options = info.get("privacy_level_options") or []
            privacy = tk["privacy"]
            if options and privacy not in options:
                warnings.append(f"TikTok không cho phép '{privacy}' ({options}), đổi sang '{options[-1]}'")
                privacy = "SELF_ONLY" if "SELF_ONLY" in options else options[-1]
            maxd = info.get("max_video_post_duration_sec")
            if maxd and job.info.get("duration") and job.info["duration"] > maxd:
                raise PlatformError(f"clip {job.info['duration']:.0f}s dài hơn mức TikTok cho phép ({maxd}s)", retryable=False)
            post_info = {
                "title": text[:2200],
                "privacy_level": privacy,
                "disable_comment": tk["disable_comment"],
                "disable_duet": tk["disable_duet"],
                "disable_stitch": tk["disable_stitch"],
                "video_cover_timestamp_ms": int(tk["cover_ms"]),
                "is_aigc": bool(tk["ai_generated"]),
            }
            data = self._post("/post/publish/video/init/", token, {"post_info": post_info, "source_info": source})
            if privacy == "SELF_ONLY":
                warnings.append("TikTok: bài đang ở chế độ riêng tư (SELF_ONLY), mày phải mở app chuyển sang Công khai")
        publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
        if not (publish_id and upload_url):
            raise PlatformError(f"TikTok init thiếu publish_id/upload_url: {data}")
        self._upload(upload_url, job.path, size, chunk, total)
        status = self._wait(token, publish_id, want="SEND_TO_USER_INBOX" if self.mode == "draft" else "PUBLISH_COMPLETE")
        res = Result(id=publish_id, note=status, warnings=warnings)
        if self.mode == "draft":
            res.manual = _manual_text(job, text, draft=True)
        return res

    def _upload(self, url: str, path, size: int, chunk: int, total: int) -> None:
        with open(path, "rb") as f:
            for i in range(total):
                start = i * chunk
                n = (size - start) if i == total - 1 else chunk
                data = f.read(n)
                r = net.request(
                    "PUT",
                    url,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(len(data)), "Content-Range": f"bytes {start}-{start + len(data) - 1}/{size}"},
                    data=data,
                    timeout=600,
                )
                if r.status_code not in (200, 201, 206):
                    raise PlatformError(f"TikTok upload chunk {i + 1}/{total} lỗi {r.status_code}: {r.text[:200]}")

    def _wait(self, token: str, publish_id: str, want: str, tries: int = 24) -> str:
        last = "PROCESSING_UPLOAD"
        for _ in range(tries):
            data = self._post("/post/publish/status/fetch/", token, {"publish_id": publish_id})
            last = data.get("status", last)
            if last in (want, "PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
                return last
            if last == "FAILED":
                raise PlatformError(f"TikTok xử lý thất bại: {data.get('fail_reason', 'không rõ')}", retryable=False)
            self.sleep(10)
        return f"{last} (vẫn đang xử lý, TikTok sẽ tự hoàn tất)"


def _manual_text(job: Job, caption: str, draft: bool = False) -> str:
    head = "Mở app TikTok, bấm thông báo trong hộp thư để hoàn tất bài, dán caption bên dưới, chọn nhạc đang trend rồi Đăng." if draft else "Tự đăng clip lên TikTok."
    link = f"\nTải clip: {job.public_url}" if job.public_url and not draft else ""
    return f"{head}{link}\nCaption:\n{caption}"


def _json(r) -> dict:
    try:
        j = r.json()
        return j if isinstance(j, dict) else {}
    except ValueError:
        return {}
