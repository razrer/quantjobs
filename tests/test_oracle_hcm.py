"""Regression tests for Oracle Fusion Recruiting, and the two Layer 2 defects
that finding it exposed.

Oracle was not recognised at all. Danske Bank -- a Copenhagen roster firm --
sat in tier B with 139 live postings behind it, and the only reason anyone
looked was a measurement asking why 59 of 120 roster firms produce no jobs.

Two other things were hiding boards in the same way and are pinned here
because both are one-line regressions waiting to happen:

  * a board URL escaped inside a JSON island matches no host pattern, which is
    how Julius Baer's Workday feed went unseen;
  * a firm linking "Jobs" at its LinkedIn page put a platform URL at the top of
    the careers candidates, and only three are ever fetched.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from quantscraper import ats, extract

BACKSLASH = chr(92)


def _payload(total, *reqs):
    return json.dumps(
        {"items": [{"TotalJobsCount": total, "requisitionList": list(reqs)}]}
    )


def _req(job_id, title="Quantitative Analyst", **extra):
    row = {"Id": job_id, "Title": title, "PrimaryLocation": "Copenhagen, Denmark"}
    row.update(extra)
    return row


class OracleTokenTest(unittest.TestCase):
    """The token is `podhost|siteNumber`, and neither half works alone."""

    def test_the_pod_host_and_the_site_are_both_captured(self):
        hit = ats.fingerprint(
            "https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience"
            "/en/sites/CX_1001/requisitions"
        )
        self.assertEqual(hit[0], "oracle_hcm")
        self.assertEqual(hit[1], "ejqi.fa.ocs.oraclecloud.eu|CX_1001")

    def test_the_language_segment_is_optional(self):
        hit = ats.fingerprint(
            "https://x1.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/sites/CX_2/jobs"
        )
        self.assertEqual(hit[1], "x1.fa.us2.oraclecloud.com|CX_2")

    def test_a_half_token_is_refused_rather_than_polled(self):
        """`CX_1001` is Oracle's default, so a site alone collides everywhere."""
        with self.assertRaises(ValueError):
            extract.oracle_hcm("CX_1001")


