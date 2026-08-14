"""Regression tests for careers-link extraction.

The failure these pin is not a wrong answer, it is no answer: a homepage that
makes the scanner run for hours at full CPU. Two `ats` runs stalled that way,
wrote nothing for two and a half hours, and looked from the outside exactly
like slow network. A timing test is the only kind that fails when the guard is
removed.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from quantscraper import ats


class CareersScanTest(unittest.TestCase):
    def test_unterminated_href_does_not_stall(self):
        """An href that never closes, over markup dense in careers words.

        Real homepages produce this constantly -- an apostrophe inside inline
        script ends the attribute the scanner thought it was reading. The old
        pattern was two unbounded runs either side of the word alternation, so
        the engine retried every split point for every occurrence: quadratic at
        best, and this input took minutes where it now takes milliseconds.
        """
        markup = 'href="' + "jobs/career/vacancies/" * 4000

        start = time.monotonic()
        ats.careers_candidates(markup, "example.com")
        self.assertLess(time.monotonic() - start, 1.0)

    def test_still_finds_careers_links(self):
        """The guard must not cost recall -- including the Nordic words."""
        markup = (
            '<a href="/about">About</a>'
            '<a href="https://example.com/careers/">Careers</a>'
            '<a href="/lediga-jobb">Lediga jobb</a>'
            '<a href="https://jobs.lever.co/example">Open roles</a>'
        )

        found = ats.careers_candidates(markup, "example.com")

        self.assertIn("https://jobs.lever.co/example", found)
        self.assertIn("https://example.com/lediga-jobb", found)

    def test_offsite_links_rank_first(self):
        """An off-site careers link is usually the ATS itself."""
        markup = (
            '<a href="/careers">Careers</a>'
            '<a href="https://jobs.lever.co/example">Roles</a>'
        )

        self.assertEqual(
            ats.careers_candidates(markup, "example.com")[0],
            "https://jobs.lever.co/example",
        )


class CustomDomainTest(unittest.TestCase):
    """An ATS serving a board from the firm's own hostname.

    `careers.lynxhedge.se` is Lynx Asset Management -- the Stockholm quant
    firm this project exists to find -- and it sat in tier B with a live
    Teamtailor feed behind it, because the board is never spelled
    `{board}.teamtailor.com` anywhere on the page.
    """

    def test_a_vendor_cdn_on_a_custom_host_resolves_to_that_host(self):
        markup = '<img src="https://assets-aws.teamtailor-cdn.com/logo.png">'

        with mock.patch.object(ats, "_serves_feed", return_value=True):
            hit = ats.fingerprint(markup, "https://careers.lynxhedge.se/")

        self.assertEqual(hit[:2], ("teamtailor", "careers.lynxhedge.se"))

    def test_the_host_must_actually_serve_the_feed(self):
        """Embedding a vendor's widget puts its CDN in the markup of pages
        that serve no feed. The first three domains this rule matched --
        3stepit, Enfuce, Infovista -- all returned 404 on `/jobs.rss`."""
        markup = '<img src="https://assets-aws.teamtailor-cdn.com/logo.png">'

        with mock.patch.object(ats, "_serves_feed", return_value=False):
            hit = ats.fingerprint(markup, "https://www.3stepit.com/")

        self.assertIsNone(hit)

    def test_a_real_board_token_still_wins(self):
        """The custom-host rule is a fallback, not a replacement: a page that
        names the board outright must still yield the board."""
        markup = (
            '<img src="https://assets-aws.teamtailor-cdn.com/logo.png">'
            '<a href="https://optiver.teamtailor.com/jobs">Jobs</a>'
        )

        with mock.patch.object(ats, "_serves_feed", return_value=True):
            hit = ats.fingerprint(markup, "https://careers.optiver.com/")

        self.assertEqual(hit[:2], ("teamtailor", "optiver"))

    def test_without_a_url_there_is_no_custom_host_to_use(self):
        markup = '<img src="https://assets-aws.teamtailor-cdn.com/logo.png">'

        self.assertIsNone(ats.fingerprint(markup))


class FingerprintCostTest(unittest.TestCase):
    def test_a_base64_blob_does_not_stall(self):
        """An inline data URI is a long run of label characters with no dot.

        Every `{board}.host.com` pattern will try to be the board, consume the
        whole run, backtrack through it, and start again one character along.
        This is what actually hung the runs -- a 40 KB image was minutes of CPU
        in a single pattern, and pages carry several.
        """
        blob = "iVBORw0KGgoAAAANSUhEUg" * 10_000  # ~220 KB, no dots

        start = time.monotonic()
        ats.fingerprint(blob)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_markup_is_bounded_before_scanning(self):
        """23 patterns over an unbounded body blocks the whole pool: the GIL
        means one thread scanning holds up the other eleven."""
        self.assertLessEqual(ats._MAX_MARKUP, 2_000_000)


class FingerprintTest(unittest.TestCase):
    def test_greenhouse_api_version_is_not_a_board(self):
        hit = ats.fingerprint('src="https://boards-api.greenhouse.io/v1/boards/optiver"')
        self.assertEqual(hit[:2], ("greenhouse", "optiver"))

    def test_a_workday_site_called_careers_is_kept(self):
        """The site component is not a host, and "Careers" is what most of
        them are called -- LSEG, Fortress and PJT Partners among them."""
        hit = ats.fingerprint('href="https://lseg.wd3.myworkdayjobs.com/en-US/Careers"')
        self.assertEqual(hit[:2], ("workday", "lseg|wd3|Careers"))

    def test_workday_needs_tenant_datacentre_and_site(self):
        """A tenant alone builds a URL that 404s on every poll."""
        hit = ats.fingerprint('href="https://abrdn.wd3.myworkdayjobs.com/en-US/abrdncareers"')
        self.assertEqual(hit[:2], ("workday", "abrdn|wd3|abrdncareers"))

    def test_infrastructure_host_is_not_a_board(self):
        """`www.teamtailor.com` fits the board shape and gave Lynx board "www"."""
        hit = ats.fingerprint('<script src="https://www.teamtailor.com/widget.js">')
        self.assertEqual(hit[0], "teamtailor")
        self.assertIsNone(hit[1])

    def test_a_compound_infrastructure_host_is_not_a_board(self):
        """`assets-cdn.breezy.hr` polled as a board and returned HTML."""
        hit = ats.fingerprint('<img src="https://assets-cdn.breezy.hr/logo.png">')
        self.assertEqual(hit[0], "breezy")
        self.assertIsNone(hit[1])

    def test_a_vendor_shared_host_is_not_a_board(self):
        """`career.emply.com` was claimed by five unrelated Danish firms."""
        hit = ats.fingerprint('<a href="https://career.emply.com/apply">')
        self.assertEqual(hit[0], "emply")
        self.assertIsNone(hit[1])

    def test_a_hyphenated_board_name_survives(self):
        """The rule rejects only tokens where every piece is infrastructure."""
        hit = ats.fingerprint('<a href="https://jane-street.breezy.hr/">')
        self.assertEqual(hit[:2], ("breezy", "jane-street"))

    def test_the_real_board_is_preferred_over_infrastructure(self):
        """Rejecting a match must not stop the scan -- the board is often the
        next match on the same page."""
        markup = (
            '<img src="https://assets-cdn.breezy.hr/logo.png">'
            '<a href="https://optiver.breezy.hr/">Careers</a>'
        )
        self.assertEqual(ats.fingerprint(markup)[:2], ("breezy", "optiver"))


if __name__ == "__main__":
    unittest.main()
