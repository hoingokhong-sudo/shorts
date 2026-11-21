"""Điều phối một lần chạy: quét clip -> quyết định lịch -> đăng -> lưu state -> thông báo."""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import captions, clips, notify, schedule, trending
from . import state as S
from .platforms.base import Job, PlatformError
from .platforms.instagram import Instagram
from .platforms.tiktok import TikTok
from .platforms.youtube import YouTube
from .tokens import TokenStore

ORDER = ["youtube", "tiktok", "instagram"]  # Instagram cuối cùng để GitHub Pages kịp dựng clip mới
LABEL = {"youtube": "YouTube Shorts", "tiktok": "TikTok", "instagram": "Instagram Reels"}


def log(*a):
    print(*a, flush=True)


def build_platforms(cfg: dict, tokens: TokenStore, env) -> tuple[dict, list[str]]:
    classes = {"youtube": YouTube, "tiktok": TikTok, "instagram": Instagram}
    active, skipped = {}, []
    for name in ORDER:
        if not cfg["platforms"].get(name):
            continue
        p = classes[name](cfg, tokens, env)
        if p.configured():
            active[name] = p
        else:
            why = "thiếu secret" + (" hoặc TOKEN_KEY" if name != "youtube" else "")
            skipped.append(f"{LABEL[name]}: {why}")
    return active, skipped


def public_url(cfg: dict, rel: str, env) -> str:
    h = cfg["hosting"]
    base = h["public_base_url"]
    repo = env.get("GITHUB_REPOSITORY", "")
    if not base and repo:
        owner, name = repo.split("/", 1)
        if h["mode"] == "raw":
            base = f"https://raw.githubusercontent.com/{repo}/{env.get('GITHUB_REF_NAME') or 'main'}/"
        elif name.lower() == f"{owner.lower()}.github.io":
            base = f"https://{owner}.github.io/"
        else:
            base = f"https://{owner}.github.io/{name}/"
    if not base:
        return ""
    return base.rstrip("/") + "/" + quote(rel)


def _ent(clip: dict, p: str) -> dict:
    return clip["platforms"].setdefault(p, {"status": "pending", "attempts": 0})


def _try(plat, job: Job, clip: dict, pname: str, now: datetime, cfg: dict, events: list) -> None:
    ent = _ent(clip, pname)
    ent["attempts"] += 1
    ent["last"] = S.iso(now)
    clip["started"] = True
    try:
        log(f"  -> {LABEL[pname]}: đăng {job.name} (lần {ent['attempts']})")
        res = plat.publish(job)
        ent.update(status="done", result=res.to_dict(), error="")
        log(f"     xong {res.url or res.id or res.note}")
    except PlatformError as e:
        ent["error"] = str(e)
        if not e.retryable or ent["attempts"] >= cfg["schedule"]["max_attempts"]:
            ent["status"] = "failed"
        log(f"     LỖI: {e}")
    except Exception as e:  # noqa: BLE001
        ent["error"] = f"{type(e).__name__}: {e}"
        if ent["attempts"] >= cfg["schedule"]["max_attempts"]:
            ent["status"] = "failed"
        log(f"     LỖI bất ngờ: {ent['error']}")
    events.append({"clip": job.name, "platform": pname, "ent": dict(ent)})


def pending_names(st: dict) -> list[str]:
    """Clip chưa từng bắt đầu đăng, theo thứ tự hàng đợi."""
    items = [(v["added"], clips.natural_key(n), n) for n, v in st["clips"].items() if not v.get("started")]
    return [n for _, _, n in sorted(items)]


