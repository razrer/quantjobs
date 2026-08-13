"""Command line entry point: `python -m quantscraper ...`"""

from __future__ import annotations

import argparse
import sys

from . import ats, audit, db, domains, extract, fca, resolve
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


def _domains(database: str, limit: int, workers: int) -> int:
    connection = db.connect(database)
    connection.executescript(domains.SCHEMA)

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

    args = parser.parse_args(argv)
    if args.command == "jobs":
        return _jobs(args.db, args.limit)
    if args.command == "ats":
        return _ats(args.db, args.limit, args.workers)
    if args.command == "domains":
        return _domains(args.db, args.limit, args.workers)
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
