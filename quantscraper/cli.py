"""Command line entry point: `python -m quantscraper ...`"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta, timezone

from . import (
    alerts, ats, audit, bodies, coverage, db, discover, domains, extract,
    fca, http, iesjobs, jobbsafari, jobindex, jobroom_ch, jobstream, labels,
    mycareersfuture, pages,
    resolve, sites, tagging,
)
from .registries import REGISTRIES

# The registries covering the focus hubs. Domain resolution starts here because
# these are the firms with no website at all; the SEC already publishes one for
# most of its filers.
FOCUS_SOURCES = ("fi_se", "afm_nl", "finanstilsynet_dk", "mas_sg", "sfc_hk", "seed")

# The live board's write route (`functions/correction_writer`), read back
# here. See `_corrections` below and CLAUDE.md's "Publishing it".
CORRECTIONS_ENDPOINT = "https://quantjobs-api.spawned.app/corrections"


def _record_poll(
    connection,
    source: str,
    started_at: str,
    seen: int,
    *,
    partial: bool = False,
    problem: str | None = None,
) -> None:
    """Put a Layer 4 poll in `runs`, so `alerts` can see the source at all.

    **The gap this closes was found the expensive way.** job-room.ch was built,
    guarded and proved against a live portal, and its rows were not in the
    database -- 187,960 postings and not one of them Swiss. Nothing announced
    it, because `alerts` is the one thing whose job is noticing silence and it
    reads `runs`, which until now only the registry fetches wrote to. A source
    that collected nothing looked exactly like a source nobody had asked about.

    A deliberate subset is not recorded: `--pages`, `--only` and `--since` are
    probes and top-ups, and a baseline built from them would judge a full sweep
    against a sample of it. That is the same rule `alerts` states for itself --
    one run is not a baseline, and inventing one produces noise on exactly the
    sources that are newest.
    """
    if partial:
        return
    db.record_run(
        connection, source, started_at, seen, ok=problem is None, error=problem
    )


def _poll(connection, source: str, sweep: Callable[[], object]):
    """Run one Layer 4 sweep, recording it in `runs` **even when it raises**.

    **This is the half of the job `_record_poll` left open, and it cost a
    source.** `_record_poll` runs after the sweep returns, so a sweep that
    *crashes* records nothing at all -- and a source with no row in `runs` is
    exactly what `alerts` cannot see. MyCareersFuture died ~400 pages into a
    `daily --full` on an HTTP 429, wrote 37,562 postings and no run, and
    `alerts` then reported **"all sources healthy"** while Singapore was down.
    That is the job-room.ch failure one step along: not a source nobody asked
    about, but a source that was asked and did not come back.

    `_fetch` has recorded a failed registry since the beginning; this brings the
    national boards to the same contract. The exception is re-raised, so the
    caller still fails and `daily` still counts the step as failed -- the only
    thing that changes is that the database now says so.
    """
    started_at = db.now()
    try:
        return started_at, sweep()
    except Exception as exc:
        db.record_run(connection, source, started_at, 0, ok=False, error=str(exc))
        raise


def _fetch(names: list[str], database: str) -> int:
    connection = db.connect(database)
    failures = 0

    for name in names:
        module = REGISTRIES[name]
        started_at = db.now()
        try:
            employers = module.fetch()
            # An implausibly small result is a failure, not a quiet day.
            if len(employers) < module.MIN_EXPECTED:
                raise ValueError(
                    f"got {len(employers)} employers, expected at least "
                    f"{module.MIN_EXPECTED} -- treating as a broken source"
                )
        except Exception as exc:  # noqa: BLE001 -- one bad source must not stop the rest
            db.record_run(connection, name, started_at, 0, ok=False, error=str(exc))
            print(f"FAIL  {name}: {exc}", file=sys.stderr)
            failures += 1
            continue

        written = db.upsert_employers(connection, name, module.JURISDICTION, employers)
        db.record_run(connection, name, started_at, written, ok=True)
        print(f"ok    {name}: {written} employers")

    return failures


def _resolve(database: str) -> int:
    connection = db.connect(database)
    firms, rows = resolve.build_firms(connection)
    print(f"resolved {rows:,d} employer rows into {firms:,d} firms")
    return 0


def _audit(database: str, verbose: bool, job_pipeline: bool = False) -> int:
    connection = db.connect(database)
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'firms'"
    ).fetchone():
        print("no firms table -- run `resolve` first", file=sys.stderr)
        return 1
    roster = audit.load_roster()
    if job_pipeline:
        # `discover` owns the roster-to-(names, domain) resolution, and it is
        # wired here rather than imported by `audit` so that module keeps its
        # one promise: it reads, and it depends on nothing that writes.
        targets = discover.roster_targets(connection, roster)
        print(audit.format_pipeline(audit.pipeline(connection, targets, roster)))
        return 0
    print(audit.format_report(audit.run(connection, roster), verbose))
    return 0


def _domains(database: str, limit: int, workers: int, regrade: bool = False) -> int:
    connection = db.connect(database)
    connection.executescript(domains.SCHEMA)

    if regrade:
        # Grades recorded before a rule changed are stale, and only the host
        # can settle them: corroboration needs the page text, which is not
        # stored. Nothing is deleted -- a demoted row keeps its domain.
        checked, demoted = domains.regrade(connection, limit, workers)
        print(f"re-checked {checked:,d} strong matches, {demoted:,d} demoted to weak")
    else:
        seeded = domains.harvest_registry_domains(connection)
        print(f"seeded {seeded:,d} domains from registry websites")

        attempted, resolved = domains.run(connection, FOCUS_SOURCES, limit, workers)
        if attempted:
            print(f"probed {attempted:,d} firms, {resolved:,d} strong matches")
        else:
            print("nothing left to probe in the focus sources")

    print("\ndomain coverage by focus registry")
    print(f"  {'':18s} {'known':>13s}   registry   fca   strong   weak   unresolved")
    for source, row in domains.coverage(connection, FOCUS_SOURCES):
        # Weak matches are stored but not counted: one word out of several is
        # not proof, and a wrong domain costs a silently empty job feed.
        known = (row["registry"] or 0) + (row["fca"] or 0) + (row["strong"] or 0)
        share = 100 * known / row["firms"] if row["firms"] else 0.0
        print(
            f"  {source:18s} {known:5,d}/{row['firms']:<6,d} ({share:4.1f}%)"
            f"   {row['registry'] or 0:8,d}"
            f"   {row['fca'] or 0:3,d}"
            f"   {row['strong'] or 0:6,d}"
            f"   {row['weak'] or 0:4,d}"
            f"   {row['unresolvable'] or 0:10,d}"
        )
    return 0


def _fca(database: str, limit: int) -> int:
    connection = db.connect(database)
    try:
        looked_up, found = fca.enrich(connection, limit)
    except fca.MissingCredentials as exc:
        print(f"FCA credentials unavailable: {exc}", file=sys.stderr)
        return 1
    print(f"looked up {looked_up:,d} firms, found {found:,d} domains")
    for row in fca.summary(connection):
        print(f"  {row['method']:10s} {row['n']:,d}")
    return 0


def _ats(database: str, limit: int, workers: int, reprobe: bool = False) -> int:
    connection = db.connect(database)
    if reprobe:
        # A pattern added to `ats.py` changes what the stored answers should
        # have been, and nothing re-asks on its own. Promotions only: see
        # `ats.reprobe`.
        checked, promoted, corrected = ats.reprobe(connection, limit, workers)
        print(
            f"re-walked {checked:,d} domains, {promoted:,d} promoted to tier A,"
            f" {corrected:,d} careers pages moved off a platform"
        )
    else:
        tally = ats.run(connection, limit, workers)
        if tally:
            print("resolved " + ", ".join(f"{n} tier {t}" for t, n in sorted(tally.items())))
        else:
            print("nothing left to fingerprint")

    print("\ntiers")
    for row in ats.summary(connection):
        print(f"  {row['tier']}  {row['n']:,d}")
    rows = ats.by_ats(connection)
    if rows:
        print("\nby ATS")
        for row in rows:
            print(f"  {row['ats']:16s} {row['n']:,d}")
    return 0


def _discover(
    database: str, limit: int, roster: bool, workers: int, source: str | None = None
) -> int:
    connection = db.connect(database)
    if roster:
        wanted = discover.roster_targets(connection, audit.load_roster())
        frame = f"{len(wanted)} active roster firms"
    else:
        wanted = [
            discover.Target(row["name"], (row["name"],), row["domain"])
            for row in discover.targets(connection, limit, source)
        ]
        frame = f"{len(wanted)} firms with a domain and no pollable board"
        if source:
            frame += f" in {source}"

    attempted, found, hits = discover.run(connection, wanted, workers)
    if not attempted:
        print("nothing left to discover")
        return 0

    print(f"probed {attempted:,d} of {frame}, verified {found:,d} boards")
    for hit in sorted(hits, key=lambda h: h.query):
        print(f"  {hit.ats:16s} {hit.token:30s} {hit.query[:30]:30s} {hit.evidence}")

    # A board found for a firm with no domain cannot be written to
    # `ats_resolution`, which is keyed on one -- so it is found and then not
    # polled. Naming those is the difference between a queue and a silent loss.
    stranded = [h.query for h in hits if not h.domain]
    if stranded:
        print(f"\n{len(stranded)} board(s) found for a firm holding no domain,")
        print("so nothing polls them yet: " + ", ".join(sorted(stranded)))
    return 0


def _sweep(database: str, name: str, walk, *, partial: bool | None = None):
    """Run one Layer 4 sweep, record it, and hand back what it found.

    **Every national board repeats the same four steps and they are here
    once.** Open the database, run the walk inside `_poll` so a crash still
    reaches `runs`, record the poll, and hand the caller the result to print.
    What differs between the six sources is the *shape of the report*, which is
    the half worth writing out per source; what does not differ is any of this.

    `partial` overrides the sweep's own flag, for the one source that has no
    such flag to read: every poll of job-room.ch is a window, so an ad-hoc
    `--days 6` is an outlier rather than a subset and `alerts` compares against
    a median precisely so one outlier cannot move the baseline.
    """
    connection = db.connect(database)
    started_at, swept = _poll(connection, name, lambda: walk(connection))
    _record_poll(
        connection, name, started_at, swept.seen,
        partial=getattr(swept, "partial", False) if partial is None else partial,
        problem=swept.problem,
    )
    return connection, swept


def _shortfall(swept) -> int:
    """Report a truncated or refused sweep, and make it the exit code.

    **Every walk here audits its own arithmetic against the total the board
    publishes**, because a walk that stopped on a result window, a short page
    or a refusal returns cleanly and looks exactly like a quiet day -- a round
    number in the output is what a cap looks like from outside, and nothing
    else in this pipeline would say so.
    """
    if swept.problem:
        print(f"  FAIL {swept.problem}", file=sys.stderr)
        return 1
    return 0


def _held(connection, ats: str, noun: str, **columns: str) -> None:
    """The "N ads held" line, with whichever extra counts a source can answer."""
    selected = ", ".join(f"{sql} AS {name}" for name, sql in columns.items())
    row = connection.execute(
        f"SELECT COUNT(*) AS n{', ' + selected if selected else ''}"
        " FROM jobs WHERE ats = ?", (ats,)
    ).fetchone()
    extra = "".join(f", {row[name] or 0:,d} {name.replace('_', ' ')}" for name in columns)
    print(f"  {row['n']:,d} {noun} held{extra}")


def _singapore(database: str, since: str | None) -> int:
    connection, swept = _sweep(
        database, mycareersfuture.NAME,
        lambda c: mycareersfuture.run(c, since=since),
    )
    print(
        f"swept {swept.pages:,d} pages: {swept.seen:,d} postings, "
        f"{swept.written:,d} written, {swept.repeats:,d} served twice"
    )
    if not swept.partial:
        print(f"  the portal advertised {swept.advertised:,d}")
    return _shortfall(swept)


def _hongkong(database: str, max_pages: int) -> int:
    connection, swept = _sweep(
        database, iesjobs.NAME, lambda c: iesjobs.run(c, max_pages=max_pages)
    )
    print(
        f"swept {len(swept.slices)} job type(s) over {swept.pages:,d} pages: "
        f"{swept.seen:,d} postings, {swept.written:,d} written, "
        f"{swept.repeats:,d} served twice"
    )
    if not swept.partial:
        # Two numbers, because the walk is a partition: the slices are what
        # was read and the unfiltered total is what should have been. They
        # agreeing is the evidence that the partition is still complete.
        print(f"  the portal advertised {swept.advertised:,d} in total")
    for got in swept.slices:
        print(f"    {got.seen:>5,d} / {got.advertised:<5,d}  {got.name}")
    return _shortfall(swept)


def _denmark(database: str, since: str | None, only: list[int] | None) -> int:
    connection, swept = _sweep(
        database, jobindex.NAME, lambda c: jobindex.run(c, since=since, only=only)
    )
    print(
        f"swept {swept.slices:,d} slice(s) over {swept.pages:,d} pages: "
        f"{swept.seen:,d} postings, {swept.written:,d} written, "
        f"{swept.repeats:,d} seen already"
    )
    if not swept.partial:
        print(f"  the board advertised {swept.advertised:,d}")
    _held(connection, jobindex.NAME, "Danish ads",
          attributed_to_an_employer_domain="SUM(domain IS NOT NULL)",
          with_a_stated_deadline="SUM(deadline IS NOT NULL)")
    # A category the board grew since `SUBCATEGORIES` was written is swept
    # anyway -- the partition is read live -- but the read-time gate in
    # `tagging.py` has never been asked about it, so it is named here.
    if swept.unknown_subcategories:
        named = ", ".join(
            f"{label!r} ({subid})"
            for subid, label in sorted(swept.unknown_subcategories.items())
        )
        print(f"  {len(swept.unknown_subcategories)} new subcategor(ies): {named}")
    return _shortfall(swept)


def _sweden(database: str, pages: int | None) -> int:
    connection, swept = _sweep(
        database, jobbsafari.NAME, lambda c: jobbsafari.run(c, pages=pages)
    )
    print(
        f"swept Jobbsafari over {swept.pages:,d} pages: "
        f"{swept.seen:,d} postings, {swept.written:,d} written, "
        f"{swept.repeats:,d} served twice"
    )
    if not swept.partial:
        print(f"  the board advertised {swept.advertised:,d}")
    _held(connection, jobbsafari.NAME, "Swedish ads",
          with_a_description="SUM(description IS NOT NULL AND description != '')")
    return _shortfall(swept)


def _switzerland(database: str, days: int | None) -> int:
    connection, swept = _sweep(
        database, jobroom_ch.NAME, lambda c: jobroom_ch.run(c, days), partial=False
    )
    print(
        f"polled job-room.ch back {swept.days} day(s) over {swept.pages:,d} pages: "
        f"{swept.seen:,d} postings, {swept.written:,d} written, "
        f"{swept.repeats:,d} served twice"
    )
    print(f"  the portal advertised {swept.advertised:,d}")
    _held(connection, jobroom_ch.NAME, "Swiss ads",
          attributed_to_an_employer_domain="SUM(domain IS NOT NULL)")
    return _shortfall(swept)


def _bodies(database: str, limit: int, workers: int) -> int:
    connection = db.connect(database)
    attempted, filled, placed, named, hong_kong = bodies.run(
        connection, limit, workers
    )
    if attempted:
        # Each is reported separately rather than folded into one total: the
        # pass cures three faults and a single number would hide any of them
        # going quiet.
        print(f"fetched {attempted:,d} pages, filled {filled:,d} bodies,"
              f" resolved {placed:,d} places, named {named:,d} employers")
    else:
        print("nothing left in the queue")

    # **The Hong Kong split, because the cheap route fails quietly.** Its cards
    # are reached either by harvesting a token off a list page -- twenty to a
    # request -- or by searching for one, which costs two requests a posting on
    # a host held to four seconds. If the portal's list markup moves, every
    # posting silently takes the second route and the only symptom is that the
    # step is slow again. `searched` climbing is that symptom, named.
    reached = hong_kong["harvested"] + hong_kong["searched"]
    if reached:
        spent = hong_kong["harvested"] + 2 * hong_kong["searched"]
        print(f"  hong kong: {hong_kong['harvested']:,d} harvested,"
              f" {hong_kong['searched']:,d} searched"
              f" -- about {spent:,d} requests against {2 * reached:,d}")

    print("\nbodies held")
    for row in bodies.coverage(connection):
        held = row["with_body"] or 0
        share = held / row["postings"] if row["postings"] else 0
        print(f"  {row['ats']:16s} {held:6,d} / {row['postings']:6,d}  ({share:.0%})")
    return 0


def _jobs(database: str, limit: int, workers: int) -> int:
    connection = db.connect(database)
    # Layer 3C rides Layer 3: each hand-written reader is an `ats_resolution`
    # row like any board, so it has to exist before `targets` runs. Idempotent,
    # and cheap enough not to need its own command.
    sites.register(connection)
    boards, jobs, failures = extract.run(connection, limit, workers)
    print(f"polled {boards:,d} boards, wrote {jobs:,d} postings")
    for failure in failures[:10]:
        print(f"  FAIL {failure}", file=sys.stderr)
    if len(failures) > 10:
        print(f"  ... and {len(failures) - 10} more", file=sys.stderr)

    print("\npostings by ATS")
    for row in connection.execute(
        "SELECT ats, COUNT(*) AS n, COUNT(DISTINCT token) AS boards"
        " FROM jobs GROUP BY ats ORDER BY n DESC"
    ):
        print(f"  {row['ats']:16s} {row['n']:5,d} from {row['boards']:,d} boards")
    return 0


def _jobstream(database: str, since_text: str | None = None) -> int:
    connection = db.connect(database)
    override = (
        datetime.fromisoformat(since_text).replace(tzinfo=timezone.utc)
        if since_text
        else None
    )
    since = override or jobstream.cursor(connection)
    started_at, (seen, written, withdrawn) = _poll(
        connection, jobstream.NAME, lambda: jobstream.run(connection, override)
    )
    # A replay of a window already polled is a deliberate subset, the same as
    # `--since` one country over.
    _record_poll(connection, jobstream.NAME, started_at, seen,
                 partial=override is not None)
    print(
        f"polled JobStream from {since:%Y-%m-%d %H:%M} UTC: "
        f"{seen:,d} changes, {written:,d} written, {withdrawn:,d} withdrawn"
    )
    _held(connection, jobstream.NAME, "Swedish ads",
          withdrawn="SUM(removed_at IS NOT NULL)")
    return 0


def _pages(database: str, limit: int, workers: int) -> int:
    connection = db.connect(database)
    polled, baselined, changed = pages.run(connection, limit, workers)
    if polled:
        print(
            f"polled {polled:,d} tier-B pages, {baselined:,d} new baselines,"
            f" {changed:,d} changed"
        )
    else:
        print("no tier-B pages to poll")

    row = pages.coverage(connection)
    print(f"\n{row['watched']:,d} of {row['tier_b']:,d} tier-B pages watched")

    recent = pages.recent_changes(connection)
    if recent:
        print("\nmost recently changed")
        for change in recent:
            print(
                f"  {change['changed_at'][:10]}  {change['changes']:2d}x"
                f"  {change['url'][:70]}"
            )
    return 0


def _tag(database: str, limit: int, dimension: str) -> int:
    connection = db.connect(database)
    tagged, written = tagging.run(connection, limit)
    print(f"tagged {tagged:,d} postings, wrote {written:,d} tags")
    # A run that stops exactly on its own limit has almost certainly been cut
    # short, and every summary printed below it then describes a partial
    # re-tag while looking like a whole one. The corpus was 157,520 against a
    # default of 100,000 and nothing said so.
    if tagged >= limit:
        print(
            f"  WARNING stopped on the --limit of {limit:,d}: this is a partial"
            " re-tag, and the counts below cover only what has been reached."
            " Re-run with a larger --limit.",
            file=sys.stderr,
        )

    print(f"\n{dimension}")
    for row in tagging.summary(connection, dimension):
        print(f"  {row['value']:24s} {row['n']:6,d}  ({row['strong'] or 0:,d} strong)")

    rows = tagging.shortlist(connection)
    if rows:
        print(f"\nread these first ({len(rows)})")
        for row in rows:
            print(
                # `hub` is a slash-joined list now, so it is truncated
                # rather than allowed to shove the title off the line.
                f"  {row['fit']:9s} {(row['hub'] or '?')[:11]:11s}"
                f" {(row['title'] or '')[:52]:54s} {(row['location'] or '')[:28]}"
            )
    return 0


def _prune(database: str, apply: bool) -> int:
    connection = db.connect(database)
    stale = tagging.stale_taggers(connection)
    if not stale:
        print(f"nothing to prune -- every tag is at lexicon {tagging.TAGGER}")
        return 0

    total = sum(n for _, n in stale)
    print(f"{len(stale)} superseded lexicon version(s), {total:,d} rows")
    for tagger, n in stale[:12]:
        print(f"  lexicon {tagger:<4d} {n:>10,d}")
    if len(stale) > 12:
        print(f"  ... and {len(stale) - 12} more")

    if not apply:
        # A destructive default is how a derived table becomes an unrecoverable
        # one by accident. The count above is the whole point of the dry run.
        print("\nthis was a dry run -- re-run with --apply to delete")
        return 0

    removed = tagging.prune(connection)
    print(f"\ndeleted {removed:,d} rows; lexicon {tagging.TAGGER} untouched")
    print("run VACUUM separately to return the space to the filesystem")
    return 0


def _coverage(database: str) -> int:
    connection = db.connect(database)

    print("what the pipeline holds, by hub")
    print(f"  {'hub':14s} {'postings':>9s} {'employers':>10s} {'worth reading':>14s}")
    for row in coverage.by_hub(connection):
        print(
            f"  {row['hub']:14s} {row['postings']:9,d} {row['employers']:10,d}"
            f" {row['worth_reading'] or 0:14,d}"
        )

    result = coverage.estimate(connection)
    print(f"\ncapture-recapture, {result.hub} (second source: JobStream)")
    print(f"  ours {result.ours:,d}   theirs {result.theirs:,d}"
          f"   both {result.overlap:,d}")
    if result.population is None:
        print(f"  no estimate -- {result.reason}")
    else:
        print(f"  population ~{result.population:,d}, we poll {result.share:.0%}")
        print(f"  {result.reason}")

    print("\nunmeasured (no second source): " + ", ".join(
        coverage.unmeasured_hubs(connection)))

    # Printed every run, because the assumption it refutes is the kind that
    # creeps back: a national feed reads like a backstop until you measure it.
    spot = coverage.blindspot(connection)
    print(f"\nwhat the national feed does NOT see, {spot.hub}")
    if spot.share is None:
        print("  no employers polled directly here yet -- nothing to compare")
    else:
        print(
            f"  {spot.unseen:,d} of {spot.ours:,d} employers we poll directly"
            f" ({spot.share:.0%}) have no ad in Platsbanken at all"
        )
        print("  " + ", ".join(spot.examples[:8]))
        print("  advertising there is voluntary -- it is a second sample, not a census")

    rows = coverage.missed(connection)
    if rows:
        print(f"\nhiring, reaching us only through the national feed ({len(rows)})")
        for row in rows:
            tier = row["tier"] or "untiered"
            print(f"  {row['ads']:3d} ads  {row['domain'][:40]:42s} {tier} {row['ats'] or ''}")
    return 0


def _list(database: str, args) -> int:
    connection = db.connect(database)

    if args.dimensions:
        for row in tagging.dimensions(connection):
            print(f"  {row['dimension']:18s} {row['value']:22s} {row['n']:7,d}")
        return 0

    def split(value):
        return tuple(v.strip() for v in value.split(",") if v.strip()) if value else ()

    require = {
        "fit": split(args.fit),
        "hub": split(args.hub),
        "relevance": split(args.relevance),
        "seniority": split(args.seniority),
        "role_class": split(args.role),
        "desk": split(args.desk),
        "contract": split(args.contract),
        "language": split(args.language),
    }
    exclude = {
        "exclusion_reason": split(args.exclude),
        "hard_gates": split(args.without),
        "seniority": split(args.not_seniority),
        # A language requirement ranks a posting down rather than gating it, so
        # dropping one is an explicit ask rather than the default.
        "spoken_language": split(args.speaks),
    }

    rows = tagging.search(
        connection, require=require, exclude=exclude, since=args.since,
        limit=args.limit,
    )
    print(f"{len(rows)} posting(s)")
    for row in rows:
        print(
            f"  {(row['fit'] or '-'):9s} {(row['hub'] or '-')[:12]:12s}"
            f" {(row['seniority'] or '-'):12s} {(row['title'] or '')[:44]:46s}"
            f" {(row['location'] or '')[:22]:24s} {row['url'] or ''}"
        )
    return 0


def _sample(database: str, limit: int, out: str) -> int:
    connection = db.connect(database)
    path = Path(out)
    written, kept = labels.draw(connection, limit, path)
    print(f"wrote {written:,d} postings to {path}")
    if kept:
        print(f"  {kept} existing label(s) preserved")
    print("\nfill in `relevance` and `seniority` on each row, then run `labels`.")
    print(f"  relevance   {' | '.join(labels.RELEVANCE)}")
    print(f"  seniority   {' | '.join(labels.SENIORITY)}")
    print("\nthe sheet deliberately does not show what the tagger decided --")
    print("agreeing with a tag that is already there measures nothing.")
    return 0


def _labels(database: str, files: list[str] | None) -> int:
    connection = db.connect(database)
    # `containment` re-tags each labelled posting live rather than reading
    # `job_tags`, so it needs the same board profile `tag` was run with -- or
    # the sheet scores a classifier the board is not using. Same argument as
    # `tagging.GATES` being one definition with two consumers.
    tagging.load_quant_boards(connection)
    paths = [Path(f) for f in (files or labels.SHEETS)]
    per_file: list[tuple[Path, list]] = []
    found: list[labels.Label] = []
    for path in paths:
        rows = labels.load(path)
        if not rows:
            print(f"no labelled rows in {path}", file=sys.stderr)
            continue
        per_file.append((path, rows))
        found.extend(rows)
    if not found:
        print("no labelled rows in any sheet -- run `sample` first", file=sys.stderr)
        return 1

    # A row typed wrongly is reported and skipped, not treated as a reason to
    # score nothing. Refusing the whole file over one shifted cell hides the
    # fifty rows that are fine, and those are the ones with something to say.
    problems = labels.validate(found)
    for problem in problems:
        print(f"SKIP {problem}", file=sys.stderr)
    usable = [
        label for label in found
        if (not label.relevance or label.relevance in labels.RELEVANCE)
        and (not label.seniority or label.seniority in labels.SENIORITY)
    ]
    if not usable:
        print("nothing usable in the file", file=sys.stderr)
        return 1

    rates, disagreements = labels.score(connection, usable)
    print(f"scored {len(usable)} labelled posting(s) against tagger {tagging.TAGGER}")
    if len(per_file) > 1:
        for path, rows in per_file:
            keep = [l for l in usable if l in set(rows)]
            sub, _ = labels.score(connection, keep)
            parts = " ".join(
                f"{d}={h}/{t} {s:.1%}" for d, (h, t, s) in sub.items()
            )
            print(f"    {path.name:22s} {len(keep):4d} rows   {parts}")

    # **A disagreement and a non-answer are different facts, and one number
    # hid the difference.** The tagger reads rank from the title and returns
    # `unknown` when the title states none; the sheet is filled in by a person
    # who has read the body. Those rows are not the tagger being wrong -- they
    # are the tagger declining to guess, which was chosen deliberately after a
    # stray *partner* in a diversity paragraph made an internship a managing
    # director.
    #
    # Reporting them together made `seniority` look like a broken classifier
    # when most of the gap is a scale that asks a question this tagger does
    # not answer. Both numbers are printed because the honest reading needs
    # both: `wrong` is what a lexicon fix can move, `silent` is not.
    silent = {"relevance": 0, "seniority": 0}
    for d in disagreements:
        if d.dimension in silent and d.tagged == "unknown":
            silent[d.dimension] += 1
    for dimension, (hits, total, share) in rates.items():
        quiet = silent.get(dimension, 0)
        wrong = total - hits - quiet
        decided = total - quiet
        extra = ""
        if quiet:
            share_of_read = hits / decided if decided else 0.0
            extra = (f"   ({wrong} wrong, {quiet} unanswered"
                     f" -- {share_of_read:.1%} of the {decided} it decided)")
        print(f"  {dimension:12s} {hits:3d}/{total:<3d} {share:6.1%}{extra}")

    # The asymmetry the whole project runs on: a posting wrongly thrown away is
    # the expensive failure, a false positive costs a few seconds of reading.
    missed = [d for d in disagreements if d.false_rejection]
    if missed:
        # **Each line says which sheet it came from**, because three sheets of
        # unequal quality are scored together and this list is the criterion
        # the whole project is tuned against. A false rejection in
        # `labels.csv` is a bug; one in `agent_labels.csv` is usually the
        # model labeller having been told to prefer `adjacent` when torn, and
        # it duly called `Slack Administrator` adjacent. Without the
        # provenance the two read identically and the number that matters is
        # buried in the noise.
        by_sheet = Counter(d.sheet or "(unnamed)" for d in missed)
        tally = ", ".join(f"{n} in {name}" for name, n in by_sheet.most_common())
        print(f"\nFALSE REJECTIONS ({len(missed)}) -- postings the lexicon threw away")
        print(f"  {tally}")
        for d in missed:
            print(f"  {d.title[:56]:58s} you: {d.labelled:14s} [{d.sheet}]")
            print(f"    {d.evidence[:100]}")

    other = [d for d in disagreements if not d.false_rejection]
    if other:
        print(f"\ndisagreements ({len(other)})")
        for d in other:
            print(f"  {d.dimension:10s} you: {d.labelled:14s} tagger: {d.tagged:14s}"
                  f" {d.title[:40]}")
            if d.evidence:
                print(f"    on {d.evidence[:96]}")

    # **The criterion gates on relevance and on the hand sheet**, and both
    # halves are decisions rather than conveniences.
    #
    # *Relevance only.* Rung agreement cannot reach the bar and should not: a
    # third of the labelled rows state no grade, where the tagger answers
    # `unknown` on purpose, and closing that gap means letting a body set rank
    # again. `containment` below asks the question that has consequences.
    #
    # *The hand sheet.* The machine sheet is scored beside it and is a real
    # diagnostic -- it found the `underwriting` bug, worth 1,834 postings, that
    # eighty hand rows never could. It is not the bar: its rubric prefers the
    # generous label when torn, so its "false rejections" contradict the
    # reader's own hand labels rather than the lexicon.
    hand = [label for path, rows in per_file if path == labels.PATH for label in rows]
    hand_rates, hand_disagreements = (
        labels.score(connection, [l for l in usable if l in set(hand)])
        if hand else (rates, disagreements)
    )
    hand_missed = [d for d in hand_disagreements if d.false_rejection]
    hand_relevance = hand_rates["relevance"]

    # Seniority is back on the bar, at the reader's request and measured by
    # what they said it is for: keeping leadership postings off the board. See
    # `labels.containment` for why rung agreement is the wrong number.
    kept, graded, lost = labels.containment(
        connection, [l for l in usable if l in set(hand)] if hand else usable,
        tagging.GATES, tagging.tag_posting,
    )
    contained = kept / graded if graded else 1.0

    passed = (
        not hand_missed
        and hand_relevance[2] >= 0.90
        and contained >= 0.90
        and rates["relevance"][1] >= 100
    )
    print(
        f"\nrelevance {hand_relevance[2]:.1%} on the hand sheet"
        f" ({hand_relevance[0]}/{hand_relevance[1]}),"
        f" {len(hand_missed)} false rejection(s),"
        f" {rates['relevance'][1]} labelled rows scored"
    )
    if missed and not hand_missed:
        print(f"  {len(missed)} false rejection(s) on the machine sheet are"
              " reported above and do not gate -- read them, do not trust them")
    print(f"seniority: {kept}/{graded} leadership postings kept off the board"
          f" ({contained:.1%}), {lost} opening(s) lost to the rank gate")
    print("\n" + ("exit criterion met" if passed else "exit criterion not met"))
    return 0 if passed else 1


def _alerts(database: str) -> int:
    connection = db.connect(database)
    found = alerts.check(connection)
    never_run = alerts.coverage(connection)

    for alert in found:
        print(alert, file=sys.stderr)
    for source in never_run:
        print(f"{'unrun':8s} {source:20s} registered but never fetched", file=sys.stderr)

    if not found and not never_run:
        print("all sources healthy")
        return 0
    # Non-zero so a scheduled run fails visibly instead of scrolling past.
    print(f"{len(found) + len(never_run)} alert(s)", file=sys.stderr)
    return 1


def _corrections(endpoint: str) -> int:
    """Pull hand corrections made on the live board back into labels.csv.

    The deployed board is a bucket behind a CDN with no server of its own, so
    a Reject click there (or a relevance/seniority override) has nowhere
    local to land -- it used to reach only that browser's `localStorage`.
    `functions/correction_writer` is the other half: a small Lambda the board
    posts to instead, appending into one JSON blob in the same bucket the
    board's own files live in. This reads that blob back and calls the same
    `labels.upsert` that `web/serve.py` calls for a correction made locally,
    so a click made on a phone reaches the tagger the same way one made at a
    desk running `serve.py` does -- on the next pull rather than immediately.

    Safe to run repeatedly: `labels.upsert` overwrites keyed on
    (ats, token, job_id), so re-pulling the same corrections is a no-op.
    """
    try:
        raw = http.get_text(endpoint)
    except Exception as exc:  # noqa: BLE001 -- report and exit, nothing else running
        print(f"could not reach {endpoint}: {exc}", file=sys.stderr)
        return 1

    data = json.loads(raw or "{}")
    if not data:
        print("no corrections pending")
        return 0

    for entry in data.values():
        key = (entry["ats"], entry["token"], entry["job_id"])
        context = {name: entry.get(name, "") for name in labels.CONTEXT}
        labels.upsert(
            labels.PATH, key, labels.DIMENSION_NAMES[entry["dim"]],
            entry.get("value", ""), context,
        )
    print(f"pulled {len(data)} correction(s) into {labels.PATH}")
    return 0


def _stats(database: str) -> int:
    connection = db.connect(database)

    print("employers by source")
    for row in connection.execute(
        "SELECT source, jurisdiction, COUNT(*) AS n,"
        " SUM(website IS NOT NULL) AS with_site"
        " FROM employers GROUP BY source, jurisdiction ORDER BY n DESC"
    ):
        print(
            f"  {row['source']:10s} {row['jurisdiction']:3s} {row['n']:7,d}"
            f"  ({row['with_site']:,d} with a website)"
        )

    firms = connection.execute(
        "SELECT COUNT(*) AS n, SUM(row_count > 1) AS merged,"
        " SUM(source_count > 1) AS cross_source FROM firms"
    ).fetchone()
    if firms["n"]:
        rows = connection.execute("SELECT COUNT(*) FROM employers").fetchone()[0]
        print(
            f"\nresolved into {firms['n']:,d} firms from {rows:,d} rows"
            f" ({rows - firms['n']:,d} collapsed;"
            f" {firms['cross_source']:,d} seen by more than one registry)"
        )

    print("\nlast run per source")
    for row in connection.execute(
        "SELECT source, MAX(started_at) AS at, row_count, ok, error"
        " FROM runs GROUP BY source ORDER BY source"
    ):
        status = "ok" if row["ok"] else f"FAIL ({row['error']})"
        print(f"  {row['source']:10s} {row['at']}  {row['row_count']:7,d}  {status}")

    return 0


def _denmark_since(connection) -> str | None:
    """The date a Jobindex top-up should read back to, or None to sweep it all.

    The top-up is one unfiltered query and the board's own result window holds
    1,000 postings against roughly 600 published a day -- so it reaches about a
    day and a half and no further. That is a daily poll, and it is only honest
    while the poll actually happens daily.

    So the date comes from the newest Danish row we hold rather than from the
    calendar: run it two days running and it asks for a day, leave it a
    fortnight and the gap is wider than the window can serve, which is the case
    that has to fall back to the full taxonomy sweep instead of quietly
    fetching the most recent 1,000 and reporting success. Same shape as the
    short page that cost Jobbsafari 43,000 postings -- the cheap answer and the
    complete one look identical from outside unless something checks.
    """
    row = connection.execute(
        "SELECT MAX(first_seen) AS newest FROM jobs WHERE ats = ?",
        (jobindex.NAME,),
    ).fetchone()
    if not row or not row["newest"]:
        return None
    newest = datetime.fromisoformat(row["newest"].replace("Z", "+00:00"))
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    gap = datetime.now(timezone.utc) - newest
    if gap.days > 2:
        print(
            f"  Denmark: {gap.days} days since the last Danish row, which is"
            " wider than the one-query window -- sweeping every category instead"
        )
        return None
    # A day of slack. A duplicate costs an idempotent upsert and a gap costs a
    # posting, which is the same trade JobStream's cursor makes.
    return (newest - timedelta(days=1)).date().isoformat()


class _ThreadStream:
    """A `sys.stdout` that routes each thread's writes to its own buffer.

    **Concurrent steps cannot share a terminal**, and the usual tool for this
    does not work here: `contextlib.redirect_stdout` swaps a process-global, so
    six steps running at once would each capture the other five. Interleaving
    them raw is worse than slow -- the whole value of `daily`'s output is that
    `alerts` names the source that went quiet, and a report shredded across six
    writers is one nobody reads.

    So each worker registers a buffer for its own thread and everything else
    falls through to the real stream. The buffers are printed whole, in the
    order the steps were listed, once the phase ends.
    """

    def __init__(self, fallback):
        self._fallback = fallback
        self._local = threading.local()

    def claim(self, buffer) -> None:
        self._local.buffer = buffer

    def write(self, text: str) -> int:
        return (getattr(self._local, "buffer", None) or self._fallback).write(text)

    def flush(self) -> None:
        (getattr(self._local, "buffer", None) or self._fallback).flush()

    def isatty(self) -> bool:
        return False


def _gather(steps: list[tuple[str, Callable[[], int]]]) -> list[str]:
    """Run independent steps at once. Returns the names that failed.

    **These are different hosts, and that is the whole argument.**
    `http._throttle` books its interval per host under a lock, so running six
    source sweeps side by side cannot make any one of them see more traffic
    than it does today -- measured: twelve concurrent callers to a single host
    still take eleven seconds for twelve slots, while four slots across three
    hosts go 9.0s -> 3.0s. Politeness is a per-host property and this changes
    only how many hosts are in flight.

    What it buys is the difference between the sum of the sweeps and the
    longest of them. Measured on the 27 August run and today's: Denmark 33.6
    min, Sweden 4.3, Switzerland 0.8, Singapore ~70, Hong Kong ~50 -- about
    160 minutes end to end, against ~70 for the longest. The database was
    already built for it: `db.connect` sets `busy_timeout` to 60s and WAL
    precisely so the long queues "are meant to be run side by side", and six
    concurrent writers committing 240 times measured 0.08s with no error.

    **Threads rather than subprocesses, deliberately.** Separate processes
    would each keep their own `http._last_hit`, so two steps that happen to
    share a host -- `jobs` and `pages` both reach firm domains -- would each
    grant themselves the full rate and quietly double it. One process, one
    throttle table, one guarantee.
    """
    if not steps:
        return []
    reports: dict[str, tuple[int | None, str, str]] = {}
    stream = _ThreadStream(sys.stdout)
    errors = _ThreadStream(sys.stderr)

    def run(item: tuple[str, Callable[[], int]]):
        name, step = item
        out, err = io.StringIO(), io.StringIO()
        stream.claim(out)
        errors.claim(err)
        try:
            code = step()
        except Exception as exc:  # noqa: BLE001 - one source must not stop the rest
            print(f"  FAIL {name}: {exc}", file=err)
            code = None
        return name, code, out.getvalue(), err.getvalue()

    previous = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stream, errors
    try:
        with ThreadPoolExecutor(max_workers=len(steps)) as pool:
            for name, code, out, err in pool.map(run, steps):
                reports[name] = (code, out, err)
    finally:
        sys.stdout, sys.stderr = previous

    failed = []
    for name, _ in steps:
        code, out, err = reports[name]
        print(f"\n=== {name} ===", flush=True)
        if out.strip():
            print(out.rstrip())
        if err.strip():
            print(err.rstrip(), file=sys.stderr)
        if code != 0:
            failed.append(name)
    return failed


def _daily(database: str, full: bool, publish: bool) -> int:
    """Run the standing sequence end to end, so a refresh is one command.

    **This is the compute-intensive half and it runs here, on demand.** Nothing
    schedules it: the national boards are a few hundred requests, the re-tag is
    minutes of CPU, and both are free on this machine and billable on anybody
    else's. What gets deployed is the *output* -- see `web/publish.py`.

    A step that fails does not stop the run. The sources are independent, and a
    board that has been redesigned underneath us should cost its own postings
    and not the other eight sources' -- nor the re-tag, nor the rebuild, which
    would otherwise leave the board serving yesterday's file with no sign of
    why. `alerts` runs at the end and is the thing that says which source went
    quiet; the exit code says whether anything did.
    """
    root = Path(__file__).resolve().parent.parent
    connection = db.connect(database)
    since = None if full else _denmark_since(connection)
    connection.close()

    # **The tagger runs twice, and the second pass is not belt-and-braces.**
    # `bodies.targets` reads `job_tags` to find postings the tagger could not
    # place, so a posting scraped ten minutes ago is not in that queue at all
    # -- it has no verdict yet. Tag first and it does; then `bodies` fetches
    # the descriptions and retires the title-only verdicts it just
    # invalidated, and the second pass re-reads them with the body in front of
    # it. Running `bodies` first is what the sequence used to do, and it meant
    # every posting spent its first day judged on a six-word title.
    #
    # Neither pass is expensive: `tag` visits only postings with no row at the
    # current version.
    # **Three phases, and the middle one runs at once.** The sources are
    # independent and live on different hosts, so running them in sequence
    # spent the *sum* of their walks where the longest of them would do --
    # measured, about 160 minutes against about 70. `_gather` explains why
    # that costs no politeness: `http._throttle` books per host, so this
    # changes how many hosts are in flight and nothing about the rate any one
    # of them sees.
    #
    # What has to stay serial is anything that reads what an earlier step
    # wrote. `corrections` goes first so a Reject clicked on the live board
    # reaches `labels.csv` before this run's `tag`; `tag`, `bodies` and the
    # re-tag are a chain by construction; `alerts` reports on the runs the
    # gather phase recorded.
    prologue: list[tuple[str, Callable[[], int]]] = [
        # Cheap (one GET) and unrelated to the rest.
        ("corrections", lambda: _corrections(CORRECTIONS_ENDPOINT)),
    ]

    # Every one of these is a different host, which is the precondition for
    # running them together and the thing to re-check before adding a fourth.
    gathered: list[tuple[str, Callable[[], int]]] = [
        ("sweden", lambda: _sweden(database, None)),
        ("denmark", lambda: _denmark(database, since, None)),
        ("switzerland", lambda: _switzerland(database, None)),
        ("jobstream", lambda: _jobstream(database, None)),
        # `jobs` and `pages` are already twelve-thread pools of their own, and
        # they belong here for the same reason: their hosts are the ATS
        # vendors and the firms' own domains, which no portal sweep touches.
        # Where they *do* overlap each other, one shared throttle table is
        # what keeps the guarantee -- see `_gather`.
        ("jobs", lambda: _jobs(database, 2_000, 12)),
        ("pages", lambda: _pages(database, 4_000 if full else 500, 12)),
    ]

    epilogue: list[tuple[str, Callable[[], int]]] = [
        ("tag", lambda: _tag(database, 1_000_000, "fit")),
        ("bodies", lambda: _bodies(database, 20_000 if full else 2_000, 12)),
        ("re-tag", lambda: _tag(database, 1_000_000, "fit")),
        ("alerts", lambda: _alerts(database)),
    ]

    if full:
        # **Both national portals are weekly and for the same reason.** Neither
        # has an incremental form worth using -- only a completed walk refreshes
        # `last_seen` on every live row, which is the sole way a withdrawal is
        # ever noticed on a board this project does not otherwise poll -- and
        # each is an hour of deliberately slow requests: Singapore ~940 pages
        # at four seconds, Hong Kong ~750 at the same. They are in `--full`
        # for that reason alone, not because either is optional.
        #
        # They are also what makes the gather phase worth having: serially
        # they are two hours on their own, concurrently they are the longer of
        # the two and everything else hides underneath them.
        gathered.insert(0, ("singapore", lambda: _singapore(database, None)))
        gathered.insert(1, ("hongkong", lambda: _hongkong(database, iesjobs.MAX_PAGES)))

    failed: list[str] = []

    def serially(steps: list[tuple[str, Callable[[], int]]]) -> None:
        for name, step in steps:
            print(f"\n=== {name} ===", flush=True)
            try:
                if step() != 0:
                    failed.append(name)
            except Exception as exc:  # noqa: BLE001 - one source must not stop the rest
                print(f"  FAIL {name}: {exc}", file=sys.stderr)
                failed.append(name)

    serially(prologue)
    print(f"\n=== gathering {len(gathered)} sources at once ===", flush=True)
    failed.extend(_gather(gathered))
    serially(epilogue)

    print("\n=== board ===", flush=True)
    script = "publish.py" if publish else "build_data.py"
    done = subprocess.run([sys.executable, str(root / "web" / script)], cwd=root)
    if done.returncode != 0:
        failed.append(script)

    if failed:
        print(f"\n{len(failed)} step(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nevery step ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantscraper", description=__doc__)
    parser.add_argument(
        "--db", default=str(db.DEFAULT_PATH), help="path to the SQLite database"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="pull employers from registries")
    fetch.add_argument(
        "registries",
        nargs="*",
        choices=[*REGISTRIES, []],
        help="registries to fetch (default: all)",
    )
    commands.add_parser("resolve", help="group employer rows into firms")
    commands.add_parser("stats", help="show what is in the database")
    audit_command = commands.add_parser(
        "audit", help="check the universe against the named roster"
    )
    audit_command.add_argument(
        "-v", "--verbose", action="store_true", help="list what each hit matched"
    )
    audit_command.add_argument(
        "--pipeline",
        action="store_true",
        help="measure the job pipeline instead of the universe: which roster"
        " firms actually produce postings, which is a different property and"
        " was 16/163 while every hub reported 100%% present",
    )
    domains_command = commands.add_parser(
        "domains", help="resolve firm names to domains (Layer 2)"
    )
    domains_command.add_argument(
        "--limit", type=int, default=500, help="firms to probe this run"
    )
    domains_command.add_argument(
        "--workers", type=int, default=12, help="parallel probes"
    )
    domains_command.add_argument(
        "--regrade",
        action="store_true",
        help="re-check recorded strong matches against the current rule",
    )

    fca_command = commands.add_parser(
        "fca", help="enrich firms with FCA register websites (needs .env)"
    )
    fca_command.add_argument(
        "--limit", type=int, default=300, help="firms to look up this run"
    )

    ats_command = commands.add_parser(
        "ats", help="fingerprint careers hosts to an ATS (Layer 2)"
    )
    ats_command.add_argument("--limit", type=int, default=500)
    ats_command.add_argument("--workers", type=int, default=12)
    ats_command.add_argument(
        "--reprobe",
        action="store_true",
        help="re-walk tier B and tokenless tier A, which a new pattern may now"
        " fingerprint; promotions only, never a demotion",
    )

    discover_command = commands.add_parser(
        "discover", help="find the board a careers page never named (Layer 2C)"
    )
    discover_command.add_argument("--limit", type=int, default=200)
    discover_command.add_argument(
        "--roster",
        action="store_true",
        help="sweep the audit roster instead of the general queue",
    )
    discover_command.add_argument("--workers", type=int, default=6)
    discover_command.add_argument(
        "--source",
        help="scope the general queue to one registry, e.g. sfc_hk. Without it"
        " the queue is ordered by how many registries saw a firm, so a hub"
        " whose firms hold a single licence is never reached by --limit",
    )

    singapore_command = commands.add_parser(
        "singapore", help="sweep MyCareersFuture, Singapore's statutory portal"
    )
    singapore_command.add_argument(
        "--since",
        help="only read back to this ISO date -- a top-up between full sweeps,"
        " which are cheap enough (~850 requests) to just do",
    )

    hongkong_command = commands.add_parser(
        "hongkong",
        help="sweep the Interactive Employment Service, Hong Kong's statutory portal",
    )
    hongkong_command.add_argument(
        "--max-pages",
        type=int,
        default=iesjobs.MAX_PAGES,
        help="stop after this many pages. A bound below the default marks the"
        " sweep partial, so a probe run can never be reported as a complete"
        " one. It bounds each of the 29 job-type slices, and the whole board"
        " is ~750 requests and about 50 minutes",
    )

    denmark_command = commands.add_parser(
        "denmark", help="sweep Jobindex, Denmark's largest job board"
    )
    denmark_command.add_argument(
        "--since",
        help="top up from the unfiltered board back to this ISO date instead of"
        " sweeping every category. One query reaches 1,000 postings and the"
        " board publishes roughly 600 a day, so this is a daily poll and it"
        " says so if the window ran out before the date did",
    )
    denmark_command.add_argument(
        "--only",
        help="sweep just these subcategory ids, comma separated -- 35 is"
        " Finans og forsikring, 45 Forskning, 1 Systemudvikling. For probing a"
        " reader change without walking all eighty",
    )

    sweden_command = commands.add_parser(
        "sweden", help="sweep Jobbsafari, Sweden's widest job board"
    )
    sweden_command.add_argument(
        "--pages",
        type=int,
        help="stop after this many pages -- a probe against a few hundred live"
        " rows. The whole board is about a hundred pages, so the default is to"
        " walk all of it",
    )

    switzerland_command = commands.add_parser(
        "switzerland", help="poll job-room.ch, Switzerland's public employment service"
    )
    switzerland_command.add_argument(
        "--days",
        type=int,
        help="read back this many days instead of using the stored cursor."
        " The portal holds a rolling 60-day window and a single query can only"
        " reach 20,000 postings, which is roughly two days",
    )

    bodies_command = commands.add_parser(
        "bodies", help="fetch descriptions a list endpoint omitted (Layer 3C)"
    )
    bodies_command.add_argument("--limit", type=int, default=2000)
    bodies_command.add_argument("--workers", type=int, default=12)

    jobs_command = commands.add_parser(
        "jobs", help="pull postings from resolved ATS boards (Layer 3)"
    )
    jobs_command.add_argument("--limit", type=int, default=100)
    jobs_command.add_argument("--workers", type=int, default=12, help="parallel boards")

    jobstream_command = commands.add_parser(
        "jobstream", help="poll Sweden's JobTech delta feed (Layer 4)"
    )
    jobstream_command.add_argument(
        "--since",
        help="replay from this UTC timestamp instead of the stored cursor,"
        " e.g. 2026-08-12 -- for backfilling a newly added column",
    )

    pages_command = commands.add_parser(
        "pages", help="watch tier-B careers pages for change (Layer 3B)"
    )
    pages_command.add_argument("--limit", type=int, default=500)
    pages_command.add_argument("--workers", type=int, default=12)

    tag_command = commands.add_parser(
        "tag", help="classify postings into rankable tags (Layer 5)"
    )
    # High enough to cover the whole corpus in one pass. This is a guard
    # against a runaway, not a batch size: a default that silently stops
    # part-way through a re-tag leaves the summaries describing a mixture.
    tag_command.add_argument("--limit", type=int, default=1_000_000)
    tag_command.add_argument(
        "--dimension", default="fit", help="dimension to summarise afterwards"
    )

    list_command = commands.add_parser(
        "list", help="filter tagged postings (Layer 5, read side)"
    )
    list_command.add_argument("--fit", help="apply_now,strong,plausible,stretch")
    list_command.add_argument("--hub", help="stockholm,amsterdam,...")
    list_command.add_argument(
        "--relevance", help="relevant,less_relevant,adjacent,rejected")
    list_command.add_argument("--seniority", help="junior_0_2,new_grad,mid_3_5,...")
    list_command.add_argument("--not-seniority", help="drop these seniorities")
    list_command.add_argument(
        "--role", help="quant_research,quant_dev,trading,operations,...")
    list_command.add_argument("--desk", help="front_office,middle_office,back_office")
    list_command.add_argument("--contract", help="internship,permanent,fixed_term,...")
    list_command.add_argument("--language", help="python,cplusplus,...")
    list_command.add_argument(
        "--speaks", help="drop postings requiring these: dutch,german,mandarin,...")
    list_command.add_argument("--exclude", help="crypto_web3,actuarial,...")
    list_command.add_argument("--without", help="hard gates to drop: phd_required,...")
    list_command.add_argument("--since", help="first seen on or after, ISO date")
    list_command.add_argument("--limit", type=int, default=50)
    list_command.add_argument(
        "--dimensions", action="store_true", help="show every filterable value"
    )

    sample_command = commands.add_parser(
        "sample", help="draw postings to hand-label (writes labels.csv)"
    )
    sample_command.add_argument("--limit", type=int, default=100)
    sample_command.add_argument(
        "--out", default=str(labels.PATH), help="where to write the sheet"
    )

    labels_command = commands.add_parser(
        "labels", help="score the lexicon against the hand-labelled sample"
    )
    # Repeatable, and both sheets by default. The machine-labelled sheet was
    # built as a diagnostic and explicitly not as the criterion -- "a model
    # grading a model agrees with it for the wrong reasons". The user has since
    # read it and confirmed the labels, which is what makes it evidence rather
    # than an echo, so it is scored alongside the hand sheet. Each file is
    # still reported on its own line, because their provenance differs and a
    # combined number alone would hide that.
    labels_command.add_argument(
        "--file", action="append", default=None,
        help="a labelled sheet to read; repeatable. Defaults to both sheets.",
    )

    prune_command = commands.add_parser(
        "prune", help="delete tags written by superseded lexicon versions"
    )
    prune_command.add_argument(
        "--apply", action="store_true",
        help="actually delete; without it this only reports what would go",
    )

    commands.add_parser(
        "coverage", help="estimate how much of the market we see (Stage 10)"
    )

    commands.add_parser(
        "alerts", help="flag sources that broke quietly (Layer 0 health)"
    )

    corrections_command = commands.add_parser(
        "corrections",
        help="pull hand corrections made on the live board into labels.csv",
    )
    corrections_command.add_argument(
        "--endpoint", default=CORRECTIONS_ENDPOINT,
        help="the live board's correction-reading Lambda (default: the deployed one)",
    )

    daily_command = commands.add_parser(
        "daily", help="run the standing sequence and rebuild the board"
    )
    daily_command.add_argument(
        "--full",
        action="store_true",
        help="sweep every Jobindex category and MyCareersFuture too, and widen"
        " the page and body queues -- a weekly, against a daily that tops up"
        " from where the data already reaches",
    )
    daily_command.add_argument(
        "--publish",
        action="store_true",
        help="push the rebuilt board to quantjobs.spawned.app afterwards"
        " (`web/publish.py`, which is also runnable on its own)",
    )

    args = parser.parse_args(argv)
    # One entry per command, where the chain of `if args.command == ...` that
    # used to be here was thirty lines whose only variable was which arguments
    # each handler wanted. Lambdas rather than partials so the argument names
    # stay visible; nothing is evaluated until the one that is looked up.
    handlers = {
        "fetch": lambda: _fetch(args.registries or list(REGISTRIES), args.db),
        "resolve": lambda: _resolve(args.db),
        "stats": lambda: _stats(args.db),
        "audit": lambda: _audit(args.db, args.verbose, args.pipeline),
        "domains": lambda: _domains(args.db, args.limit, args.workers, args.regrade),
        "fca": lambda: _fca(args.db, args.limit),
        "ats": lambda: _ats(args.db, args.limit, args.workers, args.reprobe),
        "discover": lambda: _discover(
            args.db, args.limit, args.roster, args.workers, args.source),
        "jobs": lambda: _jobs(args.db, args.limit, args.workers),
        "pages": lambda: _pages(args.db, args.limit, args.workers),
        "bodies": lambda: _bodies(args.db, args.limit, args.workers),
        "singapore": lambda: _singapore(args.db, args.since),
        "hongkong": lambda: _hongkong(args.db, args.max_pages),
        "denmark": lambda: _denmark(
            args.db, args.since,
            [int(part) for part in args.only.split(",")] if args.only else None),
        "sweden": lambda: _sweden(args.db, args.pages),
        "switzerland": lambda: _switzerland(args.db, args.days),
        "jobstream": lambda: _jobstream(args.db, args.since),
        "tag": lambda: _tag(args.db, args.limit, args.dimension),
        "list": lambda: _list(args.db, args),
        "sample": lambda: _sample(args.db, args.limit, args.out),
        "labels": lambda: _labels(args.db, args.file),
        "prune": lambda: _prune(args.db, args.apply),
        "coverage": lambda: _coverage(args.db),
        "corrections": lambda: _corrections(args.endpoint),
        "alerts": lambda: _alerts(args.db),
        "daily": lambda: _daily(args.db, args.full, args.publish),
    }
    return handlers[args.command]()


if __name__ == "__main__":
    sys.exit(main())
