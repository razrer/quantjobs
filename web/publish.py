"""Put the built board on the CDN, without putting 3 MB in the history.

The search is the expensive half and it runs on this machine: `daily` walks the
national boards, polls the ATS feeds and re-tags whatever is new. This is the
cheap half -- it takes what that produced and makes it reachable from a phone.

**Nothing is deployed that runs.** `infra.json` is a private S3 bucket and a
CloudFront distribution in front of it, and that is the whole estate: no
container, no load balancer, no database. The board was already a static file
that a `file://` page could open, so a server would have been a running cost
with nothing to do -- an idle Fargate task and an ALB bill by the hour whether
or not anybody opens the page, while a bucket holding 3 MB and a distribution
serving one reader are inside the free tier and stay there. `versioning` is
off on the bucket for the same reason: `data.js` is overwritten in full on
every publish, and keeping every prior copy would grow the bill by 3 MB a day
to hold snapshots of a file that is rebuilt from the database on demand.

**The data does not go on `master`, and that is deliberate.** Spawned's bucket
source is a git ref, so the file has to reach the repository somehow -- and
`web/data.js` is gitignored precisely because it is derived, several megabytes,
and regenerated whenever the tagger changes. Committing it daily would grow the
history by a few megabytes a day, forever, to record something no reader would
ever check out.

So the publish writes an *orphan* commit with git's plumbing: hash the two
files, build a tree, commit it with no parent, and force-push that to `board`.
The branch is therefore always exactly one commit holding exactly two files;
each publish replaces it rather than adding to it, and the objects the previous
one referenced fall out of the graph. `master` never sees `data.js`, the CI
clone is two files rather than a repository, and the working tree is never
touched -- no checkout, no stash, no branch to switch back from.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent

PROJECT = "d03ad163-70d9-43ed-ba43-3998008f8873"
REMOTE = "quantjobs"
BRANCH = "board"

# What the bucket serves. Both sit at the root of the orphan branch because
# `index.html` asks for `src="data.js"` beside it, which is also what makes the
# board openable from disk.
FILES = ("index.html", "data.js")


def _git(*args: str, stdin: str | None = None) -> str:
    """Run one git command, or fail loudly enough to read."""
    done = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if done.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed ({done.returncode})\n{done.stderr.strip()}"
        )
    return done.stdout.strip()


def _orphan_commit(message: str) -> str:
    """Write the two files as a parentless commit, touching no branch.

    `hash-object -w` writes a blob straight into the object database, which is
    the reason this works at all: `data.js` is gitignored, and `git add` would
    refuse it. Plumbing does not consult the ignore rules, so nothing has to be
    force-added and the ignore rule stays true -- the file really is not part
    of the tracked tree.
    """
    entries = []
    for name in FILES:
        path = WEB / name
        if not path.exists():
            raise SystemExit(
                f"{path} is missing -- run `python web/build_data.py` first"
                " (or drop --no-build)"
            )
        blob = _git("hash-object", "-w", str(path))
        entries.append(f"100644 blob {blob}\t{name}")
    tree = _git("mktree", stdin="\n".join(entries) + "\n")
    return _git("commit-tree", tree, "-m", message)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the board and publish it to the CDN."
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="publish the existing data.js instead of dumping a fresh one --"
        " for re-pushing after a failed apply, where the database has not moved",
    )
    parser.add_argument(
        "--no-apply",
        action="store_true",
        help="push the branch but do not call spawned -- the bucket keeps"
        " serving the previous publish until an apply syncs it",
    )
    args = parser.parse_args()

    if not args.no_build:
        sys.path.insert(0, str(WEB))
        import build_data

        build_data.main()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    size = (WEB / "data.js").stat().st_size / 1e6
    commit = _orphan_commit(f"board {stamp}")
    _git("push", "--force", REMOTE, f"{commit}:refs/heads/{BRANCH}")
    print(f"pushed {commit[:8]} to {REMOTE}/{BRANCH} ({size:.1f} MB, one commit)")

    if args.no_apply:
        print("skipped the apply -- run `spawned apply quantjobs` to sync the bucket")
        return 0

    # `apply` is what actually moves the file: Terraform settles (a no-op after
    # the first run, since nothing about the estate changes) and then CI clones
    # the branch and syncs it into the bucket.
    done = subprocess.run(["spawned", "apply", PROJECT], cwd=ROOT)
    if done.returncode != 0:
        print(
            "the apply failed -- the branch is pushed, so"
            " `python web/publish.py --no-build` retries without re-dumping",
            file=sys.stderr,
        )
        return done.returncode
    print("https://quantjobs.spawned.app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
