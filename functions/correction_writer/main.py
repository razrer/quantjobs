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
        except Exception as exc:  # noqa: BLE001 -- tell the board, never 500 it
            return _response(400, {"error": str(exc)})

        data = _load()
        data[f"{ats}:{token}:{job_id}:{dim}"] = {
            "ats": ats, "token": token, "job_id": job_id, "dim": dim, "value": value,
            "title": str(body.get("title", "")), "firm": str(body.get("firm", "")),
            "location": str(body.get("location", "")),
            "department": str(body.get("department", "")),
            "url": str(body.get("url", "")), "description": str(body.get("description", "")),
        }
        _save(data)
        return _response(204)

    return _response(404, {"error": "no such route"})
