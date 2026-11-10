"""Regression tests for the two third-party boards read per hub.

What is quiet when wrong: a location the API resolves to another country, a
failed or partial walk withdrawing adverts it never visited, a windowed
keyword search treating absence as withdrawal, and a new source missing from
the lists that keep portals out of board profiling and into alerts.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from quantscraper import alerts, bodies, db, dedup, efinancial, http, lexicon, linkedin


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _live(connection, ats: str) -> set[str]:
    return {row["job_id"] for row in connection.execute(
        "SELECT job_id FROM jobs WHERE ats = ? AND removed_at IS NULL", (ats,))}


def _efc_row(job_id: int, **overrides) -> dict:
    row = {
        "id": f"opaque{job_id}",
        "jobId": str(job_id),
        "title": "Junior Quantitative Analyst",
        "companyName": "Polymer Capital",
        "detailsPageUrl": f"/jobs-Hong_Kong-Junior_Quantitative_Analyst.id{job_id}",
        "jobLocation": {"displayName": "Hong Kong"},
        "postedDate": "2026-11-09T01:24:35.387Z",
        "expirationDate": "2027-01-01T00:00:00.000Z",
        "sectors": ["QUANTITATIVE_ANALYTICS/RESEARCH"],
        "description": "Build <b>risk</b> models &amp; tools.",
    }
    row.update(overrides)
    return row


def _efc_pages(pages: list[list[dict]], *, country: str = "HK", total: int | None = None):
    """A stand-in for `efinancial.fetch_page` serving these pages for any hub."""
    count = sum(len(page) for page in pages) if total is None else total

    def fetch(location: str, page: int) -> dict:
        data = pages[page - 1] if page <= len(pages) else []
        return {"data": data, "meta": {
            "totalResults": count, "pageCount": len(pages),
            "searchedLocation": {"countryCode2": country}}}
    return fetch


class EfinancialTest(unittest.TestCase):
    def test_a_row_becomes_a_job_with_its_public_id_and_no_deadline(self):
        job = efinancial._job("hong-kong", _efc_row(23825428))
        self.assertEqual(job.job_id, "23825428")
        self.assertEqual(job.employer, "Polymer Capital")
        self.assertTrue(job.url.endswith(".id23825428"))
        self.assertEqual(job.posted_at, "2026-11-09")
        self.assertIsNone(job.deadline)
        self.assertEqual(job.description, "Build risk models & tools.")

    def test_a_location_resolved_to_another_country_is_refused(self):
        with mock.patch.object(efinancial, "fetch_page", _efc_pages([[_efc_row(1)]], country="US")):
            with self.assertRaises(efinancial.Blocked):
                efinancial.walk("hong-kong")

    def test_a_short_walk_is_a_problem_and_writes_nothing(self):
        connection = _memory(self)
        short = _efc_pages([[_efc_row(n) for n in range(900)]], total=2_500)
        with mock.patch.object(efinancial, "fetch_page", short):
            swept = efinancial.run(connection, only=["hong-kong"])
        self.assertIn("truncation", swept.problem)
        self.assertEqual(_live(connection, efinancial.NAME), set())

    def test_a_sound_walk_withdraws_what_it_no_longer_lists_and_revives_what_returns(self):
        connection = _memory(self)
        stamps = iter(f"2026-11-{day:02d}T00:00:00+00:00" for day in range(1, 30))
        first = [_efc_row(n) for n in range(1_000)]
        second = first[1:]
        with mock.patch.object(db, "now", lambda: next(stamps)):
            for rows, live in ((first, 1_000), (second, 999), (first, 1_000)):
                with mock.patch.object(efinancial, "fetch_page", _efc_pages([rows])):
                    efinancial.run(connection, only=["hong-kong"])
                self.assertEqual(len(_live(connection, efinancial.NAME)), live)

    def test_a_page_probe_withdraws_nothing(self):
        connection = _memory(self)
        rows = [_efc_row(n) for n in range(1_000)]
        with mock.patch.object(efinancial, "fetch_page", _efc_pages([rows])):
            efinancial.run(connection, only=["hong-kong"])
        with mock.patch.object(efinancial, "fetch_page", _efc_pages([rows[:5], rows[5:]])):
            swept = efinancial.run(connection, only=["hong-kong"], pages=1)
        self.assertIsNone(swept.problem)
        self.assertEqual(len(_live(connection, efinancial.NAME)), 1_000)

    def test_one_hub_failing_does_not_stop_the_next(self):
        connection = _memory(self)

        def fetch(location: str, page: int) -> dict:
            if location == "Hong Kong":
                raise OSError("refused")
            return _efc_pages([[_efc_row(n) for n in range(800)]], country="SG")(location, page)

        with mock.patch.object(efinancial, "fetch_page", fetch):
            swept = efinancial.run(connection, only=["hong-kong", "singapore"])
        self.assertIn("hong-kong: refused", swept.problem)
        self.assertEqual(len(_live(connection, efinancial.NAME)), 800)


def _card(job_id: int, place: str = "Hong Kong, Hong Kong SAR") -> str:
    return f"""<li><div class="base-card" data-entity-urn="urn:li:jobPosting:{job_id}">
      <a class="base-card__full-link" href="https://hk.linkedin.com/jobs/view/x-{job_id}?refId=abc&amp;trackingId=d"></a>
      <h3 class="base-search-card__title"> Risk &amp; Quant Analyst </h3>
      <h4 class="base-search-card__subtitle"><a> Polymer Capital </a></h4>
      <span class="job-search-card__location"> {place} </span>
      <time class="job-search-card__listdate" datetime="2026-11-09">1 day ago</time>
    </div></li>"""


def _li_pages(by_keyword: dict[str, list[int]], place: str = "Hong Kong, Hong Kong SAR"):
    """A stand-in for `linkedin.fetch_page`: these ids per keyword, ten a page."""
    def fetch(geo: str, keyword: str, start: int) -> str:
        ids = by_keyword.get(keyword, [])[start:start + linkedin.PAGE_SIZE]
        return "".join(_card(n, place) for n in ids)
    return fetch


class LinkedinTest(unittest.TestCase):
    def test_a_card_is_read_with_its_tracking_query_dropped(self):
        (job,) = linkedin.parse(_card(4432237856), "hong-kong")
        self.assertEqual(job.job_id, "4432237856")
        self.assertEqual(job.title, "Risk & Quant Analyst")
        self.assertEqual(job.employer, "Polymer Capital")
        self.assertEqual(job.url, "https://hk.linkedin.com/jobs/view/x-4432237856")
        self.assertEqual(job.location, "Hong Kong, Hong Kong SAR")
        self.assertEqual(job.posted_at, "2026-11-09")

    def test_an_empty_page_ends_a_query_and_a_wall_does_not(self):
        self.assertEqual(linkedin.parse("", "hong-kong"), [])
        with self.assertRaises(linkedin.Blocked):
            linkedin.parse("<html><body>Sign in to continue</body></html>", "hong-kong")

    def test_keywords_are_unioned_by_posting_id(self):
        pages = _li_pages({"quant": list(range(25)), "trader": list(range(20, 40))})
        with mock.patch.object(linkedin, "fetch_page", pages):
            hub, jobs = linkedin.walk("hong-kong", keywords=("quant", "trader"))
        self.assertEqual(hub.seen, 40)
        self.assertEqual(hub.windowed, [])

    def test_a_geo_id_that_answers_about_somewhere_else_is_refused(self):
        with mock.patch.object(linkedin, "fetch_page", _li_pages({"quant": [1, 2, 3]}, "Austin, TX")):
            with self.assertRaises(linkedin.Blocked):
                linkedin.walk("hong-kong", keywords=("quant",))

    def test_absence_is_withdrawal_only_when_no_query_hit_the_window(self):
        connection = _memory(self)
        stamps = iter(f"2026-11-{day:02d}T00:00:00+00:00" for day in range(1, 30))
        with mock.patch.object(db, "now", lambda: next(stamps)), \
             mock.patch.object(linkedin, "KEYWORDS", ("quant",)):
            with mock.patch.object(linkedin, "fetch_page", _li_pages({"quant": [1, 2, 3]})):
                linkedin.run(connection)
            # A sound, unwindowed sweep no longer lists posting 3.
            with mock.patch.object(linkedin, "fetch_page", _li_pages({"quant": [1, 2]})), \
                 mock.patch.object(linkedin, "HUBS", {"hong-kong": linkedin.HUBS["hong-kong"]}):
                linkedin.run(connection)
            self.assertEqual(_live(connection, linkedin.NAME), {"1", "2"})
            # A windowed sweep that lost posting 2 proves nothing about it yet.
            full = list(range(100, 100 + linkedin.WINDOW)) + [1]
            with mock.patch.object(linkedin, "fetch_page", _li_pages({"quant": full})), \
                 mock.patch.object(linkedin, "HUBS", {"hong-kong": linkedin.HUBS["hong-kong"]}):
                swept = linkedin.run(connection)
            self.assertEqual(swept.hubs[0].windowed, ["quant"])
            self.assertIn("2", _live(connection, linkedin.NAME))

    def test_a_refused_hub_writes_nothing_and_is_reported(self):
        connection = _memory(self)

        def refuse(geo, keyword, start):
            raise OSError("HTTP Error 999")

        with mock.patch.object(linkedin, "fetch_page", refuse):
            swept = linkedin.run(connection, only=["hong-kong"])
        self.assertIn("999", swept.problem)
        self.assertEqual(_live(connection, linkedin.NAME), set())


class RegistrationTest(unittest.TestCase):
    def test_both_sources_are_portals_everywhere_a_portal_is_listed(self):
        for module in (efinancial, linkedin):
            self.assertIn(module.NAME, lexicon.NOT_A_BOARD)
            self.assertIn(module.NAME, dedup.PORTALS)
            self.assertIn(module.NAME, alerts._expected())

    def test_linkedin_has_a_body_fetcher_and_a_slow_interval(self):
        self.assertIn(linkedin.NAME, bodies.FETCHERS)
        self.assertGreaterEqual(http.HOST_INTERVAL_S[linkedin.HOST], 4.0)

    def test_neither_host_is_sent_a_contact_address(self):
        for module in (efinancial, linkedin):
            self.assertNotIn("@", module.HEADERS["User-Agent"])


if __name__ == "__main__":
    unittest.main()
