"""Regression tests for the iCIMS and Pinpoint extractors.

Both were tier A with a token and no reader: `ats.py` recognised the host,
`extract.py` had no function for it, so the rows read as resolved and polled
silence. iCIMS alone was 38 boards, the largest single block of that kind.

iCIMS is the one that needs tests rather than trust. It has no feed of any
kind -- the vendor's `format=rss` now 302s to a staff login page -- so it is
parsed out of the portal's HTML, and every HTML parser in this project has
eventually met markup that broke it.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from quantscraper import ats, extract


def _page(*jobs: tuple[str, str], host: str = "careers-acme.icims.com") -> str:
    """A portal page listing `jobs` as (id, slug)."""
    return "".join(
        f'<div><a href="https://{host}/jobs/{job_id}/{slug}/job?in_iframe=1">x</a></div>'
        for job_id, slug in jobs
    )


class IcimsPagingTest(unittest.TestCase):
    def test_it_pages_until_a_page_adds_nothing(self):
        pages = [
            _page(("1", "quant-analyst"), ("2", "risk-analyst")),
            _page(("3", "trader")),
            _page(),
        ]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.icims("acme")

        self.assertEqual([j.job_id for j in jobs], ["1", "2", "3"])

    def test_a_portal_that_ignores_the_page_parameter_terminates(self):
        """Serving page one forever is what an empty-page test never catches.

        Workday needed the same rule for a tenant that ignores `offset`; here
        it is the only stop condition that works, because the portal answers
        HTTP 200 with a full page every time.
        """
        same = _page(("1", "quant-analyst"))
        with mock.patch.object(extract.http, "get_text", return_value=same) as fetch:
            jobs = extract.icims("acme")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)  # first page, then one that adds nothing

    def test_a_posting_listed_twice_on_one_page_is_kept_once(self):
        """The portal repeats a link in its own mobile markup."""
        with mock.patch.object(
            extract.http, "get_text",
            side_effect=[_page(("1", "quant-analyst"), ("1", "quant-analyst")), _page()],
        ):
            self.assertEqual(len(extract.icims("acme")), 1)

    def test_a_dead_board_raises_on_the_first_page(self):
        """A 404 up front is a broken board and must be loud. A 404 later is a
        paging edge, and losing the postings already read for it is not."""
        error = extract.urllib.error.HTTPError("u", 404, "Not Found", {}, None)

        with mock.patch.object(extract.http, "get_text", side_effect=error):
            with self.assertRaises(extract.urllib.error.HTTPError):
                extract.icims("acme")

        with mock.patch.object(
            extract.http, "get_text",
            side_effect=[_page(("1", "quant-analyst")), error],
        ):
            self.assertEqual(len(extract.icims("acme")), 1)


class IcimsMigrationTest(unittest.TestCase):
    """A migrated portal answers HTTP 200 with a script and no postings.

    Principle 2 exactly: a scraper that breaks and returns zero rows with HTTP
    200 is more dangerous than one that crashes, because nothing announces it.
    Twelve of 36 boards were in that state -- Principal, AXA and SiriusXM among
    them -- and every one was reported as "an empty board".
    """

    STUB = (
        "<script type=\"text/javascript\">window.top.location.href = "
        "'https:\/\/careers.principal.com\/us\/jobs';</script>"
    )

    def test_a_stub_pointing_off_icims_is_loud_and_names_the_target(self):
        with mock.patch.object(extract.http, "get_text", return_value=self.STUB):
            with self.assertRaises(ValueError) as caught:
                extract.icims("principal")
        self.assertIn("https://careers.principal.com/us/jobs", str(caught.exception))

    def test_a_stub_pointing_at_another_portal_is_followed(self):
        """The prefix is not always `careers-`.

        `allcareers-frankrimerman` and `uscareers-siriusxmradio` are both real,
        so a target still on `icims.com` is the same board under a different
        prefix rather than a migration.
        """
        stub = (
            "<script>window.top.location.href = "
            "'https:\/\/allcareers-acme.icims.com\/jobs\/search';</script>"
        )
        pages = [stub, _page(("7", "quant-analyst"), host="allcareers-acme.icims.com"), _page()]
        with mock.patch.object(extract.http, "get_text", side_effect=pages) as fetch:
            jobs = extract.icims("acme")

        self.assertEqual([j.job_id for j in jobs], ["7"])
        self.assertTrue(fetch.call_args_list[1].args[0].startswith(
            "https://allcareers-acme.icims.com/"
        ))
        self.assertEqual(
            jobs[0].url,
            "https://allcareers-acme.icims.com/jobs/7/quant-analyst/job",
        )

    def test_a_stub_on_a_page_that_also_lists_jobs_is_not_a_migration(self):
        """The redirect script and postings together means the portal works."""
        body = self.STUB + _page(("1", "trader"))
        with mock.patch.object(extract.http, "get_text", side_effect=[body, _page()]):
            self.assertEqual([j.job_id for j in extract.icims("acme")], ["1"])


class BambooHrRetirementTest(unittest.TestCase):
    """A retired subdomain 302s to the vendor's marketing site.

    The JSON endpoint then answers HTTP 200 with a page of HTML, and the reader
    failed with `JSONDecodeError: Expecting value: line 1 column 1` -- four
    boards saying "this customer is gone" in the least readable way available.
    Same signal as iCIMS' redirect stub, caught the same way.
    """

    def test_a_redirect_off_the_board_host_is_loud_and_names_the_target(self):
        with mock.patch.object(
            extract.http,
            "get_with_url",
            return_value=(b"<html>marketing</html>", "https://www.bamboohr.com/"),
        ):
            with self.assertRaises(ValueError) as caught:
                extract.bamboohr("alphaconnect")
        self.assertIn("https://www.bamboohr.com/", str(caught.exception))

    def test_a_live_board_still_reads(self):
        payload = json.dumps(
            {"result": [{"id": 7, "jobOpeningName": "Quant", "atsLocation": "Toronto"}]}
        ).encode()
        with mock.patch.object(
            extract.http,
            "get_with_url",
            return_value=(payload, "https://sprott.bamboohr.com/careers/list"),
        ):
            jobs = extract.bamboohr("sprott")
        self.assertEqual(jobs[0].url, "https://sprott.bamboohr.com/careers/7")
        self.assertEqual(jobs[0].location, "Toronto")

    def test_an_empty_board_is_an_answer_not_a_failure(self):
        with mock.patch.object(
            extract.http,
            "get_with_url",
            return_value=(b'{"result": []}', "https://carval.bamboohr.com/careers/list"),
        ):
            self.assertEqual(extract.bamboohr("carval"), [])


class SuccessFactorsTest(unittest.TestCase):
    """The vendor recorded as closed, on evidence about a different surface.

    What had been tested is the `?company=pfapensionP` form, which really does
    answer a shell with no job id. The firms here run RMK on their own
    hostname and it renders its list server-side -- Nomura 514 postings, Fitch
    266, Janus Henderson 81 -- and 61 rows sat tier A with a NULL token behind
    that note.
    """

    TABLE = (
        '<tr class="data-row">'
        '<td><span class="jobTitle"><a href="/job/Sydney-Quant-NSW/1414440600/"'
        ' class="jobTitle-link">Quantitative Analyst</a></span>'
        '<span class="jobLocation">Sydney, NSW, AU</span>'
        '<span class="jobDepartment">Research</span></td></tr>'
    )
    TILE = (
        '<li class="job-tile job-id-1431979833" data-url="/x">'
        '<div class="tiletitle"><a class="jobTitle-link"'
        ' href="/Clarksons/job/Hong-Kong-Broker/1431979833/">Shipbroker</a></div>'
        '<div id="job-1431979833-desktop-section-city-value">Hong Kong </div></li>'
    )

    def _page(self, body, total=None, tile=False):
        head = ""
        if total is not None:
            head = (
                f'<span>Showing 1 to 25 of {total} Jobs</span>'
                if tile
                else f"<span>Results 1 &#8211; 25 of <b>{total}</b></span>"
            )
        return head + body

    def test_the_table_layout_is_read_with_its_place_and_department(self):
        pages = [self._page(self.TABLE, 1), self._page("", 1)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.successfactors("jobs.janushenderson.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_id, "1414440600")
        self.assertEqual(jobs[0].title, "Quantitative Analyst")
        self.assertEqual(jobs[0].location, "Sydney, NSW, AU")
        self.assertEqual(jobs[0].department, "Research")

    def test_the_tile_layout_is_read_too(self):
        """RMK ships two list layouts and a firm may run either.

        Reading only the table found 81 postings at Janus Henderson and none
        at Carnegie -- a board answering 200 and coming back empty, which is
        what a layout gap looks like from outside.
        """
        pages = [self._page(self.TILE, 1, tile=True), self._page("", 1, tile=True)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.successfactors("careers.clarksons.com")
        self.assertEqual(jobs[0].title, "Shipbroker")
        self.assertEqual(jobs[0].location, "Hong Kong")

    def test_a_path_prefix_in_front_of_job_is_kept(self):
        """Clarksons serves its board under `/Clarksons`, and reading only the
        bare `/job/` form found 0 of the 33 postings the page advertises."""
        pages = [self._page(self.TILE, 1, tile=True), self._page("", 1, tile=True)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.successfactors("careers.clarksons.com")
        self.assertEqual(
            jobs[0].url,
            "https://careers.clarksons.com/Clarksons/job/Hong-Kong-Broker/1431979833/",
        )

    def test_a_layout_it_cannot_read_is_loud_rather_than_empty(self):
        """The board states its own size, so a parser gap cannot pass as
        "this firm is not hiring" -- which is how the tile layout was found."""
        with mock.patch.object(
            extract.http, "get_text", return_value=self._page("<tr><td>?</td></tr>", 33)
        ):
            with self.assertRaises(ValueError) as caught:
                extract.successfactors("careers.clarksons.com")
        self.assertIn("advertises 33", str(caught.exception))

    def test_the_stride_follows_the_server_not_a_constant(self):
        """RMK's page size is per tenant -- 25 at Janus Henderson, 15 at Scania.

        Stepping `startrow` by a constant skipped ten postings in every
        twenty-five of Scania's 758, which is the Eightfold trap in a third
        format. The advertised total caught it and nothing else would have.
        """
        page = self._page(self.TABLE * 3, 6)  # a server that serves three
        with mock.patch.object(
            extract.http, "get_text", side_effect=[page, self._page(self.TABLE, 6)]
        ) as fetch:
            with self.assertRaises(ValueError):
                extract.successfactors("jobs.scania.com")
        self.assertIn("startrow=0", fetch.call_args_list[0].args[0])
        self.assertIn("startrow=3", fetch.call_args_list[1].args[0])

    def test_a_site_that_ignores_startrow_terminates(self):
        """Serving page one forever is what no empty-page test catches."""
        with mock.patch.object(
            extract.http, "get_text", return_value=self._page(self.TABLE, 1)
        ) as fetch:
            jobs = extract.successfactors("jobs.janushenderson.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("startrow=0", fetch.call_args_list[0].args[0])

    def test_an_empty_page_advances_by_the_guess_rather_than_stalling(self):
        """A page with no rows at all must not leave `startrow` where it was."""
        with mock.patch.object(
            extract.http, "get_text", return_value=self._page("", 0)
        ) as fetch:
            self.assertEqual(extract.successfactors("x"), [])
        self.assertEqual(fetch.call_count, 1)


class IcimsCareerSiteTest(unittest.TestCase):
    """iCIMS' newer product, served from the firm's own hostname.

    A different surface rather than a different host: a JSON API where the
    classic portal is list HTML with no location and no description at all.
    SIG's 250 postings arrive from this one with both.
    """

    @staticmethod
    def _payload(total, *rows):
        return json.dumps(
            {
                "totalCount": total,
                "count": 72,  # a different number, and deliberately not the total
                "jobs": [{"data": row} for row in rows],
            }
        )

    @staticmethod
    def _row(req_id, title="Quantitative Researcher", **extra):
        row = {
            "req_id": req_id,
            "slug": req_id,
            "title": title,
            "full_location": "Bala Cynwyd, Pennsylvania",
            "posted_date": "2026-08-25T20:58:00+0000",
            "description": "Research systematic strategies.",
            "categories": [{"name": "Research"}],
        }
        row.update(extra)
        return row

    def test_it_pages_and_maps_the_fields_the_portal_cannot(self):
        pages = [self._payload(2, self._row("1"), self._row("2")), self._payload(2)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages) as fetch:
            jobs = extract.icims_cs("careers.sig.com")

        self.assertEqual([j.job_id for j in jobs], ["1", "2"])
        self.assertEqual(jobs[0].location, "Bala Cynwyd, Pennsylvania")
        self.assertEqual(jobs[0].department, "Research")
        self.assertEqual(jobs[0].url, "https://careers.sig.com/careers-home/jobs/1")
        self.assertIn("page=1", fetch.call_args_list[0].args[0])

    def test_the_advertised_total_is_the_check_not_count(self):
        """`count` is 72 on a board of 117, so believing it would truncate."""
        with mock.patch.object(
            extract.http, "get_text", side_effect=[self._payload(500, self._row("1")), self._payload(500)]
        ):
            with self.assertRaises(ValueError) as caught:
                extract.icims_cs("careers.sig.com")
        self.assertIn("advertises 500", str(caught.exception))

    def test_a_site_that_ignores_page_terminates(self):
        same = self._payload(1, self._row("1"))
        with mock.patch.object(extract.http, "get_text", return_value=same) as fetch:
            jobs = extract.icims_cs("careers.sig.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)

    def test_a_posting_with_no_slug_falls_back_to_the_apply_url(self):
        """Never a link to the board's front door -- the Workday rule."""
        row = self._row("9", slug=None, apply_url="https://careers-sig.icims.com/jobs/9/login")
        with mock.patch.object(
            extract.http, "get_text", side_effect=[self._payload(1, row), self._payload(1)]
        ):
            jobs = extract.icims_cs("careers.sig.com")
        self.assertEqual(jobs[0].url, "https://careers-sig.icims.com/jobs/9/login")


class IcimsTitleTest(unittest.TestCase):
    def test_a_slug_becomes_a_readable_title(self):
        self.assertEqual(
            extract._icims_title("fixed-income-research-analyst"),
            "Fixed Income Research Analyst",
        )

    def test_url_encoding_in_a_slug_is_decoded(self):
        self.assertEqual(
            extract._icims_title("regional-director-%28northern-california%29"),
            "Regional Director (northern California)",
        )

    def test_the_url_points_at_the_posting_not_the_iframe(self):
        with mock.patch.object(
            extract.http, "get_text",
            side_effect=[_page(("7", "quant-researcher")), _page()],
        ):
            job = extract.icims("acme")[0]

        self.assertEqual(
            job.url, "https://careers-acme.icims.com/jobs/7/quant-researcher/job"
        )
        self.assertNotIn("in_iframe", job.url)


class IcimsCostTest(unittest.TestCase):
    def test_markup_without_a_closing_quote_does_not_stall(self):
        """The failure mode of every regex in this project is a stall, not a
        wrong answer. Both halves of the job pattern are length-bounded."""
        markup = '<a href="https://careers-acme.icims.com/jobs/1/' + "a" * 200_000

        start = time.monotonic()
        with mock.patch.object(extract.http, "get_text", return_value=markup):
            extract.icims("acme")
        self.assertLess(time.monotonic() - start, 1.0)


class PinpointTest(unittest.TestCase):
    def _payload(self, **overrides):
        posting = {
            "id": "544190",
            "title": "Senior Platform Engineer",
            "url": "https://systematica.pinpointhq.com/en/postings/abc",
            "location": {"name": "London", "city": "London"},
            "description": "<div>Build things.</div>",
            "deadline_at": None,
        }
        posting.update(overrides)
        return json.dumps({"data": [posting]}).encode()

    def test_it_reads_the_board(self):
        with mock.patch.object(extract.http, "get_text",
                               return_value=self._payload().decode()):
            job = extract.pinpoint("systematica")[0]

        self.assertEqual(job.job_id, "544190")
        self.assertEqual(job.location, "London")
        self.assertEqual(job.description, "Build things.")

    def test_location_falls_back_to_city_when_name_is_absent(self):
        with mock.patch.object(
            extract.http, "get_text",
            return_value=self._payload(location={"city": "Frankfurt"}).decode(),
        ):
            self.assertEqual(extract.pinpoint("x")[0].location, "Frankfurt")

    def test_a_published_deadline_is_carried_through(self):
        """Every board sampled leaves this null, and it is still mapped: it is
        a field the source publishes, which is the only kind of closing date
        this project will accept."""
        with mock.patch.object(
            extract.http, "get_text",
            return_value=self._payload(deadline_at="2026-09-30").decode(),
        ):
            self.assertEqual(extract.pinpoint("x")[0].deadline, "2026-09-30")

    def test_an_empty_board_is_not_an_error(self):
        with mock.patch.object(extract.http, "get_text", return_value='{"data": []}'):
            self.assertEqual(extract.pinpoint("x"), [])


class IcimsFingerprintTest(unittest.TestCase):
    def test_the_cookie_script_path_carries_the_token(self):
        """SIG's careers page names its board nowhere else.

        `careers.sig.com` fronts `careers-sig.icims.com`, and the only place
        `sig` appears in the markup is the vendor's cookie banner script. That
        one pattern is worth 237 postings.
        """
        markup = (
            '<script src="https://cookie-policy-scripts.icims.com/sig/'
            'careers.sig.com/script.js"></script>'
        )
        found = ats.fingerprint(markup)
        self.assertEqual(found[:2], ("icims", "sig"))

    def test_the_ordinary_host_form_still_wins(self):
        markup = (
            '<script src="https://cookie-policy-scripts.icims.com/acme/x.js">'
            '<a href="https://careers-realboard.icims.com/jobs/search">Jobs</a>'
        )
        self.assertEqual(ats.fingerprint(markup)[:2], ("icims", "realboard"))


def _jv_row(job_id: str, title: str, place: str, token: str = "acme") -> str:
    return (
        f'<tr><td class="jv-job-list-name">'
        f'<a href="/{token}/job/{job_id}">{title}</a></td>'
        f'<td class="jv-job-list-type">Full-Time</td>'
        f'<td class="jv-job-list-location">\n {place}\n </td></tr>'
    )


