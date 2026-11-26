import unicodedata
import unittest
from unittest import mock

from autopost import captions, config, runner, trending


class RepostAndTags(unittest.TestCase):
    def test_key_ignores_tags_number_and_unicode_form(self):
        a = runner.clip_key("01 Hiến tế Krug #tft.mp4")
        self.assertEqual(a, runner.clip_key(unicodedata.normalize("NFD", "Hiến tế Krug #khac.mp4")))
        self.assertNotEqual(a, runner.clip_key("Clip khác #tft.mp4"))

    def test_tag_mix(self):
        user = ["#GhostofTsushima", "#Gaming", "#Xuhuong", "#Shorts", "#livestream"]
        rel = ["#ghost", "#samurai", "#ps5", "#jinsakai", "#gameplay", "#katana"]
        with mock.patch.object(captions, "_gemini", return_value={"title": "T", "caption": "c", "hashtags": ["#bịa", "#samurai"]}):
            m = captions.build(config.load(), "a.mp4", {"title": "A", "tags": user, "note": ""}, {"hashtags": [], "keywords": [], "related": rel}, "k")
        self.assertEqual(len(m["tags"]["youtube"]), 10)
        self.assertEqual(m["tags"]["youtube"][:5], user)
        for p in ("tiktok", "instagram"):
            self.assertEqual(m["tags"][p], ["#GhostofTsushima", "#Gaming", "#livestream", "#samurai", "#ghost"])

    def test_broad_tags_not_searched(self):
        with mock.patch.object(trending.net, "request") as req:
            req.return_value.status_code = 403
            trending.related_tags(config.load(), ["#Gaming", "#Shorts", "#tft"], "tok", None)
        self.assertEqual([c.kwargs["params"]["q"] for c in req.call_args_list], ["#tft", "#tft"])


if __name__ == "__main__":
    unittest.main()
