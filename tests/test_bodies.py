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

from quantscraper import bodies, db, tagging


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


class WritesBothHalvesTest(unittest.TestCase):
    """Either half of a fetch may be missing and neither may blank the other."""

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
        bodies._write(connection, [(None, "Boston, MA", "workday", "acme|wd3|X", "/1")])
        row = connection.execute(
            "SELECT description, location FROM jobs").fetchone()
        self.assertEqual(row["description"], "held")
        self.assertEqual(row["location"], "Boston, MA")

    def test_a_body_alone_does_not_blank_the_location(self):
        connection = self._connection()
        bodies._write(connection, [("new text", None, "workday", "acme|wd3|X", "/1")])
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
        bodies._write(connection, [("a description", None, "jobbsafari", "sweden", "1")])
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
        bodies._write(connection, [("a description", None, "jobbsafari", "sweden", "1")])
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