def _jv_page(*rows: str, shown: int = 0, total: int = 0) -> str:
    body = "<table><tbody>" + "".join(rows) + "</tbody></table>"
    if total:
        body += f'<div class="jv-pagination-text">1-{shown} of {total}</div>'
    return body


class JobviteTest(unittest.TestCase):
    """Jobvite pages at 50 and the trailing slash is load-bearing.

    The board first came back at exactly 50 postings, which is what a cap
    looks like from the outside -- and it was one. `/search?p=1` answers the
    first page while looking like it paged; `/search/?p=1` actually pages.
    """

    def test_it_pages_past_the_first_fifty(self):
        pages = [
            _jv_page(*[_jv_row(str(n), f"Job {n}", "London") for n in range(50)],
                     shown=50, total=73),
            _jv_page(*[_jv_row(str(n), f"Job {n}", "London") for n in range(50, 73)]),
            _jv_page(),
        ]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.jobvite("acme")
        self.assertEqual(len(jobs), 73)

    def test_the_paged_url_carries_the_trailing_slash(self):
        seen: list[str] = []

        def capture(url, **kwargs):
            seen.append(url)
            return _jv_page(_jv_row("1", "Quant", "London")) if len(seen) == 1 else _jv_page()

        with mock.patch.object(extract.http, "get_text", capture):
            extract.jobvite("acme")

        self.assertEqual(seen[0], "https://jobs.jobvite.com/acme/search/")
        self.assertEqual(seen[1], "https://jobs.jobvite.com/acme/search/?p=1")

    def test_a_page_adding_nothing_ends_the_walk(self):
        page = _jv_page(_jv_row("1", "Quant Researcher", "London"))
        with mock.patch.object(extract.http, "get_text", return_value=page) as fetch:
            jobs = extract.jobvite("acme")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)

    def test_a_board_handing_over_less_than_it_advertises_is_loud(self):
        """The total was parsed and then compared to nothing.

        Stage 16 records "the advertised total is checked on every board", and
        the parsed figure was assigned to a local that was never read again --
        so the guard that found the missing trailing slash in the first place
        was not running afterwards. `1-50 of 73` is the whole evidence a cap
        leaves behind.
        """
        pages = [_jv_page(_jv_row("1", "Quant", "London"), shown=1, total=73), _jv_page()]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            with self.assertRaises(ValueError) as caught:
                extract.jobvite("acme")
        self.assertIn("advertises 73", str(caught.exception))

    def test_a_board_stating_no_total_is_not_treated_as_empty(self):
        """Most pages carry no pagination line, and 0 must not mean a failure."""
        pages = [_jv_page(_jv_row("1", "Quant", "London")), _jv_page()]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            self.assertEqual(len(extract.jobvite("acme")), 1)

    def test_title_and_location_are_read_from_their_own_cells(self):
        page = _jv_page(_jv_row("oX1", "Equity Analyst, Public Real Estate", "Chicago, Illinois"))
        with mock.patch.object(extract.http, "get_text", side_effect=[page, _jv_page()]):
            job = extract.jobvite("acme")[0]
        self.assertEqual(job.title, "Equity Analyst, Public Real Estate")
        self.assertEqual(job.location, "Chicago, Illinois")
        self.assertEqual(job.url, "https://jobs.jobvite.com/acme/job/oX1")

    def test_a_mismatched_table_drops_locations_rather_than_pairing_them_wrongly(self):
        """A location paired with the wrong posting sends the geography gate a
        wrong answer, and that gate deletes rather than reorders."""
        page = (
            '<td class="jv-job-list-name"><a href="/acme/job/1">A</a></td>'
            '<td class="jv-job-list-name"><a href="/acme/job/2">B</a></td>'
            '<td class="jv-job-list-location"> London </td>'
        )
        with mock.patch.object(extract.http, "get_text", side_effect=[page, _jv_page()]):
            jobs = extract.jobvite("acme")
        self.assertEqual([j.location for j in jobs], [None, None])


