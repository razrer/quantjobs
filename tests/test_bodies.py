"""Regression tests for Layer 3C, the description backfill.

The thing to get wrong here is how a posting is *addressed*. Workday takes
`token` plus the `externalPath` it stores as `job_id`; Jobbsafari takes the
slug, which is only in `jobs.url` and cannot be rebuilt from the id -- both
`/jobb/{id}` and `/jobb/x-{id}` answer 404. So the fetchers take the whole row,
and `targets` has to select the column they read.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from unittest import mock

from quantscraper import bodies, db, iesjobs, tagging


def _memory(test: unittest.TestCase) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    test.addCleanup(connection.close)
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA)
    connection.executescript(tagging.SCHEMA)
    return connection


def _posting(connection, ats, token, job_id, url, *, relevance="unknown"):
    connection.execute(
        "INSERT INTO jobs (ats, token, job_id, title, url, first_seen, last_seen)"
        " VALUES (?, ?, ?, ?, ?, '2026-08-20', '2026-08-20')",
        (ats, token, job_id, "Analyst", url),
    )
    connection.execute(
        "INSERT INTO job_tags (ats, token, job_id, dimension, value, confidence,"
        " tagger, tagged_at) VALUES (?, ?, ?, 'relevance', ?, 'weak', ?, '2026-08-20')",
        (ats, token, job_id, relevance, tagging.TAGGER),
    )
    connection.commit()


class SecondQueueTest(unittest.TestCase):
    """The placeholder queue, which does not care what the tagger decided.

    A posting reading `2 Locations` is not one the tagger failed on -- it may
    read perfectly and still sit under `unstated` on the board, because the
    list endpoint published a count where the names were. So this arm is
    filtered on the gates and on nothing else.
    """

    def _placeholder(self, connection, job_id, location, *, relevance, body=None):
        connection.execute(
            "INSERT INTO jobs (ats, token, job_id, title, location, description,"
            " url, first_seen, last_seen) VALUES ('workday', 'acme|wd3|X', ?,"
            " 'Analyst', ?, ?, NULL, '2026-08-20', '2026-08-20')",
            (job_id, location, body),
        )
        connection.execute(
            "INSERT INTO job_tags (ats, token, job_id, dimension, value,"
            " confidence, tagger, tagged_at) VALUES ('workday', 'acme|wd3|X', ?,"
            " 'relevance', ?, 'weak', ?, '2026-08-20')",
            (job_id, relevance, tagging.TAGGER),
        )
        connection.commit()

    def _ids(self, connection):
        return {row["job_id"] for row in bodies.targets(connection, 50)}

    def test_a_placeholder_is_queued_even_when_the_tagger_read_it_fine(self):
        connection = _memory(self)
        self._placeholder(connection, "/1", "2 Locations",
                          relevance="relevant", body="a full description")
        self.assertEqual(self._ids(connection), {"/1"})

    def test_a_real_place_is_not_queued_for_its_location(self):
        connection = _memory(self)
        self._placeholder(connection, "/1", "New York, NY",
                          relevance="relevant", body="a full description")
        self.assertEqual(self._ids(connection), set())

    def test_a_gated_posting_stays_out_of_both_queues(self):
        """A posting already off the board for being another profession does
        not come back by acquiring an address."""
        connection = _memory(self)
        self._placeholder(connection, "/1", "3 Locations", relevance="rejected")
        connection.execute(
            "INSERT INTO job_tags (ats, token, job_id, dimension, value,"
            " confidence, tagger, tagged_at) VALUES ('workday', 'acme|wd3|X', '/1',"
            " 'exclusion_reason', 'off_industry', 'strong', ?, '2026-08-20')",
            (tagging.TAGGER,),
        )
        connection.commit()
        self.assertEqual(self._ids(connection), set())

    def test_a_posting_in_both_queues_is_returned_once(self):
        """`UNION` rather than `UNION ALL`, or the pass fetches it twice."""
        connection = _memory(self)
        self._placeholder(connection, "/1", "2 Locations", relevance="unknown")
        self.assertEqual(
            [row["job_id"] for row in bodies.targets(connection, 50)], ["/1"])


class SpreadTest(unittest.TestCase):
    """The queue is fetched round-robin over hosts, not in the order selected.

    `http._throttle` books its interval per host, so a queue clustered by
    tenant makes a twelve-thread pool behave like a one-thread one.
    """

    def _row(self, ats, token, job_id="/1"):
        return {"ats": ats, "token": token, "job_id": job_id, "url": None,
                "location": None}

    def test_the_hosts_alternate(self):
        rows = [self._row("workday", "a|wd3|X", f"/a{i}") for i in range(3)]
        rows += [self._row("workday", "b|wd3|X", f"/b{i}") for i in range(3)]
        got = [bodies._host_of(r) for r in bodies._spread(rows)]
        self.assertEqual([h.split("//")[1].split(".")[0] for h in got],
                         ["a", "b", "a", "b", "a", "b"])

    def test_nothing_is_dropped_or_duplicated(self):
        rows = [self._row("workday", "a|wd3|X", f"/a{i}") for i in range(5)]
        rows += [self._row("workday", "b|wd3|X", "/b0")]
        rows += [self._row("jobbsafari", "sweden", "/s0")]
        spread = bodies._spread(rows)
        self.assertEqual(len(spread), len(rows))
        self.assertEqual({r["job_id"] for r in spread}, {r["job_id"] for r in rows})

    def test_each_hosts_own_order_is_kept(self):
        """Selection is `targets`' decision; this only reorders across hosts.
        A host's rows must still arrive newest-first within that host."""
        rows = [self._row("workday", "a|wd3|X", f"/a{i}") for i in range(4)]
        rows += [self._row("workday", "b|wd3|X", "/b0")]
        mine = [r["job_id"] for r in bodies._spread(rows)
                if r["job_id"].startswith("/a")]
        self.assertEqual(mine, ["/a0", "/a1", "/a2", "/a3"])

    def test_one_myworkdaysite_host_is_shared_by_every_tenant(self):
        """On that host the subdomain is a bare `wdN`, so keying on the tenant
        would spread rows that cannot be spread."""
        a = self._row("workday", "alpha|wd3|X|myworkdaysite.com")
        b = self._row("workday", "beta|wd3|Y|myworkdaysite.com")
        self.assertEqual(bodies._host_of(a), bodies._host_of(b))
        # ...and the ordinary host still separates them.
        c = self._row("workday", "alpha|wd3|X")
        d = self._row("workday", "beta|wd3|Y")
        self.assertNotEqual(bodies._host_of(c), bodies._host_of(d))

    def test_a_malformed_token_does_not_raise(self):
        """It still has to be fetched (and rejected) rather than crash the
        pass before a single request goes out."""
        self.assertEqual(bodies._host_of(self._row("workday", "acme")),
                         "workday:malformed")


