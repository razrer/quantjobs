"""Regression tests for Layer 3B, the tier-B careers-page watch.

The thing being defended is the signal-to-noise ratio. A watch that reports a
change every run is not a watch, and a page whose links never move must report
nothing rather than something.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest

from quantscraper import pages


class LinkSetTest(unittest.TestCase):
    def test_query_strings_and_fragments_are_dropped(self):
        """A session id or a `?srsltid=` differs on every fetch, so keeping it
        would report a change every poll on a page that never changed."""
        markup = (
            '<a href="/careers?session=abc123">Careers</a>'
            '<a href="/careers#top">Top</a>'
            '<a href="/about">About</a>'
        )

        self.assertEqual(
            pages.page_links(markup, "https://firm.com/careers/"),
            ["/about", "/careers"],
        )

    def test_offsite_and_non_http_links_are_dropped(self):
        """Social buttons and CDNs move for reasons that are not hiring."""
        markup = (
            '<a href="https://twitter.com/firm">X</a>'
            '<a href="mailto:careers@firm.com">Email</a>'
            '<a href="javascript:void(0)">Menu</a>'
            '<a href="https://www.firm.com/jobs/quant">Quant</a>'
        )

        self.assertEqual(
            pages.page_links(markup, "https://firm.com/careers/"), ["/jobs/quant"]
        )

    def test_a_new_posting_moves_the_fingerprint(self):
        base = '<a href="/about">About</a><a href="/jobs/trader">Trader</a>'
        after = base + '<a href="/jobs/quant-researcher">Quant Researcher</a>'
        url = "https://firm.com/careers/"

        before = pages.Snapshot("firm.com", url, pages.page_links(base, url))
        later = pages.Snapshot("firm.com", url, pages.page_links(after, url))

        self.assertNotEqual(before.fingerprint, later.fingerprint)

    def test_reordering_the_same_links_does_not(self):
        """Menus and grids reorder between renders. That is not a posting."""
        url = "https://firm.com/careers/"
        one = '<a href="/a">A</a><a href="/b">B</a>'
        two = '<a href="/b">B</a><a href="/a">A</a>'

        self.assertEqual(
            pages.Snapshot("firm.com", url, pages.page_links(one, url)).fingerprint,
            pages.Snapshot("firm.com", url, pages.page_links(two, url)).fingerprint,
        )


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(pages.SCHEMA)

    def tearDown(self):
        self.connection.close()

    def _shot(self, links):
        return pages.Snapshot("firm.com", "https://firm.com/careers/", links)

    def test_the_first_sight_of_a_page_is_not_a_change(self):
        changed = pages.record(self.connection, [self._shot(["/a"])])

        self.assertEqual(changed, 0)
        row = self.connection.execute("SELECT * FROM page_watch").fetchone()
        self.assertIsNone(row["changed_at"])

    def test_a_moved_link_set_is_counted_and_dated(self):
        pages.record(self.connection, [self._shot(["/a"])])
        changed = pages.record(self.connection, [self._shot(["/a", "/jobs/quant"])])

        row = self.connection.execute("SELECT * FROM page_watch").fetchone()
        self.assertEqual(changed, 1)
        self.assertEqual(row["changes"], 1)
        self.assertIsNotNone(row["changed_at"])

    def test_an_unchanged_page_keeps_its_change_history(self):
        """Three times since March is a different fact from once last night,
        so a quiet poll must not clear what an earlier one recorded."""
        pages.record(self.connection, [self._shot(["/a"])])
        pages.record(self.connection, [self._shot(["/a", "/b"])])
        pages.record(self.connection, [self._shot(["/a", "/b"])])

        row = self.connection.execute("SELECT * FROM page_watch").fetchone()
        self.assertEqual(row["changes"], 1)
        self.assertIsNotNone(row["changed_at"])


if __name__ == "__main__":
    unittest.main()
