"""Regression tests for Stage 33 -- the firms no careers walk could reach.

Three separate things are pinned here, and they failed in three different ways:

  * **the Greenhouse embed pattern**, which matched `?for=` but not the shape
    Greenhouse's own copy-paste snippet uses, `/js?for=`. That left 29 domains
    at tier A with a NULL token -- a board nobody can poll, which reads as a
    successful classification in every summary;
  * **the Avature reader**, whose board is the customer's own hostname and
    whose list page is named by the tenant;
  * **five hand-written readers** for firms that run no ATS at all. Same
    contract as the rest of `sites.py`: a redesign must raise, because an empty
    board and a broken parser are opposite facts.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from quantscraper import ats, extract, sites


class GreenhouseEmbedTest(unittest.TestCase):
    """The snippet a firm pastes onto its own careers page."""

    def test_the_js_embed_yields_the_board_and_not_the_word_embed(self):
        """Acadian and Vatic both sat unread behind exactly this string."""
        for markup, expected in (
            (
                '<script src="https://boards.greenhouse.io/embed/job_board/js'
                '?for=acadianassetmanagementllc"></script>',
                "acadianassetmanagementllc",
            ),
            (
                "https://boards.greenhouse.io/embed/job_board/js?for=vaticlabs",
                "vaticlabs",
            ),
            (
                "job-boards.greenhouse.io/embed/job_board/js?for=gsacapital&amp;b=1",
                "gsacapital",
            ),
        ):
            with self.subTest(markup=markup[:60]):
                hit = ats.fingerprint(markup)
                self.assertEqual(hit[0], "greenhouse")
                self.assertEqual(hit[1], expected)

    def test_the_older_embed_shape_still_resolves(self):
        hit = ats.fingerprint("boards.greenhouse.io/embed/job_board?for=optiver")
        self.assertEqual(hit[1], "optiver")

    def test_a_plain_board_url_is_unaffected(self):
        self.assertEqual(
            ats.fingerprint("https://job-boards.greenhouse.io/bridgewater89/jobs/1")[1],
            "bridgewater89",
        )
        self.assertEqual(
            ats.fingerprint("https://boards-api.greenhouse.io/v1/boards/janestreet")[1],
            "janestreet",
        )

    def test_an_application_form_embed_still_names_the_board(self):
        """GSA Capital publishes only these, and `for=` is always the board.

        `job_app` embeds one posting's form rather than a list, which is why
        it was skipped first time round -- and the board token is in it either
        way, so skipping it left GSA at tier A with a NULL token after the fix
        meant to clear exactly that.
        """
        hit = ats.fingerprint(
            "https://boards.greenhouse.io/embed/job_app?for=gsacapital&amp;token=4010431002"
        )
        self.assertEqual(hit[:2], ("greenhouse", "gsacapital"))


def _avature_card(job_id, title, *spans):
    inner = "".join(f'<span class="paragraph_inner-span">{s}</span>' for s in spans)
    return (
        '<article class="article article--result">'
        '<h3 class="article__header__text__title">'
        f'<a class="link" href="https://careers.example.com/careers/JobDetail/'
        f'A-Slug/{job_id}">\n  {title}\n</a></h3>'
        f'<div class="article__header__content">{inner}</div></article>'
    )


def _avature_page(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


class AvatureTest(unittest.TestCase):
    def test_it_reads_title_place_and_function_off_a_card(self):
        page = _avature_page(
            _avature_card(13671, "Quantitative Researcher", "United States - NY New York",
                          "Quantitative Research", "Early Careers")
        )
        with mock.patch.object(extract.http, "get_text", side_effect=[page, page]):
            jobs = extract.avature("careers.example.com")
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.job_id, "13671")
        self.assertEqual(job.title, "Quantitative Researcher")
        self.assertEqual(job.location, "United States - NY New York")
        self.assertEqual(job.department, "Quantitative Research")
        self.assertEqual(
            job.url,
            "https://careers.example.com/careers/JobDetail/A-Slug/13671",
        )

    def test_paging_stops_when_a_page_adds_no_new_posting(self):
        """A portal ignoring `jobOffset` serves page one forever.

        Ten is both the page size and, on a small board, the whole board, so
        stopping on a *short* page would be wrong here and stopping on an empty
        one would never terminate. Only "no new id" catches both.
        """
        page = _avature_page(*[_avature_card(n, f"Role {n}", "London") for n in range(10)])
        with mock.patch.object(extract.http, "get_text", return_value=page) as fetch:
            jobs = extract.avature("careers.example.com")
        self.assertEqual(len(jobs), 10)
        self.assertEqual(fetch.call_count, 2)

    def test_a_list_page_under_no_known_name_raises(self):
        """Silence and a renamed portal must not look alike."""
        with mock.patch.object(extract.http, "get_text", return_value="<html></html>"):
            with self.assertRaises(ValueError):
                extract.avature("careers.example.com")

    def test_it_is_dispatched_and_fingerprinted_under_the_same_name(self):
        self.assertIn("avature", extract.EXTRACTORS)
        vendors = {entry[0] for entry in ats._VENDOR_ASSETS}
        self.assertIn("avature", vendors)

    def test_the_fingerprint_and_the_reader_agree_on_the_list_paths(self):
        """One definition. Two copies of this list is a comparison that drifts."""
        for name, _asset, paths, _marker in ats._VENDOR_ASSETS:
            if name == "avature":
                self.assertIs(paths, extract.AVATURE_LIST_PATHS)


_CITADEL_SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://www.citadel.com/careers/details/c-software-engineer/</loc>
<lastmod>2026-08-25T15:14:07+00:00</lastmod></url>
<url><loc>https://www.citadel.com/careers/details/commodities-analyst/</loc>
<lastmod>2026-08-25T15:14:07+00:00</lastmod></url>
</urlset>"""