def run(cfg: dict, root: Path, *, now: datetime | None = None, force: bool = False, dry_run: bool = False, use_ai: bool = True, env=None, platforms: dict | None = None) -> dict:
    env = env if env is not None else os.environ
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(cfg["timezone"])
    d = cfg["dirs"]
    clips_dir, state_path = root / d["clips"], root / d["state"] / "state.json"
    st = S.load(state_path)
    tokens = TokenStore(root / d["state"] / "tokens.enc", env=env, writable=not dry_run)
    if platforms is None:
        platforms, skipped = build_platforms(cfg, tokens, env)
    else:
        skipped = []
    events: list[dict] = []
    out = {"events": events, "skipped": skipped, "plan": None, "new": [], "dry_run": dry_run}

    # 1. quét clip
    names = clips.scan(clips_dir)
    new = [n for n in names if n not in st["clips"]]
    for n in new:
        st["clips"][n] = {"added": S.iso(now), "platforms": {}, "started": False}
    for n in [n for n, v in st["clips"].items() if n not in names]:
        v = st["clips"][n]
        if not v.get("started"):
            del st["clips"][n]
        elif not v.get("finished"):
            for p in v.get("targets", []):
                e = _ent(v, p)
                if e["status"] == "pending":
                    e.update(status="failed", error="file clip đã bị xoá khỏi repo")
    out["new"] = new
    if new and cfg["schedule"]["post_immediately"]:
        st["credit_until"] = S.iso(now + timedelta(hours=cfg["schedule"]["immediate_window_hours"]))
    if new:
        log(f"Clip mới: {', '.join(new)}")

    def make_job(name: str, clip: dict) -> Job:
        path = clips_dir / name
        return Job(name=name, path=path, meta=clip["meta"], public_url=public_url(cfg, f"{d['clips']}/{name}", env), info=clip.get("info", {}))

    # 2. thử lại các nền tảng lỗi của clip đang dở
    cool = timedelta(minutes=cfg["schedule"]["retry_cooldown_minutes"])
    for name, clip in list(st["clips"].items()):
        if not clip.get("started") or clip.get("finished"):
            continue
        for p in clip["targets"]:
            e = _ent(clip, p)
            last = S.parse(e.get("last"))
            if e["status"] != "pending" or dry_run:
                continue
            if p not in platforms:
                e.update(status="failed", error="nền tảng chưa được cấu hình (thiếu secret)")
            elif e["attempts"] >= 1 and (last is None or now - last >= cool):
                _try(platforms[p], make_job(name, clip), clip, p, now, cfg, events)

    # 3. quyết định đăng clip mới
    pend = pending_names(st)
    plan = schedule.decide(now, cfg, st, len(pend), force=force)
    out["plan"] = plan
    log(f"[{now.astimezone(tz):%Y-%m-%d %H:%M}] hàng đợi {plan.pending}, hôm nay {plan.posts_today}/{plan.per_day} bài: {plan.reason}")
    if plan.post and not platforms:
        log("Chưa cấu hình nền tảng nào (thiếu secret), bỏ qua. " + "; ".join(skipped))
    elif plan.post:
        name = pend[0]
        clip = st["clips"][name]
        clip["targets"] = [p for p in ORDER if p in platforms]
        clip["info"] = clips.probe(clips_dir / name)
        clip["warnings"] = clips.check(clip["info"], cfg)
        if "meta" not in clip:
            clip["meta"] = _make_meta(cfg, clips_dir, name, platforms, env, use_ai)
        if dry_run:
            out["dry_meta"] = {"clip": name, **clip["meta"], "warnings": clip["warnings"], "targets": clip["targets"]}
        else:
            job = make_job(name, clip)
            for p in clip["targets"]:
                _try(platforms[p], job, clip, p, now, cfg, events)

    # 4. ghi nhận bài đã tính vào quota, dọn clip đã xong
    if not dry_run:
        for name, clip in list(st["clips"].items()):
            if not clip.get("started"):
                continue
            states = [_ent(clip, p)["status"] for p in clip["targets"]]
            if not clip.get("counted") and "done" in states:
                clip["counted"] = True
                st["posts"].append(S.iso(now))
                st["credit_until"] = None
            if not clip.get("finished") and all(s in ("done", "failed") for s in states):
                clip["finished"] = True
                ok = "done" in states
                st["history"].append({"clip": name, "at": S.iso(now), "ok": ok, "results": {p: _ent(clip, p) for p in clip["targets"]}})
                _retire(root, cfg, name, ok)
                events.append({"clip": name, "platform": "_final", "ok": ok})
        S.save(state_path, st)  # lưu trước khi gọi mạng thông báo
        tokens.save()
        if events:
            try:
                _announce(cfg, env, st, events, out)
            except Exception as e:  # noqa: BLE001
                log(f"[notify] lỗi: {e}")
        # clip đã xong khỏi state.clips để không phình
        for name in [n for n, c in st["clips"].items() if c.get("finished")]:
            del st["clips"][name]
        S.save(state_path, st)

    out["state"] = st
    out["forecast"] = schedule.forecast(now, cfg, st, len(pending_names(st)))
    _summary(cfg, env, out, tz)
    return out


