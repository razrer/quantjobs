"""Regression tests for the Interactive Employment Service (Hong Kong) portal.

Five things here are easy to get wrong and quiet when wrong: the page walk's
stop conditions, the shortfall arithmetic that is the only thing standing
between a truncated sweep and a plausible-looking number, the location string
the geography gate reads, the day-first date, and the row parse itself -- a
board that answers 200 and yields nothing is principle 2 exactly.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from quantscraper import bodies, db, iesjobs, tagging


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _row(
    index: int,
    ordno: str,
    title: str,
    *,
    posted: str = "01/09/2026",
    location: str = "Mong Kok",
) -> str:
    """One list row, in the markup the portal actually serves."""
    return f"""
    <tr class="bg-white">
      <td>{index}.</td>
      <td>
        <div class="container-fluid"><div class="row">
          <div class="col col-lg-3 mb-2 mb-lg-0">
            <span class="d-flex flex-column">
              <span>{title}</span>
              <span>
                <text class="d-none d-lg-inline">Job Order No.: </text>
                <a id="{index}_orderNo_hyper" style="color:#107d6a;"
                   href="/0/en/jobseeker/jobCard/?order=T0tFTg%3D%3D&amp;from=joblist">{ordno}</a>
              </span>
            </span>
          </div>
          <div class="col mb-2 mb-lg-0">
            <img src="/0/Image/common/common/ies_job_icon1.svg" alt="" role="presentation" />
            <span>{posted}</span>
          </div>
          <div class="col mb-2 mb-lg-0">
            <img src="/0/Image/common/common/ies_job_icon2.svg" alt="" role="presentation" />
            <span>$16,000 - $18,000  per month</span>
          </div>
          <div class="col mb-2 mb-lg-0">
            <img src="/0/Image/common/common/ies_job_fill_but3.svg" alt="" role="presentation" />
            <span>{location}</span>
          </div>
        </div></div>
      </td>
    </tr>
    """


def _page(rows: list[str], advertised: int = 14_287) -> str:
    listed = "".join(rows)
    header = (
        f"<div>Results <strong>1</strong> to <strong>{len(rows)}</strong>"
        f" of <strong>{advertised:,d}</strong></div>"
        if rows
        else ""
    )
    return f"<html><body>{header}<table id='job_list_table'><tbody>{listed}</tbody></table></body></html>"


def _full(count: int, *, start: int = 0) -> str:
    return _page([
        _row(n + 1, f"22-26-{start + n:07d}", f"Analyst {start + n}")
        for n in range(count)
    ])


class _FakePortal:
    """Serves the given pages in order, recording which were asked for.

    `pages` is either a list, meaning the unfiltered list, or a
    `{jobtype: [pages]}` map -- the walk is a partition, so a fixture has to
    be able to answer per slice. A slice with no entry answers empty, which is
    what an unused job type looks like.
    """

    def __init__(self, pages):
        self.pages = pages if isinstance(pages, dict) else {None: pages}
        self.asked: list[int] = []
        self.slices: list[int | None] = []

    def __call__(self, url: str, **kwargs) -> str:
        number = 1
        if "?page=" in url:
            number = int(url.rsplit("=", 1)[1])
        jobtype = None
        if "/jobtype/" in url:
            jobtype = int(url.split("/jobtype/")[1].split("/")[0])
        self.asked.append(number)
        self.slices.append(jobtype)
        pages = self.pages.get(jobtype, [])
        index = number - 1
        return pages[index] if index < len(pages) else _page([])


def _install(test: unittest.TestCase, portal: _FakePortal) -> _FakePortal:
    patch = mock.patch.object(iesjobs.http, "get_text", portal)
    patch.start()
    test.addCleanup(patch.stop)
    return portal


class PageSizeTest(unittest.TestCase):
    def test_the_page_size_the_portal_actually_serves_is_asserted(self):
        """`pageSize=100` is accepted and ignored -- the MAS trap one territory
        over. Twenty is a fact about the board, not a parameter."""
        self.assertEqual(iesjobs.PAGE_SIZE, 20)

    def test_the_page_bound_is_a_backstop_not_a_cap(self):
        """The real walk ends at 715. A bound anywhere near that is a silent
        truncation -- the Workday reader was capped at 40 pages and State
        Street came back at exactly 800."""
        self.assertGreaterEqual(iesjobs.MAX_PAGES, 3_000)


class ParseTest(unittest.TestCase):
    def test_a_row_yields_every_field_the_list_carries(self):
        jobs, advertised = None, None
        _install(self, _FakePortal([_page([_row(1, "22-26-0017657", "Loan Clerk")])]))
        jobs, advertised = iesjobs.fetch_page(1)
        self.assertEqual(advertised, 14_287)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.job_id, "22-26-0017657")
        self.assertEqual(job.title, "Loan Clerk")
        self.assertEqual(job.posted_at, "2026-09-01")
        self.assertEqual(job.location, "Hong Kong, Mong Kok")
        # The list carries none of these, and inventing one would be worse
        # than NULL. `url` is NULL on purpose: the portal's card token expires
        # with time, so a stored one answers HTTP 200 with the vacancy-search
        # page -- `CLAUDE.md`'s "worse than no link" exactly.
        self.assertIsNone(job.url)
        self.assertIsNone(job.employer)
        self.assertIsNone(job.description)

    def test_the_perishable_card_token_is_never_stored(self):
        """A card link that stops working is the failure this refuses. It cost
        968 filled rows and then silence before it was found."""
        _install(self, _FakePortal([_page([_row(1, "1-1-1", "Analyst")])]))
        self.assertIsNone(iesjobs.fetch_page(1)[0][0].url)

    def test_the_programme_marker_is_not_part_of_the_title(self):
        """`**` is the portal's own footnote -- *the employer is interested in
        the Employment Programme for the Elderly and Middle-aged* -- which is a
        fact about the employer's hiring scheme, not the job's name."""
        _install(self, _FakePortal([_page([_row(1, "1-1-1", "Financial Planner**")])]))
        self.assertEqual(iesjobs.fetch_page(1)[0][0].title, "Financial Planner")

    def test_a_page_of_rows_that_yields_no_postings_is_loud(self):
        """A board answering HTTP 200 and coming back empty is principle 2
        exactly, and the shortfall check alone would call it truncation --
        which reads as our paging being wrong rather than their page having
        changed."""
        broken = _row(1, "22-26-0017657", "Loan Clerk").replace(
            "<span>Loan Clerk</span>", "<span></span>"
        )
        _install(self, _FakePortal([_page([broken, broken])]))
        with self.assertRaises(ValueError):
            iesjobs.fetch_page(1)

    def test_one_bad_row_is_skipped_rather_than_ending_the_sweep(self):
        """A freak posting must not cost a fifty-minute walk. It is still
        counted, because the slice compares what arrived against the hitcount
        the portal printed on the same page."""
        broken = _row(1, "22-26-0017657", "Loan Clerk").replace(
            "<span>Loan Clerk</span>", "<span></span>"
        )
        good = _row(2, "22-26-0017658", "Quantitative Analyst")
        _install(self, _FakePortal([_page([broken, good])]))
        jobs, _ = iesjobs.fetch_page(1)
        self.assertEqual([j.job_id for j in jobs], ["22-26-0017658"])


class DateTest(unittest.TestCase):
    """`01/09/2026` is day-first. Read month-first it files September in
    January, and the board orders on dates."""

    def test_day_comes_first(self):
        self.assertEqual(iesjobs._posted("01/09/2026"), "2026-09-01")
        self.assertEqual(iesjobs._posted("28/02/2026"), "2026-02-28")

    def test_anything_else_is_no_date_rather_than_a_guess(self):
        for value in ("2026-09-01", "1/9/26", "", None, "Sep 2026"):
            with self.subTest(value=value):
                self.assertIsNone(iesjobs._posted(value))


class LocationTest(unittest.TestCase):
    """A district matches no needle in `tagging._HUBS`, so `Tsing Yi` alone
    reads `other` and the board *gates* `other`. The territory has to lead --
    the same handle MyCareersFuture uses for Singapore."""

    def test_a_district_gets_the_territory_in_front_of_it(self):
        self.assertEqual(iesjobs._location("Tsing Yi"), "Hong Kong, Tsing Yi")
        self.assertEqual(
            iesjobs._location("Admiralty/ Queensway"),
            "Hong Kong, Admiralty/ Queensway",
        )

    def test_a_posting_named_only_outside_the_territory_does_not_claim_it(self):
        """Measured over the portal's own `Outside HK` bucket: 461 of its 741
        rows name only a mainland city, and the whole vocabulary is nine
        words."""
        for value in ("Shenzhen", "Guangzhou", "Mainland China",
                      "Shenzhen,Guangzhou", "Macao"):
            with self.subTest(value=value):
                self.assertNotIn("Hong Kong", iesjobs._location(value) or "")

    def test_a_district_beside_a_mainland_city_keeps_both(self):
        """The other 280 rows in that bucket are Hong Kong jobs with mainland
        travel, and they are in Hong Kong."""
        self.assertEqual(
            iesjobs._location("Kwun Tong,Mainland China"),
            "Hong Kong, Kwun Tong, Mainland China",
        )

    def test_no_place_at_all_stays_unknown(self):
        """`unknown` survives the geography gate and `other` does not, so a
        posting naming nowhere must not be handed a city."""
        self.assertIsNone(iesjobs._location(""))
        self.assertIsNone(iesjobs._location(None))


class WalkTest(unittest.TestCase):
    def test_a_short_page_does_not_end_the_walk(self):
        """Jobbsafari reported 5,421 postings of 48,000 because one page came
        back 499 rows instead of 500, and Oracle truncated Kotak at 3,199 of
        9,959 the same way. Only an empty page ends a walk."""
        portal = _install(self, _FakePortal(
            [_full(20), _full(7, start=20), _full(20, start=27), _page([])]
        ))
        collected = [job for page, _ in iesjobs.walk() for job in page]
        self.assertEqual(len(collected), 47, "the walk stopped on the short page")
        self.assertEqual(portal.asked, [1, 2, 3, 4])

    def test_an_empty_page_ends_the_walk(self):
        portal = _install(self, _FakePortal([_full(20), _page([])]))
        self.assertEqual(len([j for p, _ in iesjobs.walk() for j in p]), 20)
        self.assertEqual(portal.asked, [1, 2])

    def test_a_repeated_page_ends_the_walk(self):
        """A server ignoring `page` serves page one forever and never returns
        an empty page, so nothing else in the loop would terminate."""
        page = _full(20)
        portal = _install(self, _FakePortal([page, page, page, page]))
        collected = [job for got, _ in iesjobs.walk(max_pages=50) for job in got]
        self.assertEqual(len(collected), 20, "the repeat was not detected")
        self.assertEqual(portal.asked, [1, 2])

    def test_the_first_page_carries_no_page_parameter(self):
        """The portal serves the list at the bare path; `?page=1` works too,
        and asking for the plain URL is what a reader would open."""
        portal = _install(self, _FakePortal([_full(20), _page([])]))
        list(iesjobs.walk())
        self.assertEqual(portal.asked[0], 1)


class ShortfallTest(unittest.TestCase):
    """The sweep audits its own arithmetic, because nothing else would: a
    round number in the output is what a cap looks like from outside."""

    def _sweep(self, **kwargs):
        return iesjobs.Sweep(
            pages=kwargs.get("pages", 715),
            seen=kwargs["seen"],
            written=kwargs["seen"],
            advertised=kwargs.get("advertised", 14_287),
            repeats=0,
            partial=kwargs.get("partial", False),
        )

    def test_a_complete_sweep_has_no_problem(self):
        self.assertIsNone(self._sweep(seen=14_280).problem)

    def test_a_truncated_sweep_is_reported_not_absorbed(self):
        problem = self._sweep(seen=10_000).problem
        self.assertIsNotNone(problem)
        self.assertIn("truncation", problem)

    def test_an_implausibly_small_result_is_a_failure(self):
        problem = self._sweep(seen=12, advertised=12).problem
        self.assertIsNotNone(problem)
        self.assertIn("broken source", problem)

    def test_a_missing_hitcount_fails_rather_than_passes(self):
        """A check whose evidence is missing must fail, not pass -- the
        `X-Total-Count` lesson, where a case-sensitive lookup read the total as
        zero and the truncation guard went quiet on a walk that had stopped
        dead on a result window."""
        problem = self._sweep(seen=14_287, advertised=0).problem
        self.assertIsNotNone(problem)
        self.assertIn("hitcount", problem)

    def test_a_bounded_run_is_never_reported_as_a_complete_one(self):
        self.assertIsNone(self._sweep(seen=40, partial=True).problem)


class RunTest(unittest.TestCase):
    """The sweep walks the job-type partition and audits the union against the
    unfiltered total, which is what re-proves the partition every run."""

    def test_a_sweep_writes_the_postings_and_counts_itself(self):
        portal = _install(self, _FakePortal({
            4: [_full(20), _page([])],
            11: [_full(20, start=20), _page([])],
            None: [_page([_row(1, "x", "y")], advertised=40)],
        }))
        connection = _memory(self)
        swept = iesjobs.run(connection, max_pages=iesjobs.MAX_PAGES)
        self.assertEqual(swept.pages, 2)
        self.assertEqual(swept.seen, 40)
        self.assertEqual(swept.written, 40)
        self.assertEqual(swept.advertised, 40)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"], 40
        )
        # Every slice was asked for, including the ones with nothing in them.
        self.assertEqual(
            {s for s in portal.slices if s is not None},
            {key for key, _ in iesjobs.JOB_TYPES},
        )

    def test_the_slice_writes_the_portal_own_occupation_onto_every_row(self):
        """The label comes from the URL, because the list prints it nowhere in
        the markup -- which is also why each posting is read exactly once."""
        _install(self, _FakePortal({4: [_full(20), _page([])]}))
        connection = _memory(self)
        iesjobs.run(connection)
        self.assertEqual(
            {r["category"] for r in connection.execute("SELECT category FROM jobs")},
            {"Cleaner"},
        )

    def test_a_row_served_twice_is_counted_once(self):
        """A posting appearing in two slices would break the partition, and it
        arrives here as a repeat rather than as a silent duplicate."""
        _install(self, _FakePortal({
            4: [_full(20), _page([])],
            11: [_full(20, start=15), _page([])],
        }))
        swept = iesjobs.run(_memory(self))
        self.assertEqual(swept.seen, 35)
        self.assertEqual(swept.repeats, 5)

    def test_a_partition_missing_a_facet_shows_up_as_a_shortfall(self):
        """The union check is the only thing that can see this: every slice
        this module knows about was complete, and the board is still bigger."""
        _install(self, _FakePortal({
            4: [_full(20), _page([])],
            None: [_page([_row(1, "x", "y")], advertised=9_000)],
        }))
        swept = iesjobs.run(_memory(self))
        self.assertEqual(swept.advertised, 9_000)
        self.assertIsNotNone(swept.problem)

    def test_a_slice_that_advertises_and_yields_nothing_is_loud(self):
        """HTTP 200 with an empty board is the failure this project cares most
        about not being fooled by."""
        empty_but_advertised = _page([], advertised=0).replace(
            "<tbody>",
            "<div>Results <strong>1</strong> to <strong>0</strong>"
            " of <strong>400</strong></div><tbody>",
        )
        _install(self, _FakePortal({4: [empty_but_advertised]}))
        swept = iesjobs.run(_memory(self))
        self.assertEqual(swept.seen, 0)

    def test_an_empty_slice_is_not_a_fault(self):
        """`Tour Guide` advertised zero on the day the partition was measured,
        and a facet with no vacancies is a fact rather than a fault."""
        self.assertIsNone(iesjobs.Slice(28, "Tour Guide", 0, 0, 0).problem)

    def test_a_bounded_run_marks_itself_partial(self):
        _install(self, _FakePortal({4: [_full(20)] * 4}))
        self.assertTrue(iesjobs.run(_memory(self), max_pages=2).partial)


class NotAFirmsBoardTest(unittest.TestCase):
    """One token carrying every job in a territory is not an employer, and
    every consumer that profiles a board has to know it."""

    def test_the_portal_is_excluded_from_board_profiling(self):
        from quantscraper import lexicon

        self.assertIn(iesjobs.NAME, lexicon.NOT_A_BOARD)

    def test_the_portal_is_a_republisher_for_the_de_duplicator(self):
        from quantscraper import dedup

        self.assertIn(iesjobs.NAME, dedup.PORTALS)

    def test_the_portal_is_a_source_alerts_expects_to_hear_from(self):
        """A source in neither `check`'s list nor `coverage`'s backstop is how
        `all sources healthy` was printed for ten days over a dead Singapore."""
        from quantscraper import alerts

        self.assertIn(iesjobs.NAME, alerts._expected())

    def test_the_whole_board_walk_is_not_treated_as_layer_three(self):
        """`build_data.withdrawn` needs one `last_seen` per board per poll, and
        this walk writes one per *page*. Inside `LAYER_THREE` the freshest page
        would retire every earlier one."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
        try:
            import build_data
        finally:
            sys.path.pop(0)
        self.assertNotIn(iesjobs.NAME, build_data.LAYER_THREE)


