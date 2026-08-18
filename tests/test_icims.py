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


def _jv_row(job_id: str, title: str, place: str, token: str = "acme") -> str:
    return (
        f'<tr><td class="jv-job-list-name">'
        f'<a href="/{token}/job/{job_id}">{title}</a></td>'
        f'<td class="jv-job-list-type">Full-Time</td>'
        f'<td class="jv-job-list-location">\n {place}\n </td></tr>'
    )


def _jv_page(*rows: str, shown: int = 0, total: int = 0) -> str:
    body = "<table><tbody>" + "".join(rows) + "</tbody></table>"
    if total:
        body += f'<div class="jv-pagination-text">1-{shown} of {total}</div>'
    return body


class JobviteTest(unittest.TestCase):
    """Jobvite pages at 50 and the trailing slash is load-bearing.

    The board first came back at exactly 50 postings, which is what a cap
    looks like from the outside -- and it was one. `/search?p=1` answers the
    first page while looking like it paged; `/search/?p=1` actually pages.
    """

    def test_it_pages_past_the_first_fifty(self):
        pages = [
            _jv_page(*[_jv_row(str(n), f"Job {n}", "London") for n in range(50)],
                     shown=50, total=73),
            _jv_page(*[_jv_row(str(n), f"Job {n}", "London") for n in range(50, 73)]),
            _jv_page(),
        ]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.jobvite("acme")
        self.assertEqual(len(jobs), 73)

    def test_the_paged_url_carries_the_trailing_slash(self):
        seen: list[str] = []

        def capture(url, **kwargs):
            seen.append(url)
            return _jv_page(_jv_row("1", "Quant", "London")) if len(seen) == 1 else _jv_page()

        with mock.patch.object(extract.http, "get_text", capture):
            extract.jobvite("acme")

        self.assertEqual(seen[0], "https://jobs.jobvite.com/acme/search/")
        self.assertEqual(seen[1], "https://jobs.jobvite.com/acme/search/?p=1")

    def test_a_page_adding_nothing_ends_the_walk(self):
        page = _jv_page(_jv_row("1", "Quant Researcher", "London"))
        with mock.patch.object(extract.http, "get_text", return_value=page) as fetch:
            jobs = extract.jobvite("acme")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)

    def test_a_board_handing_over_less_than_it_advertises_is_loud(self):
        """The total was parsed and then compared to nothing.

        Stage 16 records "the advertised total is checked on every board", and
        the parsed figure was assigned to a local that was never read again --
        so the guard that found the missing trailing slash in the first place
        was not running afterwards. `1-50 of 73` is the whole evidence a cap
        leaves behind.
        """
        pages = [_jv_page(_jv_row("1", "Quant", "London"), shown=1, total=73), _jv_page()]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            with self.assertRaises(ValueError) as caught:
                extract.jobvite("acme")
        self.assertIn("advertises 73", str(caught.exception))

    def test_a_board_stating_no_total_is_not_treated_as_empty(self):
        """Most pages carry no pagination line, and 0 must not mean a failure."""
        pages = [_jv_page(_jv_row("1", "Quant", "London")), _jv_page()]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            self.assertEqual(len(extract.jobvite("acme")), 1)

    def test_title_and_location_are_read_from_their_own_cells(self):
        page = _jv_page(_jv_row("oX1", "Equity Analyst, Public Real Estate", "Chicago, Illinois"))
        with mock.patch.object(extract.http, "get_text", side_effect=[page, _jv_page()]):
            job = extract.jobvite("acme")[0]
        self.assertEqual(job.title, "Equity Analyst, Public Real Estate")
        self.assertEqual(job.location, "Chicago, Illinois")
        self.assertEqual(job.url, "https://jobs.jobvite.com/acme/job/oX1")

    def test_a_mismatched_table_drops_locations_rather_than_pairing_them_wrongly(self):
        """A location paired with the wrong posting sends the geography gate a
        wrong answer, and that gate deletes rather than reorders."""
        page = (
            '<td class="jv-job-list-name"><a href="/acme/job/1">A</a></td>'
            '<td class="jv-job-list-name"><a href="/acme/job/2">B</a></td>'
            '<td class="jv-job-list-location"> London </td>'
        )
        with mock.patch.object(extract.http, "get_text", side_effect=[page, _jv_page()]):
            jobs = extract.jobvite("acme")
        self.assertEqual([j.location for j in jobs], [None, None])


class RegistrationTest(unittest.TestCase):
    def test_both_are_wired_into_the_extractor_table(self):
        """The bug this stage fixes is a board resolved to an ATS nothing
        reads, so the registration is the fix and belongs in a test."""
        self.assertIn("icims", extract.EXTRACTORS)
        self.assertIn("pinpoint", extract.EXTRACTORS)
        self.assertIn("jobvite", extract.EXTRACTORS)


if __name__ == "__main__":
    unittest.main()


class VarbiTest(unittest.TestCase):
    """Varbi's RSS is the only stable surface: `/what:list/` 404s."""

    FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Nya lediga jobb</title>
<item><title>Kundansvarig till Landshypotek</title>
<link>https://acme.varbi.com/en/what:job/jobID:958884/</link>
<description>Beskrivning av tjansten</description>
<pubDate>Mon, 17 Aug 2026 10:00:00 +0200</pubDate></item>
</channel></rss>"""

    def test_the_posting_id_comes_out_of_the_link(self):
        with mock.patch.object(extract.http, "get", return_value=self.FEED):
            job = extract.varbi("acme")[0]
        self.assertEqual(job.job_id, "958884")
        self.assertEqual(job.title, "Kundansvarig till Landshypotek")
        self.assertEqual(job.description, "Beskrivning av tjansten")

    def test_an_empty_channel_is_a_firm_with_no_openings(self):
        empty = b'<?xml version="1.0"?><rss version="2.0"><channel/></rss>'
        with mock.patch.object(extract.http, "get", return_value=empty):
            self.assertEqual(extract.varbi("acme"), [])

    def test_a_feed_with_no_channel_is_loud(self):
        with mock.patch.object(extract.http, "get", return_value=b"<rss/>"):
            with self.assertRaises(ValueError):
                extract.varbi("acme")


class HomerunTest(unittest.TestCase):
    """The board links out to the firm's own host, so the feed is the surface."""

    FEED = b"""<?xml version="1.0" encoding="UTF-8" ?>
<feed xmlns="http://www.w3.org/2005/Atom"><title type="text">Tiqets</title>
<entry><title type="text">Data Analyst</title>
<link rel="alternate" type="text/html" href="https://jobs.tiqets.work/data-analyst-4"></link>
<id>job_5V68pcL66o1yqHsDttfp</id>
<updated>2026-08-01T10:00:00Z</updated>
<summary type="html">Join us!</summary>
<content type="html">The full description.</content></entry></feed>"""

    def test_it_follows_the_firm_to_its_own_host(self):
        with mock.patch.object(extract.http, "get", return_value=self.FEED):
            job = extract.homerun("tiqets")[0]
        self.assertEqual(job.url, "https://jobs.tiqets.work/data-analyst-4")
        self.assertEqual(job.job_id, "job_5V68pcL66o1yqHsDttfp")

    def test_content_is_preferred_over_the_summary(self):
        with mock.patch.object(extract.http, "get", return_value=self.FEED):
            self.assertEqual(extract.homerun("t")[0].description, "The full description.")

    def test_an_empty_feed_is_not_an_error(self):
        empty = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
        with mock.patch.object(extract.http, "get", return_value=empty):
            self.assertEqual(extract.homerun("acme"), [])
