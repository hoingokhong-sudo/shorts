"""CLI: python -m autopost run|status|check|preview"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import captions, clips, config, runner, schedule
from . import state as S
from .tokens import TokenStore


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def cmd_run(a, cfg) -> int:
    out = runner.run(cfg, config.ROOT, force=a.force or _env_bool("AUTOPOST_FORCE"), dry_run=a.dry_run or _env_bool("AUTOPOST_DRY_RUN"), use_ai=not a.no_ai)
    if out.get("dry_meta"):
        print("\n--- DRY RUN: sẽ đăng clip này ---")
        print(json.dumps(out["dry_meta"], ensure_ascii=False, indent=2))
    failed = [e for e in out["events"] if e["platform"] != "_final" and e["ent"]["status"] == "failed"]
    return 1 if failed and not a.dry_run else 0  # job đỏ trên GitHub để mày thấy lỗi


def cmd_status(a, cfg) -> int:
    tz = ZoneInfo(cfg["timezone"])
    st = S.load(config.ROOT / cfg["dirs"]["state"] / "state.json")
    names = clips.scan(config.ROOT / cfg["dirs"]["clips"])
    for n in names:
        st["clips"].setdefault(n, {"added": S.iso(datetime.now(timezone.utc)), "platforms": {}, "started": False})
    pend = runner.pending_names({"clips": {n: v for n, v in st["clips"].items() if n in names}})
    now = datetime.now(timezone.utc)
    plan = schedule.decide(now, cfg, st, len(pend))
    print(f"Hàng đợi: {len(pend)} clip | hôm nay đã đăng {plan.posts_today}/{plan.per_day} | {plan.reason}")
    for n, t in zip(pend, schedule.forecast(now, cfg, st, len(pend))):
        print(f"  {t.astimezone(tz):%a %d/%m %H:%M}  {n}")
    inprog = [n for n, v in st["clips"].items() if v.get("started") and not v.get("finished")]
    for n in inprog:
        print(f"  đang dở: {n} -> " + ", ".join(f"{p}:{e['status']}" for p, e in st['clips'][n]['platforms'].items()))
    return 0


def cmd_check(a, cfg) -> int:
    env = os.environ
    tokens = TokenStore(config.ROOT / cfg["dirs"]["state"] / "tokens.enc", env=env, writable=False)
    active, skipped = runner.build_platforms(cfg, tokens, env)
    print("Nền tảng sẵn sàng:", ", ".join(active) or "(chưa có)")
    for s in skipped:
        print("  thiếu:", s)
    print("TOKEN_KEY:", "có" if tokens.enabled else "THIẾU (bắt buộc cho TikTok/Instagram)")
    print("Gemini:", "có key" if env.get("GEMINI_API_KEY") else "không có key (dùng luật cơ bản, vẫn chạy được)")
    if "youtube" in active:
        try:
            active["youtube"].access_token()
            print("YouTube: đăng nhập OK")
        except Exception as e:  # noqa: BLE001
            print("YouTube: LỖI", e)
    if "instagram" in active:
        try:
            print("Instagram: tài khoản", active["instagram"].user_id())
        except Exception as e:  # noqa: BLE001
            print("Instagram: LỖI", e)
    if "tiktok" in active:
        print(f"TikTok: mode={cfg['tiktok']['mode']} (không gọi thử vì refresh token TikTok xoay vòng, gọi ở máy này sẽ làm token trên GitHub hết hạn)")
    if env.get("GEMINI_API_KEY"):
        print("Gemini model sẽ dùng:", (captions.pick_model(env["GEMINI_API_KEY"], cfg["ai"]["model"]) or ["(không dò được)"])[0])
    print("URL clip mẫu:", runner.public_url(cfg, f"{cfg['dirs']['clips']}/vi-du.mp4", env) or "(chạy trên GitHub mới có, hoặc đặt hosting.public_base_url)")
    return 0


def cmd_preview(a, cfg) -> int:
    env = os.environ
    d = config.ROOT / cfg["dirs"]["clips"]
    name = a.clip if a.clip.endswith((".mp4", ".mov", ".m4v")) else a.clip + ".mp4"
    if not (d / name).exists():
        print("không thấy", d / name)
        return 1
    tokens = TokenStore(config.ROOT / cfg["dirs"]["state"] / "tokens.enc", env=env, writable=False)
    active, _ = runner.build_platforms(cfg, tokens, env)
    meta = runner._make_meta(cfg, d, name, active, env, use_ai=not a.no_ai)
    info = clips.probe(d / name)
    print(json.dumps({"info": info, "warnings": clips.check(info, cfg), **meta}, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autopost")
    ap.add_argument("--config", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="một lượt: quét, quyết định, đăng")
    r.add_argument("--force", action="store_true", help="đăng clip kế tiếp ngay, bỏ qua lịch")
    r.add_argument("--dry-run", action="store_true", help="không đăng, không ghi state, chỉ in caption sẽ dùng")
    r.add_argument("--no-ai", action="store_true", help="không gọi Gemini/trending")
    sub.add_parser("status", help="xem hàng đợi và lịch dự kiến")
    sub.add_parser("check", help="kiểm tra secret và đăng nhập")
    p = sub.add_parser("preview", help="xem caption/tag sẽ tạo cho 1 clip")
    p.add_argument("clip")
    p.add_argument("--no-ai", action="store_true")
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    return {"run": cmd_run, "status": cmd_status, "check": cmd_check, "preview": cmd_preview}[a.cmd](a, cfg)


if __name__ == "__main__":
    sys.exit(main())
