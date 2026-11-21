#!/usr/bin/env python3
"""Chốt clip: chuẩn hoá + tạo file tag + commit + push. Push xong GitHub Actions tự đăng.

    python tools/add_clip.py D:/render/tran1.mp4 --tags "#tft #dttc #doubleup" --note "hai đứa hop sang bàn nhau"
    python tools/add_clip.py a.mp4 b.mp4 c.mp4 --tags "#tft"       # nhiều clip: tool tự dãn lịch 1-2 clip/ngày
    python tools/add_clip.py a.mp4 --no-push                       # chỉ chuẩn bị, chưa đẩy

Thứ tự đăng = thứ tự mày truyền vào (tool tự thêm tiền tố 01-, 02-...).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prep_clip  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "clips"


def next_prefix() -> int:
    nums = [int(m.group(1)) for p in CLIPS.glob("*.mp4") if (m := re.match(r"^(\d{2,3})-", p.name))]
    return (max(nums) if nums else 0) + 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--tags", default="", help='tag của mày, ví dụ "#tft #dttc"')
    ap.add_argument("--note", default="", help="mô tả ngắn để AI viết caption sát nội dung")
    ap.add_argument("--title", default="")
    ap.add_argument("--mode", choices=["crop", "blur"], default="crop")
    ap.add_argument("--no-prep", action="store_true", help="bỏ qua ffmpeg, copy nguyên file")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)

    n = next_prefix()
    added = []
    for src in a.clips:
        if not src.exists():
            raise SystemExit(f"Không thấy {src}")
        base = f"{n:02d}-{prep_clip.slug(src.stem)}"
        dst = CLIPS / f"{base}.mp4"
        if a.no_prep:
            dst.write_bytes(src.read_bytes())
        else:
            prep_clip.prep(src, dst, a.mode)
        lines = ([f"title: {a.title}"] if a.title else []) + ([a.tags] if a.tags else []) + ([a.note] if a.note else [])
        if lines:
            (CLIPS / f"{base}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        added.append(dst.name)
        n += 1
    if a.no_push:
        print("Đã chuẩn bị:", ", ".join(added))
        return 0
    run = lambda *c: subprocess.run(c, cwd=ROOT, check=True)  # noqa: E731
    run("git", "add", "clips")
    run("git", "commit", "-m", f"chốt clip: {', '.join(added)}")
    run("git", "pull", "--rebase", "-q")
    run("git", "push")
    print("✔ Đã push. GitHub Actions sẽ tự đăng (clip đầu đăng ngay nếu còn quota hôm nay, các clip sau theo lịch).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
