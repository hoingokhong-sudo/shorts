"""Chạy thử đăng 1 clip CHỈ lên TikTok (draft) trong thư mục tạm, để quay video demo review.
Không đụng repo, không đăng YouTube/Instagram, không commit gì.
Dùng:  python tools/demo_tiktok.py duong_dan_clip.mp4 [--dry-run]
"""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if len(sys.argv) < 2:
    raise SystemExit("Thiếu đường dẫn clip: python tools/demo_tiktok.py clip.mp4")
clip = Path(sys.argv[1].strip('"'))
env = dict(os.environ)
for line in (ROOT / ".env.local").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
env.pop("GEMINI_API_KEY", None)
tmp = Path(tempfile.mkdtemp(prefix="autopost-demo-"))
(tmp / "clips").mkdir()
(tmp / "state").mkdir()
name = "01-" + clip.stem.replace(" ", "-")
shutil.copy(clip, tmp / "clips" / (name + clip.suffix))
(tmp / "clips" / (name + ".txt")).write_text(f"title: {clip.stem}\n#gaming #tft\n", encoding="utf-8")
(tmp / "config.yml").write_text("platforms:\n  youtube: false\n  tiktok: true\n  instagram: false\n", encoding="utf-8")
env["AUTOPOST_ROOT"] = str(tmp)
env["PYTHONPATH"] = str(ROOT)
args = [sys.executable, "-m", "autopost", "run", "--force", "--no-ai"] + (["--dry-run"] if "--dry-run" in sys.argv else [])
print(f"Thư mục tạm: {tmp}")
sys.exit(subprocess.call(args, cwd=ROOT, env=env))
