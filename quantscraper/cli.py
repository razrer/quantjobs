"""Command line entry point: `python -m quantscraper ...`"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

from . import (
    alerts, ats, audit, bodies, coverage, db, discover, domains, extract,
    fca, jobstream, labels, mycareersfuture, pages, resolve, tagging,
)
from .registries import REGISTRIES

# The registries covering the focus hubs. Domain resolution starts here because
# these are the firms with no website at all; the SEC already publishes one for
# most of its filers.
FOCUS_SOURCES = ("fi_se", "afm_nl", "finanstilsynet_dk", "mas_sg", "sfc_hk", "seed")


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


def _audit(database: str, verbose: bool) -> int:
    connection = db.connect(database)
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'firms'"
    ).fetchone():
        print("no firms table -- run `resolve` first", file=sys.stderr)
        return 1
    print(audit.format_report(audit.run(connection, audit.load_roster()), verbose))
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


def _ats(database: str, limit: int, workers: int) -> int:
    connection = db.connect(database)
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


def _discover(database: str, limit: int, roster: bool, workers: int) -> int:
    connection = db.connect(database)
    if roster:
        wanted = discover.roster_targets(connection, audit.load_roster())
        frame = f"{len(wanted)} active roster firms"
    else:
        wanted = [
            discover.Target(row["name"], (row["name"],), row["domain"])
            for row in discover.targets(connection, limit)
        ]
        frame = f"{len(wanted)} firms with a domain and no pollable board"

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


def _singapore(database: str, since: str | None) -> int:
    connection = db.connect(database)
    swept = mycareersfuture.run(connection, since=since)
    print(
        f"swept {swept.pages:,d} pages: {swept.seen:,d} postings, "
        f"{swept.written:,d} written, {swept.repeats:,d} served twice"
    )
    if not swept.partial:
        print(f"  the portal advertised {swept.advertised:,d}")
    # The sweep audits its own arithmetic: a round number in the output is
    # what a cap looks like from the outside, and nothing else would say so.
    if swept.problem:
        print(f"  FAIL {swept.problem}", file=sys.stderr)
        return 1
    return 0


def _bodies(database: str, limit: int, workers: int) -> int:
    connection = db.connect(database)
    attempted, filled = bodies.run(connection, limit, workers)
    if attempted:
        print(f"fetched {attempted:,d} descriptions, filled {filled:,d}")
    else:
        print("no body-less postings left in the queue")

    print("\nbodies held")
    for row in bodies.coverage(connection):
        held = row["with_body"] or 0
        share = held / row["postings"] if row["postings"] else 0
        print(f"  {row['ats']:16s} {held:6,d} / {row['postings']:6,d}  ({share:.0%})")
    return 0


def _jobs(database: str, limit: int, workers: int) -> int:
    connection = db.connect(database)
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
    seen, written, withdrawn = jobstream.run(connection, override)
    print(
        f"polled JobStream from {since:%Y-%m-%d %H:%M} UTC: "
        f"{seen:,d} changes, {written:,d} written, {withdrawn:,d} withdrawn"
    )
    row = connection.execute(
        "SELECT COUNT(*) AS n, SUM(removed_at IS NOT NULL) AS gone"
        " FROM jobs WHERE ats = ?", (jobstream.NAME,)
    ).fetchone()
    print(f"  {row['n']:,d} Swedish ads held, {row['gone'] or 0:,d} withdrawn")
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
                f"  {row['fit']:9s} {(row['hub'] or '?'):11s}"
                f" {(row['title'] or '')[:52]:54s} {(row['location'] or '')[:28]}"
            )
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
            f"  {(row['fit'] or '-'):9s} {(row['hub'] or '-'):12s}"
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
    # are the tagger declining to guess, which is the behaviour `PLAN.md`
    # chose deliberately after a stray *partner* in a diversity paragraph made
    # an internship a managing director.
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
        print(f"\nFALSE REJECTIONS ({len(missed)}) -- postings the lexicon threw away")
        for d in missed:
            print(f"  {d.title[:56]:58s} you: {d.labelled}")
            print(f"    {d.evidence[:100]}")

    other = [d for d in disagreements if not d.false_rejection]
    if other:
        print(f"\ndisagreements ({len(other)})")
        for d in other:
            print(f"  {d.dimension:10s} you: {d.labelled:14s} tagger: {d.tagged:14s}"
                  f" {d.title[:40]}")
            if d.evidence:
                print(f"    on {d.evidence[:96]}")

    # `TAGGING.md`: at least 90% on both dimensions, and no false rejection.
    passed = (
        not missed
        and all(share >= 0.90 for _, _, share in rates.values())
        and rates["relevance"][1] >= 100
    )
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

    singapore_command = commands.add_parser(
        "singapore", help="sweep MyCareersFuture, Singapore's statutory portal"
    )
    singapore_command.add_argument(
        "--since",
        help="only read back to this ISO date -- a top-up between full sweeps,"
        " which are cheap enough (~850 requests) to just do",
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

    commands.add_parser(
        "coverage", help="estimate how much of the market we see (Stage 10)"
    )

    commands.add_parser(
        "alerts", help="flag sources that broke quietly (Layer 0 health)"
    )

    args = parser.parse_args(argv)
    if args.command == "list":
        return _list(args.db, args)
    if args.command == "sample":
        return _sample(args.db, args.limit, args.out)
    if args.command == "labels":
        return _labels(args.db, args.file)
    if args.command == "coverage":
        return _coverage(args.db)
    if args.command == "tag":
        return _tag(args.db, args.limit, args.dimension)
    if args.command == "pages":
        return _pages(args.db, args.limit, args.workers)
    if args.command == "alerts":
        return _alerts(args.db)
    if args.command == "jobstream":
        return _jobstream(args.db, args.since)
    if args.command == "discover":
        return _discover(args.db, args.limit, args.roster, args.workers)
    if args.command == "bodies":
        return _bodies(args.db, args.limit, args.workers)
    if args.command == "singapore":
        return _singapore(args.db, args.since)
    if args.command == "jobs":
        return _jobs(args.db, args.limit, args.workers)
    if args.command == "ats":
        return _ats(args.db, args.limit, args.workers)
    if args.command == "domains":
        return _domains(args.db, args.limit, args.workers, args.regrade)
    if args.command == "fca":
        return _fca(args.db, args.limit)
    if args.command == "stats":
        return _stats(args.db)
    if args.command == "resolve":
        return _resolve(args.db)
    if args.command == "audit":
        return _audit(args.db, args.verbose)
    return _fetch(args.registries or list(REGISTRIES), args.db)


if __name__ == "__main__":
    sys.exit(main())
