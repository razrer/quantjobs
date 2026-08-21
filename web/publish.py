"""Put the built board on the CDN, by uploading the two files it is made of.

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

**The data reaches the bucket directly, and does not pass through git.** The
first version of this pushed an orphan commit to a `board` branch, because
Spawned's other route for filling a bucket is a git ref and `web/data.js` is
gitignored -- it is derived, several megabytes, and regenerated whenever the
tagger changes, so committing it daily would grow the history forever to record
something no reader would check out. `spawned upload` removes the question: the
file goes from here to the bucket, so there is no branch to keep, no CI clone
to pay for, and the ignore rule stays exactly true. It also removes a
dependency that was not going to hold -- the Spawned GitHub App can see two of
this account's repositories and `quantjobs` is not one of them.

`spawned apply` is therefore only needed when *infrastructure* changes, which
after the first run is approximately never. A publish is two uploads.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent

PROJECT = "d03ad163-70d9-43ed-ba43-3998008f8873"
COMPONENT = "board"
SITE = "https://quantjobs.spawned.app"

# What the bucket serves. The first two sit at its root because `index.html`
# asks for `src="data.js"` beside it, which is also what makes the board
# openable from disk; `default_root_object` on the CDN is what turns `/` into
# `index.html`. `robots.txt` is there because a public hostname is a crawlable
# one, and a search engine indexing this would re-publish other sites' listings
# under ours.
FILES = ("index.html", "data.js", "robots.txt")


def _upload(name: str) -> None:
    """Put one file in the bucket, or fail loudly enough to read."""
    path = WEB / name
    if not path.exists():
        raise SystemExit(
            f"{path} is missing -- run `python web/build_data.py` first"
            " (or drop --no-build)"
        )
    done = subprocess.run(
        [
            "spawned", "upload", PROJECT,
            "--component", COMPONENT,
            "--file", str(path),
            "--key", name,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (done.stdout or "") + (done.stderr or "")
    # The CLI has been seen to print an error and still exit 0, so the exit
    # code is not the whole check. A publish that silently did not happen is
    # the failure this whole project is built to refuse: it looks exactly like
    # a publish that did.
    if done.returncode != 0 or "Error" in output:
        raise SystemExit(f"upload of {name} failed:\n{output.strip()}")
    print(f"  {name:<11} {path.stat().st_size / 1e6:>5.1f} MB uploaded")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the board and publish it to the CDN."
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="publish the existing data.js instead of dumping a fresh one --"
        " for retrying after a failed upload, where the database has not moved",
    )
    args = parser.parse_args()

    if not args.no_build:
        sys.path.insert(0, str(WEB))
        import build_data

        build_data.main()

    for name in FILES:
        _upload(name)
    print(SITE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
