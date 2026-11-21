import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

from autopost import config, runner, schedule
from autopost import state as S
from tests.helpers import FakeNet, Resp, make_clip, tmp_root

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def vn(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=TZ).astimezone(timezone.utc)


def env_all(**extra):
    e = {
        "YT_CLIENT_ID": "cid", "YT_CLIENT_SECRET": "cs", "YT_REFRESH_TOKEN": "yrt",
        "TIKTOK_CLIENT_KEY": "tk", "TIKTOK_CLIENT_SECRET": "ts", "TIKTOK_REFRESH_TOKEN": "tt-boot",
        "IG_ACCESS_TOKEN": "igtok", "TOKEN_KEY": Fernet.generate_key().decode(),
        "GITHUB_REPOSITORY": "son/shorts", "GITHUB_REF_NAME": "main",
    }
    e.update(extra)
    return e


def good_net(yt_privacy="public", ig_fail=0, tt_status="SEND_TO_USER_INBOX", yt_fail=False):
    n = FakeNet()
    # YouTube
    n.on("POST", r"oauth2.googleapis.com/token", Resp(200, {"access_token": "yat"}))
    if yt_fail:
        n.on("POST", r"upload/youtube/v3/videos", Resp(403, {"error": {"message": "quota"}}))
    else:
        n.on("POST", r"upload/youtube/v3/videos", Resp(200, {}, headers={"Location": "https://upload.example/s1"}))
    n.on("PUT", r"upload.example/s1", Resp(200, {"id": "VID1", "status": {"privacyStatus": yt_privacy}}))
    # TikTok
    n.on("POST", r"open.tiktokapis.com/v2/oauth/token", Resp(200, {"access_token": "tat", "refresh_token": "tt-rot-1", "expires_in": 7200}))
    n.on("POST", r"creator_info/query", Resp(200, {"data": {"privacy_level_options": ["SELF_ONLY"], "max_video_post_duration_sec": 600}, "error": {"code": "ok"}}))
    init = {"data": {"publish_id": "PUB1", "upload_url": "https://up.tiktok/x"}, "error": {"code": "ok"}}
    n.on("POST", r"inbox/video/init", Resp(200, init))
    n.on("POST", r"publish/video/init", Resp(200, init))
    n.on("PUT", r"up.tiktok/x", Resp(201, {}))
    n.on("POST", r"status/fetch", Resp(200, {"data": {"status": tt_status}, "error": {"code": "ok"}}))
    # Instagram
    n.on("GET", r"graph.instagram.com/me", Resp(200, {"user_id": "1789", "username": "son"}))
    n.on("HEAD", r"github.io", Resp(200, headers={"content-type": "video/mp4"}))
    media_resp = [Resp(400, {"error": {"message": "temporary", "code": 2}})] * ig_fail + [Resp(200, {"id": "C1"})]
    n.on("POST", r"graph.instagram.com/1789/media$", lambda kw, _l=media_resp: _l.pop(0) if len(_l) > 1 else _l[0])
    n.on("GET", r"graph.instagram.com/C1", Resp(200, {"status_code": "FINISHED"}))
    n.on("POST", r"media_publish", Resp(200, {"id": "M1"}))
    n.on("GET", r"graph.instagram.com/M1", Resp(200, {"permalink": "https://instagram.com/reel/abc"}))
    return n


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root()
        self.cfg = config.load("/nonexistent")
        self.sleep = mock.patch("time.sleep", lambda s: None)
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def add_clip(self, name, tags="#tft #dttc"):
        make_clip(self.root / "clips" / name, seconds=8)
        (self.root / "clips" / (name.rsplit(".", 1)[0] + ".txt")).write_text(f"{tags}\nTrận đấu căng\n", encoding="utf-8")

    def run_(self, net, now, env, **kw):
        with mock.patch("autopost.net.request", net), mock.patch("autopost.runner.notify.send", return_value=["ntfy"]) as snd:
            out = runner.run(self.cfg, self.root, now=now, env=env, use_ai=False, **kw)
        out["notify"] = snd
        return out

    def state(self):
        return S.load(self.root / "state" / "state.json")


