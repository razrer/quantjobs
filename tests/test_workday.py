"""Regression tests for the Workday extractor.

Workday is how most large banks publish, and its failure modes are quiet. The
plan calls for a test rather than a comment here, because a comment does not
fail when someone deletes the thing it describes.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from quantscraper import extract


def _page(postings: int, total: int) -> bytes:
    """A CXS response with `postings` rows claiming `total` overall."""
    return json.dumps(
        {
            "total": total,
            "jobPostings": [
                {
                    "title": f"Job {i}",
                    "externalPath": f"/job/{i}",
                    "locationsText": "London",
                    "postedOn": "Posted Today",
                }
                for i in range(postings)
            ],
        }
    ).encode()


class WorkdayPagingTest(unittest.TestCase):
    def test_does_not_stop_on_total_after_the_first_page(self):
        """The trap that actually bites: `total` is 0 on every page but the first.

        A reader who stops when `len(jobs) >= total` gets 20 postings from a
        board of 24 and no error at all. That is a silent coverage loss, which
        is the one failure this project refuses to accept.
        """
        pages = [_page(20, 24), _page(4, 0)]
        with mock.patch.object(extract.http, "post_json", side_effect=pages):
            jobs = extract.workday("tenant|wd3|site")

        self.assertEqual(len(jobs), 24, "paging stopped early -- `total` was trusted")

    def test_never_requests_more_than_twenty(self):
        """Workday rejects limit > 20 -- with HTTP 400 on some tenants and, per
        the vendor's documented behaviour, an empty 200 on others."""
        captured = []

        def capture(url, body, **kwargs):
            captured.append(json.loads(body.decode()))
            return _page(3, 3)

        with mock.patch.object(extract.http, "post_json", side_effect=capture):
            extract.workday("tenant|wd3|site")

        self.assertTrue(captured, "no request was made")
        for request in captured:
            self.assertLessEqual(
                request["limit"], 20, f"asked Workday for {request['limit']} rows"
            )

    def test_stops_on_a_short_page(self):
        """A short page means the board is exhausted; keep going and Workday
        happily serves the same rows again."""
        with mock.patch.object(
            extract.http, "post_json", side_effect=[_page(5, 5)]
        ) as post:
            jobs = extract.workday("tenant|wd3|site")

        self.assertEqual(len(jobs), 5)
        self.assertEqual(post.call_count, 1)

    def test_offset_advances_by_the_page_size(self):
        pages = [_page(20, 40), _page(20, 0), _page(1, 0)]
        captured = []

        def capture(url, body, **kwargs):
            captured.append(json.loads(body.decode())["offset"])
            return pages[len(captured) - 1]

        with mock.patch.object(extract.http, "post_json", side_effect=capture):
            extract.workday("tenant|wd3|site")

        self.assertEqual(captured, [0, 20, 40])

    def test_rejects_a_token_that_is_not_pollable(self):
        """A tenant without a site cannot be polled. Failing loudly beats
        constructing a URL that 404s on every run."""
        with self.assertRaises(ValueError):
            extract.workday("tenant-only")


class WorkdayConstantTest(unittest.TestCase):
    def test_page_size_cap(self):
        self.assertLessEqual(
            extract._WORKDAY_MAX, 20, "Workday rejects limit > 20; do not raise this"
        )


if __name__ == "__main__":
    unittest.main()
