"""List polling must not undo detail enrichment."""

import sqlite3
import unittest
from dataclasses import replace

from quantscraper import db, tagging, extract
from quantscraper.models import Job


class LocationRefreshTest(unittest.TestCase):
    def setUp(self):
        self.connection = db.connect(":memory:")
        self.addCleanup(self.connection.close)

    def test_workday_poll_keeps_resolved_locations(self):
        job = Job("workday", "firm", "1", "Researcher", location="Boston; Chicago")
        for placeholder in ("2 Locations", " 3 locations ", "1 Location"):
            with self.subTest(placeholder=placeholder):
                db.upsert_jobs(self.connection, None, [job])
                db.upsert_jobs(self.connection, None, [replace(job, location=placeholder)])
                self.assertEqual(self.location(), job.location)

    def test_real_changes_and_unresolved_counts_still_refresh(self):
        for ats, before, after in (
            ("workday", "Boston", "Remote"),
            ("workday", "Boston", "New York"),
            ("workday", "2 Locations", "3 Locations"),
            ("workday", None, "3 Locations"),
            ("greenhouse", "Boston", "3 Locations"),
        ):
            with self.subTest(ats=ats, before=before, after=after):
                self.connection.execute("DELETE FROM jobs")
                job = Job(ats, "firm", "1", "Researcher", location=before)
                db.upsert_jobs(self.connection, None, [job])
                db.upsert_jobs(self.connection, None, [replace(job, location=after)])
                self.assertEqual(self.location(), after)

    def location(self):
        return self.connection.execute("SELECT location FROM jobs").fetchone()[0]

    def test_only_changed_evidence_invalidates_tags(self):
        self.connection.executescript(tagging.SCHEMA)
        job = Job("workday", "firm", "1", "Researcher", location="Boston")
        db.upsert_jobs(self.connection, None, [job])
        self.connection.execute(
            "INSERT INTO job_tags VALUES ('workday','firm','1','hub','boston',"
            "'strong','Boston',63,'2026-01-01')")
        db.upsert_jobs(self.connection, None, [replace(job, location="2 Locations")])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM job_tags").fetchone()[0], 1)
        db.upsert_jobs(self.connection, None, [replace(job, location="New York")])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM job_tags").fetchone()[0], 0)

    def test_limited_polls_rotate_and_do_not_repeat_shared_boards(self):
        self.connection.executescript("""
            CREATE TABLE ats_resolution (domain TEXT, ats TEXT, token TEXT, tier TEXT);
            INSERT INTO ats_resolution VALUES
                ('a.test', 'greenhouse', 'a', 'A'),
                ('alias.test', 'greenhouse', 'a', 'A'),
                ('b.test', 'greenhouse', 'b', 'A');
        """)
        self.assertEqual(len(extract.targets(self.connection, 10)), 2)
        first = extract.targets(self.connection, 1)[0]
        db.record_board_polls(self.connection, [(first['ats'], first['token'],
                                               first['domain'], False, 0, 'failed')])
        self.assertEqual(extract.targets(self.connection, 1)[0]['token'], 'b')


