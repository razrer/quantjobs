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


def _page(postings: int, total: int, start: int = 0) -> bytes:
    """A CXS response with `postings` rows claiming `total` overall.

    `start` numbers the rows, so two pages of a real board differ. Reusing the
    same ids across pages is what a tenant ignoring `offset` looks like, and
    the extractor now treats that as a stop condition.
    """
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
                for i in range(start, start + postings)
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
        pages = [_page(20, 24), _page(4, 0, start=20)]
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
        pages = [_page(20, 40), _page(20, 0, start=20), _page(1, 0, start=40)]
        captured = []

        def capture(url, body, **kwargs):
            captured.append(json.loads(body.decode())["offset"])
            return pages[len(captured) - 1]

        with mock.patch.object(extract.http, "post_json", side_effect=capture):
            extract.workday("tenant|wd3|site")

        self.assertEqual(captured, [0, 20, 40])

    def test_reads_past_eight_hundred_postings(self):
        """The page bound is a guard, not a board size limit.

        It was 40 pages, and LSEG and State Street both came back at exactly
        800 -- a round number is what a cap looks like from the outside, and
        nothing in the output said so. Every large bank publishes on Workday,
        so the boards that hit this are the ones that matter most.
        """
        pages = [_page(20, 900, start=n * 20) for n in range(45)]
        pages.append(_page(3, 0, start=900))

        with mock.patch.object(extract.http, "post_json", side_effect=pages):
            jobs = extract.workday("tenant|wd3|site")

        self.assertEqual(len(jobs), 903, "paging stopped at the page bound")

    def test_stops_when_a_page_repeats(self):
        """A tenant that ignores `offset` serves page one forever."""
        with mock.patch.object(
            extract.http, "post_json", side_effect=[_page(20, 99)] * 10
        ) as post:
            jobs = extract.workday("tenant|wd3|site")

        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(jobs), 20)

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


class WorkdayEntryWithoutAPathTest(unittest.TestCase):
    """A missing `externalPath` must not become a link to the careers site.

    The URL was built unconditionally, so an entry without a path produced
    `{origin}/en-US/{site}` -- the board's own landing page. The reader found
    two of these on the live board, at Nasdaq and Sun Life, and **42 Workday
    boards held one each**: empty `job_id`, empty `title`, and a card that
    opens a recruiting page instead of an advertisement. A link to the wrong
    page is worse than no link, because only one of the two wastes a click.
    """

    @staticmethod
    def _page(*entries: dict) -> bytes:
        return json.dumps({"total": len(entries), "jobPostings": list(entries)}).encode()

    def _read(self, *entries: dict):
        with mock.patch.object(extract.http, "post_json",
                               side_effect=[self._page(*entries)]):
            return extract.workday("tenant|wd3|site")

    def test_an_entry_with_neither_a_path_nor_a_title_is_not_a_posting(self):
        """Nothing about it can ever be read and it cannot be re-fetched --
        there is no id to ask for. Inventing a row is the write-time mistake."""
        jobs = self._read({"locationsText": "London"})
        self.assertEqual(jobs, [])

    def test_a_title_with_no_path_is_kept_and_carries_no_url(self):
        """Principle 4: this *is* a posting, however badly Workday published
        it, so it is kept -- with `url=None` rather than a fabricated one."""
        jobs = self._read({"title": "Quantitative Researcher",
                           "locationsText": "Amsterdam"})
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0].url)
        self.assertEqual(jobs[0].job_id, "Quantitative Researcher")

    def test_the_ordinary_entry_is_untouched(self):
        jobs = self._read({"title": "Quant Trader", "externalPath": "/job/QT_1",
                           "locationsText": "London"})
        self.assertEqual(jobs[0].url,
                         "https://tenant.wd3.myworkdayjobs.com/en-US/site/job/QT_1")
        self.assertEqual(jobs[0].job_id, "/job/QT_1")

    def test_a_malformed_entry_does_not_cost_the_page_beside_it(self):
        """The guard skips one entry, never the rest of the page."""
        jobs = self._read(
            {"title": "Quant Trader", "externalPath": "/job/QT_1"},
            {"locationsText": "London"},
            {"title": "Quant Researcher", "externalPath": "/job/QR_2"},
        )
        self.assertEqual([j.job_id for j in jobs], ["/job/QT_1", "/job/QR_2"])
