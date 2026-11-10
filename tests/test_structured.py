"""Regression tests for reading tier-B careers pages through structured data.

What is quiet when wrong: navigation read as postings, a posting nested in
`@graph` or an `ItemList` missed, a sitemap URL taken as a posting without its
page proving it, and a promotion replacing a board another layer resolved.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from unittest import mock

from quantscraper import ats, extract, structured


def _page(*islands, body="<a href='/careers'>Careers</a>") -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(island)}</script>'
        for island in islands
    )
    return f"<html><head>{scripts}</head><body>{body}</body></html>"


POSTING = {
    "@context": "https://schema.org", "@type": "JobPosting",
    "title": "Quantitative Researcher", "datePosted": "2026-11-01T00:00:00",
    "validThrough": "2026-12-01", "description": "<p>Research &amp; models</p>",
    "identifier": {"@type": "PropertyValue", "value": "QR-7"},
    "url": "/jobs/quant-researcher",
    "jobLocation": {"@type": "Place", "address": {
        "addressLocality": "Stockholm", "addressCountry": "SE"}},
}


class PostingsInTest(unittest.TestCase):
    def test_nested_postings_are_found_and_other_islands_ignored(self):
        page = _page(
            {"@type": "Organization", "name": "Nordic Quant"},
            {"@graph": [{"@type": "WebPage"}, POSTING]},
            {"@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "item": dict(POSTING, title="Trader")}]},
            {"@type": ["JobPosting"], "title": "Risk Quant"},
        )
        titles = [p["title"] for p in structured.postings_in(page)]
        self.assertEqual(titles, ["Quantitative Researcher", "Trader", "Risk Quant"])

    def test_a_page_of_links_yields_nothing(self):
        """The `pages.py` failure: navigation is not a posting."""
        page = "<html><body>" + "".join(
            f"<a href='/jobs/{n}'>Job {n}</a>" for n in range(20)) + "</body></html>"
        self.assertEqual(structured.postings_in(page), [])

    def test_a_malformed_island_does_not_cost_the_others(self):
        page = ('<script type="application/ld+json">{"@type": "JobPosting",</script>'
                + _page(POSTING))
        self.assertEqual(len(structured.postings_in(page)), 1)

    def test_a_posting_becomes_a_job(self):
        job = structured.job_from("https://nq.se/careers", POSTING, "https://nq.se/careers")

        self.assertEqual(job.ats, "jsonld")
        self.assertEqual(job.job_id, "QR-7")
        self.assertEqual(job.url, "https://nq.se/jobs/quant-researcher")
        self.assertEqual(job.location, "Stockholm, SE")
        self.assertEqual((job.posted_at, job.deadline), ("2026-11-01", "2026-12-01"))
        self.assertEqual(job.description, "Research & models")

    def test_an_identifier_is_its_value_not_its_issuer(self):
        jobs = [structured.job_from("t", dict(POSTING, identifier={
            "@type": "PropertyValue", "name": "Alter Domus", "value": v}), "https://a.com/c")
            for v in ("1", "2")]
        self.assertEqual([job.job_id for job in jobs], ["1", "2"])

    def test_postings_sharing_a_page_url_keep_distinct_ids(self):
        bare = {"@type": "JobPosting", "title": "Trader"}
        other = {"@type": "JobPosting", "title": "Quant Developer"}
        jobs = [structured.job_from("t", p, "https://nq.se/careers") for p in (bare, other)]
        self.assertEqual(len({job.job_id for job in jobs}), 2)


class SitemapTest(unittest.TestCase):
    def _site(self, pages):
        def fetch(url):
            return pages.get(url)
        return mock.patch.object(structured, "_fetch", side_effect=fetch)

    def test_robots_names_the_index_and_posting_sitemaps_are_read_first(self):
        pages = {
            "https://nq.se/robots.txt": "User-agent: *\nSitemap: https://nq.se/sitemap_index.xml",
            "https://nq.se/sitemap_index.xml": (
                "<sitemapindex><sitemap><loc>https://nq.se/post-sitemap.xml</loc></sitemap>"
                "<sitemap><loc>https://nq.se/job-sitemap.xml</loc></sitemap></sitemapindex>"),
            "https://nq.se/job-sitemap.xml": (
                "<urlset><url><loc>https://nq.se/jobs/quant-researcher</loc></url>"
                "<url><loc>https://nq.se/careers</loc></url>"
                "<url><loc>https://other.com/jobs/x</loc></url></urlset>"),
            "https://nq.se/post-sitemap.xml": "<urlset><url><loc>https://nq.se/blog/a</loc></url></urlset>",
        }
        with self._site(pages):
            urls = structured.sitemap_postings("https://nq.se/careers")
        self.assertEqual(urls, ["https://nq.se/jobs/quant-researcher"])

    def test_a_sitemap_url_counts_only_when_its_page_proves_it(self):
        pages = {
            "https://nq.se/careers": _page(),
            "https://nq.se/sitemap.xml": (
                "<urlset><url><loc>https://nq.se/jobs/a</loc></url>"
                "<url><loc>https://nq.se/jobs/b</loc></url></urlset>"),
            "https://nq.se/jobs/a": _page(dict(POSTING, identifier=None, url=None)),
            "https://nq.se/jobs/b": "<html>a press release under /jobs/</html>",
        }
        with self._site(pages):
            found = structured.read_board("https://nq.se/careers")
        self.assertEqual(found.route, "sitemap")
        self.assertEqual([job.job_id for job in found.jobs], ["https://nq.se/jobs/a"])

    def test_nothing_structured_is_no_route(self):
        with self._site({"https://nq.se/careers": _page()}):
            found = structured.read_board("https://nq.se/careers")
        self.assertIsNone(found.route)
        self.assertEqual(found.jobs, [])


class PromotionTest(unittest.TestCase):
    def _connection(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(ats.SCHEMA)
        connection.executemany(
            "INSERT INTO ats_resolution (domain, careers_url, ats, token, tier, evidence, checked_at)"
            " VALUES (?, ?, NULL, NULL, 'B', 'careers page', 'then')",
            [("nq.se", "https://nq.se/careers"), ("dull.se", "https://dull.se/jobb"),
             ("social.se", "https://www.linkedin.com/company/social")],
        )
        return connection

    def test_a_publishing_page_is_promoted_and_the_rest_recorded(self):
        connection = self._connection()

        def read_board(url, details):
            if "nq.se" in url:
                job = structured.job_from(url, POSTING, url)
                return structured.Read("page", [job], "1 JobPosting on the careers page")
            return structured.Read(evidence="nothing")

        with mock.patch.object(structured, "read_board", side_effect=read_board) as reader:
            counts = structured.run(connection, 10, workers=1)

        self.assertEqual((counts["probed"], counts["page"]), (3, 1))
        row = connection.execute(
            "SELECT tier, ats, token FROM ats_resolution WHERE domain = 'nq.se'").fetchone()
        self.assertEqual(tuple(row), ("A", "jsonld", "https://nq.se/careers"))
        # A platform page is not even fetched.
        self.assertNotIn("linkedin", " ".join(str(c.args[0]) for c in reader.call_args_list))
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM structured_attempts").fetchone()[0], 3)
        # Attempted rows sort behind untried ones next time.
        connection.execute(
            "INSERT INTO ats_resolution (domain, careers_url, tier, checked_at)"
            " VALUES ('new.se', 'https://new.se/careers', 'B', 'then')")
        self.assertEqual(structured.targets(connection, 1)[0]["domain"], "new.se")

    def test_only_the_firms_own_site_and_one_employer_qualify(self):
        self.assertTrue(structured.eligible("https://careers.nq.se/jobs", "nq.se"))
        self.assertFalse(structured.eligible(
            "https://careers.allianz.com/search", "allianzcapitalpartners.com"))
        self.assertFalse(structured.eligible("https://linkedin.com/company/x", None))
        portfolio = [dict(POSTING, hiringOrganization={"name": n}) for n in ("Acme", "Beta")]
        self.assertFalse(structured.one_employer(portfolio))
        self.assertTrue(structured.one_employer(portfolio[:1] + [POSTING]))

    def test_a_probe_samples_across_the_whole_sitemap(self):
        urls = [f"u{n}" for n in range(100)]
        self.assertEqual(structured.sample(urls, 3), ["u0", "u50", "u99"])
        self.assertEqual(structured.sample(urls[:2], 3), ["u0", "u1"])

    def test_the_reader_is_registered(self):
        self.assertIn(structured.NAME, extract.EXTRACTORS)


if __name__ == "__main__":
    unittest.main()