class BodiesTableTest(unittest.TestCase):
    """Bodies live in `job_bodies`; every rule the inline column kept must hold."""

    def setUp(self):
        self.connection = db.connect(":memory:")
        self.connection.executescript(tagging.SCHEMA)
        # The triggers are installed once `job_tags` exists, as on a real install.
        db._install_tag_invalidation(self.connection)
        self.addCleanup(self.connection.close)

    def body(self, job_id="1"):
        row = self.connection.execute(
            f"SELECT {db.body()} FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return row[0]

    def tags(self):
        return self.connection.execute("SELECT count(*) FROM job_tags").fetchone()[0]

    def tag(self):
        self.connection.execute(
            "INSERT OR REPLACE INTO job_tags VALUES ('workday','firm','1','hub','boston',"
            "'strong','Boston',?, 't')", (tagging.TAGGER,))

    def test_a_missing_body_never_erases_one_and_an_empty_one_is_kept(self):
        job = Job("workday", "firm", "1", "Researcher", description="first")
        db.upsert_jobs(self.connection, None, [job])
        db.upsert_jobs(self.connection, None, [replace(job, description=None)])
        self.assertEqual(self.body(), "first")
        db.upsert_jobs(self.connection, None, [replace(job, description="")])
        self.assertEqual(self.body(), "")
        db.upsert_jobs(self.connection, None, [replace(job, job_id="2", description=None)])
        self.assertIsNone(self.body("2"))

    def test_a_later_copy_in_one_batch_wins_as_it_did(self):
        job = Job("workday", "firm", "1", "Researcher", description="a")
        db.upsert_jobs(self.connection, None, [job, replace(job, description="b"),
                                               replace(job, description=None)])
        self.assertEqual(self.body(), "b")

    def test_only_a_changed_body_invalidates_tags(self):
        job = Job("workday", "firm", "1", "Researcher")
        db.upsert_jobs(self.connection, None, [job])
        self.tag()
        db.upsert_jobs(self.connection, None, [replace(job, description=None)])
        self.assertEqual(self.tags(), 1, "no body arrived")
        db.upsert_jobs(self.connection, None, [replace(job, description="first")])
        self.assertEqual(self.tags(), 0, "a first body is new evidence")
        self.tag()
        db.upsert_jobs(self.connection, None, [replace(job, description="first")])
        self.assertEqual(self.tags(), 1, "the same body again is not")
        db.upsert_jobs(self.connection, None, [replace(job, description="second")])
        self.assertEqual(self.tags(), 0, "a changed body is")

    def test_an_inline_column_is_moved_without_invalidating_anything(self):
        """An install from before `job_bodies`: the column, its trigger and a
        tag. Connecting moves the bodies -- text, `''` and NULL alike -- drops
        the column, and leaves every tag where it was."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            old = sqlite3.connect(path)
            old.executescript(OLD_JOBS)
            old.executescript(tagging.SCHEMA)
            old.executescript(OLD_TRIGGER)
            old.executemany(
                "INSERT INTO jobs (ats, token, job_id, title, description, first_seen,"
                " last_seen) VALUES ('workday', 'firm', ?, 'Analyst', ?, 't', 't')",
                [("1", "held"), ("2", ""), ("3", None)])
            old.execute("INSERT INTO job_tags VALUES ('workday','firm','1','hub','boston',"
                        "'strong','Boston',1,'t')")
            old.commit()
            old.close()

            connection = db.connect(path)
            self.addCleanup(connection.close)
            columns = {r[1] for r in connection.execute("PRAGMA table_info(jobs)")}
            self.assertNotIn("description", columns)
            self.assertEqual(
                [tuple(r) for r in connection.execute(
                    "SELECT job_id, description FROM job_bodies ORDER BY job_id")],
                [("1", "held"), ("2", "")])
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM job_tags").fetchone()[0], 1)
            connection.execute("UPDATE jobs SET title = 'Changed' WHERE job_id = '1'")
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM job_tags").fetchone()[0], 0)
            connection.close()


OLD_JOBS = """
CREATE TABLE jobs (
    ats TEXT NOT NULL, token TEXT NOT NULL, job_id TEXT NOT NULL, domain TEXT,
    employer TEXT, category TEXT, title TEXT NOT NULL, url TEXT, location TEXT,
    department TEXT, posted_at TEXT, deadline TEXT, description TEXT,
    removed_at TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    PRIMARY KEY (ats, token, job_id)
);
"""

OLD_TRIGGER = """
CREATE TRIGGER jobs_invalidate_tags
AFTER UPDATE OF title, department, description, location, employer, category, domain
ON jobs
WHEN OLD.title IS NOT NEW.title OR OLD.description IS NOT NEW.description
BEGIN
    DELETE FROM job_tags WHERE ats=NEW.ats AND token=NEW.token AND job_id=NEW.job_id;
END;
"""
