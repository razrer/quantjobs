"""The board's own gates, where the evidence is the employer rather than the row.

`board_profiles` reads `(ats, token)`, which is the right unit for a firm's own
board and useless for a national portal: every MyCareersFuture posting shares
one token, so the profile is of the portal rather than of anyone hiring. The
noise in Singapore is employer-shaped -- agencies posting thousands of ads of
which the tagger reads none as markets work -- so the employer is the unit
there.
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
import build_data  # noqa: E402


def _database(rows) -> sqlite3.Connection:
    """`rows` is (employer, relevance, n) -- n postings at that verdict."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        "CREATE TABLE jobs (ats TEXT, token TEXT, job_id TEXT, employer TEXT,"
        " removed_at TEXT);"
        "CREATE TABLE job_tags (ats TEXT, token TEXT, job_id TEXT,"
        " dimension TEXT, value TEXT, tagger INTEGER);"
    )
    n = 0
    for employer, relevance, count in rows:
        for _ in range(count):
            n += 1
            key = ("mycareersfuture", "sg", f"job{n}")
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, NULL)", (*key, employer))
            connection.execute(
                "INSERT INTO job_tags VALUES (?, ?, ?, 'relevance', ?, 99)",
                (*key, relevance))
    connection.commit()
    return connection


class EmployerProfileTest(unittest.TestCase):
    def test_an_agency_the_tagger_never_reads_as_markets_is_non_markets(self):
        """`RECRUIT EXPRESS PTE LTD` publishes 6,323 postings and the tagger
        reads nine as markets work."""
        connection = _database([("AGENCY", "rejected", 40)])
        self.assertEqual(
            build_data.employer_profiles(connection, 99).get("AGENCY"),
            "non_markets")

    def test_an_employer_below_the_floor_is_not_profiled_at_all(self):
        """`lexicon.MIN_BOARD` is 10, and failing towards keeping is the
        direction this project picks: an employer we have barely seen is not
        thereby a non-markets one."""
        connection = _database([("SMALL", "rejected", 4)])
        self.assertNotIn("SMALL", build_data.employer_profiles(connection, 99))

    def test_an_employer_with_real_desks_is_never_non_markets(self):
        connection = _database([("BANK", "relevant", 20), ("BANK", "rejected", 10)])
        self.assertEqual(
            build_data.employer_profiles(connection, 99).get("BANK"), "markets")

    def test_the_tagger_version_is_honoured(self):
        """A profile drawn across versions would mix two classifiers."""
        connection = _database([("AGENCY", "rejected", 40)])
        self.assertEqual(build_data.employer_profiles(connection, 98), {})

    def test_a_blank_employer_is_never_a_profile(self):
        """Most of the corpus reaches the board through a firm's own board and
        sets no employer; grouping those together would profile "everyone"."""
        connection = _database([("", "rejected", 40), ("   ", "rejected", 40)])
        self.assertEqual(build_data.employer_profiles(connection, 99), {})


class TheGateNeedsTwoPiecesOfEvidenceTest(unittest.TestCase):
    """The employer profile alone never removes a posting.

    `non_markets_employer` fires only where the tagger *also* had nothing to
    say. `RECRUIT EXPRESS` has nine postings rated positively and all nine
    survive its own `non_markets` profile, because they are rated rather than
    `unknown` -- the same double test `non_markets_board` has made since it
    went in.
    """

    def test_the_reason_is_in_the_gate_table_so_it_is_counted(self):
        self.assertIn("non_markets_employer", build_data.GATES)

    def test_it_is_listed_after_the_board_profile(self):
        """`hit` takes the first reason that matches, and a posting removable
        for a sharper reason should be attributed to that one."""
        reasons = list(build_data.GATES)
        self.assertLess(reasons.index("non_markets_board"),
                        reasons.index("non_markets_employer"))


