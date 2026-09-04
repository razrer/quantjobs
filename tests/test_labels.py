"""Regression tests for the hand-labelled fixture and its two commands.

The fixture is the one input here a machine cannot regenerate, so the tests
that matter most are the ones about not destroying it.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import csv
import io
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from quantscraper import db, labels, tagging


class ChooseTest(unittest.TestCase):
    """The draw has to be able to find a false rejection, which is the only
    failure `TAGGING.md` treats as disqualifying."""

    @staticmethod
    def _rows(spec):
        made = []
        for bucket, token, count in spec:
            for n in range(count):
                made.append({
                    "ats": "greenhouse", "token": token,
                    "job_id": f"{token}-{bucket}-{n}", "bucket": bucket,
                    "has_body": 1, "near": 1,
                })
        return made

    def test_the_contested_rejections_are_always_represented(self):
        """A false rejection can only hide among postings the lexicon threw
        away, so a sheet with none of them cannot find one."""
        rows = self._rows([
            ("keep", "a", 40), ("undecided", "b", 40), ("contested", "c", 40),
        ])

        chosen = labels.choose(rows, 60)
        buckets = {job_id.split("-")[1] for _, _, job_id in chosen}

        self.assertIn("contested", buckets)
        self.assertIn("undecided", buckets)

    def test_one_board_cannot_fill_the_sheet(self):
        """A single large Workday tenant would otherwise supply every row."""
        rows = self._rows([("contested", "huge", 500)])

        chosen = labels.choose(rows, 100)

        self.assertLessEqual(len(chosen), labels.MAX_PER_BOARD)

    def test_an_undersized_bucket_hands_its_quota_to_the_others(self):
        """`keep` is 618 postings against a frame of 2,084, and a short sheet
        fails a criterion written for 100 on arithmetic."""
        rows = self._rows([
            ("keep", "a", 1),
            *[("contested", f"b{n}", 2) for n in range(30)],
            *[("undecided", f"c{n}", 2) for n in range(30)],
        ])

        self.assertEqual(len(labels.choose(rows, 60)), 60)

    def test_the_draw_is_deterministic(self):
        rows = self._rows([("keep", "a", 20), ("undecided", "b", 20)])

        self.assertEqual(labels.choose(rows, 10), labels.choose(rows, 10))


class FrameTest(unittest.TestCase):
    """What reaches the sheet at all.

    The first sheet drew 30% of its rows from `out_of_scope` across the whole
    corpus, so the reader's first seven rows were an AI-training gig, a
    compliance officer, a commercial lawyer and a real-estate acquisition
    manager. Rejecting a van driver is not a mistake the lexicon can make.
    """

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(db.SCHEMA)
        self.connection.executescript(tagging.SCHEMA)

    def tearDown(self):
        self.connection.close()

    def _store(self, job_id, title, description="", url="https://example.test/1"):
        self.connection.execute(
            "INSERT INTO jobs (ats, token, job_id, title, location, description,"
            " url, first_seen, last_seen) VALUES ('greenhouse', 'firm', ?, ?,"
            " 'Amsterdam', ?, ?, '2026-01-01', '2026-01-01')",
            (job_id, title, description, url),
        )
        row = dict(
            ats="greenhouse", token="firm", job_id=job_id, title=title,
            location="Amsterdam", description=description, department=None,
        )
        tags = tagging.tag_posting(row)
        tags.append(tagging._fit(tags))
        tagging.record(self.connection, tags)

    def _titles(self):
        return {
            self.connection.execute(
                "SELECT title FROM jobs WHERE ats=? AND token=? AND job_id=?",
                (r["ats"], r["token"], r["job_id"]),
            ).fetchone()["title"]
            for r in labels._candidates(self.connection)
        }

    def test_another_profession_never_reaches_the_sheet(self):
        quant = "Systematic trading and alpha research on our desk. " * 8
        self._store("1", "Quantitative Researcher", quant)
        for n, title in enumerate(("Housekeeper - 300 Main", "Van Driver (Seattle)",
                                   "Tandsköterska - Smile Kramfors"), start=2):
            self._store(str(n), title, "En trevlig arbetsplats med bra kollegor. " * 8)

        self.assertEqual(self._titles(), {"Quantitative Researcher"})

    def test_a_posting_with_no_markets_word_anywhere_is_not_a_near_miss(self):
        """`judge` calls an unrecognised title `undecided`, which is most of a
        corpus of `Regional Sales Manager`. A verdict is not a signal."""
        self._store("1", "Regional Sales Manager - South Central",
                    "You will grow our territory and manage relationships. " * 8)

        self.assertEqual(self._titles(), set())

    def test_a_contested_rejection_does_reach_the_sheet(self):
        """`Equity Research Analyst` is where a false rejection hides, and the
        reader overturned exactly this one by hand."""
        self._store("1", "Equity Research Analyst",
                    "Cover listed equities and publish research on capital "
                    "markets for institutional clients. " * 6)

        self.assertEqual(self._titles(), {"Equity Research Analyst"})

    def test_a_posting_written_in_another_language_is_left_out(self):
        swedish = "Vi söker dig som vill arbeta med kvantitativ analys och handel. " * 6
        french = ("Et le poste consiste à conduire la ligne de production avec "
                  "les équipes dans un environnement de marché. " * 6)
        self._store("1", "Kvantitativ Analytiker", swedish)
        self._store("2", "Conducteur de ligne, marché", french)

        self.assertEqual(self._titles(), {"Kvantitativ Analytiker"})

    def test_a_posting_with_no_link_is_left_out(self):
        """Half the complaint about the first sheet was that the
        advertisement could not be opened."""
        quant = "Systematic trading and alpha research on our desk. " * 8
        self._store("1", "Quantitative Researcher", quant, url="")

        self.assertEqual(self._titles(), set())


class FileTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "labels.csv"
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(db.SCHEMA)
        self.connection.executescript(tagging.SCHEMA)

    def tearDown(self):
        self.connection.close()
        self.directory.cleanup()

    def _store(self, job_id, title, description="", token="firm"):
        self.connection.execute(
            "INSERT INTO jobs (ats, token, job_id, title, location, description,"
            " url, first_seen, last_seen) VALUES ('greenhouse', ?, ?, ?,"
            " 'Amsterdam', ?, ?, '2026-01-01', '2026-01-01')",
            (token, job_id, title, description,
             f"https://example.test/{token}/{job_id}"),
        )
        row = dict(
            ats="greenhouse", token=token, job_id=job_id, title=title,
            location="Amsterdam", description=description, department=None,
        )
        tags = tagging.tag_posting(row)
        tags.append(tagging._fit(tags))
        tagging.record(self.connection, tags)

    def _write(self, rows):
        """Rows as (ats, token, job_id, relevance, seniority, note)."""
        with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(labels.HEADER)
            blanks = [""] * (len(labels.CONTEXT))
            for ats, token, job_id, relevance, seniority, note in rows:
                writer.writerow(
                    ["", relevance, seniority, note, *blanks, ats, token, job_id]
                )

    def test_redrawing_never_destroys_a_label(self):
        """Hand-labelling is the one input a machine cannot regenerate."""
        self._store("1", "Quantitative Researcher")
        self._store("2", "Receptionist")
        self._write([("greenhouse", "firm", "1", "relevant", "junior_0_2", "mine")])

        labels.draw(self.connection, 2, self.path)
        kept = labels.load(self.path)

        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].relevance, "relevant")
        self.assertEqual(kept[0].note, "mine")

    def test_a_labelled_row_outside_the_draw_survives(self):
        self._store("1", "Quantitative Researcher")
        self._store("2", "Receptionist")
        self._write([("greenhouse", "firm", "2", "rejected", "unknown", "not a job")])

        labels.draw(self.connection, 1, self.path)

        self.assertIn(
            ("greenhouse", "firm", "2"),
            {(row.ats, row.token, row.job_id) for row in labels.load(self.path)},
        )

    def test_the_sheet_does_not_show_the_taggers_verdict(self):
        """Agreeing with a tag that is already on the page measures nothing."""
        self._store("1", "Quantitative Researcher")

        labels.draw(self.connection, 1, self.path)
        header = self.path.read_text(encoding="utf-8-sig").splitlines()[0]

        for leaked in ("fit", "role_class", "desk"):
            self.assertNotIn(leaked, header)

    def test_row_position_does_not_leak_the_verdict_either(self):
        """Leaving `fit` out of the columns achieves nothing if the draw is
        written bucket by bucket: the first rows are then every `apply_now`
        and a block further down is every `out_of_scope`.

        `choose` returns exactly that grouped order, so the property to hold is
        that the sheet is not written in it."""
        # Both sides must survive the frame, so the "bad" half is a contested
        # rejection rather than a receptionist -- a receptionist is filtered
        # out before the draw now, which is the whole point of the frame.
        body = "You will work on systematic trading and alpha research. " * 8
        for n in range(15):
            self._store("1", "Quantitative Researcher", body, token=f"good{n}")
            self._store("1", "Software Engineer, Trading Systems", body, token=f"bad{n}")

        labels.draw(self.connection, 30, self.path)
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            on_sheet = [
                (r["ats"], r["token"], r["job_id"]) for r in csv.DictReader(handle)
            ]
        grouped = labels.choose(labels._candidates(self.connection), 30)

        self.assertEqual(sorted(on_sheet), sorted(grouped))  # same postings
        self.assertNotEqual(on_sheet, grouped)               # different order

    def test_the_shuffle_survives_a_redraw(self):
        """A half-filled sheet must not be reordered under the reader, so the
        scatter cannot come from `hash()`, which is salted per process."""
        for n in range(10):
            self._store("1", "Quantitative Researcher", token=f"f{n}")

        labels.draw(self.connection, 10, self.path)
        first = self.path.read_text(encoding="utf-8-sig")
        labels.draw(self.connection, 10, self.path)

        self.assertEqual(first, self.path.read_text(encoding="utf-8-sig"))

    def test_what_you_type_comes_before_what_you_read(self):
        self._store("1", "Quantitative Researcher")

        labels.draw(self.connection, 1, self.path)
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle))

        self.assertLess(header.index("relevance"), header.index("title"))
        self.assertLess(header.index("note"), header.index("url"))
        self.assertEqual(header[-3:], ["ats", "token", "job_id"])

    def test_the_sheet_does_not_cache_the_description(self):
        """**It was 3.6 MB of the sheets' 4.3 MB**, a verbatim copy of a column
        `jobs` already owns, rewritten in git on every redraw. Every binary
        format was measured against simply dropping it and lost: SQLite 4.9 MB,
        gzip 1.4 MB, xz 0.9 MB, against 318 KB for this."""
        self._store("1", "Quantitative Researcher", description="x" * 5_000)

        labels.draw(self.connection, 1, self.path)
        text = self.path.read_text(encoding="utf-8-sig")

        self.assertNotIn("description", next(csv.reader(io.StringIO(text))))
        self.assertNotIn("x" * 200, text)

    def test_a_hand_edited_header_still_parses(self):
        """Spreadsheets are edited by people: a column picks up a capital, or
        a reminder of the allowed values."""
        self._store("1", "Quantitative Researcher")
        with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Relevance (relevant/adjacent)", "Seniority", "Note",
                             "ats", "token", "job_id"])
            writer.writerow(["Less Relevant", "junior_0_2", "x",
                             "greenhouse", "firm", "1"])

        label = labels.load(self.path)[0]

        self.assertEqual(label.relevance, "less_relevant")
        self.assertEqual(label.job_id, "1")

    def test_a_blank_row_is_skipped_rather_than_guessed_at(self):
        self._store("1", "Quantitative Researcher")
        self._write([("greenhouse", "firm", "1", "", "", "")])

        self.assertEqual(labels.load(self.path), [])

    def test_labels_from_an_older_scale_are_translated(self):
        """A fixture that discards last week's work every time the lexicon
        moves is a fixture nobody fills in twice."""
        self._store("1", "Quantitative Researcher")
        self._write([("greenhouse", "firm", "1", "core", "student_only", "")])

        label = labels.load(self.path)[0]

        self.assertEqual(label.relevance, "relevant")
        # `student_intern` has left the scale, so a row written against it
        # reads as `unknown` -- what the scale now says about such a posting.
        # Discarding the row instead would cost an afternoon's labelling over
        # a scale change the labeller did not make.
        self.assertEqual(label.seniority, "unknown")

    def test_intern_as_a_rank_is_refused_with_the_reason(self):
        self._store("1", "Quantitative Researcher")
        self._write([("greenhouse", "firm", "1", "relevant", "intern", "")])

        problems = labels.validate(labels.load(self.path))

        self.assertEqual(len(problems), 1)
        self.assertIn("contract now", problems[0])


class ScoreTest(FileTest):
    def test_a_false_rejection_is_reported_apart_from_the_rest(self):
        """A posting wrongly thrown away is the expensive failure; a false
        positive costs a few seconds of reading."""
        self._store("1", "Actuarial Pricing Analyst")
        self._write([("greenhouse", "firm", "1", "relevant", "junior_0_2", "")])

        _, disagreements = labels.score(self.connection, labels.load(self.path))
        missed = [d for d in disagreements if d.false_rejection]

        self.assertEqual(len(missed), 1)
        self.assertEqual(missed[0].tagged, "rejected")

    def test_agreement_is_counted_per_dimension(self):
        self._store("1", "Junior Quantitative Researcher")
        self._write([("greenhouse", "firm", "1", "relevant", "senior_6_10", "")])

        rates, _ = labels.score(self.connection, labels.load(self.path))

        self.assertEqual(rates["relevance"][2], 1.0)
        self.assertEqual(rates["seniority"][2], 0.0)

    def test_a_label_whose_keys_match_nothing_is_named(self):
        """Titles are not keys: two postings in the first sample were both
        called `Graduate Trader`."""
        self._write([("greenhouse", "firm", "nope", "relevant", "junior_0_2", "")])

        _, disagreements = labels.score(self.connection, labels.load(self.path))

        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0].dimension, "key")


class TheSheetSurvivesItsWriterTest(unittest.TestCase):
    """`labels.csv` is the one input here a machine cannot regenerate, and both
    ways of losing it were reachable: a truncating open that leaves the file
    empty if the write fails half way, and two `serve.py` request threads
    reading the same rows and the second dropping the first."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "labels.csv"

    def _write(self, n):
        labels.upsert(self.path, ("a", "b", str(n)), "relevance", "rejected",
                      {"title": f"row {n}"})

    def test_a_failed_write_leaves_the_previous_sheet_intact(self):
        self._write(1)
        before = self.path.read_text(encoding="utf-8-sig")
        real = csv.writer

        class Exploding:
            def __init__(self, handle): self.handle = handle
            def writerows(self, rows): raise RuntimeError("disk full")

        csv.writer = Exploding
        try:
            with self.assertRaises(RuntimeError):
                self._write(2)
        finally:
            csv.writer = real
        self.assertEqual(self.path.read_text(encoding="utf-8-sig"), before)
        self.assertEqual(len(labels.load(self.path)), 1)

    def test_no_temporary_file_is_left_behind(self):
        self._write(1)
        self.assertEqual([p.name for p in Path(self.dir.name).iterdir()], ["labels.csv"])

    def test_concurrent_corrections_do_not_lose_each_other(self):
        """The `serve.py` case: one thread per request, one file."""
        start = threading.Barrier(8)

        def go(n):
            start.wait()
            self._write(n)

        threads = [threading.Thread(target=go, args=(n,)) for n in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(
            {label.job_id for label in labels.load(self.path)},
            {str(n) for n in range(8)},
        )


if __name__ == "__main__":
    unittest.main()
