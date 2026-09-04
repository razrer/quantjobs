"""Regression tests for Layer 3C -- firms read from their own website.

These readers are the most fragile thing in the project: a hand-written parser
against markup nobody promised to keep stable. The tests are therefore mostly
about the *failure* shape rather than the happy path -- specifically that a
redesign is loud, because the alternative is a firm silently reported as not
hiring for months. That is the `heyrowan` lesson pointed the other way.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from quantscraper import ats, db, extract, sites


def _nordea_page(count, *rows):
    return json.dumps({"count": count, "results": list(rows)})


def _nordea_row(nid, title="Quantitative Analyst", **extra):
    row = {"nid": nid, "title": title, "location_name": "Sweden, Stockholm",
           "created": "2026-08-18", "url": f"https://www.nordea.com/en/positions/{nid}"}
    row.update(extra)
    return row


class RegistrationTest(unittest.TestCase):
    def test_every_site_is_reachable_through_the_layer_3_dispatch(self):
        """A reader nothing dispatches to is a reader that never runs.

        Same guard as `test_icims`: recognising a board and reading it are
        separate capabilities, and 88 boards once sat resolved and unread.
        """
        self.assertIn("site", extract.EXTRACTORS)
        for site in sites.SITES:
            with self.subTest(site=site.token):
                self.assertIs(sites.BY_TOKEN[site.token], site)

    def test_an_unknown_token_is_refused_rather_than_returning_nothing(self):
        with self.assertRaises(ValueError):
            sites.read("no-such-firm")

    def test_registering_is_idempotent_and_writes_tier_a(self):
        import sqlite3

        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        self.assertEqual(sites.register(connection), len(sites.SITES))
        sites.register(connection)
        rows = connection.execute(
            "SELECT domain, ats, token, tier FROM ats_resolution ORDER BY domain"
        ).fetchall()
        self.assertEqual(len(rows), len(sites.SITES))
        self.assertEqual({r["tier"] for r in rows}, {"A"})
        # Most entries dispatch to a reader here; an entry with no reader names
        # an extractor that already exists, which is how Nasdaq is recorded --
        # its board is ordinary Workday, only the fingerprint was unreachable.
        for row, site in zip(rows, sorted(sites.SITES, key=lambda s: s.domain)):
            with self.subTest(domain=row["domain"]):
                self.assertEqual(row["ats"], site.ats)
                self.assertEqual(row["token"], site.token)

    def test_an_entry_with_no_reader_names_an_extractor_that_exists(self):
        """Otherwise it resolves tier A and polls nothing, which is Stage 14."""
        for site in sites.SITES:
            if site.read is None:
                with self.subTest(site=site.token):
                    self.assertIn(site.ats, extract.EXTRACTORS)
                    self.assertNotEqual(site.ats, "site")

    def test_a_reader_entry_is_dispatched_under_site(self):
        for site in sites.SITES:
            if site.read is not None:
                with self.subTest(site=site.token):
                    self.assertEqual(site.ats, "site")

    def test_a_registered_site_is_never_picked_up_by_a_reprobe(self):
        """Tier A with a token is outside both sweeps, which is the point.

        `ats.targets` visits untiered domains and `ats.reprobe_targets` visits
        tier B, tokenless tier A, and tier A holding no postings. A hand-written
        reader must not be quietly replaced by a fingerprint of the firm's
        marketing site -- and it is in the third population by construction,
        because Captor and Norron advertise nothing, which is the answer their
        readers exist to give.
        """
        connection = db.connect(":memory:")
        sites.register(connection)
        self.assertEqual(ats.reprobe_targets(connection, 100), [])


class NordeaTest(unittest.TestCase):
    def test_it_pages_and_stops_on_a_short_page(self):
        pages = [
            _nordea_page(52, *[_nordea_row(str(n)) for n in range(sites._NORDEA_PAGE)]),
            _nordea_page(52, _nordea_row("x"), _nordea_row("y")),
        ]
        with mock.patch.object(sites.http, "get_text", side_effect=pages) as fetch:
            jobs = sites.nordea()
        self.assertEqual(len(jobs), sites._NORDEA_PAGE + 2)
        self.assertEqual(fetch.call_count, 2)

    def test_a_count_serialised_as_a_string_still_checks(self):
        """It arrives as `"110"`, and comparing a str to an int raises.

        Caught in a dry-run rather than in production, which is luck; the
        coercion is here so the check is a check rather than a TypeError.
        """
        with mock.patch.object(
            sites.http, "get_text", return_value=_nordea_page("9", _nordea_row("1"))
        ):
            with self.assertRaises(sites.SiteChanged):
                sites.nordea()

    def test_a_missing_results_key_is_loud(self):
        with mock.patch.object(sites.http, "get_text", return_value=json.dumps({})):
            with self.assertRaises(sites.SiteChanged):
                sites.nordea()

    def test_the_published_closing_date_is_mapped(self):
        with mock.patch.object(
            sites.http,
            "get_text",
            return_value=_nordea_page(1, _nordea_row("1", field_apply_due="2026-09-06")),
        ):
            self.assertEqual(sites.nordea()[0].deadline, "2026-09-06")


class Ap4Test(unittest.TestCase):
    def _page(self, *slugs, index=True):
        links = "".join(
            f'<li><a href="/karriar/lediga-tjanster/{slug}/">{title}</a></li>'
            for slug, title in slugs
        )
        head = '<a href="/karriar/lediga-tjanster/">Lediga tjanster</a>' if index else ""
        return f"<ul>{head}{links}</ul>"

    def test_the_listing_page_is_not_recorded_as_a_posting(self):
        page = self._page(("hr-chef-till-ap4", "HR-chef till AP4"))
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.ap4()
        self.assertEqual([j.job_id for j in jobs], ["hr-chef-till-ap4"])

    def test_a_posting_listed_twice_is_kept_once(self):
        """The same links appear again in the mobile menu."""
        page = self._page(("a-b-c", "One")) + self._page(("a-b-c", "One"), index=False)
        with mock.patch.object(sites.http, "get_text", return_value=page):
            self.assertEqual(len(sites.ap4()), 1)

    def test_a_page_that_no_longer_names_the_section_is_loud(self):
        with mock.patch.object(sites.http, "get_text", return_value="<h1>Ooops</h1>"):
            with self.assertRaises(sites.SiteChanged):
                sites.ap4()

    def test_an_empty_section_is_an_answer_not_a_failure(self):
        with mock.patch.object(
            sites.http, "get_text", return_value=self._page()
        ):
            self.assertEqual(sites.ap4(), [])


class BrummerTest(unittest.TestCase):
    def _page(self, *jobs):
        body = "".join(
            f"<p><strong>{title}</strong></p><p>{blurb}</p>"
            f'<p><a href="{url}" class="primary-link-arrow">Ansok har</a></p>'
            for title, blurb, url in jobs
        )
        return f"<h2>Lediga tj&#xE4;nster</h2>{body}</div>"

    def test_each_posting_keeps_its_own_apply_link(self):
        """One opening hides this bug entirely; two expose it.

        Searching the whole block for the apply link gives the second posting
        the first one's URL -- a well-formed link to the wrong job, which is
        the `heyrowan` failure at a smaller scale.
        """
        page = self._page(
            ("Compliance Officer", "Regulatory work.", "https://sharp.example/one/"),
            ("Quantitative Analyst", "Research work.", "https://recruto.example/two/"),
        )
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.brummer()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].url, "https://sharp.example/one/")
        self.assertEqual(jobs[1].url, "https://recruto.example/two/")

    def test_a_missing_heading_is_loud(self):
        with mock.patch.object(
            sites.http, "get_text", return_value="<h2>Karriar</h2><p>Hej</p></div>"
        ):
            with self.assertRaises(sites.SiteChanged):
                sites.brummer()

    def test_an_empty_block_is_an_answer(self):
        with mock.patch.object(sites.http, "get_text", return_value=self._page()):
            self.assertEqual(sites.brummer(), [])

    def test_entities_in_the_title_are_decoded(self):
        page = self._page(("Risk &amp; Kapital", "x", "https://e.example/a/"))
        with mock.patch.object(sites.http, "get_text", return_value=page):
            self.assertEqual(sites.brummer()[0].title, "Risk & Kapital")


class HaileyTest(unittest.TestCase):
    """Hailey HR, a Nordic ATS that no generic scraper covers. Coeli is on it."""

    def _card(self, job_id, title, place="Coeli Stockholm HK", summary="Blurb."):
        href = f"/sv-SE/job/{'a' * 8}-{'b' * 4}-{'c' * 4}-{'d' * 4}-{'e' * 12}/{job_id}/{'f' * 8}-{'0' * 4}-{'1' * 4}-{'2' * 4}-{'3' * 12}"
        return (
            f'<a href="{href}" class="group">'
            f'<div class="flex items-center justify-between gap-1">{place}</div>'
            f"<h3 class=\"text-2xl\">{title}</h3><p class=\"text-xl\">{summary}</p></a>"
        )

    def _job_id(self, n):
        return f"{str(n) * 8}-{'b' * 4}-{'c' * 4}-{'d' * 4}-{'e' * 12}"

    def test_it_reads_the_cards_off_the_server_rendered_board(self):
        page = self._card(self._job_id(1), "Private Equity Associate") + self._card(
            self._job_id(2), "Systemutvecklare"
        )
        with mock.patch.object(extract.http, "get_text", return_value=page):
            jobs = extract.hailey("coeli")
        self.assertEqual([j.title for j in jobs],
                         ["Private Equity Associate", "Systemutvecklare"])
        self.assertEqual(jobs[0].location, "Coeli Stockholm HK")
        self.assertTrue(jobs[0].url.startswith("https://coeli.careers.haileyhr.app/"))

    def test_an_anchor_with_no_heading_is_not_a_job(self):
        """Hailey reuses the card anchor shape for non-job tiles."""
        page = self._card(self._job_id(1), "Real Job").replace(
            '<h3 class="text-2xl">Real Job</h3>', ""
        )
        with mock.patch.object(extract.http, "get_text", return_value=page):
            self.assertEqual(extract.hailey("coeli"), [])

    def test_the_job_id_is_the_middle_uuid(self):
        page = self._card(self._job_id(7), "Quant")
        with mock.patch.object(extract.http, "get_text", return_value=page):
            self.assertEqual(extract.hailey("coeli")[0].job_id, self._job_id(7))

    def test_the_host_pattern_and_the_reader_agree(self):
        self.assertEqual(
            ats.fingerprint("https://coeli.careers.haileyhr.app/")[:2], ("hailey", "coeli")
        )
        self.assertIn("hailey", extract.EXTRACTORS)


if __name__ == "__main__":
    unittest.main()


class ProseBoardTest(unittest.TestCase):
    """AP7, Captor and Norron: careers pages written as prose, not boards."""

    def _page(self, *jobs, no_vacancies=False):
        body = "".join(
            f'<p><a href="{url}"><strong>{title}</strong></a></p>'
            for title, url in jobs
        )
        if no_vacancies:
            body += "<p>För tillfället har vi inga lediga tjänster.</p>"
        return f"<h2>Lediga tjänster</h2>{body}"

    def test_both_nestings_of_the_bold_title_are_read(self):
        """A hand-edited page has no house style, and this cost a posting.

        AP7 writes three of four as `<a><strong>x</strong></a>` and the fourth
        as `<strong><a>x</a></strong>` -- and the fourth is the Senior
        Portfolio Manager, Asset Allocation seat.
        """
        page = (
            '<h2>Lediga tjänster</h2>'
            '<p><a href="https://r.example/a/"><strong>Portfolio Manager</strong></a></p>'
            '<p><strong><a href="https://r.example/b/">Asset Allocation</a></strong></p>'
        )
        with mock.patch.object(sites.http, "get_text", return_value=page):
            jobs = sites.ap7()
        self.assertEqual([j.title for j in jobs], ["Portfolio Manager", "Asset Allocation"])
        self.assertEqual(jobs[1].url, "https://r.example/b/")

    def test_a_firm_that_says_it_has_no_vacancies_reports_none(self):
        with mock.patch.object(
            sites.http, "get_text", return_value=self._page(no_vacancies=True)
        ):
            self.assertEqual(sites.captor(), [])

    def test_but_silence_with_no_such_statement_is_loud(self):
        """An empty result and a broken parser look identical from outside.

        Only one of them is news, so the page has to prove it was understood:
        either a posting, or the sentence saying there are none.
        """
        with mock.patch.object(sites.http, "get_text", return_value="<h1>Hej</h1>"):
            with self.assertRaises(sites.SiteChanged):
                sites.captor()

    def test_the_english_phrasing_counts_too(self):
        with mock.patch.object(
            sites.http, "get_text", return_value="<p>We have no current vacancies.</p>"
        ):
            self.assertEqual(sites.captor(), [])

    def test_a_posting_listed_twice_is_kept_once(self):
        page = self._page(("Quant", "https://r.example/a/"), ("Quant", "https://r.example/a/"))
        with mock.patch.object(sites.http, "get_text", return_value=page):
            self.assertEqual(len(sites.ap7()), 1)
