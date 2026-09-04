"""Regression tests for job-room.ch, Switzerland's public employment service.

Four things here are easy to get wrong and quiet when wrong: the 10,000-result
window, the deadline that is not a deadline, the recruiter's domain wearing the
employer's clothes, and a truncated poll that saves its cursor anyway.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest
from datetime import date, timedelta
from unittest import mock

from quantscraper import db, jobroom_ch


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _ad(job_id: str, **content) -> dict:
    """One search hit, in the envelope the portal actually returns."""
    return {
        "jobAdvertisement": {
            "id": job_id,
            "status": "PUBLISHED_PUBLIC",
            "stellennummerEgov": "242554775",
            "publication": {"startDate": "2026-08-19", "endDate": "2026-09-18"},
            "jobContent": {
                "jobDescriptions": [
                    {
                        "languageIsoCode": "de",
                        "title": f"Quantitative Analystin {job_id}",
                        "description": "Wir suchen eine quantitative Analystin.",
                    }
                ],
                "company": {"name": "Bank Julius Baer", "website": "juliusbaer.com"},
                "location": {"city": "Zurich", "cantonCode": "ZH", "countryIsoCode": "CH"},
                "occupations": [{"avamOccupationCode": "101233"}],
                **content,
            },
        }
    }


class DeadlineTest(unittest.TestCase):
    """`publication.endDate` is a display window, not an application deadline.

    81% of ads sit at exactly 30 days after the start date and 12.8% at exactly
    60 -- two round defaults. The board pins an approaching deadline above
    everything else, so writing this would nail ~80,000 Swiss postings to the
    top of the page ahead of the sources that publish a real one.
    """

    def test_the_publication_window_is_never_read_as_a_deadline(self):
        job = jobroom_ch._job(_ad("a")["jobAdvertisement"])

        self.assertIsNone(job.deadline)

    def test_the_start_date_is_still_the_posting_date(self):
        job = jobroom_ch._job(_ad("a")["jobAdvertisement"])

        self.assertEqual(job.posted_at, "2026-08-19")


class DomainAttributionTest(unittest.TestCase):
    """A surrogate company is an agency standing in for an unnamed employer.

    372 of the 379 websites in a 2,000-ad sample came from surrogate rows, and
    they are staffing agencies -- MediPersonal, fachkraft.ch. Recording those
    files a posting under a firm that never advertised it.
    """

    def test_a_real_employer_keeps_its_domain(self):
        content = _ad("a")["jobAdvertisement"]["jobContent"]

        self.assertEqual(jobroom_ch._domain(content), "juliusbaer.com")

    def test_a_surrogate_company_yields_no_domain(self):
        content = _ad(
            "a", company={"name": "MediPersonal", "website": "med-ipersonal.ch",
                          "surrogate": True}
        )["jobAdvertisement"]["jobContent"]

        self.assertIsNone(jobroom_ch._domain(content))

    def test_the_advertiser_name_survives_either_way(self):
        """`employer` is the advertiser verbatim -- the same contract JobStream
        and MyCareersFuture follow for a board that is not one firm's own."""
        ad = _ad("a", company={"name": "MediPersonal", "website": "med-ipersonal.ch",
                               "surrogate": True})["jobAdvertisement"]

        self.assertEqual(jobroom_ch._job(ad).employer, "MediPersonal")

    def test_a_platform_page_is_not_a_domain(self):
        content = _ad(
            "a", company={"name": "Somebody", "website": "https://linkedin.com/company/x"}
        )["jobAdvertisement"]["jobContent"]

        self.assertIsNone(jobroom_ch._domain(content))


