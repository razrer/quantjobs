"""Stage 8's exit criterion, as a test.

"Deliberately breaking a parser produces an alert rather than a quiet zero."
The interesting cases are the ones a fixed `MIN_EXPECTED` floor sails past.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quantscraper import alerts, cli, db, lexicon, tagging


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _run(connection, source, count, ok=True, error=None, days_ago=0):
    started = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(
        timespec="seconds"
    )
    db.record_run(connection, source, started, count, ok=ok, error=error)


class BreakageTest(unittest.TestCase):
    def test_a_parser_returning_nothing_is_flagged(self):
        connection = _memory(self)
        for _ in range(3):
            _run(connection, "fi_se", 650)
        _run(connection, "fi_se", 0)

        kinds = {a.kind for a in alerts.check(connection)}
        self.assertIn("empty", kinds)

    def test_a_collapse_that_clears_min_expected_is_still_flagged(self):
        """The case a fixed floor cannot catch.

        Finanstilsynet normally returns 26,495 and declares MIN_EXPECTED of
        15,000. A parser that breaks and returns 16,000 passes the floor while
        having lost 40% of the register.
        """
        connection = _memory(self)
        for _ in range(3):
            _run(connection, "finanstilsynet_dk", 26_495)
        _run(connection, "finanstilsynet_dk", 16_000)

        shrank = [a for a in alerts.check(connection) if a.kind == "shrank"]
        self.assertEqual(len(shrank), 1, "a 40% collapse above the floor went unnoticed")
        self.assertIn("16,000", shrank[0].detail)

    def test_a_failed_fetch_is_reported(self):
        connection = _memory(self)
        _run(connection, "eurex", 330)
        _run(connection, "eurex", 0, ok=False, error="HTTP 500")
        self.assertEqual([a.kind for a in alerts.check(connection)], ["fail"])

    def test_normal_variation_is_not_flagged(self):
        """An alert that cries wolf gets ignored, which is worse than none."""
        connection = _memory(self)
        for count in (2705, 3715, 3700):
            _run(connection, "afm_nl", count)
        _run(connection, "afm_nl", 3690)
        self.assertEqual(alerts.check(connection), [])

    def test_one_bad_run_does_not_become_the_new_normal(self):
        """A mean would let a zero drag the baseline down far enough that the
        next broken run looks healthy. The median does not move."""
        connection = _memory(self)
        for _ in range(4):
            _run(connection, "sfc_hk", 3600)
        _run(connection, "sfc_hk", 0)
        _run(connection, "sfc_hk", 1200)

        kinds = {a.kind for a in alerts.check(connection)}
        self.assertIn("shrank", kinds, "the outlier moved the baseline")

    def test_a_single_run_is_not_judged(self):
        connection = _memory(self)
        _run(connection, "esma_eea", 12_332)
        self.assertEqual(alerts.check(connection), [])

    def test_a_source_that_stopped_running_is_flagged(self):
        connection = _memory(self)
        for _ in range(3):
            _run(connection, "cboe_europe", 52, days_ago=90)
        self.assertEqual([a.kind for a in alerts.check(connection)], ["stale"])

    def test_registries_that_never_ran_are_reported(self):
        connection = _memory(self)
        _run(connection, "fi_se", 650)
        self.assertIn("esma_eea", alerts.coverage(connection))


class Layer4PollsAreVisibleTest(unittest.TestCase):
    """The gap that let a whole national source hold zero rows in silence.

    `alerts` reads `runs`, and until the Swiss postings turned out to be
    missing, only the registry fetches wrote to it -- so a Layer 4 poller that
    collected nothing looked exactly like one nobody had asked about.
    """

    def test_a_full_sweep_is_recorded(self):
        connection = _memory(self)
        cli._record_poll(connection, "jobbsafari", db.now(), 48_173)
        row = connection.execute("SELECT source, row_count, ok FROM runs").fetchone()
        self.assertEqual((row["source"], row["row_count"], row["ok"]),
                         ("jobbsafari", 48_173, 1))

    def test_a_probe_or_a_top_up_is_not(self):
        """A baseline built from `--pages 2` would judge a full sweep against a
        sample of it -- the same reason `alerts` refuses to judge one run."""
        connection = _memory(self)
        cli._record_poll(connection, "jobbsafari", db.now(), 999, partial=True)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_a_truncated_walk_is_recorded_as_a_failure(self):
        connection = _memory(self)
        cli._record_poll(connection, "jobroom", db.now(), 19_999,
                         problem="22,900 advertised, 19,999 reachable")
        row = connection.execute("SELECT ok, error FROM runs").fetchone()
        self.assertEqual(row["ok"], 0)
        self.assertIn("19,999", row["error"])
        self.assertIn("fail", {a.kind for a in alerts.check(connection)})

    def test_a_national_board_that_stops_collecting_now_shows_up(self):
        connection = _memory(self)
        for _ in range(3):
            cli._record_poll(connection, "jobbsafari", db.now(), 48_000)
        cli._record_poll(connection, "jobbsafari", db.now(), 5_421)
        self.assertIn("shrank", {a.kind for a in alerts.check(connection)})


class CrashedPollsAreVisibleTest(unittest.TestCase):
    """The same gap one step along, and it cost Singapore.

    `_record_poll` runs *after* a sweep returns, so a sweep that **crashes**
    recorded nothing at all. MyCareersFuture died ~400 pages into a
    `daily --full` on an HTTP 429 having written 37,562 postings, `runs` held
    no row for it, and `alerts` printed `all sources healthy`.
    """

    def test_a_crashed_sweep_is_recorded_before_it_is_re_raised(self):
        connection = _memory(self)
        def sweep():
            raise urllib.error.HTTPError("https://x", 429, "", None, None)
        with self.assertRaises(urllib.error.HTTPError):
            cli._poll(connection, "mycareersfuture", sweep)
        row = connection.execute("SELECT source, row_count, ok, error FROM runs").fetchone()
        self.assertEqual((row["source"], row["row_count"], row["ok"]),
                         ("mycareersfuture", 0, 0))
        self.assertIn("429", row["error"])

    def test_alerts_stops_saying_healthy(self):
        connection = _memory(self)
        with self.assertRaises(RuntimeError):
            cli._poll(connection, "mycareersfuture",
                      lambda: (_ for _ in ()).throw(RuntimeError("HTTP Error 429: ")))
        self.assertIn("fail", {a.kind for a in alerts.check(connection)})

    def test_a_sweep_that_returns_is_untouched(self):
        """The wrapper must not record anything itself on the happy path --
        `_record_poll` owns that, and two rows per sweep would move the
        baseline `alerts` compares against."""
        connection = _memory(self)
        started, value = cli._poll(connection, "jobbsafari", lambda: "swept")
        self.assertEqual(value, "swept")
        self.assertTrue(started)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_every_layer_4_poller_goes_through_it(self):
        """A poller wired straight to its module is invisible when it crashes,
        which is exactly the state this test exists to keep out. Checked by
        reading the source, the same way `EveryFingerprintHasAReaderTest` does:
        the alternative is six near-identical network tests.

        Two ways in are allowed and both end in the same place: `_poll`
        directly, or `_sweep`, which is the shared open-poll-record wrapper the
        five portal commands use. The second clause is what keeps that from
        being a loophole -- `_sweep` is asserted to reach `_poll` itself."""
        source = Path(cli.__file__).read_text(encoding="utf-8")

        def body_of(name):
            start = source.index(f"def {name}(")
            end = source.find(chr(10) + "def ", start + 1)
            return source[start : end if end > 0 else len(source)]

        self.assertIn("_poll(", body_of("_sweep"), "_sweep stopped recording crashes")
        for command, module in (
            ("_singapore", "mycareersfuture"), ("_hongkong", "iesjobs"),
            ("_denmark", "jobindex"), ("_sweden", "jobbsafari"),
            ("_switzerland", "jobroom_ch"), ("_jobstream", "jobstream"),
        ):
            body = body_of(command)
            self.assertTrue(
                "_poll(" in body or "_sweep(" in body,
                f"{command} does not record a crash",
            )
            self.assertNotIn(f"= {module}.run(", body,
                             f"{command} calls {module}.run outside _poll")


class CoverageReachesLayer4Test(unittest.TestCase):
    """`check` cannot judge a source with no rows, so `coverage` is the
    backstop -- and it read `REGISTRIES` alone, which does not contain the
    national boards. MyCareersFuture was missing from both lists at once and
    `alerts` printed `all sources healthy` for ten days."""

    def test_a_national_board_that_never_ran_is_named(self):
        connection = _memory(self)
        self.assertIn("mycareersfuture", alerts.coverage(connection))

    def test_every_layer_4_poller_is_expected_to_report(self):
        for name in ("jobtech", "jobroom", "jobindex", "jobbsafari", "mycareersfuture"):
            self.assertIn(name, alerts._expected(), name)

    def test_a_board_that_has_run_is_not_named(self):
        connection = _memory(self)
        cli._record_poll(connection, "mycareersfuture", db.now(), 95_536)
        self.assertNotIn("mycareersfuture", alerts.coverage(connection))

    def test_the_registries_are_still_covered(self):
        from quantscraper.registries import REGISTRIES
        self.assertTrue(set(REGISTRIES) <= alerts._expected())


class AnUnbumpedLexiconIsLoudTest(unittest.TestCase):
    """`tag` visits only postings with no row at the current `TAGGER`, so a
    lexicon edited without a bump reports `tagged 0 postings` and every
    summary keeps serving the previous answers. `CLAUDE.md` has warned about
    it since the beginning and nothing detected it -- and it had happened:
    53 postings in the live database carried a verdict at version 58 that
    version 58's own code no longer produced."""

    def test_a_fingerprint_is_stable_across_calls(self):
        self.assertEqual(tagging.fingerprint(), tagging.fingerprint())

    def test_a_fingerprint_is_stable_across_processes(self):
        """**The failure that shipped first.** `_STOPWORD_LANGUAGES` is built by
        walking `frozenset`s, and set order follows string hashing, which
        Python randomises per process -- so the fingerprint differed on every
        run and the alert fired on a database that had *just* been re-tagged.
        An alert that always fires is worse than no alert, so this is pinned
        against a second interpreter rather than against a second call."""
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r);" % str(Path(tagging.__file__).parents[2])
             + " from quantscraper import tagging; print(tagging.fingerprint())"],
            capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": "random"},
        )
        self.assertEqual(out.stdout.strip(), tagging.fingerprint(), out.stderr)

    def test_a_changed_needle_list_changes_it(self):
        before = tagging.fingerprint()
        saved = lexicon.MARKETS
        try:
            lexicon.MARKETS = saved + ("a phrase nobody wrote",)
            self.assertNotEqual(tagging.fingerprint(), before)
        finally:
            lexicon.MARKETS = saved
        self.assertEqual(tagging.fingerprint(), before)

    def test_a_comment_is_free(self):
        """It hashes the needles, not the source, so a refactor costs nothing
        -- otherwise the alert would fire on every edit and be ignored."""
        before = tagging.fingerprint()
        tagging.__doc__ = (tagging.__doc__ or '') + chr(10) + 'an added sentence'
        self.assertEqual(tagging.fingerprint(), before)

    def test_an_unstamped_database_is_not_an_alert(self):
        """A database predating the stamp has nothing to compare against, and
        a guard that fires on the absence of evidence is the one thing every
        gate in this project is forbidden to be."""
        connection = _memory(self)
        connection.executescript(tagging.SCHEMA)
        self.assertIsNone(tagging.drifted(connection))
        self.assertEqual([a for a in alerts.check(connection) if a.kind == "lexicon"], [])

    def test_a_drifted_stamp_is_an_alert(self):
        connection = _memory(self)
        connection.executescript(tagging.SCHEMA)
        tagging._stamp(connection)
        self.assertIsNone(tagging.drifted(connection))
        connection.execute("UPDATE tagger_state SET lexicon = 'not-what-it-is-now'")
        self.assertEqual(tagging.drifted(connection), "not-what-it-is-now")
        self.assertEqual([a.kind for a in alerts.check(connection)], ["lexicon"])

    def test_a_run_that_tags_nothing_still_stamps(self):
        """The normal shape of this failure is a run with nothing to do: after
        an unbumped edit every posting already has a row at this version, so
        `postings` comes back empty. Returning early without stamping would
        leave the one case unrecorded."""
        connection = _memory(self)
        self.assertEqual(tagging.run(connection, 10), (0, 0))
        self.assertEqual(
            connection.execute("SELECT lexicon FROM tagger_state WHERE tagger = ?",
                               (tagging.TAGGER,)).fetchone()["lexicon"],
            tagging.fingerprint())


if __name__ == "__main__":
    unittest.main()
