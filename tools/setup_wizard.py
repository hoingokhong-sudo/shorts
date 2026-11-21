#!/usr/bin/env python3
"""Trình cài đặt một lần, chạy trên máy mày.

    python tools/setup_wizard.py                  # làm lần lượt tất cả
    python tools/setup_wizard.py --only youtube   # hoặc tiktok | instagram | gemini | notify | github
    python tools/setup_wizard.py --repo son/shorts  # tự đẩy secret lên GitHub bằng gh CLI (nếu đã cài)

Việc nó làm: lấy refresh token YouTube/TikTok qua trình duyệt, kiểm tra token Instagram, sinh TOKEN_KEY,
ghi .env.local (không commit), và nếu có `gh` thì set secret + bật GitHub Pages luôn.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import shutil
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"
YT_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TT_SCOPES = "user.info.basic,video.upload"
TT_PORT = 3455
TT_REDIRECT = f"http://localhost:{TT_PORT}/callback/"


# ---------- tiện ích ----------
def load_env() -> dict:
    d = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def save_env(d: dict) -> None:
    ENV_FILE.write_text("# KHÔNG commit file này\n" + "\n".join(f"{k}={v}" for k, v in d.items()) + "\n", encoding="utf-8")


def pkce_pair(tiktok: bool = False) -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    # TikTok yêu cầu hex(SHA256), Google dùng base64url chuẩn
    challenge = digest.hex() if tiktok else base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def wait_for_code(port: int, path: str = "/", state: str | None = None, timeout: int = 300) -> str:
    """Mở server loopback 1 lần để bắt ?code=... từ redirect của trình duyệt."""
    box: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = "code" in q and (state is None or q.get("state", [""])[0] == state)
            if ok:
                box["code"] = q["code"][0]
            elif "error" in q:
                box["error"] = q["error"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h3>Xong, quay lại cửa sổ terminal nhé.</h3>".encode() if ok else b"<h3>Loi, xem terminal.</h3>")

        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), H) as srv:
        srv.timeout = 1
        t = threading.Timer(timeout, lambda: box.setdefault("error", "timeout"))
        t.start()
        while "code" not in box and "error" not in box:
            srv.handle_request()
        t.cancel()
    if "error" in box:
        raise SystemExit(f"Đăng nhập thất bại: {box['error']}")
    return box["code"]


def free_port() -> int:
    with socketserver.TCPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as s:
        return s.server_address[1]


def ask(msg: str, default: str = "") -> str:
    v = input(f"{msg}{f' [{default}]' if default else ''}: ").strip()
    return v or default


# ---------- từng bước ----------
def step_key(env: dict) -> None:
    if not env.get("TOKEN_KEY"):
        from cryptography.fernet import Fernet

        env["TOKEN_KEY"] = Fernet.generate_key().decode()
        print("✔ Đã sinh TOKEN_KEY (khoá mã hoá token, giữ bí mật).")


def parse_client_secret(path: Path) -> tuple[str, str]:
    j = json.loads(path.read_text(encoding="utf-8"))
    c = j.get("installed") or j.get("web")
    if not c:
        raise SystemExit("File client_secret.json không đúng. Phải tạo OAuth client loại 'Desktop app'.")
    return c["client_id"], c["client_secret"]


def step_youtube(env: dict) -> None:
    print("\n== YouTube ==")
    p = Path(ask("Đường dẫn client_secret.json", str(ROOT / "client_secret.json")).strip('"'))
    cid, cs = parse_client_secret(p)
    port = free_port()
    redirect = f"http://127.0.0.1:{port}"
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {"client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": YT_SCOPES, "access_type": "offline", "prompt": "consent", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    )
    print("Trình duyệt sẽ mở. Chọn ĐÚNG kênh YouTube muốn đăng. Nếu thấy 'Google chưa xác minh ứng dụng' thì bấm Nâng cao > Tiếp tục.")
    webbrowser.open(url)
    code = wait_for_code(port, state=state)
    r = requests.post("https://oauth2.googleapis.com/token", data={"client_id": cid, "client_secret": cs, "code": code, "code_verifier": verifier, "grant_type": "authorization_code", "redirect_uri": redirect}, timeout=30)
    j = r.json()
    if "refresh_token" not in j:
        raise SystemExit(f"Không lấy được refresh token: {j}")
    if "refresh_token_expires_in" in j:
        days = int(j["refresh_token_expires_in"]) / 86400
        print(f"⚠ Token này chỉ sống {days:.0f} ngày vì app Google đang ở chế độ Testing.")
        print("  Vào Google Cloud > APIs & Services > OAuth consent screen > bấm 'PUBLISH APP' rồi chạy lại bước youtube.")
    env.update(YT_CLIENT_ID=cid, YT_CLIENT_SECRET=cs, YT_REFRESH_TOKEN=j["refresh_token"])
    print("✔ YouTube xong.")


def step_tiktok(env: dict) -> None:
    print("\n== TikTok ==")
    print(f"Trong TikTok for Developers > app của mày > Login Kit > Redirect URI: thêm đúng {TT_REDIRECT}")
    key, sec = ask("Client key", env.get("TIKTOK_CLIENT_KEY", "")), ask("Client secret", env.get("TIKTOK_CLIENT_SECRET", ""))
    verifier, challenge = pkce_pair(tiktok=True)
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(
        {"client_key": key, "scope": TT_SCOPES, "response_type": "code", "redirect_uri": TT_REDIRECT, "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    )
    print("Trình duyệt sẽ mở, đăng nhập đúng tài khoản TikTok muốn đăng.")
    webbrowser.open(url)
    code = wait_for_code(TT_PORT, state=state)
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={"client_key": key, "client_secret": sec, "code": code, "grant_type": "authorization_code", "redirect_uri": TT_REDIRECT, "code_verifier": verifier}, timeout=30)
    j = r.json()
    j = j.get("data", j)
    if "refresh_token" not in j:
        raise SystemExit(f"Không lấy được refresh token TikTok: {j}")
    env.update(TIKTOK_CLIENT_KEY=key, TIKTOK_CLIENT_SECRET=sec, TIKTOK_REFRESH_TOKEN=j["refresh_token"])
    print(f"✔ TikTok xong. Scope được cấp: {j.get('scope')}. Refresh token sống ~{int(j.get('refresh_expires_in', 0)) // 86400} ngày và tự xoay vòng mỗi lần tool chạy.")
    print("  LƯU Ý: đừng chạy lệnh nào gọi TikTok refresh trên máy này nữa, nếu không token trên GitHub sẽ bị vô hiệu.")


def step_instagram(env: dict) -> None:
    print("\n== Instagram ==")
    print("Meta for Developers > app > Instagram > API setup with Instagram login > Generate token (cạnh tài khoản IG của mày).")
    tok = ask("Dán access token", env.get("IG_ACCESS_TOKEN", ""))
    r = requests.get("https://graph.instagram.com/me", params={"fields": "user_id,username", "access_token": tok}, timeout=30)
    j = r.json()
    if r.status_code != 200:
        raise SystemExit(f"Token không dùng được: {j}")
    env["IG_ACCESS_TOKEN"] = tok
    print(f"✔ Instagram xong: @{j.get('username')} (id {j.get('user_id') or j.get('id')}).")


def step_gemini(env: dict) -> None:
    print("\n== Gemini (AI viết caption, miễn phí) ==")
    print("Lấy key ở https://aistudio.google.com/apikey (không cần thẻ).")
    key = ask("Dán GEMINI_API_KEY (Enter để bỏ qua)", env.get("GEMINI_API_KEY", ""))
    if not key:
        return
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": key}, params={"pageSize": 5}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Key không dùng được: {r.text[:200]}")
    env["GEMINI_API_KEY"] = key
    print("✔ Gemini xong.")


def step_notify(env: dict) -> None:
    print("\n== Thông báo điện thoại (miễn phí, tuỳ chọn) ==")
    print("Cài app ntfy (Android/iOS), subscribe một topic bí mật. Tool sẽ báo khi đăng xong/lỗi và gửi caption để dán cho TikTok.")
    topic = ask("Tên topic ntfy (Enter để bỏ qua, gợi ý: autopost-" + secrets.token_hex(4) + ")", env.get("NTFY_TOPIC", ""))
    if topic:
        env["NTFY_TOPIC"] = topic


SECRET_NAMES = ["TOKEN_KEY", "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN", "IG_ACCESS_TOKEN", "IG_USER_ID", "GEMINI_API_KEY", "NTFY_TOPIC"]


def step_github(env: dict, repo: str | None) -> None:
    print("\n== GitHub ==")
    gh = shutil.which("gh")
    repo = repo or ask("Repo dạng user/ten-repo (Enter để tự thêm secret bằng tay)", "")
    if not (gh and repo):
        print("Thêm tay: GitHub repo > Settings > Secrets and variables > Actions > New repository secret. Các giá trị nằm trong .env.local:")
        print("  " + ", ".join(k for k in SECRET_NAMES if env.get(k)))
        return
    for k in SECRET_NAMES:
        if env.get(k):
            subprocess.run([gh, "secret", "set", k, "--repo", repo], input=env[k].encode(), check=True, capture_output=True)
            print(f"  ✔ secret {k}")
    branch = ask("Nhánh chính", "main")
    r = subprocess.run([gh, "api", "-X", "POST", f"repos/{repo}/pages", "-f", f"source[branch]={branch}", "-f", "source[path]=/"], capture_output=True, text=True)
    print("  ✔ Đã bật GitHub Pages" if r.returncode == 0 else f"  (Pages: {r.stderr.strip()[:120]}; nếu báo đã tồn tại thì ổn)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["youtube", "tiktok", "instagram", "gemini", "notify", "github"])
    ap.add_argument("--repo")
    a = ap.parse_args(argv)
    env = load_env()
    step_key(env)
    steps = {"youtube": step_youtube, "tiktok": step_tiktok, "instagram": step_instagram, "gemini": step_gemini, "notify": step_notify}
    todo = [a.only] if a.only else list(steps) + ["github"]
    for s in todo:
        try:
            if s == "github":
                step_github(env, a.repo)
            elif not a.only and input(f"\nLàm bước {s}? [Y/n] ").strip().lower() == "n":
                continue
            else:
                steps[s](env)
        except KeyboardInterrupt:
            print("\nBỏ qua.")
        save_env(env)
    save_env(env)
    print(f"\nĐã lưu {ENV_FILE.name}. Xong. Kiểm tra: python -m autopost check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
