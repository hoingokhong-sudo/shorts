"""Một chỗ duy nhất gọi HTTP (dễ retry, dễ mock khi test)."""
from __future__ import annotations

import time

import requests

_session = requests.Session()
RETRY_STATUS = (429, 500, 502, 503, 504)


class HttpError(Exception):
    pass


def request(method: str, url: str, *, retries: int = 2, timeout: int = 60, **kw) -> requests.Response:
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            r = _session.request(method, url, timeout=timeout, **kw)
        except requests.RequestException as e:  # mất mạng, timeout...
            last = e
            if i < retries:
                time.sleep(2 * (i + 1))
            continue
        if r.status_code in RETRY_STATUS and i < retries:
            time.sleep(min(30, 3 * (i + 1)))
            continue
        return r
    raise HttpError(f"{method} {url.split('?')[0]} lỗi mạng: {last}")
