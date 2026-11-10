"""Regression tests for reading the ATS vendors' cross-tenant search.

What is quiet when wrong: a location read as another country, a short or
partial walk withdrawing postings it never visited, a tenant's platform page
taken as its domain, an irrelevant tenant polled weekly, and a tenant board
overwriting a domain's working one.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from quantscraper import alerts, db, dedup, discover, domains, lexicon, vendors
from quantscraper.models import Job


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    return connection


def _row(job_id: str, title="Quantitative Researcher", country="Sweden",
         company="Nordic Quant AB", website="https://www.nordicquant.se") -> dict:
    return {
        "id": job_id, "title": title, "description": "<p>Build models.</p>",
        "requirementsSection": "<ul><li>Python</li></ul>", "department": "Research",
        "url": f"https://jobs.workable.com/view/{job_id}/x",
        "locations": [f"Stockholm, {country}"],
        "location": {"city": "Stockholm", "countryName": country},
        "created": "2026-11-09T10:00:00Z",
        "company": {"title": company, "website": website},
    }


def _pages(*pages, total=None):
    """`fetch_page` answers, chained by cursor."""
    answers = []
    for index, rows in enumerate(pages):
        answers.append({
            "totalSize": total if total is not None else sum(len(p) for p in pages),
            "jobs": rows,
            "nextPageToken": f"c{index + 1}" if index + 1 < len(pages) else None,
        })
    return answers


class WorkableCensusTest(unittest.TestCase):
    def setUp(self):
        floors = {token: (loc, country, 0) for token, (loc, country, _) in vendors.HUBS.items()}
        patcher = mock.patch.dict(vendors.HUBS, floors)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_row_keeps_the_tenant_name_body_and_domain(self):
        job = vendors._job("sweden", _row("a1"))

        self.assertEqual((job.ats, job.token, job.job_id), ("workable_jobs", "sweden", "a1"))
        self.assertEqual(job.employer, "Nordic Quant AB")
        self.assertIn("Python", job.description)
        self.assertEqual(vendors.tenant_domain(_row("a1")), "nordicquant.se")
        self.assertIsNone(vendors.tenant_domain(
            _row("a1", website="https://linkedin.com/company/x")))

    def test_a_location_read_as_another_country_is_refused(self):
        rows = [_row(str(i), country="United States") for i in range(4)]
        with mock.patch.object(vendors, "fetch_page", side_effect=_pages(rows)):
            with self.assertRaises(vendors.Blocked):
                vendors.walk("sweden")

    def test_a_short_walk_is_a_problem_and_writes_nothing(self):
        connection = _memory(self)
        with mock.patch.object(vendors, "fetch_page",
                               side_effect=_pages([_row("a"), _row("b")], total=9)):
            result = vendors.run(connection, only=["sweden"])

        self.assertIsNotNone(result.hubs[0].problem)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_a_sound_walk_withdraws_only_what_it_no_longer_lists(self):
        connection = _memory(self)
        with mock.patch.object(vendors, "fetch_page",
                               side_effect=_pages([_row("a"), _row("b")], [_row("c")])):
            vendors.run(connection, only=["sweden"])
        connection.execute("UPDATE jobs SET last_seen = '2000-01-01'")
        with mock.patch.object(vendors, "fetch_page", side_effect=_pages([_row("a"), _row("c")])):
            result = vendors.run(connection, only=["sweden"])

        self.assertEqual(result.hubs[0].withdrawn, 1)
        live = {r[0] for r in connection.execute(
            "SELECT job_id FROM jobs WHERE removed_at IS NULL")}
        self.assertEqual(live, {"a", "c"})
        domain = connection.execute(
            "SELECT DISTINCT domain FROM jobs").fetchall()
        self.assertEqual([r[0] for r in domain], ["nordicquant.se"])

    def test_a_page_probe_withdraws_nothing(self):
        connection = _memory(self)
        with mock.patch.object(vendors, "fetch_page", side_effect=_pages([_row("a")])):
            vendors.run(connection, only=["sweden"])
        connection.execute("UPDATE jobs SET last_seen = '2000-01-01'")
        with mock.patch.object(vendors, "fetch_page",
                               side_effect=_pages([_row("b")], [_row("c")])):
            result = vendors.run(connection, only=["sweden"], pages=1)

        self.assertTrue(result.partial)
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE removed_at IS NOT NULL").fetchone()[0], 0)

    def test_only_a_tenant_hiring_for_markets_is_cached_as_a_lead(self):
        connection = _memory(self)
        connection.executescript(domains.SCHEMA)
        connection.execute(
            "INSERT INTO domain_lookups VALUES ('Known AB', 'known.se', 'registry', 'x', 'then')")
        found = {
            "a": (vendors._job("sweden", _row("a")), "nordicquant.se"),
            "b": (vendors._job("sweden", _row("b", title="Cashier", company="Shop AB")), "shop.se"),
            "c": (vendors._job("sweden", _row("c", company="Known AB")), "other.se"),
        }

        self.assertEqual(vendors.leads(connection, found), 1)
        rows = dict(connection.execute("SELECT query, domain FROM domain_lookups"))
        self.assertEqual(rows, {"Known AB": "known.se", "Nordic Quant AB": "nordicquant.se"})


def _sr(token, name, title, country="se"):
    return {"name": title, "company": {"identifier": token, "name": name},
            "location": {"country": country}}


class SmartRecruitersLeadTest(unittest.TestCase):
    def _search(self, rows_by_keyword, total=None):
        def answer(keyword):
            rows = rows_by_keyword.get(keyword, [])
            return {"totalFound": total or len(rows), "content": rows}
        return answer

    def test_tenants_are_read_per_hub_and_a_full_window_is_named(self):
        result = vendors.LeadSweep()
        rows = {"Stockholm": [_sr("NQ", "Nordic Quant", "Quant Trader"),
                              _sr("US1", "Elsewhere", "Trader", country="us")]}
        with mock.patch.object(vendors, "sr_search", side_effect=self._search(rows, total=500)):
            tenants = vendors.sr_tenants(result)

        self.assertEqual(set(tenants), {"NQ"})
        self.assertIn("Stockholm", result.windowed)

    def test_an_irrelevant_tenant_is_not_read_at_all(self):
        tenant = vendors.Tenant("SHOP", "Shop AB", "SE", ["Cashier"])
        reader = mock.Mock()
        with mock.patch.dict(vendors.extract.EXTRACTORS, {"smartrecruiters": reader}):
            outcome = vendors._settle(tenant, {})
        self.assertEqual(outcome[0], "not-relevant")
        reader.assert_not_called()

    def test_a_universe_firm_is_read_even_without_a_markets_title(self):
        tenant = vendors.Tenant("ACME", "Acme Bank AB", "SE", ["Receptionist"])
        job = Job(ats="smartrecruiters", token="ACME", job_id="1", title="Receptionist")
        with mock.patch.dict(vendors.extract.EXTRACTORS,
                             {"smartrecruiters": mock.Mock(return_value=[job])}):
            outcome = vendors._settle(tenant, {"acme bank": "acmebank.se"})
        self.assertEqual(outcome[:2], ("board", "acmebank.se"))

    def test_a_board_never_replaces_a_domains_working_one(self):
        connection = _memory(self)
        connection.executescript(domains.SCHEMA)
        connection.executescript(discover.ats.SCHEMA)
        connection.executemany(
            "INSERT INTO domain_lookups VALUES (?, ?, 'registry', 'x', 'then')",
            [("Acme Bank AB", "acmebank.se"), ("Beta Capital AB", "beta.se")])
        connection.execute(
            "INSERT INTO ats_resolution (domain, careers_url, ats, token, tier, evidence, checked_at)"
            " VALUES ('acmebank.se', NULL, 'workday', 'acme|wd3|Ext', 'A', 'walk', 'then')")
        rows = {"Stockholm": [_sr("ACME", "Acme Bank AB", "Quant Analyst"),
                              _sr("BETA", "Beta Capital AB", "Quantitative Trader")]}
        job = Job(ats="smartrecruiters", token="x", job_id="1", title="Quant")
        with mock.patch.object(vendors, "sr_search", side_effect=self._search(rows)), \
             mock.patch.dict(vendors.extract.EXTRACTORS,
                             {"smartrecruiters": mock.Mock(return_value=[job])}):
            result = vendors.sr_leads(connection, workers=1)

        self.assertEqual([b[0] for b in result.boards], ["BETA"])
        self.assertEqual(tuple(connection.execute(
            "SELECT ats, token FROM ats_resolution WHERE domain = 'acmebank.se'").fetchone()),
            ("workday", "acme|wd3|Ext"))
        outcomes = dict(connection.execute("SELECT token, outcome FROM vendor_tenants"))
        self.assertEqual(outcomes, {"ACME": "domain-taken", "BETA": "board"})
        # Settled, so the next run asks nothing.
        self.assertEqual(vendors._due(connection, "smartrecruiters", ["ACME", "BETA"]), set())


class RegistrationTest(unittest.TestCase):
    def test_the_census_is_a_portal_everywhere_a_portal_is_listed(self):
        self.assertIn(vendors.NAME, lexicon.NOT_A_BOARD)
        self.assertIn(vendors.NAME, dedup.PORTALS)
        self.assertIn(vendors.NAME, alerts._expected())

    def test_the_search_host_is_read_slowly(self):
        from quantscraper import http

        self.assertGreaterEqual(http.HOST_INTERVAL_S[vendors.HOST], 4.0)

    def test_no_contact_address_is_sent(self):
        self.assertNotIn("@", vendors.HEADERS["User-Agent"])


if __name__ == "__main__":
    unittest.main()
