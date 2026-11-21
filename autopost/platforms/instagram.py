"""Instagram Reels qua "Instagram API with Instagram Login" (graph.instagram.com).

Cần tài khoản Professional (Creator/Business). Không cần Facebook Page.
Meta chỉ nhận video_url công khai nên clip được host qua GitHub Pages (hoặc raw).
Token dài hạn sống 60 ngày, tool tự refresh khi còn dưới 30 ngày.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .. import net
from .. import state as S
from .base import Job, PlatformError, Result

HOST = "https://graph.instagram.com"
FB_HOST = "https://graph.facebook.com"  # Unified login (system-user token), app Meta mới chỉ còn kiểu này


class Instagram:
    name = "instagram"

    def __init__(self, cfg, tokens, env, sleep=None):
        self.cfg, self.tokens, self.env, self._sleep = cfg, tokens, env, sleep
        v = cfg["instagram"]["api_version"]
        # Có IG_USER_ID => token system-user (Unified login): graph.facebook.com, không hết hạn, không refresh
        self.system = bool(env.get("IG_USER_ID"))
        host = FB_HOST if self.system else HOST
        self.base = f"{host}/{v}" if v else host

    def sleep(self, s: float) -> None:
        (self._sleep or time.sleep)(s)

    def configured(self) -> bool:
        return bool(self.env.get("IG_ACCESS_TOKEN")) and self.tokens.enabled

    # ----- token -----
    def token(self) -> str:
        t = self.tokens.get("ig_token", "IG_ACCESS_TOKEN")
        if not t:
            raise PlatformError("thiếu IG_ACCESS_TOKEN", retryable=False)
        return t

    def maybe_refresh(self, now: datetime | None = None) -> None:
        if self.system:
            return
        now = now or datetime.now(timezone.utc)
        last = S.parse(self.tokens.meta("ig_refreshed_at"))
        if last is None:
            self.tokens.set_meta("ig_refreshed_at", S.iso(now))  # token vừa tạo từ dashboard
            return
        if now - last < timedelta(days=30):
            return
        r = net.request("GET", f"{HOST}/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": self.token()}, retries=1)
        j = _json(r)
        if r.status_code == 200 and j.get("access_token"):
            self.tokens.set("ig_token", "IG_ACCESS_TOKEN", j["access_token"])
            self.tokens.set_meta("ig_refreshed_at", S.iso(now))
        else:
            print(f"[instagram] refresh token lỗi {r.status_code}: {str(j)[:160]} (sẽ thử lại lần sau)")

    def user_id(self) -> str:
        if self.system:
            return str(self.env["IG_USER_ID"])
        uid = self.tokens.meta("ig_user_id")
        if uid:
            return uid
        r = net.request("GET", f"{self.base}/me", params={"fields": "user_id,username", "access_token": self.token()})
        j = _json(r)
        if r.status_code != 200 or not (j.get("user_id") or j.get("id")):
            raise PlatformError(f"Instagram không đọc được tài khoản ({r.status_code}): {_err(j, r)}", retryable=r.status_code >= 500)
        uid = str(j.get("user_id") or j["id"])
        self.tokens.set_meta("ig_user_id", uid)
        return uid

    # ----- đăng -----
    def publish(self, job: Job) -> Result:
        if not job.public_url:
            raise PlatformError("không có URL công khai cho clip", retryable=False)
        self.maybe_refresh()
        uid = self.user_id()
        token = self.token()
        self._wait_url(job.public_url)
        r = net.request(
            "POST",
            f"{self.base}/{uid}/media",
            data={
                "media_type": "REELS",
                "video_url": job.public_url,
                "caption": job.meta["text"]["instagram"][:2200],
                "share_to_feed": "true" if self.cfg["instagram"]["share_to_feed"] else "false",
                "access_token": token,
            },
        )
        j = _json(r)
        if r.status_code != 200 or not j.get("id"):
            raise PlatformError(f"Instagram tạo container lỗi {r.status_code}: {_err(j, r)}", retryable=_retryable(j, r))
        cid = j["id"]
        for _ in range(60):  # tối đa ~10 phút
            s = net.request("GET", f"{self.base}/{cid}", params={"fields": "status_code,status", "access_token": token})
            sj = _json(s)
            code = sj.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise PlatformError(f"Instagram xử lý video lỗi: {sj.get('status', code)}", retryable=False)
            self.sleep(10)
        else:
            raise PlatformError("Instagram xử lý video quá lâu, sẽ thử lại")
        p = net.request("POST", f"{self.base}/{uid}/media_publish", data={"creation_id": cid, "access_token": token})
        pj = _json(p)
        if p.status_code != 200 or not pj.get("id"):
            raise PlatformError(f"Instagram publish lỗi {p.status_code}: {_err(pj, p)}", retryable=_retryable(pj, p))
        mid = pj["id"]
        res = Result(id=mid)
        try:
            g = net.request("GET", f"{self.base}/{mid}", params={"fields": "permalink", "access_token": token}, retries=0)
            res.url = _json(g).get("permalink", "")
        except Exception:  # noqa: BLE001
            pass
        if pj.get("config_issue"):
            res.warnings.append(f"Instagram báo config_issue: {pj['config_issue']}")
        return res

    def _wait_url(self, url: str) -> None:
        """Đợi GitHub Pages dựng xong (clip vừa push chưa có URL ngay)."""
        deadline = time.time() + self.cfg["hosting"]["wait_minutes"] * 60
        pages = self.cfg["hosting"]["mode"] == "pages"
        last = ""
        while True:
            try:
                r = net.request("HEAD", url, retries=0, timeout=30, allow_redirects=True)
                ctype = r.headers.get("content-type", "")
                if r.status_code == 200 and (not pages or ctype.startswith("video/")):
                    return
                last = f"HTTP {r.status_code} {ctype}"
            except Exception as e:  # noqa: BLE001
                last = str(e)
            if time.time() > deadline:
                raise PlatformError(f"URL clip chưa truy cập được ({last}). Kiểm tra GitHub Pages đã bật chưa: {url}")
            self.sleep(15)


def _retryable(j: dict, r) -> bool:
    e = j.get("error") or {}
    if r.status_code in (400, 401, 403) and e.get("code") in (190, 10, 200, 100, 2207026, 2207001, 2207023):
        return False
    return True


def _err(j: dict, r) -> str:
    e = j.get("error")
    if isinstance(e, dict):
        return f"{e.get('message', '')} (code {e.get('code')}, subcode {e.get('error_subcode')})"
    return r.text[:200]


def _json(r) -> dict:
    try:
        j = r.json()
        return j if isinstance(j, dict) else {}
    except ValueError:
        return {}
