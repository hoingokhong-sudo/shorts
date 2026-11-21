"""Logic lịch đăng. Toàn hàm thuần, không đụng mạng/file nên test được.

Quy tắc:
- Có `schedule.double_days` (vd sat, sun): những thứ đó 2 clip/ngày, các ngày còn lại 1 clip/ngày.
- Không khai `double_days`: hàng đợi (kể cả clip đã đăng trong hôm nay) <= ngưỡng -> 1 clip/ngày, ngược lại 2 clip/ngày.
- Đăng khi tới "slot" giờ vàng, hoặc ngay khi vừa chốt clip mới (nếu chưa hết quota, không phải giờ ngủ).
- Luôn giữ khoảng cách tối thiểu giữa 2 bài và không vượt quota ngày.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import state as S


@dataclass
class Plan:
    post: bool
    reason: str
    per_day: int = 1
    posts_today: int = 0
    pending: int = 0


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def per_day_for(queue_size: int, cfg: dict, day=None) -> int:
    dd = {str(x).strip().lower()[:3] for x in cfg["schedule"].get("double_days") or []}
    if dd and day is not None:
        return 2 if WEEKDAYS[day.weekday()] in dd else 1
    return 2 if queue_size > cfg["schedule"]["two_per_day_when_queue_over"] else 1


def slots_for(per_day: int, cfg: dict) -> list[time]:
    key = "slots_2_per_day" if per_day >= 2 else "slots_1_per_day"
    return sorted(_t(x) for x in cfg["schedule"][key])


def in_quiet(local_now: datetime, cfg: dict) -> bool:
    qh = cfg["schedule"].get("quiet_hours")
    if not qh:
        return False
    a, b, t = _t(qh[0]), _t(qh[1]), local_now.time()
    return (a <= t < b) if a <= b else (t >= a or t < b)


def _post_times(st: dict) -> list[datetime]:
    return [S.parse(x) for x in st.get("posts", []) if S.parse(x)]


def posts_today(st: dict, now_utc: datetime, tz: ZoneInfo) -> int:
    today = now_utc.astimezone(tz).date()
    return sum(1 for p in _post_times(st) if p.astimezone(tz).date() == today)


def decide(now_utc: datetime, cfg: dict, st: dict, pending: int, force: bool = False) -> Plan:
    tz = ZoneInfo(cfg["timezone"])
    sc = cfg["schedule"]
    local = now_utc.astimezone(tz)
    pt = posts_today(st, now_utc, tz)
    per_day = per_day_for(pending + pt, cfg, local.date())
    base = dict(per_day=per_day, posts_today=pt, pending=pending)
    if pending == 0:
        return Plan(False, "hàng đợi trống", **base)
    if force:
        return Plan(True, "ép đăng ngay (force)", **base)
    if pt >= per_day:
        return Plan(False, f"đủ quota hôm nay ({pt}/{per_day})", **base)
    times = _post_times(st)
    if times:
        gap = now_utc - max(times)
        if gap < timedelta(hours=sc["min_spacing_hours"]):
            return Plan(False, f"mới đăng cách đây {gap.total_seconds() / 3600:.1f}h, chờ đủ khoảng cách", **base)
    cu = S.parse(st.get("credit_until"))
    if sc["post_immediately"] and cu and now_utc < cu:
        if in_quiet(local, cfg):
            return Plan(False, "vừa chốt clip nhưng đang giờ ngủ, chờ hết giờ ngủ", **base)
        return Plan(True, "clip mới chốt: đăng ngay", **base)
    for s in slots_for(per_day, cfg):
        start = datetime.combine(local.date(), s, tzinfo=tz)
        if start <= local < start + timedelta(hours=sc["late_window_hours"]):
            return Plan(True, f"tới slot {s.strftime('%H:%M')}", **base)
    return Plan(False, "chưa tới slot", **base)


def forecast(now_utc: datetime, cfg: dict, st: dict, pending: int, limit: int = 30) -> list[datetime]:
    """Dự đoán giờ đăng của các clip đang chờ (chỉ để hiển thị)."""
    tz = ZoneInfo(cfg["timezone"])
    local = now_utc.astimezone(tz)
    out: list[datetime] = []
    remaining = pending
    pt = posts_today(st, now_utc, tz)
    cu = S.parse(st.get("credit_until"))
    if remaining and cfg["schedule"]["post_immediately"] and cu and now_utc < cu and not in_quiet(local, cfg):
        if pt < per_day_for(remaining + pt, cfg, local.date()):
            out.append(local)
            remaining -= 1
            pt += 1
    day = local.date()
    first_day = True
    while remaining > 0 and len(out) < limit and (day - local.date()).days < 400:
        done_today = pt if first_day else 0
        per_day = per_day_for(remaining + done_today, cfg, day)
        slots = slots_for(per_day, cfg)
        for s in slots:
            if done_today >= per_day or remaining <= 0:
                break
            dt = datetime.combine(day, s, tzinfo=tz)
            if first_day and dt <= local:
                continue
            out.append(dt)
            remaining -= 1
            done_today += 1
        day += timedelta(days=1)
        first_day = False
    return out[:limit]