class TargetsTest(unittest.TestCase):
    def test_the_queue_carries_the_url(self):
        """The Jobbsafari fetcher reads it, and a missing column reads as a
        KeyError inside a thread pool -- which is a silent zero-filled run."""
        connection = _memory(self)
        _posting(connection, "jobbsafari", "sweden", "1",
                 "https://jobbsafari.se/jobb/analytiker-abc-1")
        row = bodies.targets(connection, 10)[0]
        self.assertEqual(row["url"], "https://jobbsafari.se/jobb/analytiker-abc-1")

    def test_only_sources_with_a_fetcher_are_queued(self):
        connection = _memory(self)
        _posting(connection, "greenhouse", "firm", "1", "https://x/1")
        self.assertEqual(bodies.targets(connection, 10), [])

    def test_a_posting_the_tagger_already_placed_is_not_queued(self):
        connection = _memory(self)
        _posting(connection, "jobbsafari", "sweden", "1",
                 "https://jobbsafari.se/jobb/a-1", relevance="relevant")
        self.assertEqual(bodies.targets(connection, 10), [])


class JobbsafariBodyTest(unittest.TestCase):
    def setUp(self):
        bodies._JOBBSAFARI_DEPLOY.clear()
        self.addCleanup(bodies._JOBBSAFARI_DEPLOY.clear)

    def _row(self, url):
        return {"ats": "jobbsafari", "token": "sweden", "job_id": "1", "url": url}

    def test_the_slug_comes_off_the_stored_url(self):
        payload = json.dumps(
            {"pageProps": {"jobEntry": {"description": "<p>Vi söker en analytiker.</p>"}}}
        )
        seen = []

        def fake(url, **kwargs):
            seen.append(url)
            return payload

        with mock.patch.object(bodies.jobbsafari, "build_id", return_value="B/sv-SE"):
            with mock.patch.object(bodies.http, "get_text", side_effect=fake):
                got = bodies.jobbsafari_body(
                    self._row("https://jobbsafari.se/jobb/analytiker-abcde-99"))
        self.assertEqual(got.description, "Vi söker en analytiker.")
        # Jobbsafari publishes one place and the list endpoint already has
        # it, so this fetcher has nothing to add to the location.
        self.assertIsNone(got.location)
        self.assertEqual(
            seen,
            ["https://jobbsafari.se/_next/data/B/sv-SE/jobb/analytiker-abcde-99.json"])

    def test_a_posting_with_no_usable_url_is_skipped_rather_than_guessed(self):
        for url in (None, "", "https://jobbsafari.se/lediga-jobb"):
            with self.subTest(url=url):
                self.assertEqual(bodies.jobbsafari_body(self._row(url)),
                                 bodies.Fetched(None, None))

    def test_a_stale_deploy_id_is_refreshed_once(self):
        payload = json.dumps({"pageProps": {"jobEntry": {"description": "text here"}}})
        answers = [OSError("404"), payload]

        def fake(url, **kwargs):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(bodies.jobbsafari, "build_id",
                               side_effect=["STALE/sv-SE", "FRESH/sv-SE"]):
            with mock.patch.object(bodies.http, "get_text", side_effect=fake):
                self.assertEqual(
                    bodies.jobbsafari_body(
                        self._row("https://jobbsafari.se/jobb/a-1")).description,
                    "text here")

    def test_a_posting_the_board_has_dropped_returns_nothing(self):
        with mock.patch.object(bodies.jobbsafari, "build_id", return_value="B/sv-SE"):
            with mock.patch.object(bodies.http, "get_text",
                                   return_value=json.dumps({"pageProps": {}})):
                self.assertEqual(
                    bodies.jobbsafari_body(self._row("https://jobbsafari.se/jobb/a-1")),
                    bodies.Fetched(None, None))


