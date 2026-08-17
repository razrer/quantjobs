"""Regression tests for the JobTech JobStream delta feed.

Two things here are easy to get wrong and quiet when wrong: resuming from the
cursor, and the shape of a withdrawn ad.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from quantscraper import db, jobstream


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    connection.executescript(jobstream.SCHEMA)
    return connection


def _ad(job_id: str, **overrides) -> dict:
    ad = {
        "id": job_id,
        "headline": f"Kvantitativ analytiker {job_id}",
        "webpage_url": f"https://arbetsformedlingen.se/{job_id}",
        "publication_date": "2026-08-13T06:12:05",
        "timestamp": 1786594325538,
        "removed": False,
        "removed_date": None,
        "employer": {"name": "Lynx Asset Management", "url": "https://lynxhedge.se"},
        "workplace_address": {"municipality": "Stockholm", "region": "Stockholms län"},
        "occupation": {"label": "Analytiker"},
        "application_deadline": "2026-09-30T23:59:59",
        "description": "Vi söker en kvantitativ analytiker.",
    }
    ad.update(overrides)
    return ad


class WithdrawnAdTest(unittest.TestCase):
    def test_removal_does_not_blank_the_record(self):
        """A withdrawn ad arrives with every field but `id` set to null.

        Feeding one through the normal upsert leaves the row in place but wipes
        the title, employer and description -- the job is still counted and no
        longer readable. That is worse than either keeping it or deleting it,
        because nothing announces it.
        """
        connection = _memory(self)
        jobstream.apply(connection, [_ad("31346649")])

        jobstream.apply(
            connection,
            [
                {
                    "id": "31346649",
                    "removed": True,
                    "removed_date": "2026-08-13T09:00:00",
                    "timestamp": 1786594999999,
                    "headline": None,
                    "employer": None,
                    "description": None,
                }
            ],
        )

        row = connection.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(row["removed_at"], "2026-08-13T09:00:00")
        self.assertEqual(
            row["title"],
            "Kvantitativ analytiker 31346649",
            "the withdrawal blanked the title",
        )
        self.assertIsNotNone(row["description"], "the withdrawal blanked the body")
        self.assertEqual(row["employer"], "Lynx Asset Management")
        self.assertEqual(row["deadline"], "2026-09-30T23:59:59")

    def test_withdrawal_of_an_unseen_ad_is_harmless(self):
        """Cold starts see withdrawals for ads published before the window."""
        connection = _memory(self)
        written, withdrawn, _ = jobstream.apply(
            connection, [{"id": "999", "removed": True, "timestamp": 1}]
        )
        self.assertEqual((written, withdrawn), (0, 1))
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)


class CursorTest(unittest.TestCase):
    def test_cold_start_reaches_back_a_bounded_window(self):
        connection = _memory(self)
        since = jobstream.cursor(connection)
        gap = datetime.now(timezone.utc) - since
        self.assertAlmostEqual(
            gap.total_seconds(), jobstream.COLD_START.total_seconds(), delta=60
        )

    def test_cursor_advances_to_the_newest_timestamp(self):
        connection = _memory(self)
        _, _, latest = jobstream.apply(
            connection,
            [_ad("1", timestamp=100), _ad("2", timestamp=300), _ad("3", timestamp=200)],
        )
        self.assertEqual(latest, 300)

    def test_resume_rewinds_by_the_overlap(self):
        """Re-reading an ad costs an idempotent upsert; missing one because it
        shared a second with the cursor costs a posting."""
        connection = _memory(self)
        milliseconds = 1_786_594_325_538
        jobstream.save_cursor(connection, milliseconds)

        since = jobstream.cursor(connection)
        stored = datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
        self.assertEqual(stored - since, jobstream.OVERLAP)
        self.assertLess(since, stored, "resume must not start after the last ad seen")


class MappingTest(unittest.TestCase):
    def test_location_and_employer_domain(self):
        connection = _memory(self)
        jobstream.apply(connection, [_ad("77")])
        row = connection.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(row["location"], "Stockholm, Stockholms län")
        self.assertEqual(row["domain"], "lynxhedge.se", "employer URL is the bridge to firms")
        self.assertEqual(row["ats"], "jobtech")

    def test_closing_date_is_carried(self):
        """The one source that publishes a deadline as a field.

        The board sorts an approaching closing date above everything else, so a
        dropped `application_deadline` does not read as a missing column -- it
        reads as a posting that never closes.
        """
        connection = _memory(self)
        jobstream.apply(connection, [_ad("78")])
        self.assertEqual(
            connection.execute("SELECT deadline FROM jobs").fetchone()[0],
            "2026-09-30T23:59:59",
        )

    def test_employer_name_survives_a_missing_url(self):
        """Only half of the feed's ads carry a resolvable employer URL.

        Without the name the other half are postings from nobody, which is what
        the board showed before this column existed.
        """
        connection = _memory(self)
        jobstream.apply(connection, [_ad("79", employer={"name": "REGION UPPSALA"})])
        row = connection.execute("SELECT domain, employer FROM jobs").fetchone()
        self.assertIsNone(row["domain"])
        self.assertEqual(row["employer"], "REGION UPPSALA")


class ClosingDateUpdateTest(unittest.TestCase):
    """`deadline` takes the newer value, but never takes NULL for an answer."""

    def test_an_employer_may_move_its_closing_date(self):
        connection = _memory(self)
        jobstream.apply(connection, [_ad("80")])
        jobstream.apply(connection, [_ad("80", application_deadline="2026-10-15T23:59:59")])
        self.assertEqual(
            connection.execute("SELECT deadline FROM jobs").fetchone()[0],
            "2026-10-15T23:59:59",
        )

    def test_a_feed_that_stops_publishing_one_does_not_erase_it(self):
        connection = _memory(self)
        jobstream.apply(connection, [_ad("81")])
        jobstream.apply(connection, [_ad("81", application_deadline=None)])
        self.assertEqual(
            connection.execute("SELECT deadline FROM jobs").fetchone()[0],
            "2026-09-30T23:59:59",
            "a silent gap in the feed must not un-date a posting we already showed",
        )


if __name__ == "__main__":
    unittest.main()
