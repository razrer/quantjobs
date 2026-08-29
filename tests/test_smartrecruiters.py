"""Regression tests for the SmartRecruiters extractor.

One defect, and it was total: **every live SmartRecruiters row we held had a
NULL URL** -- 1,507 of them across 12 boards, rendered on the board as cards
nobody could open. The API returns `ref` as a dict of links on some boards and
as a bare self-link string on others, and where it is a string `applyUrl` is
null too, so both fallbacks resolved to nothing. The code carried a comment
noting the two shapes and then gave up on the second.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from quantscraper import extract


def _payload(*postings: dict) -> bytes:
    return json.dumps({"content": list(postings)}).encode()


class SmartRecruitersUrlTest(unittest.TestCase):
    def _read(self, *postings: dict, token: str = "BoschGroup"):
        with mock.patch.object(extract.http, "get",
                               return_value=_payload(*postings)):
            return extract.smartrecruiters(token)

    def test_a_string_ref_falls_back_to_the_public_ad(self):
        """The live shape, taken verbatim from `BoschGroup`: `ref` is the API's
        own self-link and `applyUrl` is null. The constructed URL was verified
        against the live board -- it returns the ad, and the title slug some
        boards append is optional."""
        jobs = self._read({
            "id": "744000146296139",
            "name": "AI Research Scientist - GenAI",
            "ref": "https://api.smartrecruiters.com/v1/companies/BoschGroup"
                   "/postings/744000146296139",
            "applyUrl": None,
            "company": {"identifier": "BoschGroup", "name": "Bosch Group"},
        })
        self.assertEqual(
            jobs[0].url,
            "https://jobs.smartrecruiters.com/BoschGroup/744000146296139")

    def test_a_published_link_still_wins(self):
        """The fallback must not displace a URL the board actually gave us."""
        jobs = self._read({
            "id": "1", "name": "Quant Trader",
            "ref": {"jobAd": "https://example.com/ad/1"},
        })
        self.assertEqual(jobs[0].url, "https://example.com/ad/1")

    def test_apply_url_is_preferred_over_the_construction(self):
        jobs = self._read({
            "id": "2", "name": "Quant Researcher",
            "ref": "https://api.smartrecruiters.com/whatever",
            "applyUrl": "https://example.com/apply/2",
        })
        self.assertEqual(jobs[0].url, "https://example.com/apply/2")

    def test_the_token_stands_in_when_the_payload_names_no_company(self):
        """`company.identifier` is the payload's own answer to the same
        question, so it wins -- but the token is what we queried with and is
        never absent."""
        jobs = self._read({"id": "3", "name": "Strat", "ref": "https://api/x"},
                          token="SomeBoard")
        self.assertEqual(jobs[0].url,
                         "https://jobs.smartrecruiters.com/SomeBoard/3")

    def test_no_posting_is_left_without_a_url(self):
        """The property that failed, stated directly."""
        jobs = self._read(
            {"id": "1", "name": "A", "ref": "https://api/1"},
            {"id": "2", "name": "B", "ref": {"jobAd": "https://example.com/2"}},
            {"id": "3", "name": "C", "applyUrl": "https://example.com/3"},
        )
        self.assertEqual(len(jobs), 3)
        self.assertTrue(all(j.url for j in jobs))