class ResultWindowTest(unittest.TestCase):
    """The API answers HTTP 412 once `page * size` reaches 10,000.

    Its own `Link` header advertises a `rel="last"` far past that, so believing
    the advertised last page builds a walk that dies 88% short. This is
    MyCareersFuture's 418 one country over.
    """

    def test_the_walk_never_requests_past_the_window(self):
        """`_page` asserts rather than letting the request 412 at the far end
        of a long walk."""
        with self.assertRaises(AssertionError):
            jobroom_ch._page(1, jobroom_ch.WINDOW // jobroom_ch.PAGE_SIZE, "date_desc")

    def test_a_slice_within_one_end_needs_no_second_leg(self):
        """The common path -- a daily poll is ~9,400 -- must cost exactly the
        forward requests it looks like it should."""
        pages = []

        def fake(days, page, sort):
            pages.append(sort)
            rows = [_ad(f"{sort}-{page}-{i}") for i in range(jobroom_ch.PAGE_SIZE)]
            return (rows if page < 2 else [], 2 * jobroom_ch.PAGE_SIZE)

        with mock.patch.object(jobroom_ch, "_page", fake):
            rows, _, total = jobroom_ch.walk(1)

        self.assertEqual(total, 2 * jobroom_ch.PAGE_SIZE)
        self.assertEqual(len(rows), 2 * jobroom_ch.PAGE_SIZE)
        self.assertNotIn("date_asc", pages)

    def test_an_oversized_slice_reads_from_both_ends(self):
        """`date_asc` is the exact reverse of `date_desc` -- verified against a
        whole canton -- so the far end is what the forward leg could not reach."""
        seen = []

        def fake(days, page, sort):
            seen.append(sort)
            return ([_ad(f"{sort}-{page}-{i}") for i in range(jobroom_ch.PAGE_SIZE)],
                    jobroom_ch.WINDOW + 3 * jobroom_ch.PAGE_SIZE)

        with mock.patch.object(jobroom_ch, "_page", fake):
            _, _, total = jobroom_ch.walk(2)

        self.assertIn("date_asc", seen)
        self.assertEqual(total, jobroom_ch.WINDOW + 3 * jobroom_ch.PAGE_SIZE)
        # Only the shortfall is read backwards, not another full 10,000.
        self.assertEqual(seen.count("date_asc"), 3)


class TruncationTest(unittest.TestCase):
    """A short walk must announce itself. A quiet day and a truncated poll look
    identical from the outside, and only the advertised total tells them apart.
    """

    def test_a_slice_too_big_for_a_two_ended_walk_is_a_problem(self):
        swept = jobroom_ch.Sweep(
            days=7, pages=10, seen=jobroom_ch.REACH, written=0,
            advertised=27_403, repeats=0,
        )

        self.assertIsNotNone(swept.problem)
        self.assertIn("27,403", swept.problem)

    def test_a_short_walk_is_a_problem(self):
        swept = jobroom_ch.Sweep(
            days=1, pages=10, seen=9_000, written=9_000, advertised=9_401, repeats=0,
        )

        self.assertIsNotNone(swept.problem)
        self.assertIn("401 short", swept.problem)

    def test_a_complete_poll_is_not_a_problem(self):
        swept = jobroom_ch.Sweep(
            days=1, pages=10, seen=9_401, written=9_401, advertised=9_401, repeats=12,
        )

        self.assertIsNone(swept.problem)

    def test_a_missing_total_is_a_problem_rather_than_a_free_pass(self):
        """The audit is that one number, so losing it disables the only check
        there is. A case-sensitive header lookup did exactly that over HTTP/2:
        the count read as zero and a walk that stopped dead on the result
        window reported success with a round 10,000 postings."""
        swept = jobroom_ch.Sweep(
            days=1, pages=10, seen=jobroom_ch.WINDOW, written=jobroom_ch.WINDOW,
            advertised=0, repeats=0,
        )

        self.assertIsNotNone(swept.problem)
        self.assertIn("no total", swept.problem)

    def test_a_quiet_window_is_not_a_failure(self):
        """Deliberately no `MIN_EXPECTED` floor: this is a delta, so a genuinely
        quiet window is a true answer and a floor would fire on exactly the days
        it should not."""
        swept = jobroom_ch.Sweep(
            days=1, pages=1, seen=3, written=3, advertised=3, repeats=0,
        )

        self.assertIsNone(swept.problem)


class CursorTest(unittest.TestCase):
    def test_a_cold_start_reads_only_what_one_walk_reaches(self):
        """`onlineSince` is nested and a week is 27,403 postings -- past any
        walk. The rest arrives by polling; the board is a rolling 60-day
        window, so daily polling converges on all of it."""
        connection = _memory(self)

        self.assertLessEqual(jobroom_ch.cursor(connection), 2)

    def test_a_resume_covers_the_gap_plus_an_overlap(self):
        connection = _memory(self)
        jobroom_ch.save_cursor(connection, date.today() - timedelta(days=3))

        self.assertEqual(jobroom_ch.cursor(connection), 3 + jobroom_ch.OVERLAP_DAYS)

    def test_a_long_absence_is_clamped_to_what_the_portal_holds(self):
        """Nothing older than 60 days exists, and the API rejects a larger
        value outright."""
        connection = _memory(self)
        jobroom_ch.save_cursor(connection, date.today() - timedelta(days=400))

        self.assertEqual(jobroom_ch.cursor(connection), jobroom_ch.MAX_ONLINE_SINCE)

    def test_a_truncated_poll_does_not_move_the_cursor(self):
        """A cursor saved after a short walk leaves the unread remainder behind
        the window permanently -- the one way this source can lose a posting
        for good."""
        connection = _memory(self)
        with mock.patch.object(
            jobroom_ch, "walk", return_value=([_ad("a")], 1, 9_999)
        ):
            swept = jobroom_ch.run(connection, days=1)

        self.assertIsNotNone(swept.problem)
        self.assertIsNone(
            connection.execute(
                "SELECT cursor FROM feed_state WHERE feed = ?", (jobroom_ch.NAME,)
            ).fetchone()
        )

    def test_a_sound_poll_moves_the_cursor(self):
        connection = _memory(self)
        with mock.patch.object(jobroom_ch, "walk", return_value=([_ad("a")], 1, 1)):
            swept = jobroom_ch.run(connection, days=1)

        self.assertIsNone(swept.problem)
        row = connection.execute(
            "SELECT cursor FROM feed_state WHERE feed = ?", (jobroom_ch.NAME,)
        ).fetchone()
        self.assertEqual(row["cursor"], date.today().isoformat())


class WriteTest(unittest.TestCase):
    def test_a_poll_lands_a_readable_posting(self):
        connection = _memory(self)
        with mock.patch.object(jobroom_ch, "walk", return_value=([_ad("a")], 1, 1)):
            jobroom_ch.run(connection, days=1)

        row = connection.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(row["ats"], "jobroom")
        self.assertEqual(row["title"], "Quantitative Analystin a")
        self.assertEqual(row["location"], "Zurich, ZH")
        self.assertEqual(row["domain"], "juliusbaer.com")
        self.assertEqual(row["url"], "https://www.job-room.ch/job-search/a")
        self.assertIsNone(row["deadline"])

    def test_the_overlap_is_deduplicated_rather_than_written_twice(self):
        connection = _memory(self)
        with mock.patch.object(
            jobroom_ch, "walk", return_value=([_ad("a"), _ad("a")], 1, 1)
        ):
            swept = jobroom_ch.run(connection, days=1)

        self.assertEqual(swept.seen, 1)
        self.assertEqual(swept.repeats, 1)

    def test_a_posting_abroad_keeps_its_country(self):
        ad = _ad("a", location={"city": "Vaduz", "cantonCode": "FL",
                                "countryIsoCode": "LI"})["jobAdvertisement"]

        self.assertEqual(jobroom_ch._job(ad).location, "Vaduz, FL, LI")


if __name__ == "__main__":
    unittest.main()