class OraclePagingTest(unittest.TestCase):
    def test_it_pages_by_offset_and_stops_on_a_short_page(self):
        full = [_req(str(n)) for n in range(extract._ORACLE_PAGE)]
        pages = [_payload(extract._ORACLE_PAGE + 2, *full), _payload(202, _req("x"), _req("y"))]
        with mock.patch.object(extract.http, "get_text", side_effect=pages) as fetch:
            jobs = extract.oracle_hcm("pod.example|CX_1001")

        self.assertEqual(len(jobs), extract._ORACLE_PAGE + 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("offset=0", fetch.call_args_list[0].args[0])
        self.assertIn(f"offset={extract._ORACLE_PAGE}", fetch.call_args_list[1].args[0])

    def test_a_board_handing_over_less_than_it_advertises_is_loud(self):
        """The board states its own size, so a truncation cannot be silent.

        This is the check that caught Jobvite's missing slash: a round number
        is what a cap looks like from the outside and nothing else says so.
        """
        with mock.patch.object(
            extract.http, "get_text", return_value=_payload(500, _req("1"))
        ):
            with self.assertRaises(ValueError) as caught:
                extract.oracle_hcm("pod.example|CX_1001")
        self.assertIn("advertises 500", str(caught.exception))

    def test_an_empty_board_is_an_answer_not_a_failure(self):
        with mock.patch.object(extract.http, "get_text", return_value=_payload(0)):
            self.assertEqual(extract.oracle_hcm("pod.example|CX_1001"), [])


class OracleFieldsTest(unittest.TestCase):
    def test_a_published_closing_date_is_mapped(self):
        """`PostingEndDate` is a field, so it is taken -- never mined from prose."""
        with mock.patch.object(
            extract.http,
            "get_text",
            return_value=_payload(1, _req("7", PostingEndDate="2026-09-30")),
        ):
            jobs = extract.oracle_hcm("pod.example|CX_1001")
        self.assertEqual(jobs[0].deadline, "2026-09-30")

    def test_a_row_with_no_id_is_dropped_and_the_shortfall_is_loud(self):
        """Two rules meeting, and the pair is the point.

        A posting with no id cannot be keyed, so it is dropped -- but the board
        counted it, so dropping it silently would look exactly like a board
        that shrank. The advertised-total check turns that into a failure.
        """
        with mock.patch.object(
            extract.http, "get_text", return_value=_payload(1, _req("", title="Ghost"))
        ):
            with self.assertRaises(ValueError):
                extract.oracle_hcm("pod.example|CX_1001")

    def test_the_url_addresses_the_posting_on_the_firms_own_pod(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=_payload(1, _req("42"))
        ):
            jobs = extract.oracle_hcm("ejqi.fa.ocs.oraclecloud.eu|CX_1001")
        self.assertEqual(
            jobs[0].url,
            "https://ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience"
            "/en/sites/CX_1001/job/42",
        )


class RegisteredTest(unittest.TestCase):
    def test_every_fingerprinted_oracle_board_has_a_reader(self):
        """Recognising an ATS and reading it are separate capabilities.

        88 boards once sat tier A with a token and no extractor, counted as
        resolved everywhere and polling nothing. `test_icims` pins the same
        thing for the same reason.
        """
        self.assertIn("oracle_hcm", extract.EXTRACTORS)
        self.assertIn("oracle_hcm", {name for name, _ in ats.ATS_PATTERNS})


class EscapedMarkupTest(unittest.TestCase):
    """A board URL inside a JSON island matches no host pattern as written."""

    def _julius_baer(self, slash):
        return (
            "&quot;href&quot;:&quot;https:" + slash + slash
            + "juliusbaer.wd3.myworkdayjobs.com" + slash + "en-US" + slash
            + "External&quot;"
        )

    def test_a_json_escaped_workday_url_is_still_found(self):
        hit = ats.fingerprint(self._julius_baer(BACKSLASH + "/"))
        self.assertEqual(hit[0], "workday")
        self.assertEqual(hit[1], "juliusbaer|wd3|External")

    def test_and_so_is_a_doubly_escaped_one(self):
        hit = ats.fingerprint(self._julius_baer(BACKSLASH + BACKSLASH + "/"))
        self.assertEqual(hit[1], "juliusbaer|wd3|External")

    def test_a_code_point_slash_is_undone_in_either_case(self):
        for spelling in (BACKSLASH + "u002F", BACKSLASH + "u002f"):
            with self.subTest(spelling=spelling):
                hit = ats.fingerprint(self._julius_baer(spelling))
                self.assertEqual(hit[1], "juliusbaer|wd3|External")

    def test_unescaping_leaves_ordinary_markup_alone(self):
        plain = "https://boards.greenhouse.io/optiver"
        self.assertEqual(ats._unescape(plain), plain)

    def test_it_stays_cheap_on_a_page_dense_in_escapes(self):
        """Anything that scans fetched markup gets timed here.

        Two `ats` runs once sat at 100% CPU for two and a half hours on a
        quadratic pattern, and it looked exactly like slow network. This one is
        linear, but it runs on every page at up to 2 MB, so it is pinned. It
        also *shrinks* the markup, which makes the regex pass that follows
        cheaper rather than dearer.
        """
        chunk = "&quot;a" + BACKSLASH + "/b&amp;c" + BACKSLASH * 2 + "/d&#x2F;e"
        markup = chunk * (2_000_000 // len(chunk))
        start = time.monotonic()
        shrunk = ats._unescape(markup)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertLess(len(shrunk), len(markup))


class PlatformCareersLinkTest(unittest.TestCase):
    """A social profile is not a careers page, and it outranked the real one."""

    def test_a_linkedin_jobs_link_is_not_a_careers_candidate(self):
        markup = (
            '<a href="https://www.linkedin.com/company/handelsbanken/jobs/">Jobb</a>'
            '<a href="/karriar">Karriar</a>'
        )
        self.assertEqual(
            ats.careers_candidates(markup, "handelsbanken.se"),
            ["https://handelsbanken.se/karriar"],
        )

    def test_nor_is_an_instagram_account(self):
        markup = (
            '<a href="https://www.instagram.com/werkenbijpggm/">werken bij</a>'
            '<a href="/nl/werken-bij">Werken bij</a>'
        )
        self.assertEqual(
            ats.careers_candidates(markup, "pggm.nl"), ["https://pggm.nl/nl/werken-bij"]
        )

    def test_a_genuine_off_site_board_still_ranks_first(self):
        """The rule that let the platform link win is the rule worth keeping.

        An off-site careers link is usually the ATS itself, which is the whole
        thing being looked for -- so only platforms are excluded, not off-site
        links in general.
        """
        markup = (
            '<a href="/about">x</a>'
            '<a href="https://job-boards.greenhouse.io/acme">Careers</a>'
            '<a href="/careers">Careers</a>'
        )
        self.assertEqual(
            ats.careers_candidates(markup, "acme.com")[0],
            "https://job-boards.greenhouse.io/acme",
        )


if __name__ == "__main__":
    unittest.main()


class ReprobeTest(unittest.TestCase):
    """A re-probe may improve a stored row and must never demote one."""

    def _stored(self, careers_url):
        return {"domain": "acme.com", "careers_url": careers_url}

    def test_a_pollable_board_is_written(self):
        found = ats.Resolution(
            "acme.com", "https://acme.com/careers", "oracle_hcm", "pod|CX_1", "A", "x"
        )
        self.assertTrue(ats._improves(found, self._stored("https://acme.com/careers")))

    def test_a_tier_a_row_with_no_token_is_not_an_improvement(self):
        """Tier A with no token is the state this sweep exists to fix."""
        found = ats.Resolution("acme.com", "https://acme.com/c", "taleo", None, "A", "x")
        self.assertFalse(ats._improves(found, self._stored("https://acme.com/c")))

    def test_a_host_that_times_out_does_not_delete_the_watched_page(self):
        """One bad request must not cost months of Layer 3B history."""
        found = ats.Resolution("acme.com", None, None, None, "C", "homepage unreachable")
        self.assertFalse(ats._improves(found, self._stored("https://acme.com/careers")))

    def test_a_real_careers_page_replaces_a_platform_one(self):
        """Not a promotion -- it stays tier B -- but worth writing.

        Leaving it alone keeps Layer 3B diffing an Instagram account, which can
        never carry a posting.
        """
        found = ats.Resolution(
            "pggm.nl", "https://pggm.nl/nl/werken-bij", None, None, "B", "no fingerprint"
        )
        self.assertTrue(
            ats._improves(found, self._stored("https://www.instagram.com/werkenbijpggm/"))
        )

    def test_but_one_ordinary_careers_page_does_not_replace_another(self):
        """Otherwise every sweep rewrites every row for no reason."""
        found = ats.Resolution(
            "acme.com", "https://acme.com/jobs", None, None, "B", "no fingerprint"
        )
        self.assertFalse(ats._improves(found, self._stored("https://acme.com/careers")))


class AdpTest(unittest.TestCase):
    """ADP Workforce Now -- the largest unrecognised vendor in a tier-B sample."""

    def _payload(self, total, *reqs):
        return json.dumps({"jobRequisitions": list(reqs), "meta": {"totalNumber": total}})

    def _req(self, item_id, title="Quantitative Analyst", **loc):
        return {
            "itemID": item_id,
            "requisitionTitle": title,
            "postDate": "2026-08-12T11:48:00.000-04:00",
            "requisitionLocations": [
                {
                    "address": {
                        "cityName": loc.get("city", ""),
                        "countrySubdivisionLevel1": {"codeValue": loc.get("region", "")},
                    },
                    "nameCode": {"shortName": loc.get("country", " US")},
                }
            ],
        }

    def test_the_cid_guid_is_the_whole_token(self):
        hit = ats.fingerprint(
            "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/"
            "recruitment.html?cid=7120c628-221c-4769-b7e7-8ab11b78b67f&ccId=9200879253113_2"
        )
        self.assertEqual(hit[0], "adp")
        self.assertEqual(hit[1], "7120c628-221c-4769-b7e7-8ab11b78b67f")

    def test_the_location_facet_is_not_read_as_a_posting_location(self):
        """`meta.links` pairs *location* ids with places, not requisition ids.

        Joining it to `itemID` produces a confident location for every posting
        and matches nothing. The board gates on geography, so a wrong location
        is worse than none.
        """
        payload = json.loads(self._payload(1, self._req("9205211298133_1")))
        payload["meta"]["links"] = [
            {
                "schema": "LOCATION",
                "payLoadArguments": [
                    {"argumentPath": "9200391134514_1",
                     "argumentValue": "Hong Kong - Wanchai, HK"}
                ],
            }
        ]
        with mock.patch.object(
            extract.http, "get_text", return_value=json.dumps(payload)
        ):
            job = extract.adp("cid")[0]
        self.assertEqual(job.location, "US")

    def test_a_filled_in_address_is_preferred(self):
        with mock.patch.object(
            extract.http,
            "get_text",
            return_value=self._payload(
                1, self._req("1", city="Wanchai", region="HK", country=" Hong Kong")
            ),
        ):
            self.assertEqual(extract.adp("cid")[0].location, "Wanchai, HK, Hong Kong")

    def test_a_shortfall_against_the_advertised_total_is_loud(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=self._payload(9, self._req("1"))
        ):
            with self.assertRaises(ValueError):
                extract.adp("cid")


class UkgTest(unittest.TestCase):
    """UKG Pro Recruiting, formerly UltiPro. `code|boardGuid`, both required."""

    GUID = "c0ae7303-ee90-41c6-b44a-abf63303ceb4"

    def _payload(self, total, *opps):
        return json.dumps({"opportunities": list(opps), "totalCount": total})

    def _opp(self, job_id, title="Quant Researcher", places=("Tampa, FL",)):
        return {
            "Id": job_id,
            "Title": title,
            "JobCategoryName": "Data",
            "PostedDate": "2026-08-13T20:15:11.282Z",
            "Locations": [{"LocalizedDescription": p} for p in places],
        }

    def test_the_token_carries_customer_code_and_board(self):
        hit = ats.fingerprint(
            f"https://recruiting.ultipro.com/FIN1008FICT/JobBoard/{self.GUID}/?q="
        )
        self.assertEqual(hit[0], "ukg")
        self.assertEqual(hit[1], f"FIN1008FICT|{self.GUID}")

    def test_a_half_token_is_refused(self):
        with self.assertRaises(ValueError):
            extract.ukg("FIN1008FICT")

    def test_it_pages_and_stops_on_a_short_page(self):
        full = [self._opp(str(n)) for n in range(extract._UKG_PAGE)]
        pages = [
            self._payload(extract._UKG_PAGE + 1, *full),
            self._payload(extract._UKG_PAGE + 1, self._opp("x")),
        ]
        with mock.patch.object(extract.http, "post_json",
                               side_effect=[p.encode() for p in pages]) as post:
            jobs = extract.ukg(f"code|{self.GUID}")
        self.assertEqual(len(jobs), extract._UKG_PAGE + 1)
        self.assertEqual(post.call_count, 2)

    def test_two_sites_are_both_named(self):
        with mock.patch.object(
            extract.http,
            "post_json",
            return_value=self._payload(1, self._opp("1", places=("Tampa, FL", "Hong Kong"))).encode(),
        ):
            self.assertEqual(extract.ukg(f"code|{self.GUID}")[0].location, "Tampa, FL, Hong Kong")

    def test_a_shortfall_against_the_advertised_total_is_loud(self):
        with mock.patch.object(
            extract.http, "post_json", return_value=self._payload(50, self._opp("1")).encode()
        ):
            with self.assertRaises(ValueError):
                extract.ukg(f"code|{self.GUID}")


class EveryFingerprintHasAReaderTest(unittest.TestCase):
    """The gap Stage 14 exists to close, pinned for the whole table.

    `ats.py` once recognised 22 systems while `extract.py` read 11, so 88
    boards sat tier A with a token, counted as resolved everywhere and polling
    nothing. Anything deliberately unread is named here with its reason, so
    adding a pattern without a reader fails rather than going quiet.
    """

    INVESTIGATED = {
        "taleo": "needs a per-board portal id it does not publish; tokens collide on tbe.taleo.net",
        "eightfold": "the jobs path is inside a JS bundle; /api/apply/v2/jobs returns page config",
        "join": "every page/pageSize value tried returns HTTP 422",
        "successfactors": "career site is a 206 KB shell with no job id, RSS path 404s",
        "jobylon": "board token is a CDN host on every row sampled",
        "emply": "career.emply.com is shared by every tenant; no per-board token",
    }

    def test_every_pattern_is_read_or_named_as_investigated(self):
        for name, _ in ats.ATS_PATTERNS:
            with self.subTest(ats=name):
                if name in extract.EXTRACTORS:
                    continue
                self.assertIn(
                    name,
                    self.INVESTIGATED,
                    f"{name} is fingerprinted, unread, and undocumented -- "
                    "either write a reader or record why there is none",
                )
