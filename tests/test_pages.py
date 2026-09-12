"""Regression tests for Layer 3B, the tier-B careers-page watch.

The thing being defended is the signal-to-noise ratio. A watch that reports a
change every run is not a watch, and a page whose links never move must report
nothing rather than something.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest

from quantscraper import db, pages


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


class FailedPollTest(unittest.TestCase):
    """`snapshot` returned `None` for three unrelated reasons and `run`
    counted every one of them as a page polled -- so a careers page that had
    404'd for months was indistinguishable from a healthy page that had not
    changed. The same silence `board_polls` closed one layer up."""

    def setUp(self):
        self.connection = db.connect(":memory:")
        self.connection.executescript(pages.SCHEMA)

    def tearDown(self):
        self.connection.close()

    def _shot(self, links, domain="firm.com"):
        return pages.Snapshot(domain, "https://firm.com/careers/", links)

    def _row(self, domain="firm.com"):
        return self.connection.execute(
            "SELECT * FROM page_watch WHERE domain = ?", (domain,)
        ).fetchone()

    def test_a_failure_counts_against_a_page_that_has_a_baseline(self):
        pages.record(self.connection, [self._shot(["/a"])])
        pages.record_failures(
            self.connection, [pages.Poll("firm.com", error="HTTP 404")]
        )
        row = self._row()
        self.assertEqual(row["failures"], 1)
        self.assertEqual(row["error"], "HTTP 404")

    def test_a_failure_does_not_disturb_the_baseline_it_cannot_refresh(self):
        """`last_seen` is the last *successful* read and the whole layer
        compares one of those against the next. The attempt goes to
        `polled_at`, and the gap between them is the outage."""
        pages.record(self.connection, [self._shot(["/a", "/jobs/quant"])])
        before = self._row()
        pages.record_failures(
            self.connection, [pages.Poll("firm.com", error="HTTP 404")]
        )
        after = self._row()
        self.assertEqual(after["fingerprint"], before["fingerprint"])
        self.assertEqual(after["links"], before["links"])
        self.assertEqual(after["last_seen"], before["last_seen"])
        self.assertIsNotNone(after["polled_at"])

    def test_a_success_clears_the_run_of_failures(self):
        pages.record(self.connection, [self._shot(["/a"])])
        for _ in range(3):
            pages.record_failures(
                self.connection, [pages.Poll("firm.com", error="HTTP 500")]
            )
        self.assertEqual(self._row()["failures"], 3)
        pages.record(self.connection, [self._shot(["/a"])])
        self.assertEqual(self._row()["failures"], 0)
        self.assertIsNone(self._row()["error"])

    def test_a_page_that_never_read_gets_no_placeholder_row(self):
        """Writing one would put a fingerprint in the table that no page ever
        produced, and `record`'s change test compares against whatever is
        stored -- so the first real read would come back as *changed*. That is
        the false hiring signal an empty link set is refused to avoid,
        arriving by the other door. The absence of a row is the record, and
        `coverage` counts exactly those."""
        pages.record_failures(
            self.connection, [pages.Poll("never.com", error="DNS does not resolve")]
        )
        self.assertIsNone(self._row("never.com"))

    def test_a_failed_first_read_does_not_starve_the_next_page(self):
        self.connection.executescript("""
            CREATE TABLE ats_resolution(domain TEXT, careers_url TEXT, tier TEXT);
            INSERT INTO ats_resolution VALUES
                ('a.com', 'https://a.com/jobs', 'B'),
                ('b.com', 'https://b.com/jobs', 'B');
        """)
        self.assertEqual(pages.targets(self.connection, 1)[0]['domain'], 'a.com')
        pages.record_failures(self.connection, [pages.Poll('a.com', error='DNS failure')])
        self.assertEqual(pages.targets(self.connection, 1)[0]['domain'], 'b.com')
        self.assertIsNone(self._row('a.com'))

    def test_the_first_read_after_a_failure_is_not_reported_as_a_change(self):
        pages.record(self.connection, [self._shot(["/a"])])
        pages.record_failures(
            self.connection, [pages.Poll("firm.com", error="HTTP 503")]
        )
        changed = pages.record(self.connection, [self._shot(["/a"])])
        self.assertEqual(changed, 0)
        self.assertIsNone(self._row()["changed_at"])


class CoverageTest(unittest.TestCase):
    """It printed 3,873 of 3,593 -- 108%, an impossible number. The excess is
    pages since promoted to tier A, which is this layer succeeding; the row
    stays behind after `targets` stops selecting it, so the count drifted
    above the thing it was a share of."""

    def setUp(self):
        self.connection = db.connect(":memory:")
        self.connection.executescript(pages.SCHEMA)
        self.connection.executescript(
            "CREATE TABLE IF NOT EXISTS ats_resolution ("
            " domain TEXT PRIMARY KEY, careers_url TEXT, ats TEXT, token TEXT,"
            " tier TEXT NOT NULL, evidence TEXT, checked_at TEXT)"
        )

    def tearDown(self):
        self.connection.close()

    def _tier(self, domain, tier):
        self.connection.execute(
            "INSERT INTO ats_resolution (domain, careers_url, tier, checked_at)"
            " VALUES (?, ?, ?, '2026-01-01')",
            (domain, f"https://{domain}/careers", tier),
        )

    def test_a_promoted_page_does_not_inflate_the_share(self):
        self._tier("stillb.com", "B")
        self._tier("promoted.com", "A")
        for domain in ("stillb.com", "promoted.com"):
            pages.record(
                self.connection,
                [pages.Snapshot(domain, f"https://{domain}/careers", ["/a"])],
            )
        row = pages.coverage(self.connection)
        self.assertEqual(row["tier_b"], 1)
        self.assertEqual(row["watched"], 1, "the tier-A row must not be counted")
        self.assertLessEqual(row["watched"], row["tier_b"])

    def test_a_page_never_read_is_named_rather_than_missing(self):
        self._tier("read.com", "B")
        self._tier("never.com", "B")
        pages.record(
            self.connection,
            [pages.Snapshot("read.com", "https://read.com/careers", ["/a"])],
        )
        row = pages.coverage(self.connection)
        self.assertEqual(row["tier_b"], 2)
        self.assertEqual(row["watched"], 1)
        self.assertEqual(row["unwatched"], 1)

    def test_a_watched_page_that_can_no_longer_be_read_counts_as_dark(self):
        self._tier("dark.com", "B")
        pages.record(
            self.connection,
            [pages.Snapshot("dark.com", "https://dark.com/careers", ["/a"])],
        )
        self.assertEqual(pages.coverage(self.connection)["dark"], 0)
        pages.record_failures(
            self.connection, [pages.Poll("dark.com", error="HTTP 404")]
        )
        row = pages.coverage(self.connection)
        self.assertEqual(row["watched"], 1, "still on the watch")
        self.assertEqual(row["dark"], 1, "and watched in name only")


if __name__ == "__main__":
    unittest.main()
