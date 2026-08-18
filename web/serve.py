"""Serve `web/`, plus one write route the board needs and `http.server` cannot give it.

`python -m http.server` can only read files back to the browser. The board's
reclassify control needs the other direction -- a correction made by clicking
a card has to land in `quantscraper/labels.csv`, the file `python -m
quantscraper labels` already scores against, with no download and no manual
merge. One POST route does that; everything else is served exactly as
`http.server` would. Standard library only, per CLAUDE.md.
"""

from __future__ import annotations

import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantscraper import labels  # noqa: E402

ROOT = Path(__file__).resolve().parent
PORT = 8731

# The board's short facet keys, translated to `labels.csv`'s column names.
_DIMENSION = {"rel": "relevance", "sen": "seniority"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        pass  # a correction is confirmed on the card itself; the console adds nothing

    def do_POST(self) -> None:
        if self.path != "/correction":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            dimension = _DIMENSION[body["dim"]]
            key = (body["ats"], body["token"], body["job_id"])
            context = {name: body.get(name, "") for name in labels.CONTEXT}
            labels.upsert(labels.PATH, key, dimension, body.get("value", ""), context)
        except Exception as exc:  # noqa: BLE001 -- tell the board, never take the server down
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(exc).encode())
            return
        self.send_response(204)
        self.end_headers()


def main() -> None:
    with ThreadingHTTPServer(("", PORT), Handler) as httpd:
        print(f"http://localhost:{PORT}  (board corrections write to {labels.PATH})")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