class CitadelTest(unittest.TestCase):
    def test_it_reads_the_career_sitemap(self):
        with mock.patch.object(sites.http, "get_text", return_value=_CITADEL_SITEMAP):
            jobs = sites.citadel()
        self.assertEqual([j.job_id for j in jobs], ["c-software-engineer", "commodities-analyst"])
        self.assertEqual(jobs[0].title, "C Software Engineer")
        self.assertEqual(jobs[0].url, "https://www.citadel.com/careers/details/c-software-engineer/")

    def test_the_regeneration_timestamp_is_not_read_as_a_posting_date(self):
        """Every entry carries the same `lastmod`, so it dates the file."""
        with mock.patch.object(sites.http, "get_text", return_value=_CITADEL_SITEMAP):
            jobs = sites.citadel()
        self.assertTrue(all(job.posted_at is None for job in jobs))

    def test_no_location_is_invented_from_the_slug(self):
        with mock.patch.object(sites.http, "get_text", return_value=_CITADEL_SITEMAP):
            jobs = sites.citadel()
        self.assertTrue(all(job.location is None for job in jobs))

    def test_a_sitemap_with_no_career_entries_is_loud(self):
        empty = '<?xml version="1.0"?><urlset><url><loc>https://www.citadel.com/</loc></url></urlset>'
        with mock.patch.object(sites.http, "get_text", return_value=empty):
            with self.assertRaises(sites.SiteChanged):
                sites.citadel()

    def test_the_two_firms_read_two_different_hosts(self):
        with mock.patch.object(sites.http, "get_text", return_value=_CITADEL_SITEMAP) as fetch:
            sites.citadel()
            sites.citadel_securities()
        hosts = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual(
            hosts,
            [
                "https://www.citadel.com/career-sitemap.xml",
                "https://www.citadelsecurities.com/career-sitemap.xml",
            ],
        )