class HappyPath(Base):
    def test_new_clip_posts_everywhere_and_cleans_up(self):
        self.add_clip("01-tft-lat-keo.mp4")
        summary = self.root / "summary.md"
        env, net = env_all(GITHUB_STEP_SUMMARY=str(summary)), good_net()
        out = self.run_(net, vn(22, 15), env)
        self.assertTrue(out["plan"].post)
        self.assertIn("Quyết định", summary.read_text(encoding="utf-8"))
        st = self.state()
        self.assertEqual(len(st["posts"]), 1)
        self.assertEqual(st["clips"], {})  # đã xong -> khỏi state
        self.assertTrue(st["history"][0]["ok"])
        self.assertFalse((self.root / "clips" / "01-tft-lat-keo.mp4").exists())
        self.assertFalse((self.root / "clips" / "01-tft-lat-keo.txt").exists())
        # YouTube
        init = [c for c in net.calls if c[0] == "POST" and "upload/youtube" in c[1]][0]
        body = init[2]["json"]
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertIn("#Shorts", body["snippet"]["description"])
        self.assertEqual(body["snippet"]["defaultLanguage"], "vi")
        put = [c for c in net.calls if c[0] == "PUT" and "upload.example" in c[1]][0]
        self.assertTrue(put[2]["headers"]["Content-Range"].startswith("bytes 0-"))
        # TikTok draft
        self.assertEqual(net.count("POST", "inbox/video/init"), 1)
        self.assertEqual(net.count("POST", "publish/video/init"), 0)
        tinit = [c for c in net.calls if "inbox/video/init" in c[1]][0][2]["json"]
        self.assertEqual(tinit["source_info"]["total_chunk_count"], 1)
        self.assertNotIn("post_info", tinit)
        # Instagram dùng URL GitHub Pages
        ig = [c for c in net.calls if c[0] == "POST" and c[1].endswith("/1789/media")][0][2]["data"]
        self.assertEqual(ig["video_url"], "https://son.github.io/shorts/clips/01-tft-lat-keo.mp4")
        self.assertEqual(ig["media_type"], "REELS")
        self.assertIn("#tft", ig["caption"])
        # token TikTok xoay vòng được lưu mã hoá
        from autopost.tokens import TokenStore
        ts = TokenStore(self.root / "state" / "tokens.enc", env=env)
        self.assertEqual(ts.get("tiktok_refresh", "TIKTOK_REFRESH_TOKEN"), "tt-rot-1")
        # thông báo có hướng dẫn thao tác tay cho TikTok draft
        text = out["notify"].call_args[0][2]
        self.assertIn("VIỆC CẦN LÀM TAY", text)
        self.assertIn("youtube.com/shorts/VID1", text)

    def test_second_run_uses_rotated_token(self):
        self.add_clip("a.mp4")
        env = env_all()
        self.run_(good_net(), vn(22, 15), env)
        self.add_clip("b.mp4")
        net2 = good_net()
        self.run_(net2, vn(24, 20, 5), env)
        tok_calls = [c for c in net2.calls if "oauth/token" in c[1]]
        self.assertEqual(tok_calls[0][2]["data"]["refresh_token"], "tt-rot-1")


class Scheduling(Base):
    def test_two_clips_second_waits_until_next_slot(self):
        self.add_clip("01-a.mp4")
        self.add_clip("02-b.mp4")
        env = env_all()
        self.run_(good_net(), vn(22, 15), env)
        self.assertEqual(sorted(p.name for p in (self.root / "clips").glob("*.mp4")), ["02-b.mp4"])
        # chạy lại 15:20 và 19:00: chưa tới giờ
        for h, m in [(15, 20), (19, 0)]:
            net = good_net()
            out = self.run_(net, vn(22, h, m), env)
            self.assertFalse(out["plan"].post, out["plan"].reason)
            self.assertEqual(len(net.calls), 0)
        # 20:00 vẫn chặn vì hôm nay đã đủ 1 bài (hàng đợi nhỏ = 1/ngày)
        self.assertFalse(self.run_(good_net(), vn(22, 20, 0), env)["plan"].post)
        # hôm sau 20:00 thì đăng
        out = self.run_(good_net(), vn(23, 20, 0), env)
        self.assertTrue(out["plan"].post)
        self.assertEqual(len(list((self.root / "clips").glob("*.mp4"))), 0)

    def test_order_is_natural_filename(self):
        for n in ["clip10.mp4", "clip2.mp4", "clip1.mp4"]:
            self.add_clip(n)
        env = self.env = env_all()
        net = good_net()
        self.run_(net, vn(22, 15), env)
        left = sorted(p.name for p in (self.root / "clips").glob("*.mp4"))
        self.assertEqual(left, ["clip10.mp4", "clip2.mp4"])  # clip1 đăng trước

    def test_force(self):
        self.add_clip("a.mp4")
        self.add_clip("b.mp4")
        env = env_all()
        self.run_(good_net(), vn(22, 15), env)
        out = self.run_(good_net(), vn(22, 15, 30), env, force=True)
        self.assertTrue(out["plan"].post)

    def test_quiet_hours_defer_then_post(self):
        self.add_clip("a.mp4")
        env = env_all()
        self.assertFalse(self.run_(good_net(), vn(23, 1, 0), env)["plan"].post)
        self.assertTrue(self.run_(good_net(), vn(23, 6, 40), env)["plan"].post)


