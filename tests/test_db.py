"""List polling must not undo detail enrichment."""

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