def _drw_page(en, fr=()):
    payload = {"props": {"pageProps": {"jobData": {"en": list(en), "fr": list(fr)}}}}
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></html>"
    )


def _drw_job(job_id, title="Quantitative Trader", locations=("Chicago",), slug=None):
    return {
        "id": job_id,
        "job_title": title,
        "slug": slug or f"{title.lower().replace(' ', '-')}-{job_id}",
        "locations": list(locations),
        "career_categories": ["Trading"],
    }


class DrwTest(unittest.TestCase):
    def test_it_reads_the_english_array_and_joins_multiple_places(self):
        page = _drw_page([_drw_job(1, locations=("Amsterdam", "Chicago", "London"))])
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.drw()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "Amsterdam; Chicago; London")
        self.assertEqual(jobs[0].url, "https://drw.com/work-at-drw/listings/quantitative-trader-1")

    def test_the_french_array_is_not_counted_twice(self):
        """All 17 `fr` ids are already in `en` -- a whole office, doubled."""
        page = _drw_page([_drw_job(1), _drw_job(2)], fr=[_drw_job(1, title="Trader")])
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.drw()
        self.assertEqual([j.job_id for j in jobs], ["1", "2"])

    def test_a_repeated_id_inside_the_english_array_is_dropped(self):
        page = _drw_page([_drw_job(1), _drw_job(1)])
        with mock.patch.object(sites.http, "get_text", return_value=page):
            self.assertEqual(len(sites.drw()), 1)

    def test_a_page_without_next_data_is_loud(self):
        with mock.patch.object(sites.http, "get_text", return_value="<html></html>"):
            with self.assertRaises(sites.SiteChanged):
                sites.drw()

    def test_a_next_data_without_jobs_is_loud(self):
        page = '<html><script id="__NEXT_DATA__">{"props":{}}</script></html>'
        with mock.patch.object(sites.http, "get_text", return_value=page):
            with self.assertRaises(sites.SiteChanged):
                sites.drw()


def _deshaw_card(job_id, title, category="Financial Research", location="New York"):
    return (
        f'<div class="job" data-job-id="{job_id}"><div class="information">'
        f'<p class="category">{category}</p><span class="location">{location}</span>'
        '<button><svg viewBox="0 0 20 20"><path d="M10,0A10,10"/></svg></button></div>'
        f'<div class="description-wrapper"><a href="/careers/slug-{job_id}">'
        f'<p><span class="job-display-name">{title}</span>'
        "<span>: a paragraph of description&hellip;</span></p></a></div></div>"
    )


class DeShawTest(unittest.TestCase):
    def test_it_reads_title_office_and_category(self):
        page = "<html>" + _deshaw_card(5836, "Alternative Data Analyst", location="Denver") + "</html>"
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.deshaw()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_id, "5836")
        self.assertEqual(jobs[0].title, "Alternative Data Analyst")
        self.assertEqual(jobs[0].location, "Denver")
        self.assertEqual(jobs[0].department, "Financial Research")
        self.assertEqual(jobs[0].url, "https://www.deshaw.com/careers/slug-5836")

    def test_the_description_snippet_is_not_stored_as_a_body(self):
        """`bodies.py` decides what to fetch from whether a body exists."""
        page = "<html>" + _deshaw_card(1, "Quantitative Analyst") + "</html>"
        with mock.patch.object(sites.http, "get_text", return_value=page):
            self.assertIsNone(sites.deshaw()[0].description)

    def test_each_card_keeps_its_own_fields(self):
        page = "<html>" + _deshaw_card(1, "A", "Systems", "London") + _deshaw_card(
            2, "B", "Trading", "Hong Kong"
        ) + "</html>"
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.deshaw()
        self.assertEqual([(j.title, j.location, j.department) for j in jobs],
                         [("A", "London", "Systems"), ("B", "Hong Kong", "Trading")])

    def test_a_page_with_no_cards_is_loud(self):
        with mock.patch.object(sites.http, "get_text", return_value="<html>careers</html>"):
            with self.assertRaises(sites.SiteChanged):
                sites.deshaw()


