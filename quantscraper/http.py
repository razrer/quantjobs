"""Polite HTTP fetching."""

from __future__ import annotations

import datetime
import email.utils
import gzip
import http.cookiejar
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import certifi

USER_AGENT = "quant-scraper/0.1 (personal job-hunt tool; razrer@live.com)"

# Windows builds its certificate store lazily: roots are fetched on demand by
# the OS, so a fresh Python process sees only the handful already cached -- 38
# measured here, against 152 in a real bundle. Any site whose root has not
# happened to be cached fails with CERTIFICATE_VERIFY_FAILED, which reads
# exactly like a broken server. FINMA was diagnosed as "serves an incomplete
# chain" on that evidence and the diagnosis was wrong; the chain is fine, our
# trust store was short. This used to borrow whichever of Git for Windows' or
# msys2's own CA bundle happened to be installed on this machine -- correct
# here, and silently back to the short OS store on a machine with neither.
# `certifi` ships and maintains the bundle itself, so there is nothing to
# happen to have installed.
def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())

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

# Hosts that have said, in a response, that one second is too fast. **This is
# compliance, not tuning**: a 429 exists to make a client slow down, so slowing
# down is the requested behaviour -- as distinct from changing the user agent,
# rotating an address or imitating a browser, none of which this project does.
#
# `api.mycareersfuture.gov.sg` answers a sustained sweep with HTTP 429 carrying
# `x-amzn-errortype: ForbiddenException` and a header the operators typed by
# hand: `scrapper: contact us via the feedback form if you have legitimate
# reasons`. Low-volume requests answer 200 either side of it, so the threshold
# is volume rather than this tool -- but the note is a statement of their
# wishes, and it is written up in `ACTION-REQUIRED.md` for the reader to settle
# rather than treated as a number to tune against. The interval here is
# deliberately conservative and was not found by probing for the limit, which
# would be the same hammering wearing a lab coat.
#
# `apply.workable.com` is the second entry and it was found the same way --
# by being told. `discover` probes ten ATS vendors per candidate token, so a
# board-discovery sweep is, from Workable's side, one client asking about
# thousands of boards that do not exist; it began answering 429 partway
# through a Hong Kong sweep and kept answering it for unrelated reads of a
# board that *does* exist. Four seconds is the same conservative number, for
# the same reason: the rate was not probed for.
#
# `www2.jobs.gov.hk` is the third and it is here for the opposite reason -- it
# has said nothing to us at all. Its `robots.txt` ends `Disallow: /` and this
# project reads it anyway, at the reader's instruction, so the interval is not
# a response to a refusal but the whole of what is offered in exchange: a full
# sweep of Hong Kong's statutory board is about 750 requests spread over
# 50 minutes, once a week, by one reader. Nothing else about the request
# changes -- same user agent, same single connection, no retry of a refusal.
HOST_INTERVAL_S = {
    "api.mycareersfuture.gov.sg": 4.0,
    "apply.workable.com": 4.0,
    "www2.jobs.gov.hk": 4.0,
}

# How long a 429 is honoured for when the server names no `Retry-After`. A 429
# is not a transient blip like a 503 -- it is the server saying the *rate* is
# wrong -- so it gets its own schedule rather than the generic `2 ** attempt`,
# which spent its whole budget in three seconds and walked into the wall three
# times. Capped so a hostile or mistaken `Retry-After` cannot hang a run.
_BACKOFF_429_S = (30.0, 90.0, 300.0)
MAX_RETRY_AFTER_S = 300.0

_last_hit: dict[str, float] = {}
# Domain resolution probes thousands of *different* hosts, so it is worth doing
# in parallel -- the per-host interval barely applies when no two requests share
# a host. The lock is what makes that safe; the bookkeeping is still per host,
# so any one registry is hit no harder than before.
_throttle_lock = threading.Lock()


def _throttle(host: str) -> None:
    with _throttle_lock:
        now = time.monotonic()
        interval = HOST_INTERVAL_S.get(host, MIN_INTERVAL_S)
        wait = interval - (now - _last_hit.get(host, 0.0))
        # Reserve the slot before sleeping, so concurrent callers for the same
        # host queue up behind each other instead of all waking together.
        _last_hit[host] = now + max(wait, 0.0)
    if wait > 0:
        time.sleep(wait)


def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
    """How long to wait after `exc`, preferring the server's own answer.

    `Retry-After` is either a number of seconds or an HTTP date, and both
    forms occur. A server that names a wait has told us the one thing we would
    otherwise be guessing, so it wins -- clamped, because an absurd value in
    that header would otherwise hang a run for as long as the header says.
    """
    if exc.code != 429:
        return float(2**attempt)
    header = (exc.headers.get("Retry-After") or "").strip()
    stated: float | None = None
    if header.isdigit():
        stated = float(header)
    elif header:
        # Raises on a malformed date rather than returning None, and a broken
        # header must not turn a rate limit into a crash -- the fallback below
        # is a perfectly good answer.
        try:
            when = email.utils.parsedate_to_datetime(header)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            stated = (when - datetime.datetime.now(when.tzinfo)).total_seconds()
    if stated is not None and stated > 0:
        return min(stated, MAX_RETRY_AFTER_S)
    return _BACKOFF_429_S[min(attempt, len(_BACKOFF_429_S) - 1)]


def _send(
    request: urllib.request.Request,
    timeout: int,
    retries: int,
    final_url: list[str] | None = None,
    headers_out: dict[str, str] | None = None,
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
                if headers_out is not None:
                    # Lowercased, because header names are case-insensitive by
                    # spec and the wire does not agree with itself: HTTP/2
                    # normalises them down, HTTP/1.1 sends whatever the server
                    # typed. Looking up `X-Total-Count` against an HTTP/2
                    # response found nothing, the count read as zero, and the
                    # truncation guard that count exists to feed went quiet --
                    # a walk stopped dead on the result window and reported
                    # success. One predictable form is the fix.
                    headers_out.update(
                        (name.lower(), value) for name, value in response.headers.items()
                    )
                return body
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt == retries - 1:
                raise
            # **A 429 is not a 503 and must not share its schedule.** A 5xx is
            # a blip and `2 ** attempt` is right for it; a 429 is the server
            # saying the rate is wrong, and answering that by trying again one
            # second later is both useless and rude. Measured: a MyCareersFuture
            # sweep spent its entire three-attempt budget inside three seconds
            # and died ~400 pages in, losing forty minutes of walk and leaving
            # nothing in `runs` to say so.
            time.sleep(_retry_after(exc, attempt))
            continue
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


def post_json(
    url: str, body: bytes, *, timeout: int = 60, retries: int = 3
) -> bytes:
    """POST a JSON body. Workday's CXS endpoint is the reason this exists."""
    return post_json_with_headers(url, body, timeout=timeout, retries=retries)[0]


def post_json_with_headers(
    url: str, body: bytes, *, timeout: int = 60, retries: int = 3
) -> tuple[bytes, dict[str, str]]:
    """POST a JSON body, returning the response and its headers.

    The headers are the point for exactly one caller: job-room.ch reports how
    many postings a query matched in `x-total-count` and nowhere in the body,
    and that number is the only way `jobroom_ch` can tell a complete slice from
    a truncated one. Reading a count out of the body would be the simpler
    signature and there is no count in the body to read.

    **Header names come back lowercased.** See `_send` -- the casing on the
    wire is not stable and a case-sensitive lookup silently found nothing.
    """
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    received: dict[str, str] = {}
    return _send(request, timeout, retries, headers_out=received), received


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