class WorkdayBodyTest(unittest.TestCase):
    def _row(self, token, job_id):
        return {"ats": "workday", "token": token, "job_id": job_id, "url": None}

    def test_the_two_hosts_invert_the_url(self):
        payload = json.dumps({"jobPostingInfo": {"jobDescription": "<p>Body</p>"}})
        seen = []

        def fake(url, **kwargs):
            seen.append(url)
            return payload

        with mock.patch.object(bodies.http, "get_text", side_effect=fake):
            bodies.workday_body(self._row("acme|wd3|External", "/en-US/job/1"))
            bodies.workday_body(
                self._row("brevanhoward|wd3|BH_ExternalCareers|myworkdaysite.com",
                          "/en-US/job/2"))
        self.assertEqual(seen, [
            "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/External/en-US/job/1",
            "https://wd3.myworkdaysite.com/wday/cxs/brevanhoward/BH_ExternalCareers"
            "/en-US/job/2",
        ])

    def test_a_malformed_token_is_skipped(self):
        self.assertEqual(bodies.workday_body(self._row("acme", "/job/1")),
                         bodies.Fetched(None, None))
        self.assertEqual(bodies.workday_body(self._row("acme|wd3|External", "")),
                         bodies.Fetched(None, None))

    def test_the_detail_page_spells_out_what_the_list_summarised(self):
        """`2 Locations` is the largest single thing in the `hub: unknown`
        bucket and it is not a posting that named no place -- it is one that
        named several, summarised by a field too narrow to hold them."""
        payload = json.dumps({"jobPostingInfo": {
            "jobDescription": "<p>Body</p>",
            "location": "Nashville, Tennessee",
            "additionalLocations": ["New York, New York"],
        }})
        with mock.patch.object(bodies.http, "get_text", return_value=payload):
            got = bodies.workday_body(self._row("acme|wd3|External", "/job/1"))
        self.assertEqual(got.location, "Nashville, Tennessee; New York, New York")

    def test_a_repeated_location_is_published_twice_and_stored_once(self):
        """Some tenants echo `location` into `additionalLocations`, so the two
        fields must be unioned rather than concatenated."""
        payload = json.dumps({"jobPostingInfo": {
            "jobDescription": "<p>Body</p>",
            "location": "Minneapolis, Minnesota",
            "additionalLocations": ["Minneapolis, Minnesota"],
        }})
        with mock.patch.object(bodies.http, "get_text", return_value=payload):
            got = bodies.workday_body(self._row("acme|wd3|External", "/job/1"))
        self.assertEqual(got.location, "Minneapolis, Minnesota")

    def test_a_posting_with_no_places_published_yields_none(self):
        payload = json.dumps({"jobPostingInfo": {"jobDescription": "<p>Body</p>"}})
        with mock.patch.object(bodies.http, "get_text", return_value=payload):
            got = bodies.workday_body(self._row("acme|wd3|External", "/job/1"))
        self.assertEqual(got.description, "Body")
        self.assertIsNone(got.location)


class UnresolvedPlaceTest(unittest.TestCase):
    """Which stored locations this pass is allowed to overwrite.

    `N Locations` is a *count*, and the names behind it are strictly more than
    it says, so replacing it loses nothing. `Remote` is not: the detail
    endpoint answers it with the requisition's anchor office, and writing that
    would pin a remote posting to a city nobody has to travel to.
    """

    def test_the_count_is_a_placeholder(self):
        for value in ("2 Locations", "10 Locations", " 3 locations ", "1 Location"):
            with self.subTest(value=value):
                self.assertTrue(bodies._UNRESOLVED.match(value))

    def test_a_real_place_is_not(self):
        for value in ("Remote", "New York, NY", "2 Locations in Texas",
                      "Stockholm", "", "Locations"):
            with self.subTest(value=value):
                self.assertFalse(bodies._UNRESOLVED.match(value))


class WritesEveryPartTest(unittest.TestCase):
    """Any part of a fetch may be missing and none may blank another."""

    def _connection(self):
        connection = db.connect(":memory:")
        connection.executescript(tagging.SCHEMA)
        connection.execute(
            "INSERT INTO jobs (ats, token, job_id, title, location, description,"
            " first_seen, last_seen) VALUES"
            " ('workday', 'acme|wd3|X', '/1', 'Analyst', '2 Locations', 'held',"
            "  '2026-01-01', '2026-01-01')")
        return connection

    def test_a_location_alone_does_not_blank_the_body(self):
        connection = self._connection()
        bodies._write(connection, [(None, "Boston, MA", None, "workday", "acme|wd3|X", "/1")])
        row = connection.execute(
            "SELECT description, location FROM jobs").fetchone()
        self.assertEqual(row["description"], "held")
        self.assertEqual(row["location"], "Boston, MA")

    def test_a_body_alone_does_not_blank_the_location(self):
        connection = self._connection()
        bodies._write(connection, [("new text", None, None, "workday", "acme|wd3|X", "/1")])
        row = connection.execute(
            "SELECT description, location FROM jobs").fetchone()
        self.assertEqual(row["description"], "new text")
        self.assertEqual(row["location"], "2 Locations")


if __name__ == "__main__":
    unittest.main()


class RetiresStaleVerdictTest(unittest.TestCase):
    """A body that arrives after the tag must send the posting back to `tag`.

    `tagging.postings` selects postings with no row at the current version, so
    a posting classified on its title is finished as far as `tag` is concerned
    -- and a description fetched afterwards would never be read. That is how
    585 Swedish postings reached the board judged on a six-word title.
    """

    def test_current_version_tags_go(self):
        connection = _memory(self)
        _posting(connection, "jobbsafari", "sweden", "1", "https://x/jobb/a-1")
        bodies._write(connection, [("a description", None, None, "jobbsafari", "sweden", "1")])
        self.assertEqual(
            connection.execute(
                "SELECT description FROM jobs WHERE job_id = '1'"
            ).fetchone()["description"],
            "a description",
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) n FROM job_tags WHERE job_id = '1' AND tagger = ?",
                (tagging.TAGGER,),
            ).fetchone()["n"],
            0,
        )

    def test_an_older_tagger_is_left_alone(self):
        """Only the current version is retired; the history stays as it was."""
        connection = _memory(self)
        _posting(connection, "jobbsafari", "sweden", "1", "https://x/jobb/a-1")
        connection.execute(
            "INSERT INTO job_tags (ats, token, job_id, dimension, value, confidence,"
            " tagger, tagged_at) VALUES ('jobbsafari', 'sweden', '1', 'relevance',"
            " 'rejected', 'weak', ?, '2026-08-01')",
            (tagging.TAGGER - 1,),
        )
        connection.commit()
        bodies._write(connection, [("a description", None, None, "jobbsafari", "sweden", "1")])
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) n FROM job_tags WHERE job_id = '1' AND tagger = ?",
                (tagging.TAGGER - 1,),
            ).fetchone()["n"],
            1,
        )

    def test_nothing_written_touches_nothing(self):
        connection = _memory(self)
        _posting(connection, "jobbsafari", "sweden", "1", "https://x/jobb/a-1")
        bodies._write(connection, [])
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) n FROM job_tags WHERE tagger = ?", (tagging.TAGGER,)
            ).fetchone()["n"],
            1,
        )


class SuccessFactorsBodyTest(unittest.TestCase):
    """991 of the board's 2,298 body-less unread cards were this source, more
    than any other -- its list page carries a title, a place and a department
    and no prose at all."""

    PAGE = (
        '<div class="jobDisplayShell" itemscope itemtype="http://schema.org/JobPosting">'
        '<span itemprop="jobLocation" itemscope><span itemprop="address" itemscope>'
        '<meta itemprop="addressLocality" content="Wiesbaden">'
        '<meta itemprop="addressRegion" content="HE">'
        '<meta itemprop="addressCountry" content="DE"></span></span>'
        '<div class="job"><span itemprop="description" class="jobdescription">'
        "<p>Wir suchen einen <b>Quantitative Analyst</b>.</p></span></div></div>"
    )

    def _row(self, url="https://careers.deka.de/job/Wiesbaden-Analyst/1/"):
        return {"ats": "successfactors", "token": "careers.deka.de",
                "job_id": "1", "url": url}

    def test_the_description_and_the_place_both_come_off_the_page(self):
        with mock.patch.object(bodies.http, "get_text", return_value=self.PAGE):
            got = bodies.successfactors_body(self._row())
        self.assertEqual(got.description, "Wir suchen einen Quantitative Analyst .")
        self.assertEqual(got.location, "Wiesbaden, HE, DE")

    def test_the_other_microdata_shape(self):
        """Tenants disagree: AkzoNobel and Scania write one `streetAddress`
        where DekaBank and NordLB write three separate fields."""
        page = self.PAGE.replace(
            '<meta itemprop="addressLocality" content="Wiesbaden">'
            '<meta itemprop="addressRegion" content="HE">'
            '<meta itemprop="addressCountry" content="DE">',
            '<meta itemprop="streetAddress" content="Groningen, NL, 9723 BW">',
        )
        with mock.patch.object(bodies.http, "get_text", return_value=page):
            self.assertEqual(
                bodies.successfactors_body(self._row()).location,
                "Groningen, NL, 9723 BW")

    def test_a_page_with_neither_yields_nothing_rather_than_raising(self):
        with mock.patch.object(bodies.http, "get_text", return_value="<html></html>"):
            self.assertEqual(bodies.successfactors_body(self._row()),
                             bodies.Fetched(None, None))


class IcimsBodyTest(unittest.TestCase):
    """The classic portal publishes a title reconstructed from a URL slug and
    nothing else -- no location at all, so 1,824 postings sit at `hub:
    unknown`. The frame it renders for a job carries a schema.org island."""

    def _page(self, extra=""):
        posting = json.dumps({
            "@type": "JobPosting",
            "description": "<p>Credit investing associate.</p>",
            "jobLocation": [{"address": {
                "addressLocality": "Dallas", "addressRegion": "TX",
                "addressCountry": "US"}}],
        })
        return (f'{extra}<script type="application/ld+json">{posting}</script>')

    def _row(self):
        return {"ats": "icims", "token": "affiniuscapital", "job_id": "2276",
                "url": "https://careers-affiniuscapital.icims.com/jobs/2276/a/job"}

    def test_the_frame_parameter_is_what_carries_the_island(self):
        seen = []

        def fake(url, **kwargs):
            seen.append(url)
            return self._page()

        with mock.patch.object(bodies.http, "get_text", side_effect=fake):
            got = bodies.icims_body(self._row())
        self.assertEqual(
            seen, ["https://careers-affiniuscapital.icims.com/jobs/2276/a/job"
                   "?in_iframe=1"])
        self.assertEqual(got.description, "Credit investing associate.")
        self.assertEqual(got.location, "Dallas, TX, US")

    def test_a_second_island_does_not_hide_the_posting(self):
        """A page may carry a breadcrumb or an organisation island too, and a
        malformed one must not cost the description."""
        page = self._page(
            '<script type="application/ld+json">{"@type": "BreadcrumbList"}</script>'
            '<script type="application/ld+json">{not json,}</script>')
        with mock.patch.object(bodies.http, "get_text", return_value=page):
            self.assertEqual(bodies.icims_body(self._row()).description,
                             "Credit investing associate.")


class OracleBodyTest(unittest.TestCase):
    def _row(self):
        return {"ats": "oracle_hcm", "token": "edix.fa.us2.oraclecloud.com|CX_1",
                "job_id": "8067", "url": None}

    def test_the_site_number_is_required_as_well_as_the_id(self):
        """`CX_1001` is Oracle's default and most tenants keep it, so an id
        alone is ambiguous across sites on one pod -- the same both-halves
        rule `ats.py` records about the token."""
        seen = []

        def fake(url, **kwargs):
            seen.append(url)
            return json.dumps({"items": [{
                "ExternalDescriptionStr": "<p>General Purpose:</p>",
                "ExternalQualificationsStr": "<p>Five years.</p>",
                "PrimaryLocation": "Shenzhen, China",
            }]})

        with mock.patch.object(bodies.http, "get_text", side_effect=fake):
            got = bodies.oracle_hcm_body(self._row())
        self.assertIn("siteNumber=CX_1", seen[0])
        self.assertIn('Id="8067"', seen[0])
        self.assertEqual(got.description, "General Purpose: Five years.")
        self.assertEqual(got.location, "Shenzhen, China")

    def test_a_token_missing_its_site_is_not_guessed_at(self):
        row = dict(self._row(), token="edix.fa.us2.oraclecloud.com")
        self.assertEqual(bodies.oracle_hcm_body(row), bodies.Fetched(None, None))


class SmartRecruitersBodyTest(unittest.TestCase):
    def _row(self):
        return {"ats": "smartrecruiters", "token": "BoschGroup",
                "job_id": "744000143462790", "url": None}

    def test_the_company_blurb_is_left_out(self):
        """It is the firm describing itself, which is the one kind of text
        `lexicon.judge` is built to keep out of a decision about the role."""
        payload = json.dumps({"jobAd": {"sections": {
            "companyDescription": {"text": "<p>Bei Bosch gestalten wir Zukunft.</p>"},
            "jobDescription": {"text": "<p>Serviceprozesse optimieren.</p>"},
            "qualifications": {"text": "<p>Abgeschlossenes Studium.</p>"},
            "videos": {"text": None},
        }}})
        with mock.patch.object(bodies.http, "get_text", return_value=payload):
            got = bodies.smartrecruiters_body(self._row())
        self.assertEqual(got.description,
                         "Serviceprozesse optimieren. Abgeschlossenes Studium.")
        self.assertIsNone(got.location)


class PlacesIsASubsetTest(unittest.TestCase):
    def test_every_placer_has_a_fetcher(self):
        self.assertTrue(bodies.PLACES <= set(bodies.FETCHERS))

    def test_a_fetcher_that_cannot_answer_where_is_not_queued_for_it(self):
        """Jobbsafari and SmartRecruiters return `Fetched(body, None)` and
        always will. Queue two exists to fix a location."""
        self.assertNotIn("jobbsafari", bodies.PLACES)
        self.assertNotIn("smartrecruiters", bodies.PLACES)


class AHostilePayloadEndsThePostingNotThePassTest(unittest.TestCase):
    """An exception raised inside a fetcher does not cost one posting -- it
    propagates out of `pool.map`, ends the loop, and discards the batch of up
    to a hundred rows already fetched and not yet written. Batching exists so
    tens of minutes of network work survives one bad answer.

    A blanket `try` around `work()` is deliberately *not* the fix: a missing
    column must still raise, or a schema change reads as a zero-filled run --
    see `TargetsTest`. So each fetcher shape-checks its own payload instead.
    """

    SHAPES = ("[]", '"a string"', "null", '{"items": "not a list"}',
              '{"items": [7]}', '{"jobAd": "not a dict"}',
              '{"jobAd": {"sections": []}}', "{}")

    def test_oracle_survives_every_shape(self):
        row = {"ats": "oracle_hcm", "token": "pod|CX_1", "job_id": "1", "url": None}
        for payload in self.SHAPES:
            with self.subTest(payload=payload):
                with mock.patch.object(bodies.http, "get_text", return_value=payload):
                    self.assertEqual(bodies.oracle_hcm_body(row),
                                     bodies.Fetched(None, None))

    def test_smartrecruiters_survives_every_shape(self):
        row = {"ats": "smartrecruiters", "token": "acme", "job_id": "1", "url": None}
        for payload in self.SHAPES:
            with self.subTest(payload=payload):
                with mock.patch.object(bodies.http, "get_text", return_value=payload):
                    self.assertEqual(bodies.smartrecruiters_body(row),
                                     bodies.Fetched(None, None))

    def test_icims_survives_a_malformed_island(self):
        row = {"ats": "icims", "token": "acme", "job_id": "1",
               "url": "https://careers-acme.icims.com/jobs/1/a/job"}
        for page in ('<script type="application/ld+json">[1, 2]</script>',
                     '<script type="application/ld+json">"text"</script>',
                     '<script type="application/ld+json">{"@type":"JobPosting",'
                     '"jobLocation":"nope"}</script>',
                     "<html></html>"):
            with self.subTest(page=page[:40]):
                with mock.patch.object(bodies.http, "get_text", return_value=page):
                    self.assertIsNone(bodies.icims_body(row).location)


class IesHarvestTest(unittest.TestCase):
    """Hong Kong's card tokens, minted twenty to a page instead of one at a time.

    The saving is the whole reason this pass exists: `www2.jobs.gov.hk` is four
    seconds a request and the search route spends two of them per posting, which
    measured 115 minutes on a live queue of 864 -- about three quarters of a
    `daily --full`. What is pinned here is that the cheap route is taken where it
    pays, abandoned where it does not, and that nothing is ever lost by trying.
    """

    def _row(self, job_id, category="Others"):
        return {
            "ats": "iesjobs", "token": "iesjobs", "job_id": job_id,
            "url": None, "location": "Kwai Hing", "category": category,
            "first_seen": "2026-09-01T00:00:00+00:00",
        }

    def _pages(self, mapping):
        """`{page number: {order number: card url}}` as `card_links` returns it."""
        def links(number, *, jobtype=None):
            return mapping.get(number, {})
        return links

    def test_a_page_mints_tokens_for_every_row_it_carries(self):
        rows = [self._row("A"), self._row("B")]
        pages = {1: {"A": "/card?order=aaa", "B": "/card?order=bbb", "C": "/card?order=ccc"}}
        read = {}

        def card(url, job_id):
            read[job_id] = url
            return bodies.Fetched("prose", None, "EMPLOYER LTD")

        with mock.patch.object(bodies.iesjobs, "card_links", self._pages(pages)), \
             mock.patch.object(bodies, "_ies_read_card", card), \
             mock.patch.object(bodies, "iesjobs_body") as search:
            got = list(bodies._iesjobs_pass(rows))

        self.assertEqual(len(got), 2)
        self.assertEqual(read, {"A": "/card?order=aaa", "B": "/card?order=bbb"})
        # One page bought both cards, so the search was never reached.
        search.assert_not_called()

    def test_a_posting_the_slice_never_shows_falls_back_to_the_search(self):
        """The fallback is the old path in full, so nothing is lost by trying.

        A posting withdrawn between the walk and this pass is simply not on any
        page any more -- which is a fact about the board, not a fault.
        """
        rows = [self._row("A"), self._row("GONE")]
        pages = {1: {"A": "/card?order=aaa"}}

        with mock.patch.object(bodies.iesjobs, "card_links", self._pages(pages)), \
             mock.patch.object(bodies, "_ies_read_card",
                               lambda url, job_id: bodies.Fetched("prose", None, "E")), \
             mock.patch.object(bodies, "iesjobs_body",
                               return_value=bodies.Fetched("searched", None, "E")) as search:
            got = list(bodies._iesjobs_pass(rows))

        self.assertEqual(len(got), 2)
        self.assertEqual([r["job_id"] for r, _ in got], ["A", "GONE"])
        self.assertEqual(got[1][1].description, "searched")
        search.assert_called_once()

    def test_a_thin_slice_is_abandoned_rather_than_walked_to_the_end(self):
        """Paging wins only while the pages spent stay below the postings found.

        `Management / Administration` wants 23 postings spread over 41 pages, so
        walking it whole costs 64 requests against the search's 46. The rule has
        to notice that and hand the rest back -- otherwise this "optimisation"
        is slower than what it replaced on exactly the slices where the wanted
        postings are rare, which is most of them.
        """
        rows = [self._row(str(n)) for n in range(3)]
        # Nothing this pass wants is on any page, so no page can ever justify
        # the next one.
        calls = []

        def links(number, *, jobtype=None):
            calls.append(number)
            return {"other-%d" % number: "/card"}

        with mock.patch.object(bodies.iesjobs, "card_links", links), \
             mock.patch.object(bodies, "_ies_read_card",
                               lambda url, job_id: bodies.Fetched("prose", None, "E")), \
             mock.patch.object(bodies, "iesjobs_body",
                               return_value=bodies.Fetched("searched", None, "E")):
            got = list(bodies._iesjobs_pass(rows))

        # It gave up after the grace and searched all three rather than paging
        # a slice that was paying for nothing.
        self.assertEqual(len(calls), bodies._IES_HARVEST_GRACE + 1)
        self.assertEqual([g.description for _, g in got], ["searched"] * 3)

    def test_an_empty_page_ends_the_slice(self):
        """Stop on an empty page, never a short one -- the walk's own rule."""
        rows = [self._row("A"), self._row("MISSING")]
        pages = {1: {"A": "/card?order=aaa"}, 2: {}}

        with mock.patch.object(bodies.iesjobs, "card_links", self._pages(pages)), \
             mock.patch.object(bodies, "_ies_read_card",
                               lambda url, job_id: bodies.Fetched("prose", None, "E")), \
             mock.patch.object(bodies, "iesjobs_body",
                               return_value=bodies.Fetched("searched", None, "E")):
            got = list(bodies._iesjobs_pass(rows))
        self.assertEqual(len(got), 2)

    def test_an_uncategorised_posting_goes_straight_to_the_search(self):
        """There is no slice to walk, and inventing one would walk the wrong board."""
        rows = [self._row("A", category=None)]
        with mock.patch.object(bodies.iesjobs, "card_links") as links, \
             mock.patch.object(bodies, "iesjobs_body",
                               return_value=bodies.Fetched("searched", None, "E")):
            got = list(bodies._iesjobs_pass(rows))
        links.assert_not_called()
        self.assertEqual(got[0][1].description, "searched")

    def test_a_failed_page_falls_back_instead_of_losing_the_slice(self):
        rows = [self._row("A")]

        def links(number, *, jobtype=None):
            raise OSError("the portal timed out")

        with mock.patch.object(bodies.iesjobs, "card_links", links), \
             mock.patch.object(bodies, "iesjobs_body",
                               return_value=bodies.Fetched("searched", None, "E")):
            got = list(bodies._iesjobs_pass(rows))
        self.assertEqual(got[0][1].description, "searched")

    def test_the_card_is_checked_against_the_row_it_was_fetched_for(self):
        """The `palmersquare.com` guard, and the expiry check in the same line.

        A card for somebody else's posting would write one firm's description
        onto another's row; an expired token answers HTTP 200 with the vacancy
        search page and no card at all. Both are the same absent-or-wrong
        `data-ordno`, and both must yield nothing rather than something.
        """
        card = '<span id="ordNo" data-ordno="RIGHT"></span><span id="empName">ACME</span>'
        with mock.patch.object(bodies.http, "get_text", return_value=card):
            self.assertEqual(bodies._ies_read_card("/u", "RIGHT").employer, "ACME")
            self.assertIsNone(bodies._ies_read_card("/u", "WRONG").employer)
        with mock.patch.object(bodies.http, "get_text", return_value="<html>search</html>"):
            self.assertIsNone(bodies._ies_read_card("/u", "RIGHT").employer)


