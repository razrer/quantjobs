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