class CardFetcherTest(unittest.TestCase):
    """The employer and the description live on the card, and the card link is
    minted per render -- so a stale one answers 200 with no card in it."""

    CARD = (
        '<span id="ordNo" data-ordno="22-26-0017657" class="item-content">'
        '22-26-0017657 CK </span>'
        '<span id="jobTitle" class="item-content">Loan Clerk</span>'
        '<span id="empName" class="item-content">TIPTOP CREDIT LIMITED</span>'
        '<span id="indsDesc" class="item-content">Finance</span>'
        '<span id="jobRemark" class="item-content">Handle customers&#39; loans.</span>'
        '<span id="eduRemark" class="item-content">Secondary 5; 2 years.</span>'
        '<span id="empTerm" class="item-content">$16,000 per month, 5 days.</span>'
    )

    def _row(self, **overrides):
        row = {
            "url": "https://www2.jobs.gov.hk/0/en/jobseeker/jobCard/?order=T0tFTg%3D%3D",
            "job_id": "22-26-0017657",
            "ats": "iesjobs",
            "token": "hongkong",
            "location": "Hong Kong, Mong Kok",
        }
        row.update(overrides)
        return row

    # The one-result search page the portal answers a job-order-number POST
    # with. **The card link is a `data-jobcard` attribute, not an `href`** --
    # the search renders the quickview layout, whose only `<a>` is the clip
    # button, and scanning for the href finds nothing while the search itself
    # plainly succeeded.
    SEARCH = (
        '<div class="row item" data-jobcard="/0/en/jobseeker/jobCard/'
        '?order=T0tFTg%3D%3D&amp;from=quickview">'
        '<a class="clipItBtn" href="#" data-ordno="22-26-0017657"></a></div>'
    )

    def _serve(self, page: str, search: str | None = None):
        """Both halves of the fetch, and **both must be mocked**.

        `iesjobs_body` mints a token with a POST before it reads the card, so
        stubbing only `get_text` leaves the search hitting the live portal --
        which is how the suite went from 25 seconds to a minute of real,
        throttled network calls before anybody noticed.
        """
        post = mock.patch.object(
            bodies.http, "post_form",
            return_value=(self.SEARCH if search is None else search).encode(),
        )
        get = mock.patch.object(bodies.http, "get_text", return_value=page)
        post.start()
        get.start()
        self.addCleanup(post.stop)
        self.addCleanup(get.stop)

    def test_the_card_yields_the_employer_and_the_prose(self):
        self._serve(self.CARD)
        got = bodies.iesjobs_body(self._row())
        self.assertEqual(got.employer, "TIPTOP CREDIT LIMITED")
        self.assertIn("Handle customers' loans.", got.description)
        self.assertIn("Secondary 5", got.description)
        # A place the list already carried; the card is not a second opinion.
        self.assertIsNone(got.location)

    def test_the_contract_and_the_application_note_are_not_the_job(self):
        """`empTerm` is hours and leave days, which is the boilerplate every
        body-matched rule in this project has been caught by."""
        self._serve(self.CARD)
        self.assertNotIn("5 days", bodies.iesjobs_body(self._row()).description)

    def test_entities_are_decoded(self):
        """`Business &amp; Risk` folded to the token `amp` once already."""
        self._serve(self.CARD)
        self.assertNotIn("&#39;", bodies.iesjobs_body(self._row()).description)

    def test_the_marker_tolerates_either_attribute_order(self):
        """This one fails **closed**: an attribute swap would return nothing
        for every posting rather than raising, and the only thing that would
        say so is a `0%` row in `bodies.coverage`."""
        swapped = self.CARD.replace(
            'id="ordNo" data-ordno="22-26-0017657"',
            'data-ordno="22-26-0017657" id="ordNo"',
        )
        self.assertNotEqual(swapped, self.CARD, "the fixture did not swap")
        self._serve(swapped)
        self.assertEqual(
            bodies.iesjobs_body(self._row()).employer, "TIPTOP CREDIT LIMITED"
        )

    def test_a_page_with_no_card_yields_nothing(self):
        """A stale token answers HTTP 200 with the vacancy-search page, so the
        status code proves nothing and the card's own marker is the test."""
        self._serve("<html><body>Vacancy Search</body></html>")
        self.assertEqual(bodies.iesjobs_body(self._row()), bodies.Fetched(None, None))

    def test_a_card_for_a_different_posting_yields_nothing(self):
        """Writing one firm's description onto another's row is the
        `palmersquare.com` failure, and it costs one comparison to refuse."""
        self._serve(self.CARD)
        got = bodies.iesjobs_body(self._row(job_id="99-99-9999999"))
        self.assertEqual(got, bodies.Fetched(None, None))

    def test_a_blank_employer_field_is_nobody_rather_than_a_dash(self):
        self._serve(self.CARD.replace("TIPTOP CREDIT LIMITED", "-"))
        self.assertIsNone(bodies.iesjobs_body(self._row()).employer)

    def test_a_row_with_no_job_id_is_not_fetched(self):
        """`job_id` is what the fetch is keyed on now -- the stored `url` is a
        perishable token and is no longer used at all."""
        self.assertEqual(
            bodies.iesjobs_body(self._row(job_id="")), bodies.Fetched(None, None)
        )

    def test_the_stored_url_is_not_used(self):
        """**The bug this fetcher was rewritten for.** The portal mints
        `?order=<base64>` per render and it expires with time -- verified by
        isolating the causes: a seconds-old token works in a brand-new process
        with a fresh cookie jar, so it is not session-bound, while tokens a
        couple of hours old return the vacancy-search page with HTTP 200 and no
        card. The first version stored the token and used it; it filled 968
        rows and then silently filled nothing.
        """
        self._serve(self.CARD)
        got = bodies.iesjobs_body(self._row(url="https://example.invalid/dead"))
        self.assertEqual(got.employer, "TIPTOP CREDIT LIMITED")

    def test_a_search_that_matches_nothing_yields_nothing(self):
        """The portal says so in words -- *No jobs matching your search
        criteria* -- for a posting that has come off the board since the sweep.
        That is a fact about the board, not a failure."""
        self._serve(self.CARD, search="<div>No jobs matching your search criteria.</div>")
        self.assertEqual(bodies.iesjobs_body(self._row()), bodies.Fetched(None, None))

    def test_a_search_that_matches_a_different_posting_yields_nothing(self):
        self._serve(self.CARD, search=self.SEARCH.replace("22-26-0017657", "99-99-9999999"))
        self.assertEqual(bodies.iesjobs_body(self._row()), bodies.Fetched(None, None))

    def test_the_portal_has_a_fetcher_at_all(self):
        """A reader whose list carries no prose leaves every posting at
        `relevance: unknown` -- 991 board cards for SuccessFactors before it
        had one. The number to check for a new reader is not "does it list"
        but "does the list carry prose"."""
        self.assertIn(iesjobs.NAME, bodies.FETCHERS)

    def test_the_portal_does_not_claim_to_answer_where(self):
        """`PLACES` is the honest bound on queue two: this card carries a
        district the list already published, so queueing a row here to fix a
        location would fetch a page that cannot answer the question."""
        self.assertNotIn(iesjobs.NAME, bodies.PLACES)


