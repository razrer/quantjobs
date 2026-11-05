"""The readers added when the audit stopped counting portal adverts as boards.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from quantscraper import ats, bodies, extract, sites


def _radancy_page(total, cards):
    results = f'<section data-total-job-results="{total}" data-total-pages="1"><ul>'
    for job_id, title, place in cards:
        results += (
            f'<li><a href="/job/london/x/45831/{job_id}" data-job-id="{job_id}">'
            f'<h2>{title}</h2><span class="job-location">{place}</span></a></li>'
        )
    return json.dumps({"results": results + "</ul></section>", "hasJobs": bool(cards)})


class RadancyTest(unittest.TestCase):
    def _read(self, *pages):
        with mock.patch.object(extract.http, "get_text", side_effect=list(pages)):
            return extract.radancy("careers.example.com")

    def test_a_card_becomes_a_posting(self):
        job = self._read(_radancy_page(1, [("7", "Quant &amp; Analyst", "London")]))[0]
        self.assertEqual((job.ats, job.token, job.job_id), ("radancy", "careers.example.com", "7"))
        self.assertEqual((job.title, job.location), ("Quant & Analyst", "London"))
        self.assertEqual(job.url, "https://careers.example.com/job/london/x/45831/7")

    def test_the_walk_continues_until_the_board_is_read(self):
        jobs = self._read(
            _radancy_page(2, [("1", "A", "X")]), _radancy_page(2, [("2", "B", "Y")])
        )
        self.assertEqual([j.job_id for j in jobs], ["1", "2"])

    def test_a_site_ignoring_paging_is_caught_as_a_shortfall(self):
        page = _radancy_page(50, [("1", "A", "X")])
        with self.assertRaises(ValueError):
            self._read(page, page)

    def test_an_empty_board_is_an_answer(self):
        self.assertEqual(self._read(_radancy_page(0, [])), [])

    def test_a_changed_template_is_not_an_empty_board(self):
        with self.assertRaises(ValueError):
            self._read(json.dumps({"results": "<div>redesigned</div>"}))

    def test_the_body_fetcher_is_registered(self):
        self.assertIn("radancy", bodies.FETCHERS)


def _oleeo_page(*opps, boards=(1, 2)):
    nav = "".join(
        f'<a href="https://x.tal.net/vx/candidate/jobboard/vacancy/{n}/adv/">b</a>'
        for n in boards
    )
    tiles = "".join(
        f'<div class="candidate-opp-tile" data-oppid="{i}" data-lat="" data-title="{t}">'
        f'<a class="subject" href="https://x.tal.net/vx/candidate/so/pm/1/pl/2/opp/{i}-slug/en-GB">t</a></div>'
        for i, t in opps
    )
    return nav + tiles


class OleeoTest(unittest.TestCase):
    def _read(self, *pages):
        with mock.patch.object(extract.http, "get_text", side_effect=list(pages)) as get:
            return extract.oleeo("x.tal.net|4"), get

    def test_every_board_the_first_page_names_is_read(self):
        jobs, get = self._read(
            _oleeo_page(),  # board 1: an events board with nothing on it
            _oleeo_page((10, "Summer Analyst &amp; Quant")),  # board 2
            _oleeo_page(),  # board 2 page 2 adds nothing
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_id, "10")
        self.assertEqual(jobs[0].title, "Summer Analyst & Quant")
        self.assertIn("/opp/10-slug/", jobs[0].url)
        self.assertIn("brand-4", get.call_args_list[1].args[0])
        self.assertIn("/vacancy/2/", get.call_args_list[1].args[0])

    def test_paging_advances_by_start(self):
        _, get = self._read(
            _oleeo_page((1, "A"), boards=(1,)),
            _oleeo_page((2, "B"), boards=(1,)),
            _oleeo_page(boards=(1,)),
        )
        self.assertIn("?start=50", get.call_args_list[1].args[0])
        self.assertIn("?start=100", get.call_args_list[2].args[0])

    def test_a_moved_tenant_is_not_an_empty_board(self):
        with self.assertRaises(ValueError):
            self._read("<html>somewhere else</html>")


class FingerprintTest(unittest.TestCase):
    def test_oleeo_token_carries_host_and_brand(self):
        hit = ats.fingerprint(
            '<a href="https://jefferies.tal.net/vx/lang-en-GB/mobile-0/'
            'appcentre-ext/brand-4/xf-016c/candidate/jobboard/vacancy/1/adv/">x</a>'
        )
        self.assertEqual(hit[:2], ("oleeo", "jefferies.tal.net|4"))

    def test_both_vendors_have_extractors(self):
        for name in ("oleeo", "radancy"):
            self.assertIn(name, extract.EXTRACTORS)


def _patched(*pages):
    return mock.patch.object(extract.http, "get_text", side_effect=list(pages))


class ReflineTest(unittest.TestCase):
    PAGE = (
        '<table class="searchResult"><tbody><tr>'
        '<td class="position"><a href="https://apply.refline.ch/9/11/pub/3" '
        'target="_blank">Quant &amp; Analyst</a></td>'
        '<td class="operationArea">Risk</td><td class="workplace">Zürich</td>'
        "</tr></tbody></table>"
    )

    def test_a_row_becomes_a_posting(self):
        with _patched(self.PAGE):
            job = extract.refline("9")[0]
        self.assertEqual((job.job_id, job.title), ("11", "Quant & Analyst"))
        self.assertEqual((job.location, job.department), ("Zürich", "Risk"))
        self.assertEqual(job.url, "https://apply.refline.ch/9/11/pub/3")

    def test_an_empty_table_is_an_answer_and_no_table_is_not(self):
        with _patched('<table class="searchResult"></table>'):
            self.assertEqual(extract.refline("9"), [])
        with _patched("<div>moved</div>"), self.assertRaises(ValueError):
            extract.refline("9")


class PaylocityTest(unittest.TestCase):
    def _page(self, jobs):
        return f"<script>window.pageData = {json.dumps({'Jobs': jobs})};</script>"

    def test_the_teaser_is_not_stored_and_internal_jobs_are_skipped(self):
        page = self._page([
            {"JobId": 5, "JobTitle": "Trader", "LocationName": "Chicago",
             "PublishedDate": "2026-10-08T10:20:24-05:00", "Description": "XR is a pro",
             "IsInternal": False},
            {"JobId": 6, "JobTitle": "Internal", "IsInternal": True},
        ])
        with _patched(page):
            jobs = extract.paylocity("guid")
        self.assertEqual([j.job_id for j in jobs], ["5"])
        self.assertIsNone(jobs[0].description)
        self.assertTrue(jobs[0].url.endswith("/Recruiting/Jobs/Details/5"))

    def test_a_changed_page_raises(self):
        with _patched("<html></html>"), self.assertRaises(ValueError):
            extract.paylocity("guid")


class ApplicantProTest(unittest.TestCase):
    def test_the_site_number_comes_from_the_list_page(self):
        api = json.dumps({"success": True, "data": {"jobs": [
            {"id": 4, "title": "Quant", "jobLocation": "Chicago, IL",
             "startDateRef": "Sep 24, 2026", "orgTitle": "Trading",
             "jobUrl": "https://x.applicantpro.com/jobs/4"},
        ]}})
        with _patched('{"domain_id":"489"}', api) as get:
            jobs = extract.applicantpro("x")
        self.assertIn("/core/jobs/489?getParams=", get.call_args_list[1].args[0])
        self.assertEqual(jobs[0].posted_at, "2026-09-24")
        self.assertEqual(jobs[0].location, "Chicago, IL")

    def test_a_page_with_no_site_number_raises(self):
        with _patched("<html></html>"), self.assertRaises(ValueError):
            extract.applicantpro("x")


class ReachMeeTest(unittest.TestCase):
    SCRIPT = "var validator = 'abcdef0123456789'; var langDef = 'SE';"
    PAGE = (
        "<div id='mainjoblist'><table><tr><td><a href='https://w.reachmee.com/ext/I1/2/"
        "job?site=6&lang=SE&validator=abc&job_id=241' class='btn'>Testare</a></td>"
        "<td><span>2026-11-15</span></td></tr></table></div>"
    )

    DETAIL = (
        '<p class="text-color-muted extid">Stockholm</p>'
        '<div class="jobad-body"><p>The role</p></div></main>'
    )

    def test_the_validator_is_read_from_the_script(self):
        with _patched(self.SCRIPT, self.PAGE, self.DETAIL) as get:
            job = extract.reachmee("w.reachmee.com|I1|2|6")[0]
        self.assertIn("validator=abcdef0123456789", get.call_args_list[1].args[0])
        self.assertEqual((job.job_id, job.title), ("241", "Testare"))
        self.assertEqual(job.deadline, "2026-11-15")

    def test_each_posting_gets_its_place_and_description(self):
        with _patched(self.SCRIPT, self.PAGE, self.DETAIL):
            job = extract.reachmee("w.reachmee.com|I1|2|6")[0]
        self.assertEqual((job.location, job.description), ("Stockholm", "The role"))

    def test_an_external_id_is_not_taken_for_a_place(self):
        page = '<p class="extid">REF-2031</p><div class="jobad-body">x</div></main>'
        with _patched(self.SCRIPT, self.PAGE, page):
            self.assertIsNone(extract.reachmee("w.reachmee.com|I1|2|6")[0].location)

    def test_a_failed_posting_page_keeps_the_posting(self):
        def answer(url, **_):
            if "customerjs" in url:
                return self.SCRIPT
            if "/main?" in url:
                return self.PAGE
            raise TimeoutError
        with mock.patch.object(extract.http, "get_text", side_effect=answer):
            job = extract.reachmee("w.reachmee.com|I1|2|6")[0]
        self.assertEqual((job.title, job.location), ("Testare", None))

    def test_a_missing_validator_or_list_raises(self):
        with _patched("nothing"), self.assertRaises(ValueError):
            extract.reachmee("w.reachmee.com|I1|2|6")
        with _patched(self.SCRIPT, "<html></html>"), self.assertRaises(ValueError):
            extract.reachmee("w.reachmee.com|I1|2|6")


class HeartpaceTest(unittest.TestCase):
    def _page(self, jobs, count, next_page=None):
        data = {"props": {"pageProps": {"job_data": {
            "jobs": jobs, "jobs_count": count, "next_page": next_page}}}}
        return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'

    JOB = {"slug": "quant", "job_title": "Quant", "city_country": "Gothenburg",
           "description": "<p>The role</p>", "published_date": "Posted 1 day(s) ago"}

    def test_a_posting_keeps_its_description(self):
        with _patched(self._page([self.JOB], 1)):
            job = extract.heartpace("ap2")[0]
        self.assertEqual((job.job_id, job.description), ("quant", "The role"))
        self.assertIsNone(job.posted_at)
        self.assertEqual(job.url, "https://jobs.hiring.heartpace.com/ap2/quant/view-job")

    def test_a_short_walk_raises(self):
        with _patched(self._page([self.JOB], 40)), self.assertRaises(ValueError):
            extract.heartpace("ap2")

    def test_a_changed_page_raises(self):
        with _patched("<html></html>"), self.assertRaises(ValueError):
            extract.heartpace("ap2")


class SmallVendorFingerprintTest(unittest.TestCase):
    def test_each_vendor_yields_its_token(self):
        for markup, ats_name, token in (
            ("https://apply.refline.ch/792841/search.html", "refline", "792841"),
            ("https://recruiting.paylocity.com/recruiting/jobs/All/"
             "5c109104-7c4d-415c-9ee4-54e3af55f9e7/XR", "paylocity",
             "5c109104-7c4d-415c-9ee4-54e3af55f9e7"),
            ("https://group1.applicantpro.com/jobs/4221876", "applicantpro", "group1"),
            ("https://web103.reachmee.com/customerjs/I005-1018-6.js", "reachmee",
             "web103.reachmee.com|I005|1018|6"),
            ("https://jobs.hiring.heartpace.com/ap2/x/view-job", "heartpace", "ap2"),
            ("https://ap2.hiring.heartpace.com/careers", "heartpace", "ap2"),
        ):
            with self.subTest(ats=ats_name):
                self.assertEqual(ats.fingerprint(markup)[:2], (ats_name, token))
                self.assertIn(ats_name, extract.EXTRACTORS)


class JobylonGroupTest(unittest.TestCase):
    def test_a_group_token_reads_the_group_widget(self):
        page = "JBL.embed_v2['jobs'] = [ { id: '1', url: '/jobs/1-x/', title: 'Quant', company: 'AMF', } ]"
        with _patched(page) as get:
            extract.jobylon("g468")
        self.assertIn("/company-groups/468/embed", get.call_args.args[0])

    def test_a_company_token_still_reads_the_company_widget(self):
        page = "JBL.embed_v2['jobs'] = []"
        with _patched(page) as get:
            extract.jobylon("1843")
        self.assertIn("/companies/1843/embed", get.call_args.args[0])

    def test_groups_are_fingerprinted_from_both_forms(self):
        for markup in (
            "https://cdn.jobylon.com/jobs/company-groups/468/embed/v2/",
            "var jbl_group_id = 468;",
        ):
            self.assertEqual(ats.fingerprint(markup)[:2], ("jobylon", "g468"))
        self.assertEqual(
            ats.fingerprint("https://cdn.jobylon.com/jobs/companies/953/embed/v2/")[:2],
            ("jobylon", "953"),
        )


class DeelTest(unittest.TestCase):
    def _page(self, postings):
        stream = '{"x":1,"jobPostings":' + json.dumps(postings) + ',"y":2}'
        half = len(stream) // 2
        return "".join(
            f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>"
            for part in (stream[:half], stream[half:])
        )

    def test_a_posting_spread_across_chunks_is_read(self):
        page = self._page([{
            "id": "abc", "title": "Data Scientist ", "createdAt": "2026-07-17T13:51:21Z",
            "job": {"jobLocations": [
                {"location": {"name": "Stockholm", "country": {"name": "Sweden"}}}
            ]},
        }])
        with _patched(page):
            job = extract.deel("klarna")[0]
        self.assertEqual((job.job_id, job.title), ("abc", "Data Scientist"))
        self.assertEqual(job.location, "Stockholm, Sweden")
        self.assertEqual(job.url, "https://jobs.deel.com/klarna/job-details/abc/overview")

    def test_an_empty_board_is_an_answer_and_a_changed_page_is_not(self):
        with _patched(self._page([])):
            self.assertEqual(extract.deel("klarna"), [])
        with _patched("<html></html>"), self.assertRaises(ValueError):
            extract.deel("klarna")


def _attrax_tile(job_id, title="Analyst", place="Solna"):
    return (
        f'<div class="attrax-vacancy-tile" data-jobid="{job_id}">'
        f'<a class="attrax-vacancy-tile__title attrax-button" href="/global/job/x-jid-{job_id}">{title}</a>'
        '<div class="attrax-vacancy-tile__location-freetext attrax-vacancy-tile__item">'
        f'<p class="attrax-vacancy-tile__item-label">Location</p>'
        f'<p class="attrax-vacancy-tile__item-value"> {place} </p></div></div>'
    )


class AttraxTest(unittest.TestCase):
    def test_paging_stops_on_a_page_adding_nothing(self):
        with _patched(_attrax_tile(1), _attrax_tile(2), _attrax_tile(2)) as get:
            jobs = extract.attrax("careers.x.com/global/jobs")
        self.assertEqual([j.job_id for j in jobs], ["1", "2"])
        self.assertEqual(jobs[0].location, "Solna")
        self.assertEqual(jobs[0].url, "https://careers.x.com/global/job/x-jid-1")
        self.assertIn("?page=2", get.call_args_list[1].args[0])

    def test_a_changed_page_raises(self):
        with _patched("<html></html>"), self.assertRaises(ValueError):
            extract.attrax("careers.x.com/global/jobs")


def _gresearch_card(slug, title, place="London"):
    return (
        f'<a href="https://www.gresearch.com/vacancies/{slug}/" class="c-vacancy-result">'
        f'<span class="c-vacancy-result__title">{title}</span>'
        f'<span class="c-vacancy-result__location">{place}</span></a>'
    )


class GResearchTest(unittest.TestCase):
    def test_paging_stops_when_a_page_repeats_the_first(self):
        page = _gresearch_card("quant-researcher", "Quantitative Researcher")
        fetched = bodies.Fetched("the role", None)
        with mock.patch.object(sites.http, "get_text", side_effect=[page, page]):
            with mock.patch.object(bodies, "_ld_body", return_value=fetched):
                jobs = sites.gresearch()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_id, "quant-researcher")
        self.assertEqual(jobs[0].location, "London")
        self.assertEqual(jobs[0].description, "the role")

    def test_a_redesign_raises(self):
        with mock.patch.object(sites.http, "get_text", return_value="<div>new</div>"):
            with self.assertRaises(sites.SiteChanged):
                sites.gresearch()


if __name__ == "__main__":
    unittest.main()
