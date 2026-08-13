"""Command line entry point: `python -m quantscraper ...`"""

from __future__ import annotations

import argparse
import sys

from . import audit, db, resolve
from .registries import REGISTRIES


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

    args = parser.parse_args(argv)
    if args.command == "stats":
        return _stats(args.db)
    if args.command == "resolve":
        return _resolve(args.db)
    if args.command == "audit":
        return _audit(args.db, args.verbose)
    return _fetch(args.registries or list(REGISTRIES), args.db)


if __name__ == "__main__":
    sys.exit(main())
