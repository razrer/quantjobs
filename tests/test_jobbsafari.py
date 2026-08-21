"""Regression tests for Jobbsafari, Sweden's widest job board.

Five things here are easy to get wrong and quiet when wrong: the walk's stop
conditions (a board ignoring the pager serves page one forever and never
returns an empty page), the two surfaces one parser has to read, the closing
date the board publishes and this module refuses to write, the multi-location
string the geography gate reads, and the guard that compares what arrived
against what the board advertised.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from unittest import mock

from quantscraper import db, jobbsafari


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _row(pk: int, **overrides) -> dict:
    row = {
        "pk": pk,
        "title": "Kvantitativ analytiker till Markets",
        "slug": f"kvantitativ-analytiker-till-markets-abcde-{pk}",
        "startDate": "2026-08-17 00:00:00",
        "endDate": "2026-09-06 00:00:00",
        "dateUpdated": "2026-08-20T03:01:16.613697+03:00",
        "company": {"pk": 1, "name": "Nordnet", "slug": "nordnet"},
        "locations": [{"pk": 9, "area": {"pk": 9, "name": "Stockholm"}, "name": "Stockholm"}],
        "categories": [],
        "mainCategories": [],
        "subcategories": [],
        "apply": {"method": "url", "href": "https://nordnet.teamtailor.com/jobs/1"},
        "status": 2,
    }
    row.update(overrides)
    return row


def _payload(rows: list[dict], *, count: int | None = None, page_size: int = 30) -> str:
    """The data route's answer: `pageProps` at the top level."""
    return json.dumps(
        {
            "pageProps": {
                "pageSize": page_size,
                "jobEntries": {
                    "count": len(rows) if count is None else count,
                    "results": rows,
                },
            }
        }
    )


def _markup(rows: list[dict], *, count: int | None = None) -> str:
    """The rendered page: the same object, wrapped and inlined in a script."""
    island = json.dumps(
        {"props": json.loads(_payload(rows, count=count)), "buildId": "BUILD", "locale": "sv-SE"}
    )
    return (
        "<!doctype html><html><body><div>chrome</div>"
        f'<script id="__NEXT_DATA__" type="application/json">{island}</script>'
        "</body></html>"
    )


class ParseTest(unittest.TestCase):
    """One parser, two surfaces -- the fallback is worthless if it needs a second."""

    def test_reads_the_data_route(self):
        page = jobbsafari.parse(_payload([_row(1), _row(2)], count=48_550))
        self.assertEqual([r["pk"] for r in page.rows], [1, 2])
        self.assertEqual(page.hitcount, 48_550)

    def test_reads_the_rendered_page(self):
        page = jobbsafari.parse(_markup([_row(1)], count=7))
        self.assertEqual([r["pk"] for r in page.rows], [1])
        self.assertEqual(page.hitcount, 7)

    def test_leading_whitespace_does_not_pick_the_wrong_surface(self):
        page = jobbsafari.parse("\n  " + _payload([_row(1)]))
        self.assertEqual(len(page.rows), 1)

    def test_a_page_with_no_search_response_is_blocked_not_empty(self):
        """An empty page is how the walk terminates, so a wall must not read as one."""
        for text in (
            "<html><body>Sign in to continue</body></html>",
            json.dumps({"pageProps": {"pageSize": 30}}),
            json.dumps({"pageProps": {"jobEntries": {"count": 0}}}),
            json.dumps({"notPageProps": 1}),
        ):
            with self.subTest(text=text[:40]):
                with self.assertRaises(jobbsafari.Blocked):
                    jobbsafari.parse(text)

    def test_a_genuinely_empty_result_set_is_not_blocked(self):
        page = jobbsafari.parse(_payload([], count=0))
        self.assertEqual(page.rows, [])