def _make_meta(cfg, clips_dir: Path, name: str, platforms: dict, env, use_ai: bool) -> dict:
    side = clips.parse_sidecar(clips_dir / (name.rsplit(".", 1)[0] + ".txt"))
    key = env.get("GEMINI_API_KEY")
    tr = {"hashtags": [], "keywords": []}
    if use_ai and (cfg["trending"]["enabled"]):
        tok = None
        yt = platforms.get("youtube")
        if yt:
            try:
                tok = yt.access_token()
            except Exception:  # noqa: BLE001
                tok = None
        tr = trending.collect(cfg, tok, env.get("YT_API_KEY"))
    meta = captions.build(cfg, name, side, tr, key, use_ai=use_ai)
    meta["trending_used"] = {"hashtags": tr["hashtags"][:10], "keywords": tr["keywords"][:6]}
    return meta


def _retire(root: Path, cfg: dict, name: str, ok: bool) -> None:
    d = cfg["dirs"]
    src_dir = root / d["clips"]
    stem = name.rsplit(".", 1)[0]
    files = [src_dir / name, src_dir / f"{stem}.txt"]
    if ok:
        for f in files:
            f.unlink(missing_ok=True)
    else:
        dst = root / d["failed"]
        dst.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.exists():
                shutil.move(str(f), str(dst / f.name))


def _announce(cfg, env, st, events, out) -> None:
    by: dict[str, list] = {}
    for e in events:
        if e["platform"] != "_final":
            by.setdefault(e["clip"], []).append(e)
    lines, manual = [], []
    for clip, evs in by.items():
        c = st["clips"].get(clip) or next((h for h in st["history"] if h["clip"] == clip), {})
        lines.append(f"Clip: {clip}")
        for e in evs:
            ent, p = e["ent"], e["platform"]
            if ent["status"] == "done":
                r = ent.get("result", {})
                lines.append(f"  OK {LABEL[p]}: {r.get('url') or r.get('id') or r.get('note') or 'xong'}")
                for w in r.get("warnings", []):
                    lines.append(f"     ! {w}")
                if r.get("manual"):
                    manual.append(f"[{LABEL[p]}] {r['manual']}")
            else:
                lines.append(f"  {'LỖI' if ent['status'] == 'failed' else 'sẽ thử lại'} {LABEL[p]}: {ent.get('error', '')}")
        for w in (st["clips"].get(clip) or {}).get("warnings", []):
            lines.append(f"  ! {w}")
    if manual:
        lines += ["", "VIỆC CẦN LÀM TAY:"] + manual
    title = "autopost: " + ("có lỗi" if any(e.get("ent", {}).get("status") == "failed" for e in events) else "đã đăng")
    sent = notify.send(env, title, "\n".join(lines))
    out["notified"] = sent


def _summary(cfg, env, out: dict, tz) -> None:
    f = env.get("GITHUB_STEP_SUMMARY")
    plan = out["plan"]
    md = [f"### autopost", f"- Quyết định: **{plan.reason}** (hôm nay {plan.posts_today}/{plan.per_day}, hàng đợi {plan.pending})"]
    if out["skipped"]:
        md.append("- Bỏ qua: " + "; ".join(out["skipped"]))
    for e in out["events"]:
        if e["platform"] == "_final":
            continue
        ent = e["ent"]
        md.append(f"- {e['clip']} / {LABEL[e['platform']]}: {ent['status']} {ent.get('error', '')}")
    if out.get("forecast"):
        md.append("\n**Lịch dự kiến:**")
        pend = pending_names(out["state"])
        for n, t in zip(pend, out["forecast"]):
            md.append(f"- {t.astimezone(tz):%d/%m %H:%M} → {n}")
    text = "\n".join(md) + "\n"
    if f:
        try:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass
