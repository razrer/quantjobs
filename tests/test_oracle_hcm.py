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
import urllib.error
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
    def test_a_short_page_is_not_the_end_of_the_board(self):
        """Oracle serves the occasional short page in the middle of a board.

        Measured on Kotak's tenant: offset 3,000 hands back 199 rows and
        offset 3,200 hands back a full 200. Stopping on a short page ended the
        walk wherever one landed -- Kotak truncated at 3,199 of 9,959 and Tata
        Capital at 1,599 of 5,542, both the round number a cap leaves behind.
        The Jobbsafari lesson in a second format: only an empty page is the end.
        """
        short = [_req(f"s{n}") for n in range(extract._ORACLE_PAGE - 1)]
        rest = [_req(f"r{n}") for n in range(extract._ORACLE_PAGE)]
        pages = [
            _payload(2 * extract._ORACLE_PAGE - 1, *short),
            _payload(2 * extract._ORACLE_PAGE - 1, *rest),
            _payload(0),
        ]
        with mock.patch.object(extract.http, "get_text", side_effect=pages) as fetch:
            jobs = extract.oracle_hcm("pod.example|CX_1001")

        self.assertEqual(len(jobs), 2 * extract._ORACLE_PAGE - 1)
        self.assertEqual(fetch.call_count, 3)
        self.assertIn("offset=0", fetch.call_args_list[0].args[0])
        self.assertIn(f"offset={extract._ORACLE_PAGE}", fetch.call_args_list[1].args[0])

    def test_a_tenant_that_ignores_offset_does_not_page_forever(self):
        """The guard the short-page stop used to provide by accident."""
        with mock.patch.object(
            extract.http, "get_text", return_value=_payload(1, _req("1"))
        ) as fetch:
            jobs = extract.oracle_hcm("pod.example|CX_1001")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)

    def test_a_board_handing_over_less_than_it_advertises_is_loud(self):
        """The board states its own size, so a truncation cannot be silent.

        This is the check that caught Jobvite's missing slash: a round number
        is what a cap looks like from the outside and nothing else says so.
        """
        pages = [_payload(500, _req("1")), _payload(500)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            with self.assertRaises(ValueError) as caught:
                extract.oracle_hcm("pod.example|CX_1001")
        self.assertIn("advertises 500", str(caught.exception))

    def test_a_handful_of_postings_closing_mid_walk_is_not_a_truncation(self):
        """BNY advertises 1,390 and hands over 1,387, and that is not a bug.

        A board large enough to take minutes to read changes while it is being
        read. Raising on the difference threw away 1,387 real postings -- the
        guard against silent truncation deleting a board outright, which is
        the failure it exists to prevent, one direction over.
        """
        rows = [_req(str(n)) for n in range(99)]
        pages = [_payload(100, *rows), _payload(100)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            self.assertEqual(len(extract.oracle_hcm("pod.example|CX_1001")), 99)

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
        ghosts = [_req(str(n), title="Ghost") for n in range(50)]
        for ghost in ghosts:
            ghost["Id"] = ""
        pages = [_payload(50, *ghosts), _payload(50)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
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
        """This is not hypothetical -- it caught the reader truncating.

        The first version read one page and five boards raised
        "advertises 174, read 20". ADP caps a request at 20 and ignores `$top`,
        so `$skip` is the only way through a board.
        """
        with mock.patch.object(
            extract.http, "get_text", return_value=self._payload(9, self._req("1"))
        ):
            with self.assertRaises(ValueError):
                extract.adp("cid")

    def test_it_pages_with_skip_and_omits_it_on_the_first_request(self):
        """`$skip=0` returns 19 rows where the bare URL returns 20.

        Enough of a difference that a short-page stop rule ends the walk on the
        first page, which is how this was found.
        """
        first = self._payload(3, *[self._req(str(n)) for n in range(2)])
        second = self._payload(3, self._req("9"))
        third = self._payload(3)
        with mock.patch.object(
            extract.http, "get_text", side_effect=[first, second, third]
        ) as fetch:
            jobs = extract.adp("cid")
        self.assertEqual(len(jobs), 3)
        self.assertNotIn("$skip", fetch.call_args_list[0].args[0])
        self.assertIn(f"$skip={extract._ADP_PAGE}", fetch.call_args_list[1].args[0])

    def test_a_tenant_ignoring_skip_terminates(self):
        """Serving page one forever is what an empty-page rule never catches."""
        same = self._payload(1, self._req("1"))
        with mock.patch.object(extract.http, "get_text", return_value=same) as fetch:
            jobs = extract.adp("cid")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(fetch.call_count, 2)


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
        with self._on_first_host(), mock.patch.object(
            extract.http, "post_json", side_effect=[p.encode() for p in pages]
        ) as post:
            jobs = extract.ukg(f"code|{self.GUID}")
        self.assertEqual(len(jobs), extract._UKG_PAGE + 1)
        self.assertEqual(post.call_count, 2)

    def test_two_sites_are_both_named(self):
        with self._on_first_host(), mock.patch.object(
            extract.http,
            "post_json",
            return_value=self._payload(1, self._opp("1", places=("Tampa, FL", "Hong Kong"))).encode(),
        ):
            self.assertEqual(extract.ukg(f"code|{self.GUID}")[0].location, "Tampa, FL, Hong Kong")

    def test_a_shortfall_against_the_advertised_total_is_loud(self):
        with self._on_first_host(), mock.patch.object(
            extract.http, "post_json", return_value=self._payload(50, self._opp("1")).encode()
        ):
            with self.assertRaises(ValueError):
                extract.ukg(f"code|{self.GUID}")

    # --- the two hosts ------------------------------------------------------
    #
    # UKG serves its tenants from `recruiting.ultipro.com` and
    # `recruiting2.ultipro.com`, and a tenant is on exactly one: the other
    # answers 404. This reader addressed the first unconditionally, and every
    # one of the eight boards it could not read had `recruiting2` written in
    # its own stored evidence -- Mesirow Financial and Calamos, both Chicago,
    # among them. Same shape as Workday's two hosts.

    def _on_first_host(self):
        return mock.patch.object(extract.http, "get")

    def _404(self, url, **kwargs):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    def test_a_tenant_on_the_second_host_is_read_rather_than_missed(self):
        def answer(url, **kwargs):
            if url.startswith("https://recruiting.ultipro.com/"):
                self._404(url, **kwargs)
            return b""

        with mock.patch.object(extract.http, "get", side_effect=answer),                 mock.patch.object(
                    extract.http,
                    "post_json",
                    return_value=self._payload(1, self._opp("1")).encode(),
                ) as post:
            jobs = extract.ukg(f"code|{self.GUID}")
        self.assertEqual(len(jobs), 1)
        self.assertTrue(
            post.call_args.args[0].startswith("https://recruiting2.ultipro.com/")
        )

    def test_a_board_missing_from_both_hosts_is_still_loud(self):
        with mock.patch.object(extract.http, "get", side_effect=self._404):
            with self.assertRaises(urllib.error.HTTPError):
                extract.ukg(f"code|{self.GUID}")


class EmplyTest(unittest.TestCase):
    """The Danish ATS that was recorded as unreadable and is not.

    The board page is 209 KB of chrome with no job id in it, which is why it
    was closed -- and the list is one POST that the page itself names, beside
    the exact body it sends. `/api/integration/vacancy/get-page`, read off the
    site rather than guessed, which is the rule job-room.ch's 401 established.
    """

    SECTION = "aff9dd90-0140-46de-af0b-1b3b49c47453"

    def _board(self, language="en-GB"):
        return (
            f"<script>var languageKey = '{language}';"
            f" var config = {{ sectionId: '{self.SECTION}' }};</script>"
        )

    @staticmethod
    def _payload(count, *vacancies):
        return json.dumps({"count": count, "vacancies": list(vacancies)}).encode()

    @staticmethod
    def _vacancy(vid, title="Investment Intern", **extra):
        row = {
            "id": vid,
            "title": title,
            "titleAsUrl": "investment-intern",
            "shortId": "px827o",
            "location": "Regeringsgatan 25, 111 53, Stockholm, Sweden",
            "department": "Sweden",
            "published": "2026-08-24T06:35:08Z",
            "deadline": "2026-09-20T21:59:00Z",
            "translations": [{"content": "<p>Real estate equity.</p>"}],
        }
        row.update(extra)
        return row

    def test_it_reads_the_section_from_the_page_and_maps_the_fields(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=self._board()
        ), mock.patch.object(
            extract.http,
            "post_json",
            side_effect=[self._payload(1, self._vacancy("a")), self._payload(1)],
        ) as post:
            jobs = extract.emply("urbanpartners")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "Regeringsgatan 25, 111 53, Stockholm, Sweden")
        self.assertEqual(jobs[0].description, "Real estate equity.")
        self.assertEqual(
            jobs[0].url,
            "https://urbanpartners.career.emply.com/ad/investment-intern/px827o",
        )
        self.assertEqual(json.loads(post.call_args.args[1])["sectionId"], self.SECTION)

    def test_a_published_closing_date_is_mapped(self):
        """Checked before it was mapped: 54 of 95 postings carry one and the
        gaps from publication run 14 to 45 days with nothing repeating. That is
        an employer typing a date, not job-room.ch's dropdown, where 81% sat
        exactly 30 days out."""
        with mock.patch.object(
            extract.http, "get_text", return_value=self._board()
        ), mock.patch.object(
            extract.http,
            "post_json",
            side_effect=[self._payload(1, self._vacancy("a")), self._payload(1)],
        ):
            self.assertEqual(extract.emply("x")[0].deadline, "2026-09-20T21:59:00Z")

    def test_the_sites_own_language_is_asked_for(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=self._board("da-DK")
        ), mock.patch.object(
            extract.http, "post_json", side_effect=[self._payload(0)]
        ) as post:
            extract.emply("guldborgsund")
        self.assertEqual(json.loads(post.call_args.args[1])["langCode"], "da-DK")

    def test_a_board_naming_no_section_is_loud(self):
        with mock.patch.object(extract.http, "get_text", return_value="<html></html>"):
            with self.assertRaises(ValueError):
                extract.emply("x")

    def test_a_shortfall_against_the_advertised_total_is_loud(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=self._board()
        ), mock.patch.object(
            extract.http,
            "post_json",
            side_effect=[self._payload(9, self._vacancy("a")), self._payload(9)],
        ):
            with self.assertRaises(ValueError):
                extract.emply("x")


class JoinTest(unittest.TestCase):
    """The API 422s and the company page carries the whole list.

    The same shape as DRW's `__NEXT_DATA__` and Jobylon's widget: when a
    vendor's API refuses, read the page the customer publishes.
    """

    @staticmethod
    def _page(total, page_count, *items):
        island = {
            "items": list(items),
            "pagination": {
                "page": 1,
                "pageCount": page_count,
                "pageSize": len(items),
                "perPage": 5,
                "total": total,
            },
        }
        return '<script>{"a":1,"jobs":' + json.dumps(island) + "}</script>"

    @staticmethod
    def _item(item_id, title="Java Software Engineer"):
        return {
            "id": item_id,
            "idParam": f"{item_id}-java-software-engineer",
            "title": title,
            "createdAt": "2026-03-12T13:45:15.897Z",
            "city": {"cityName": "Vilnius", "countryName": "Lithuania"},
            "category": {"name": "Software Development"},
        }

    def test_the_island_is_read_with_its_city_and_country(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=self._page(1, 1, self._item(15842402))
        ):
            jobs = extract.join("wallee")
        self.assertEqual(jobs[0].location, "Vilnius, Lithuania")
        self.assertEqual(jobs[0].department, "Software Development")
        self.assertEqual(
            jobs[0].url,
            "https://join.com/companies/wallee/15842402-java-software-engineer",
        )

    def test_it_walks_to_the_page_count_the_island_states(self):
        pages = [
            self._page(4, 2, self._item(1), self._item(2)),
            self._page(4, 2, self._item(3), self._item(4)),
        ]
        with mock.patch.object(
            extract.http, "get_text", side_effect=pages
        ) as fetch:
            jobs = extract.join("carhartt-wip")
        self.assertEqual(len(jobs), 4)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("page=2", fetch.call_args_list[1].args[0])

    def test_a_board_counting_one_it_does_not_publish_is_not_a_truncation(self):
        """Wallee reports `total: 4` with `pageCount: 1` and lists three.

        Measured rather than generous: Carhartt's 47 arrive exactly, and a real
        truncation is short by pages rather than by one.
        """
        with mock.patch.object(
            extract.http, "get_text", return_value=self._page(4, 1, self._item(1))
        ):
            self.assertEqual(len(extract.join("wallee")), 1)

    def test_a_shortfall_of_more_than_a_page_is_loud(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=self._page(90, 1, self._item(1))
        ):
            with self.assertRaises(ValueError) as caught:
                extract.join("x")
        self.assertIn("advertises 90", str(caught.exception))

    def test_a_page_with_no_island_is_loud(self):
        with mock.patch.object(extract.http, "get_text", return_value="<html></html>"):
            with self.assertRaises(ValueError):
                extract.join("x")


class EightfoldTest(unittest.TestCase):
    """The vendor recorded as closed, where the truth is per tenant.

    The note said `/api/apply/v2/jobs` answers 403, which it does on Morgan
    Stanley's tenant and on NAB's -- and Vale's answers 200 with 193 positions,
    and **Millennium's with 219**, including `Quantitative Researcher`,
    `Portfolio Researcher` and `Deep Learning Quantitative Researcher` across
    New York, Hong Kong and Singapore. A vendor refusing one customer's board
    is not the vendor being shut, and writing it down as closed stopped anyone
    asking a second tenant.
    """

    @staticmethod
    def _payload(count, *positions):
        return json.dumps({"count": count, "positions": list(positions)})

    @staticmethod
    def _position(pid, name="Quantitative Researcher", **extra):
        row = {
            "id": pid,
            "name": name,
            "canonicalPositionUrl": f"https://mlp.eightfold.ai/careers/job/{pid}",
            "location": "Hong Kong",
            "locations": ["Hong Kong, Hong Kong", "Tokyo, Tokyo, Japan"],
            "department": "Research",
            "job_description": "Signals research.",
        }
        row.update(extra)
        return row

    def test_every_published_place_is_kept_not_just_the_summary(self):
        """The board's geography is multi-valued, and `location` is a summary.

        Vale's rows summarise as `Brazil` while `locations` names the town, and
        Millennium's summarise as `Hong Kong` while a seat is open in Tokyo too.
        """
        pages = [self._payload(1, self._position("1")), self._payload(1)]
        with mock.patch.object(extract.http, "get_text", side_effect=pages):
            jobs = extract.eightfold("mlp")
        self.assertEqual(jobs[0].location, "Hong Kong, Hong Kong, Tokyo, Tokyo, Japan")

    def test_a_stride_the_server_ignores_is_caught_by_the_total(self):
        """Eightfold serves ten however many are asked for -- the MAS trap.

        Paging fifty at a time skipped forty in every fifty, and the advertised
        total is what said so; nothing in the response did.
        """
        self.assertEqual(extract._EIGHTFOLD_PAGE, 10)
        with mock.patch.object(
            extract.http,
            "get_text",
            side_effect=[self._payload(193, self._position("1")), self._payload(193)],
        ):
            with self.assertRaises(ValueError) as caught:
                extract.eightfold("vale")
        self.assertIn("advertises 193", str(caught.exception))

    def test_it_pages_by_start_in_steps_of_ten(self):
        with mock.patch.object(
            extract.http, "get_text", return_value=self._payload(1, self._position("1"))
        ) as fetch:
            extract.eightfold("mlp")
        self.assertIn("start=0", fetch.call_args_list[0].args[0])
        self.assertIn("start=10", fetch.call_args_list[1].args[0])

    def test_the_tenant_alone_addresses_the_board(self):
        """`domain=` is what the vendor's own page sends and is not required --
        measured with it, with it empty and without it, all three answer 219."""
        hit = ats.fingerprint("https://mlp.eightfold.ai/careers")
        self.assertEqual(hit[:2], ("eightfold", "mlp"))


class JobylonTest(unittest.TestCase):
    """The Nordic ATS whose board is an Angular widget -- and whose widget page
    carries the whole list as a JavaScript array, rendered server-side.

    Read the page the embed loads, not the page that embeds it.
    """

    WIDGET = "\n".join(
        (
            "JBL.embed_v2['jobs'] = [",
            "    {",
            "      id: '374915',",
            "      url: '/jobs/374915-aktia-risk-manager/',",
            "      title: 'Risk Manager',",
            "      company: 'Aktia Pankki Oyj',",
            # Two fields are nested objects, and they sit between the id and
            # the place. A record bounded by the next `}` stops here.
            "      klass: {",
            "        'job-id-374915': true,",
            "      },",
            "      locations_text: 'Helsinki',",
            "      function: 'Pankki ja rahoitus',",
            "      to_date: '13. syyskuuta 2026',",
            "    },",
            "    {",
            "      id: '376721',",
            "      title: 'Project Manager',",
            "      klass: {",
            "        'job-id-376721': true,",
            "      },",
            "      locations_text: 'Vaasa',",
            "    },",
            "];",
        )
    )

    def test_fields_after_a_nested_object_are_still_read(self):
        """A record ends where the next begins, not at the next `}`.

        `klass` and `layers` are nested objects, so a non-greedy run to the
        first closing brace stops inside the record -- and `locations_text` is
        past that point, which is every place name on the board.
        """
        with mock.patch.object(extract.http, "get_text", return_value=self.WIDGET):
            jobs = extract.jobylon("2551")
        self.assertEqual([j.location for j in jobs], ["Helsinki", "Vaasa"])
        self.assertEqual(jobs[0].department, "Pankki ja rahoitus")
        self.assertEqual(jobs[0].employer, "Aktia Pankki Oyj")
        self.assertEqual(jobs[0].url, "https://jobylon.com/jobs/374915-aktia-risk-manager/")

    def test_a_localised_closing_date_is_not_mapped(self):
        """`to_date` is a real field rendered in the tenant's own language.

        Turning `13. syyskuuta 2026` into a date to hand a deadline-ordered
        board is the mistake this project refuses everywhere else.
        """
        with mock.patch.object(extract.http, "get_text", return_value=self.WIDGET):
            self.assertTrue(all(j.deadline is None for j in extract.jobylon("2551")))

    def test_a_missing_field_does_not_borrow_its_neighbours(self):
        with mock.patch.object(extract.http, "get_text", return_value=self.WIDGET):
            jobs = extract.jobylon("2551")
        self.assertIsNone(jobs[1].url)
        self.assertIsNone(jobs[1].department)

    def test_a_page_with_no_job_list_is_loud(self):
        with mock.patch.object(extract.http, "get_text", return_value="<html></html>"):
            with self.assertRaises(ValueError):
                extract.jobylon("2551")

    def test_the_numeric_customer_id_survives_the_not_a_board_rule(self):
        """`jobs.lever.co/500` is why numeric tokens are refused; here the
        digits are the board, and they appear in the embed URL alone."""
        hit = ats.fingerprint("https://cdn.jobylon.com/jobs/companies/2551/embed/v2/")
        self.assertEqual(hit[:2], ("jobylon", "2551"))

    def test_the_vendors_own_host_still_yields_no_token(self):
        self.assertIsNone(ats.fingerprint("https://emp.jobylon.com/")[1])


class EveryFingerprintHasAReaderTest(unittest.TestCase):
    """The gap Stage 14 exists to close, pinned for the whole table.

    `ats.py` once recognised 22 systems while `extract.py` read 11, so 88
    boards sat tier A with a token, counted as resolved everywhere and polling
    nothing. Anything deliberately unread is named here with its reason, so
    adding a pattern without a reader fails rather than going quiet.
    """

    INVESTIGATED = {
        "taleo": "needs a per-board portal id it does not publish; tokens collide on tbe.taleo.net",
    }

    def test_every_vendor_asset_rule_has_a_reader(self):
        """The second fingerprinting table, which had no guard at all.

        `_VENDOR_ASSETS` recognises a vendor from its CDN when the board is on
        the firm's own hostname -- Teamtailor and Avature. It records tier A
        with a token like any other match, so an entry with no reader is the
        same 88-board silence one table over.
        """
        for name, *_ in ats._VENDOR_ASSETS:
            with self.subTest(ats=name):
                self.assertIn(name, extract.EXTRACTORS)

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


class EmplyTokenTest(unittest.TestCase):
    """The board is the label before the vendor's `career` host, not after it."""

    def test_the_customer_label_is_the_token(self):
        hit = ats.fingerprint("https://urbanpartners.career.emply.com/open-positions")
        self.assertEqual(hit[:2], ("emply", "urbanpartners"))

    def test_the_bare_vendor_host_yields_no_token(self):
        """`career` is infrastructure, and five firms resolved to it."""
        self.assertEqual(ats.fingerprint("https://career.emply.com/x")[1], None)