class Failures(Base):
    def test_partial_failure_retries_only_failed_platform(self):
        self.add_clip("a.mp4")
        env = env_all()
        net = good_net(ig_fail=5)
        out = self.run_(net, vn(22, 15), env)
        st = self.state()
        c = st["clips"]["a.mp4"]
        self.assertEqual(c["platforms"]["youtube"]["status"], "done")
        self.assertEqual(c["platforms"]["instagram"]["status"], "pending")
        self.assertEqual(len(st["posts"]), 1)  # đã tính 1 bài vào quota
        self.assertTrue((self.root / "clips" / "a.mp4").exists())  # chưa xoá vì IG chưa xong
        # chạy lại sau 5 phút: chưa tới cooldown -> không gọi gì
        net2 = good_net()
        self.run_(net2, vn(22, 15, 5), env)
        self.assertEqual(len(net2.calls), 0)
        # sau 25 phút: chỉ thử lại IG, không upload lại YouTube/TikTok
        net3 = good_net()
        self.run_(net3, vn(22, 15, 25), env)
        self.assertEqual(net3.count("POST", "upload/youtube"), 0)
        self.assertEqual(net3.count("POST", "inbox/video/init"), 0)
        self.assertEqual(net3.count("POST", r"/1789/media$"), 1)
        st = self.state()
        self.assertEqual(st["clips"], {})
        self.assertFalse((self.root / "clips" / "a.mp4").exists())
        self.assertEqual(len(st["posts"]), 1)  # không đếm đôi

    def test_all_platforms_fail_goes_to_failed_dir(self):
        import re
        self.add_clip("a.mp4")
        env = env_all(IG_ACCESS_TOKEN="")  # IG bị bỏ qua
        net = good_net(yt_fail=True)
        net.routes.insert(0, ("POST", re.compile("open.tiktokapis.com/v2/oauth/token"), Resp(401, {"error": "invalid_grant", "error_description": "refresh token invalid"})))
        self.run_(net, vn(22, 15), env)
        st = self.state()
        self.assertFalse(st["history"][-1]["ok"])
        self.assertTrue((self.root / "failed" / "a.mp4").exists())
        self.assertFalse((self.root / "clips" / "a.mp4").exists())
        self.assertEqual(len(st["posts"]), 0)  # không nền tảng nào thành công => không tính quota
        self.assertEqual(st["clips"], {})

    def test_max_attempts_then_failed(self):
        self.add_clip("a.mp4")
        env = env_all()
        net = good_net(ig_fail=99)
        t = vn(22, 15)
        for i in range(3):
            self.run_(net, t + timedelta(minutes=25 * i), env)
        st = self.state()
        self.assertEqual(st["clips"], {})
        self.assertTrue(st["history"][-1]["ok"])  # YT + TikTok xong nên vẫn tính là đã đăng
        self.assertEqual(st["history"][-1]["results"]["instagram"]["status"], "failed")

    def test_youtube_private_warning(self):
        self.add_clip("a.mp4")
        out = self.run_(good_net(yt_privacy="private"), vn(22, 15), env_all())
        text = out["notify"].call_args[0][2]
        self.assertIn("Công khai", text)

    def test_missing_platform_secrets_skipped(self):
        self.add_clip("a.mp4")
        env = env_all(YT_REFRESH_TOKEN="", IG_ACCESS_TOKEN="")
        net = good_net()
        out = self.run_(net, vn(22, 15), env)
        self.assertEqual(net.count("POST", "upload/youtube"), 0)
        self.assertTrue(any("YouTube" in s for s in out["skipped"]))
        self.assertEqual(net.count("POST", "inbox/video/init"), 1)

    def test_no_platforms_does_not_burn_clip(self):
        self.add_clip("a.mp4")
        out = self.run_(good_net(), vn(22, 15), {"GITHUB_REPOSITORY": "a/b"})
        st = self.state()
        self.assertTrue(st["clips"]["a.mp4"]["started"] is False)
        self.assertTrue((self.root / "clips" / "a.mp4").exists())

    def test_tiktok_requires_token_key(self):
        self.add_clip("a.mp4")
        env = env_all()
        env.pop("TOKEN_KEY")
        net = good_net()
        out = self.run_(net, vn(22, 15), env)
        self.assertTrue(any("TikTok" in s for s in out["skipped"]))
        self.assertEqual(net.count("POST", "oauth/token"), 0)


