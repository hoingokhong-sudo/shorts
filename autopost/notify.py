"""Thông báo miễn phí: ntfy.sh, Telegram, Discord. Cấu hình bằng secret, không có thì bỏ qua."""
from __future__ import annotations

import sys

from . import net


def send(env, title: str, text: str) -> list[str]:
    text = text[:3500]
    sent = []

    def attempt(name, fn):
        try:
            r = fn()
            if r.status_code < 300:
                sent.append(name)
            else:
                print(f"[notify] {name} HTTP {r.status_code}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[notify] {name} lỗi: {e}", file=sys.stderr)

    if env.get("NTFY_TOPIC"):
        attempt("ntfy", lambda: net.request("POST", env.get("NTFY_SERVER", "https://ntfy.sh"), json={"topic": env["NTFY_TOPIC"], "title": title, "message": text}, retries=0, timeout=20))
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        attempt(
            "telegram",
            lambda: net.request(
                "POST",
                f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
                json={"chat_id": env["TELEGRAM_CHAT_ID"], "text": f"{title}\n\n{text}", "disable_web_page_preview": True},
                retries=0,
                timeout=20,
            ),
        )
    if env.get("DISCORD_WEBHOOK"):
        attempt("discord", lambda: net.request("POST", env["DISCORD_WEBHOOK"], json={"content": f"**{title}**\n{text}"[:1900]}, retries=0, timeout=20))
    return sent
