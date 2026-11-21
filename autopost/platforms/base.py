from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class PlatformError(Exception):
    """retryable=False: lỗi cấu hình/quyền, thử lại cũng vô ích."""

    def __init__(self, msg: str, retryable: bool = True):
        super().__init__(msg)
        self.retryable = retryable


@dataclass
class Job:
    """Một clip chuẩn bị đăng."""

    name: str
    path: Path
    meta: dict
    public_url: str = ""
    info: dict = field(default_factory=dict)


@dataclass
class Result:
    id: str = ""
    url: str = ""
    note: str = ""
    warnings: list = field(default_factory=list)
    manual: str = ""  # nội dung cần mày tự làm tay (TikTok draft/manual)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}
