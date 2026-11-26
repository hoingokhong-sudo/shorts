import json
import os
import unittest
from pathlib import Path
from unittest import mock

from autopost import captions, clips, config
from autopost.platforms import tiktok
from autopost.tokens import TokenStore
from tests.helpers import FakeNet, Resp, make_clip, tmp_root

CFG = config.load("/nonexistent")


class Sidecar(unittest.TestCase):
    def test_parse(self):
        root = tmp_root()
        f = root / "a.txt"
        f.write_text("title: Cú lật kèo\n#TFT #đấutrườngchânlý #tft\nTrận này cực căng với bạn thân\n", encoding="utf-8")
        s = clips.parse_sidecar(f)
        self.assertEqual(s["title"], "Cú lật kèo")
        self.assertEqual(s["tags"], ["#TFT", "#đấutrườngchânlý"])
        self.assertIn("cực căng", s["note"])

    def test_missing(self):
        self.assertEqual(clips.parse_sidecar(Path("/nope.txt"))["tags"], [])

    def test_filename_title_tags(self):
        n = clips.parse_name("03 Pentakill Yasuo cực gắt #tft #HighLight")
        self.assertEqual(n["title"], "Pentakill Yasuo cực gắt")
        self.assertEqual(n["tags"], ["#tft", "#HighLight"])
        self.assertEqual(clips.parse_name("02-cach-nau-pho")["title"], "cach nau pho")

    def test_prettify_and_order(self):
        self.assertEqual(clips.prettify("02-cach-nau-pho"), "Cach nau pho")
        self.assertEqual(clips.natural_key("clip10.mp4") > clips.natural_key("clip2.mp4"), True)


class Mp4(unittest.TestCase):
    def test_probe(self):
        root = tmp_root()
        p = make_clip(root / "clips" / "x.mp4", seconds=8)
        info = clips.probe(p)
        self.assertEqual((info["width"], info["height"]), (1080, 1920))
        self.assertAlmostEqual(info["duration"], 8, delta=0.3)
        self.assertEqual(clips.check(info, CFG), [])

    def test_landscape_warns(self):
        root = tmp_root()
        p = make_clip(root / "clips" / "y.mp4", seconds=2, size="1280x720")
        w = clips.check(clips.probe(p), CFG)
        self.assertTrue(any("9:16" in x for x in w))

    def test_garbage_file(self):
        root = tmp_root()
        p = root / "clips" / "z.mp4"
        p.write_bytes(b"not a video at all")
        self.assertIsNone(clips.probe(p)["duration"])


