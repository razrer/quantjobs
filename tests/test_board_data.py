"""The board's own gates, where the evidence is the employer rather than the row.

`board_profiles` reads `(ats, token)`, which is the right unit for a firm's own
board and useless for a national portal: every MyCareersFuture posting shares
one token, so the profile is of the portal rather than of anyone hiring. The
noise in Singapore is employer-shaped -- agencies posting thousands of ads of
which the tagger reads none as markets work -- so the employer is the unit
there.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
import build_data  # noqa: E402
import publish  # noqa: E402


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



class UnreadCensusCardTest(unittest.TestCase):
    """Hong Kong's statutory board, where an unreadable card is noise.

    `non_markets_employer` is how a national portal's noise comes off the
    board -- profile the employer, because one token carries a whole territory.
    That works for Singapore and **cannot** work for Hong Kong, whose portal
    publishes an employer name nowhere on either list view. So the noise there
    has nothing to profile and needs the source-level answer.

    Measured before it went in: of 13,465 live Hong Kong postings from that
    portal, **six** are rated above `unknown`, against 277 from 1,789 postings
    on the firms' own boards in the same hub -- 0.04% against 15.5%.
    """

    def test_an_unreadable_card_from_the_census_is_noise(self):
        self.assertTrue(build_data.unread_census("iesjobs", "unknown"))

    def test_a_rated_card_survives_however_bad_the_source_average_is(self):
        """This is the whole safety argument, and it is the second half.

        All six of Hong Kong's rated postings stay -- including
        `Quantitative Researcher (QR)` and `Quantitative Developer (QD)`, which
        exist nowhere else in the corpus.
        """
        for verdict in ("relevant", "less_relevant", "adjacent"):
            self.assertFalse(build_data.unread_census("iesjobs", verdict), verdict)

    def test_it_touches_no_other_source(self):
        """An unreadable card elsewhere is a gap to close, not noise to drop.

        Singapore's `unknown` bucket was measured the other way -- a vocabulary
        gap holding real work, only 8% of it missing a usable description -- so
        the same rule there would delete jobs.
        """
        for ats in ("mycareersfuture", "jobbsafari", "jobindex", "workday",
                    "greenhouse", "jobroom", "jobtech"):
            self.assertFalse(build_data.unread_census(ats, "unknown"), ats)

    def test_it_is_counted_on_every_build(self):
        """One total would hide which gate ate a hub -- so it needs a name."""
        self.assertIn("unread_census_card", build_data.GATES)

    def test_it_is_not_an_exclusion_reason(self):
        """It is a fact about our reading, not about the posting.

        `tagging.GATES` is what `labels._candidates` builds a labelling frame
        from, so a reason that is not an `exclusion_reason` must stay out of it
        -- exactly as `rejected`, `non_markets_board` and `hand_rejected` do.
        """
        from quantscraper import tagging
        self.assertNotIn("unread_census_card", tagging.GATES)


class TheBuildRefusesToShipNothingTest(unittest.TestCase):
    """**Principle 2, on the one step that ships.** `MIN_EXPECTED` guards every
    registry and every national board because a source that returns zero rows
    with HTTP 200 is more dangerous than one that crashes -- and the file the
    reader actually looks at had no such floor.

    It is not hypothetical. `tagging.TAGGER` was bumped, the re-tag had not
    run, every posting fell out as `untagged`, and `main` wrote a 0-posting
    `data.js` and returned normally; `publish.py` checks the file exists and
    that the CLI printed no error, so it would have uploaded it. `daily` runs
    `tag` in a phase where a failing step is logged and the run continues, and
    then rebuilds and publishes, which is the route.
    """

    def _payload(self, cards):
        return "window.BOARD = " + json.dumps(
            {"built": "now", "tagger": 1, "firms": {}, "jobs": [{"id": str(n)} for n in range(cards)]}
        ) + ";\n"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "data.js"

    def test_a_full_board_passes(self):
        self.path.write_text(self._payload(build_data.MIN_CARDS), encoding="utf-8")
        publish._check(self.path, build_data.MIN_CARDS)  # does not raise

    def test_an_empty_board_is_refused_before_anything_is_uploaded(self):
        self.path.write_text(self._payload(0), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            publish._check(self.path, build_data.MIN_CARDS)
        self.assertIn("REFUSED", str(caught.exception))

    def test_a_thin_board_is_refused_too(self):
        self.path.write_text(self._payload(build_data.MIN_CARDS - 1), encoding="utf-8")
        with self.assertRaises(SystemExit):
            publish._check(self.path, build_data.MIN_CARDS)

    def test_the_floor_sits_well_below_any_real_board(self):
        """A catastrophe check, not a regression check: the recorded range is
        4,211 to 8,513 cards, so a board that halves is a story and a board
        that empties is a broken pipeline."""
        self.assertLess(build_data.MIN_CARDS, 4_211 // 4)


if __name__ == "__main__":
    unittest.main()
