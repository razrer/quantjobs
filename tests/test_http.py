"""Regression tests for the polite-fetching layer.

One thing here has already cost a source: a 429 shared its retry schedule with
a 503, so a rate limit spent its whole budget inside three seconds and raised.
MyCareersFuture died ~400 pages into a sweep that way.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import email
import time
import unittest
import urllib.error

from quantscraper import http


def _error(code: int, **headers) -> urllib.error.HTTPError:
    text = "".join(f"{name.replace('_', '-')}: {value}\n"
                   for name, value in headers.items())
    return urllib.error.HTTPError(
        "https://api.mycareersfuture.gov.sg/v2/jobs", code, "",
        email.message_from_string(text), None,
    )


class RetryAfterTest(unittest.TestCase):
    def test_a_rate_limit_does_not_share_the_schedule_of_a_blip(self):
        """`2 ** attempt` is 1s then 2s. A server saying "too fast" is not
        answered by asking again one second later."""
        self.assertGreater(http._retry_after(_error(429), 0), 2**0)
        self.assertGreater(http._retry_after(_error(429), 1), 2**1)

    def test_a_server_error_keeps_the_generic_backoff(self):
        for attempt in range(3):
            self.assertEqual(http._retry_after(_error(503), attempt), float(2**attempt))

    def test_the_servers_own_answer_wins(self):
        self.assertEqual(http._retry_after(_error(429, Retry_After="45"), 0), 45.0)

    def test_an_http_date_is_read_as_well_as_a_number(self):
        """Both forms are legal and both occur."""
        when = email.utils.formatdate(time.time() + 120, usegmt=True)
        self.assertGreater(http._retry_after(_error(429, Retry_After=when), 0), 60.0)

    def test_an_absurd_wait_cannot_hang_a_run(self):
        self.assertEqual(
            http._retry_after(_error(429, Retry_After="99999"), 0),
            http.MAX_RETRY_AFTER_S,
        )

    def test_a_malformed_header_falls_back_rather_than_crashing(self):
        """`parsedate_to_datetime` raises on junk, and a broken header must not
        turn a rate limit into a traceback."""
        self.assertEqual(
            http._retry_after(_error(429, Retry_After="whenever you like"), 0),
            http._BACKOFF_429_S[0],
        )

    def test_a_past_date_does_not_produce_a_negative_wait(self):
        when = email.utils.formatdate(time.time() - 600, usegmt=True)
        self.assertGreater(http._retry_after(_error(429, Retry_After=when), 0), 0)


class HostIntervalTest(unittest.TestCase):
    """A host that has asked for a wider gap gets one. This is compliance, not
    tuning: slowing down is the behaviour a 429 exists to request."""

    def test_the_default_still_applies_to_every_other_host(self):
        self.assertEqual(
            http.HOST_INTERVAL_S.get("boards-api.greenhouse.io", http.MIN_INTERVAL_S),
            http.MIN_INTERVAL_S,
        )

    def test_a_named_host_is_slower_than_the_default(self):
        for host, interval in http.HOST_INTERVAL_S.items():
            self.assertGreater(interval, http.MIN_INTERVAL_S, host)

    def test_the_throttle_reads_the_table_and_not_only_the_constant(self):
        """The table existing is not the same as `_throttle` consulting it."""
        host = next(iter(http.HOST_INTERVAL_S))
        http._last_hit.pop(host, None)
        http._throttle(host)          # first call books the slot, returns at once
        started = time.monotonic()
        http._throttle(host)          # second must wait out the wider interval
        waited = time.monotonic() - started
        http._last_hit.pop(host, None)
        self.assertGreater(waited, http.MIN_INTERVAL_S)


if __name__ == "__main__":
    unittest.main()