class IesCardLinksTest(unittest.TestCase):
    """`card_links` reads the href `_job` deliberately throws away.

    `jobs.url` must stay NULL -- a stored token dies within hours and answers
    HTTP 200 with a search box, which is `CLAUDE.md`'s *worse than no link*.
    This returns the same href to a caller that spends it within the minute and
    stores none of it.
    """

    PAGE = (
        '<tr class="bg-white">'
        '<td><span class="d-flex flex-column"><span>Quantitative Analyst</span></span></td>'
        '<td><a id="1_orderNo_hyper" href="/0/en/jobseeker/jobCard/?order=tok1&amp;from=x">'
        '11-26-0000001</a></td>'
        "</tr>"
        '<tr class="bg-white">'
        '<td><span class="d-flex flex-column"><span>Clerk</span></span></td>'
        '<td><a id="2_orderNo_hyper" href="/0/en/jobseeker/jobCard/?order=tok2">'
        "11-26-0000002</a></td>"
        "</tr>"
    )

    def test_it_pairs_every_order_number_with_its_own_link(self):
        with mock.patch.object(iesjobs.http, "get_text", return_value=self.PAGE):
            links = iesjobs.card_links(1, jobtype=17)
        self.assertEqual(
            links,
            {
                "11-26-0000001":
                    "https://www2.jobs.gov.hk/0/en/jobseeker/jobCard/?order=tok1&from=x",
                "11-26-0000002":
                    "https://www2.jobs.gov.hk/0/en/jobseeker/jobCard/?order=tok2",
            },
        )

    def test_the_entity_in_the_href_is_unescaped(self):
        """`&amp;` in an attribute is one ampersand, and `from=` is a real parameter."""
        with mock.patch.object(iesjobs.http, "get_text", return_value=self.PAGE):
            links = iesjobs.card_links(1, jobtype=17)
        self.assertNotIn("&amp;", links["11-26-0000001"])

    def test_it_asks_for_the_slice_and_the_page_it_was_given(self):
        seen = {}

        def get_text(url, **kwargs):
            seen["url"] = url
            return ""

        with mock.patch.object(iesjobs.http, "get_text", get_text):
            iesjobs.card_links(3, jobtype=17)
        self.assertEqual(
            seen["url"],
            "https://www2.jobs.gov.hk/0/en/jobseeker/jobsearch/joblist/jobtype/17/?page=3",
        )


