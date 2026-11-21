import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "tools"))

import prep_clip  # noqa: E402
import setup_wizard as W  # noqa: E402
from autopost import clips  # noqa: E402
from tests.helpers import make_clip, tmp_root  # noqa: E402


class Prep(unittest.TestCase):
    def test_landscape_crop_and_blur(self):
        root = tmp_root()
        src = make_clip(root / "src.mp4", seconds=2, size="1280x720")
        for mode in ("crop", "blur"):
            dst = root / f"out-{mode}.mp4"
            prep_clip.prep(src, dst, mode)
            i = prep_clip.probe(dst)
            self.assertEqual((i["w"], i["h"], i["vcodec"], i["pix"]), (1080, 1920, "h264", "yuv420p"))
            self.assertEqual(clips.probe(dst)["width"], 1080)  # parser thuần Python đồng ý với ffprobe
        # faststart: moov nằm trước mdat
        data = dst.read_bytes()
        self.assertLess(data.find(b"moov"), data.find(b"mdat"))

    def test_already_ok_is_remuxed_not_reencoded(self):
        root = tmp_root()
        src = make_clip(root / "ok.mp4", seconds=2)
        dst = root / "ok2.mp4"
        with mock.patch.object(prep_clip, "build_cmd", side_effect=AssertionError("không được nén lại")):
            prep_clip.prep(src, dst)
        self.assertTrue(dst.exists())

    def test_slug(self):
        self.assertEqual(prep_clip.slug("Trận 1 (final)!"), "Tran-1-final")
        self.assertEqual(prep_clip.slug("Đấu Trường_Chân Lý"), "Dau-Truong-Chan-Ly")
        self.assertEqual(prep_clip.slug("!!!"), "clip")


class Wizard(unittest.TestCase):
    def test_pkce_google_vs_tiktok(self):
        v, c = W.pkce_pair()
        self.assertEqual(c, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("="))
        v2, c2 = W.pkce_pair(tiktok=True)
        self.assertEqual(c2, hashlib.sha256(v2.encode()).hexdigest())
        self.assertTrue(43 <= len(v2) <= 128)
        self.assertRegex(v2, r"^[A-Za-z0-9\-._~]+$")

    def test_loopback_captures_code_and_checks_state(self):
        port = W.free_port()
        got = {}
        t = threading.Thread(target=lambda: got.update(code=W.wait_for_code(port, state="S1", timeout=20)))
        t.start()
        time.sleep(0.5)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/?code=BAD&state=EVIL").read()  # sai state: bỏ qua
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback/?code=GOOD&state=S1").read()
        t.join(10)
        self.assertEqual(got.get("code"), "GOOD")

    def test_parse_client_secret(self):
        p = tmp_root() / "cs.json"
        p.write_text(json.dumps({"installed": {"client_id": "a", "client_secret": "b"}}))
        self.assertEqual(W.parse_client_secret(p), ("a", "b"))
        p.write_text(json.dumps({"nope": {}}))
        with self.assertRaises(SystemExit):
            W.parse_client_secret(p)

    def test_github_step_sets_secrets_via_stdin(self):
        env = {"TOKEN_KEY": "k", "YT_REFRESH_TOKEN": "r", "GEMINI_API_KEY": ""}
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw))
            return mock.Mock(returncode=0, stderr="")

        with mock.patch.object(W.shutil, "which", return_value="/usr/bin/gh"), mock.patch.object(W.subprocess, "run", fake_run), mock.patch.object(W, "ask", return_value="main"):
            W.step_github(env, "son/shorts")
        names = [c[0][3] for c in calls if c[0][1] == "secret"]
        self.assertEqual(names, ["TOKEN_KEY", "YT_REFRESH_TOKEN"])  # secret rỗng không đẩy
        self.assertTrue(all("input" in kw and "k" not in " ".join(c[0]) for c, kw in calls if c[1] == "secret"))  # giá trị đi qua stdin, không nằm trên dòng lệnh
        self.assertTrue(any(c[0][1] == "api" and "repos/son/shorts/pages" in c[0] for c in calls))


class AddClip(unittest.TestCase):
    def test_add_and_push(self):
        d = Path(tempfile.mkdtemp(prefix="addclip-"))
        repo, remote = d / "repo", d / "remote.git"
        shutil.copytree(PROJECT, repo, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        sh = lambda *c, cwd=repo: subprocess.run(c, cwd=cwd, check=True, capture_output=True, text=True)  # noqa: E731
        sh("git", "init", "-q", "-b", "main", cwd=repo)
        sh("git", "config", "user.email", "t@t", cwd=repo)
        sh("git", "config", "user.name", "t", cwd=repo)
        sh("git", "init", "-q", "--bare", "-b", "main", str(remote), cwd=d)
        sh("git", "remote", "add", "origin", str(remote), cwd=repo)
        sh("git", "add", "-A", cwd=repo)
        sh("git", "commit", "-q", "-m", "init", cwd=repo)
        sh("git", "push", "-q", "-u", "origin", "main", cwd=repo)
        a = make_clip(d / "Trận 1.mp4", seconds=2, size="1280x720")
        b = make_clip(d / "Trận 2.mp4", seconds=2)
        r = subprocess.run([sys.executable, "tools/add_clip.py", str(a), str(b), "--tags", "#tft #dttc", "--note", "hop bàn"], cwd=repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = sorted(p.name for p in (repo / "clips").glob("*.mp4"))
        self.assertEqual(names, ["01-Tran-1.mp4", "02-Tran-2.mp4"])
        self.assertIn("#tft", (repo / "clips" / "01-Tran-1.txt").read_text(encoding="utf-8"))
        log = sh("git", "log", "--oneline", "-1", cwd=remote).stdout
        self.assertIn("chốt clip", log)


class Cli(unittest.TestCase):
    def run_cli(self, root, *args, env=None):
        e = {**os.environ, "AUTOPOST_ROOT": str(root), "PYTHONPATH": str(PROJECT)}
        e.update(env or {})
        return subprocess.run([sys.executable, "-m", "autopost", *args], cwd=PROJECT, capture_output=True, text=True, env=e)

    def test_status_preview_dryrun(self):
        root = tmp_root()
        make_clip(root / "clips" / "01-tft-lat-keo.mp4", seconds=8)
        (root / "clips" / "01-tft-lat-keo.txt").write_text("#tft #dttc\nhai đứa hop bàn\n", encoding="utf-8")
        make_clip(root / "clips" / "02-b.mp4", seconds=8)
        r = self.run_cli(root, "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Hàng đợi: 2 clip", r.stdout)
        self.assertIn("01-tft-lat-keo.mp4", r.stdout)
        r = self.run_cli(root, "preview", "01-tft-lat-keo", "--no-ai")
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        self.assertEqual(j["tags"]["instagram"][:2], ["#tft", "#dttc"])
        self.assertEqual((j["info"]["width"], j["info"]["height"]), (1080, 1920))
        r = self.run_cli(root, "run", "--dry-run", "--force", "--no-ai", env={"YT_CLIENT_ID": "x", "YT_CLIENT_SECRET": "y", "YT_REFRESH_TOKEN": "z"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DRY RUN", r.stdout)
        self.assertFalse((root / "state" / "state.json").exists())

    def test_check_without_secrets(self):
        root = tmp_root()
        env = {k: "" for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN", "TIKTOK_CLIENT_KEY", "IG_ACCESS_TOKEN", "TOKEN_KEY", "GEMINI_API_KEY")}
        r = self.run_cli(root, "check", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("chưa có", r.stdout)
        self.assertIn("THIẾU", r.stdout)


if __name__ == "__main__":
    unittest.main()
