"""Polite HTTP fetching. Standard library only, so there is nothing to install."""

from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "quant-scraper/0.1 (personal job-hunt tool; razrer@live.com)"

# Minimum gap between two requests to the same host. These are public
# registries doing us a favour; there is no reason to hammer them.
MIN_INTERVAL_S = 1.0

_last_hit: dict[str, float] = {}


def _throttle(host: str) -> None:
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_hit.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def get(url: str, *, timeout: int = 60, retries: int = 3) -> bytes:
    """GET `url` and return the body, retrying transient failures.

    Client errors (except 429) are not retried -- a 404 will still be a 404.
    """
    host = urllib.parse.urlsplit(url).netloc
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    )

    for attempt in range(retries):
        _throttle(host)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt)

    raise AssertionError("unreachable")


def get_text(url: str, *, encoding: str = "utf-8", **kwargs) -> str:
    return get(url, **kwargs).decode(encoding, errors="replace")
