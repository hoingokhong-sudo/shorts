import json
import re
import subprocess
import tempfile
from pathlib import Path


class Resp:
    def __init__(self, status=200, data=None, headers=None, text=None, content=None):
        self.status_code = status
        self._data = data
        self.headers = headers or {}
        self.text = text if text is not None else (json.dumps(data) if data is not None else "")
        self.content = content if content is not None else self.text.encode()

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeNet:
    """Bảng route: (method, regex url) -> Resp hoặc hàm(kw)->Resp. Ghi lại mọi cuộc gọi."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def on(self, method, pattern, resp):
        self.routes.append((method, re.compile(pattern), resp))
        return self

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for m, pat, resp in self.routes:
            if m == method and pat.search(url):
                r = resp(kw) if callable(resp) else resp
                if isinstance(r, list):  # chuỗi phản hồi lần lượt
                    r = r.pop(0) if len(r) > 1 else r[0]
                return r
        raise AssertionError(f"không có route cho {method} {url}")

    def count(self, method, pattern):
        p = re.compile(pattern)
        return sum(1 for m, u, _ in self.calls if m == method and p.search(u))


def make_clip(path: Path, seconds=3, size="1080x1920"):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=30", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(path)],
        check=True,
    )
    return path


def tmp_root():
    d = Path(tempfile.mkdtemp(prefix="autopost-test-"))
    (d / "clips").mkdir()
    (d / "state").mkdir()
    return d
