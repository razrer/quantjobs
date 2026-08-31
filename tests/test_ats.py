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

from quantscraper import ats, db


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


class CaptureOffByOneTest(unittest.TestCase):
    """A capture that lands one segment early is the quiet kind of wrong.

    The token is well-formed, the row reads tier A everywhere, and the board it
    names either does not exist or already belongs to somebody else.
    """

    def test_a_workday_locale_written_with_an_underscore_is_not_the_site(self):
        """`mmc|wd1|en_US` 404s on every poll; `mmc|wd1|MMC` holds 2,437."""
        self.assertEqual(
            ats.fingerprint("https://mmc.wd1.myworkdayjobs.com/en_US/MMC")[1],
            "mmc|wd1|MMC",
        )

    def test_the_hyphenated_locale_still_works(self):
        self.assertEqual(
            ats.fingerprint("https://juliusbaer.wd3.myworkdayjobs.com/en-US/External")[1],
            "juliusbaer|wd3|External",
        )

    def test_a_workable_job_page_is_not_a_board(self):
        """`apply.workable.com/j/{shortcode}` is one posting.

        Read as the board `j` and recorded against two unrelated domains at
        once, which is the same "several firms agree on it" signal `tbe` and
        `__assets__` were found by.
        """
        self.assertIsNone(ats.fingerprint("https://apply.workable.com/j/AB12CD34EF"))

    def test_a_workable_board_still_resolves(self):
        self.assertEqual(
            ats.fingerprint("https://apply.workable.com/optiver/")[1], "optiver"
        )

    def test_the_shared_taleo_business_edition_host_is_not_a_board(self):
        """Four unrelated domains claimed `tbe`, which is the vendor's."""
        self.assertIsNone(ats.fingerprint("https://tbe.taleo.net/CR07/ats/careers")[1])


class ReprobePopulationTest(unittest.TestCase):
    """A board resolved with a token and holding no postings is silent too.

    `reprobe_targets` covered tier B and tokenless tier A -- the two states
    CLAUDE.md calls "a board nobody can poll" -- and missed the larger one:
    167 rows sat tier A *with* a token, polling nothing, and no sweep revisited
    them because having a token is what both other clauses tested for. Three
    carried a `/` from a JSON island the escape table had since learned to
    undo, and four carried `tbe`, which it had since learned to refuse.
    """

    def _connection(self):
        connection = db.connect(":memory:")
        connection.executescript(ats.SCHEMA)
        return connection

    def _row(self, connection, domain, ats_name, token, tier="A", evidence="x"):
        connection.execute(
            "INSERT INTO ats_resolution"
            " (domain, careers_url, ats, token, tier, evidence, checked_at)"
            " VALUES (?, ?, ?, ?, ?, ?, '2026-08-31')",
            (domain, f"https://{domain}/", ats_name, token, tier, evidence),
        )
        connection.commit()

    def test_a_tier_a_board_with_no_postings_is_re_walked(self):
        connection = self._connection()
        self._row(connection, "varde.com", "taleo", "tbe")
        self.assertEqual(
            [r["domain"] for r in ats.reprobe_targets(connection, 10)], ["varde.com"]
        )

    def test_a_tier_a_board_that_produced_postings_is_left_alone(self):
        connection = self._connection()
        self._row(connection, "janestreet.com", "greenhouse", "janestreet")
        connection.execute(
            "INSERT INTO jobs (ats, token, job_id, title, first_seen, last_seen)"
            " VALUES ('greenhouse', 'janestreet', '1', 'Trader', 'x', 'x')"
        )
        connection.commit()
        self.assertEqual(ats.reprobe_targets(connection, 10), [])

    def test_a_hand_written_site_is_never_swept_up(self):
        """Captor and Norron advertise nothing, which is the answer their
        readers exist to give -- and the marker is the evidence string, because
        two thirds of `sites.py` names an extractor that already exists."""
        connection = self._connection()
        self._row(
            connection,
            "captor.se",
            "site",
            "captor",
            evidence="hand-written reader in sites.py (Captor)",
        )
        self._row(
            connection,
            "nasdaq.com",
            "workday",
            "nasdaq|wd1|Nasdaq_External",
            evidence="hand-verified board in sites.py (Nasdaq)",
        )
        self.assertEqual(ats.reprobe_targets(connection, 10), [])


class VendorPrecedenceTest(unittest.TestCase):
    """Which wins when a page names a board *and* serves one from its own host.

    It turns on the vendor. Same vendor and the named token wins -- Optiver's
    two hostnames are one board. Different vendor and the verified host wins,
    because the two are then different products and only one is live: iCIMS'
    career sites still print `careers-{token}.icims.com` for their login link,
    so the classic-portal pattern matched and won a board that is a 150-byte
    redirect stub.
    """

    MARKUP = (
        '<script src="https://app.jibecdn.com/prod/search/4.11.215/main.js"></script>'
        '<a href="https://careers-principal.icims.com/jobs/login">Sign in</a>'
    )

    def test_a_different_vendor_serving_the_feed_beats_the_named_token(self):
        with mock.patch.object(ats, "_serves_feed", return_value=True):
            hit = ats.fingerprint(self.MARKUP, "https://careers.principal.com/")
        self.assertEqual(hit[:2], ("icims_cs", "careers.principal.com"))

    def test_the_named_token_stands_when_the_host_serves_nothing(self):
        with mock.patch.object(ats, "_serves_feed", return_value=False):
            hit = ats.fingerprint(self.MARKUP, "https://careers.principal.com/")
        self.assertEqual(hit[:2], ("icims", "principal"))


class InfrastructureTokenTest(unittest.TestCase):
    """A vendor's own host recorded as a board polls nothing, forever.

    It is the quiet failure: the row reads tier A, every summary counts it as
    resolved, and the feed is silent because there is no board there.
    """

    def test_an_asset_path_with_underscores_is_not_a_board(self):
        """`jobs.jobvite.com/__assets__` was recorded against three unrelated
        firms at once -- Five Rings among them. `assets` was already on the
        list; only the underscores were hiding it."""
        self.assertTrue(ats._is_infrastructure("__assets__"))

    def test_one_infrastructure_piece_is_enough_when_it_is_unambiguous(self):
        """`vs-errors.eightfold.ai` survived the all-pieces rule, because
        `errors` is the vendor's error host and `vs` is nothing."""
        self.assertTrue(ats._is_infrastructure("vs-errors"))

    def test_a_hyphenated_firm_name_still_survives(self):
        """The all-pieces rule exists for these, and must keep working."""
        for token in ("jane-street", "da-vinci", "old-mission", "five-rings"):
            self.assertFalse(ats._is_infrastructure(token), token)

    def test_a_compound_workday_token_is_judged_on_its_tenant(self):
        """The site half is very often literally called `Careers`."""
        self.assertFalse(ats._is_infrastructure("lseg|wd3|LSEG_Careers"))
        self.assertFalse(
            ats._is_infrastructure("brevanhoward|wd3|BH_ExternalCareers|myworkdaysite.com")
        )

    def test_the_fingerprinter_skips_past_an_asset_path_to_a_real_board(self):
        markup = (
            '<script src="https://jobs.jobvite.com/__assets__/scripts/x.js">'
            '<a href="https://jobs.jobvite.com/quantlab/jobs">Careers</a>'
        )
        self.assertEqual(ats.fingerprint(markup)[:2], ("jobvite", "quantlab"))


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
