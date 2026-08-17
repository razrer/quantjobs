"""Regression tests for the MyCareersFuture (Singapore) portal.

Four things here are easy to get wrong and quiet when wrong: the page walk's
stop conditions, the shortfall arithmetic that is the only thing standing
between a truncated sweep and a plausible-looking number, the location string
the geography gate reads, and the closing date.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest

from quantscraper import db, mycareersfuture as mcf


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _row(uuid: str, **overrides) -> dict:
    row = {
        "uuid": uuid,
        "title": "Quantitative Researcher",
        "description": "<p><strong>Signals</strong></p>\n<ul><li>R&amp;D</li></ul>",
        "postedCompany": {
            "uen": "201942646E",
            "name": "QUBE RESEARCH & TECHNOLOGIES SINGAPORE PTE. LTD.",
        },
        "hiringCompany": None,
        "categories": [
            {"id": 21, "category": "Information Technology"},
            {"id": 5, "category": "Banking and Finance"},
        ],
        "employmentTypes": [{"id": 7, "employmentType": "Permanent"}],
        "positionLevels": [{"id": 7, "position": "Professional"}],
        "minimumYearsExperience": 3,
        "status": {"id": 102, "jobStatus": "Open"},
        "address": {
            "isOverseas": False,
            "overseasCountry": None,
            "districts": [
                {
                    "id": 1,
                    "location": "D01 Marina, Raffles Place, People's Park, Cecil",
                    "region": "Central",
                }
            ],
        },
        "metadata": {
            "jobPostId": "MCF-2026-1386577",
            "newPostingDate": "2026-08-12",
            "originalPostingDate": "2026-08-12",
            "expiryDate": "2026-09-11",
            "jobDetailsUrl": "https://www.mycareersfuture.gov.sg/job/banking-finance/x",
        },
    }
    row.update(overrides)
    return row


def _pages(*sizes_and_rows: list[dict]) -> list[list[dict]]:
    return list(sizes_and_rows)


class _FakePortal:
    """Serves canned pages, counting how many were actually asked for."""

    def __init__(self, pages: list[list[dict]], total: int | None = None):
        self.pages = pages
        self.total = len(sum(pages, [])) if total is None else total
        self.asked: list[int] = []

    def fetch_page(self, number: int, *, category: str | None = None):
        self.asked.append(number)
        rows = self.pages[number] if number < len(self.pages) else []
        return rows, self.total


def _install(test: unittest.TestCase, portal: _FakePortal) -> _FakePortal:
    original = mcf.fetch_page
    mcf.fetch_page = portal.fetch_page
    test.addCleanup(lambda: setattr(mcf, "fetch_page", original))
    return portal


def _full(rows: int, *, start: int = 0) -> list[dict]:
    return [_row(f"u{start + n:05d}") for n in range(rows)]


class PageSizeTest(unittest.TestCase):
    def test_the_page_size_the_api_actually_accepts_is_asserted(self):
        """`limit=200` is HTTP 400. Raising the constant must fail here, not at
        the far end of an 850-page sweep."""
        self.assertLessEqual(mcf.PAGE_SIZE, 100)

    def test_the_page_bound_is_a_backstop_not_a_cap(self):
        """The real walk ends near page 850. A bound anywhere near that is a
        silent truncation of exactly the source that matters -- the Workday
        reader was capped at 40 pages and State Street came back at 800."""
        self.assertGreaterEqual(mcf.MAX_PAGES, 4_000)


class WalkTest(unittest.TestCase):
    def test_a_short_page_ends_the_walk(self):
        portal = _install(self, _FakePortal([_full(100), _full(39, start=100)]))
        rows = [row for page, _ in mcf.walk() for row in page]
        self.assertEqual(len(rows), 139)
        self.assertEqual(portal.asked, [0, 1])

    def test_a_repeated_page_ends_the_walk(self):
        """A server ignoring `page` serves page one forever and never returns
        an empty page, so nothing else in the loop would terminate."""
        page = _full(100)
        portal = _install(self, _FakePortal([page, list(page), list(page), list(page)]))
        collected = [row for got, _ in mcf.walk(max_pages=50) for row in got]
        self.assertEqual(len(collected), 100, "the repeat was not detected")
        self.assertEqual(portal.asked, [0, 1])

    def test_an_empty_page_ends_the_walk(self):
        portal = _install(self, _FakePortal([_full(100), []]))
        self.assertEqual(len([r for p, _ in mcf.walk() for r in p]), 100)
        self.assertEqual(portal.asked, [0, 1])

    def test_the_walk_does_not_stop_on_a_full_page(self):
        """The mutation that matters: stopping on `len(rows) >= total` or on the
        first full page truncates the portal at 100 postings with no error."""
        _install(self, _FakePortal([_full(100), _full(100, start=100), _full(5, start=200)]))
        self.assertEqual(len([r for p, _ in mcf.walk() for r in p]), 205)


class SinceTest(unittest.TestCase):
    """`since` is a top-up bound, and it must not cut a day in half."""

    def _dated(self, *dates: str, start: int = 0) -> list[dict]:
        """Rows on the given dates, with uuids unique across pages.

        `start` is not decoration: the walk stops when a page repeats the
        previous one's uuid set, so a fixture that mints `d0..d99` on every
        page triggers that guard and the test measures it instead of `since`.
        """
        return [
            _row(
                f"d{start + n}",
                metadata={**_row("x")["metadata"], "newPostingDate": date},
            )
            for n, date in enumerate(dates)
        ]

    def test_a_page_still_holding_the_cutoff_day_is_not_the_last(self):
        page_one = self._dated(*(["2026-08-18"] * 50 + ["2026-08-17"] * 50))
        page_two = self._dated(*(["2026-08-17"] * 100), start=100)
        page_three = self._dated(*(["2026-08-15"] * 100), start=200)
        portal = _install(self, _FakePortal([page_one, page_two, page_three, _full(3)]))
        list(mcf.walk(since="2026-08-17"))
        self.assertEqual(
            portal.asked,
            [0, 1, 2],
            "the walk must read a whole page older than the cutoff before stopping,"
            " because rows sharing a posting date are in no order within it",
        )

    def test_no_since_reads_the_whole_portal(self):
        portal = _install(self, _FakePortal([self._dated(*(["2020-01-01"] * 100)), _full(2)]))
        list(mcf.walk())
        self.assertEqual(portal.asked, [0, 1])


class ShortfallTest(unittest.TestCase):
    """The sweep audits its own arithmetic, because nothing else would."""

    def test_a_truncated_sweep_is_reported_not_absorbed(self):
        connection = _memory(self)
        _install(self, _FakePortal([_full(100), _full(4, start=100)], total=84_739))
        swept = mcf.run(connection)
        self.assertEqual(swept.seen, 104)
        self.assertEqual(swept.shortfall, 84_635)
        self.assertIsNotNone(swept.problem, "a 104-row sweep of an 84,739-row board passed")

    def test_a_moving_index_is_turbulence_not_truncation(self):
        """`total` drifts by a dozen while the walk runs and a few rows slide
        across a page boundary. That must not read as a broken source."""
        connection = _memory(self)
        # Sized so the final page is naturally short, which is what ends the
        # walk. Truncating a full last page instead would discard 60 rows and
        # the shortfall under test would be those, not the drift.
        rows = _full(mcf.MIN_EXPECTED + 40)
        pages = [rows[n : n + 100] for n in range(0, len(rows), 100)]
        _install(self, _FakePortal(pages, total=len(rows) + 12))
        swept = mcf.run(connection)
        self.assertIsNone(swept.problem, swept.problem)
        self.assertEqual(swept.shortfall, 12)

    def test_duplicates_are_counted_and_not_double_written(self):
        connection = _memory(self)
        page = _full(100)
        _install(self, _FakePortal([page, [page[0], *_full(2, start=100)]], total=102))
        swept = mcf.run(connection)
        self.assertEqual(swept.repeats, 1)
        self.assertEqual(swept.seen, 102)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 102
        )

    def test_a_top_up_is_not_judged_against_the_whole_board(self):
        connection = _memory(self)
        _install(self, _FakePortal([_full(100), _full(1, start=100)], total=84_739))
        swept = mcf.run(connection, since="2026-08-17")
        self.assertTrue(swept.partial)
        self.assertEqual(swept.shortfall, 0)
        self.assertIsNone(swept.problem, "a deliberate top-up read as a broken source")

    def test_an_implausibly_small_full_sweep_fails(self):
        connection = _memory(self)
        _install(self, _FakePortal([_full(40)], total=40))
        swept = mcf.run(connection)
        self.assertIn("broken source", swept.problem or "")


class MappingTest(unittest.TestCase):
    def test_the_advertiser_name_is_carried(self):
        """This board is not one firm's own and the portal publishes no employer
        website, so without the name these are postings from nobody."""
        connection = _memory(self)
        _install(self, _FakePortal([[_row("a")]]))
        mcf.run(connection)
        row = connection.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(
            row["employer"], "QUBE RESEARCH & TECHNOLOGIES SINGAPORE PTE. LTD."
        )
        self.assertIsNone(row["domain"])
        self.assertEqual(row["ats"], "mycareersfuture")
        self.assertEqual(row["job_id"], "a")

    def test_the_firm_hired_for_outranks_the_agency_that_posted(self):
        job = mcf._job(
            _row("b", hiringCompany={"name": "OPTIVER ASIA PACIFIC PTE. LTD."})
        )
        self.assertEqual(job.employer, "OPTIVER ASIA PACIFIC PTE. LTD.")

    def test_the_portals_own_taxonomy_is_carried_verbatim(self):
        job = mcf._job(_row("c"))
        self.assertEqual(job.category, "Banking and Finance, Information Technology")

    def test_every_category_the_portal_publishes_is_named(self):
        """The union of these is exactly the unfiltered total, which is what
        makes them a complete cover. `Telecommunications` was the 43rd and was
        nearly missed -- it holds 66 postings and appeared in no sample."""
        self.assertEqual(len(mcf.CATEGORIES), 43)
        self.assertIn("Telecommunications", mcf.CATEGORIES)
        self.assertEqual(len(set(mcf.CATEGORIES)), 43)

    def test_the_location_names_the_country_the_gate_reads(self):
        """A gate makes every gap in a place list a deleted posting, and
        `singapore` is a focus hub matched on the location text."""
        job = mcf._job(_row("d"))
        self.assertTrue(job.location.startswith("Singapore"))
        self.assertIn("Marina", job.location)

    def test_islandwide_names_no_place_and_is_dropped(self):
        job = mcf._job(
            _row(
                "e",
                address={
                    "isOverseas": False,
                    "districts": [{"id": 998, "location": "Islandwide"}],
                },
            )
        )
        self.assertEqual(job.location, "Singapore")

    def test_an_overseas_posting_does_not_claim_singapore(self):
        job = mcf._job(
            _row(
                "f",
                address={
                    "isOverseas": True,
                    "overseasCountry": "Indonesia",
                    "districts": [{"id": 999, "location": "Overseas"}],
                },
            )
        )
        self.assertEqual(job.location, "Indonesia")

    def test_an_overseas_posting_whose_employer_said_singapore_is_believed(self):
        job = mcf._job(
            _row(
                "g",
                address={
                    "isOverseas": True,
                    "overseasCountry": "Singapore",
                    "districts": [{"id": 999, "location": "Overseas"}],
                },
            )
        )
        self.assertEqual(job.location, "Singapore")

    def test_a_missing_address_does_not_crash_or_invent_a_place(self):
        job = mcf._job(_row("h", address=None))
        self.assertEqual(job.location, "Singapore")

    def test_department_is_left_empty_on_purpose(self):
        """`positionLevels` and `minimumYearsExperience` are both published and
        both belong in columns of their own. `tagging.py` folds `department`
        into the *title* when reading rank, so a level parked there is a covert
        third door to seniority."""
        job = mcf._job(_row("i"))
        self.assertIsNone(job.department)


class ClosingDateTest(unittest.TestCase):
    def test_the_published_expiry_is_the_deadline(self):
        """The portal states a closing date as a field. Every one of the 9,485
        rows walked had one, and the board sorts an approaching deadline above
        everything else."""
        connection = _memory(self)
        _install(self, _FakePortal([[_row("j")]]))
        mcf.run(connection)
        self.assertEqual(
            connection.execute("SELECT deadline FROM jobs").fetchone()[0], "2026-09-11"
        )

    def test_a_posting_with_no_expiry_gets_none_rather_than_a_guess(self):
        job = mcf._job(_row("k", metadata={"newPostingDate": "2026-08-12"}))
        self.assertIsNone(job.deadline)

    def test_the_body_is_never_mined_for_a_date(self):
        job = mcf._job(
            _row(
                "l",
                description="<p>Apply by 30 September 2026.</p>",
                metadata={"newPostingDate": "2026-08-12"},
            )
        )
        self.assertIsNone(job.deadline, "a date was read out of prose")


class DescriptionTest(unittest.TestCase):
    def test_markup_is_stripped_and_entities_decoded(self):
        job = mcf._job(_row("m"))
        self.assertEqual(job.description, "Signals R&D")

    def test_an_escaped_tag_in_the_employers_prose_survives(self):
        """Decoding before stripping would turn a literal `&lt;p&gt;` into a tag
        and then eat it."""
        job = mcf._job(_row("n", description="<p>Write &lt;p&gt; tags</p>"))
        self.assertEqual(job.description, "Write <p> tags")

    def test_an_empty_body_is_none_rather_than_an_empty_string(self):
        self.assertIsNone(mcf._job(_row("o", description="<p> </p>")).description)
        self.assertIsNone(mcf._job(_row("p", description=None)).description)


class SearchEndpointTest(unittest.TestCase):
    def test_the_search_ceiling_is_recorded(self):
        """`/v2/search` advertises a last page of 672 and returns HTTP 418 from
        page 100 on. This module must never be "simplified" onto it."""
        self.assertEqual(mcf.SEARCH_PAGE_CEILING, 100)
        self.assertIn("/v2/jobs", mcf.LIST_URL)


class IdempotenceTest(unittest.TestCase):
    def test_re_sweeping_refreshes_rather_than_duplicates(self):
        connection = _memory(self)
        portal = _FakePortal([[_row("q")]])
        _install(self, portal)
        mcf.run(connection)
        mcf.run(connection)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_a_title_change_lands_but_a_vanished_body_does_not_erase_one(self):
        connection = _memory(self)
        _install(self, _FakePortal([[_row("r")]]))
        mcf.run(connection)
        _install(self, _FakePortal([[_row("r", title="Senior Quant Researcher", description=None)]]))
        mcf.run(connection)
        row = connection.execute("SELECT title, description FROM jobs").fetchone()
        self.assertEqual(row["title"], "Senior Quant Researcher")
        self.assertIsNotNone(row["description"], "a silent gap blanked a body we held")


if __name__ == "__main__":
    unittest.main()
