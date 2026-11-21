"""Kho token mã hoá cho token bị xoay vòng (TikTok refresh token, Instagram token).

Repo public => file state/tokens.enc được mã hoá Fernet bằng secret TOKEN_KEY.
Nếu mày đổi secret gốc (ví dụ cấp lại token), giá trị trong kho tự bị bỏ qua
vì "boot" (dấu vân tay của secret gốc) không còn khớp.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def _fp(v: str | None) -> str:
    return hashlib.sha256((v or "").encode()).hexdigest()[:12]


class TokenStore:
    def __init__(self, path: Path, key: str | None = None, env=None, writable: bool = True):
        self.path = path
        self.env = env if env is not None else os.environ
        self.key = key if key is not None else self.env.get("TOKEN_KEY")
        self.writable = writable
        self.data = {"tokens": {}, "meta": {}}
        self.dirty = False
        self._f = None
        if self.key:
            from cryptography.fernet import Fernet, InvalidToken

            self._f = Fernet(self.key.encode())
            if path.exists():
                try:
                    self.data = json.loads(self._f.decrypt(path.read_bytes()))
                except InvalidToken:
                    print("[tokens] không giải mã được tokens.enc (sai TOKEN_KEY?), dùng secret gốc", file=sys.stderr)

    @property
    def enabled(self) -> bool:
        return self._f is not None

    def get(self, name: str, env_name: str) -> str | None:
        boot = self.env.get(env_name)
        ent = self.data["tokens"].get(name)
        if ent and ent.get("boot") == _fp(boot):
            return ent["value"]
        return boot or None

    def set(self, name: str, env_name: str, value: str) -> None:
        self.data["tokens"][name] = {"value": value, "boot": _fp(self.env.get(env_name))}
        self.dirty = True
        self.save()

    def meta(self, key: str, default=None):
        return self.data["meta"].get(key, default)

    def set_meta(self, key: str, value) -> None:
        if self.data["meta"].get(key) != value:
            self.data["meta"][key] = value
            self.dirty = True
            self.save()

    def save(self) -> None:
        if not (self.dirty and self.writable):
            return
        if not self._f:
            print("[tokens] CẢNH BÁO: chưa có TOKEN_KEY nên token mới không được lưu lại", file=sys.stderr)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._f.encrypt(json.dumps(self.data).encode()))
        os.replace(tmp, self.path)
        self.dirty = False
