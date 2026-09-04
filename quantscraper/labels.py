"""The fixture Layer 5 was missing, and the two commands around it.

`roster.csv` did this for coverage in Stage 2 and immediately found a false hit
nobody suspected. Tagging had no equivalent, so "the lexicon improved" and "the
market moved" were indistinguishable, and every false positive found so far was
found by luck -- whatever happened to be on screen.

    python -m quantscraper sample --limit 100     # draw postings to label
    python -m quantscraper labels                 # score the lexicon on them

## Two things the first attempt at this got wrong

**The sample was drawn from the top of the shortlist.** `list --limit 100` sorts
by fit, so the hundred postings offered for labelling were the hundred the
tagger was most confident about. A sample like that can only ever find false
*positives*, and the exit criterion in `TAGGING.md` is **no false rejection** --
the one failure this project treats as expensive. It cannot be measured from
rows the tagger already likes. `draw` therefore stratifies across every fit
bucket, `out_of_scope` included, and caps how many rows one board may
contribute so a single large Workday tenant cannot fill the page.

**The sample carried no keys.** It printed fit, hub, seniority, a title
truncated to 44 characters and a URL -- and the label format asks for
`ats,token,job_id`, none of which were in the file. The rows written from it
could not be joined back to `jobs` at all, and titles are not a substitute:
two postings in that very sample were both called `Graduate Trader`.

## And one it got right by accident, now on purpose

The drawn file shows the posting and **not the tagger's verdict**. Seeing the
machine's answer while labelling is how a fixture ends up measuring agreement
with itself; `ACTION-REQUIRED.md` warned about it in prose and then handed over
a file with `fit` in the first column.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import os
import re
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from . import lexicon, tagging

PATH = Path(__file__).with_name("labels.csv")
AUTO_PATH = Path(__file__).with_name("auto_labels.csv")
AGENT_PATH = Path(__file__).with_name("agent_labels.csv")

# All three sheets, scored together by default.
#
# `TAGGING.md` argued a machine sheet must never be the criterion -- "a model
# grading a model agrees with it for the wrong reasons, and this one shares a
# family with the classifier's author". That argument is about *unread*
# labels. The reader has confirmed both machine sheets, which is the step that
# turns one from an echo into evidence, so all three are scored and `labels`
# still reports each file on its own line -- which is the part that matters,
# because they do not agree and a single blended number would hide it.
#
# **`agent_labels.csv` is the noisiest of the three and its own limits are
# worth keeping in front of whoever reads the score.** Twelve model labellers
# over 471 postings, told to prefer `adjacent` when torn -- and they did,
# calling `Slack Administrator`, `IT Support Engineer` and
# `Network Security Engineer` adjacent while calling
# `Junior Quantitative Analyst (Credit & FI)` rejected. It is scored because
# the reader has read it; it is still not the sheet to tune a needle against,
# and the per-file lines are how that stays visible.
SHEETS = (PATH, AUTO_PATH, AGENT_PATH)

# Column order is reading order. What you type comes first so the cursor lands
# on it, what you read comes next, and the three keys go last -- they are how a
# row joins back to `jobs` and they are never edited, so they have no business
# occupying columns A to C.
#
# **`description` is deliberately not here, and dropping it was worth 13x.**
# The three sheets were 4.3 MB of which **3.6 MB was a verbatim copy of
# `jobs.description`** -- a column the database already owns, checked into git,
# and rewritten in full whenever a sheet is redrawn. Measured against every
# alternative before choosing: SQLite as a binary table is 4.9 MB (*larger*,
# on page overhead), CSV+gzip 1.4 MB, CSV+xz 0.9 MB, and Parquet would land
# near those -- so a new dependency would still have lost to simply not
# storing the column, and would have cost the git diff, the Excel edit and
# `serve.py`'s write path along the way.
#
# What the labeller loses is the body text inline; what they keep is the
# title, the firm, the place, the department and a **clickable `url`**, which
# is the posting itself rather than a 4,000-character truncation of it. The
# description is one click away and regenerable from `jobs` at any time -- the
# verdicts are the only thing here that cannot be.
#
# To reverse: put `"description"` back on `CONTEXT` and append the column to
# the row `write` builds. It wants flattening first -- markup stripped,
# entities decoded, whitespace collapsed, capped -- which is what
# `bodies._clean` already does for the tagger.
FILL = ("relevance", "seniority", "note")
CONTEXT = ("title", "firm", "location", "department", "url")
KEYS = ("ats", "token", "job_id")
HEADER = ("n", *FILL, *CONTEXT, *KEYS)

# Kept for callers that only care which columns are writable.
FIELDS = (*KEYS, *FILL)

# The board's short facet keys, translated to this file's column names. Shared
# by `web/serve.py` (local corrections) and `cli._corrections` (corrections
# pulled back from the live board's Lambda) so the two paths can't drift.
DIMENSION_NAMES = {"rel": "relevance", "sen": "seniority"}

RELEVANCE = ("relevant", "less_relevant", "adjacent", "rejected")
# `student_intern` was here and is gone, at the user's decision. It was the
# only value on this scale the tagger reads from a *body* rather than a title,
# so every intern-titled row got labelled `student_intern` and disagreed with a
# tagger that finds no grade word in the title -- the scale was asking a
# question the tagger does not answer. Being a student is an eligibility fact
# and a contract, and both are recorded: `contract: internship` and
# `hard_gates: student_only`.
SENIORITY = (
    "new_grad", "junior_0_2", "mid_3_5",
    "senior_6_10", "lead", "head_or_md", "unknown",
)

# Labels written against an older scale, translated rather than rejected. A
# fixture that throws away last week's work every time the lexicon moves is a
# fixture nobody fills in twice.
LEGACY = {
    "core": "relevant",
    "less relevant": "less_relevant",
    # Rows written while `student_intern` was on the scale. They are read as
    # `unknown`, which is what the scale now says about them: the sheet no
    # longer distinguishes a student contract from an unstated grade, and
    # silently dropping the rows instead would cost an afternoon's labelling
    # over a scale change the labeller did not make.
    "student_only": "unknown",
    "student only": "unknown",
    "student_intern": "unknown",
    "student intern": "unknown",
}

# **A false rejection can only hide among postings that could plausibly be in
# scope**, and the first sheet got this wrong in the most expensive way: it
# drew 30% of its rows from `out_of_scope` across the *whole* corpus, so the
# reader's first seven rows were an AI-training gig, a compliance officer and a
# commercial lawyer. Rejecting a van driver is not a mistake the lexicon can
# make; the rows worth an hour are the ones where it could.
#
# So the frame comes from `lexicon.judge`, which already separates the two kinds
# of rejection. These reasons are *contestable* -- a human could reasonably
# overturn them, and one already did.
CONTESTABLE = frozenset({
    "non_quant_finance", "pure_engineering", "too_senior", "student_only",
})

# These are not contestable. No body text turns a housekeeper, a dental nurse
# or a lifecycle-marketing director into a quant role, and asking a person to
# confirm that a van driver is not one measures nothing.
NEVER_ASK = frozenset({"unrelated_occupation", "corporate_function", "crypto_web3"})

# The user reads English and Swedish. Everything else is excluded only when it
# is *positively identified* -- `unknown` stays, because 81% of the corpus is a
# six-word title that no detector should claim to have read.
READABLE = frozenset({"en", "sv", "unknown"})

# Everywhere the board is willing to show, which is the same question this asks
# -- London, New York and Frankfurt are places the reader would plausibly work,
# where Cyprus and Bulgaria are not. Used to *order* the draw, never to filter
# it.
#
# **Derived rather than restated.** It was a copy of the hub list and drifted
# the moment one was added: promoting the United States would have left the
# sheet ranking New York level with Bucharest. `unknown` is dropped because a
# posting that named no place is not evidence of being near one.
_NEARBY = frozenset(tagging.BOARD_HUBS) - {"unknown"}

# Stratified over what the judge made of a posting, not over the fit bucket.
# `undecided` is the largest share on purpose: it is the genuine ambiguity, the
# queue the classifier cannot settle on its own, and therefore the rows where a
# human hour buys the most.
QUOTA = {
    "keep": 0.35,
    "undecided": 0.35,
    "contested": 0.30,
}
MAX_PER_BOARD = 2

_MARKUP = re.compile(r"<[^>]{0,4000}>")
_SPACE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# Drawing a sample
# --------------------------------------------------------------------------


def anchored(title: str, department: str | None, description: str | None) -> str | None:
    """The word that makes this posting worth a person's attention, or None.

    Without this the frame is 46,595 postings, because `judge` returns
    `undecided` for every title it recognises no word in at all -- which is
    most of a seventy-thousand-row corpus of `Regional Sales Manager` and
    `Field Service Delivery`. Those are not near misses, they are noise with a
    verdict attached.

    `MARKETS` is read from the **role** only. In a body it belongs to the
    employer, not the job: a market-data vendor describes markets on its every
    backend-engineer advertisement, and that is how eleven venture boards ended
    up in the keep list once already.
    """
    role = lexicon.normalize(f"{title or ''} {department or ''}")
    body = lexicon.normalize(description)
    return (
        lexicon.first(role, lexicon.QUANT)
        or lexicon.first(role, lexicon.TITLE_ANCHOR)
        or lexicon.first(role, lexicon.MARKETS)
        or lexicon.first(body, lexicon.QUANT_BODY)
    )


def _candidates(connection: sqlite3.Connection) -> list[dict]:
    """The postings worth putting in front of a person, and their bucket.

    Four gates, each answering something an earlier sheet got wrong:

    - **still live and openable** -- a withdrawn posting or one with no URL
      cannot be read, and half the complaint about the first sheet was that
      the advertisement was gone;
    - **not gated off the board** -- `tagging.GATES`, the same list
      `web/build_data.py` reads. A labelling sheet that disagrees with the
      board is measuring a classifier nobody reads, and this was checking only
      `off_industry`, so it kept offering VP roles and postings in Kiruna
      after the board had stopped showing either;
    - **readable** -- English, Swedish, or a posting too short to tell;
    - **plausibly in scope** -- see `CONTESTABLE`.
    """
    rows = connection.execute(
        """
        SELECT j.ats, j.token, j.job_id, j.title, j.department, j.description,
               length(j.description) > 200 AS has_body,
               (SELECT group_concat(value) FROM job_tags x
                 WHERE x.ats = j.ats AND x.token = j.token AND x.job_id = j.job_id
                   AND x.dimension = 'exclusion_reason' AND x.tagger = ?) AS excluded,
               (SELECT value FROM job_tags l
                 WHERE l.ats = j.ats AND l.token = j.token AND l.job_id = j.job_id
                   AND l.dimension = 'posting_language' AND l.tagger = ?) AS lang,
               -- Multi-valued: a posting open in two cities carries a row
               -- per city, and a scalar read would pick one of them at random.
               (SELECT group_concat(value, '/') FROM job_tags h
                 WHERE h.ats = j.ats AND h.token = j.token AND h.job_id = j.job_id
                   AND h.dimension = 'hub' AND h.tagger = ?) AS hub
        FROM jobs j
        WHERE j.removed_at IS NULL AND j.url IS NOT NULL AND j.url <> ''
        """,
        (tagging.TAGGER, tagging.TAGGER, tagging.TAGGER),
    ).fetchall()

    frame = []
    for row in rows:
        if any(gate in (row["excluded"] or "") for gate in tagging.GATES):
            continue
        if (row["lang"] or "unknown") not in READABLE:
            continue
        if not anchored(row["title"], row["department"], row["description"]):
            continue
        call = lexicon.judge(row["title"], row["department"], row["description"])
        if call.verdict == "reject":
            if call.reason in NEVER_ASK or call.reason not in CONTESTABLE:
                continue
            bucket = "contested"
        else:
            bucket = call.verdict
        frame.append({
            "ats": row["ats"], "token": row["token"], "job_id": row["job_id"],
            # `length(NULL) > 200` is NULL, not 0, and a posting with no
            # description is exactly the row that hits it.
            "bucket": bucket, "has_body": int(bool(row["has_body"])),
            # A place the reader might actually take a job. This **orders** the
            # draw and never filters it -- geography ranks and never gates, and
            # relevance and seniority are what the sheet measures, neither of
            # which depends on where the desk is. It only stops an afternoon
            # going on postings in Cyprus and Bulgaria.
            "near": int(
                bool(set((row["hub"] or "other").split("/")) & _NEARBY)
            ),
        })
    return frame


def choose(rows: list[dict], limit: int) -> list[tuple[str, str, str]]:
    """A stratified draw over `judge` verdicts, then spread over boards.

    Deterministic, so re-drawing the same corpus returns the same sample and a
    partly-labelled file stays valid. Postings that carry a body sort first
    within a bucket -- a label read off a bare title measures the labeller's
    priors rather than the posting, which is exactly how the first three rows
    came back with a reason the text contradicts.
    """
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(row["bucket"], []).append(row)

    for available in buckets.values():
        # Body first, then a stable spread over the corpus rather than the
        # first N of one board.
        available.sort(
            key=lambda r: (-r["has_body"], -r["near"], r["job_id"], r["token"]))

    chosen: list[tuple[str, str, str]] = []
    seen: dict[str, int] = {}
    taken: set[tuple[str, str, str]] = set()

    def fill(bucket: str, want: int) -> int:
        """Take up to `want` from a bucket. Returns how many were short."""
        for row in buckets.get(bucket, []):
            if want <= 0 or len(chosen) >= limit:
                break
            key = (row["ats"], row["token"], row["job_id"])
            if key in taken or seen.get(row["token"], 0) >= MAX_PER_BOARD:
                continue
            seen[row["token"]] = seen.get(row["token"], 0) + 1
            taken.add(key)
            chosen.append(key)
            want -= 1
        return want

    # A bucket can be smaller than its quota -- there are five `apply_now`
    # postings in the whole corpus -- so the shortfall is handed to the others
    # rather than silently shrinking the sheet. A 96-row sample against a
    # criterion written for 100 fails it on arithmetic.
    short = sum(fill(bucket, round(limit * share)) for bucket, share in QUOTA.items())
    while short and len(chosen) < limit:
        before = len(chosen)
        for bucket in QUOTA:
            short = fill(bucket, short)
        if len(chosen) == before:
            break  # every bucket is exhausted; a short sheet is the true answer
    return chosen


# **The sheet is written under a lock and replaced atomically**, and both
# halves are about the same file: `labels.csv` is the one input here a machine
# cannot regenerate, and the two ways it can be lost are both reachable today.
#
# *Lost update.* `web/serve.py` is a `ThreadingHTTPServer` and `upsert` is a
# read-modify-write of the whole file, so two corrections in flight at once
# read the same rows and the second write drops the first. One click and a
# quick second one is all that takes.
#
# *Truncation.* `open(path, "w")` empties the file before a single row is
# written, so an exception or a killed process between those two moments
# leaves an empty `labels.csv` -- the project's own exit criterion, gone, and
# the failure looks like "the sheet has no rows in it" rather than like a
# crash. Writing beside it and renaming means the old file survives until the
# new one is complete; `os.replace` is atomic on Windows as well as POSIX.
_SHEET_LOCK = threading.Lock()


def _write_sheet(path: Path, rows) -> None:
    """Write `rows` (header first) to `path`, atomically. Caller holds the lock.

    Excel on Windows reads a BOM-less UTF-8 CSV as cp1252, which turns every
    Swedish and Dutch posting into mojibake. `load` reads `utf-8-sig`, so this
    round-trips.
    """
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="", delete=False,
        dir=str(path.parent or "."), prefix=path.name, suffix=".tmp",
    )
    try:
        with handle:
            csv.writer(handle).writerows(rows)
        os.replace(handle.name, path)
    except BaseException:
        pathlib_unlink(handle.name)
        raise


def pathlib_unlink(name: str) -> None:
    try:
        os.unlink(name)
    except OSError:
        pass


def draw(connection: sqlite3.Connection, limit: int, path: Path) -> tuple[int, int]:
    """Write the labelling sheet. Returns (rows written, labels preserved).

    **Never destructive.** Hand-labelling is the one input here a machine
    cannot regenerate, so a row already carrying a verdict keeps it, and keeps
    it even when this draw would not have selected the posting again. Re-running
    `sample` after the lexicon changes therefore tops the sheet up rather than
    resetting an afternoon's reading.
    """
    done = {(l.ats, l.token, l.job_id): l for l in load(path)}
    drawn = choose(_candidates(connection), limit)

    # **Shuffled, and this is not cosmetic.** The draw is built bucket by
    # bucket, so writing it in that order leaks the tagger's verdict through
    # row position as plainly as the omitted `fit` column would -- and thirty
    # rejections in a row invite rubber-stamping.
    #
    # `hash()` is salted per process and would reshuffle on every run, so the
    # order comes from a digest of the key: stable across runs and machines,
    # which is what lets a half-filled sheet survive a redraw.
    ordered = sorted(dict.fromkeys([*done, *drawn]), key=_scatter)

    written = 0
    rows = [list(HEADER)]
    for key in ordered:
        row = connection.execute(
            "SELECT title, department, location, url, description, domain"
            " FROM jobs WHERE ats = ? AND token = ? AND job_id = ?", key,
        ).fetchone()
        if row is None:
            continue
        label = done.get(key)
        written += 1
        rows.append([
            written,
            label.relevance if label else "",
            label.seniority if label else "",
            label.note if label else "",
            row["title"] or "",
            row["domain"] or key[1],
            row["location"] or "",
            row["department"] or "",
            row["url"] or "",
        ] + list(key))
    with _SHEET_LOCK:
        _write_sheet(path, rows)
    return written, len(done)


# --------------------------------------------------------------------------
# Reading labels back, and scoring against them
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Label:
    ats: str
    token: str
    job_id: str
    relevance: str
    seniority: str
    note: str
    # Which sheet the row came from. Defaulted so nothing that builds a Label
    # by hand has to care, and set by `load`, because with three sheets of
    # unequal quality being scored together the *provenance* of a
    # disagreement is most of what makes it readable -- a false rejection
    # against the hand sheet is a bug and one against `agent_labels.csv` is
    # usually the model having preferred `adjacent` when torn.
    sheet: str = ""


def _scatter(key: tuple[str, str, str]) -> str:
    """A stable, process-independent sort key for one posting."""
    return hashlib.md5("|".join(key).encode()).hexdigest()


def _clean(value: str | None) -> str:
    text = (value or "").strip().lower()
    # A cell holding only punctuation is a person writing "I did not judge
    # this one" -- `-`, `–`, `?`, `n/a`. It is not a value, and the
    # space-and-dash folding below would otherwise turn a lone dash into `_`
    # and report it as an invalid label.
    if not any(character.isalnum() for character in text) or text in ("na", "n/a"):
        return ""
    # "Less Relevant", "less relevant" and "less_relevant" are the same answer.
    # The sheet is filled in by hand in a spreadsheet, which autocapitalises.
    text = LEGACY.get(text, text.replace(" ", "_").replace("-", "_"))
    # A slipped finger is not a different answer. Anything further off than
    # that is reported rather than guessed at -- see `nearest`.
    if text not in RELEVANCE and text not in SENIORITY:
        text = nearest(text, RELEVANCE + SENIORITY) or text
    return text


def _column(name: str) -> str:
    """Fold a header cell to its canonical name.

    Spreadsheets are edited by people: a column gets renamed to `relevance
    (relevant/less_relevant/...)` as a reminder, or picks up a stray capital.
    None of that should cost an afternoon's labelling.
    """
    return re.split(r"[ (\[]", (name or "").strip().lower(), maxsplit=1)[0]


def load(path: Path = PATH) -> list[Label]:
    """Every filled-in row. Blank verdicts are skipped, not guessed at."""
    if not path.exists():
        return []
    labels = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = [_column(cell) for cell in next(reader, [])]
        for values in reader:
            row = dict(zip(header, values))
            relevance = _clean(row.get("relevance"))
            seniority = _clean(row.get("seniority"))
            if not relevance and not seniority:
                continue
            labels.append(Label(
                (row.get("ats") or "").strip(),
                (row.get("token") or "").strip(),
                (row.get("job_id") or "").strip(),
                relevance, seniority, (row.get("note") or "").strip(),
                path.name,
            ))
    return labels


def upsert(path: Path, key: tuple[str, str, str], dimension: str, value: str,
           context: dict[str, str]) -> None:
    """Write one FILL column for one posting, in place if the row already exists.

    The board's reclassify control calls this (through `web/serve.py`) so a
    correction lands straight in the file `labels` already scores against --
    no download, no manual merge. Only `dimension` is touched: the sibling FILL
    column and `note` are left exactly as a person left them, so a live
    one-field correction can never clobber a hand-typed cell it was not asked
    to change. Context columns are written only when the row is brand new; an
    existing row keeps whatever a person already put there, same as `draw`
    never overwriting a filled-in label.
    """
    with _SHEET_LOCK:
        _upsert(path, key, dimension, value, context)


def _upsert(path: Path, key: tuple[str, str, str], dimension: str, value: str,
            context: dict[str, str]) -> None:
    """`upsert`'s read-modify-write. The caller holds `_SHEET_LOCK`."""
    header = list(HEADER)
    rows: list[list[str]] = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            first = next(reader, None)
            if first:
                header = first
            rows = list(reader)

    idx = {_column(name): i for i, name in enumerate(header)}

    def cell(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else ""

    target = None
    for row in rows:
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        if (cell(row, "ats"), cell(row, "token"), cell(row, "job_id")) == key:
            target = row
            break

    if target is None:
        target = [""] * len(header)
        for name, part in zip(KEYS, key):
            if name in idx:
                target[idx[name]] = part
        for name, text in context.items():
            if name in idx and text:
                target[idx[name]] = text
        if "note" in idx:
            target[idx["note"]] = "from the board"
        if "n" in idx:
            target[idx["n"]] = str(len(rows) + 1)
        rows.append(target)

    if dimension in idx:
        target[idx[dimension]] = value

    _write_sheet(path, [header, *rows])


def nearest(value: str, allowed: tuple[str, ...]) -> str | None:
    """The one allowed value `value` is obviously a typo for, if any.

    Cut high on purpose. `rejectec` is `rejected` with a slipped finger and
    correcting it silently is right; `slightly` is a person reaching for a
    word the scale does not have, and quietly filing it as `less_relevant`
    would put an answer in the fixture that nobody gave.
    """
    close = difflib.get_close_matches(value, allowed, n=1, cutoff=0.85)
    return close[0] if close else None


def validate(labels: list[Label]) -> list[str]:
    """Complaints about the file itself, before any of it is believed."""
    problems = []
    for label in labels:
        where = f"{label.ats}/{label.token}/{label.job_id}"
        for column, value, allowed in (("relevance", label.relevance, RELEVANCE),
                                       ("seniority", label.seniority, SENIORITY)):
            if not value or value in allowed:
                continue
            hint = ""
            if guess := nearest(value, allowed):
                hint = f" -- did you mean {guess!r}?"
            elif column == "seniority" and value in RELEVANCE:
                hint = " -- that is a relevance value; the columns look shifted"
            elif column == "seniority" and value == "intern":
                hint = ("  -- `intern` is a contract now, not a rank; give the"
                        " level the body asks for")
            problems.append(f"{where}: {column} {value!r} is not one of"
                            f" {'/'.join(allowed)}{hint}")
    return problems


@dataclass(frozen=True, slots=True)
class Disagreement:
    ats: str
    token: str
    job_id: str
    title: str
    dimension: str
    labelled: str
    tagged: str
    evidence: str
    note: str
    sheet: str = ""

    @property
    def false_rejection(self) -> bool:
        """The expensive failure: a real posting the lexicon threw away."""
        return self.dimension == "relevance" and self.tagged == "rejected"


def score(connection: sqlite3.Connection, labels: list[Label]):
    """(agreement per dimension, disagreements) for the current lexicon."""
    agreed = {"relevance": [0, 0], "seniority": [0, 0]}
    found: list[Disagreement] = []

    for label in labels:
        key = (label.ats, label.token, label.job_id)
        posting = connection.execute(
            "SELECT title FROM jobs WHERE ats = ? AND token = ? AND job_id = ?", key
        ).fetchone()
        tags = {
            row["dimension"]: (row["value"], row["evidence"] or "")
            for row in connection.execute(
                "SELECT dimension, value, evidence FROM job_tags"
                " WHERE ats = ? AND token = ? AND job_id = ? AND tagger = ?"
                "   AND dimension IN ('relevance', 'seniority')",
                (*key, tagging.TAGGER),
            )
        }
        if posting is None:
            found.append(Disagreement(
                *key, "(not in the database)", "key", "-", "-",
                "no posting matches these three columns", label.note,
                label.sheet,
            ))
            continue
        if not tags:
            # A different fact entirely, and reporting it as the one above sent
            # me looking for a broken key when the tagger had simply not been
            # re-run after a version bump.
            found.append(Disagreement(
                *key, posting["title"] or "", "key", "-", "-",
                f"no tags at lexicon {tagging.TAGGER} -- run `tag` first",
                label.note, label.sheet,
            ))
            continue

        for dimension, labelled in (("relevance", label.relevance),
                                    ("seniority", label.seniority)):
            if not labelled:
                continue
            tagged, evidence = tags.get(dimension, ("(missing)", ""))
            agreed[dimension][1] += 1
            if tagged == labelled:
                agreed[dimension][0] += 1
            else:
                found.append(Disagreement(
                    *key, posting["title"] or "", dimension, labelled, tagged,
                    evidence, label.note, label.sheet,
                ))

    rates = {
        dimension: (hits, total, hits / total if total else 0.0)
        for dimension, (hits, total) in agreed.items()
    }
    return rates, found


# The ranks the reader asked not to be shown. `lead` and `head_or_md` are
# obvious; `senior_6_10` is here because a posting demanding six years is out
# of reach from under one, which is the same fact stated as a number.
LEADERSHIP = frozenset({"senior_6_10", "lead", "head_or_md"})


def containment(connection, labels: list[Label], gates, tag_posting):
    """(leadership kept off the board, total, openings lost to the rank gate).

    **Seniority is scored by what it is for, not by rung agreement.** The
    reader's own words: it matters "for filtering out leadership positions,
    which I am not interested in". Rung agreement measures something else and
    measures it badly -- a third of the labelled rows are titles stating no
    grade, where the tagger answers `unknown` on purpose, and a `Senior X`
    posting the reader calls `mid_3_5` and the tagger calls `senior_6_10` is a
    disagreement about a word and an agreement about the decision.

    So this asks the two questions that have consequences:

    - **containment** -- of the postings the reader graded as leadership, how
      many does the board actually withhold? Any other answer means a posting
      they asked not to see is on the page.
    - **cost** -- of the postings they rated worth reading, how many did the
      *rank* gate remove? That is the expensive direction, and it is counted
      separately rather than netted off, because the two errors are not
      interchangeable.
    """
    kept = shown = lost = 0
    for label in labels:
        if not label.seniority:
            continue
        row = connection.execute(
            "SELECT * FROM jobs WHERE ats = ? AND token = ? AND job_id = ?",
            (label.ats, label.token, label.job_id),
        ).fetchone()
        if row is None:
            continue
        tags = tag_posting(row)
        excluded = {t.value for t in tags if t.dimension == "exclusion_reason"}
        relevance = next(
            (t.value for t in tags if t.dimension == "relevance"), "unknown")
        on_board = not (excluded & set(gates)) and relevance != "rejected"
        if label.seniority in LEADERSHIP:
            shown += on_board
            kept += not on_board
        elif (label.relevance in ("relevant", "less_relevant", "adjacent")
              and not on_board and "out_of_reach" in excluded):
            lost += 1
    return kept, kept + shown, lost
