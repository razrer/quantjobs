"""Regression tests for `audit --pipeline`.

The universe audit and the job pipeline are different measurements, and the
gap between them went unnoticed for a long time: every focus hub reported 100%
*present* while 147 of 163 roster firms produced no postings at all. This
measurement is the one that chooses work now, so the ways it can flatter
itself are worth pinning.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest

from quantscraper import audit


def _entry(hub, name, priority=audit.FOCUS, status="active"):
    return audit.Entry(
        hub=hub, priority=priority, name=name, aliases=(), status=status, note=""
    )


class _Target:
    """The shape `discover.roster_targets` returns."""

    def __init__(self, label, names, domain=None):
        self.label, self.names, self.domain = label, names, domain


def _jobs(rows):
    """(domain, employer), or (domain, employer, ats, removed_at) to say more."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE jobs"
        " (domain TEXT, employer TEXT, ats TEXT, removed_at TEXT, token TEXT)"
    )
    connection.executemany(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?)",
        [
            (*row, *(("greenhouse", None) if len(row) == 2 else ()), row[0])
            for row in rows
        ],
    )
    return connection


class HubCountingTest(unittest.TestCase):
    def test_a_firm_hiring_in_four_hubs_counts_in_all_four(self):
        """`roster_targets` dedupes; the hub rates must not inherit that.

        Jane Street occupies four roster lines because it hires in four hubs.
        Probing it once is right; reporting it in one hub is not, because "is
        Hong Kong covered" is a question about Hong Kong.
        """
        roster = [
            _entry("Hong Kong", "Jane Street"),
            _entry("Amsterdam", "Jane Street"),
            _entry("Singapore", "Jane Street"),
        ]
        targets = [_Target("Jane Street", ("Jane Street",), "janestreet.com")]
        connection = _jobs([("janestreet.com", None)] * 5)

        results = audit.pipeline(connection, targets, roster)
        self.assertEqual(len(results), 3)
        self.assertEqual({r.entry.hub for r in results if r.polled},
                         {"Hong Kong", "Amsterdam", "Singapore"})

        report = audit.format_pipeline(results)
        # ...and the headline dedupes again, so it stays a count of firms.
        self.assertIn("1/1 roster firms have a board", report)
        self.assertIn("1 produce postings today", report)

    def test_a_stale_roster_line_is_not_a_miss(self):
        roster = [_entry("Stockholm", "Gone Capital", status="stale")]
        results = audit.pipeline(_jobs([]), [], roster)
        self.assertEqual(results, [])


class BoardVersusPortalTest(unittest.TestCase):
    """A national portal naming a firm is not a board we read.

    The two were netted together, and firms reported as reached while nothing
    read their boards -- which emptied the one list this report exists to
    produce.
    """

    def test_postings_on_the_firms_own_board_count(self):
        roster = [_entry("Copenhagen", "Danske Bank")]
        targets = [_Target("Danske Bank", ("Danske Bank",), "danskebank.dk")]
        connection = _jobs([("danskebank.dk", None, "oracle_hcm", None)] * 3)
        result = audit.pipeline(connection, targets, roster)[0]
        self.assertEqual((result.postings, result.portal), (3, 0))
        self.assertTrue(result.reached)

    def test_a_firm_seen_only_by_advertiser_name_is_not_reached(self):
        roster = [_entry("Stockholm", "Lynx")]
        targets = [_Target("Lynx", ("Lynx Asset Management",), None)]
        connection = _jobs([(None, "Lynx Asset Management AB", "jobtech", None)] * 2)
        result = audit.pipeline(connection, targets, roster)[0]
        self.assertEqual((result.postings, result.portal), (0, 2))
        self.assertFalse(result.reached)

        report = audit.format_pipeline([result])
        self.assertIn("0/1 roster firms have a board", report)
        self.assertIn("1 more seen only on a national portal", report)
        self.assertIn("no pollable board", report)

    def test_a_portal_advert_carrying_the_firms_domain_is_not_its_board(self):
        """Some portal adverts resolve a URL, so `domain` alone proves nothing."""
        roster = [_entry("Stockholm", "Nordkinn")]
        targets = [_Target("Nordkinn", ("Nordkinn",), "nordkinn.se")]
        connection = _jobs([("nordkinn.se", None, "jobtech", None)] * 4)
        result = audit.pipeline(connection, targets, roster)[0]
        self.assertEqual((result.postings, result.portal), (0, 4))
        self.assertFalse(result.reached)

    def test_a_firm_with_both_reports_both_without_adding_them(self):
        roster = [_entry("Stockholm", "Nordea")]
        targets = [_Target("Nordea", ("Nordea",), "nordea.com")]
        connection = _jobs(
            [("nordea.com", None, "site", None)]
            + [(None, "Nordea Bank Abp", "jobtech", None)] * 9
        )
        result = audit.pipeline(connection, targets, roster)[0]
        self.assertEqual((result.postings, result.portal), (1, 9))

    def test_a_withdrawn_posting_counts_for_nothing(self):
        """Postings are kept forever; "today" has to mean today."""
        roster = [_entry("Stockholm", "Nordea")]
        targets = [_Target("Nordea", ("Nordea",), "nordea.com")]
        connection = _jobs([("nordea.com", None, "site", "2026-01-01")] * 5)
        self.assertEqual(audit.pipeline(connection, targets, roster)[0].postings, 0)

    def test_postings_filed_under_a_sibling_domain_still_count(self):
        """One board, several domains: Danske's 500 sit under `danica.dk`."""
        roster = [_entry("Copenhagen", "Danske Bank")]
        targets = [_Target("Danske Bank", ("Danske Bank",), "danskebank.dk")]
        connection = _jobs([])
        connection.executemany(
            "INSERT INTO jobs VALUES ('danica.dk', NULL, 'oracle_hcm', NULL, 'danske')",
            [()] * 7,
        )
        connection.execute(
            "CREATE TABLE ats_resolution (domain TEXT, ats TEXT, token TEXT, tier TEXT)"
        )
        connection.execute(
            "INSERT INTO ats_resolution VALUES"
            " ('danskebank.dk', 'oracle_hcm', 'danske', 'A')"
        )
        result = audit.pipeline(connection, targets, roster)[0]
        self.assertEqual(result.postings, 7)
        self.assertTrue(result.polled)

    def test_a_portal_token_is_not_a_pollable_board(self):
        roster = [_entry("Stockholm", "Nordkinn")]
        targets = [_Target("Nordkinn", ("Nordkinn",), "nordkinn.se")]
        connection = _jobs([])
        connection.execute(
            "CREATE TABLE ats_resolution (domain TEXT, ats TEXT, token TEXT, tier TEXT)"
        )
        connection.execute(
            "INSERT INTO ats_resolution VALUES ('nordkinn.se', 'jobtech', 'x', 'A')"
        )
        self.assertFalse(audit.pipeline(connection, targets, roster)[0].board)