class RegistrationTest(unittest.TestCase):
    def test_both_are_wired_into_the_extractor_table(self):
        """The bug this stage fixes is a board resolved to an ATS nothing
        reads, so the registration is the fix and belongs in a test."""
        self.assertIn("icims", extract.EXTRACTORS)
        self.assertIn("pinpoint", extract.EXTRACTORS)
        self.assertIn("jobvite", extract.EXTRACTORS)


if __name__ == "__main__":
    unittest.main()


class VarbiTest(unittest.TestCase):
    """Varbi's RSS is the only stable surface: `/what:list/` 404s."""

    FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Nya lediga jobb</title>
<item><title>Kundansvarig till Landshypotek</title>
<link>https://acme.varbi.com/en/what:job/jobID:958884/</link>
<description>Beskrivning av tjansten</description>
<pubDate>Mon, 17 Aug 2026 10:00:00 +0200</pubDate></item>
</channel></rss>"""

    def test_the_posting_id_comes_out_of_the_link(self):
        with mock.patch.object(extract.http, "get", return_value=self.FEED):
            job = extract.varbi("acme")[0]
        self.assertEqual(job.job_id, "958884")
        self.assertEqual(job.title, "Kundansvarig till Landshypotek")
        self.assertEqual(job.description, "Beskrivning av tjansten")

    def test_an_empty_channel_is_a_firm_with_no_openings(self):
        empty = b'<?xml version="1.0"?><rss version="2.0"><channel/></rss>'
        with mock.patch.object(extract.http, "get", return_value=empty):
            self.assertEqual(extract.varbi("acme"), [])

    def test_a_feed_with_no_channel_is_loud(self):
        with mock.patch.object(extract.http, "get", return_value=b"<rss/>"):
            with self.assertRaises(ValueError):
                extract.varbi("acme")


class HomerunTest(unittest.TestCase):
    """The board links out to the firm's own host, so the feed is the surface."""

    FEED = b"""<?xml version="1.0" encoding="UTF-8" ?>
<feed xmlns="http://www.w3.org/2005/Atom"><title type="text">Tiqets</title>
<entry><title type="text">Data Analyst</title>
<link rel="alternate" type="text/html" href="https://jobs.tiqets.work/data-analyst-4"></link>
<id>job_5V68pcL66o1yqHsDttfp</id>
<updated>2026-08-01T10:00:00Z</updated>
<summary type="html">Join us!</summary>
<content type="html">The full description.</content></entry></feed>"""

    def test_it_follows_the_firm_to_its_own_host(self):
        with mock.patch.object(extract.http, "get", return_value=self.FEED):
            job = extract.homerun("tiqets")[0]
        self.assertEqual(job.url, "https://jobs.tiqets.work/data-analyst-4")
        self.assertEqual(job.job_id, "job_5V68pcL66o1yqHsDttfp")

    def test_content_is_preferred_over_the_summary(self):
        with mock.patch.object(extract.http, "get", return_value=self.FEED):
            self.assertEqual(extract.homerun("t")[0].description, "The full description.")

    def test_an_empty_feed_is_not_an_error(self):
        empty = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
        with mock.patch.object(extract.http, "get", return_value=empty):
            self.assertEqual(extract.homerun("acme"), [])