class RunMergesBothQueuesTest(unittest.TestCase):
    """`run` drives two fetch strategies at once and writes from one thread.

    Hong Kong is one host at four seconds a request, so it is walked
    sequentially by `_iesjobs_pass` while every other source goes through the
    thread pool. The two produce into a queue and the *caller's* thread does all
    the writing, because `db.connect` hands out a connection bound to the thread
    that made it. What is pinned here is that both queues land, that the
    counters cover both, and that a fetcher raising still ends the pass loudly.
    """

    def _connection(self):
        connection = _memory(self)
        connection.executemany(
            "INSERT INTO jobs (ats, token, job_id, title, url, location,"
            " category, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, '2026-09-01', '2026-09-01')",
            [
                ("iesjobs", "iesjobs", "HK1", "Clerk", None, "Kwai Hing", "Others"),
                ("workday", "acme|wd1|X", "/job/1", "Analyst", None, "2 Locations", None),
            ],
        )
        connection.commit()
        return connection

    def _targets(self, connection):
        return connection.execute(
            "SELECT ats, token, job_id, url, location, category, first_seen"
            " FROM jobs ORDER BY ats"
        ).fetchall()

    def test_both_sources_are_fetched_and_counted(self):
        connection = self._connection()
        rows = self._targets(connection)

        with mock.patch.object(bodies, "targets", return_value=rows), \
             mock.patch.dict(bodies.FETCHERS, {
                 "workday": lambda row: bodies.Fetched("wd body", "Stockholm", None),
             }), \
             mock.patch.object(bodies, "_iesjobs_pass") as hk:
            hk.side_effect = lambda rows, stats=None: iter(
                [(rows[0], bodies.Fetched("hk body", None, "ACME LTD"))]
            )
            attempted, filled, placed, named, routes = bodies.run(
                connection, 10, workers=2
            )

        self.assertEqual(attempted, 2)
        self.assertEqual(filled, 2)
        self.assertEqual(placed, 1)   # only Workday answered a location
        self.assertEqual(named, 1)    # only Hong Kong answers an employer
        self.assertIn("harvested", routes)
        stored = dict(
            connection.execute(
                "SELECT job_id, description FROM jobs ORDER BY job_id"
            ).fetchall()
        )
        self.assertEqual(stored["HK1"], "hk body")
        self.assertEqual(stored["/job/1"], "wd body")

    def test_a_fetcher_that_raises_still_ends_the_pass(self):
        """A missing column must not read as a zero-filled run.

        The producers run on their own threads now, so an exception no longer
        propagates out of `pool.map` on its own -- it is carried across the
        boundary and re-raised here, after the rows already fetched have been
        committed.
        """
        connection = self._connection()
        rows = self._targets(connection)

        def explode(row):
            raise KeyError("last_seen")

        with mock.patch.object(bodies, "targets", return_value=rows), \
             mock.patch.dict(bodies.FETCHERS, {"workday": explode}), \
             mock.patch.object(bodies, "_iesjobs_pass") as hk:
            hk.side_effect = lambda rows, stats=None: iter(
                [(rows[0], bodies.Fetched("hk body", None, "ACME LTD"))]
            )
            with self.assertRaises(KeyError):
                bodies.run(connection, 10, workers=2)

        # The Hong Kong row it did reach was still committed before the raise.
        self.assertEqual(
            connection.execute(
                "SELECT description FROM jobs WHERE job_id = 'HK1'"
            ).fetchone()[0],
            "hk body",
        )


class HongKongQueueIsInvertedTest(unittest.TestCase):
    """Hong Kong asks the opposite question of every other source.

    Everywhere else `targets` fetches a body for a posting the tagger could
    **not** place, because a description resolves it. That is measured and it
    holds -- corpus-wide a posting with a body stays `unknown` 1.0% of the time
    and one without 9.3%.

    It does not hold here. Of 1,028 iesjobs postings whose description had been
    fetched, exactly **one** came out rated above `unknown` and **718 were
    still `unknown`** -- because 44% of those descriptions are majority-Chinese
    and this lexicon is English, Swedish and Danish. So the old queue spent
    about 72 minutes a week, three quarters of a `daily --full`, fetching prose
    nothing downstream reads.

    What the card is still wanted for is the **employer**, which the portal
    publishes nowhere on either list view. So the queue keeps the postings
    where a name is worth a request: the ones already rated.
    """

    def _connection(self, rows):
        connection = _memory(self)
        connection.executemany(
            "INSERT INTO jobs (ats, token, job_id, title, description, employer,"
            " location, category, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, 'Kwai Hing', 'Others',"
            " '2026-09-01', '2026-09-01')",
            [(ats, ats, job_id, "Some Title", body, employer)
             for ats, job_id, body, employer in rows],
        )
        connection.executemany(
            "INSERT INTO job_tags (ats, token, job_id, dimension, value,"
            " confidence, evidence, tagger, tagged_at)"
            " VALUES (?, ?, ?, 'relevance', ?, 'weak', NULL, ?, '2026-09-01')",
            [(ats, ats, job_id, verdict, tagging.TAGGER)
             for (ats, job_id, _, _), verdict in zip(rows, self.VERDICTS)],
        )
        connection.commit()
        return connection

    ROWS = [
        ("iesjobs", "HK-UNREAD", None, None),
        ("iesjobs", "HK-RATED", None, None),
        ("iesjobs", "HK-RATED-NAMED", "prose", "ACME LTD"),
        ("workday", "/WD-UNREAD", None, None),
    ]
    VERDICTS = ["unknown", "relevant", "relevant", "unknown"]

    def _queued(self):
        connection = self._connection(self.ROWS)
        return {row["job_id"] for row in bodies.targets(connection, 100)}

    def test_an_unreadable_hong_kong_card_is_not_fetched(self):
        """The 864-row queue that cost 72 minutes a week and bought one card."""
        self.assertNotIn("HK-UNREAD", self._queued())

    def test_a_rated_hong_kong_card_is_fetched_for_its_employer(self):
        """Five of the six positives were found on the title with no body.

        They still need a name on the card, and the portal prints one only
        there -- so these are the rows worth a request.
        """
        self.assertIn("HK-RATED", self._queued())

    def test_a_rated_card_that_already_has_both_is_left_alone(self):
        self.assertNotIn("HK-RATED-NAMED", self._queued())

    def test_every_other_source_still_asks_the_original_question(self):
        """The inversion is Hong Kong's alone, and nothing else may inherit it.

        Singapore's `unknown` bucket was measured the other way round -- a
        vocabulary gap holding real work, only 8% of it missing a description.
        """
        self.assertIn("/WD-UNREAD", self._queued())