class Hashtags(unittest.TestCase):
    def sidecar(self, tags, note=""):
        return {"title": "", "tags": tags, "note": note}

    def test_limits_and_user_priority(self):
        user = ["#a1", "#b1", "#c1", "#d1", "#e1", "#f1", "#g1"]
        tr = {"hashtags": ["#trendx", "#trendy", "#trendz"], "keywords": []}
        cfg = config.load("/nonexistent")
        with mock.patch.object(captions, "_gemini", return_value={"title": "T", "caption": "Câu hook. Bạn nghĩ sao?", "hashtags": ["#trendx", "#trendy", "#trendz"]}):
            m = captions.build(cfg, "clip.mp4", self.sidecar(user), tr, "key")
        self.assertEqual(len(m["tags"]["instagram"]), 5)
        self.assertEqual(len(m["tags"]["tiktok"]), 5)
        self.assertEqual(len(m["tags"]["youtube"]), 10)  # 7 tag của mày + 3 trending
        self.assertEqual(m["tags"]["instagram"][:3], ["#a1", "#b1", "#c1"])  # tag của mày giữ trước
        self.assertEqual(m["tags"]["instagram"][3:], ["#trendx", "#trendy"])  # 2 slot trending
        self.assertIn("#Shorts", m["text"]["youtube"]["description"])
        self.assertEqual(m["source"], "gemini")

    def test_few_user_tags_fill_with_trending(self):
        with mock.patch.object(captions, "_gemini", return_value={"title": "T", "caption": "c", "hashtags": ["#t1", "#t2", "#t3", "#t4"]}):
            m = captions.build(CFG, "c.mp4", self.sidecar(["#mine"]), {"hashtags": [], "keywords": []}, "k")
        self.assertEqual(m["tags"]["instagram"][0], "#mine")
        self.assertEqual(len(m["tags"]["instagram"]), 5)

    def test_no_user_tags_no_ai(self):
        m = captions.build(CFG, "02-cach-nau-pho.mp4", self.sidecar([]), {"hashtags": ["#phở", "#xe"], "keywords": []}, None)
        self.assertEqual(m["source"], "rule")
        self.assertEqual(m["title"], "Cach nau pho")
        self.assertEqual(m["tags"]["instagram"], [])  # không có niche khớp thì không bịa tag

    def test_rule_fallback_matches_niche(self):
        cfg = config.load("/nonexistent")
        cfg["niche"]["keywords"] = ["tft"]
        m = captions.build(cfg, "a.mp4", self.sidecar(["#dttc"]), {"hashtags": ["#tftset14", "#bongda"], "keywords": []}, None)
        self.assertEqual(m["tags"]["instagram"], ["#dttc", "#tftset14"])

    def test_gemini_failure_falls_back(self):
        net = FakeNet().on("GET", "/models", Resp(200, {"models": []}))
        with mock.patch("autopost.net.request", net):
            m = captions.build(CFG, "a.mp4", self.sidecar(["#x1"]), {"hashtags": [], "keywords": []}, "key")
        self.assertEqual(m["source"], "rule")

    def test_norm_tag(self):
        self.assertEqual(captions.norm_tag("# hello world!"), "#helloworld")
        self.assertIsNone(captions.norm_tag("#1"))
        self.assertIsNone(captions.norm_tag("#a"))

    def test_model_pick_prefers_lite_stable(self):
        models = {"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in
                  ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite-preview", "gemini-3.8-flash-image", "gemini-3.8-pro", "text-embedding"]]}
        net = FakeNet().on("GET", "/models$", Resp(200, models))
        with mock.patch("autopost.net.request", net):
            picks = captions.pick_model("k")
        self.assertEqual(picks[0], "gemini-3.5-flash-lite")
        self.assertNotIn("gemini-3.8-flash-image", picks)
        self.assertNotIn("gemini-3.8-pro", picks)


class Tokens(unittest.TestCase):
    def setUp(self):
        from cryptography.fernet import Fernet

        self.key = Fernet.generate_key().decode()
        self.path = tmp_root() / "state" / "tokens.enc"

    def test_rotation_roundtrip_and_encrypted_on_disk(self):
        env = {"TIKTOK_REFRESH_TOKEN": "boot1"}
        s = TokenStore(self.path, key=self.key, env=env)
        self.assertEqual(s.get("tt", "TIKTOK_REFRESH_TOKEN"), "boot1")
        s.set("tt", "TIKTOK_REFRESH_TOKEN", "rot2")
        self.assertNotIn(b"rot2", self.path.read_bytes())
        s2 = TokenStore(self.path, key=self.key, env=env)
        self.assertEqual(s2.get("tt", "TIKTOK_REFRESH_TOKEN"), "rot2")

    def test_new_secret_beats_stale_store(self):
        s = TokenStore(self.path, key=self.key, env={"X": "boot1"})
        s.set("tt", "X", "rot2")
        s2 = TokenStore(self.path, key=self.key, env={"X": "reauthorized"})
        self.assertEqual(s2.get("tt", "X"), "reauthorized")

    def test_wrong_key_falls_back(self):
        from cryptography.fernet import Fernet

        s = TokenStore(self.path, key=self.key, env={"X": "b"})
        s.set("tt", "X", "r")
        s2 = TokenStore(self.path, key=Fernet.generate_key().decode(), env={"X": "b"})
        self.assertEqual(s2.get("tt", "X"), "b")

    def test_not_writable(self):
        s = TokenStore(self.path, key=self.key, env={"X": "b"}, writable=False)
        s.set("tt", "X", "r")
        self.assertFalse(self.path.exists())


class TikTokChunks(unittest.TestCase):
    def test_plan(self):
        self.assertEqual(tiktok.plan_chunks(3_000_000), (3_000_000, 1))
        self.assertEqual(tiktok.plan_chunks(60 * 1024 * 1024), (60 * 1024 * 1024, 1))
        c, n = tiktok.plan_chunks(100 * 1024 * 1024)
        self.assertEqual((c, n), (32 * 1024 * 1024, 3))
        self.assertLessEqual(100 * 1024 * 1024 - (n - 1) * c, 128 * 1024 * 1024)  # chunk cuối hợp lệ


if __name__ == "__main__":
    unittest.main()
