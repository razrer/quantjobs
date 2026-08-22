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
                body = bodies.jobbsafari_body(
                    self._row("https://jobbsafari.se/jobb/analytiker-abcde-99"))
        self.assertEqual(body, "Vi söker en analytiker.")
        self.assertEqual(
            seen,
            ["https://jobbsafari.se/_next/data/B/sv-SE/jobb/analytiker-abcde-99.json"])

    def test_a_posting_with_no_usable_url_is_skipped_rather_than_guessed(self):
        for url in (None, "", "https://jobbsafari.se/lediga-jobb"):
            with self.subTest(url=url):
                self.assertIsNone(bodies.jobbsafari_body(self._row(url)))

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
                    bodies.jobbsafari_body(self._row("https://jobbsafari.se/jobb/a-1")),
                    "text here")

    def test_a_posting_the_board_has_dropped_returns_nothing(self):
        with mock.patch.object(bodies.jobbsafari, "build_id", return_value="B/sv-SE"):
            with mock.patch.object(bodies.http, "get_text",
                                   return_value=json.dumps({"pageProps": {}})):
                self.assertIsNone(
                    bodies.jobbsafari_body(self._row("https://jobbsafari.se/jobb/a-1")))


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
        self.assertIsNone(bodies.workday_body(self._row("acme", "/job/1")))
        self.assertIsNone(bodies.workday_body(self._row("acme|wd3|External", "")))


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
        bodies._write(connection, [("a description", "jobbsafari", "sweden", "1")])
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
        bodies._write(connection, [("a description", "jobbsafari", "sweden", "1")])
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