class RecordTest(unittest.TestCase):
    def test_the_id_is_the_key_and_not_the_slug(self):
        """A retitled posting keeps its pk and mints a new slug."""
        job = jobbsafari._job(_row(4242, slug="retitled-abcde-4242"))
        self.assertEqual(job.job_id, "4242")
        self.assertEqual(job.url, "https://jobbsafari.se/jobb/retitled-abcde-4242")

    def test_the_advertisement_end_date_is_never_a_deadline(self):
        """`endDate` is when the ad comes down. 11% of them are exactly 181 days
        out and a long tail fall in the year 2650, so writing it would pin
        thousands of Swedish cards to the top of a deadline-first board."""
        job = jobbsafari._job(_row(1, endDate="2650-01-01 00:00:00"))
        self.assertIsNone(job.deadline)

    def test_every_named_place_reaches_the_location(self):
        job = jobbsafari._job(
            _row(
                1,
                locations=[
                    {"name": "Stockholm", "area": {"name": "Stockholm"}},
                    {"name": "Göteborg", "area": {"name": "Göteborg"}},
                ],
            )
        )
        self.assertEqual(job.location, "Stockholm, Göteborg")

    def test_a_repeated_place_is_named_once(self):
        job = jobbsafari._job(
            _row(1, locations=[{"name": "Malmö"}, {"name": "Malmö"}, {"name": "Lund"}])
        )
        self.assertEqual(job.location, "Malmö, Lund")

    def test_the_area_name_stands_in_when_the_entry_has_none(self):
        job = jobbsafari._job(_row(1, locations=[{"area": {"name": "Uppsala"}}]))
        self.assertEqual(job.location, "Uppsala")

    def test_no_place_at_all_is_none_rather_than_empty(self):
        self.assertIsNone(jobbsafari._job(_row(1, locations=[])).location)

    def test_nothing_is_smuggled_into_department(self):
        """`tagging.py` folds department into the title, so a value here would
        be a covert second door to seniority."""
        self.assertIsNone(jobbsafari._job(_row(1)).department)

    def test_no_domain_is_read_off_the_apply_link(self):
        """386 hosts over 1,681 rows, headed by ATS vendors and staffing
        agencies. Nothing on the record separates an employer's own host from
        an agency standing in for a client it does not name."""
        connection = _memory(self)
        with mock.patch.object(
            jobbsafari, "fetch_page", side_effect=[jobbsafari.parse(_payload([_row(1)]))]
        ):
            jobbsafari.run(connection, pages=1)
        row = connection.execute("SELECT domain, employer FROM jobs").fetchone()
        self.assertIsNone(row["domain"])
        self.assertEqual(row["employer"], "Nordnet")


class WalkTest(unittest.TestCase):
    def _pages(self, *sizes: int, count: int) -> list[jobbsafari.Page]:
        pk = 0
        pages = []
        for size in sizes:
            rows = []
            for _ in range(size):
                pk += 1
                rows.append(_row(pk))
            pages.append(jobbsafari.parse(_payload(rows, count=count)))
        return pages

    def test_an_empty_page_ends_the_walk(self):
        connection = _memory(self)
        pages = self._pages(jobbsafari.PAGE_SIZE, 3, 0, count=jobbsafari.PAGE_SIZE + 3)
        with mock.patch.object(jobbsafari, "fetch_page", side_effect=pages) as fetch:
            swept = jobbsafari.run(connection, pages=9)
        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(swept.exhausted)
        self.assertEqual(swept.seen, jobbsafari.PAGE_SIZE + 3)

    def test_a_short_page_does_not_end_the_walk(self):
        """The bug that cost the first live sweep 43,000 postings: page 11 came
        back with 499 rows instead of 500 and the walk called it finished."""
        connection = _memory(self)
        pages = self._pages(jobbsafari.PAGE_SIZE - 1, jobbsafari.PAGE_SIZE, 2, 0, count=9_999)
        with mock.patch.object(jobbsafari, "fetch_page", side_effect=pages) as fetch:
            swept = jobbsafari.run(connection, pages=9)
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(swept.seen, 2 * jobbsafari.PAGE_SIZE + 1)

    def test_a_board_ignoring_the_pager_is_loud_rather_than_endless(self):
        """The Jobvite trap: page one served twice looks like the end of the
        board to a count and like an infinite walk to a stop condition."""
        connection = _memory(self)
        one = _payload([_row(n) for n in range(1, jobbsafari.PAGE_SIZE + 1)], count=99_999)
        pages = [jobbsafari.parse(one), jobbsafari.parse(one)]
        with mock.patch.object(jobbsafari, "fetch_page", side_effect=pages):
            with self.assertRaises(jobbsafari.Blocked):
                jobbsafari.run(connection)

    def test_a_row_served_twice_is_counted_once(self):
        connection = _memory(self)
        first = _payload([_row(n) for n in range(1, jobbsafari.PAGE_SIZE + 1)], count=600)
        second = _payload(
            [_row(jobbsafari.PAGE_SIZE)] + [_row(n) for n in range(900, 902)], count=600
        )
        with mock.patch.object(
            jobbsafari,
            "fetch_page",
            side_effect=[jobbsafari.parse(first), jobbsafari.parse(second), jobbsafari.parse(_payload([]))],
        ):
            swept = jobbsafari.run(connection, pages=5)
        self.assertEqual(swept.repeats, 1)
        self.assertEqual(swept.seen, jobbsafari.PAGE_SIZE + 2)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], swept.seen
        )

    def test_a_row_with_no_id_is_dropped_rather_than_crashing_the_walk(self):
        """`_job` reads `row["pk"]`, so an unkeyed row would end a sweep
        mid-page -- and the walk is the one place a single bad row must not."""
        connection = _memory(self)
        page = _payload([_row(1), {"title": "no id", "slug": "x"}, _row(2)], count=3)
        with mock.patch.object(
            jobbsafari, "fetch_page",
            side_effect=[jobbsafari.parse(page), jobbsafari.parse(_payload([]))],
        ):
            swept = jobbsafari.run(connection, pages=4)
        self.assertEqual(swept.seen, 2)
        self.assertEqual(swept.repeats, 0)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)

    def test_the_advertised_total_is_taken_from_the_first_page(self):
        connection = _memory(self)
        pages = self._pages(4, count=48_550)
        with mock.patch.object(jobbsafari, "fetch_page", side_effect=pages):
            swept = jobbsafari.run(connection, pages=1)
        self.assertEqual(swept.advertised, 48_550)