class Modes(Base):
    def test_tiktok_direct_mode_private_warning(self):
        self.cfg["tiktok"]["mode"] = "direct"
        self.add_clip("a.mp4")
        net = good_net(tt_status="PUBLISH_COMPLETE")
        out = self.run_(net, vn(22, 15), env_all())
        d = [c for c in net.calls if c[1].endswith("publish/video/init/")][0][2]["json"]
        self.assertEqual(d["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertIn("#tft", d["post_info"]["title"])
        self.assertIn("riêng tư", out["notify"].call_args[0][2])

    def test_tiktok_manual_mode_makes_no_api_calls(self):
        self.cfg["tiktok"]["mode"] = "manual"
        self.add_clip("a.mp4")
        env = env_all(TIKTOK_CLIENT_KEY="", TIKTOK_REFRESH_TOKEN="")
        net = good_net()
        out = self.run_(net, vn(22, 15), env)
        self.assertEqual(net.count("POST", "tiktokapis"), 0)
        text = out["notify"].call_args[0][2]
        self.assertIn("Caption:", text)
        self.assertIn("son.github.io/shorts/clips/a.mp4", text)

    def test_dry_run_changes_nothing(self):
        self.add_clip("a.mp4")
        net = good_net()
        out = self.run_(net, vn(22, 15), env_all(), dry_run=True)
        self.assertIn("dry_meta", out)
        self.assertEqual(len(net.calls), 0)
        self.assertFalse((self.root / "state" / "state.json").exists())
        self.assertTrue((self.root / "clips" / "a.mp4").exists())

    def test_ai_path_end_to_end(self):
        self.add_clip("a.mp4", tags="#tft")
        net = good_net()
        net.on("GET", r"v1beta/models$", Resp(200, {"models": [{"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}]}))
        gem = {"candidates": [{"content": {"parts": [{"text": json.dumps({"title": "Lật kèo phút chót", "caption": "Không ai ngờ. Bạn có đoán được?", "hashtags": ["#tft", "#tftset14"]})}]}}]}
        net.on("POST", r":generateContent", Resp(200, gem))
        net.on("GET", r"youtube/v3/videos\?|youtube/v3/videos$", Resp(200, {"items": [{"snippet": {"title": "Giải đấu #tftset14 cực hot", "description": "", "tags": []}}]}))
        net.on("GET", r"trends.google.com", Resp(200, content=b"<rss><channel><item><title>tft set 14</title></item></channel></rss>", text="x"))
        env = env_all(GEMINI_API_KEY="gk")
        with mock.patch("autopost.net.request", net), mock.patch("autopost.runner.notify.send", return_value=[]):
            runner.run(self.cfg, self.root, now=vn(22, 15), env=env, use_ai=True)
        yt = [c for c in net.calls if c[0] == "POST" and "upload/youtube" in c[1]][0][2]["json"]
        self.assertEqual(yt["snippet"]["title"], "Lật kèo phút chót")
        self.assertIn("#tftset14", yt["snippet"]["description"])
        gem_call = [c for c in net.calls if ":generateContent" in c[1]][0][2]["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("#tftset14", gem_call)  # ứng viên trending được đưa vào prompt
        self.assertIn("tft set 14", gem_call)


if __name__ == "__main__":
    unittest.main()
