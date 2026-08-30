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


if __name__ == "__main__":
    unittest.main()