class GuardTest(unittest.TestCase):
    """A walk that stops early must say so. Every other source in this pipeline
    learned that the same way: a round number in the output is what a cap looks
    like from the outside and nothing else announces it."""

    def test_a_sound_sweep_reports_no_problem(self):
        swept = jobbsafari.Sweep(
            seen=48_500, advertised=48_550, exhausted=True, pages=98
        )
        self.assertIsNone(swept.problem)

    def test_a_shortfall_is_truncation_rather_than_a_moving_index(self):
        swept = jobbsafari.Sweep(seen=30_000, advertised=48_550, exhausted=True)
        self.assertIn("truncation", swept.problem)

    def test_a_small_gap_is_the_index_moving_under_the_walk(self):
        swept = jobbsafari.Sweep(seen=48_000, advertised=48_550, exhausted=True)
        self.assertIsNone(swept.problem)

    def test_an_implausibly_small_result_is_a_broken_source(self):
        swept = jobbsafari.Sweep(seen=42, advertised=42, exhausted=True)
        self.assertIn("broken source", swept.problem)

    def test_hitting_the_page_bound_is_a_problem_in_its_own_right(self):
        swept = jobbsafari.Sweep(seen=99_000, advertised=99_000, exhausted=False)
        self.assertIn("cut short", swept.problem)

    def test_a_probe_stands_the_guards_down(self):
        """`--pages 2` is a deliberate subset, so falling short of the board is
        the request rather than a failure."""
        swept = jobbsafari.Sweep(seen=1_000, advertised=48_550, partial=True)
        self.assertIsNone(swept.problem)


class BuildIdTest(unittest.TestCase):
    def test_the_deploy_id_comes_off_the_page(self):
        with mock.patch.object(jobbsafari.http, "get_text", return_value=_markup([_row(1)])):
            self.assertEqual(jobbsafari.build_id(), "BUILD/sv-SE")

    def test_a_page_without_one_is_blocked(self):
        for markup in ("<html>nothing</html>",
                       '<script id="__NEXT_DATA__" type="application/json">{"locale":"sv-SE"}</script>'):
            with self.subTest(markup=markup[:30]):
                with mock.patch.object(jobbsafari.http, "get_text", return_value=markup):
                    with self.assertRaises(jobbsafari.Blocked):
                        jobbsafari.build_id()

    def test_a_stale_deploy_id_is_refreshed_once_before_the_slow_route(self):
        """A deploy mid-walk 404s a URL that worked a second ago."""
        answers = [
            OSError("404"),          # the cached id, now stale
            _markup([_row(1)]),      # build_id() re-reading the search page
            _payload([_row(2)]),     # the retry, on the fresh id
        ]

        def fake(url, **kwargs):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(jobbsafari.http, "get_text", side_effect=fake):
            page = jobbsafari.fetch_page(1, deploy=["STALE/sv-SE"])
        self.assertEqual([r["pk"] for r in page.rows], [2])
        self.assertEqual(answers, [])

    def test_the_rendered_page_is_the_last_resort(self):
        answers = [
            OSError("404"),      # cached id
            OSError("boom"),     # build_id() re-read
            _markup([_row(3)]),  # the rendered search page
        ]

        def fake(url, **kwargs):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(jobbsafari.http, "get_text", side_effect=fake):
            page = jobbsafari.fetch_page(1, deploy=["STALE/sv-SE"])
        self.assertEqual([r["pk"] for r in page.rows], [3])


if __name__ == "__main__":
    unittest.main()