class EmployerWriteTest(unittest.TestCase):
    """The third column `bodies` may fill, and it must not blank anything."""

    def _connection(self):
        connection = _memory(self)
        # `_write` also retires the current tagger's verdicts, so it needs the
        # tag table as well as `jobs`.
        connection.executescript(tagging.SCHEMA)
        connection.execute(
            "INSERT INTO jobs (ats, token, job_id, title, location, description,"
            " employer, first_seen, last_seen) VALUES"
            " ('iesjobs', 'hongkong', '1', 'Analyst', 'Hong Kong, Mong Kok',"
            "  'held', 'HELD LTD', '2026-01-01', '2026-01-01')")
        connection.commit()
        return connection

    def test_an_employer_alone_blanks_neither_body_nor_place(self):
        connection = self._connection()
        bodies._write(connection, [(None, None, "NEW LTD", "iesjobs", "hongkong", "1")])
        row = connection.execute(
            "SELECT description, location, employer FROM jobs").fetchone()
        self.assertEqual(row["description"], "held")
        self.assertEqual(row["location"], "Hong Kong, Mong Kok")
        self.assertEqual(row["employer"], "NEW LTD")

    def test_a_body_alone_does_not_blank_the_employer(self):
        connection = self._connection()
        bodies._write(connection, [("new text", None, None, "iesjobs", "hongkong", "1")])
        row = connection.execute("SELECT description, employer FROM jobs").fetchone()
        self.assertEqual(row["description"], "new text")
        self.assertEqual(row["employer"], "HELD LTD")


if __name__ == "__main__":
    unittest.main()
