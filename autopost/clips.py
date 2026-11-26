"""Quét clip, đọc file .txt đi kèm, đọc thông số mp4 (không cần ffprobe)."""
from __future__ import annotations

import re
import struct
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".m4v"}
HASHTAG = re.compile(r"#([^\W]+)", re.UNICODE)


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def scan(clips_dir: Path) -> list[str]:
    """Trả về tên file clip (tương đối so với clips_dir), sắp xếp tự nhiên."""
    if not clips_dir.exists():
        return []
    names = [p.name for p in clips_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT]
    return sorted(names, key=natural_key)


def prettify(stem: str) -> str:
    s = re.sub(r"^\s*\d{1,3}[-_. ]+(?=\D)", "", stem)  # bỏ tiền tố số thứ tự 01-
    s = re.sub(r"[-_]+", " ", s).strip()
    return (s[:1].upper() + s[1:]) if s else stem


def parse_name(stem: str) -> dict:
    """Tên file = tiêu đề + tag, ví dụ: `Pentakill Yasuo cực gắt #tft #highlight.mp4`.
    Tiêu đề giữ nguyên chữ mày gõ (bỏ tiền tố số thứ tự và phần #tag)."""
    tags = ["#" + t for t in HASHTAG.findall(stem)]
    title = re.sub(r"\s+", " ", HASHTAG.sub("", stem)).strip(" -_.")
    title = re.sub(r"^\s*\d{1,3}[-_. ]+(?=\D)", "", title).strip()
    if title and " " not in title:  # kiểu cach-nau-pho: đổi gạch thành khoảng trắng
        title = re.sub(r"[-_]+", " ", title).strip()
    return {"title": title, "tags": tags}


def parse_sidecar(path: Path) -> dict:
    """File .txt cạnh clip:
        title: tiêu đề tuỳ chọn
        #tag1 #tag2 ...
        mô tả/ghi chú tuỳ chọn (AI dùng làm ngữ cảnh)
    """
    out = {"title": "", "tags": [], "note": "", "repost": False}
    if not path.exists():
        return out
    note = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^\s*(title|tiêu đề|tieu de)\s*:\s*(.+)$", line, re.I)
        if m:
            out["title"] = m.group(2).strip()
            continue
        if re.match(r"^\s*repost\s*:\s*(yes|true|1)\s*$", line, re.I):
            out["repost"] = True
            continue
        tags = HASHTAG.findall(line)
        if tags:
            out["tags"] += ["#" + t for t in tags]
            rest = HASHTAG.sub("", line).strip()
            if rest:
                note.append(rest)
        elif line.strip():
            note.append(line.strip())
    seen, uniq = set(), []
    for t in out["tags"]:
        if t.lower() not in seen:
            seen.add(t.lower())
            uniq.append(t)
    out["tags"] = uniq
    out["note"] = " ".join(note)
    return out


# ---------- đọc mp4 thuần Python ----------

def _boxes(f, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, typ = struct.unpack(">I4s", f.read(8))
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr:
            return
        yield typ.decode("latin1"), pos + hdr, min(pos + size, end)
        pos += size


def probe(path: Path) -> dict:
    """Trả về duration (s), width, height (đã tính xoay), size_mb. Thiếu thì để None."""
    info = {"duration": None, "width": None, "height": None, "size_mb": round(path.stat().st_size / 1e6, 1)}
    try:
        with open(path, "rb") as f:
            total = path.stat().st_size
            for typ, a, b in _boxes(f, 0, total):
                if typ != "moov":
                    continue
                for t2, a2, b2 in _boxes(f, a, b):
                    if t2 == "mvhd":
                        f.seek(a2)
                        ver = f.read(1)[0]
                        f.seek(a2 + 4)
                        if ver == 1:
                            f.seek(a2 + 4 + 16)
                            ts, dur = struct.unpack(">IQ", f.read(12))
                        else:
                            f.seek(a2 + 4 + 8)
                            ts, dur = struct.unpack(">II", f.read(8))
                        if ts:
                            info["duration"] = round(dur / ts, 2)
                    elif t2 == "trak":
                        w = h = None
                        is_video = False
                        rot = False
                        for t3, a3, b3 in _boxes(f, a2, b2):
                            if t3 == "tkhd":
                                f.seek(a3)
                                ver = f.read(1)[0]
                                moff = 4 + (32 if ver == 1 else 20) + 8 + 8
                                f.seek(a3 + moff)
                                m = struct.unpack(">9i", f.read(36))
                                rot = m[0] == 0 and m[4] == 0 and m[1] != 0 and m[3] != 0
                                w, h = struct.unpack(">II", f.read(8))
                                w, h = w >> 16, h >> 16
                            elif t3 == "mdia":
                                for t4, a4, b4 in _boxes(f, a3, b3):
                                    if t4 == "hdlr":
                                        f.seek(a4 + 8)
                                        is_video = f.read(4) == b"vide"
                        if is_video and w and h and info["width"] is None:
                            info["width"], info["height"] = (h, w) if rot else (w, h)
                break
    except (OSError, struct.error, IndexError):
        pass
    return info


def check(info: dict, cfg: dict) -> list[str]:
    """Cảnh báo mềm giúp clip dễ được đẩy hơn. Không chặn đăng."""
    c = cfg["checks"]
    warn = []
    d, w, h = info.get("duration"), info.get("width"), info.get("height")
    if d is not None:
        if d < c["min_seconds"]:
            warn.append(f"clip chỉ {d:.0f}s, quá ngắn")
        if d > c["max_seconds"]:
            warn.append(f"clip {d:.0f}s > {c['max_seconds']}s: YouTube sẽ không coi là Shorts")
        elif d > c["warn_over_seconds"]:
            warn.append(f"clip {d:.0f}s hơi dài cho short-form (nên 15-60s)")
    if w and h:
        if h <= w:
            warn.append(f"khung {w}x{h} không phải dọc 9:16, Shorts/Reels/TikTok sẽ hiện kém")
        elif abs(w / h - 9 / 16) > 0.03:
            warn.append(f"khung {w}x{h} lệch tỉ lệ 9:16")
        if min(w, h) < 720:
            warn.append(f"độ phân giải {w}x{h} thấp (nên 1080x1920)")
    if info.get("size_mb") and info["size_mb"] > c["max_mb"]:
        warn.append(f"file {info['size_mb']}MB, GitHub chặn file > 100MB, nén lại bằng tools/prep_clip.py")
    return warn
