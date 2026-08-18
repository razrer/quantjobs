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
from quantscraper.resolve import domain_of


def _page(text: str) -> bytes:
    return f"<html><body><p>{text}</p></body></html>".encode()


class MalformedWebsiteTest(unittest.TestCase):
    """A registry's own website field, published wrong.

    AFM writes `http//www.optiver.com` -- no colon -- for 68 firms, Optiver
    and IMC Trading among them. The host read as "http", yielded no domain,
    and the firm then fell through both paths: skipped by the harvester for
    having no parseable website and excluded from the probe queue for having
    one. Neither said anything.
    """

    def test_a_scheme_without_its_colon_still_yields_the_host(self):
        self.assertEqual(domain_of("http//www.optiver.com"), "optiver.com")
        self.assertEqual(domain_of("https//imc.nl/careers"), "imc.nl")

    def test_a_well_formed_url_is_unchanged(self):
        self.assertEqual(domain_of("https://www.optiver.com/careers"), "optiver.com")

    def test_a_bare_domain_keeps_its_first_label(self):
        """The permissive pattern must still require the separator: a rule
        like `^\w+:?/{0,2}` eats "optiver" and leaves ".com"."""
        self.assertEqual(domain_of("optiver.com"), "optiver.com")
        self.assertEqual(domain_of("www.optiver.com"), "optiver.com")

    def test_something_with_no_host_is_still_nothing(self):
        self.assertIsNone(domain_of("http//localhost"))
        self.assertIsNone(domain_of(""))


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
                ("Dead Ltd", "dead.com", "https://dead.com/ names 'dead' [unreachable at regrade]"),
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


class BestWebsiteTest(unittest.TestCase):
    """A merged firm must not inherit a social page over its own domain.

    Two Sigma's firm website came out `https://x.com/twosigma` because the
    platform URL simply outnumbered the real one among its rows, and every
    layer downstream reads that one field: `harvest_registry_domains` seeds
    `domain_lookups` from it, `discover._domain_for` reads that, and the board
    ends up on a host thousands of firms claim -- or, once the platform guard
    rejects it, on nothing.
    """

    def test_a_real_domain_beats_a_more_common_platform_page(self):
        from quantscraper.resolve import _best_website

        self.assertEqual(
            _best_website(
                [
                    "https://x.com/twosigma",
                    "https://x.com/twosigma",
                    "https://www.twosigma.com",
                ]
            ),
            "https://www.twosigma.com",
        )

    def test_a_platform_page_is_still_kept_when_it_is_all_there_is(self):
        """Better a record of where the firm publishes than none at all."""
        from quantscraper.resolve import _best_website

        self.assertEqual(
            _best_website(["https://uk.linkedin.com/company/acme"]),
            "https://uk.linkedin.com/company/acme",
        )

    def test_no_website_stays_none(self):
        from quantscraper.resolve import _best_website

        self.assertIsNone(_best_website([None, None]))
