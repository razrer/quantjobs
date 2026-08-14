"""Regression tests for Stage 10, coverage measurement.

The thing being defended is the refusal. An estimator that always returns a
number is worse than one that sometimes declines, because the number it
returns from no evidence looks exactly like the number it returns from good
evidence.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest

from quantscraper import coverage, db, tagging


class ChapmanTest(unittest.TestCase):
    def test_it_is_defined_at_zero_overlap_which_is_why_it_is_guarded(self):
        """Plain Lincoln-Petersen divides by zero and crashes, which is honest.
        Chapman returns 110 from nothing, which is not."""
        self.assertEqual(coverage._chapman(36, 2, 0), 110)

    def test_a_full_overlap_estimates_the_sample_itself(self):
        self.assertEqual(coverage._chapman(50, 50, 50), 50)


class EstimateTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(db.SCHEMA)
        self.connection.executescript(tagging.SCHEMA)
        self.connection.executescript(
            "CREATE TABLE domain_lookups (query TEXT, domain TEXT, method TEXT,"
            " evidence TEXT, checked_at TEXT)"
        )

    def tearDown(self):
        self.connection.close()

    def _posting(self, ats, domain, job_id):
        self.connection.execute(
            "INSERT INTO jobs (ats, token, job_id, domain, title, first_seen,"
            " last_seen) VALUES (?, 'b', ?, ?, 't', '2026-01-01', '2026-01-01')",
            (ats, job_id, domain),
        )
        self.connection.execute(
            "INSERT INTO domain_lookups (query, domain, method, evidence,"
            " checked_at) VALUES (?, ?, 'name-strong', '', '2026-01-01')",
            (domain, domain),
        )
        if ats != coverage.SECOND_SOURCE:
            self.connection.execute(
                "INSERT INTO job_tags (ats, token, job_id, dimension, value,"
                " confidence, evidence, tagger, tagged_at)"
                " VALUES (?, 'b', ?, 'hub', ?, 'strong', '', ?, '2026-01-01')",
                (ats, job_id, coverage.SECOND_SOURCE_HUB, tagging.TAGGER),
            )

    def test_a_thin_overlap_is_refused_not_reported(self):
        for n in range(3):
            self._posting("greenhouse", f"firm{n}.se", str(n))
            self._posting(coverage.SECOND_SOURCE, f"other{n}.se", f"j{n}")

        result = coverage.estimate(self.connection)

        self.assertEqual(result.overlap, 0)
        self.assertIsNone(result.population)
        self.assertIsNone(result.share)
        self.assertIn("below", result.reason)

    def test_a_real_overlap_produces_an_estimate(self):
        for n in range(10):
            self._posting("greenhouse", f"firm{n}.se", str(n))
        for n in range(8):
            self._posting(coverage.SECOND_SOURCE, f"firm{n}.se", f"j{n}")

        result = coverage.estimate(self.connection)

        self.assertGreaterEqual(result.overlap, coverage.MIN_OVERLAP)
        self.assertIsNotNone(result.population)
        self.assertGreater(result.share, 0)

    def test_the_second_source_is_cut_to_our_own_universe(self):
        """A national feed carries waiting staff and care homes. Estimating one
        population from two differently scoped frames measures neither."""
        self._posting(coverage.SECOND_SOURCE, "restaurant.se", "j1")
        self.connection.execute("DELETE FROM domain_lookups WHERE domain = ?",
                                ("restaurant.se",))

        self.assertEqual(coverage.estimate(self.connection).theirs, 0)


if __name__ == "__main__":
    unittest.main()
