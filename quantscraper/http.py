"""Polite HTTP fetching. Standard library only, so there is nothing to install."""

from __future__ import annotations

import gzip
import http.cookiejar
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "quant-scraper/0.1 (personal job-hunt tool; razrer@live.com)"

# One opener for the process, so cookies persist across calls. Some registers
# hand out a session on the search page and return an empty result set to
# anything that arrives without it -- an empty result set, not an error, which
# is the failure mode this project cares most about not being fooled by.
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)

# Minimum gap between two requests to the same host. These are public
# registries doing us a favour; there is no reason to hammer them.
MIN_INTERVAL_S = 1.0

_last_hit: dict[str, float] = {}


def _throttle(host: str) -> None:
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_hit.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def _send(request: urllib.request.Request, timeout: int, retries: int) -> bytes:
    """Send `request`, retrying transient failures.

    Client errors (except 429) are not retried -- a 404 will still be a 404.
    """
    host = urllib.parse.urlsplit(request.full_url).netloc

    for attempt in range(retries):
        _throttle(host)
        try:
            with _OPENER.open(request, timeout=timeout) as response:
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


def get(url: str, *, timeout: int = 60, retries: int = 3) -> bytes:
    """GET `url` and return the body."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    )
    return _send(request, timeout, retries)


def get_text(url: str, *, encoding: str = "utf-8", **kwargs) -> str:
    return get(url, **kwargs).decode(encoding, errors="replace")


def post_form(
    url: str, fields: dict[str, str], *, timeout: int = 60, retries: int = 3
) -> bytes:
    """POST `fields` as an HTML form and return the body.

    Sends the header that marks this as a background request, because the
    registers that need POST are all JSON endpoints behind a JavaScript grid.
    """
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields, doseq=True).encode(),
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    return _send(request, timeout, retries)
