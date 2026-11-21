import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from autopost import config, schedule
from autopost import state as S

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
CFG = config.load("/nonexistent")


def vn(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ).astimezone(timezone.utc)


def fresh():
    return {"posts": [], "credit_until": None}


class Decide(unittest.TestCase):
    def test_empty_queue(self):
        self.assertFalse(schedule.decide(vn(2026, 11, 22, 20), CFG, fresh(), 0).post)

    def test_slot_one_per_day(self):
        st = fresh()
        self.assertFalse(schedule.decide(vn(2026, 11, 22, 15), CFG, st, 3).post)
        p = schedule.decide(vn(2026, 11, 22, 20, 10), CFG, st, 3)
        self.assertTrue(p.post)
        self.assertEqual(p.per_day, 1)

    def test_late_window_expires(self):
        self.assertFalse(schedule.decide(vn(2026, 11, 22, 23, 30), CFG, fresh(), 3).post)

    def test_two_per_day_when_queue_big(self):
        st = fresh()
        p = schedule.decide(vn(2026, 11, 22, 12, 5), CFG, st, 8)
        self.assertTrue(p.post)
        self.assertEqual(p.per_day, 2)

    def test_quota_not_flipping_mid_day(self):
        # 8 clip -> 2/ngày. Sau bài 12:00 còn 7 clip nhưng vẫn phải đăng bài thứ 2 lúc 20:00
        st = {"posts": [S.iso(vn(2026, 11, 22, 12, 5))], "credit_until": None}
        p = schedule.decide(vn(2026, 11, 22, 20, 5), CFG, st, 7)
        self.assertEqual(p.per_day, 2)
        self.assertTrue(p.post)

    def test_one_per_day_quota_blocks_second(self):
        st = {"posts": [S.iso(vn(2026, 11, 22, 20, 2))], "credit_until": None}
        p = schedule.decide(vn(2026, 11, 22, 20, 30), CFG, st, 3)
        self.assertFalse(p.post)

    def test_immediate_when_new_clip(self):
        now = vn(2026, 11, 22, 15)
        st = {"posts": [], "credit_until": S.iso(now + timedelta(hours=6))}
        p = schedule.decide(now, CFG, st, 1)
        self.assertTrue(p.post)
        self.assertIn("ngay", p.reason)

    def test_immediate_blocked_in_quiet_hours_then_released(self):
        t0 = vn(2026, 11, 23, 1, 0)
        st = {"posts": [], "credit_until": S.iso(t0 + timedelta(hours=6))}
        self.assertFalse(schedule.decide(t0, CFG, st, 1).post)
        self.assertTrue(schedule.decide(vn(2026, 11, 23, 6, 40), CFG, st, 1).post)

    def test_immediate_credit_expires(self):
        t0 = vn(2026, 11, 22, 21, 0)
        st = {"posts": [S.iso(vn(2026, 11, 22, 20, 0))], "credit_until": S.iso(t0 + timedelta(hours=6))}
        # hết quota hôm nay -> không đăng; sáng mai credit đã hết hạn -> chờ slot 20:00
        self.assertFalse(schedule.decide(vn(2026, 11, 22, 21, 30), CFG, st, 2).post)
        self.assertFalse(schedule.decide(vn(2026, 11, 23, 7, 0), CFG, st, 2).post)
        self.assertTrue(schedule.decide(vn(2026, 11, 23, 20, 0), CFG, st, 2).post)

    def test_min_spacing(self):
        st = {"posts": [S.iso(vn(2026, 11, 22, 11, 0))], "credit_until": None}
        p = schedule.decide(vn(2026, 11, 22, 12, 0), CFG, st, 9)  # slot 12:00 nhưng mới đăng 1h trước
        self.assertFalse(p.post)

    def test_force(self):
        st = {"posts": [S.iso(vn(2026, 11, 22, 11, 0))], "credit_until": None}
        self.assertTrue(schedule.decide(vn(2026, 11, 22, 11, 30), CFG, st, 1, force=True).post)

    def test_timezone_day_boundary(self):
        # 23:50 UTC = 06:50 VN hôm sau; post lúc 20:00 VN hôm trước thuộc ngày khác
        st = {"posts": [S.iso(vn(2026, 11, 22, 20, 0))], "credit_until": None}
        now = vn(2026, 11, 23, 20, 5)
        self.assertEqual(schedule.decide(now, CFG, st, 3).posts_today, 0)


class Simulate(unittest.TestCase):
    """Chạy giả lập cron mỗi 20 phút nhiều ngày và đếm số bài mỗi ngày."""

    def run_sim(self, start_clips, days, push_at=None):
        st = fresh()
        queue = start_clips
        t = vn(2026, 11, 22, 0, 0)
        per_day, times = {}, []
        end = t + timedelta(days=days)
        while t < end:
            if push_at and t in push_at:
                queue += push_at[t]
                st["credit_until"] = S.iso(t + timedelta(hours=6))
            plan = schedule.decide(t, CFG, st, queue)
            if plan.post:
                queue -= 1
                st["posts"].append(S.iso(t))
                st["credit_until"] = None
                d = t.astimezone(TZ).date()
                per_day[d] = per_day.get(d, 0) + 1
                times.append(t.astimezone(TZ))
            t += timedelta(minutes=20)
        return per_day, times, queue

    def test_big_queue_two_then_one(self):
        per_day, times, left = self.run_sim(12, 10, push_at={vn(2026, 11, 22, 0, 0): 0})
        counts = list(per_day.values())
        self.assertEqual(sum(counts), 12 - left)
        self.assertTrue(all(c <= 2 for c in counts))
        self.assertEqual(left, 0)
        # 12 clip: ngày 1-3 đủ 2/ngày (>7), rồi 1/ngày
        self.assertEqual(counts[:3], [2, 2, 2])
        self.assertTrue(all(c == 1 for c in counts[-2:]))

    def test_never_more_than_quota(self):
        per_day, _, _ = self.run_sim(30, 20)
        self.assertTrue(all(c <= 2 for c in per_day.values()))

    def test_push_posts_immediately(self):
        t = vn(2026, 11, 22, 14, 0)
        per_day, times, left = self.run_sim(0, 3, push_at={t: 1})
        self.assertEqual(times[0], t.astimezone(TZ))
        self.assertEqual(left, 0)


class Forecast(unittest.TestCase):
    def test_forecast_matches_rules(self):
        now = vn(2026, 11, 22, 9, 0)
        f = schedule.forecast(now, CFG, fresh(), 3)
        self.assertEqual([x.strftime("%d %H:%M") for x in f], ["22 20:00", "23 20:00", "24 20:00"])

    def test_forecast_two_per_day(self):
        f = schedule.forecast(vn(2026, 11, 22, 9, 0), CFG, fresh(), 9)
        self.assertEqual(f[0].strftime("%H:%M"), "12:00")
        self.assertEqual(f[1].strftime("%H:%M"), "20:00")
        self.assertEqual(len(f), 9)


if __name__ == "__main__":
    unittest.main()