_RENTEC_PAGE = """<html>
<div class="Subhead"><h2 class="Subhead_heading h4-mktg">Facilities</h2></div>
<div class="f4-mktg"><div class="md:flex"><div class="flex-auto">
<a class="Link--primary" href="/Careers.action?jobs=true&amp;selectedPosition=dataCenterSpecialist">Data Center Specialist&nbsp;</a>
</div><div>East Setauket, NY</div></div></div>
<div class="Subhead"><h2 class="Subhead_heading h4-mktg">Research</h2></div>
<div class="f4-mktg"><div class="md:flex"><div class="flex-auto">
<a class="Link--primary" href="/Careers.action?jobs=true&amp;selectedPosition=researchScientist">Research Scientist&nbsp;</a>
</div><div>New York, NY</div></div></div>
</html>"""


class RentecTest(unittest.TestCase):
    def test_it_reads_the_position_key_title_office_and_group(self):
        with mock.patch.object(sites.http, "get_text", return_value=_RENTEC_PAGE):
            jobs = sites.rentec()
        self.assertEqual([j.job_id for j in jobs], ["dataCenterSpecialist", "researchScientist"])
        self.assertEqual(jobs[1].title, "Research Scientist")
        self.assertEqual(jobs[1].location, "New York, NY")
        self.assertEqual(jobs[1].department, "Research")

    def test_the_department_is_the_heading_above_the_link(self):
        with mock.patch.object(sites.http, "get_text", return_value=_RENTEC_PAGE):
            jobs = sites.rentec()
        self.assertEqual([j.department for j in jobs], ["Facilities", "Research"])

    def test_the_entity_in_the_href_is_decoded(self):
        with mock.patch.object(sites.http, "get_text", return_value=_RENTEC_PAGE):
            self.assertIn("&selectedPosition=", sites.rentec()[0].url)
            self.assertNotIn("&amp;", sites.rentec()[0].url)

    def test_a_page_with_no_positions_is_loud(self):
        with mock.patch.object(sites.http, "get_text", return_value="<html>Jobs</html>"):
            with self.assertRaises(sites.SiteChanged):
                sites.rentec()


class Trading323Test(unittest.TestCase):
    def test_the_h1_is_the_opening(self):
        page = "<html><h1>Software Development/IT Operations</h1><p>About Us</p></html>"
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.trading_323()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Software Development/IT Operations")
        self.assertEqual(jobs[0].location, "Amsterdam, Netherlands")

    def test_a_page_with_no_title_is_loud(self):
        """A hand-edited page is the one most likely to be redesigned."""
        with mock.patch.object(sites.http, "get_text", return_value="<html><p>x</p></html>"):
            with self.assertRaises(sites.SiteChanged):
                sites.trading_323()


class MarqueeRegistrationTest(unittest.TestCase):
    def test_every_firm_found_by_hand_is_registered_once(self):
        """A reader nobody registers is a reader nobody runs."""
        tokens = [site.token for site in sites.SITES]
        self.assertEqual(len(tokens), len(set(tokens)))
        domains = [site.domain for site in sites.SITES]
        self.assertEqual(len(domains), len(set(domains)))

    def test_the_marquee_firms_are_all_present(self):
        by_domain = {site.domain: site for site in sites.SITES}
        for domain, token in (
            ("citadel.com", "citadel"),
            ("citadelsecurities.com", "citadel_securities"),
            ("twosigma.com", "careers.twosigma.com"),
            ("deshaw.com", "deshaw"),
            ("drw.com", "drw"),
            ("rentec.com", "rentec"),
            ("bridgewater.com", "bridgewater89"),
        ):
            with self.subTest(domain=domain):
                self.assertEqual(by_domain[domain].token, token)


if __name__ == "__main__":
    unittest.main()
