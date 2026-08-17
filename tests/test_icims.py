"""Regression tests for the iCIMS and Pinpoint extractors.

Both were tier A with a token and no reader: `ats.py` recognised the host,
`extract.py` had no function for it, so the rows read as resolved and polled
silence. iCIMS alone was 38 boards, the largest single block of that kind.

iCIMS is the one that needs tests rather than trust. It has no feed of any
kind -- the vendor's `format=rss` now 302s to a staff login page -- so it is
parsed out of the portal's HTML, and every HTML parser in this project has
eventually met markup that broke it.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from quantscraper import ats, extract


def _page(*jobs: tuple[str, str], host: str = "careers-acme.icims.com") -> str:
    """A portal page listing `jobs` as (id, slug)."""
    return "".join(
        f'<div><a href="https://{host}/jobs/{job_id}/{slug}/job?in_iframe=1">x</a></div>'
        for job_id, slug in jobs
    )


class IcimsPagingTest(unittest.TestCase):
    def test_it_pages_until_a_page_adds_nothing(self):
        pages = [
            _page(("1", "quant-analyst"), ("2", "risk-analyst")),
            _page(("3", "trader")),
            _page(),
        ]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.icims("acme")

        self.assertEqual([j.job_id for j in jobs], ["1", "2", "3"])

    def test_a_portal_that_ignores_the_page_parameter_terminates(self):
        """Serving page one forever is what an empty-page test never catches.

        Workday needed the same rule for a tenant that ignores `offset`; here
        it is the only stop condition that works, because the portal answers
        HTTP 200 with a full page every time.
        """
        same = _page(("1", "quant-analyst"))
        with mock.patch.object(extract.http, "get_text", return_value=same) as fetch:
            jobs = extract.icims("acme")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)  # first page, then one that adds nothing

    def test_a_posting_listed_twice_on_one_page_is_kept_once(self):
        """The portal repeats a link in its own mobile markup."""
        with mock.patch.object(
            extract.http, "get_text",
            side_effect=[_page(("1", "quant-analyst"), ("1", "quant-analyst")), _page()],
        ):
            self.assertEqual(len(extract.icims("acme")), 1)

    def test_a_dead_board_raises_on_the_first_page(self):
        """A 404 up front is a broken board and must be loud. A 404 later is a
        paging edge, and losing the postings already read for it is not."""
        error = extract.urllib.error.HTTPError("u", 404, "Not Found", {}, None)

        with mock.patch.object(extract.http, "get_text", side_effect=error):
            with self.assertRaises(extract.urllib.error.HTTPError):
                extract.icims("acme")

        with mock.patch.object(
            extract.http, "get_text",
            side_effect=[_page(("1", "quant-analyst")), error],
        ):
            self.assertEqual(len(extract.icims("acme")), 1)


class IcimsTitleTest(unittest.TestCase):
    def test_a_slug_becomes_a_readable_title(self):
        self.assertEqual(
            extract._icims_title("fixed-income-research-analyst"),
            "Fixed Income Research Analyst",
        )

    def test_url_encoding_in_a_slug_is_decoded(self):
        self.assertEqual(
            extract._icims_title("regional-director-%28northern-california%29"),
            "Regional Director (northern California)",
        )

    def test_the_url_points_at_the_posting_not_the_iframe(self):
        with mock.patch.object(
            extract.http, "get_text",
            side_effect=[_page(("7", "quant-researcher")), _page()],
        ):
            job = extract.icims("acme")[0]

        self.assertEqual(
            job.url, "https://careers-acme.icims.com/jobs/7/quant-researcher/job"
        )
        self.assertNotIn("in_iframe", job.url)


class IcimsCostTest(unittest.TestCase):
    def test_markup_without_a_closing_quote_does_not_stall(self):
        """The failure mode of every regex in this project is a stall, not a
        wrong answer. Both halves of the job pattern are length-bounded."""
        markup = '<a href="https://careers-acme.icims.com/jobs/1/' + "a" * 200_000

        start = time.monotonic()
        with mock.patch.object(extract.http, "get_text", return_value=markup):
            extract.icims("acme")
        self.assertLess(time.monotonic() - start, 1.0)


class PinpointTest(unittest.TestCase):
    def _payload(self, **overrides):
        posting = {
            "id": "544190",
            "title": "Senior Platform Engineer",
            "url": "https://systematica.pinpointhq.com/en/postings/abc",
            "location": {"name": "London", "city": "London"},
            "description": "<div>Build things.</div>",
            "deadline_at": None,
        }
        posting.update(overrides)
        return json.dumps({"data": [posting]}).encode()

    def test_it_reads_the_board(self):
        with mock.patch.object(extract.http, "get_text",
                               return_value=self._payload().decode()):
            job = extract.pinpoint("systematica")[0]

        self.assertEqual(job.job_id, "544190")
        self.assertEqual(job.location, "London")
        self.assertEqual(job.description, "Build things.")

    def test_location_falls_back_to_city_when_name_is_absent(self):
        with mock.patch.object(
            extract.http, "get_text",
            return_value=self._payload(location={"city": "Frankfurt"}).decode(),
        ):
            self.assertEqual(extract.pinpoint("x")[0].location, "Frankfurt")

    def test_a_published_deadline_is_carried_through(self):
        """Every board sampled leaves this null, and it is still mapped: it is
        a field the source publishes, which is the only kind of closing date
        this project will accept."""
        with mock.patch.object(
            extract.http, "get_text",
            return_value=self._payload(deadline_at="2026-09-30").decode(),
        ):
            self.assertEqual(extract.pinpoint("x")[0].deadline, "2026-09-30")

    def test_an_empty_board_is_not_an_error(self):
        with mock.patch.object(extract.http, "get_text", return_value='{"data": []}'):
            self.assertEqual(extract.pinpoint("x"), [])


class IcimsFingerprintTest(unittest.TestCase):
    def test_the_cookie_script_path_carries_the_token(self):
        """SIG's careers page names its board nowhere else.

        `careers.sig.com` fronts `careers-sig.icims.com`, and the only place
        `sig` appears in the markup is the vendor's cookie banner script. That
        one pattern is worth 237 postings.
        """
        markup = (
            '<script src="https://cookie-policy-scripts.icims.com/sig/'
            'careers.sig.com/script.js"></script>'
        )
        found = ats.fingerprint(markup)
        self.assertEqual(found[:2], ("icims", "sig"))

    def test_the_ordinary_host_form_still_wins(self):
        markup = (
            '<script src="https://cookie-policy-scripts.icims.com/acme/x.js">'
            '<a href="https://careers-realboard.icims.com/jobs/search">Jobs</a>'
        )
        self.assertEqual(ats.fingerprint(markup)[:2], ("icims", "realboard"))


class RegistrationTest(unittest.TestCase):
    def test_both_are_wired_into_the_extractor_table(self):
        """The bug this stage fixes is a board resolved to an ATS nothing
        reads, so the registration is the fix and belongs in a test."""
        self.assertIn("icims", extract.EXTRACTORS)
        self.assertIn("pinpoint", extract.EXTRACTORS)


if __name__ == "__main__":
    unittest.main()