class StillListedTest(unittest.TestCase):
    """The two gates that ask whether a posting is still on offer.

    Until they existed, nothing on the board asked: `jobs` rows are never
    deleted and `removed_at` is written by `jobstream` alone, so a posting
    whose board stopped listing it stayed on the page for as long as the
    database did. **30,522 of 138,961 live Layer 3 postings** were in that
    state when this was measured.
    """

    BOARDS = {("greenhouse", "janestreet"), ("jobtech", "se")}

    @staticmethod
    def _row(ats, token, last_seen):
        return {"ats": ats, "token": token, "last_seen": last_seen}

    _DEFAULT_READS = {("greenhouse", "janestreet"): "2026-08-31"}

    def _call(self, row, last_read=_DEFAULT_READS):
        # Bound as a default rather than `last_read or ...`, because an empty
        # dict is falsy and a test passing one means it, which is the case
        # below.
        return build_data.still_listed(row, last_read, self.BOARDS)

    def test_a_posting_absent_from_the_latest_read_is_withdrawn(self):
        row = self._row("greenhouse", "janestreet", "2026-08-20")
        self.assertEqual(self._call(row), "withdrawn")

    def test_a_posting_present_in_the_latest_read_is_kept(self):
        row = self._row("greenhouse", "janestreet", "2026-08-31")
        self.assertIsNone(self._call(row))

    def test_a_board_we_no_longer_poll_is_retired(self):
        """What makes a board switch safe.

        When SIG moved from the classic iCIMS portal to its career site, the
        269 rows under the old token would otherwise have sat beside the new
        ones forever -- a board nobody polls never reports a withdrawal.
        """
        row = self._row("icims", "sig", "2026-08-31")
        self.assertEqual(self._call(row), "retired_board")

    def test_a_delta_source_is_never_touched(self):
        """The whole safety argument, and it is one line in the rule.

        `jobtech` is a delta feed and `jobindex --since` tops up from where the
        data reaches, so a poll refreshes only what changed. "Absent from the
        latest poll" there is most of a perfectly live board, and applying this
        rule to them would empty Sweden and Denmark on the next build.
        """
        row = self._row("jobtech", "se", "2026-07-01")
        self.assertIsNone(self._call(row, {("jobtech", "se"): "2026-08-31"}))

    def test_a_board_with_no_recorded_read_is_kept(self):
        """Failure-safe: a poll that fails writes nothing and moves nothing."""
        row = self._row("greenhouse", "janestreet", "2026-08-20")
        self.assertIsNone(self._call(row, {}))

    def test_nothing_here_reads_a_clock(self):
        """An age threshold would fire on the absence of evidence.

        A gate that removes cards because a run was simply not made is the one
        thing every gate on this page is forbidden to be. The rule compares a
        posting against its own board and against nothing else, so a board
        untouched for a year keeps every card it has.
        """
        old = self._row("greenhouse", "janestreet", "2020-01-01")
        self.assertIsNone(self._call(old, {("greenhouse", "janestreet"): "2020-01-01"}))


class BoardDomainsTest(unittest.TestCase):
    """One board belongs to one firm, and the token says which.

    `jobs` upserts on `(ats, token, job_id)` and never moves `domain`, so a
    board reached under two domains keeps its rows split between them -- which
    made Barclays' Workday board two firms on the page, the big half named
    `Barclaycardus` after a US card brand. That is not only a bad label: it is
    the name a cross-source fold would have to match, so the internship stayed
    on the board twice.
    """

    def _db(self, rows):
        """`rows` is (ats, token, domain, n)."""
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE jobs (ats TEXT, token TEXT, domain TEXT, removed_at TEXT)")
        for ats, token, domain, n in rows:
            connection.executemany(
                "INSERT INTO jobs VALUES (?, ?, ?, NULL)", [(ats, token, domain)] * n)
        return connection

    def test_the_token_names_the_domain_even_against_the_majority(self):
        """Barclays, and eight more like it: `cards.barclaycardus.com` brought
        1,557 rows to `home.barclays`'s 3 and is still not the firm."""
        chosen = build_data.board_domains(self._db([
            ("workday", "barclays|wd3|External_Career_Site_Barclays",
             "cards.barclaycardus.com", 40),
            ("workday", "barclays|wd3|External_Career_Site_Barclays", "home.barclays", 3),
        ]))
        self.assertEqual(chosen[("workday", "barclays|wd3|External_Career_Site_Barclays")],
                         "home.barclays")

    def test_vendor_furniture_in_the_token_names_nothing(self):
        """`careers.sig.com` is a real board on a firm's own host, so a token
        containing `careers` must not pick a domain for saying so."""
        chosen = build_data.board_domains(self._db([
            ("ashby", "acme-careers", "careers.example.com", 2),
            ("ashby", "acme-careers", "acme.com", 9),
        ]))
        self.assertEqual(chosen[("ashby", "acme-careers")], "acme.com")

    def test_the_parent_brand_wins_when_the_token_names_neither(self):
        """Marsh's board is `mmc|wd1|MMC`, which matches neither domain. The
        majority alone renamed fifteen `Marsh` cards `Mma Asset Management`."""
        chosen = build_data.board_domains(self._db([
            ("workday", "mmc|wd1|MMC", "marshmma.com", 62),
            ("workday", "mmc|wd1|MMC", "marsh.com", 15),
        ]))
        self.assertEqual(chosen[("workday", "mmc|wd1|MMC")], "marsh.com")

    def test_otherwise_the_majority_keeps_it(self):
        """Unchanged behaviour where nothing else decides -- `usbank|wd1` names
        neither `btig.com` nor `elavon.com`, and none is a form of another."""
        chosen = build_data.board_domains(self._db([
            ("workday", "usbank|wd1|US_Bank_Careers", "usbank.com", 30),
            ("workday", "usbank|wd1|US_Bank_Careers", "btig.com", 20),
            ("workday", "usbank|wd1|US_Bank_Careers", "elavon.com", 2),
        ]))
        self.assertEqual(chosen[("workday", "usbank|wd1|US_Bank_Careers")], "usbank.com")

    def test_a_board_with_one_domain_is_left_alone(self):
        self.assertEqual(build_data.board_domains(
            self._db([("workday", "acme|wd1|X", "acme.com", 5)])), {})

    def test_a_national_board_is_never_remapped(self):
        """One token there is a whole country and the domain is the individual
        employer's, which is the point of it -- Jobindex publishes
        `company.homeurl` on 20,483 rows under the single token `denmark`."""
        self.assertEqual(build_data.board_domains(self._db([
            ("jobindex", "denmark", "novonordisk.dk", 70),
            ("jobindex", "denmark", "danskebank.com", 40),
        ])), {})


if __name__ == "__main__":
    unittest.main()
