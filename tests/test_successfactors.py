"""Regression tests for SuccessFactors RMK's two surfaces.

The classic career site renders its list server-side; the "unify" one renders
it from a JSON API, so every selector the classic reader uses matches nothing
and the board reads as **empty with HTTP 200** -- the failure this project is
least able to see. 16 domains sat tier A with a NULL token on that surface and
four of them serve 510 postings between them.

Three things here are quiet when wrong and each has a test below:

  * the locale, which is not optional and not guessable -- `en_US` against
    Orkla returns `totalJobs: 0`, a well-formed empty answer rather than an
    error, where its own `en_GB` returns 9;
  * the posting URL, which is `/job/{display title}/{id}-{locale}` and not the
    classic `/job/{slug}/{id}/` -- the obvious guess redirects to an error page,
    and a card nobody can open is the SmartRecruiters defect this project has
    already paid for, all 1,507 rows of it;
  * the walk, because one pass cannot read this board: the API hands over
    exactly as many rows as it advertises and shuffles which page each lands
    on, so a single pass serves some twice and others never.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from quantscraper import extract


LOCALE_PAGE = (
    "<html><head><script>var resultStyles = {"
    " apiURL: 'https://api012.successfactors.eu',"
    " currentLocale: 'en_GB', defaultLocale: 'en_GB' };"
    "</script></head><body>"
    "<script src='/platform/js/j2w/min/j2w.SearchManager.min.js'></script>"
    "<div id='job-results-list'></div></body></html>"
)

CLASSIC_PAGE = (
    "<html><body><span>Results 1 - 1 of 1</span>"
    "<table><tr class='data-row'>"
    "<a class='jobTitle-link' href='/job/Quant-Analyst/4242/'>Quant Analyst</a>"
    "<span class='jobLocation'>Stockholm</span>"
    "<span class='jobDepartment'>Research</span>"
    "</tr></table></body></html>"
)


def _row(job_id, title="Quant Researcher", place="Hong Kong ", dept="Research",
         start="9/24/26"):
    return {"response": {
        "id": job_id,
        "unifiedStandardTitle": title,
        "unifiedUrlTitle": title.replace(" ", "-"),
        "jobLocationShort": [place],
        "department_obj": [dept],
        "unifiedStandardStart": start,
    }}


def _payload(total, *ids, **kwargs):
    return json.dumps({
        "totalJobs": total,
        "jobSearchResult": [_row(i, **kwargs) for i in ids],
    }).encode()


def _server(total, passes, **kwargs):
    """A board that answers `pageNumber`, pass after pass.

    `passes` is one plan per repeat of the walk, each a list of pages, each
    page a list of requisition ids; a page beyond a plan answers empty, which
    is how this board says it is done. The last plan repeats, so a test never
    has to count how many requests the reader makes -- which is the thing these
    tests exist to let change.
    """
    seen = {"pass": -1}

    def respond(url, body, **_):
        page = json.loads(body)["pageNumber"]
        if page == 0:
            seen["pass"] += 1
        plan = passes[min(seen["pass"], len(passes) - 1)]
        return _payload(total, *(plan[page] if page < len(plan) else ()), **kwargs)

    return respond


class SurfaceChoiceTest(unittest.TestCase):
    def test_a_rendered_list_is_read_without_touching_the_api(self):
        """The boards that already work must cost exactly what they did."""
        with mock.patch.object(extract.http, "get_text", return_value=CLASSIC_PAGE), \
                mock.patch.object(extract.http, "post_json") as post:
            jobs = extract.successfactors("jobs.volvogroup.com")

        post.assert_not_called()
        self.assertEqual([job.job_id for job in jobs], ["4242"])
        self.assertEqual(jobs[0].location, "Stockholm")

    def test_an_empty_rendered_list_falls_through_to_the_api(self):
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE), \
                mock.patch.object(
                    extract.http, "post_json",
                    side_effect=_server(1, [[["18532"]]])):
            jobs = extract.successfactors("careers.vistra.com")

        self.assertEqual([job.job_id for job in jobs], ["18532"])
        self.assertEqual(jobs[0].title, "Quant Researcher")

    def test_a_page_stating_no_locale_raises_rather_than_guessing(self):
        """`en_US` against a site that answers in another locale returns
        `totalJobs: 0` -- an empty board, not an error. Inventing the locale
        would turn that into a silently empty feed."""
        # Carries the unify marker, so the reader does engage -- what is
        # missing is the locale, not the surface.
        no_locale = LOCALE_PAGE.replace("defaultLocale: 'en_GB'", "")
        with mock.patch.object(extract.http, "get_text", return_value=no_locale), \
                mock.patch.object(extract.http, "post_json") as post:
            with self.assertRaises(ValueError) as caught:
                extract.successfactors("careers.orkla.com")

        post.assert_not_called()
        self.assertIn("states no locale", str(caught.exception))

    def test_the_locale_is_sent_as_the_page_states_it(self):
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE), \
                mock.patch.object(
                    extract.http, "post_json",
                    side_effect=_server(1, [[["1"]]])) as post:
            extract.successfactors("careers.orkla.com")

        sent = json.loads(post.call_args_list[0].args[1])
        self.assertEqual(sent["locale"], "en_GB")
        self.assertEqual(sent["pageNumber"], 0)
        self.assertEqual(sent["sortBy"], "")


class PostingUrlTest(unittest.TestCase):
    def test_the_url_is_the_shape_that_actually_resolves(self):
        """`/job/{display title}/{id}-{locale}`, taken from the widget's own
        href builder and then opened. `/job/{slug}/{id}/` -- the classic shape
        and the obvious guess -- redirects to `/errorpage/`."""
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE), \
                mock.patch.object(
                    extract.http, "post_json",
                    side_effect=_server(1, [[["18532"]]],
                                        title="Client Acceptance Manager")):
            jobs = extract.successfactors("careers.vistra.com")

        self.assertEqual(
            jobs[0].url,
            "https://careers.vistra.com/job/Client%20Acceptance%20Manager/18532-en_GB",
        )

    def test_a_posting_with_no_title_still_gets_an_openable_url(self):
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE), \
                mock.patch.object(
                    extract.http, "post_json",
                    side_effect=_server(1, [[["7"]]], title="")):
            jobs = extract.successfactors("careers.vistra.com")

        self.assertEqual(
            jobs[0].url, "https://careers.vistra.com/job/untitled/7-en_GB"
        )


class ShuffledPagesTest(unittest.TestCase):
    """One pass cannot read this board, and the walk is repeated until it can.

    Measured: Royal London advertises 33, serves exactly 33 rows over four
    pages, and yields **26 distinct** -- then 29 on the first pass, all 33 on
    the second, nothing new on the third.
    """

    def test_the_walk_repeats_until_it_stops_finding_requisitions(self):
        # The shuffle: the first pass serves 1 and 2 twice over and never 3 or
        # 4; the second serves the other half. Exactly Royal London's shape.
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE),                 mock.patch.object(
                    extract.http, "post_json",
                    side_effect=_server(4, [[["1", "2"], ["1", "2"]], [["3", "4"]]])):
            jobs = extract.successfactors("jobs.royallondon.com")

        self.assertEqual(sorted(job.job_id for job in jobs), ["1", "2", "3", "4"])

    def test_an_identical_page_twice_over_ends_the_pass(self):
        """A server ignoring `pageNumber` serves the same page forever, which
        no empty-page test catches. Narrowed to that signature, because a
        *reshuffle* of a page is this board working normally."""
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE), \
                mock.patch.object(
                    extract.http, "post_json",
                    return_value=_payload(2, "1", "2")) as post:
            jobs = extract.successfactors("stuck.example.com")

        self.assertEqual(sorted(job.job_id for job in jobs), ["1", "2"])
        # Two requests end the first pass, and the pass adds nothing new the
        # second time, so the walk stops rather than spending its whole cap.
        self.assertLessEqual(post.call_count, 4)

    def test_overlap_is_not_reported_as_truncation(self):
        """The board handed over everything it claimed; some arrived twice."""
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE),                 mock.patch.object(
                    extract.http, "post_json",
                    side_effect=_server(4, [[["1", "2"], ["2", "1"]]])):
            jobs = extract.successfactors("jobs.royallondon.com")

        self.assertEqual(len(jobs), 2, "2 distinct of 4 advertised, 4 rows served")

    def test_a_genuinely_truncated_walk_still_raises(self):
        """Served short of advertised is truncation and must stay loud."""
        with mock.patch.object(extract.http, "get_text", return_value=LOCALE_PAGE), \
                mock.patch.object(
                    extract.http, "post_json",
                    side_effect=_server(900, [[["1", "2"]]])):
            with self.assertRaises(ValueError) as caught:
                extract.successfactors("truncated.example.com")

        self.assertIn("advertises 900", str(caught.exception))
        self.assertIn("rows served", str(caught.exception))


class FieldShapeTest(unittest.TestCase):
    def test_a_field_published_as_a_list_becomes_one_string(self):
        self.assertEqual(extract._sf_unify_text(["Hong Kong "]), "Hong Kong")
        self.assertEqual(
            extract._sf_unify_text(["France-Lyon ", "Belgium"]),
            "France-Lyon, Belgium",
        )
        self.assertIsNone(extract._sf_unify_text([]))
        self.assertIsNone(extract._sf_unify_text(None))
        self.assertEqual(extract._sf_unify_text("Stockholm "), "Stockholm")

    def test_a_two_digit_american_date_becomes_iso(self):
        """`9/24/26` is a shape no other reader here emits and
        `web/build_data.posted` cannot parse, so it is normalised at source."""
        self.assertEqual(extract._sf_unify_date("9/24/26"), "2026-09-24")
        self.assertEqual(extract._sf_unify_date("12/1/2026"), "2026-12-01")

    def test_anything_else_is_no_date_rather_than_a_wrong_one(self):
        for value in ("", "yesterday", "2026-09-24", "13/40/26", None, 20260924):
            with self.subTest(value=value):
                self.assertIsNone(extract._sf_unify_date(value))


class VendorFingerprintTest(unittest.TestCase):
    def test_the_two_surfaces_are_told_apart_by_the_marker(self):
        """`ats._VENDOR_ASSETS` carries one entry per surface, on the same CDN,
        separated only by which script the page loads."""
        from quantscraper import ats

        markers = [
            marker for name, _, _, marker in ats._VENDOR_ASSETS
            if name == "successfactors"
        ]
        self.assertIn("jobTitle-link", markers)
        self.assertIn(extract.SF_UNIFY_MARKER, markers)
