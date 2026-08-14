"""Command line entry point: `python -m quantscraper ...`"""

from __future__ import annotations

import argparse
import sys

from . import (
    alerts, ats, audit, db, domains, extract, fca, jobstream, pages, resolve,
    tagging,
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


def _jobs(database: str, limit: int) -> int:
    connection = db.connect(database)
    boards, jobs, failures = extract.run(connection, limit)
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


def _jobstream(database: str) -> int:
    connection = db.connect(database)
    since = jobstream.cursor(connection)
    seen, written, withdrawn = jobstream.run(connection)
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

    jobs_command = commands.add_parser(
        "jobs", help="pull postings from resolved ATS boards (Layer 3)"
    )
    jobs_command.add_argument("--limit", type=int, default=100)

    commands.add_parser(
        "jobstream", help="poll Sweden's JobTech delta feed (Layer 4)"
    )

    pages_command = commands.add_parser(
        "pages", help="watch tier-B careers pages for change (Layer 3B)"
    )
    pages_command.add_argument("--limit", type=int, default=500)
    pages_command.add_argument("--workers", type=int, default=12)

    tag_command = commands.add_parser(
        "tag", help="classify postings into rankable tags (Layer 5)"
    )
    tag_command.add_argument("--limit", type=int, default=100_000)
    tag_command.add_argument(
        "--dimension", default="fit", help="dimension to summarise afterwards"
    )

    commands.add_parser(
        "alerts", help="flag sources that broke quietly (Layer 0 health)"
    )

    args = parser.parse_args(argv)
    if args.command == "tag":
        return _tag(args.db, args.limit, args.dimension)
    if args.command == "pages":
        return _pages(args.db, args.limit, args.workers)
    if args.command == "alerts":
        return _alerts(args.db)
    if args.command == "jobstream":
        return _jobstream(args.db)
    if args.command == "jobs":
        return _jobs(args.db, args.limit)
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
