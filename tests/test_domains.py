"""Regression tests for the strong/weak grade on a resolved domain.

A wrong domain is worse than no domain: it points Layer 3 at somebody else's
careers page, so the feed goes quietly wrong rather than visibly empty. The
grade is the only thing standing between a guess and that outcome.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from quantscraper import domains


def _page(text: str) -> bytes:
    return f"<html><body><p>{text}</p></body></html>".encode()


class CorroborationTest(unittest.TestCase):
    """A two-word fragment is 74% of every strong match, and it is where the
    grade failed: *brown brothers* and *four seasons* are ordinary English."""

    def _verify(self, page: str, normalized: str):
        with mock.patch.object(
            domains.http, "get_with_url", return_value=(_page(page), "https://x.com/")
        ):
            return domains.verify("x.com", normalized)

    def test_a_fragment_alone_is_not_strong(self):
        """The page that owns *brown brothers* is a paint distributor PPG
        acquired, and it has no reason to say *harriman*."""
        result = self._verify(
            "Brown Brothers vehicle refinish paint distribution",
            "brown brothers harriman hong kong",
        )

        self.assertEqual(result[1], "weak")
        self.assertIn("harriman", result[2])

    def test_a_fragment_with_a_second_word_is_strong(self):
        result = self._verify(
            "Brown Brothers Harriman private banking", "brown brothers harriman hong kong"
        )

        self.assertEqual(result[1], "strong")
        self.assertIn("harriman", result[2])

    def test_the_full_name_needs_no_corroboration(self):
        """Nothing is left over, so there is nothing to ask for."""
        result = self._verify("Lightyear Europe", "lightyear europe")

        self.assertEqual(result[1], "strong")

    def test_industry_words_are_not_asked_for(self):
        """Demanding one back demotes correct matches wholesale: a fund
        vehicle's structure words appear nowhere on its manager's site, and
        `federatedhermes.com` really is the domain for its funds."""
        self.assertEqual(
            domains._corroborators("contrarian capital fund", "contrarian capital"), []
        )
        self.assertEqual(
            domains._corroborators("aries global capital", "aries global"), []
        )

    def test_short_leftovers_are_not_asked_for(self):
        """A page matching "ii" or "sa" is chance, not evidence."""
        self.assertEqual(
            domains._corroborators("kikk capital ii management", "kikk capital"), []
        )

    def test_a_regraded_row_is_not_picked_up_twice(self):
        """The pass resumes rather than restarts, so its own output must not
        look like more work: both outcomes leave a mark in the evidence."""
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(domains.SCHEMA)
        connection.executemany(
            "INSERT INTO domain_lookups (query, domain, method, evidence, checked_at)"
            " VALUES (?, ?, 'name-strong', ?, '2026-01-01')",
            [
                ("Old Grade Ltd", "old.com", "https://old.com/ names 'old grade'"),
                ("Kept Ltd", "kept.com", "https://kept.com/ names 'kept' and 'ltd'"),
                ("Demoted Ltd", "no.com", "https://no.com/ names 'x', but no y"),
            ],
        )

        pending = [row["query"] for row in domains.regrade_targets(connection, 10)]
        connection.close()

        self.assertEqual(pending, ["Old Grade Ltd"])

    def test_a_one_word_match_is_still_weak(self):
        """The older rule this one sits beside: accepting one word out of
        several is what produced australia.com for the banking group."""
        result = self._verify(
            "Australia holidays and travel", "australia and new zealand banking group"
        )

        self.assertEqual(result[1], "weak")


if __name__ == "__main__":
    unittest.main()
