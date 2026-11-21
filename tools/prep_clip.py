#!/usr/bin/env python3
"""Chuẩn hoá clip cho Shorts/Reels/TikTok (cần ffmpeg trên máy).

    python tools/prep_clip.py video.mp4                 # ra clips/video.mp4
    python tools/prep_clip.py video.mp4 --mode blur     # video ngang -> nền mờ, giữ nguyên hình ở giữa
    python tools/prep_clip.py video.mp4 --out D:/x.mp4

Làm gì: 1080x1920, H.264 High yuv420p, AAC 48kHz, chuẩn hoá âm lượng -14 LUFS (mức các nền tảng nhắm tới),
faststart (video load ngay khi bấm), giới hạn dung lượng < 95MB để GitHub không chặn.
Nếu clip đã chuẩn thì chỉ remux (không nén lại, không mất chất lượng).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        raise SystemExit("File không có luồng video")
    rot = 0
    for sd in v.get("side_data_list", []):
        rot = int(sd.get("rotation", rot))
    w, h = int(v["width"]), int(v["height"])
    if abs(rot) in (90, 270):
        w, h = h, w
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    return {
        "w": w, "h": h, "vcodec": v["codec_name"], "acodec": a["codec_name"] if a else None,
        "fps": float(num) / float(den or 1), "dur": float(j["format"].get("duration", 0)), "mb": Path(path).stat().st_size / 1e6,
        "pix": v.get("pix_fmt"), "rot": rot,
    }


def already_ok(i: dict) -> bool:
    return (i["vcodec"] == "h264" and i["acodec"] in (None, "aac") and (i["w"], i["h"]) == (1080, 1920) and i["fps"] <= 60 and i["pix"] == "yuv420p" and i["mb"] < 95 and i["rot"] == 0)


def build_cmd(src: Path, dst: Path, mode: str, crf: int, info: dict) -> list[str]:
    fps = ["-r", "30"] if info["fps"] > 60 else []
    if mode == "blur":
        vf = ["-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5[bg];[0:v]scale=1080:-2:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]", "-map", "[v]", "-map", "0:a?"]
    else:
        vf = ["-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"]
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *vf, *fps,
            "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", str(crf), "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-movflags", "+faststart", str(dst)]


def slug(name: str) -> str:
    """Tên file ASCII (bỏ dấu tiếng Việt) để URL GitHub Pages và git không bị lệch chuẩn Unicode."""
    s = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9\-]+", "-", s).strip("-")
    return s or "clip"


def prep(src: Path, dst: Path, mode: str = "crop") -> Path:
    if not shutil.which("ffmpeg"):
        raise SystemExit("Chưa cài ffmpeg (winget install ffmpeg)")
    info = probe(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if already_ok(info):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c", "copy", "-movflags", "+faststart", str(dst)], check=True)
        print(f"✔ {src.name} đã chuẩn, chỉ remux faststart -> {dst}")
        return dst
    for crf in (21, 24, 27):
        subprocess.run(build_cmd(src, dst, mode, crf, info), check=True)
        mb = dst.stat().st_size / 1e6
        if mb < 95:
            print(f"✔ {src.name} -> {dst} ({mb:.1f}MB, crf {crf})")
            return dst
        print(f"  {mb:.0f}MB còn lớn, nén mạnh hơn...")
    raise SystemExit("Clip vẫn > 95MB sau khi nén, hãy cắt ngắn bớt")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--mode", choices=["crop", "blur"], default="crop")
    a = ap.parse_args(argv)
    dst = a.out or ROOT / "clips" / (slug(a.src.stem) + ".mp4")
    prep(a.src, dst, a.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
