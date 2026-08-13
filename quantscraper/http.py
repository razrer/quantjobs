"""Polite HTTP fetching. Standard library only, so there is nothing to install."""

from __future__ import annotations

import gzip
import http.cookiejar
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "quant-scraper/0.1 (personal job-hunt tool; razrer@live.com)"

# Windows builds its certificate store lazily: roots are fetched on demand by
# the OS, so a fresh Python process sees only the handful already cached -- 38
# here, against the 152 in a real bundle. Any site whose root has not happened
# to be cached fails with CERTIFICATE_VERIFY_FAILED, which reads exactly like a
# broken server. FINMA was diagnosed as "serves an incomplete chain" on that
# evidence and the diagnosis was wrong; the chain is fine, our trust store was
# short. These bundles already exist on this machine.
_CA_BUNDLES = (
    r"C:\Program Files\Git\mingw64\etc\ssl\certs\ca-bundle.crt",
    r"C:\msys64\etc\pki\ca-trust\extracted\pem\tls-ca-bundle.pem",
)


def _ssl_context() -> ssl.SSLContext:
    for bundle in _CA_BUNDLES:
        if Path(bundle).exists():
            try:
                return ssl.create_default_context(cafile=bundle)
            except (ssl.SSLError, OSError):
                continue
    # No bundle found: the platform default still works for most hosts.
    return ssl.create_default_context()

# One opener for the process, so cookies persist across calls. Some registers
# hand out a session on the search page and return an empty result set to
# anything that arrives without it -- an empty result set, not an error, which
# is the failure mode this project cares most about not being fooled by.
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    urllib.request.HTTPSHandler(context=_ssl_context()),
)

# Minimum gap between two requests to the same host. These are public
# registries doing us a favour; there is no reason to hammer them.
MIN_INTERVAL_S = 1.0

_last_hit: dict[str, float] = {}
# Domain resolution probes thousands of *different* hosts, so it is worth doing
# in parallel -- the per-host interval barely applies when no two requests share
# a host. The lock is what makes that safe; the bookkeeping is still per host,
# so any one registry is hit no harder than before.
_throttle_lock = threading.Lock()


def _throttle(host: str) -> None:
    with _throttle_lock:
        now = time.monotonic()
        wait = MIN_INTERVAL_S - (now - _last_hit.get(host, 0.0))
        # Reserve the slot before sleeping, so concurrent callers for the same
        # host queue up behind each other instead of all waking together.
        _last_hit[host] = now + max(wait, 0.0)
    if wait > 0:
        time.sleep(wait)


def _send(
    request: urllib.request.Request,
    timeout: int,
    retries: int,
    final_url: list[str] | None = None,
) -> bytes:
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
                if final_url is not None:
                    final_url.append(response.geturl())
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


def get(
    url: str,
    *,
    timeout: int = 60,
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> bytes:
    """GET `url` and return the body."""
    return get_with_url(url, timeout=timeout, retries=retries, headers=headers)[0]


def get_with_url(
    url: str,
    *,
    timeout: int = 60,
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    """GET `url`, returning the body and the URL that actually answered.

    Redirects matter to domain resolution: a guess that lands on the right firm
    via a redirect should be recorded as the domain it ended on, not the one we
    guessed, or Layer 2 caches an alias and Layer 3 chases it every poll.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            **(headers or {}),
        },
    )
    final: list[str] = []
    body = _send(request, timeout, retries, final_url=final)
    return body, (final[0] if final else url)


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
