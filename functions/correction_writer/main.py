"""The live board's write route, for the one thing a static bucket can't do.

`web/serve.py` already answers `POST /correction` for the board run locally,
upserting straight into `quantscraper/labels.csv`. The deployed board at
quantjobs.spawned.app is a bucket behind a CDN -- no server, on purpose, see
CLAUDE.md's "Publishing it" -- so a click there had nowhere to land and only
ever reached `localStorage`, in that one browser, gone on the next clear.

This function is the other half. Same request shape `serve.py` accepts,
answered from a Lambda instead of a laptop, appending into one JSON object
kept in the same S3 bucket the board's own files live in
(`_corrections/corrections.json`, under a prefix the CDN never has reason to
serve). `python -m quantscraper corrections` reads it back on the machine
that owns `labels.csv`, the same upsert `serve.py` calls, so a Reject clicked
from a phone reaches the tagger exactly like one clicked at a desk running
`serve.py` -- just on the next pull instead of immediately.

Single JSON blob rather than one object per correction, and no DynamoDB
table: this is one person clicking a few corrections a month, a
read-modify-write race is not a realistic risk at that volume, and it keeps
this to the one extra component (this Function) rather than two.
"""

from __future__ import annotations

import json
import os
import re

import boto3

BUCKET = os.environ["BOARD_BUCKET"]
KEY = "_corrections/corrections.json"
ALLOWED_ORIGIN = "https://quantjobs.spawned.app"
DIMENSIONS = {"rel", "sen"}
# ats/token/job_id are URL and CSV-safe by construction (see web/build_data.py
# and extract.py) -- this just refuses to store anything that stopped being.
_ID_RE = re.compile(r"^[^\s]{1,200}$")

# **The route is public and unauthenticated, and until now nothing bounded what
# it would store.** CORS keeps a *browser* on another origin out and does
# nothing about a plain POST, so the blob this appends to -- read back by
# `python -m quantscraper corrections` and written straight into `labels.csv`,
# which feeds the board's `hand_rejected` gate -- could be grown without limit
# by anyone who found the URL. Three bounds, none of which a real correction
# comes near: the value is a vocabulary term, the context fields are what the
# card already shows, and the blob holds one entry per (posting, dimension).
#
# Deliberately *not* an allow-list of the vocabulary itself. This function
# cannot import `quantscraper.labels`, so a copy of `RELEVANCE` and
# `SENIORITY` here would be a second definition free to drift from the first;
# `labels.validate` already refuses an unknown value on the way in, and
# `labels.nearest` corrects a typo. A length bound is the part that belongs
# here, because it is about the store rather than about the vocabulary.
_MAX_VALUE = 40
_MAX_TEXT = 500
_MAX_ENTRIES = 20_000

# What the board sends beside the key, and the only free text kept -- exactly
# `labels.CONTEXT`, because those are the columns `cli._corrections` reads.
# **`description` is deliberately absent**: it was stored here and dropped on
# the way back in, since `labels.py` took it off `CONTEXT` on purpose (the
# `url` is a click away and the body is regenerable from `jobs`). It was the
# largest field in a blob that is read-modify-written on every correction, and
# nothing has ever read it. To reverse, put it back in both places at once.
_CONTEXT = ("title", "firm", "location", "department", "url")

s3 = boto3.client("s3")


def _cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def _response(status: int, body: object = None) -> dict:
    return {
        "statusCode": status,
        "headers": {**_cors_headers(), "Content-Type": "application/json"},
        "body": json.dumps(body) if body is not None else "",
    }


def _load() -> dict:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=KEY)
        return json.loads(obj["Body"].read() or b"{}")
    except s3.exceptions.NoSuchKey:
        return {}


def _save(data: dict) -> None:
    s3.put_object(
        Bucket=BUCKET, Key=KEY,
        Body=json.dumps(data).encode(), ContentType="application/json",
    )


def handler(event: dict, _context: object) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")

    if method == "OPTIONS":
        return _response(204)

    if method == "GET" and path.rstrip("/").endswith("/corrections"):
        return _response(200, _load())

    if method == "POST" and path.rstrip("/").endswith("/correction"):
        try:
            body = json.loads(event.get("body") or "{}")
            ats, token, job_id = str(body["ats"]), str(body["token"]), str(body["job_id"])
            dim, value = str(body["dim"]), str(body.get("value", ""))
            if dim not in DIMENSIONS:
                raise ValueError(f"unknown dimension {dim!r}")
            for part in (ats, token, job_id):
                if not _ID_RE.match(part):
                    raise ValueError("empty or malformed id field")
            if len(value) > _MAX_VALUE:
                raise ValueError("value is not a vocabulary term")
        except Exception as exc:  # noqa: BLE001 -- tell the board, never 500 it
            return _response(400, {"error": str(exc)})

        data = _load()
        entry = f"{ats}:{token}:{job_id}:{dim}"
        # A cap on the *store* rather than on the request: re-correcting a card
        # overwrites its own entry and can never be what fills this up.
        if entry not in data and len(data) >= _MAX_ENTRIES:
            return _response(429, {"error": "correction store is full"})
        data[entry] = {
            "ats": ats, "token": token, "job_id": job_id, "dim": dim, "value": value,
            **{name: str(body.get(name, ""))[:_MAX_TEXT] for name in _CONTEXT},
        }
        _save(data)
        return _response(204)

    return _response(404, {"error": "no such route"})
