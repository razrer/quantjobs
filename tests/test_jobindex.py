"""Regression tests for Jobindex, Denmark's job board.

Five things here are easy to get wrong and quiet when wrong: the walk's stop
conditions, the recursive split that is the only reason a slice bigger than the
board's 1,000-posting window is read at all, the closing date (the board
publishes two dates and only one of them is one), the location string the
geography gate reads, and the JSON island the whole module depends on being
able to find.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sqlite3
import unittest

from quantscraper import db, jobindex, tagging


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _row(tid: str, **overrides) -> dict:
    row = {
        "tid": tid,
        "headline": "Kvantitativ analytiker til Markets",
        "companytext": "Danske Bank",
        "company": {"homeurl": "https://danskebank.dk/"},
        "area": "København K",
        "addresses": [{"city": "København K", "zipcode": "1092"}],
        "firstdate": "2026-08-17",
        "lastdate": "2026-09-06",
        "apply_deadline": "2026-09-06T21:59:59Z",
        "apply_deadline_asap": False,
        "share_url": f"https://www.jobindex.dk/vis-job/{tid}",
        "url": f"https://www.jobindex.dk/c?t={tid}&ctx=w&jobsearchid=1111055425",
        "html": "<div><p>Vi s&oslash;ger en analytiker.</p></div>",
        "is_archived": False,
    }
    row.update(overrides)
    return row


def _markup(
    rows: list[dict],
    *,
    hitcount: int | None = None,
    max_page: int = 50,
    page_size: int = 20,
    taxonomy: bool = True,
) -> str:
    """A page as the site serves it: the island inline, chrome either side."""
    store = {
        "searchResponse": {
            "results": rows,
            "hitcount": len(rows) if hitcount is None else hitcount,
            "max_page": max_page,
            "page_size": page_size,
        }
    }
    if taxonomy:
        store["subjobcategory_list"] = [
            ["Kontor og økonomi", [["Finans og forsikring", 35], ["Kontor", 18]]],
            ["Informationsteknologi", [["Systemudvikling og programmering", 1]]],
            ["Handel og service", [["Detailhandel", 70]]],
        ]
    stash = {"common": {"lang": "da"}, "jobsearch/result_app": {"storeData": store}}
    return (
        "<html><head><title>Ledige job</title></head><body>\n"
        "<script>//<![CDATA[\n\n    var Stash = "
        + json.dumps(stash, ensure_ascii=False)
        + ";\n//]]></script>\n</body></html>"
    )


class _FakeBoard:
    """Serves canned pages per query, counting what was actually asked for."""

    def __init__(self, pages: dict[tuple, list[list[dict]]], hitcounts=None):
        self.pages = pages
        self.hitcounts = hitcounts or {}
        self.asked: list[tuple] = []

    def _key(self, query: dict) -> tuple:
        return tuple(sorted(query.items()))

    def fetch_page(self, query: dict[str, int], page: int) -> jobindex.Page:
        key = self._key(query)
        self.asked.append((key, page))
        pages = self.pages.get(key, [])
        rows = pages[page - 1] if page <= len(pages) else []
        return jobindex.parse(
            _markup(
                rows,
                hitcount=self.hitcounts.get(key, sum(len(p) for p in pages)),
            )
        )

    def install(self, test: unittest.TestCase) -> "_FakeBoard":
        original = jobindex.fetch_page
        jobindex.fetch_page = self.fetch_page
        test.addCleanup(setattr, jobindex, "fetch_page", original)
        return self


def _full(count: int, start: int = 0) -> list[dict]:
    return [_row(f"h{start + n}") for n in range(count)]


class IslandTest(unittest.TestCase):
    """The module reads one JSON blob out of an HTML page; if that stops
    working every other test here is testing a fiction."""

    def test_the_island_is_read_out_of_a_real_looking_page(self):
        page = jobindex.parse(_markup(_full(3), hitcount=342))
        self.assertEqual(len(page.rows), 3)
        self.assertEqual(page.hitcount, 342)

    def test_the_board_is_believed_about_its_own_window(self):
        page = jobindex.parse(_markup(_full(2), max_page=12, page_size=25))
        self.assertEqual(page.max_page, 12)
        self.assertEqual(page.window, 300)

    def test_a_page_with_no_island_raises_rather_than_reading_as_empty(self):
        # An empty page is how a walk terminates, so a login wall or a redesign
        # must not be able to impersonate the end of a slice.
        with self.assertRaises(jobindex.Blocked):
            jobindex.parse("<html><body>Log ind for at fortsætte</body></html>")

    def test_an_island_without_a_search_response_raises(self):
        stash = {"common": {"lang": "da"}, "jobsearch/result_app": {"storeData": {}}}
        with self.assertRaises(jobindex.Blocked):
            jobindex.parse("var Stash = " + json.dumps(stash) + ";\n")

    def test_the_island_is_read_by_value_not_to_end_of_line(self):
        # The site puts it on one line today. A pretty-printer at their end
        # would silently halve every page if this depended on that.
        stash = {
            "jobsearch/result_app": {
                "storeData": {
                    "searchResponse": {
                        "results": [_row("h1")],
                        "hitcount": 1,
                        "max_page": 50,
                        "page_size": 20,
                    }
                }
            }
        }
        page = jobindex.parse(
            "var Stash = " + json.dumps(stash, indent=2) + ";\nmore();\n"
        )
        self.assertEqual(len(page.rows), 1)

    def test_the_live_taxonomy_is_read_off_the_page(self):
        page = jobindex.parse(_markup(_full(1)))
        self.assertEqual(page.taxonomy[35], "Finans og forsikring")
        self.assertEqual(page.taxonomy[1], "Systemudvikling og programmering")


class WalkTest(unittest.TestCase):
    def test_a_short_page_ends_the_walk(self):
        board = _FakeBoard({(): [_full(20), _full(5, 100)]}).install(self)
        self.assertEqual(sum(len(p.rows) for p in jobindex.walk({})), 25)
        self.assertEqual([page for _, page in board.asked], [1, 2])

    def test_an_empty_page_ends_the_walk(self):
        board = _FakeBoard({(): [_full(20)]}).install(self)
        self.assertEqual(sum(len(p.rows) for p in jobindex.walk({})), 20)
        self.assertEqual([page for _, page in board.asked], [1, 2])

    def test_a_repeated_page_ends_the_walk(self):
        # A server ignoring `page` serves page one forever and never returns an
        # empty page, so nothing else here would terminate.
        first = _full(20)
        board = _FakeBoard({(): [first, list(first), list(first)]}).install(self)
        self.assertEqual(sum(len(p.rows) for p in jobindex.walk({})), 20)
        self.assertEqual([page for _, page in board.asked], [1, 2])

    def test_the_walk_stops_at_the_boards_own_window(self):
        # 50 full pages is the ceiling; page 51 is a 404 on the live board, so
        # asking for it is the bug this pins.
        pages = [_full(20, n * 20) for n in range(60)]
        board = _FakeBoard({(): pages}, hitcounts={(): 1200}).install(self)
        collected = sum(len(page.rows) for page in jobindex.walk({}))
        self.assertEqual(collected, 1000)
        self.assertEqual(max(page for _, page in board.asked), 50)

    def test_page_one_already_in_hand_is_not_fetched_again(self):
        pages = [_full(20), _full(3, 100)]
        board = _FakeBoard({(): pages}).install(self)
        first = jobindex.parse(_markup(pages[0], hitcount=23))
        collected = list(jobindex.walk({}, first=first))
        self.assertEqual(sum(len(p.rows) for p in collected), 23)
        self.assertEqual([page for _, page in board.asked], [2])


class SinceTest(unittest.TestCase):
    def test_a_page_entirely_older_than_the_cutoff_ends_the_walk(self):
        recent = [_row(f"h{n}", firstdate="2026-08-18") for n in range(20)]
        old = [_row(f"h{100 + n}", firstdate="2026-08-01") for n in range(20)]
        board = _FakeBoard({(): [recent, old, _full(20, 200)]}).install(self)
        collected = list(jobindex.walk({}, since="2026-08-10"))
        self.assertEqual(sum(len(p.rows) for p in collected), 40)
        self.assertEqual([page for _, page in board.asked], [1, 2])

    def test_a_page_still_holding_the_cutoff_day_is_not_the_last(self):
        # Postings sharing a day are in no guaranteed order among themselves,
        # so a page mixing the cutoff day with older rows must not end the walk.
        mixed = [_row("h1", firstdate="2026-08-10"), _row("h2", firstdate="2026-08-01")]
        mixed += [_row(f"h{n}", firstdate="2026-08-01") for n in range(3, 21)]
        board = _FakeBoard({(): [mixed, _full(2, 100)]}).install(self)
        collected = list(jobindex.walk({}, since="2026-08-10"))
        self.assertEqual(sum(len(p.rows) for p in collected), 22)

    def test_no_cutoff_reads_the_whole_slice(self):
        board = _FakeBoard({(): [_full(20), _full(20, 100), _full(1, 200)]})
        board.install(self)
        self.assertEqual(sum(len(p.rows) for p in jobindex.walk({})), 41)


class SplitTest(unittest.TestCase):
    """The recursive split is what makes this an enumeration rather than a
    sample. Getting it wrong loses the oldest postings of the biggest
    categories, and nothing about the output would say so."""

    def _board(self) -> _FakeBoard:
        # subid 35 advertises 40 and fits. subid 70 advertises 1,400 and does
        # not, so it must be cut along the first split dimension.
        pages = {
            (("subid", 35),): [_full(20, 0), _full(20, 20)],
            (("subid", 70),): [_full(20, n * 20) for n in range(50)],
        }
        hits = {(("subid", 35),): 40, (("subid", 70),): 1400}
        for value, size in ((1, 600), (2, 700), (-1, 100)):
            key = (("subid", 70), ("workinghours_type", value))
            pages[key] = [_full(20, 5000 * value + n * 20) for n in range(size // 20)]
            hits[key] = size
        return _FakeBoard(pages, hits).install(self)

    def test_a_slice_inside_the_window_is_walked_whole_and_not_split(self):
        board = self._board()
        sweep = jobindex.run(_memory(self), only=[35])
        self.assertEqual(sweep.seen, 40)
        self.assertEqual(sweep.slices, 1)
        self.assertFalse(sweep.truncated)
        self.assertNotIn("workinghours_type", {k for key, _ in board.asked for k, _ in key})

    def test_a_slice_bigger_than_the_window_is_split_rather_than_truncated(self):
        self._board()
        sweep = jobindex.run(_memory(self), only=[70])
        # 600 + 700 + 100 with no overlap between the three, against a slice
        # the window would have cut to 1,000.
        self.assertEqual(sweep.seen, 1400)
        self.assertEqual(sweep.slices, 3)
        self.assertFalse(sweep.truncated)

    def test_the_split_uses_the_sites_own_unspecified_bucket(self):
        # Without the -1 value the split is a filter, not a cover: every ad
        # that left the field blank would be dropped and nothing would say so.
        for name, values in jobindex.SPLIT_DIMENSIONS:
            with self.subTest(dimension=name):
                self.assertIn(-1 if name != "employment_place" else 4, values)

    def test_a_slice_that_cannot_be_split_far_enough_is_reported_not_absorbed(self):
        pages = {(("subid", 70),): [_full(20, n * 20) for n in range(50)]}
        hits = {(("subid", 70),): 9999}
        # Every split value reports the same oversized count, so the recursion
        # runs out of dimensions with the slice still too big.
        def _stuff(prefix, depth):
            if depth >= len(jobindex.SPLIT_DIMENSIONS):
                return
            name, values = jobindex.SPLIT_DIMENSIONS[depth]
            for value in values:
                # Sorted, because `_FakeBoard` keys a query by its sorted items
                # and the split builds them in dimension order.
                key = tuple(sorted(prefix + ((name, value),)))
                pages[key] = [_full(20, n * 20) for n in range(50)]
                hits[key] = 9999
                _stuff(key, depth + 1)
        _stuff((("subid", 70),), 0)
        _FakeBoard(pages, hits).install(self)

        sweep = jobindex.run(_memory(self), only=[70])
        self.assertTrue(sweep.truncated)
        self.assertIn("never reached", sweep.problem)
        self.assertGreater(sweep.unread, 0)


class SweepTest(unittest.TestCase):
    def test_a_posting_filed_under_two_categories_is_counted_once(self):
        shared = _full(5)
        board = _FakeBoard(
            {(("subid", 35),): [shared], (("subid", 18),): [list(shared)]},
            {(("subid", 35),): 5, (("subid", 18),): 5},
        )
        board.install(self)
        connection = _memory(self)
        sweep = jobindex.run(connection, only=[35, 18])
        self.assertEqual(sweep.seen, 5)
        self.assertEqual(sweep.repeats, 5)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 5
        )

    def test_a_posting_in_two_categories_keeps_both_not_the_first(self):
        # Otherwise `jobs.category` holds whichever slice happened to reach it
        # first, so a posting under both cleaning and finance is gated or kept
        # depending on sweep order.
        shared = _full(2)
        _FakeBoard(
            {(("subid", 35),): [shared], (("subid", 18),): [list(shared)]},
            {(("subid", 35),): 2, (("subid", 18),): 2},
        ).install(self)
        connection = _memory(self)
        jobindex.run(connection, only=[35, 18])
        held = {
            row[0] for row in connection.execute("SELECT DISTINCT category FROM jobs")
        }
        self.assertEqual(held, {"Finans og forsikring | Kontor"})

    def test_a_named_subset_is_not_judged_against_the_whole_board(self):
        _FakeBoard({(("subid", 35),): [_full(3)]}, {(("subid", 35),): 3}).install(self)
        sweep = jobindex.run(_memory(self), only=[35])
        self.assertTrue(sweep.partial)
        self.assertIsNone(sweep.problem)

    def test_an_implausibly_small_full_sweep_fails(self):
        _FakeBoard(
            {(): [_full(2)], (("subid", 35),): [_full(2)], (("subid", 18),): [],
             (("subid", 1),): []},
            {(): 17534},
        ).install(self)
        sweep = jobindex.run(_memory(self))
        self.assertFalse(sweep.partial)
        self.assertIn("broken source", sweep.problem)

    def test_a_top_up_that_ran_out_of_window_says_so(self):
        # Reaching the ceiling means the cutoff was never reached, so the days
        # in between were read by nobody -- the opposite of a clean poll.
        pages = [_full(20, n * 20) for n in range(60)]
        _FakeBoard({(): pages}, {(): 5000}).install(self)
        sweep = jobindex.run(_memory(self), since="2020-01-01")
        self.assertTrue(sweep.stale)
        self.assertIn("run a full sweep", sweep.problem)

    def test_a_top_up_never_erases_a_category_a_full_sweep_established(self):
        # The unfiltered board says which postings exist, not which slice they
        # belong to, so a top-up carries no category at all. Overwriting with
        # that would silently un-gate every Danish nurse and cleaner between
        # full sweeps.
        rows = [_row("h1", firstdate="2026-08-01")]
        _FakeBoard(
            {(): [rows], (("subid", 35),): [rows]},
            {(): 5000, (("subid", 35),): 1},
        ).install(self)
        connection = _memory(self)
        jobindex.run(connection, only=[35])
        jobindex.run(connection, since="2026-08-18")
        self.assertEqual(
            connection.execute("SELECT category FROM jobs").fetchone()[0],
            "Finans og forsikring",
        )

    def test_a_top_up_that_reached_the_date_is_sound(self):
        rows = [_row(f"h{n}", firstdate="2026-08-01") for n in range(20)]
        _FakeBoard({(): [rows]}, {(): 5000}).install(self)
        sweep = jobindex.run(_memory(self), since="2026-08-18")
        self.assertFalse(sweep.stale)
        self.assertIsNone(sweep.problem)

    def test_a_subcategory_the_board_grew_is_swept_and_named(self):
        # The partition is read live, so a new category is enumerated without
        # an edit here; naming it is how the read-time gate learns it exists.
        live = dict(jobindex.SUBCATEGORIES)
        live[999] = "Rumfart"
        _FakeBoard(
            {(): [_full(1)], **{(("subid", sid),): [] for sid in live}},
            {(): 17534},
        ).install(self)
        original = jobindex.parse

        def _with_new_category(markup: str) -> jobindex.Page:
            page = original(markup)
            return jobindex.Page(page.rows, page.hitcount, page.max_page,
                                 page.page_size, live)

        jobindex.parse = _with_new_category
        self.addCleanup(setattr, jobindex, "parse", original)
        sweep = jobindex.run(_memory(self))
        self.assertEqual(sweep.unknown_subcategories, {999: "Rumfart"})


class MappingTest(unittest.TestCase):
    def _job(self, **overrides):
        return jobindex._job(_row("h1", **overrides), "Finans og forsikring")

    def test_the_advertiser_name_is_carried(self):
        self.assertEqual(self._job().employer, "Danske Bank")

    def test_the_boards_own_taxonomy_is_carried_verbatim(self):
        self.assertEqual(self._job().category, "Finans og forsikring")

    def test_the_stable_share_url_is_kept_not_the_click_tracker(self):
        # `url` on the row is a `/c?t=...` redirect carrying the search session
        # it was minted in, and robots.txt disallows it outright.
        job = self._job()
        self.assertEqual(job.url, "https://www.jobindex.dk/vis-job/h1")
        self.assertNotIn("/c?", job.url)

    def test_the_employers_own_host_becomes_the_domain(self):
        self.assertEqual(jobindex._domain(_row("h1")), "danskebank.dk")

    def test_a_social_page_is_not_an_employer_domain(self):
        row = _row("h1", company={"homeurl": "https://www.linkedin.com/company/x/"})
        self.assertIsNone(jobindex._domain(row))

    def test_a_missing_website_is_none_rather_than_a_crash(self):
        self.assertIsNone(jobindex._domain(_row("h1", company={})))
        self.assertIsNone(jobindex._domain(_row("h1", company=None)))

    def test_the_area_is_the_location_the_gate_reads(self):
        self.assertEqual(self._job().location, "København K")

    def test_a_blank_area_falls_back_to_the_structured_address(self):
        job = self._job(area="", addresses=[{"city": "Aarhus C", "zipcode": "8000"}])
        self.assertEqual(job.location, "Aarhus C")

    def test_one_seat_across_three_of_a_firms_offices_names_each_town_once(self):
        job = self._job(
            area=None,
            addresses=[{"city": "Herlev"}, {"city": "Herlev"}, {"city": "Odense"}],
        )
        self.assertEqual(job.location, "Herlev, Odense")

    def test_no_place_at_all_is_none_rather_than_an_invented_one(self):
        self.assertIsNone(self._job(area=None, addresses=[]).location)

    def test_department_is_left_empty_on_purpose(self):
        # `tagging.py` folds `department` into the title when reading rank and
        # role, so anything parked there is a covert door to seniority.
        self.assertIsNone(self._job().department)

    def test_the_danish_capital_survives_folding(self):
        # Every Copenhagen posting gates as off-location if it does not: the
        # place list spells the city `kobenhavn`, the board spells it with an ø.
        self.assertIn(" kobenhavn ", tagging.fold(self._job().location))


class GeographyTest(unittest.TestCase):
    """Jobindex writes a *postcode and town* — `2650 Hvidovre` — and never the
    word København, so a gap in the place list is a Copenhagen posting deleted
    for being somewhere else. 1,444 of them were, before the belt went in.
    """

    def _hub(self, location: str) -> str:
        from quantscraper.tagging import _HUBS, _first, fold

        found = _first(_HUBS, fold(location, ""))
        return found[0] if found else "other"

    def test_the_suburbs_the_board_actually_publishes_are_copenhagen(self):
        for place in (
            "2650 Hvidovre", "2605 Brøndby", "2770 Kastrup", "2610 Rødovre",
            "2500 Valby", "2670 Greve", "2620 Albertslund", "2150 Nordhavn",
            "2635 Ishøj", "2720 Vanløse", "2791 Dragør", "2880 Bagsværd",
            "3460 Birkerød", "4600 Køge", "3520 Farum", "Storkøbenhavn",
        ):
            with self.subTest(place=place):
                self.assertEqual(self._hub(place), "copenhagen")

    def test_the_rest_of_denmark_is_named_rather_than_lumped_into_other(self):
        # Same gate either way, but `other` means "we read it and it was
        # Bangalore" — so answering "where did Denmark go?" with it is a lie
        # the board would tell on every build.
        for place in ("7400 Herning", "8600 Silkeborg", "4200 Slagelse",
                      "3000 Helsingør", "6400 Sønderborg"):
            with self.subTest(place=place):
                self.assertEqual(self._hub(place), "denmark_other")

    def test_a_north_american_street_number_is_not_a_danish_postcode(self):
        # The rejected alternative was reading the leading four digits as a
        # postcode. Measured over the corpus, that claimed **225 US and
        # Canadian street addresses as Copenhagen** — Philadelphia, Montreal,
        # Toronto — and a wrong hub in a focus hub puts them on the board.
        for place in ("2005 Market Street, Philadelphia, Pennsylvania",
                      "1966 Yonge Street, Toronto, Ontario",
                      "2925 VIRTUAL WAY:VANCOUVER"):
            with self.subTest(place=place):
                self.assertNotEqual(self._hub(place), "copenhagen")


class ClosingDateTest(unittest.TestCase):
    """The board publishes two dates on every row and only one is a deadline.
    The board sorts an approaching deadline above everything else, so reading
    the wrong one nails thousands of Danish cards to the top of the page."""

    def test_the_published_application_deadline_is_the_deadline(self):
        job = jobindex._job(_row("h1"), None)
        self.assertEqual(job.deadline, "2026-09-06T21:59:59Z")

    def test_an_as_soon_as_possible_ad_has_no_deadline_rather_than_a_guess(self):
        job = jobindex._job(
            _row("h1", apply_deadline=None, apply_deadline_asap=True), None
        )
        self.assertIsNone(job.deadline)

    def test_the_ads_own_run_end_is_never_read_as_a_closing_date(self):
        # `lastdate` is set on every row and is when the advertisement comes
        # down, which Jobindex decides -- not a date the employer stated.
        row = _row("h1", apply_deadline=None, apply_deadline_asap=True,
                   lastdate="2026-09-16")
        self.assertIsNone(jobindex._job(row, None).deadline)

    def test_an_asap_flag_beats_a_stray_date(self):
        row = _row("h1", apply_deadline="2026-09-06T21:59:59Z",
                   apply_deadline_asap=True)
        self.assertIsNone(jobindex._job(row, None).deadline)


class DescriptionTest(unittest.TestCase):
    def test_markup_is_stripped_and_entities_decoded(self):
        job = jobindex._job(_row("h1"), None)
        self.assertEqual(job.description, "Vi søger en analytiker.")

    def test_an_escaped_tag_in_the_employers_prose_survives(self):
        row = _row("h1", html="<p>Skriv &lt;h1&gt; korrekt</p>")
        self.assertEqual(jobindex._job(row, None).description, "Skriv <h1> korrekt")

    def test_an_empty_teaser_is_none_rather_than_an_empty_string(self):
        self.assertIsNone(jobindex._job(_row("h1", html=""), None).description)


class IdempotenceTest(unittest.TestCase):
    def test_re_sweeping_refreshes_rather_than_duplicates(self):
        _FakeBoard({(("subid", 35),): [_full(4)]}, {(("subid", 35),): 4}).install(self)
        connection = _memory(self)
        jobindex.run(connection, only=[35])
        jobindex.run(connection, only=[35])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 4
        )

    def test_each_row_keeps_its_own_employer_domain(self):
        # Every other source's board *is* one firm's, so `db.upsert_jobs` takes
        # a single domain for a batch. Here the rows are grouped by theirs.
        rows = [
            _row("h1", company={"homeurl": "https://danskebank.dk/"}),
            _row("h2", company={"homeurl": "https://nykredit.dk/"}),
            _row("h3", company={"homeurl": "https://danskebank.dk/"}),
        ]
        _FakeBoard({(("subid", 35),): [rows]}, {(("subid", 35),): 3}).install(self)
        connection = _memory(self)
        jobindex.run(connection, only=[35])
        held = dict(
            connection.execute("SELECT job_id, domain FROM jobs").fetchall()
        )
        self.assertEqual(
            held, {"h1": "danskebank.dk", "h2": "nykredit.dk", "h3": "danskebank.dk"}
        )


class CategoryGateTest(unittest.TestCase):
    """The board's own taxonomy is the gate, the same argument the Swedish
    occupation fields and the Singaporean categories make. Denmark needs it
    more than either: the occupation word lists in `tagging.py` are English and
    Swedish, so `Sygeplejerske` and `Pædagog` are caught by no needle at all.
    """

    def test_a_posting_in_an_off_industry_category_is_gated(self):
        from quantscraper.tagging import _jobindex_off_industry

        self.assertIsNotNone(_jobindex_off_industry("Pædagog"))
        self.assertIsNotNone(_jobindex_off_industry("Rengøring | Bud og udbringning"))

    def test_a_label_containing_a_comma_is_not_cut_in_half(self):
        # `Hotel, restaurant og køkken` and `Landbrug, skov og fiskeri` are one
        # category each. Splitting on the comma leaves four names matching
        # nothing, and the gate stops firing on two of the biggest trades on
        # the board -- silently, because a gate that never fires looks the same
        # from outside as a board with no such postings.
        from quantscraper.tagging import _jobindex_off_industry

        self.assertIsNotNone(_jobindex_off_industry("Hotel, restaurant og køkken"))
        self.assertIsNotNone(_jobindex_off_industry("Landbrug, skov og fiskeri"))

    def test_one_kept_category_keeps_the_posting(self):
        # A posting is filed under more than one category about a quarter of
        # the time, and one kept category is enough -- a subset test, never
        # equality, the same direction the Swedish drop list picks.
        from quantscraper.tagging import _jobindex_off_industry

        self.assertIsNone(_jobindex_off_industry("Rengøring | Finans og forsikring"))

    def test_finance_and_research_are_never_gated(self):
        from quantscraper.tagging import _jobindex_off_industry

        self.assertIsNone(_jobindex_off_industry("Finans og forsikring"))
        self.assertIsNone(_jobindex_off_industry("Forskning"))
        self.assertIsNone(_jobindex_off_industry("Systemudvikling og programmering"))

    def test_an_unrecognised_category_passes(self):
        # A drop list fails towards keeping, so a name the board invents
        # reaches the reader rather than vanishing.
        from quantscraper.tagging import _jobindex_off_industry

        self.assertIsNone(_jobindex_off_industry("Rumfart"))
        self.assertIsNone(_jobindex_off_industry(None))

    def test_every_gated_name_is_one_the_board_actually_publishes(self):
        # A typo here gates nothing and looks like it gates something.
        from quantscraper.tagging import _JOBINDEX_OFF_INDUSTRY

        self.assertTrue(_JOBINDEX_OFF_INDUSTRY <= set(jobindex.SUBCATEGORIES.values()))


if __name__ == "__main__":
    unittest.main()