class ReportTest(unittest.TestCase):
    def test_the_misses_are_named_not_merely_counted(self):
        roster = [_entry("Stockholm", "Brummer & Partners"), _entry("Stockholm", "Lynx")]
        targets = [
            _Target("Brummer & Partners", ("Brummer",), "brummer.se"),
            _Target("Lynx", ("Lynx",), "lynxhedge.se"),
        ]
        report = audit.format_pipeline(
            audit.pipeline(_jobs([("lynxhedge.se", None)]), targets, roster)
        )
        self.assertIn("Brummer & Partners", report)
        self.assertIn("brummer.se", report)
        self.assertNotIn("lynxhedge.se", report)

    def test_a_deprioritized_hub_never_reaches_the_miss_list(self):
        """The list is a work queue, and deprioritized work is not queued."""
        roster = [_entry("London", "Winton", priority="deprioritized")]
        targets = [_Target("Winton", ("Winton",), "winton.com")]
        report = audit.format_pipeline(audit.pipeline(_jobs([]), targets, roster))
        self.assertIn("deprioritized hubs", report)
        self.assertNotIn("Winton", report.split("producing nothing")[-1])



class ReachedVersusProducingTest(unittest.TestCase):
    """A firm with a working reader and no openings is covered, not missing.

    Netting the two together hides both: it would either report Captor as a
    coverage gap -- sending someone to build a reader that already exists --
    or report it as covered while a genuinely unreachable firm hid behind the
    same number.
    """

    def _reader_but_no_openings(self):
        roster = [_entry("Stockholm", "Captor")]
        targets = [_Target("Captor", ("Captor",), "captor.se")]
        connection = _jobs([])
        connection.execute(
            "CREATE TABLE ats_resolution (domain TEXT, ats TEXT, token TEXT, tier TEXT)"
        )
        connection.execute(
            "INSERT INTO ats_resolution VALUES ('captor.se', 'site', 'captor', 'A')"
        )
        return audit.pipeline(connection, targets, roster)

    def test_a_board_with_no_openings_counts_as_reached(self):
        result = self._reader_but_no_openings()[0]
        self.assertTrue(result.board)
        self.assertFalse(result.polled)

    def test_and_is_kept_out_of_the_work_list(self):
        report = audit.format_pipeline(self._reader_but_no_openings())
        self.assertNotIn("no pollable board", report)
        self.assertIn("nothing posted today", report)

    def test_a_firm_with_no_board_at_all_is_still_work(self):
        roster = [_entry("Stockholm", "Nordkinn")]
        targets = [_Target("Nordkinn", ("Nordkinn",), "nordkinn.se")]
        connection = _jobs([])
        connection.execute(
            "CREATE TABLE ats_resolution (domain TEXT, ats TEXT, token TEXT, tier TEXT)"
        )
        report = audit.format_pipeline(audit.pipeline(connection, targets, roster))
        self.assertIn("no pollable board", report)
        self.assertIn("Nordkinn", report)

    def test_a_tier_a_row_with_no_token_does_not_count_as_reached(self):
        """A board nobody can poll is not a board. 98 rows sat in that state."""
        roster = [_entry("Copenhagen", "PFA")]
        targets = [_Target("PFA", ("PFA",), "pfa.dk")]
        connection = _jobs([])
        connection.execute(
            "CREATE TABLE ats_resolution (domain TEXT, ats TEXT, token TEXT, tier TEXT)"
        )
        connection.execute(
            "INSERT INTO ats_resolution VALUES ('pfa.dk', 'successfactors', NULL, 'A')"
        )
        self.assertFalse(audit.pipeline(connection, targets, roster)[0].board)


if __name__ == "__main__":
    unittest.main()
