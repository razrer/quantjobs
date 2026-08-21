"""Stage 8's exit criterion, as a test.

"Deliberately breaking a parser produces an alert rather than a quiet zero."
The interesting cases are the ones a fixed `MIN_EXPECTED` floor sails past.
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from quantscraper import alerts, cli, db


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


if __name__ == "__main__":
    unittest.main()
