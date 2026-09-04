# CLAUDE.md

Guidance for Claude Code working in this repo.

## What this is

A personal job-hunt tool aggregating quantitative-finance job listings.
**Exhaustiveness is the hard requirement** — a missed listing is the expensive
failure, a duplicate is not.

The architecture is **employer-first, not aggregator-first**: enumerate the
firms that could hire a quant from registries that are complete by law, resolve
each to its own careers feed, and poll that. Aggregators are a discovery net for
employers we lack, never the primary content source.

- **Acquisition methodology:** `C:\Users\razre\.claude\plans\snoopy-growing-hoare.md`
- **Stage log and what is next:** `PLAN.md` — read it before starting work, and
  update it when a stage closes.
- **Blocked on the user:** `ACTION-REQUIRED.md` — write to it when something
  needs review or manual input, and **delete the item when it is resolved**.
- **Tag dimensions and the labelling method:** `TAGGING.md`

Keep terminal output minimal: results and warnings, not narration.

## Running it

```bash
python -m quantscraper <command>
```

| Layer | Command | What it does |
|---|---|---|
| 1 | `fetch` | pull employers from registries |
| 1 | `resolve` | group raw rows into firms |
| 1 | `stats` / `audit` | what is in the database / check it against `roster.csv` |
| 2 | `domains --limit 1000` | firm name → domain, guessed then verified |
| 2 | `domains --regrade --limit 2000` | re-check strong matches |
| 2 | `fca --limit 300` | enrich domains from the FCA register (needs `.env`) |
| 2 | `ats --limit 800` | fingerprint careers hosts to an ATS |
| 2C | `discover --roster` | find boards no careers page named |
| 3 | `jobs --limit 100` | pull postings from resolved boards |
| 3B | `pages --limit 500` | watch tier-B careers pages |
| 3C | `bodies --limit 2000` | fetch the description a list endpoint omitted |
| 4 | `jobstream` | Sweden's national delta feed (`--since` replays a window) |
| 4 | `switzerland` | job-room.ch |
| 4 | `sweden` | Jobbsafari, all of it |
| 4 | `denmark` | Jobindex, every category (`--since` tops up with one query) |
| 4 | `singapore` | MyCareersFuture, the whole portal (weekly, ~70 min) |
| 4 | `hongkong` | the Labour Department's board, all 29 job types (weekly, ~50 min) |
| 5 | `tag` | classify postings into tags |
| 5 | `list --fit apply_now --hub amsterdam` | filter the tags |
| 5 | `list --dimensions` | every filterable value |
| 5 | `sample --limit 100` / `labels` | draw postings to hand-label / score against them |
| 5 | `corrections` | pull reclassify clicks off the live board |
| 6 | `coverage` | how much of the market we see |
| — | `alerts` | flag sources that broke quietly |
| — | `daily` | the whole standing sequence, once |

```bash
python -m quantscraper daily --full --publish   # weekly sweep, then push live
python -m unittest discover -s tests            # regression tests
```

`daily` runs corrections, sweden, denmark, switzerland, jobstream, jobs, pages,
tag, bodies, re-tag, alerts, then a rebuild — **`tag` twice, on purpose**, since
`bodies` fetches text and places the first pass could not see and
`bodies.targets` reads the current tagger to know what to fetch. **It runs
weekly, on this machine, and only here**: the search is the expensive half,
free here and billable anywhere else — what is deployed is the *output*, not
the scraper. A failing step does not
stop the run, because a board redesigned underneath us should cost its own
postings and not the other eight sources', nor the re-tag, nor the rebuild —
which would otherwise leave yesterday's file up with no sign of why. `alerts`
says which one went quiet and the exit code says whether any did.

**Wednesdays at 03:00, by Windows Task Scheduler.** `weekly.ps1` runs
`daily --full --publish`; `install-weekly.ps1` registers or removes the task.
**This reverses a line that used to stand here** — *"nothing schedules it"* —
at the reader's instruction, and the reasoning behind that line is untouched:
the cost still lands on this machine, once a week, and the deployed artifact
is still the output.

It has to be a *local* timer and that is not a preference. `data.js` is built
from the SQLite database, which exists only here, so the build cannot run in
CI — the same fact that keeps `.github/workflows/publish-board-static.yml`
limited to `index.html` and `robots.txt`.

Four things the wrapper exists for, each of which fails silently at 3am
otherwise: it names the **Windows interpreter** (bare `python` is the msys2
build with no CA bundle, so every HTTPS request would die), sets
**`PYTHONIOENCODING`**, captures **both streams** through `Start-Process` with
two redirect files rather than `*>&1` (PowerShell 5.1 wraps a native command's
redirected stderr in `NativeCommandError` records, which would bury exactly
the `FAIL` lines worth reading), and reads those files back with
**`-Encoding UTF8`** — without which `Öhman` logs as `Ã–hman`, measured on a
probe run before it reached a real transcript. Transcripts are
`logs/weekly-<date>.log`, last twelve kept, gitignored.

The task runs as `Interactive` rather than `S4U` on purpose: the sweep needs
the user's own profile — the interpreter under `%LOCALAPPDATA%`, the `.env`
holding the FCA key, and the Spawned CLI's stored login that `publish.py`
uses — and no password is stored anywhere. The cost is that a fully logged-out
machine skips the week, which `StartWhenAvailable` then makes up at the next
opportunity.

`--full` sweeps every Jobindex category and **both national portals** —
MyCareersFuture and Hong Kong's Interactive Employment Service — and widens the
page and body queues. Those two are weekly rather than daily for one reason
each and the same reason: neither has an incremental form worth using, because
only a completed walk refreshes `last_seen` on every live row, which is how a
withdrawal is noticed on a board nothing else polls; and each is about an hour
of deliberately slow requests. **They are in `--full` because they are
expensive, not because they are optional.**

Without it, Denmark tops up with one query from where the data already reaches: `_denmark_since` reads the newest Danish row we hold
rather than the calendar, because the board's own result window covers about a
day and a half — and when the gap is wider it sweeps the whole taxonomy rather
than quietly fetching the most recent 1,000 and reporting success.

**The board is a static page.** Dump the data, then serve `web/`:

```bash
python web/build_data.py && python web/serve.py
```

`serve.py` is `http.server` plus one write route: the board's reclassify
dropdowns POST a correction there and it upserts straight into `labels.csv`.
Opening `index.html` via `file://` still works for reading; a correction made
that way only lives in the browser until it is exported by hand.

`data.js` **omits every dimension sitting on its "nothing known" default** rather
than writing `unknown` a hundred thousand times. The board reads a missing key
as exactly that — do not "fix" it by writing the defaults back in. If the file
ever looks *too* small, the number to read is the per-gate breakdown every build
prints, not the file size.

`fca` needs `FCA_EMAIL` and `FCA_KEY` in `.env` (gitignored, never committed).

**Interpreter gotcha — this will waste your time otherwise.** Bare `python` here
resolves to the msys2 build, which ships without a CA bundle, so every HTTPS
request dies with `CERTIFICATE_VERIFY_FAILED`. Use the Windows Python, which is
what `run.ps1` / `run.sh` do:

```bash
"/c/Users/razre/AppData/Local/Programs/Python/Python313/python" -m quantscraper fetch
```

Also set `PYTHONIOENCODING=utf-8` when printing firm names, or non-ASCII names
raise `UnicodeEncodeError` on this console.

## Publishing it

```bash
python web/publish.py                         # build, push, sync the CDN
```

The board is served at **https://quantjobs.spawned.app** from `infra.json`: a
private S3 bucket and a CloudFront distribution, and that is the whole estate.
No container, no load balancer, no database — the board was already a static
file a `file://` page could open, so a server would be a running cost with
nothing to do. Bucket `versioning` is off for the same reason: `data.js` is
overwritten whole on every publish and rebuilds from the database on demand.

**The data never passes through git.** `spawned upload` puts a file straight
into the bucket, so `web/data.js` stays gitignored — it is derived, several
megabytes, and regenerated whenever the tagger changes. `spawned apply` is only
needed when *infrastructure* changes, which after the first run is approximately
never.

**`.github/workflows/publish-board-static.yml` re-uploads `index.html` and
`robots.txt` on push, and deliberately nothing else.** `data.js` cannot go
through CI — it is built from the local SQLite DB, which only exists on this
machine. The workflow authenticates with `SPAWNED_API_KEY` (a repo secret
holding a dedicated `spawned apikeys create` key, not the browser-login
session), so an HTML/CSS edit to the board goes live without a manual publish.

Three things that cost an afternoon:

- **A repo the Spawned GitHub App cannot see reports as `deployment with id
  '<project-uuid>' not found`.** That reads like a broken project and is not —
  it is a bucket `source.git` pointing at a repository the App was never
  granted. `spawned repos` lists what it can see. The seed config applied
  cleanly the whole time, which is what finally located it: **bisect the config
  before doubting the platform.**
- **The Spawned CLI prints `Error:` and still exits 0.** `publish.py` greps the
  output as well as the exit code, because a publish that silently did not
  happen looks exactly like one that did.
- **CloudFront revalidates, so a publish is visible immediately.** No
  `Cache-Control` is set and a re-upload comes back as `RefreshHit` with the new
  bytes — measured rather than assumed. Nothing has to invalidate the
  distribution and no cache-busting query string is needed.

**`labels.csv` is the one input a machine cannot regenerate, and both ways of
losing it were reachable.** `web/serve.py` is a `ThreadingHTTPServer` and
`labels.upsert` is a read-modify-write of the whole file, so two corrections in
flight read the same rows and the second dropped the first — one click and a
quick second one. And `open(path, "w")` empties the file before a row is
written, so an exception between those two moments left an empty sheet, which
reads as *"there are no labels"* rather than as a crash. The sheet is written
under a module lock and replaced with `os.replace` now, atomic on Windows as
well as POSIX. **Both tests were verified by planting the failure back.**

**The board's reclassify clicks needed a way off a static site, and the answer
is one Function, not a database.** `functions/correction_writer` (`infra.json`'s
`correction-writer`, at `quantjobs-api.spawned.app`) appends into one JSON blob
in the same bucket (`_corrections/corrections.json`); `corrections` reads it
back and calls the same `labels.upsert` that `serve.py` calls. One blob rather
than one object per correction, and no DynamoDB table: this is one person
clicking a handful of corrections a month, so a read-modify-write race is not a
real risk, and it keeps the added cost to one component (~$3.89/mo for a
Function, billed per second regardless of invocation count).

**That route is public and unauthenticated, and nothing bounded what it would
store.** CORS keeps a *browser* on another origin out and does nothing about a
plain POST, so the blob — read back by `corrections` and written into
`labels.csv`, which feeds the `hand_rejected` gate — could be grown without
limit by anyone who found the URL. Three bounds, none of which a real
correction comes near: the value is length-capped as the vocabulary term it is,
the context fields are capped at 500 characters, and the store refuses a *new*
key past 20,000 entries (re-correcting a card overwrites its own key and can
never fill it). Deliberately **not** an allow-list of the vocabulary: this
function cannot import `quantscraper.labels`, and a copy of `RELEVANCE` and
`SENIORITY` here would be a second definition free to drift — `labels.validate`
already refuses an unknown value on the way in. **`description` is no longer
stored at all**: `labels.CONTEXT` dropped it on purpose, so it was the largest
field in a blob rewritten on every correction and nothing had ever read it.
Changing this Function needs a deploy; the code here is ahead of what is live
until one runs.

## Architecture

```
registries/*.py  ->  employers table  ->  resolve.py  ->  firms table
   (one module         (raw, never          (grouping)      (deduplicated)
    per source)         edited)                                  |
                                            audit.py  <----------+
                                          (measures coverage
                                           against roster.csv)
```

- `models.py` — `Employer`, the one record type registries produce
- `http.py` — throttled, retrying GET and form POST, sharing one cookie jar
- `parsing.py` — minimal HTML table and `.xlsx` readers, plus `text()`, the
  one strip-tags-then-unescape used by every reader that touches markup
- `db.py` — SQLite schema and upserts
- `sweep.py` — the two checks every national-board walk owes its caller: an
  implausibly small result, and a shortfall against the board's own total
- `resolve.py` — entity resolution, plus the shared name/country normalizers
- `audit.py` — coverage measurement against `roster.csv`; reads only
- `domains.py` — Layer 2: firm name → domain, guessed then verified
- `fca.py` — Layer 2 enrichment from the FCA register; needs `.env`
- `ats.py` — Layer 2: domain → `(ats, token)` by fingerprint, else tier B/C
- `discover.py` — Layer 2C: firm name → board token, guessed then proven
- `extract.py` — Layer 3: one function per ATS format; postings land in `jobs`
- `sites.py` — Layer 3C: hand-written readers for firms running no ATS, and
  hand-verified boards for firms whose careers walk could not reach one
- `bodies.py` — fetch detail pages: descriptions for postings whose verdict one
  could change, and the real place list for a Workday `N Locations` summary
- `jobstream.py` — Layer 4: Sweden's national delta feed, cursor in `feed_state`
- `jobroom_ch.py` — Layer 4: Switzerland; walks from both ends around a
  10,000-result window
- `jobindex.py` — Layer 4: Denmark, enumerated by partitioning its own
  subcategory taxonomy under a published 1,000-posting result window
- `jobbsafari.py` — Layer 4: Sweden's widest board. One unfiltered walk, no
  result window, robots-clean
- `mycareersfuture.py` — Layer 4: Singapore
- `iesjobs.py` — Layer 4: Hong Kong's statutory board, walked as its own
  job-type partition
- `lexicon.py` / `tagging.py` — Layer 5, the deterministic classifier
- `labels.py` — the hand-labelled fixture and the scoring
- `alerts.py` — per-source volume anomaly detection over the `runs` history
- `web/build_data.py` — Layer 6: dumps `jobs` + `job_tags` to `data.js`
- `web/index.html` — the board: filter rail, card grid, deadline-first ordering
- `web/publish.py` — pushes the built board to the CDN
- `infra.json` — the deployed estate: one private bucket, one distribution

`roster.csv` is the *audit set*, never the universe. A firm's absence from it
says nothing. Keep names specific: a bare `Grasshopper` matched an unrelated
`GRASSHOPPER ESCAPEMENT, LLC` and reported a hub better covered than it was. A
false hit hides a miss, so it is worse than a false miss.

**Third-party dependencies are allowed, at the user's instruction, provided
they cost nothing.** Free as in no licence fee, no account, no API key and no
metered service -- an ordinary PyPI package under an open licence qualifies and
a hosted API does not, whatever its free tier says, because a free tier is a
bill waiting for a threshold. **This reverses the older rule** (*"standard
library only, keep it that way"*) and the reversal is not conditional: reach
for a well-established library first rather than proving a hand-rolled
alternative is worse. The reasoning behind the old rule is still worth keeping
as a *design taste* rather than a gate -- everything here still runs from a
clean checkout on this machine, and a dependency earns its place by replacing
something the standard library or a hand-rolled block does worse, not by
surviving an interrogation.

Two tests before adding one, and neither requires a benchmark first:

1. **Would its absence be loud?** A pinned import that fails at start-up is
   fine. A dependency read at the bottom of a fetcher, inside a thread, on one
   source, is how a step goes quiet -- which is principle 2 arriving through
   the package manager.
2. **Does it touch load-bearing logic without being proven equivalent on the
   incidents that logic was written for?** Most of this codebase is ordinary
   glue that any competent library can replace outright. A specific handful of
   places are not glue -- they are fixes for a documented, measured failure,
   and a library swapped in there must be checked against the same corpus or
   the same incident before it ships, not assumed correct because it is
   popular. The known list: `http.py`'s per-host throttle and its 429-vs-503
   backoff split (see *A 429 is not a 503* above -- a generic retry
   decorator's default schedule is exactly the bug that lost a MyCareersFuture
   walk), `tagging.fold`'s confusable-character table (a general transliterator
   like `unidecode` mangles the genuine CJK and Greek titles this was
   deliberately scoped to leave alone), `audit._matches`'s token-run name
   matching (a distance-based fuzzy match reintroduces the false-merge risk
   Principle 3 exists to avoid -- `GRASSHOPPER ESCAPEMENT, LLC` is the standing
   example), and the per-vendor paging/shape quirks in `extract.py` and
   `bodies.py` (each `isinstance` check there is a specific vendor's specific
   lie about its own data, catalogued above one at a time). Everywhere else --
   HTTP transport plumbing below the throttle, TLS trust (`certifi` over
   hand-listing Git/msys2 CA bundle paths), country-name normalization,
   archive/columnar formats -- is ordinary and a library is the default,
   not a last resort.

`openpyxl` for `parsing.py`'s ninety-line `.xlsx` reader is the one measured
counterexample on record -- called twice a month, and the library would save
nothing that has ever cost anything. It is not a reason to require the same
measurement of the next candidate; it is a reminder that "shorter" and "an
improvement" are not always the same file.

Whatever is added goes in `requirements.txt` with a pinned version and a line
saying what it replaced, and `weekly.ps1` keeps working on a machine that has
only run `pip install -r`. The first two entries: `certifi`, replacing the
hand-listed Git/msys2 CA bundle fallback in `http._ssl_context` with a bundle
the package maintains itself; and `pyarrow`, for `board_triage.parquet` -- a
static, code-unread archive that used to duplicate the same "big CSV" mistake
`labels.csv` was already fixed for (see *A fixture that caches a column*
below). Neither is imported by the daily/weekly pipeline except `certifi`,
which every fetch now depends on -- `http.py` is no longer stdlib-only.

### Adding a registry

Drop a module in `quantscraper/registries/` exposing `NAME`, `JURISDICTION`,
`MIN_EXPECTED` and `fetch() -> list[Employer]`, then add it to `REGISTRIES` in
that package's `__init__.py`.

Prefer sources you can **enumerate** over sources you must **query**. A search
endpoint only returns what you thought to ask for, which is a hard ceiling on
recall; a category listing or a bulk file has no such ceiling.

## Principles that must not be quietly violated

Load-bearing. If a change appears to require breaking one, stop and raise it.

1. **Never filter the employer universe.** Every firm a registry returns is kept
   forever and rows are never deleted. Regulatory attributes and geography set
   *polling frequency* and *ranking*, never membership. A mis-tuned heuristic
   must cost latency, not coverage.
2. **An implausibly small result is a failure.** Each registry declares
   `MIN_EXPECTED`. A scraper that breaks and returns zero rows with HTTP 200 is
   far more dangerous than one that crashes, because nothing announces it.
3. **Bias to false splits over false merges.** A duplicate firm costs a second
   of reading; a wrong merge silently deletes an employer.
4. **Classify at read time, never at write time.** Ingest broadly and store
   everything including rejects, so a wrong classifier can be re-run over
   history instead of re-scraped. Filtering is reversible; a missed posting is
   not. **Do not speed the pipeline up by filtering at ingest** — the legitimate
   version of that idea is filtering the *work*, which `bodies.py` already does.
5. **Raw tables are append-only.** `employers` is never edited; derived tables
   like `firms` rebuild from scratch on demand.

## How this project crawls

**`robots.txt` is not honoured, at the user's instruction, and the whole of
what is offered instead is rate.** Any host whose rules this project reads past
runs at one request per four seconds in `http.HOST_INTERVAL_S` — four times
slower than the default `MIN_INTERVAL_S` — and no such source is swept more
than weekly. Jobindex's `page=`, Citadel's sitemaps and Hong Kong's whole
statutory board are all read on that basis.

**The line that does not move is bot detection.** A `Disallow:` is a text file
asking a crawler not to index; a CAPTCHA and a WAF are a server refusing *this
client*, and getting past either means completing a challenge or pretending to
be a browser. So Dubai's DFSA reCAPTCHA, Jefferies' Altcha, Quantlab's Jobvite
403, and `efinancialcareers.hk` and `ctgoodjobs.hk` answering HTTP 405 to every
path are all recorded as closed and stay closed. **Do not change the user agent
to get past a refusal**, and do not probe for where a threshold sits.

**A 429 is still obeyed, and it is not the same question.** MyCareersFuture's
`robots.txt` reads `Disallow:` with a sitemap — it never asked us not to read,
it asked us to slow down, and slowing down is what a 429 requests. See
`http._retry_after`.

## Geographic priority

Priority affects **what to build next**, not what to ingest.

- **Focus:** Stockholm, Copenhagen, Amsterdam, Switzerland, Hong Kong,
  Singapore, **New York, Chicago, Boston**
- **On the board, ranked below focus:** the rest of the US (`us_other`)
- **Deprioritized:** Germany, London/UK, China, Dubai

**The US was promoted out of `deprioritized` at the user's instruction, and the
numbers say it should have been there already.** It carries 876 postings rated
`adjacent` or better against 887 for all six older focus hubs combined, and New
York alone carries 468 — more than Hong Kong, Stockholm, Amsterdam, Switzerland
and Copenhagen put together.

**It is three metros plus a residual, not one country**, which is the rule the
rest of `_HUBS` already follows: a focus hub is a city plus a real commuting
belt, and the rest of the country gets its own value. A single national hub
would be the `sweden` mistake at continental scale — every insurance clerk in
Omaha ranking level with a Jane Street desk. Measured: the three metros hold 74%
of the American postings this board rates positively in 27% of its volume — New
York 468, Chicago 107, Boston 75, all the rest 148. The Bay Area (31), Texas
(31) and Miami (15) are out because of *what* their positives are — wealth
advisers, tax principals, real-estate capital markets. `us_other` is on the
board, unlike `sweden_other` and `denmark_other`, which are gated.

**One deliberate exception, at the user's instruction: the *board* gates on
geography.** The universe rule is unchanged — no row is deleted, no registry is
filtered, and re-running the tagger rebuilds the verdict. What changed is what
`web/build_data.py` renders: a posting in Kiruna or Paris is not one this user
will take. See `exclusion_reason: off_location`, and `GATES` — deleting a line
there puts those postings back on the next build with no re-tag.

## Scope discipline

The user has asked for minimal, readable, maintainable code and for the work to
proceed methodically rather than opportunistically.

- Work the current `PLAN.md` stage to its exit criterion, then stop.
- Do not add sources because they are interesting. Add them because the audit
  says they are missing.
- Verify against real endpoints before writing an adapter — several sources
  published formats nothing like what their documentation implied.
- **Do not create accounts or register for API keys.** Put those in
  `ACTION-REQUIRED.md`.

## Known structural gaps

The load-bearing one: a firm dealing exclusively on its own account can be
exempt from investment-firm licensing under MiFID II Art. 2(1)(d), so it appears
in **no** register. Exchange participant lists cover most of these. Firms
trading via sponsored access under someone else's membership are covered by
nothing public — Da Vinci Derivatives is the standing example.

---

# Gotchas, each of which silently produced a wrong result

## Registries and bulk files

- **Form ADV** `Website Address` is a LinkedIn page for over 4,000 filers, plus
  ~2,000 on other social platforms. Useless for domain resolution, and it merges
  the whole long tail into one firm if used as an identity key. **Form ADV
  covers SEC registrants only** — advisers under roughly $110M AUM register with
  their state and are absent.
- **SEC broker-dealer file** is UTF-16 with a blank line between every record,
  so roughly half of parsed rows are empty by design. **SEC bulk file paths
  move** and filenames are inconsistent (`bd-070124.txt`, `bd080126.txt`,
  `bd080122_1_0.txt`, plus malformed seven-digit ones). Read the link off the
  index page; never construct a URL.
- **AFM** exports are semicolon-delimited and cp1252-encoded, neither declared.
  **And the CSV exports are not the whole register**: the AIFM manager registers
  are published only as `.xlsx` further down the same page while the CSV link
  sits at the top looking complete. Missing them cost PGGM and APG. Always
  scroll a register page for spreadsheet links.
- **FI publishes 495 category codes**, not the 139 an earlier note claimed, and
  most are permissions rather than company types. Occupational pension
  undertakings are filed under *three* codes by legal form — walking only
  `TJPAB` misses Alecta, which is a mutual (`TJPÖMS`).
- **Finanstilsynet (DK) has no enumerable endpoint.** Six service operations,
  none of them a listing; the site's own "list extract" pages render empty
  shells. `searchVUT` matches a substring, so the register is swept by single
  letters and unioned. Saturation is the completeness evidence.
- **SFC (HK) returns `totalCount: 0` rather than an error** when the session
  cookie or the `nameStartLetter` field is missing. Both are required; fetch the
  search page first, and `http.post_form` shares one cookie jar for this.
- **MAS (SG) ignores every page-size parameter** — ten rows per page, no
  override. An out-of-range page returns zero rows rather than wrapping, which
  is what makes the walk terminate correctly.
- **ESMA's Solr endpoint is a real enumeration** — `q=entity_type:ae` returns
  all 13,930 EEA firms, paged. Always pass `sort=id asc`: deep paging without a
  stable sort silently repeats and skips rows. The child documents
  (`aeActivity*`) are per-permission rows, not firms.
- **FCA: Cloudflare returns 403 "error 1010" to any request without a
  `User-Agent`**, which is indistinguishable from a bad API key. Check the
  header before doubting the credentials.
- **FCA `CommonSearch` returns "No search result found" for everything**,
  forever. The working endpoint is `Search?q=...&type=firm`, and paging is
  `pgnp=N` — not `page`, which is silently ignored while the response
  advertises `pgnp` in its own `Next` URL.
- **FCA cannot enumerate, and this is settled.** Queries under three characters
  are rejected, broad ones return `Request Entity Too Large`, and there is no
  bulk download. It is enrichment only — `fca.py` lives outside `registries/`
  deliberately, because calling it a registry would overstate coverage. **FCA
  search is also fuzzy**: a query for "barclays" returns `PEAC Business Finance
  Limited` first, so accept a result only on a token-aligned name match.
- **`CERTIFICATE_VERIFY_FAILED` on Windows usually means our trust store, not
  their server.** Windows populates its root store *lazily*, so a fresh Python
  process trusts only the roots already cached — 38 here, against 152 in a real
  bundle. FINMA was diagnosed as "serves an incomplete chain" on that evidence
  and the diagnosis was wrong. **Test with `curl` first**: it ships its own
  bundle, so if curl connects and Python does not, the store is short.

## Domain resolution (Layer 2)

- **A guessed domain must be verified against the page, and one word is not
  proof.** `australia.com` (the tourism board) "matched" Australia and New
  Zealand Banking Group, `societe.com` matched Societe Generale, and
  `citadel.com` matched *Citadel Securities* — a different employer with a
  different careers page. Only strong matches count; a wrong domain yields a
  silently empty feed, which is worse than no domain.
- **Evidence must not be circular.** `marketfrance.com` proved itself by
  printing its own domain on the page — and the domain was what we guessed.
  Match on spaced phrases, never on the run-together form.
- **Fold both sides the same way before matching.** The register says
  "J.P. Morgan SE" (normalizing to `jp morgan`) while the page says
  "J.P. Morgan"; comparing a normalized name against raw page text matches
  nothing.
- **Naming the firm is necessary and not sufficient.** `athoscap.com` prints
  "Athos Capital" and passes the spaced-phrase rule — and it is *Athos Capital
  Partners*, a real-estate PE firm, not the Hong Kong hedge fund. When a firm
  name is two common words, read the title before recording the domain.
- **A registry's own website field can be malformed, and two guards can each
  assume the other caught it.** AFM publishes `http//www.optiver.com` — no colon
  — for 68 firms, Optiver and IMC among them. `domain_of` returned None so the
  harvester skipped them for having no parseable website, *and* `targets`
  excluded them for having one. `domains` reported "nothing left to probe" while
  they had never been looked at.
- **A platform domain is not an employer, and it leaks into five layers.**
  `resolve.is_platform_domain` is the one answer: Stage 1 must not merge 6,688
  firms onto LinkedIn, Layer 2C must not file Point72's 229 postings under
  `linkedin.com`, the Stage 10 miss list must not top out with `youtube.com`,
  the careers walk must not rank a social profile as a careers page, and
  Jobindex's `company.homeurl` goes through it too. Match the registrable suffix
  — the junk arrives as `uk.linkedin.com` as often as the bare form.
- **A merged firm can inherit a social page as its website.** `resolve._best`
  picks the most common value among a group's rows, so Two Sigma's
  `firms.website` came out `https://x.com/twosigma` while the seed registry
  carried `twosigma.com`. `_best_website` prefers any real domain the group
  holds.
- **`domain_lookups.query` is the registry's name for a firm, not the
  roster's.** Looking a roster entry up by exact name found a domain for 40 of
  161 and reported the other 121 as having none; going through `audit.run`'s
  matching found 104 of 120. The same mistake reads as a coverage collapse.
- **A three-character *domain* guess is refused and a three-character board
  token is fine.** `domains._labels` refuses short labels because a wrong domain
  is a silently empty feed; reusing that rule for board tokens cost IMC's board,
  which is `imc` and worth 165 postings. Token length is not the safety check —
  corroboration is.

## ATS fingerprinting and extraction (Layers 2–3)

### Paging: every stop condition here was wrong once

- **Workday's trap is `total`, not `limit`.** True `total` on page one and
  **`total: 0` on every page after**, so `len(jobs) >= total` truncates every
  board at 20. Cap the page at 20, page by `offset`, stop on a short page.
  `tests/test_workday.py` pins all three.
- **Stop on an empty page, never on a short one — Oracle is the second format
  to teach it.** Its API serves the occasional 199-row page mid-board (Kotak's
  tenant: offset 3,000 → 199, offset 3,200 → 200), so the short-page stop
  truncated Kotak at **3,199 of 9,959** and Tata Capital at **1,599 of 5,542**
  — both the round number a cap leaves behind. Removing that stop needs
  Workday's repeat-page guard, or a tenant ignoring `offset` pages forever.
- **A page-count guard is a silent cap on the boards that matter most.** The
  Workday reader stopped at 40 pages and LSEG and State Street both came back
  at exactly **800**; State Street has 1,295. The bound is 1,000 pages now.
  **Whenever a per-board count is suspiciously round, suspect our guard before
  their register.**
- **A trailing slash was a silent 50-posting cap.** Jobvite pages at
  `/{token}/search/?p=1`; without the slash it serves page one while looking
  like it paged. Sikich's own text says `1-50 of 73` — **the board states its
  own size, so compare against it.**
- **Eightfold ignores `num` and serves ten**, the MAS trap one vendor over.
  Paging fifty at a time skipped forty in every fifty and **the advertised
  total was the only thing that said so.**
- **iCIMS has no feed** (`format=rss` 302s to a staff login). Links are
  `/jobs/{id}/{slug}/job`, `pr` pages 50 at a time, and the list carries **no
  anchor text** — the slug is the title, losing casing and `c++`. Stop when a
  page adds no *new* id: a portal ignoring `pr` serves page one forever and
  never returns an empty page.
- **A shortfall check must tolerate churn, or it deletes the board it was
  written to protect.** Oracle's raised on any difference; BNY advertises 1,390
  and hands over 1,387 — three requisitions closing mid-walk — and **1,387 real
  postings were thrown away**. `_ORACLE_CHURN` is what one walk may lose;
  anything wider is our paging. (`TotalJobsCount` is honest on every page, so
  Oracle has no `total: 0` trap; it is a *check*, never the stop condition.)

### Tokens: the wrong answer looks right

- **Workday needs `tenant|wdN|site`.** A tenant alone builds a URL that 404s
  every poll while the board reads resolved.
- **Workday has a second host and it inverts the URL.** On `myworkdayjobs.com`
  the tenant is the subdomain; on `myworkdaysite.com` the subdomain is a bare
  `wdN` and the tenant moves into the path. Capture by *name*: joining by
  position built `wd3|brevanhoward|BH_ExternalCareers`, well-formed and
  addressing nothing.
- **A vendor can serve its tenants from two hosts, and a tenant lives on
  exactly one.** UKG's `recruiting2.ultipro.com` 404s a `recruiting.ultipro.com`
  board and the reverse; this reader addressed the first unconditionally, so
  eight boards 404'd on every poll while **every one had `recruiting2` in its
  own stored evidence** (Mesirow Financial and Calamos among them). **When a
  board 404s, read the evidence that resolved it before doubting the token.**
- **A capture that lands one segment early is the quiet kind of wrong.**
  Workday's optional locale skipped the underscore form, so
  `mmc.wd1.myworkdayjobs.com/en_US/MMC` made the locale the site —
  `mmc|wd1|en_US` 404s forever while `mmc|wd1|MMC` holds **2,437 postings**.
  And `apply.workable.com/j/{shortcode}` is one posting's page, read as the
  board `j` against two unrelated domains. Both are well-formed, both read
  tier A, both address nothing or somebody else's board.
- **Vendor infrastructure is not a board.** `boards-api.greenhouse.io/v1/...`
  yields `v1` for every Greenhouse user and `www.teamtailor.com` yields `www`;
  `tbe.taleo.net` is Taleo Business Edition, which `varde.com` and
  `hanoverco.com` both resolved to. **A token several unrelated domains agree
  on is the vendor's**, which is what `_NOT_A_TOKEN` is for. **Always read the
  first handful of tokens before trusting a batch.**
- **That list is an *all-pieces* rule and that is only half right.** It must
  be, or `jane-street` and `da-vinci` are thrown away — but
  `jobs.jobvite.com/__assets__` was recorded against three unrelated firms and
  `vs-errors.eightfold.ai` passed because `vs` means nothing. Split on `_` as
  well as `-`, and check the unambiguous words (`assets`, `cdn`, `errors`,
  `sentry`, `staging`) with *any* rather than *all*.
- **Oracle Fusion's token is `podhost|siteNumber` and neither half works
  alone**: `CX_1001` is Oracle's default site number, so a token of the site
  collides across every firm on the platform. UKG's `code|boardGuid` is the
  same shape.
- **Greenhouse's own copy-paste snippet did not match the Greenhouse pattern,
  and 29 boards sat unread.** The rule allowed
  `/embed/job_board?for={board}`; what a firm actually pastes is
  **`/embed/job_board/js?for={board}`**, a path segment before the query. The
  general host rule then captured `embed`, `_NOT_A_TOKEN` correctly refused it,
  and the domain landed at **tier A with a NULL token**, the one state
  `discover.targets` calls out as a board nobody can poll — Maven Securities (39
  postings across Amsterdam, Chicago and Hong Kong), GSA Capital, Geneva
  Trading, Acadian, Vatic. **A NULL token on a
  recognised ATS is a firm that reads as resolved everywhere and yields nothing
  forever.** `job_app?for=` names the board too: that embed is an application
  form rather than a list, so the first fix skipped it — and `for=` is the
  board in *every* Greenhouse embed. GSA publishes its whole careers page as
  `job_app` forms and names the board nowhere else.
- **And GSA then added no postings, because its board was already polled under
  a sibling domain** (`gsa-coral.com`, same Greenhouse token). `jobs`'s upsert
  keys on `(ats, token, job_id)` and does not move `domain`. **Check
  `SELECT domain FROM jobs WHERE token = ?` before counting a fix as
  postings.**
- **The same upsert leaves one board split between two domains, which reads as
  two firms and names the bigger half wrong.** 24 boards are claimed by more
  than one domain, 1,668 postings sit on the minority one, and
  `barclays|wd3|External_Career_Site_Barclays` held 1,557 rows under
  **`cards.barclaycardus.com`** against 3 under `home.barclays` — so the board
  read *"Barclaycardus"*, and nothing matching this firm across sources could
  ever recognise MyCareersFuture's `BARCLAYS BANK PLC`. **The token names the
  tenant, so the token picks the domain** (`build_data.board_domains`): the
  domain whose registrable label is one of the token's pieces is the firm whose
  board it is. Right or harmless on all 24 and better than "most rows" on nine
  — Barclays, Chicago Trading (`ctceurope.com` 23 rows to
  `chicagotrading.com`'s 2), Piper Sandler, Bain Capital, Quilter, Toyota,
  ORIX, Mariner, Corebridge. It reads `ats._NOT_A_TOKEN` rather than restating
  it, or a token containing `careers` would pick `careers.sig.com`. Where the
  token names nothing, **the parent brand wins before the majority**: `mmc`
  matches neither `marsh.com` nor `marshmma.com`, and the majority alone
  renamed fifteen `Marsh` cards *"Mma Asset Management"*. Dry-run first — that
  clause fires on exactly one board.

### Boards that live on the firm's own hostname

- **An ATS board often lives there, and every host pattern misses it.**
  `careers.lynxhedge.se` is Lynx and `jobs.swedbank.com` is Swedbank —
  Teamtailor boards that never spell `{board}.teamtailor.com`. The vendor's
  asset CDN is in the markup and the custom host is the token. **Verify it**:
  the CDN proves the firm *uses* the vendor, not where its board is, and the
  first three domains matched this way all 404'd on `/jobs.rss`.
  `careers.sig.com` is the same shape, worth 237 postings.
- **Avature serves every customer this way**, so `careers.twosigma.com` matches
  no `{board}.vendor.com` pattern and the board *is* the host — the reason
  `_VENDOR_ASSETS` exists; the giveaway is
  `templates-static-assets.avacdn.net`. **Its list page is named by the tenant
  rather than the vendor**: Two Sigma calls it `/careers/OpenRoles` against
  Avature's default `/careers/SearchJobs`, so reader and fingerprint try a list
  of names — a wrong one 404s, which cannot be mistaken for an empty board.
  `extract.AVATURE_LIST_PATHS` is one definition both read.
- **`_VENDOR_ASSETS` is a second fingerprinting table and had no reader
  guard.** `EveryFingerprintHasAReaderTest` walked `ATS_PATTERNS` only, so a
  vendor recognised by its CDN could resolve tier A and poll nothing — the
  88-board silence one table over. It checks both now.
- **A verified board outranks a host pattern, and the rule turns on the
  vendor.** iCIMS career sites still print `careers-{token}.icims.com` for
  their login link, so the classic-portal pattern won — a board the firm had
  migrated *away* from. `_custom_host` wins when it names a *different* vendor
  (two products, one live) and defers when it names the same one
  (`careers.optiver.com` and `optiver.teamtailor.com` are one board).
- **A board URL escaped inside a JSON island matches no host pattern.** Julius
  Baer ships its navigation as JSON inside an HTML attribute, so its Workday
  board arrives as `&quot;https:\/\/juliusbaer.wd3.myworkdayjobs.com\/...`.
  `fingerprint` unescapes first. On a random tier-B sample that rescues 1 page
  in 400; among tier-B *roster* firms, one in ten — **pick the frame before
  believing a yield.**

### Boards that answer 200 and are not boards

- **Every tier-A board holding no postings was polled once and the answers
  sorted, which is the audit this section is made of.** 118 boards: **70
  answer 200 and are genuinely empty**, 29 raise (26 of them 404), 10 are
  Taleo and have no reader, 7 raise a shortfall, and **2 were live and simply
  had never been reached**. The 70 are the finding worth keeping: they are
  small VC and PE firms with nothing open, and the JSON vendors say so
  authoritatively -- `pinpoint` answers `{"data":[]}`, `join` answers
  `"items":[],"total":0`, Homerun and Varbi serve feeds with no entries. **A
  board that answers 200 with nothing is usually telling the truth**, and the
  way to know which is to ask the endpoint rather than the reader.
- **Most of the 404s are somebody else's board.** `8vc.com` resolving to
  `greenhouse/habi`, `valuestreamventures.com` to `userinterviews`,
  `infinityvc.capital` to `sensible` -- a venture firm's careers page links to
  its portfolio companies, which is the `palmersquare.com` shape at scale. The
  two that looked recoverable were checked on every Greenhouse host there is
  (`boards-api`, `api`, `job-boards`, `job-boards.eu`, the `embed` endpoint)
  and 404 on all of them while `mangroup` answers on all of them, so
  `questpartnersllc` and `monoceros` are stale embeds on the firms' own pages.
- **Jobvite ships two list layouts and a firm may run either**, which is the
  SuccessFactors lesson one vendor over. A *table*, where `jv-job-list-name`
  labels the cell containing the anchor, and a *card list*, where the anchor
  comes first and the name and location are `<div>`s inside it. They agree on
  the class names and on nothing else, so the table pattern found zero on a
  card board: `addendacapital` advertised `1-3 of 3` and `mercycorps` 32, and
  both read as nought. **The board stating its own size is what caught it** --
  the shortfall check raised rather than the board reading as empty.
  `class="jv-job-list-location ml-auto"` then cost every location, because the
  pattern wanted a quote where the markup has a space.


- **A migrated board answers HTTP 200 with a redirect script and no postings,
  which is principle 2 exactly.** Twelve of 36 iCIMS boards served a 150-byte
  `window.top.location.href = ...` stub (Principal, AXA, SiriusXM) and the
  reader called every one "an empty board". The stub names where it went: a
  target still on `icims.com` is the same portal under a different prefix
  (`allcareers-frankrimerman`, `uscareers-siriusxmradio`) and is followed;
  anything else is a migration and is raised with the target.
- **A retired board says so by redirecting.** BambooHR 302s a dead subdomain to
  its marketing site, so the JSON endpoint answers 200 with HTML and the reader
  failed with `JSONDecodeError` — four boards saying "this customer is gone" in
  the least readable way available. **Compare the URL that answered against the
  one asked for**; `http.get_with_url` exists for it.
- **A suspiciously *small* board deserves the suspicion a suspiciously round
  one gets.** Aon's classic iCIMS portal answers with **one** posting while its
  career site holds **1,058** — not silent, not working, and invisible to every
  check here including the "tier A and no postings" sweep.
- **iCIMS' career sites beat the classic portal on more than volume.** SIG's
  250 postings arrive from the career site with a location and a description
  and from the portal with **neither** — and the board gates on geography, so
  1,805 portal postings carry no place at all. The endpoint is
  `/api/jobs?limit=100&page=N`, read off the site's own `featured-jobs.js`.
- **SuccessFactors RMK ships two list layouts and a firm may run either** — a
  table of `<tr class="data-row">` and a list of `<li class="job-tile">`,
  agreeing on the `jobTitle-link` anchor and nothing else. Reading only the
  table found 81 postings at Janus Henderson and none at Carnegie: a board
  answering 200 and coming back empty. Clarksons adds a third, a path prefix
  before `/job/`, worth 33 postings.
- **A board page serving a dead end does not mean there is no feed.** Varbi's
  `/{lang}/what:list/` answers *404 Unallowed call* for every language and
  Homerun's board is script-rendered; both publish a feed (`/what:rssfeed/`,
  `feed.homerun.co/{token}`) carrying the description the page does not.
  **Read the page's own link shapes before concluding a vendor has no feed**;
  guessing paths found neither.
- **A careers page can link to a board that is not the firm's.**
  `palmersquare.com` linked to `jobs.lever.co/heyrowan` — syndicated content
  with a Google `srsltid` still attached — and delivered 90 jewellery-retail
  postings under a credit manager's domain. Well-formed token, real ATS, live
  feed, wrong company. **Read the postings, not just the token.**
- **The careers walk must try every candidate and go two hops.** The loop used
  to `return` tier B on the first readable page, so candidates two and three
  were fetched by nobody — and Swedbank's board is a link *off* its careers
  page. Six fetches per domain is the ceiling.

### Vendors recorded as closed, and why most of those notes were wrong

- **"This vendor is closed" is a claim about one tenant on one endpoint until a
  second is checked, and five of the six closures here were wrong.** Each was
  written from a single firm's board and generalised, which is what made them
  expensive: the note then gets read instead of the endpoint.
  - **Eightfold answers per tenant.** `/api/apply/v2/jobs` really does 403 on
    Morgan Stanley's tenant and NAB's; Vale's answers 200 with 193 positions
    and **Millennium's with 219**, including `Quantitative Researcher`,
    `Portfolio Researcher` and `Deep Learning Quantitative Researcher` across
    New York, Hong Kong and Singapore. One marquee quant board behind a
    one-line note for months.
  - **SuccessFactors' dead end was a different surface.** The
    `?company=pfapensionP` form really is a shell with no `job_id`; these firms run **RMK on their own hostname**,
    rendered server-side — Nomura 514, Fitch 266, Janus Henderson 81, Carnegie
    7. 61 rows sat tier A with a NULL token behind that sentence.
  - **Emply's board is client-side and names its own endpoint.** The page is
    209 KB with no job id, which is true and is not the same as unreadable:
    `/api/integration/vacancy/get-page` sits in an inline script beside the
    exact body it POSTs. **Jobylon** is the same shape — an Angular widget whose embedded
    page carries the whole list as a JavaScript array.
  - **Join's API really does 422** on every `page`/`pageSize` combination, and
    the company page carries
    `"jobs":{"items":[...]}` as an unescaped JSON island. **When a vendor's API
    refuses, read the page the customer publishes** — the answer DRW's
    `__NEXT_DATA__` gave.
- **Genuinely closed:** Paylocity, Rippling and Phenom render client-side (the
  41 "job ids" in Paylocity's HTML are analytics and CSS); Jefferies' `tal.net`
  answers with an Altcha CAPTCHA, which this project does not complete.
- **Taleo needs a per-board portal id and does not publish one**, so it is the
  only fingerprinted ATS with no reader: without the right `portal=` the search
  endpoint returns `careerSectionUnAvailable: true` and the section page is a
  1,534-byte stub. Its ten rows are worse — `ocbc.taleo.net` does not resolve,
  `socgen.taleo.net` redirects to the recruiter login, `tbe` is the shared
  host. **OCBC is not a miss**: 43 of its postings arrive through
  MyCareersFuture, which is what a national board is for.

### A vendor's shared host is not a tenant, and 24 rows sat on one

- **`careerN.successfactors.com` is the pod, not the board.** 24 of the 43
  tier-A rows with a NULL token named one, and `_NOT_A_TOKEN` was right to
  refuse it -- it is `careers-analytics.recruitee.com` one vendor over. But
  refusing leaves the row in the state this file calls *a firm that reads as
  resolved everywhere and yields nothing forever*, and nothing re-asked. The
  board is on the **firm's own hostname**, as it is for every RMK tenant this
  project already reads: `careers.nomura.com`, `jobs.scania.com`,
  `careers.fitch.group`.
- **Seven of the 24 answered, and one of them matters.** Found by walking each
  domain for a `jobs.`/`careers.` host and running the reader against it:
  **GIC**, Singapore's sovereign fund, **171 postings, 133 of them in a focus
  hub**, carrying `Portfolio Manager, Securities Finance` and `Associate - VP,
  External Managers, Macro/Fixed Income`. Then Quintet 19, PartnerRe 56, Grace
  67, Popular 59, Valentino 55, Sonepar 929. **GIC was unreachable by any
  walk**: `gic.com.sg` does not resolve at all, only `www.gic.com.sg` does, so
  every careers path this project tries fails at DNS.
- **Two of the 24 were duplicates of a board already polled** -- `scania.com`
  resolving to `jobs.scania.com`, which is held under `traton.com`. Check
  `SELECT domain FROM jobs WHERE token = ?` before counting a recovery, which
  is the GSA rule in a second place.
- **`tt.teamtailor.com` is the vendor's own initials**, recorded as the board
  `tt` against `savills.com` -- `www.teamtailor.com` yielding `www` one
  abbreviation over. It slipped the "several unrelated domains agree" signal
  because only one domain claimed it. Listed in `_NOT_A_TOKEN` by name rather
  than caught by a length rule: **a two-character token is not inherently
  wrong**, and `ashby/3e` is `endicottgp.com`'s real board with 16 live
  postings.

### Capabilities that look like one and are three

- **Fingerprinting an ATS and reading it are separate, and the gap is silent.**
  `ats.py` once recognised 22 systems while `extract.py` read 11, so 88 boards
  sat tier A with a token, resolved everywhere, polling nothing.
  `tests/test_oracle_hcm.EveryFingerprintHasAReaderTest` is the guard: every
  name in `ATS_PATTERNS` and `_VENDOR_ASSETS` must be in `extract.EXTRACTORS`
  or in that test's `INVESTIGATED` map with a reason.
- **Reading a board and reading a *posting* are a third, and that gap was
  silent for longer.** A reader whose list carries no description leaves every
  posting at `relevance: unknown` — 991 cards for SuccessFactors, 430 Oracle,
  230 iCIMS — while `bodies.FETCHERS` had two entries against 33 extractors.
  **The number to check for a new reader is not "does it list" but "does the
  list carry prose"**, and the answer is usually a per-posting resource the
  vendor already publishes: `itemprop="description"` microdata
  (SuccessFactors), a schema.org island behind `?in_iframe=1` (iCIMS),
  `recruitingCEJobRequisitionDetails` (Oracle), `/postings/{id}`
  (SmartRecruiters). `bodies.coverage` prints the per-source share; a `0%` row
  is the tell.
- **Nine sources published no description at all, and the answer differs per
  vendor -- so each was asked rather than assumed.** `bodies.coverage` printed
  `0%` for `site`, `adp`, `bamboohr`, `jobvite`, `breezy`, `personio`, `join`,
  `avature` and `jobylon`, about 2,690 postings reaching the tagger as a title
  and a date. What the probe found:
  - **Jobvite and Breezy publish a schema.org `JobPosting` island** on the
    posting page whose URL the list already stores -- the same island
    `icims_body` has parsed since it was written, carrying `jobLocation` as
    well. One shared `_ld_body` reads all three, because a vendor-shaped copy
    of it is what let the entity-decoding bug live in three modules at once.
  - **Personio publishes the whole board as XML** at `/{token}.jobs.personio.de/xml`,
    with the prose, `createdAt`, `yearsOfExperience` and `occupationCategory`
    -- its own occupation taxonomy, which is what `Job.category` is for. It is
    the *same ids* as `search.json` (26 of 26 overlap, checked before the
    switch, because a new id space would have orphaned every stored row) and
    the same one request. `search.json` publishes `"description": ""` on every
    row, which reads as an employer who wrote nothing rather than as a gap.
    **The feed is a fallback and not a replacement**: 4 of 25 tenants answer
    404 on `/xml` while serving `search.json` normally, so reading only the
    XML would have taken those boards silently to zero.
  - **ADP and BambooHR are genuinely closed** and it took asking properly. ADP's
    requisition carries no description key, `links` and `postingInstructions`
    are empty arrays, the per-requisition route returns `{}`, and `$expand` and
    `$select` change nothing; the recruitment page is a federation redirector
    in front of a JS shell. BambooHR's job page is 98 KB of application
    bootstrap with no JSON-LD, no embedded payload and an `og:description`
    reading *"Take a look at the current openings at 17Capital"*.
- **Ask what else the detail page settles before assuming a fetcher only
  returns prose.** Two of the three fields `bodies.Fetched` carries were added after
  the fact: `location` for Workday's `N Locations`, and `employer` for Hong
  Kong, whose portal publishes the employer's name on the card and nowhere on
  either list view. Without it that hub would carry fourteen thousand postings
  from nobody, which is the JobStream failure.
- **A detail URL that cannot be re-derived needs a marker, not a status code.**
  Hong Kong mints its card link per render and a rotted one answers **HTTP
  200** with the vacancy-search page. `iesjobs_body` tests the card's own
  `data-ordno` against the row it was fetched for — `get_with_url`'s lesson
  where the URL itself cannot be compared, and the `palmersquare.com` guard
  against writing one firm's description onto another's row.
- **Tier A with a NULL token is a board nobody can poll and a tier-B sweep
  never touches it** — 98 rows. **The larger population is tier A *with* a
  token and no postings**, which no sweep revisited either because having a
  token is what both other clauses test for: **167 rows**, of which three
  carried a `/` from a JSON island, four carried `tbe`, and the rest had moved
  or died. `reprobe_targets` covers both now, excluding any row whose evidence
  names `sites.py` — a hand-written reader is there precisely because the walk
  could not find the board, and Captor advertises nothing by design. The marker
  is the evidence string rather than `ats = 'site'`: two thirds of that file
  names an existing extractor, so testing the ATS name would leave every
  hand-verified token exposed.

### Fields, text and failure modes

- **A URL built unconditionally from a missing field becomes a link to the
  vendor's landing page, which is worse than no link.** `extract.workday` did
  `url=f"{origin}/en-US/{site}{path}"` with `path = externalPath or ""`, so
  **42 Workday boards held exactly one** empty-id, empty-title card opening the
  recruiting site (found at Nasdaq and Sun Life). The halves are handled
  separately: a **title and no path** is kept with `url=None` — it is a posting
  however badly published — and **neither** is not a posting at all, since
  nothing about it can be read and there is no id to re-fetch it by.
  `build_data` counts `untitled` separately as the guard for the next source
  that does this.
- **Every live SmartRecruiters row had a NULL URL — 1,507 across all 12 boards
  — and the code carried a comment describing the cause.** `ref` is a dict of
  links on some boards and a bare API self-link string on others; where it is a
  string, `applyUrl` is `null` too, so `ref.get("jobAd") or applyUrl` resolved
  to nothing and the board rendered cards nobody could open. The public ad is `jobs.smartrecruiters.com/{company}/{id}`;
  the title slug is optional. **A comment noting that a field comes in two
  shapes is not the same as handling the second one.**
- **ADP's `meta.links` looks like a location map and is a filter facet.** It
  pairs an id with "Hong Kong - Wanchai, HK", and joining it to `itemID` yields
  a confident location matching nothing — those are the places you may *search*
  by. **A wrong location is worse than none**, because the board gates on
  geography and `unknown` survives the gate.
- **Some employers write titles in letters that only look Latin.** Jane Street
  publishes `ꓟachine ꓡearning ꓣesearcher` (Lisu M, L, R), which arrived as
  "achine earning esearcher". Scan before writing the map: of 75 suspicious
  codepoints across all titles, nearly all are genuine CJK and must be left
  alone. Only letters impersonating an ASCII one are folded.
- **Entities were never decoded, and every HTML-sourced format carries them.**
  Coeli's `Business &amp; Risk Operations` folded to the token `amp`; Swedish
  spells `ä` as `&#xE4;`, which folds to nothing. Fixed in `extract`, then
  found again in `bodies` — three fetchers read HTML, so every description
  SuccessFactors, iCIMS and Jobbsafari backfilled reached the tagger with its
  entities intact. **Strip tags first, unescape second**, or a literal
  `&lt;p&gt;` is decoded into a tag and then eaten. There is now one
  implementation, `parsing.text`, and five readers call it. **Whenever a
  fixed-in-one-place rule turns up, grep for the other places.**
- **An exception inside a body fetcher ends the *pass*, not the posting.**
  `bodies.run` maps twelve threads over the queue and writes in batches of a
  hundred, so an `AttributeError` from a `.get()` on something that is not a
  dict discards up to a hundred fetched rows and skips the trailing write.
  Each fetcher shape-checks its own payload at every level. **A blanket `try`
  around the worker is deliberately not the fix**: a missing column must still
  raise, or a schema change reads as a zero-filled run —
  `tests/test_bodies.TargetsTest` pins that.
- **A regex over fetched markup is a denial-of-service waiting to happen, and
  it fails as a *stall*, not an error.** Two `ats` runs sat at 100% CPU for two
  and a half hours, wrote nothing, and looked like slow network. Both causes
  quadratic: `[^"']*(?:career|jobs|…)[^"']*` over an href that never closes,
  and `([a-z0-9-]+)\.host\.com` over an inline base64 data URI. Extract hrefs
  with a bounded pattern and match words in Python; bound every host label to
  63 characters and prefix it with `(?<![a-z0-9-])`. Cap fetched markup too —
  23 patterns over an unbounded body blocks every other thread through the GIL.

### Which reader to build next

- **It is a measurable question, not a guess.** 1,400 tier-B careers pages were
  swept for unrecognised third-party *hiring* hosts, ranked by distinct firms
  rescued: ADP 19, Paylocity 18, Radancy 12, Rippling 11, Phenom 7, UKG 5,
  HiBob 5, Talentsoft 4, Avature 3, JazzHR 3, Dayforce 3, Zoho 3, Cornerstone
  2.
- **And that ranking is the wrong order to build in.** It put Avature ninth at
  3 firms, one of which is **Two Sigma** — worth more here than ADP's nineteen.
  The count answers "what is most common"; the question is "who do I want to
  work for". **Weight the list by the firms on it before picking.**

## Board discovery (Layer 2C) and firms with no ATS

- **The firms that matter were all tier B, and the careers walk is why.** It
  settled on Jane Street's `/join-jane-street/overview/`, on a Cloudinary
  **image** for DRW and on a **PDF** for Man Group. `discover.py` exists because
  no regex over the page we did fetch can fix that: guess the token from the
  name and prove it against the feed.
- **A guessed board token must be proven by the postings, not by the token.**
  `greenhouse/cfm` is a live board of 9 postings whose first three are *Account
  Executive - Air Distribution* — a heating company, not Capital Fund Management
  — and `recruitee/radix` is a different Radix. Corroboration is a **spaced**
  needle so the run-together token cannot match itself, and a lone word never
  counts.
- **Verify a discovered board by running the extractor, not by status code.** A
  board Layer 3 cannot read is not a board, and an empty one recorded as
  resolved polls silence forever.
- **A roster trading name is not the board token.** The roster says `Akuna`,
  `Qube`, `Da Vinci`, `Old Mission`, `Squarepoint`; the boards are
  `akunacapital`, `quberesearchandtechnologies`, `davinciderivatives`,
  `oldmissioncapital`, `squarepointcapital`. `discover.Target` carries every
  name `audit` matched, and corroboration is checked against the *same* name
  each token came from, so a wider search does not become a looser test.
- **But that match is fuzzy, so a discovered board must never displace a working
  one.** `Millennium` matches *Millennium New Horizons Management*, a venture
  firm, and `Two Sigma` resolved to `x.com`. `discover.record` upgrades only
  rows that are tier B/C or tier A with a NULL token.
- **A verified board with no domain polls nowhere.** `ats_resolution` is keyed
  on the domain, so `discover.record` silently drops a proved board when the
  firm has none — Akuna, Voleon, Belvedere and Quadrature, 113 postings between
  them. The seed registry is the route.
- **A one-word firm name is always a *strong* needle, and that is the last hole
  in board discovery.** `bamboohr/blackrock` is BlackRock **Asphalt** of Tampa,
  and its postings contain "blackrock" because that is genuinely the company's
  name. No text rule separates it, so `discover._reads_as_another_industry`
  reads the postings with `lexicon.judge` and rejects a one-word match when
  *every* posting is an unrelated occupation or carries no signal. Both halves
  are load-bearing: requiring a `keep` throws away Coeli, and requiring merely
  "some rejection" keeps the asphalt board.
- **A three-letter alias will find a fund, not the firm.** A bare `AQR` matched
  *LUMYNA – AQR GLOBAL RELATIVE VALUE UCITS FUND* and put AQR's board on
  `lumyna.com`, a platform hosting other managers' strategies; Marshall Wace
  landed there for the same reason. Check what an alias matches before trusting
  it.
- **Some boards name the firm only in the location field.** Hailey HR labels
  every card with a *workplace*, so Coeli's eight postings say `Coeli Stockholm
  HK` and name the firm nowhere else. `discover.corroboration_text` reads
  location for this reason; the URL is still never read, because a guessed board
  carries the guess in every link.
- **`sjunde.se` is not AP7.** It is *Sjunde Konsultbolaget*, a Stockholm IT
  consultancy, and it resolved on a weak name match while `fi_se` publishes no
  website for the fund. `discover._domain_for` prefers non-weak over both
  sources before falling back — *excluding* weak outright was tried and is
  worse, because Coeli resolves weakly and by no other route.
- **`leverer` is Danish for *supplier*, and it looks exactly like a Lever
  board.** Probing Maj Invest's careers page for ATS vendor names matched it and
  reported a board that does not exist. A vendor-name regex over foreign markup
  needs the same suspicion as a token: read what matched.
- **Guessing careers paths rescues tier C into tier B and no further.** 150
  tier-C domains re-walked with `/careers`, `/jobb`, `/karriere`: 23 became
  readable pages, **none fingerprinted to any ATS**. That population has no
  board, and the firms that matter are reached by `discover`.
- **A `discover --roster` sweep is worth re-running and mostly re-confirms.**
  253 firms probed, 32 boards verified — and all 32 were already held. Closing
  the focus-hub names still missing is per-firm hand work like `sites.py`, not
  another sweep.
- **Some roster firms run no ATS at all, and Stockholm is where that shows.**
  AP4 publishes five openings as ordinary links, AP7 four as bolded titles
  linking out to two recruiters, Brummer one as a paragraph, and Nordea 112
  through a JSON endpoint on its own domain. `sites.py` is the answer and is
  deliberately a short list: each reader rides Layer 3 as `ats='site'` and each
  **raises** rather than returning `[]` when its anchor is missing, because an
  empty board and a broken parser are opposite facts that look identical from
  outside.
- **A firm that advertises nothing says so, and that sentence is the anchor.**
  Captor has one line saying there are no vacancies. `_prose_board`
  requires *either* a posting *or* the no-vacancies phrase. **Norron proved
  the other half of that rule and then left**: its page 404'd rather than
  saying anything, which is a different fact from advertising nothing, and
  the reader raised every poll until the roster caught up. It is `stale` now,
  the fund business having gone to Simplicity AB.
- **A hand-edited careers page has no house style.** AP7 writes three of its
  four openings as `<a><strong>Title</strong></a>` and the fourth as
  `<strong><a>Title</a></strong>` — and the fourth is the Senior Portfolio
  Manager seat. One nesting cost the most relevant row on the page.
- **Two roster firms had ceased to exist.** AP1 and AP6 were wound up at the end
  of 2025 by riksdag decision and their domains now serve AP4's and AP2's sites.
  A roster line naming a dead firm is a permanent miss nobody can close — check
  the page before building a reader for it.
- **A site that 403s every page can still be publishing a list for crawlers,
  and Citadel is the case.** Every HTML page and the WordPress REST API answer
  403; `robots.txt` and the sitemaps answer 200, and `robots.txt` itself reads
  `Allow: /` with `Crawl-delay: 10` and names two sitemap indexes. Inside them
  is **`career-sitemap.xml`, regenerated the same day** — 51 postings for
  Citadel and 85 for Citadel Securities, which is the whole board. That is not
  a wall worked around; it is the door the site points a crawler at. **Read
  `robots.txt` and the sitemap index before concluding a 403 means no.**
- **Two things in that sitemap must not be read.** `<lastmod>` is identical to
  within seconds across every entry, so it dates the file's regeneration and not
  the opening — writing it as `posted_at` is the `publication.endDate` mistake
  from job-room.ch one field over. And the slug is not a location: a few end
  `-asia` or `-us` and most end in nothing, and the board *gates* on geography,
  where `unknown` survives and a wrong city does not.
- **The board is often in the page and not in any vendor's host.** DRW ships all
  160 postings inside `__NEXT_DATA__` on `/work-at-drw/listings` — with titles,
  ids and a location *list* — while its stored careers URL was a Cloudinary
  image. The D. E. Shaw group serves its whole board, 86 cards with title,
  office and category, as one 900 KB server-rendered page. Renaissance publishes
  a dozen openings as `Careers.action?jobs=true&selectedPosition={key}` links.
  None of the three runs an ATS and all three are readable in one request.
- **A firm can proxy a real ATS through its own domain and name it nowhere.**
  Bridgewater's careers page carries `data-job-api="/jobboard"`, and
  `bridgewater.com/jobboard` is a **verbatim Greenhouse departments payload** —
  board `bridgewater89`, a token no name guess produces. The attribute was the
  only evidence on the page. Same shape as XTX's `api.xtxcareers.com`.
- **`data-*` attributes are worth reading when the markup names no vendor.**
  That is how Bridgewater was found, after `href` scanning had turned up
  nothing but CSS.
- **Six of the nine hand-found boards also had the wrong domain**, which is why
  they are `sites.Site` rows rather than `discover` results: `twosigma.cn` for
  Two Sigma, `bwasc.com` for Bridgewater, `headlands.com` for Headlands,
  `gardacp.dk` for Garda, `viviennecourt.com` for VivCourt, and — the expensive
  one — **`acadian.com` for Acadian Asset Management, which is Acadian
  *Ambulance*, whose ADP board `myjobs.adp.com/acadianhealth` had been recorded
  against the asset manager.** A wrong domain is not merely an empty feed here;
  it is a live feed belonging to somebody else. `sites.register` writes
  `domain_lookups` under the roster's own spelling, which is the route to fixing
  one.
- **A `Site` row with no reader is the cheapest fix in this project.** It names
  an extractor that already exists and a board a human verified, which is how
  Nasdaq was recorded and now Two Sigma (Avature), Northern Trust (Workday,
  ~3,600 postings), Bridgewater, Robeco, Five Rings, Headlands, Garda, Acadian,
  Teza, Wolverine, Magnetar and VivCourt. Every one was hidden by something the
  careers walk cannot do — a hop it does not take, a redirect that leaves no
  markup, a token no name produces — and none of them needed a line of parsing.
- **Robeco's board is one hop past the page the walk settled on.** `/careers`
  links to `/careers/job-openings` and only the second carries the Workday host.
  The walk goes two hops and still missed it, because six fetches is the ceiling
  and the first three candidates were spent elsewhere.
- **Two vendors are confirmed closed and a third was not.** Paylocity's board
  is still client-rendered, with `/Recruiting/Content/public-jobs-list` serving
  a stylesheet rather than an app bundle, and Jefferies' `tal.net` portal now
  answers with an **Altcha CAPTCHA**, which this project does not complete —
  the same answer as the DFSA register. **Eightfold was the third and it is
  open**; see the closures note in the ATS section for what re-checking all
  five found.
- **The Hong Kong long tail mostly runs no board at all.** Twenty-one of the
  hub's unreached firms were probed by hand: eight 404 on every careers path,
  and of the rest, Nine Masts, Ovata, Oasis and Janchor publish a page with no
  postings on it, Marshall Wace publishes early-careers only, and Capula's
  `careers.capula.com` answers 0 bytes. Only Pandtong lists openings on its own
  host. **That is the same answer tier C gave: the population has no board, and
  the firms that matter are reached one at a time.**
- **HKEX and the HKMA were in no register at all, and they are the largest
  single thing missing from Hong Kong.** `sfc_hk` enumerates licensed
  *corporations* under the SFO; an exchange controller and a central bank are
  neither, so both sat outside a universe of 79,225 firms while running live
  boards -- **HKEX 164 postings on Workday, the HKMA 14 on its own vacancies
  table**. Both are seeded now. HKEX hid for a second reason worth keeping:
  its careers page is on **`hkexgroup.com`** while the firm's site is
  `hkex.com.hk`, so a walk that starts at the domain never reaches the hop
  that names the board. **Before deciding a hub's long tail is empty, check
  whether its exchange and its central bank are in the universe at all.**
- **Four Hong Kong roster firms had a domain belonging to somebody else, and
  Capula is the dangerous one.** `capula.com` is **Capula Ltd, a Staffordshire
  engineering contractor working on nuclear and power-generation sites**, with
  a live careers page; the hedge fund is `capulaglobal.com`, whose careers page
  names `capula-investment-management-ltd.workable.com` and yields 12 postings
  including a `Quantitative Strategist (PhD)`. That row was tier B, which is
  what `ats --regrade` re-walks -- so it was one promotion away from polling an
  engineering firm's board under a hedge fund's name, the `acadian.com` failure
  waiting to happen rather than one that had. The other three are dead ends
  with no correct domain known and are recorded as `NULL`: `ortus.com` is
  **Ortus Fitness, a Spanish gym-equipment maker**, `liquid.com` is the crypto
  exchange Quoine, `panview.se` is a Swedish image supplier, `trivest.com` is
  Trivest Partners, a US private-equity firm. All five were `name-weak`
  matches. **A weak match on a one-word name is worth reading the page for
  before it is worth polling.**
- **Hong Kong's hedge-fund long tail really does run no board, and the second
  measurement agrees with the first.** Stage 33 probed 21 unreached firms by
  hand; probing the remaining ones the same way found the same answer --
  Janchor, Nine Masts, Oasis and Blue Pool serve one SPA shell for every path,
  Ovata's careers page says *No positions available* in as many words, Marshall
  Wace publishes programmes rather than postings. **Two do publish openings on
  their own host and are readers now**: Pandtong (13, including
  `Quantitative researcher` and `Machine learning researcher`) and Anatole (2
  internships). Pandtong is read in **English** from `/careersEn` -- the same
  board as `/careers` under the same `name=N` ids, and the lexicon is English,
  Swedish and Danish, so the Chinese rendering would match none of it.
- **Scoping `discover` to a register also has to re-order it.** `--source` was
  added so a hub could be swept at all -- Hong Kong's firms are almost all
  SFC-only, so `source_count DESC` sorts them behind 27,314 others and no
  `--limit` ever reaches one. Scoping alone was not enough: inside *one*
  register that ordering stops meaning "an operating company rather than a fund
  share class" and starts meaning "a multinational", because the firms several
  registers hold are the banks licensed everywhere. The first HK-scoped sweep
  probed **ING, Societe Generale, Intesa Sanpaolo, Natixis, RBC and Bank of
  China -- 50 firms, 0 boards, not one of them a Hong Kong company.** Scoped
  sweeps order by `row_count` instead.
- **Handelsbanken publishes its Swedish jobs on LinkedIn only.** The
  `careers.handelsbanken.co.uk` API its own bundle names is the **UK** board. A
  structural limit, not a gap — LinkedIn is deliberately out of scope.

## National boards (Layer 4)

- **Hong Kong's statutory board is read, and it is the source that hub was
  missing.** The Labour Department's **Interactive Employment Service**
  (`www2.jobs.gov.hk`) is Singapore's MyCareersFuture one territory over: a
  government portal carrying every job an employer advertised through the
  public employment service. `quantscraper/iesjobs.py` walks it.
  **It disallows crawling and is read anyway, at the user's instruction** —
  `robots.txt` ends `Disallow: /` above an allow-list of about forty corporate
  and sector pages, none of them finance, and names `/0/api/*` separately, so
  there is no reading on which the job pages are open and only the URL shapes
  closed. What is offered in exchange is rate: four seconds a request
  (`http.HOST_INTERVAL_S`), 715 requests, weekly, one reader — slower than this
  project's own default. Nothing about the request is disguised.
  - **It enumerates and it checks itself.** No result window, unlike
    Jobindex's 1,000 and job-room.ch's 10,000: 14,287 postings over 715 pages
    of 20, page 715 short at 7 rows, page 716 empty. Every page prints
    `Results 1 to 20 of 14,287`, which is the shortfall check's evidence, and
    a missing hitcount **fails** rather than passes.
  - **It publishes two facets and only one of them partitions, which is the
    same measurement with two different answers.** The 27 **industries** sum to
    **15,175 against 14,287**, so a posting carries several and the slices
    *cover*: one classified under none would be absent from every slice while
    the arithmetic still looked right. Refused. The 29 **job types** sum to
    **14,287, delta zero** — an exact partition — so that is what the walk
    enumerates, and every posting arrives carrying the employer's own
    occupation in `jobs.category`. **Measure a partition against the
    unfiltered total before trusting it**, and measure it again on every
    sweep: `iesjobs.run` walks the slices and then audits their union against
    the whole board, so a posting in two slices arrives as a repeat and a
    posting in none as a shortfall.
  - **That taxonomy is worth more than the word list it replaced, and the
    numbers say so.** With English occupation needles alone, 62% of the first
    2,380 postings rejected and **38% stayed `relevance: unknown`** — `School
    Worker`, `General Office Clerk`, `Storekeeper`, `Dish Washer`, `Labourer`
    — every one of them an unread card on a *focus hub*. `tagging.
    _IES_OFF_INDUSTRY` drops 21 of the 29 types on the advertiser's own word:
    `Security Guard` 1,382, `Cleaner` 1,084, `Cook / Waiter` 933, `Driver`
    806. **It is an equality test, not the subset test the other three
    taxonomies need**, because a partition means one label is the whole
    answer. `Others` and `Other Professional/Associate Professional` stay in
    — a catch-all is where a posting nobody classified lands, which is the
    opposite of evidence, and MyCareersFuture keeps its own `Others` for the
    same reason.
  - **A district is not a city, and this is the third country to teach it.**
    The board writes `Tsing Yi`, `Kwai Hing`, `Mong Kok` — finer than its own
    21-district taxonomy and matching no needle, so every one would read
    `other`, which the board *gates*. The territory leads, as it does for
    Singapore. **But not unconditionally**: the portal's own `Outside HK`
    bucket was swept, and 461 of its 741 rows name only a mainland place, in a
    vocabulary of nine words (Shenzhen 303, Guangzhou 56, Dongguan 42,
    Mainland China 17, Zhuhai 14, Zhongshan 13, Foshan 11, Huizhou 3,
    Jiangmen 2). The other 280 name a Hong Kong district *too* and are Hong
    Kong jobs with mainland travel, so they keep both. Hence: claim the
    territory unless **every** place named is outside it.
  - **The card token expires, and one short measurement said otherwise.**
    `?order=<base64>` is minted per render, and the first version of this
    reader *stored* it -- on the evidence that a twenty-minute-old token still
    worked. Tokens a couple of hours old return the vacancy-search page:
    **HTTP 200**, 53 KB of valid HTML, no card in it. The backfill filled 968
    rows and then silently filled nothing while still spending a request per
    row. **Isolating the cause is what made the fix obvious**, because the two
    candidates have opposite remedies: a seconds-old token works in a
    brand-new process with a fresh cookie jar, so it is *time*, not the
    session. So `jobs.url` is NULL -- a card whose "open" button lands on a
    search box is *worse than no link* -- and `bodies` mints a fresh token per
    posting, at the cost of a second request per body.
  - **The search field is `criteria.searchField` and a GET ignores it.**
    `?ordno=`, `/ordno/` and `?searchKeyword=` all fail outright;
    `?criteria.searchField=` on a GET returns the **whole board** while
    looking like a match, which is the dangerous shape -- read the result
    count, never the status code. The working form is a POST to
    `/0/en/jobseeker/jobsearch/simple/`.
  - **And the fresh link on that page is a `data-jobcard` attribute, not an
    `href`.** The search answers in the quickview layout, whose only `<a>` is
    the clip button, so href scanning returns nothing while the search plainly
    succeeded. **This is the Bridgewater lesson in a second place** -- read the
    `data-*` attributes when href scanning turns up nothing -- and it was the
    slowest half to find, because every step of the chain fails quietly.
  - `bodies.iesjobs_body` still tests the card's own `data-ordno` against the
    row it was fetched for: the `palmersquare.com` guard against writing one
    firm's description onto another's row. A posting the search cannot find is
    off the board, and the portal says so in words -- *No jobs matching your
    search criteria* -- which is a fact rather than a fault.
  - **The cards have a link now, and it is a form rather than an href.** The
    portal takes the order number in no GET -- `?ordno=`, `?ordNo=`, `?order=`
    and `?criteria.searchField=` were each tried against a posting deep in the
    board and every one returns page one of the whole board while answering
    HTTP 200 -- so `jobs.url` stays NULL and the board's *open* control submits
    a cross-origin form POST to the portal's own search instead. A form
    submission is not an XHR: it is not subject to CORS, it carries the
    reader's cookies, and it lands on the one-result page with a card link the
    portal has just minted. Measured from a cold jar, a warm jar, and with and
    without an XHR header: **one row, ours, in all four**. An earlier probe
    that came back with the whole board had **no cookie jar at all**, which is
    a state no browser is ever in -- and that is worth remembering, because it
    is the shape that makes a working endpoint look broken. The order number
    *is* the `job_id`, so nothing perishable is stored and the button cannot go
    stale. See `PORTAL_SEARCH` in `index.html`.
  - **The employer and the description are on the card and on neither list
    view**, which is 14,287 requests against 715 for the board. So the walk
    writes a NULL employer and `bodies.py` fills it — `Fetched` gained an
    `employer` field for this, the same way it gained `location` for Workday.
    Without it the hub would show fourteen thousand postings from nobody,
    which is the JobStream failure. **The cost is stated rather than designed
    around**: until `bodies` reaches a posting its employer is NULL and
    `firm_key` groups it under `~unknown`, so the hub opens with one large
    unattributed tile that shrinks every pass — and at four seconds a row, a
    few thousand queued Hong Kong postings are *hours* of `bodies`, which
    makes the first `daily --full` after this source lands a long one.
    `--limit` is the control and the pass is resumable.
  - **Landing a national portal means telling every board-profiler about it.**
    `lexicon.NOT_A_BOARD` and `dedup.PORTALS` both needed the name: one token
    carrying a territory's whole board profiles `non_markets` on any threshold,
    and `non_markets_board` would then have removed every unread card in a
    focus hub. It stays out of `build_data.LAYER_THREE` for the opposite
    reason — that rule needs one `last_seen` per board per poll and this walk
    writes one per *page*, so inside it the freshest page would retire every
    earlier one.
  - **What the whole source is worth was finally counted, and it is six
    postings.** Of **13,465** live Hong Kong postings from this portal, six are
    rated above `unknown` — against **277 from 1,789** postings on the firms'
    own boards in the same hub. That is **0.04% against 15.5%**, and it is the
    answer to "is this source any good": as *content* it is the worst in the
    project by two orders of magnitude. What it does give is real and small:
    `Quantitative Researcher (QR)` and `Quantitative Developer (QD)` exist
    **nowhere else in the corpus** — small Hong Kong firms running no ATS,
    which is exactly the structural gap this source was added to close.
    `Junior Trader` arrives anyway from Eagle Seven, Akuna and Invesco.
  - **Deleting the source would save no more wall time than switching off its
    body queue, and that is why it stays.** The walk is 715 pages ≈ 48 minutes
    and it runs *inside* the gather phase, concurrently with Singapore's ~70 —
    so Singapore sets that phase's length either way and the walk is free in
    wall-clock terms. **Measure what a step costs in the phase it actually runs
    in**, not on its own: the intuitive saving from dropping a slow source can
    be zero.
  - **The body queue was the expensive half and it bought one card.** Of 1,028
    iesjobs postings whose description had been fetched, **one** came out rated
    above `unknown` and **718 were still `unknown` afterwards** — against a
    corpus where a posting with a body stays unreadable 1.0% of the time. The
    cause is not a missing needle: **44% of those descriptions are
    majority-Chinese**, and `posting_language` already labels 437 of them
    `cjk`, while this lexicon is English, Swedish and Danish. So the queue
    spent ~72 minutes a week — three quarters of a `daily --full` — fetching
    prose nothing downstream can read. **Before backfilling a source, check
    what language it publishes in**; `bodies.coverage` cannot tell a body that
    was read from one that was merely stored.
  - **So `targets`' third arm inverts the rule for this source alone**: fetch a
    card for a posting the tagger has *already rated*, not one it could not
    place. The card is still the only place the **employer** is printed, and
    five of the six positives were found from the title alone with no body at
    all — so nothing is being asked of the description that it was doing. Queue
    864 rows → **5**.
  - **And `unread_census_card` takes the unreadable ones off the board.**
    `non_markets_employer` is how a national portal's noise is removed —
    profile the *employer*, since one token carries a whole territory — and it
    **cannot** reach Hong Kong, because the portal publishes an employer name
    nowhere on either list view and we have just decided not to fetch it. So
    the noise there has nothing to profile and needs the source-level answer.
    It fires on the same double evidence as the other two: the source is one
    whose unread cards have been counted, **and** this is a posting the tagger
    could not place. Measured on the build: **1,223 cards removed, board 5,718
    → 4,495, and all six rated cards verified still on it** — including the two
    reachable nowhere else.
  - **1,223 and not the 2,828 a query first suggested, and the gap is the gate
    order.** `iesjobs` rows with no `exclusion_reason` are 2,828 — but
    `rejected` is the `relevance` verdict itself rather than an
    `exclusion_reason`, and `withdrawn`, `off_location` and `off_industry` all
    fire before this one. **A gate's real cost is only readable from the build
    that runs it**, because `hit` takes the first reason that matches; counting
    a gate's population with a standalone query overstates it by whatever the
    gates above it would have taken anyway.
  - **This reverses a call written down when the source landed.** The note
    below still says `lexicon.NOT_A_BOARD` needed the name because
    `non_markets_board` "would then have removed every unread card in a focus
    hub". It would — and that is now the intended effect rather than the
    danger, because nothing had counted what those cards were worth when the
    sentence was written. `iesjobs` stays *in* `NOT_A_BOARD` all the same:
    that list also feeds `lexicon.board_profile` and `dedup`, and this is one
    gate rather than a claim that a territory's labour market is a firm's job
    board. **A protection written from a guess is worth re-measuring once the
    source has run.**
  - **The commercial boards are still closed, and for reasons robots.txt does
    not cover.** `efinancialcareers.hk` and `ctgoodjobs.hk` answer **HTTP 405
    to every path including their own homepages** — a WAF refusing this client,
    and changing the user agent to get past it is a different act from
    ignoring a text file. `recruit.com.hk` pages by ASP.NET `__doPostBack` and
    publishes no hitcount, so a sweep of it could not be checked for
    truncation. `hk.jobsdb.com` and `jobmarket.com.hk` are readable if ever
    wanted; measured, jobmarket's **entire board is 3,639 postings**, of which
    banking-finance is 234. `data.gov.hk` carries no vacancy dataset.

- **A 401 can be our own URL, and it cost this project a source for months.**
  job-room.ch was recorded as blocked on a registered API programme on the
  strength of a 401 from `/api/jobadservice/api/...` — one `/api/` too many. The
  real path is what the public site itself calls and answers a bare
  unauthenticated POST with full postings. **Read the site's own network traffic
  before believing an auth wall.** The registered API is a *different* thing: it
  lets an employer manage its own postings and no read endpoint returns the
  register.
- **`X-Total-Count` is not `x-total-count`, and the guard it feeds went
  silent.** HTTP/2 normalises header names to lowercase and HTTP/1.1 sends
  whatever the server typed, so a case-sensitive lookup found nothing, the
  advertised total read as **0**, and the truncation check — whose entire job is
  comparing collected against advertised — passed a walk that had stopped dead
  on the result window at a suspiciously round 10,000. `http._send` lowercases
  header names. The deeper lesson is the guard's: **a check whose evidence is
  missing must fail, not pass.**
- **job-room.ch's `Link` header advertises a last page that 412s.** Any request
  whose `page * size` reaches **10,000** returns HTTP 412 — Elasticsearch's
  `max_result_window`, the same trap as MyCareersFuture's 418 one country over.
  The fix is a **two-ended walk**: `sort=date_asc` is the exact reverse of
  `date_desc` (verified over a whole canton), so reading the first 10,000
  forwards and the last `T - 10,000` backwards covers any slice up to 20,000.
  Proved live: 12,033 advertised, 12,033 collected, 967 overlapping in the
  middle, where a single-ended walk returns exactly 10,000 and reports success.
- **Swiss cantons are not a partition**, and two separate things break it. They
  sum to 78,355 against a total of 80,460: `FL` (Liechtenstein) is a 27th code
  no list of Swiss cantons contains, and ~2,100 postings carry **no canton at
  all**. **Measure a partition against the unfiltered total before trusting it.**
- **A publication window is not an application deadline.** job-room.ch sets
  `publication.endDate` on every ad, and **81% sit exactly 30 days after the
  start date and 12.8% exactly 60** — two round defaults, which is a dropdown,
  not a date an employer chose. Writing it would hand ~80,000 Swiss postings a
  fabricated deadline that outranks every posting publishing a real one.
- **A published "company website" is often the recruiter's, and one flag tells
  them apart.** On job-room.ch the field is present on 19% of ads and the top
  six domains are all staffing agencies. `company.surrogate` marks an agency
  standing in for an employer it does not name, and **372 of 379 websites in a
  2,000-ad sample came from surrogate rows**. Record a domain only from a
  non-surrogate company: 0.3% of rows, every one correct.
- **Jobindex (DK) publishes its own result window, and the answer is to
  partition rather than to shrug.** Every search page carries `hitcount` and
  `max_page: 50`, so no query yields more than 1,000 postings and page 51 is a
  404 — loud, unlike Workday's `total: 0`. The board is enumerated through its
  own 81-subcategory taxonomy (200 of 200 sampled postings carry at least one),
  and the four slices bigger than the window are **split again** rather than
  truncated. "The tagger gates those anyway" is the write-time filtering
  principle 4 forbids.
- **A split dimension is only a cover if the site publishes an "unspecified"
  bucket for it.** `workinghours_type`, `employment_type` and `employment_place`
  each have one; without that, every ad leaving the field blank is dropped and
  nothing says so. Measured on all four overflowing slices, the parts sum to *at
  least* the whole every time. The obvious partition, publication date, is
  closed: `jobage=archive` answers HTTP 401 anonymously.
- **Jobindex prints two dates on every posting and only one is a deadline.**
  `apply_deadline` is the employer's stated closing date, set on about half the
  rows; `lastdate` is when the *advertisement* comes down and is set on all of
  them. `apply_deadline_asap` marks the other half as *snarest muligt*. Reading
  `lastdate` would hand a deadline-first board 17,000 dates nobody promised.
- **A national board's search results can carry the employer's own website.**
  Jobindex's `company.homeurl` resolves on 486 of 561 postings in a two-category
  sample — a live bridge into `firms` that JobStream manages for half its ads
  and MyCareersFuture not at all.
- **And MyCareersFuture had the same stop until it was measured out.** The
  Singapore walk ended on a short page too — guarded by the shortfall check,
  which is real, and still a latent truncation on the source that supplies 98%
  of the board's dated cards. Nothing had gone wrong yet: a seven-page sample
  across the walk was 100 rows every time. It stops on the empty page now.
  Measured live: page 940 is the genuine last page at 58 rows and pages 941
  and 942 answer with an empty result set, so **the fix costs one request per
  sweep.** That is the price of the guarantee, and it is worth paying wherever
  a repeat-page guard already exists to make removing the stop safe.
- **A short page is not the end of a board, and only a floor caught it.**
  Jobbsafari's first live sweep reported **5,421 postings, cleanly** — page 11
  returned 499 rows instead of 500, an advertisement withdrawn between the count
  and the render, and the walk read that as the last page. 43,000 postings were
  missing and the arithmetic looked perfect, because a short page is exactly
  what the *real* last page looks like too. Stop on an **empty** page, and check
  what arrived against the total the board publishes. `MIN_EXPECTED` is what
  actually announced it.
- **Platsbanken is not a census, and three files claimed it was.** Publishing
  there is **voluntary** for private employers, so "every job advertised in
  Sweden is published to Platsbanken" was false. Measured: of the Stockholm
  employers reached through their *own* board, JobStream carries **0 of 55** —
  not a shortfall, a disjoint set. It is a wide net, not a backstop, and
  `coverage.blindspot` prints the number every run so the assumption cannot
  creep back. The capture-recapture estimator was never wrong — it *requires*
  both samples to be incomplete — but the two turn out to be near-disjoint
  rather than independent, which biases the population down.
- **A withdrawn JobStream ad arrives with `id` set and every other field null.**
  Feeding one through the normal upsert leaves the row and wipes its title,
  employer and description — still counted, no longer readable, nothing
  announced. Withdrawals take a separate path touching only `removed_at`, and
  they are the majority of a poll: 2,826 of 5,053 changes on the first run.
- **JobStream's cursor is `timestamp`, epoch milliseconds** — not
  `publication_date`. Resume rewinds a few minutes, because a duplicate costs an
  idempotent upsert and a gap costs a posting.
- **Half of JobStream's ads have no resolvable employer URL**, so `domain` is
  NULL and the board showed 1,737 postings from nobody. `jobs.employer` holds
  the advertiser name verbatim for the sources whose board is not one firm's
  own; everywhere else the domain *is* the employer.
- **A closing date is published as a field by exactly one source, and mining it
  out of prose is a trap.** JobStream sets `application_deadline` on every ad
  and no other ATS publishes one. Hundreds of Swedish ads carry *"tjänsten kan
  tillsättas innan sista ansökningsdag"* with **no date in the sentence**, and
  Ashby prints *"unless a specific application deadline is stated"* on every
  posting it hosts. The board sorts an approaching deadline above everything
  else, so a wrong one nails the wrong card to the top of the page for weeks.
- **A 429 is not a 503 and must not share its retry schedule.** `_send` backed
  off `2 ** attempt` for both, so a rate limit spent its entire three-attempt
  budget **inside three seconds** and then raised. MyCareersFuture died ~400
  pages into a `daily --full` that way, having written 37,562 postings.
  `Retry-After` is honoured when the server sends one, clamped so an absurd
  value cannot hang a run, and a 429 otherwise waits 30s/90s/300s. Slowing down
  is what a 429 *asks for*; it is the compliant response, as distinct from
  changing the user agent or probing for the threshold, which is evasion.
- **`api.mycareersfuture.gov.sg` answers a sustained sweep in words.** HTTP 429
  with `x-amzn-errortype: ForbiddenException` and a header somebody typed:
  `scrapper: contact us via the feedback form if you have legitimate reasons`.
  It is a **rate threshold, not a ban** — it lifts within the hour and
  low-volume requests answer 200 either side of it. The host runs at one request
  per four seconds (`http.HOST_INTERVAL_S`), and **that rate completes a full
  sweep: 958 pages, 95,536 postings against 95,561 advertised, no refusal,
  ~70 minutes.** Backing off was the whole fix; nobody had to find the
  threshold. Whether to write to them via the feedback form they name is item 5
  of `ACTION-REQUIRED.md` and is courtesy, not necessity. Note
  `www.mycareersfuture.gov.sg/robots.txt` says
  `Disallow:` with a sitemap, i.e. crawl freely; the **API host publishes no
  robots.txt at all**, and the two hosts do not say the same thing.
- **A crashed poll left no row, and `alerts` then reported every source
  healthy.** This is the job-room.ch failure one step along: `_record_poll`
  closed *"a source nobody asked about"* and left open *"a source that was asked
  and did not come back"*, because it runs **after** the sweep returns.
  Singapore was down, 37,562 rows landed, `runs` held nothing, and `alerts`
  printed `all sources healthy`. `cli._poll` wraps every Layer 4 sweep and
  records `ok=0` on the way out, which is the contract `_fetch` has had for the
  registries since the beginning. **A report that cannot fail is not a report.**
- **`alerts.coverage` read `REGISTRIES` alone, so the national boards were
  missing from *both* of its lists at once.** `check` walks
  `SELECT DISTINCT source FROM runs` and therefore cannot judge a source with
  no rows; `coverage` is the backstop for exactly that, and it only knew the
  Layer 1 modules — the national boards live in the package root rather than in
  `registries/`. So a Layer 4 source that had never recorded a run was invisible
  to the check *and* to the check's backstop. `alerts._expected()` is the union
  now. **A backstop that shares the blind spot it exists to cover is not a
  backstop** — and a source in neither list is how `all sources healthy` was
  printed for ten days over a dead Singapore.
- **A refusal mid-walk ends the walk; it does not throw the walk away.** The
  pages already fetched cost the portal something, and they are committed. What
  a traceback destroys is the *arithmetic* — how much of the board was reached.
  `Sweep.blocked` carries the portal's own sentence and `problem` reports it
  **before** the shortfall check, because a refused sweep reported as
  "truncation" reads as our paging being wrong when the portal has simply
  declined. A refused `--since` top-up is a failure too: there is nothing
  incremental about being turned away.
- **A sweep that dies half way makes `last_seen` unreadable, and that is the
  real cost.** After the crash, 54,159 Singapore rows sat last-seen 17 August
  still carrying a future deadline and **nothing could say whether they were
  withdrawn or merely never reached** — the two are distinguishable only by a
  walk that finished. One finished walk resolved it to 29,262 genuinely
  withdrawn, 1,800 of them still claiming a future deadline. **The remedy for
  an ambiguous `last_seen` is a completed sweep, not a query.**
- **A source that collected nothing looks exactly like a source nobody asked
  about.** job-room.ch was built, guarded and proved against a live portal, and
  `jobs` held **not one Swiss row**. Every report in this pipeline is per source,
  so a source with no rows simply does not appear — and `alerts`, whose job is
  noticing silence, reads the `runs` table, which none of the Layer 4 pollers
  writes to. **Check `SELECT ats, COUNT(*) FROM jobs GROUP BY ats` against the
  list of modules before believing a stage is live.**

---

# The classifier (Layers 5 and 6)

`TAGGING.md` holds the dimensions. These are the rules that were expensive to
learn.

## Where a rule reads from

- **`fold` deleted every non-ASCII letter, so every Swedish rule was dead.** The
  strip keeps `a-z0-9+#`, so `ö` became a *space*: `Sjuksköterska` folded to
  `sjuksk terska` while the needle said `sjukskoterska`. Not one accented
  Swedish needle had ever matched — nurses, cleaners, drivers and shop staff
  were all reaching the board, which is exactly what "the filtering is lacking
  in Swedish ads" looks like from outside. `fold` transliterates now, so both
  spellings converge. **1,013 postings were gated by that one change, with no
  needle edited.**
- **Language detection cannot use `fold`.** `är` becomes `r` and `från` becomes
  `frn`, and function words are the whole method. `posting_language` keeps
  diacritics and returns `unknown` below four stopword hits rather than
  guessing.
- **The title decides what the role *is*; the body decides everything else.**
  Scoring relevance over the body made `Insurance Accounting & Reporting
  Specialist` a core quant role three times over, because "strong quantitative
  skills" is boilerplate and every bank's about-us names market and credit risk.
  This is not classifying on the title alone: a title carrying no signal falls
  through to the body. The body reaches rank through **two doors only** — an
  explicit years figure, and `student_only`.
- **Boilerplate is the default failure mode of any body-matched rule.**
  Exclusions fired `support_function` on "maintain strong stakeholder
  communications", and asset class read `rates` off a firm's own "we invest
  across Quant, Tactical, Fundamental Equity and Fixed Income" paragraph. Match
  the title; fall back to the body only for words no posting uses in passing,
  and grade the fallback `weak`.
- **Whenever a needle list says it reads the title, check what text the call
  site actually passes it.** This has now happened three times. Desk support was
  first: `Senior Trading Associate` sits in a department called *Trading
  Operations*, so the desk's name rejected a seat on the desk. Seniority was
  second: `rank = _first(_SENIORITY, fold(title, department))`, unnoticed while
  the needles were phrases like `head of` that a department rarely carries, and
  live the moment bare `director` went in — `Associate - Fund Governance` sits
  in a department called *Director Services*. `discretionary_investing` was
  third: Nordea's `Rates Sales - SEK Focus` sits in *Investment banking /
  Institutional banking / Markets* and was rejected outright.
- **A department is nothing but the desk's name, so it must never reject the
  role.**
- **And the fourth instance is the mirror of the other three: a department must
  never *rescue* the role either.** `desk`, `management`, `software` and
  `corporate` are all read from the title, correctly — and each was compared
  against a `certain` read from title *and* department, so a department called
  *Quantitative Research & Trading* or *Quantitative Strategies* switched the
  rejection off entirely. Measured over every live posting carrying a
  department: **thirteen have a quant word there, none in the title, beside a
  title-level rejection — and four were in the board's top two buckets.**
  Vatic's `Trading Operations Specialist` at `apply_now`; D. E. Shaw's
  `Product Manager - AI Vendor Tools`, `Technical Product Manager - Macro` and
  `Systems: Cloud Engineer` at `strong`; Point72's three `Cubist Portfolio
  Manager` postings behind them. `certain_in_title` is the fix. **`core` and
  `trading_style` deliberately keep the department**, because they ask a
  different question — *is there any quant signal at all*, and a `Trader` in a
  quantitative trading department is a quant trader.
- **Whenever a needle gets shorter, re-check what text it is matched against.**
- **`MARKETS` is a role list, `judge` step 9 read it from the body, and that was
  the single largest hole the reader's own rejections found.** The module says
  so in its own comments twice — "a markets word in the title is about the job;
  the same word in the body may only be about the employer's customers" — and
  `labels.anchored` says it a third time; step 9's absence test read
  `markets_role or markets_body` anyway, so **one word anywhere in a description
  switched `no_markets_signal` off entirely**. Of the 40 postings the reader
  hand-rejected off the live board, **19 escaped there**: Adidas's `Part-Time
  Sales Consultants` and Fortum's `Balance Settlement Specialist` on bare
  *trading*, Karolinska Institutet's `Projektadministratör` on *front office* —
  a hospital's reception desk — a `Swedish Content Writer` on *market data*,
  Accenture's `Service Now business architect` on *structuring*, and Baker
  McKenzie's antitrust associate on *capital markets*. It reads `markets_role`
  only now: **2,504 postings moved `unknown → rejected` and 29 `adjacent →
  rejected`, no `relevant` card was lost**, and every one of the 29 was read by
  hand — thirteen are one Singapore recruiter's `HSBC Life Wealth Management
  Advisor`, the rest investor relations, wealth management and a consulting
  grade ladder. **Nothing a body can prove is lost**, because the branch above
  it is a body test: `quant_body` is markets *activity*, and a description
  naming any still holds the posting open. **Steps 7 and 8 still read the body
  and must** — there the title has already been recognised as an engineer or an
  analyst, so the body corroborates a reading rather than supplying the only one
  there is.
- **A stricter step 9 amplifies every inflection gap in the lists above it, and
  that is the thing to re-measure after tightening it.** 61 of the 2,506
  removals reach step 9 only because a plural was invisible one list earlier —
  `Solutions Architect` for `solution architect`, `Investment Analysts` for
  `analyst`, `Account Managers` for `account manager`. Measured, the verdict is
  the same either way in all but one case and only the recorded *reason*
  differs, so this was left alone. **`solutions architect` is the one worth
  adding** and is not added yet: 328 live titles, and unlike the others its list
  (`ENGINEERING`) is two-sided, so the gap costs a *keep* — `Solutions
  Architect, RBC Capital Markets` should be reaching step 7 with its markets
  anchor and is falling off the end instead.
- **The English half of `_MANAGEMENT` had never been inflected and the Swedish
  half had been inflected twice.** `Delivery Managers - Tieto Banktech` escaped
  `delivery manager` and reached the board; `Undersköterskor` and `Taxiföraren`
  had each already cost a rule. Dry-run over 382,034 live titles: `managers`,
  `directors`, `leaders` and `supervisors` are 146 hits with one rated
  positively, and it reads correctly by hand. **Four more were measured and
  dropped, three of them on the *reason* rather than the count**: `partners` has
  84 hits whose two positives are `Associate, Private Equity, CLSA Capital
  Partners` — the word is in the *firm's name* and the applicant is an
  associate; `principals` is sixteen preschool principals, an occupation and not
  a rank; `presidents` and `heads of` reach only an *assistant to* one.
- **A Swedish `-er` plural must be a list and never a suffix rule.** `-n`, `-na`
  and `-rna` are safe as a compound suffix; `-er` would fire on `researcher` and
  `developer`. `redovisningskonsulter` and `ekonomiassistenter` are spelled out
  beside their singulars for that reason.
- **Investment banking is out of scope, and the gap was every IB title that does
  not spell the words.** `investment banking`, `equity capital markets` and
  `debt capital markets` had been on `NON_QUANT_FINANCE` for a long time, which
  is why `Equity Capital Markets - Associate` was already off the board — so the
  family read as handled. `corporate finance` was the hole: **94 live titles, 19
  of them on the board**, carrying `Analytiker I EY Parthenon Corporate
  Finance`, `Corporate Finance Specialist` and `SEB Corporate Finance and
  Corporate Finance Growth Analysts`. Its four positively-rated hits are three
  `Corporate Finance Executive (Commodity Trading)` at one Singapore recruiter
  and an `Analyst, Corporate Finance & Treasury`, none of them quant. **`mergers`
  is one needle for both spellings**, because `&` folds to a space so `Mergers &
  Acquisitions` and `Mergers and Acquisitions` share only that word.
- **Three IB-sounding needles were measured and dropped, and two of them name
  markets desks rather than banking coverage.** `origination` promotes 39 titles
  whose positives are LSEG's `Fixed Income Origination` and Guggenheim's `UIT
  Trading & Origination`; `corporate banking` is on `MARKETS` deliberately and
  carries 89 positively-rated titles, so moving it would be a different decision.
  The third is **`m a`, the folded form of `M&A`** — 173 titles against 29 for
  `mergers`, and four of its positives could not be accounted for by reading the
  title. **A two-letter needle is the `AQR` and `tbe` shape**: it will find
  something, and what it finds cannot be checked by eye.
- **One word, two lists, two answers — check the other list.** `_MANAGEMENT` had
  treated `vp` and bare `director` as unreachable since the user asked for
  director titles to go, while `_SENIORITY` still called them `senior_6_10`.
  Moving them needed a `_NOT_HEAD_GRADE` guard, because bare `director` swallows
  `Associate Director` — a bank's five-year grade — and `Art Director`, where
  the word is not a rank at all. `_first` takes the first bucket that hits, so
  ordering cannot express this.
- **The same trap one language over: `erfaren` was a rank and `experienced` was
  not.** `_SENIORITY` has graded the Swedish and Danish words `senior_6_10`
  since it was written — 1,463 titles — while bare English `experienced` was
  graded by nothing, so 225 of its 478 titles came back `unknown` and
  `Experienced Options Trader` at Akuna and `Experienced Trader` at Gelber sat
  at **`apply_now`**, the top of the board, for a reader with under a year.
  `mid_3_5` rather than `senior_6_10`, on two grounds: `experienced hire` was
  already on that rung and the pair must not disagree, and a prop shop's
  *experienced* means has-traded-before rather than ten years. It costs those
  cards the top bucket and nothing else — `mid_3_5` is not a `stretch` and not
  a gate. **Whenever a word is graded in one language, grep for its
  translations before assuming the English half was done first.**
- **A title-only rule is not implemented until the fall-through is closed too.**
  "The rank is in the title" was written, tested, then undone by
  `_first(_SENIORITY, title) or _first(_SENIORITY, text)`: a *partner* in
  Schonfeld's diversity paragraph made an internship a `head_or_md` posting.
- **A years figure may raise a rank and must never lower one the title stated.**
  The carve-out was written for a title that *under-sells* itself. Read the
  other way it is a leadership escape: `Senior Software Engineer` whose body
  mentions three years came out `mid_3_5` and cleared `out_of_reach`, because a
  body's smallest number is routinely the *entry* bar ("3+ required, 8+
  preferred" floors at three). Measured on the machine sheet, leadership
  containment was 46.1% and every miss was this shape.
- **A firm's name reaches the tagger only through the title, and for boards that
  is usually wrong.** SimCorp's own board advertises `Senior Software Engineer -
  Portfolio Analysis` and the word *SimCorp* is in `jobs.employer`, which nothing
  reads for relevance. `lexicon.board_profile` is the rule for the general case
  — reach for that before widening `MARKETS` again.
- **And that rule was measured, wired to a gate, and only ever allowed to say
  no.** `web/build_data.py` reads `board_profile`'s `non_markets` verdict to
  *remove* a posting; its `markets` verdict was computed on every build and
  consumed by nothing. So a board this project has read hundreds of times and
  found quant work on could lend none of it to the posting beside it — and
  **that is exactly the posting that needs it**, because the boards publishing
  no description are disproportionately the ones worth reading. Measured:
  **94% of the postings rejected as `pure_engineering` at a pure quant shop
  have no body at all.** Citadel Securities' `Machine Learning Researcher`,
  `Deep Learning ML Researcher` and `Research Engineer` read `unknown`; DRW's
  `Software Developer (Research)` and `Software Engineer, Research —
  Cumberland Systematic` read `rejected`. Neither verdict is a lexicon failure.
  There is nothing in either posting to read.
- **`tagging.quant_boards` is the other direction, and the evidence is
  `_QUANT_CORE` in the title counted over the board** — which is what breaks
  the loop. A profile taken from `job_tags` feeds the tagger its own output; a
  profile taken from `lexicon.judge` depends on which bodies happened to be
  fetched. A title matching `_QUANT_CORE` is a pure function of `jobs.title`,
  so the measurement is the same on a cold database as on a warm one, and it
  costs 17s over 419,475 titles against a re-tag measured in minutes.
- **The share is the half that keeps the banks out.** At `floor=2, share=5%`
  the 61 boards read as a roll-call rather than a threshold — Point72, SIG,
  Jane Street, Tower Research, Citadel, DRW, Jump, Squarepoint, Two Sigma, Man
  Group, Schonfeld, D. E. Shaw, Old Mission, Virtu, Millennium, Flow Traders,
  Akuna, AQR, Voleon, Radix, GTS, Chicago Trading, TransMarket, Five Rings,
  Belvedere, Da Vinci, Winton, Vatic, Aquatic, Arrowstreet, Acadian, Gelber, OTC Flow, Mako,
  Eagle Seven, Valkyrie, Simplex, Nomura/Instinet, CLSA, PIMCO. An
  **absolute** floor alone admits Citi (126 quant titles in 3,724 postings,
  3.4%), Barclays 2.8%, LSEG 2.1%, RBC 2.0%, State Street 1.9%, BNY 1.3%,
  Santander 1.1%, US Bank 1.0%, DBS 1.0%, TD 0.9% — boards that are 98% retail
  banking and would put thousands of unread cards on the page. It is the mirror of `board_profile`'s own argument for
  `non_markets`, where the *absolute* floor is the protection: there the risk
  is judging a large board by a small share, here it is judging a small share
  as a board.
- **The floor is 2 rather than 3, and the ten boards in between were read.**
  Wolverine, Mesirow, Geneva Trading, Kepler Cheuvreux, Headlands, ABC
  Arbitrage, Tudor, swissQuant, Numerix Quant, Midpoint Markets — every one a
  quant firm, none larger than twenty postings. The share had already done the
  protecting and the floor was only costing boutiques. It stays at 2 rather
  than 1 because one quant title is an accident at any size: Pandtong is 1 in
  13, a real Hong Kong quant shop, correctly excluded, because one title cannot
  tell it apart from an insurer advertising one modelling seat. **Renaissance
  is the honest miss** — its twelve openings are `Research Scientist`,
  `Real-Time Trading Programmer`, `Research Engineer`, and the word
  *quantitative* is on none of them.
- **Both branches fire only when there is no body, and that is the whole safety
  argument.** A description naming markets nowhere is evidence measured over a
  document and it keeps winning — Jane Street's `MacOS Software Engineer` and
  `Enterprise Mobility Platform Engineer` have real bodies with no markets word
  in them and stay rejected. Absence of evidence in a *stub* is not evidence of
  absence, which `lexicon.MIN_BODY` already says one module over.
- **`_SOFTWARE_SPECIALTY` is untouched by it, and the measurement is why.** On
  the same 51 boards the 124 postings that list rejects are cybersecurity,
  network, SRE, systems administration and Salesforce work, and every one
  should stay rejected — the list is the proper subset where the specialty *is*
  the job. `pure_engineering` is the ambiguous remainder, and the reader's own
  scope calls it a **down-rank rather than a hard drop**.
- **`_fit` notches an employer-read relevance a bucket below a posting-read
  one**, or Point72's `Database Support Engineer` sits level with its `Fixed
  Income Research Analyst`. Weaker than "title said nothing", which is at least
  the posting's own text.

## What a needle may be

- **A Swedish occupation is one token, so a needle cannot see inside it.**
  `Elsäljare`, `Fältsäljare`, `Tandsköterska` and `Inköpschef` all survive a
  word list. Match the occupational *head* as a suffix. Same asymmetry when
  picking heads: `-arbetare` catches *medarbetare*, which is just "employee",
  and `-assistent` catches *Forskningsassistent*, worth keeping.
- **Swedish and Danish inflect the head, so the singular needle cannot see the
  plural** (`underskoterska` against 269 `Undersköterskor`), and **Swedish marks
  the definite by suffixing it too** (`Taxiföraren`). `_TRADE_HEADS_INFLECTED`
  appends `-n`, `-na` and `-rna` rather than spelling each form out, so the next
  form nobody has seen is caught too.
- **Two more shapes leak with it**: the **workplace** where it is the only thing
  naming the profession (`äldreboende`, `hemtjänsten`), and the **assignment**
  where nothing does — 33 postings headed *Veteraner till städuppdrag!* carry no
  occupation word at all.
- **The `_MIN_COMPOUND` floor of nine characters still applies to all of it.**
  `Städarna` folds to eight and is not caught; lowering the floor would make a
  suffix test fire on ordinary words. That form does not occur — `stadarna`,
  `forarna`, `saljarna` and `kockarna` have zero hits between them across every
  live title — and the indefinite plurals that *do* occur are heads in their own
  right.
- **Five Nordic compound heads are the `-arbetare` mistake in a new language**,
  recorded in `_NOT_A_TRADE_HEAD`: `-arbejder` is *medarbejder*,
  `-medhjaelper` is *studentermedhjælper* and half of those are IT and data
  work, `-vagt` is *aftenvagt* — a shift, not a security guard — and
  `-assistenter` is *Forskningsassistenter*.
- **A compound head must be passed raw, never folded.** `fold` pads its result
  with spaces, so `fold("kock")` is `" kock "` and `token.endswith(" kock ")` is
  never true. A dry-run harness that folded its heads reported **0 hits for all
  twelve**, including one that plainly matches `pizzakock`. **A dry-run that
  reports zero everywhere is measuring itself.**
- **Check the form the corpus advertises, not the form the dictionary uses.**
  `environmental inspector` did not match `Environmental Inspectors (Field
  Based)`.
- **`Ph.D.` is two tokens.** It folds to `ph d`, so every needle spelled `phd`
  missed the majority of postings that punctuate it. Fold it to one word — and
  check the negation, because " no phd required " contains " phd required ".
- **When a needle is a phrase, check the noun form too.** `_QUANT_CORE` held
  only the participle forms, so `Algorithmic Trader` is not "algorithmic
  trading" and read as a trader with no quant signal at all.
- **A bare adjective is not evidence.** `tagging.py`'s body-only branch counted
  `quantitative` and `quant`, so `Cloud Engineer` reached `adjacent` on "body
  only 'quantitative', once". `lexicon.GENERIC_IN_BODY` had named that set and
  the other module was not reading it. In a *title* the same word is the whole
  job, which is why there are two lists rather than one edit.

- **A needle list may not repeat itself, and `first()` will never tell you.**
  A block of six needles was pasted twice into `STUDENT_PROGRAMME` and nothing
  noticed: `first()` stops at the first match, so a duplicate is inert against
  it. It is not inert against a reader that *counts* --
  `_QUANT_CORE_BODY`'s "two distinct phrases before a body alone decides" rule
  would corroborate a posting with itself. The guard walks every phrase tuple
  in both modules (`tests/test_tagging.NoNeedleListRepeatsItselfTest`) and
  found five more that were already there, including `sygeplejerskerna`, which
  is *generated* twice -- `-rna` on `sygeplejerske` meets `-na` on its plural.

## What a needle must not be

- **Every needle in a hard gate must be dry-run over the whole corpus first**,
  and **the check is not the head count but whether it touches a posting the
  tagger already rates positively.** Any needle that does is read by hand before
  it goes in. `landscape` was dropped on that test — it caught `Managing
  Technical Consultant, Landscape Architecture`, and a *data* landscape is one
  usage away.
- **Five words that look like trades name jobs this project might want**:
  `coach` is *Portfolio Manager/Agile Coach*, `pilot` is *Paint Pilot Projects*,
  `librarian` is *ECAD Librarian*, `translator` is DBS's *Data Translator*,
  `interpreter` is *Parts Interpreter*. `chef` is worse — Swedish for *manager*,
  so it would drop `Ekonomichef`, a CFO. `driver` cost one true positive and
  would eventually catch something like *Value Driver Analyst*.
- **A word can be the asset class and the kitchen.** `råvaror` is Swedish for
  commodities and for raw ingredients: it matches 49 bodies and every one is a
  cook's posting. Bare `handel` is *commerce* and names a shop as often as a
  desk. **The Nordic markets words that survive are the compounds.**
- **The Nordic quant vocabulary has almost no signal, because the Nordic quant
  postings are written in English.** Of 54 candidates dry-run over every live
  title, **forty have zero hits** — `räntebärande`, `obligationsportfölj`,
  `marknadsrisk`, `modellvalidering`, `handelsbord`, not one occurrence between
  them. **Translating the *negative* half — the occupation words — is what moves
  a Nordic board; translating the positive half is insurance.** Worth not
  re-deriving: the dry-run has now been run twice with the same answer.
- **`förvaltare` is the one Swedish word this board turns on, and it means two
  opposite jobs.** *Teknisk förvaltare* is a property caretaker;
  *Ränteförvaltare till Swedbank Robur* is a fixed-income PM. The bare head
  belongs on neither list — the qualified compounds go on `MARKETS` and the
  property ones on `_OFF_INDUSTRY`.
- **`Anlage` is `handel` in German, and it is the costliest false friend in the
  corpus.** It means *investment* and *industrial plant*, and here it is
  overwhelmingly the second: `anlagenführer` is **212 titles and every one is a
  machine operator**. The same sweep found `gestionnaire` (French for
  *manager*), `handeln` (the ordinary verb) and `kreditoren` (accounts payable).
  **Mine the vocabulary out of the corpus and read what it matches; never
  translate a word list.**
- **Two phrases that look obviously like markets words are not.** `broker`
  promotes 61 postings and **59 are insurance brokers**, and insurance is on the
  exclude list outright; `valuation` promotes 12 and they are real-estate
  advisory and forensic litigation. `dealer` passes the identical test — 8
  promotions, all genuine — which is what makes the test rather than the
  intuition the thing to trust.
- **A needle can pass the stated test and still be wrong to add.** `-ingenjör`
  reaches 972 compounds and touches no positively-rated posting, which is the
  check every gate needle is held to. It is out anyway, because the same suffix
  reaches *Softwareingeniør*, and `software engineer` is deliberately absent
  from `_SOFTWARE_SPECIALTY` because a quant-dev posting calls itself one. **A
  gate that could delete a wanted posting is worse than a page with a scroll on
  it.** When the measurement says yes and the principle says no, the principle
  is the one that was written down first.
- **A contextual list is only as safe as the strongest thing that reads it.**
  Adding a branch that reads `MARKETS` alone is what exposed bare `handel` and
  `front office` hiding on it — the latter genuine on 209 titles and a hotel
  reception on `Shiftleader Front Office, Scandic Spectrum`.
- **Prefer the source's own taxonomy to any word list you would write.**
  JobStream files every Swedish ad under one of 21 `occupation_field` values —
  an enumeration written by the employer — and 15 can never hold a quant job.
  `jobs.category` exists for this. The keep list is deliberately a *drop* list:
  an unrecognised field passes, because failing towards keeping is the direction
  this project always picks.
- **Danish occupation words are caught by nothing in `tagging.py`.** The needle
  lists are English and Swedish, and Danish is close enough to look covered and
  far enough not to be: `sygeplejerske`, `pædagog`, `lærer` and `rengøring`
  match no Swedish needle. This is why the Jobindex gate is the board's own
  taxonomy.
- **American English is a different vocabulary, and "the list is in English"
  hid it for as long as the US was deprioritized.** 3,385 American postings sat
  at `relevance: unknown` — the same diagnosis the Nordics gave, and the same
  two-sided repair. From below: `nurse`, `medical` and `clinical` were all
  present and caught none of `LPN/MA/EMT`, `Cardiac Sonographer`, `Clinic
  Assistant`, `Dietary Aide` or `Health Unit Coordinator`; `janitor` caught no
  `Custodial Worker I`. An American **television group** publishes through the
  same ATS platforms as the trading firms, so `WSMV-Station-Nashville` arrives
  mixed in with anchors, meteorologists and multimedia journalists.
- **The whole American batch was dry-run and exactly one needle touched a
  positively-rated posting.** `environmental services` reaches `Equity Research
  Associate - Environmental Services` — an equity research seat covering the
  sector, the `landscape` collision again. The aide's own title went in instead.
- **Three more American needles were dropped on the principle rather than the
  count**, all clean on the numbers: `sales lead` is the `salesperson` argument
  again and this list has refused `sales associate` for years; `security
  officer` reaches `Chief Information Security Officer` seven times, and a CISO
  is a corporate function rather than another profession, so the *reason* would
  have been wrong even where the verdict was not; bare `advanced practice`
  reaches `Advanced Practice Wealth Banker`, so the two clinical compounds went
  in instead.
- **`exchange traded` was on `MARKETS` and never matched, because the corpus
  writes `ETF`.** Fourteen Invesco and AllianceBernstein desks sat unread —
  `ETF Strategist`, `Sr. Equity ETF Strategist`. `market making` was the same
  omission one word over. **`secondaries` failed the same test that admitted
  them**: all eleven promotions are private-equity, infrastructure and
  real-estate secondaries, which is `discretionary_investing` arriving under a
  markets-sounding word. `order management` was already refused for being
  Motorola's supply chain — the American read found it independently, which is
  what a rule that holds looks like.

## Two-sided rules

- **A markets word in a body is two different claims and `MARKETS` did not
  separate them.** The module's own docstring says it — "a markets word in the
  title is about the job; the same word in the body may only be about the
  employer's customers" — and `judge` step 9 was fixed for it while steps 7 and
  8 were not. The note defending that said the two remaining body reads are
  safe because "the title has already been recognised as an engineer or an
  analyst, so the body corroborates a reading rather than supplying the only
  one there is". **That is true of step 7 and false of step 8**: `AMBIGUOUS`
  carries bare *consultant* and bare *associate*, which are not
  finance-adjacent at all, so there is no reading for the body to corroborate.
  `lexicon.MARKETS_EMPLOYER` is the seventeen phrases that name what a firm
  *is* rather than what a job *does* — `asset management`, `financial
  institutions`, `treasury` — and `MARKETS_IN_BODY` is the rest.
  `proprietary trading`, `hedge fund`, `trading floor`, `trading desk`,
  `buy side` and `sell side` are deliberately *not* on it: every large bank
  writes *asset management* and only a prop shop writes *proprietary trading*.
- **Narrowing both steps was tried and the hand sheet refused it.** It moved
  743 postings out of `unknown` and cost the sheet its **first false rejection**
  — an `AI Engineer` the reader had labelled `adjacent`, rejected as
  `pure_engineering` once its body's *investment management* stopped counting.
  Narrowed to step 8 alone: hand sheet **67.7% → 68.4% with zero false
  rejections**, board 4,565 → 4,365 cards, unread 41% → 38%, shortlist 201 →
  202. **The criterion is the hand sheet and it is not a formality** — the wide
  version looked better on every aggregate.
- **Ranking the board's positive cards by the phrase that decided them is the
  diagnostic that finds a rule nobody would think to question.** Every
  relevance tag records its evidence, so grouping the board by that string
  says which single needle is doing the most unexamined work — and the second
  largest block, 351 live postings, reads `title 'trading', 'trading'`: a
  two-sided test satisfied twice by one word, because bare `trading` is on
  `_QUANT_ADJACENT` *and* on `MARKETS`. **It is inert, and that was measured
  rather than assumed**: all 351 fall through to the markets-title branch,
  which fires on the same word and confers the same `adjacent`. What is wrong
  is the evidence string, not the verdict. The method is what to keep — it is
  the only view here that is ranked by *leverage* rather than by volume.
- **The companion check is consistency: one folded title, two verdicts.** If
  the same title reads `relevant` on one board and `rejected` on another, the
  difference came from somewhere other than the title, and that somewhere is
  either evidence or noise. Measured over every live posting, **eight folded
  titles hold both a positive and a rejection**, and every split is explained:
  `software developer` is rejected at 96 firms and `adjacent` at DRW on the
  board profile, `applied ai engineer` is `adjacent` at Millennium and
  rejected at DBS, `machine learning engineer` is carried by *trading* in Jane
  Street's title. Nothing is split by accident, which is the answer this check
  exists to get.
- **A weak positive needs a markets word beside it.** `judge` reasoned this way
  about engineering titles and nothing else did, so a `Computational Chemist`
  whose body says "model validation" once, a `Thermal - Fluids Analyst` and a
  `Cloud Engineer` all came back as quant work. `Data Scientist` is a quant hire
  at a systematic fund and a growth-analytics hire at a payments company, and
  this corpus holds both.
- **One quant phrase in a body is not a quant role.** `Data Management Analyst —
  Data Governance` says "model validation" once, the way every governance
  document does. A body-only reading needs a second distinct phrase before it
  can reach `relevant`.
- **But counting phrases is the wrong rule, and only a dry-run showed it.**
  `Thermal - Fluids Analyst` carries *model validation* **and** *numerical
  methods*; a payments company's `Data Scientist` carries *time series* **and**
  *statistical modelling*. **The quantitative *method* vocabulary belongs to
  every technical field and the markets vocabulary does not** — `monte carlo` is
  derivatives pricing at a bank and radiation shielding at a reactor. So
  `lexicon` splits its body list: `QUANT_MARKETS_BODY` carries a body alone,
  `QUANT_METHOD_BODY` needs a markets anchor. 103 postings moved, hand-read in
  full — a radiation-shielding engineer kept by *monte carlo*, a robotaxi tech
  lead by *time series*, and a **garage-door salesman by *options pricing***.
  Put the doubtful ones in the method bucket: a wrong entry there costs nothing
  unless the posting mentions markets nowhere, which no genuine quant
  advertisement manages. `quantitative finance` sits there for that reason.
- **A body can overturn a title-based occupation rejection, and it is the same
  bug one level up.** `judge` step 6's escape hatch was a single `quant_body`
  phrase — so `Wealth Advisor` **with no body rejects, and the same title with a
  28,572-character body came back `undecided`**. The escape needs a phrase from
  `QUANT_MARKETS_BODY`; step 5 has already let every quantitative title through
  before step 6 runs, so the hatch was never protecting a quant title.
- **Where a specialty is the job, no markets context changes that.**
  `lexicon.ENGINEERING` is deliberately two-sided and must stay so — `Software
  Engineer, Trading Systems` at Optiver is in scope.
  `tagging._SOFTWARE_SPECIALTY` is the proper subset where the ambiguity does
  not exist. Six hand-labelled rejections had all reached `adjacent` on the bare
  word *trading* — the name of the platform, not the work.
- **A `ENGINEERING_HEADS` suffix is safe *because the list is two-sided*.**
  `Systemutvecklare till SEB Markets` keeps; `Fullstackutvecklare till en
  e-handelsplattform` does not.

## Verdicts and ordering

### Four families the reader asked to be rid of, and two ways of being rid

**"There are a lot of legal and audit jobs that are incorrect... give it a
pass. Also, heavily downgrade IB style jobs such as equity research or
similar... same for pure IT roles, or non quant development roles, cybersec
roles."** Two instructions, and they are not the same instruction, so they are
implemented differently.

- **Legal and audit/tax *reject*, and the vocabulary had to go in twice.**
  `lexicon.CORPORATE` carried `counsel` and `paralegal` and not bare
  `legal <noun>`; `NON_QUANT_FINANCE` carried `auditor` and `tax analyst` and
  not the grades those firms advertise -- `Audit Associate`, `Tax Senior`,
  `Assurance Associate`. Both lists reject inside `judge`, **which runs last**,
  so a legal or audit title carrying an ordinary markets word had already
  reached `adjacent` on the branch above: `Securities Trading Attorney` and
  `Legal Counsel (Equity Derivatives, Trading Documentation)` on bare
  `trading`, which is on `_QUANT_ADJACENT`. So they are *also*
  `tagging._EXCLUSION` categories, where `rejecting` is checked before the
  weak-positive branch -- the same ordering argument `lending` already makes.
  Dry-run over 502,782 live postings: **legal is clean of positives entirely**,
  and audit reaches exactly one, `Audit Specialist, Credit Risk`, which
  `_QUANT_CORE_TITLE` spares because `core` is tested before `rejecting`.
  Board effect: legal 19 -> 8 cards, audit/tax 64 -> 18.
- **The other three *rank*, through a new `fit` bucket.** Sell-side research,
  enterprise IT and non-quant development are real work in a real industry and
  the reader does not want them, which is what `fit` is for -- "the one
  dimension that encodes the user's profile". So `relevance` is untouched, the
  evidence is untouched, the card stays filterable, and `_fit` returns
  **`background`**, ranked at **-1: below `unknown`**. That ordering is the
  point: *nothing decided* is a weaker reason to skip a card than *read, and it
  is a different line of work*. `out_of_scope` goes to -2 for the same reason,
  which also buries the 42 student-only cards a graduate cannot take.
- **Both guards on `_buried` are load-bearing and the dry-run is why there are
  two.** A quant word in the title spares `Quantitative Technologist (DevOps)`
  and `Credit Quantitative Research - Associate`; a *markets* word spares
  `Full Stack Engineer - Equities Autocallables`, `Site Reliability Engineer -
  Algorithmic Trading` and `Platform Engineer, C/FICCO`. Measured over 502,782
  postings the three lists reach 259, 11,228 and 6,580 and **not one is rated
  `relevant` or `less_relevant`** -- and the overwhelming majority were already
  `rejected` and off the board, so what actually moves is about 150 cards.
- **Sell-side research is checked *before* the markets guard and the two
  engineering families after it, and the asymmetry is not an oversight.**
  `equity research` is itself on `MARKETS`, so a guard that spared any title
  carrying a markets word would spare every one of these -- it would read
  `Equity Research Associate - Large Cap Banks` as a desk seat on the strength
  of the words naming the thing being buried. For the engineering families the
  markets word is a *qualifier somebody added*, and it is exactly what
  separates `Full Stack Engineer - Equities Autocallables` from `Full Stack
  Engineer`.
- **The security desk needed the analyst seats, not just the engineer.**
  `_SOFTWARE_SPECIALTY` named `security engineer` and `information security`
  and stopped, so `Senior Cyber Threat Analyst` reached `judge` step 8 as an
  `analyst`. Eleven phrases added, all clean. **Bare `iam` was measured and
  left out** -- 206 hits, all clean, and a three-letter token is the `AQR`
  shape whatever today's numbers say; `identity and access` says the same thing
  and cannot collide.
- **Board effect, measured end to end**: 4,365 -> 4,298 cards, 260 cards moved
  to `background`, IB/research 102 of 103 buried, IT/cyber 22 of 32, non-quant
  development 81 of 93 -- **and the shortlist did not move, 202 to 202.** The
  hand sheet went 67.7% -> 69.9% with **zero false rejections at both ends**.
  The machine sheet gained two, `Internal Auditor – Financial risks and models`
  and `Associate Sales Engineer`, both of which are the instruction working.


- **`lexicon.judge` is the last word on relevance, and it must stay last.** It
  carries the long occupation lists while `_EXCLUSION` carries seven categories,
  so a `Wealth Advisor` fell through both and was reported `unknown`: "nothing
  looked at this", when three rules had. It runs only on the branch that would
  otherwise emit `unknown`, so it can convert a non-answer and can never
  overturn a positive.
- **`judge` returning `undecided` is not evidence of anything.** It is the
  default for a title matching no list, which in this corpus is `Regional Sales
  Manager` by the thousand. Require a real anchor before treating it as a near
  miss.
- **`lexicon.MARKETS` existed, was correct, and nothing read it for relevance.**
  So `Market Data Specialist` and `Backoffice Administrator - Mutual Funds`
  returned the same verdict as a purchaser. The branch reading it runs **last,
  after `judge`**, so it can only convert an `unknown`, and it confers
  `adjacent` and no better — a markets word says *where* a posting is, never
  what the work is.
- **Stopping a rejection is not the same as conferring a reading, and half a fix
  looks exactly like a whole one.** `discretionary_investing` came off the
  reject list and **201 of the 342 postings that then reached the board arrived
  at `relevance: unknown`**, sorted to the bottom with the purchasers —
  `Investment Analyst, Public Equity` ranking below `Bäcker`. **Whenever an
  exclusion is softened, check what the posting then lands on, not merely that
  it survived.**
- **A management title outranks a weak positive, the same way an exclusion
  does.** `Director of Trading` and `Product Manager - B2C Credit` reached
  `adjacent` on one ordinary word while announcing that somebody else does the
  work. An unambiguous quant word still wins, so `Head of Quantitative Research`
  stays `relevant` and its seniority is what says it is out of reach.
- **A student rung outranks a management word**, because that is the grade the
  title states about the applicant. Nordea's `Student Client Credit Manager`
  was rejected on *manager*, which there names the book.
- **A corporate function outranks a quant word; a desk does not — and the two
  were on one list.** The desk ladder is three rungs (`desk and not core`
  rejects, `desk and not certain` demotes, an unambiguous quant word reads
  normally) and the third rung is right for a *desk*: `Quantitative Researcher,
  Trading Operations` is a researcher embedded in the ops org, and only a
  **body** describing reconciliations should demote one. But `recruiter` and
  `recruitment` were on `_DESK_ADJACENT` too, and **a recruiter does not live
  next to a trading desk, a recruiter lives in HR.** So `Quantitative Campus
  Recruiter` at SIG, `Campus Recruiter, Machine Learning and Quantitative
  Research` at Jane Street, `Senior Recruiter, Quantitative Research` at Voleon
  and `Experienced Quantitative Investing Recruiter` at Two Sigma all read
  `relevant` and reached the top of the board — every one of them hiring the
  reader's colleagues rather than the reader. Measured: **eleven live titles
  carry a corporate function and an unambiguous quant word, ten are recruiters
  and the eleventh is Northern Trust's `Director Quantitative & Index Product
  Marketing`.** Unanimous, which is what makes it a rule. `adjacent` rather
  than `rejected`, following `judge` step 1, which meets the same collision and
  deliberately downgrades to a *read*. **And the branch must test for the quant
  word**: without it, it runs ahead of the exclusion list and promotes every
  ordinary `HR-ansvarig` from rejected to adjacent — it exists to stop a quant
  word lifting a corporate title, never to lift one itself.
- **Investing by judgement is not quant work**, and `investment analyst` and
  `portfolio analyst` were weak positives while the hand sheet rejected nine
  such rows in a row. It is an exclusion now, matched on the title and read
  after the core check, so `Quantitative Analyst, Private Equity` keeps its
  quant reading.
- **Most postings with "Trader" in the title are not quant trading.**
  `trading_style` splits `Agency MBS Trader` from `Quantitative Trader`. Two
  things it got wrong first: it keyed on `role_class: trading`, whose lexicon
  includes bare *trading*, which is the name of a **department**.
- **`heavy_systems` is the one exclusion that reads differently in a title and a
  body, and both halves are load-bearing.** In a *body* it must not reject:
  `fpga` in a paragraph was removing 295 postings, including **Jane Street**'s
  `Low-Latency Engineer`. In a *title* it must: `Junior FPGA Engineer` at Eagle
  Seven is a hand rejection reading "electronics work". The filter that builds
  `rejecting` and the one that builds `hard` are different lists for this reason
  — check both when either changes.
- **A compulsory doctorate is an eligibility fact, not a verdict.** Two rows
  were labelled `rejected` with the note *"perfect fit — but has hard
  requirement of phd"*, and *perfect fit* decides where it belongs: relevance
  stays `relevant` and the posting comes off through `GATES`.
- **A doctorate in the *title* gates, and this reverses an earlier reading.**
  The note here used to say bare `phd` must never gate, on the evidence that
  220 titles carried it and 29 were rated positively — **and those 29 were
  never read**. Re-measured: 437 titles carry a doctorate, 71 are rated
  positively, and **69 of the 71 name a doctorate and no lesser degree**.
  `Quantitative Researcher (Ph.D.)` at Old Mission, `Quantitative Researcher
  Phd Graduate Asia` at Citadel Securities, `PhD Degree Required — Quantitative
  Analyst/Programmer` at Cerberus — two of them at `apply_now` and six at
  `strong`, on a board built for a reader who has no doctorate. The head count
  was never the test; **reading what a needle promotes is**, and the rule that
  came out of reading them is *sole*: a doctorate with `BSc`, `MSc`, `master`
  or a bare `or` beside it does not gate, which is the only two exceptions in
  the corpus. It stays a `GATES` entry rather than a rejection, so one deleted
  line puts all 437 back.
- **A five-letter abbreviation is the `AQR` shape, and bare `strat` was one.**
  It sat on `_QUANT_CORE_TITLE` and reaches **12 live titles, nine of them
  false** — six copies of an advertising agency's `Solutions Architect - Strat
  Media` and two `Multi-Strat and Investment AI Specialist`, where the word
  names a strategy *type* rather than Goldman's job family. Of the three
  genuine ones, two carry `quantitative` or `quant` and keep their reading
  without it and the third is a `Principal`. `strats` stays and is clean on all
  four of its live titles. **Reading what a needle promotes is the test for a
  promoting needle as much as for a gate needle.**
- **`vikarie` is a contract, not a profession**, and gating on it would delete a
  temporary quant seat on evidence about its duration. **An apprenticeship is
  likewise a contract** — Swiss-German `Lehrstelle` and `Lernende/r` belong in
  `STUDENT_PROGRAMME`. **`Praktikum` is not one of them**: it is German for
  *internship*, and its one positively-rated hit is `Praktikum Private Equity`.
- **And that contract has five names, four of which were missing.** Bare
  `ausbildung` (332 live titles, replacing three qualified forms that caught
  only the phrasings somebody had seen), `lehrling` (8), `alternance` (93),
  `apprenti` (77), `aprendiz` (25), `vocational trainee` (7) — not one of them
  touching a positively-rated posting, and all of them arriving through **one
  European truck-dealership network** whose apprentice adverts were on the
  board. **Bare English `apprentice` is out on the reason rather than the
  count**: it reaches Euronext's `Treasury Apprentice`, a finance seat, and
  this list rejects outright.
- **`student_intern` is not a seniority.** It was the one value on that ladder
  read from a *body*, so the labelling sheet kept asking a question the tagger
  does not answer. Being a student is `hard_gates: student_only`, and a
  contract.

## Geography

- **A country name in a city's list claims a city it does not know.** `sweden`
  sat in the `stockholm` tuple, so every Swedish ad read Stockholm. Harmless
  while geography ranked; under a gate it deletes postings for being somewhere
  they are not.
- **And a country that genuinely *contains* a focus hub does the same thing
  from the other side.** `Hong Kong, SAR, China` is one place matching two
  hubs, and 89 live postings write it that way — `Hong Kong, China` and
  `HK - Hong Kong, China` are the rest. It gates nothing, because the board
  shows both, and it files a focus-hub card under *Deprioritized* as well, so
  group-by-place shows it twice. `deprioritized` was deliberately outside
  `_RESIDUAL_OF` on the grounds that it spans four countries and is nobody's
  complement — true, and `china` is the one needle on it that contains a focus
  hub, so it goes in with a `_COUNTRY_WORDS` set of exactly that word.
  `Hong Kong; Shanghai` keeps both, because `shanghai` is a town; `Amsterdam;
  Frankfurt` keeps both for the same reason.
- **A single *employer* can be its own administrative unit, and HKEX is.** Its
  Workday board writes the office rather than the city — `HK-CMP 6/F`,
  `HK-TWO ES 11/F`, `HK-TKO 5/F` — so **all 164 postings matched no needle and
  read as `other`**, which the board gates. Same failure as `Wallisellen, ZH`
  at one firm's scale, and the same handle: `_HK_SITE` is anchored on the raw
  location, never `fold(location, title)`, because `hk` is two letters. HKEX
  writes `CN-Shenzhen-HyQ` and `UK-London` by the same convention and both
  already resolve on the city, so only the Hong Kong half needed a pattern.
  Dry-run first: **not one live posting in the corpus wrote a location
  beginning `HK-`**, so it can claim nothing already read correctly.
- **A national board writes the *administrative* place, and each country picks a
  different one.** Jobindex writes a postcode and a town (`2650 Hvidovre`),
  Jobbsafari a municipality (`Ludvika`), job-room.ch a town and a **canton
  code** (`Wallisellen, ZH`) — so each landed with most of its corpus in `hub:
  other`, which the board gates. Switzerland was loudest: **18,562 of 22,946
  postings in a focus hub** read as somewhere they are not. The handle is the
  source's own administrative unit, matched against the **location alone** for
  the same reason US state codes are: `SO`, `BE`, `AG`, `UR` and `GE` are
  ordinary words in a title.
- **A tie-break written for one focus hub expires when the other side becomes
  one too.** `AR`, `NE` and `FL` were left off the canton list because they are
  also Arkansas, Nebraska and Florida, on the rule that *a false hit in a focus
  hub is worse than a false miss* — true while only Switzerland was focus.
  Promoting the US made that rule say nothing, and the question became simply
  which reading is right, which is a count: `, AR` is **235 postings and every
  one is Appenzell**, `, NE` is 419 of which **380 are Neuchâtel**, and `, FL`
  is 980 of which 938 are Florida. So `AR` and `NE` are cantons now and `FL` is
  still a state. **Nebraska's head count survives because `_HUBS` is read
  first** and `omaha` is named there. Liechtenstein is the leftover — `Vaduz,
  FL` and `Schaan, FL` are filed with Switzerland, which is where job-room.ch
  files them.
- **Case-folding a country-code pattern is pure loss, and `\b` lets a full stop
  in.** `_US_STATE` was `re.IGNORECASE`, so an ATS writing the *country* in
  lowercase gave Bengaluru to Indiana, Berlin and Mainz to Delaware, Casablanca
  to Massachusetts and Buenos Aires to Arkansas; and `\b` let `Dublin, Co.
  Dublin, Ireland` read as Colorado **37 times**. Uppercase only, and
  `(?![.\w])`. **Two codes are wrong more often than right even in upper case**
  and are off the list entirely: `, IN` is 279 postings of which more than half
  are Bangalore and Pune, `, DE` is 190 of which more than half are Glatten,
  Meerane and Stuttgart. Their American half is named instead —
  `indianapolis`, `wilmington de`, `dover de`.
- **`Austin Station` is an MTR stop, and this one is measured and *not*
  fixed.** Hong Kong's statutory board writes a railway station as the
  district -- `West Kowloon Station/ Austin Station` -- so twelve Hong Kong
  postings read `us_other` as well as `hong_kong`, which is the
  `Hong Kong, SAR, China` double-filing one hub over. **The needle is right
  and the collision is rare**: `austin` reaches 996 live postings and 984 are
  Texas, so dropping it costs eighty times what it saves, and there is no
  negative-needle mechanism in `_HUBS` to express "Austin but not Austin
  Station". It gates nothing -- `hub` is multi-valued and the card is already
  correctly in a focus hub -- so the whole cost is a handful of cards
  appearing twice under group-by-place. Recorded so the next reader who sees
  `us_other` on a Hong Kong card does not go looking for a bug.
- **`georgia` is the `Åre` lesson in a new alphabet.** It reaches Tbilisi and
  Vancouver's Georgia Street, and buys nothing that `atlanta` and `, GA` do not
  already hold. Out. `washington` was kept — every hit is the state or the
  District.
- **A residual can be the complement of more than one hub, and the value has to
  be a set to say so.** `_RESIDUAL_OF` mapped one bucket to one focus hub,
  which is right for `sweden_other`; the US has three metros, so `us_other` is
  the complement of all of them at once — and its "country words" are the
  country's names *plus* the three states, since a state is what contains its
  metro. Without that, `Chicago, Illinois` is one posting claiming two places.
- **Whenever a new source lands, bucket its `hub` values before believing the
  board**: `other` filling up is what a place-list gap looks like from outside.
- **A leading four-digit number is a postcode in Denmark and a street number in
  North America.** Reading `^\d{4}` as a postcode claims **225 US and Canadian
  street addresses as Copenhagen** — `2005 Market Street, Philadelphia` — and
  Copenhagen is a focus hub, so those go *on* the board. The names went in a
  list instead, each dry-run over the corpus.
- **A place name folds into somebody else's word, and the dry-run is the only
  thing that finds it.** Sweden's 315 municipalities went in and seven came
  straight back out: **`Åre` folds to `are`, the ISO code for the UAE, and
  reaches 83 Workday postings in Dubai**; `Vara` is Dubai's virtual-asset
  regulator, `Eda` is electronic design automation, `Sala` is a Venetian waiter,
  `Malå` is Sichuan food, `Mark` is Singapore's Green Mark, `Salem` is Oregon.
  **Take the candidate list from the source's own taxonomy** — anything it does
  not carry is not that country, which is what kept `Island`, `Bangalore` and
  `Paris` out.
- **A gate makes every gap in a place list a deleted posting**, the opposite of
  the pressure a ranking list is under. `2 Locations` is what Workday publishes
  for 6,281 multi-site postings and reading it as `other` claimed we had looked
  — it is `unknown`, and `unknown` is kept.
- **But `N Locations` is not a posting that named no place, and calling it
  `unknown` only stopped the bleeding.** It is a posting that named *several*,
  summarised by a list field too narrow to hold them — and Workday's **detail**
  endpoint spells them out in `location` + `additionalLocations`. That summary
  was **8,004 postings, 58% of the whole `hub: unknown` bucket**, and it is
  exactly the multi-location population, so it cost the board twice: the card
  said `unstated` where the answer was knowable, and a seat open in Stockholm
  *and* Copenhagen appeared under neither. `bodies.py` already fetched that
  page for its description and threw the locations away; it returns
  `Fetched(description, location)` now, with a second target queue for postings
  whose location is the placeholder regardless of body or relevance. **Only the
  placeholder is ever overwritten** — `Remote` is deliberately not treated as
  one, because the detail endpoint answers it with the requisition's anchor
  office and writing that would pin a remote posting to a city nobody has to
  travel to.
- **`hub` is multi-valued, and a country bucket is a complement rather than a
  second place.** A posting open in Amsterdam and London carries a row for each.
  But `sweden_other` means "in Sweden and *not* Stockholm", so a residual is
  dropped when **every needle it matched was the country's own name**.
  Collapsing on the bucket instead throws `Copenhagen, Aarhus`'s second city
  away.
- **A scalar subquery over a multi-valued dimension picks a row at random.**
  Three places read `hub` that way and all three had to become `group_concat`.
  `shortlist`'s copy was also unpinned to a lexicon version, so it summed every
  retired tagger as well — two bugs in one line.
- **Making a dimension multi-valued in the tagger is half the job; the board
  has to stop collapsing it too.** `hub` was multi-valued end to end *except* in
  `index.html`'s grouping, which keyed on `hub[0]` — so **group by place**, the
  one view whose entire question is "what is open in Copenhagen", answered it
  only under Stockholm for a two-city seat. The comment defending it said
  filtering and the rail counts still saw both places so only the pile had to
  pick one; that was the wrong trade, because anyone who filtered to Copenhagen
  then watched the posting vanish into a pile named for a city they had just
  filtered out. Every `GROUP_KEY` returns a *list* now, and a card rendering
  twice is the point rather than a cost. **`GROUP_NAME` had to start reading the
  key rather than `list[0]`** — a Copenhagen pile led by a Stockholm-first
  posting was otherwise titled "Stockholm".
- **A copy of the hub list drifts the moment a hub is added, and there were
  three of them.** `labels._NEARBY` restated the six focus hubs plus
  `deprioritized`, so promoting the US would have left the labelling sheet
  ranking New York level with Bucharest; `coverage.unmeasured_hubs` restated
  the focus hubs minus Stockholm, so it would have printed five while nine
  existed — **quietly claiming New York, Chicago and Boston were measured when
  nothing had measured them**, which is the worse of the two because a coverage
  report that overstates itself is the one number nobody re-checks. Both are
  derived now, and `tests/test_tagging.HubTableIsSelfConsistentTest` pins all
  three against each other. `web/build_data.py` was already derived
  (`_HUB_ORDER = tuple(tagging._HUBS)`) and needed nothing — which is the
  pattern to copy.

## The board's gates

**Eleven gates now, and the two oldest are not classifications at all.**
`withdrawn` and `retired_board` answer *is this posting still on offer*, which
is prior to *is it wanted*, so they run first and every other gate's count now
means "of the postings still open". The seventh is the reader's own click; the
eighth is `non_markets_employer`, the board profile one level down.
`hand_rejected` reads `labels.csv` — the corrections `python -m quantscraper
corrections` pulls off the live board — and removes what the reader has already
said no to. Until it existed a Reject click lived in one browser's
`localStorage` and the card came back on the next build, in a new browser, or
on another machine.

- **Nothing on the board asked whether a posting was still listed, and 30,522
  of 138,961 live Layer 3 postings were not.** `jobs` rows are never deleted
  and `removed_at` is written by `jobstream` alone, so a posting whose board
  stopped listing it stayed on the page for as long as the database did. JLL,
  Citi, TD and US Bank were each turning over 40–50% of a three-thousand-posting
  board across three weeks, and every retired ad was still a card.
- **The rule reads no clock, and that is the whole design.** "Older than N
  days" fires on the *absence* of evidence — it empties the board whenever a
  run was simply not made, which is the one thing every gate here is forbidden
  to do. `withdrawn` compares a posting against **its own board's last complete
  read** and against nothing else, so a board untouched for a year keeps every
  card it has, and a partial `jobs --limit` run is safe because each board's
  answer is independent.
- **That comparison is exact rather than a heuristic, and one line in `db.py`
  is why.** `upsert_jobs` stamps one timestamp per call and `extract.run` calls
  it once per board, so every row a board writes in a poll shares a `last_seen`
  and the newest one *is* that board's last complete read. A poll that fails or
  comes back empty writes nothing and moves nothing, so the cards stay — the
  failure-safe direction. **Check that property before trusting the gate**: if
  anything else ever starts writing `last_seen` per row, this silently inverts
  and the freshest posting on a board retires all its neighbours. `bodies.py`
  deliberately does not.
- **It applies to Layer 3 only, and that restriction is the safety argument
  rather than tidiness.** `jobtech` is a *delta* feed and `jobindex --since`
  tops up from where the data already reaches, so on those sources "absent from
  the latest poll" describes most of a perfectly live board — applying this
  rule to them would empty Sweden and Denmark on the next build. They manage
  withdrawal themselves. `LAYER_THREE` is derived from `extract.EXTRACTORS`
  rather than restated, the same way `_HUB_ORDER` is derived from `_HUBS`.
- **`retired_board` is the other half, and it is what makes a board switch
  safe.** A posting can also stop being read because *we* moved: a board nobody
  polls never reports a withdrawal, so SIG's 269 rows under the classic iCIMS
  portal would have sat beside its 250 career-site rows forever. The evidence
  is that `(ats, token)` is no longer a pollable target in `ats_resolution`.
  It removed **4 postings** the day it went in and it is not a small rule for
  that reason — it is the precondition for ever moving a board.

- **A rejection has to survive the repost, and that is why it is keyed on a
  fingerprint as well as on the row.** `~anradus pte. ltd.` posts `Quant
  Researcher #77900` to MyCareersFuture every five days — four live cards, four
  different job ids, and a **byte-identical 2,737-character description**.
  Rejecting the 11 August one has to reject the 27 August one, so
  `build_data.hand_rejections` returns both the exact keys and the
  `dedup.fingerprint` of every rejected posting.
- **Only `labels.csv` feeds that gate, and a model sheet gating by *row* was
  tried and taken out.** `model_rejected` read `agent_labels.csv` and
  `board_triage.csv` and removed 1,105 named cards — Singapore 1,499 → 439 —
  and the reader's answer was *"I'm not interested in deleting specific
  records."* That is the right instinct and worth writing down: **a list of
  rejected ids is not a classifier.** It does nothing for the posting that
  arrives tomorrow, it grows without bound, and it makes the board's behaviour
  depend on which cards a labeller happened to be shown. The labels are worth
  keeping as *evidence to mine*; the mined rules are what ships.
- **The de-duplicator's dangerous direction is hiding a real opening, not
  showing an advertisement twice.** `dedup.fingerprint` is
  `(firm, location, description-hash)` and the **location is what makes it
  safe**: Jane Street writes one description per role and posts it in every
  office, so hashing the body alone merges its Hong Kong `Software Engineer`
  with its London one and the London job disappears. With the location in the
  key that pair stays apart, and only the two Hong Kong `Quantitative
  Researcher` postings sharing one text collapse — which is a duplicate from
  the reader's seat whatever the requisition numbers say.
- **The title is the fallback and the description is preferred, because each
  is blunt where the other is sharp.** `(title, firm, location)` alone merges
  genuinely different Apex openings, because Workday writes `2 Locations` as a
  location. A description under `dedup.MIN_BODY` is boilerplate — "apply
  within" is identical across postings with nothing in common — so short
  bodies fall back to the title.
- **299 of 6,086 cards were repeats, 103 of them in Singapore.** The survivor is
  the newest of its cluster, because a recruiter's oldest repost is the one
  most likely to have been filled, and the count rides on the card as `×N`
  rather than the others vanishing without a word.
- **A duplicate the fingerprint cannot see is one job carried by two
  *sources*, and every part of the key differs.** An employer advertises an
  opening on its own board and a national board carries it too, which is what a
  national board is *for*. Barclays' `Quantitative Analytics Associate Off
  Cycle Internship 2027 Singapore` is on Workday and on MyCareersFuture, and
  the firm differs (`firm_key` gives a domain for one and `~name` for the
  other, because the portals publish an employer name and no domain and the ATS
  boards the reverse), the location differs (`Singapore, Marina Bay Financial
  Tower 2` against `Singapore, D01 Marina, Raffles Place, People's Park,
  Cecil`), and the description differs (7,875 characters against none at all).
  No widening of `fingerprint` reaches that, so `dedup.collapse_across_sources`
  is a second pass with its own rule: **same folded title, same hub, and a firm
  test strong enough to carry the whole thing.**
- **The measurement is what designed it, and it splits in two.** 39
  `(title, hub)` groups hold both a portal row and a firm-board row. Thirteen
  hold three or more firms and **every one is a generic title** -- `trader`,
  `quantitative researcher`, `software engineer`, `senior ai engineer` --
  different openings at different employers, where folding would delete real
  jobs. The rest hold two, and there the *names* decide.
  `dedup.same_company` is a **shared leading run** of the name after legal
  suffixes come off, because a company name reads outside in: `Squarepoint
  Services Singapore` ~ `Squarepoint Ops` and `State Street Fund Services
  (Singapore)` ~ `State Street Liquidity` are one firm each, while every false
  pair in the corpus shares no leading word at all -- `Cumberland SG` ~ `DRW`,
  `DRW` ~ `Fragment Works`, `Blockchain Capital` ~ `Chevron Singapore`,
  `Amendo` ~ `AP4`, `Danica Pension` ~ `Danske Bank`. Two shared words always
  count; **one counts only when it is a name rather than a word half of finance
  carries** -- `barclays` and `airwallex` yes, `capital` and `global` no, which
  is the `bamboohr/blackrock` rule in a second place. Result: 20 folds, and
  **zero same-company pairs left unfolded and zero different-company pairs
  folded**.
- **Restricted to cross-source pairs on purpose.** Within one source a repeated
  title is either a repost, which the description rule already folds, or two
  genuine seats -- Jane Street really does advertise two `Software Engineer`
  openings in one office. The justification for the whole pass is that a portal
  republishes somebody else's advertisement.
- **The survivor is the card the board rates highest, and the closing date
  crosses over.** The two copies are tagged separately and *disagree*: the
  Barclays internship is `apply_now` on Workday, which publishes no description
  for it, and `strong` on MyCareersFuture, which publishes 7,875 characters --
  so a rule that picked a side by source would sometimes bury the better card.
  Ties go to the firm's own board, because an aggregator is a discovery net and
  never the primary content source. And MyCareersFuture publishes a deadline on
  every row where an ATS almost never does, so keeping the ATS card would throw
  a real deadline away on a board that orders on deadlines. It is carried, not
  invented.
- **A fingerprint is keyed on the firm, so anything that changes the firm has
  to change on both sides of every comparison.** `hand_rejections` computes the
  fingerprint of a rejected posting separately from the build loop, and the
  moment `board_domains` started remapping domains those two stopped agreeing
  for exactly the 1,668 remapped postings -- a rejection that silently stopped
  sticking to a repost. It takes the same mapping now.
- **`firms[].n` deliberately still counts the folded copies.** It is what the
  firm advertised, and a recruiter posting one job eleven times has advertised
  once — but the tile count is about the board's shape, not the reader's queue.

**`smart` was a sort option that did nothing, and the menu said otherwise.**
It read *"Closing soon, then newest"* and its comparator was byte-identical to
`Newest posted`, because the "closing soon" half is not a spine at all --
`order()` pins an approaching deadline above *every* spine, so that half was
already true of all six options and the menu offered it as though it were a
choice. Removed. A stored `sort: "smart"` falls through to the default, which
is what it was always doing; the `<select>` now reads back what the browser
accepted, because a stored value naming an option that no longer exists leaves
the control blank while the board sorts by the fallback.

**A control that lives in a hover panel cannot survive a re-render, and the
board was re-rendering everything over a change to one card.** `reclassify`
ended in `commit()`, which rebuilds the whole grid — so the `<select>` the
reader had just used left the document while its own `change` event was still
being dispatched, focus fell to `<body>`, `.deep` stopped matching `:hover` and
shut, and the second dropdown could not be reached without hunting the card
down and hovering it again. Measured before the fix: select gone,
`document.activeElement` `BODY`, panel `display: none`, one click after it was
opened. It also re-laid-out every drawn card, which is what *"the ones I just
showed disappeared"* was — the draw depth was restored by count and nothing
else was. **A correction patches its card in place now (`patchCard`) and calls
`render(false)`, which recounts the rail and leaves the grid alone.** A rejected
card stays on the page, dimmed and marked, until the next filter change
rebuilds the grid — which is also what makes the click undoable without
going looking for it under `Rejected`. `save` goes the same way, for the same
reason: it is a button in the same panel.

**`innerHTML =` on a container destroys three things, and remembering one of
them looks like a fix.** The rail was rebuilt wholesale on every commit and the
`<details>` open/closed state was restored from a map — which worked, and
left the focus ring on the clicked option and the rail's own scroll offset to
be lost anyway. Two of the three are invisible in a test that only asserts the
open flags. **The rail is built once and only its option lists are rewritten**;
`<details>` then keeps its own state natively, the clicked option is re-focused
by value (never by selector — a facet value can be `hong kong` or `c++`),
and the facet under the cursor is pinned to its own offset across the whole
render, grid rebuild included, because the rail is `position: sticky` and a
shorter grid clamps the *page* scroll and slides it. Measured: a narrowing
click moved the rail 3,000px → 1,885px and the facet under the cursor off
the screen; it now moves it half a pixel.

**A rail that drops a value when its count reaches zero makes its own height a
function of the filter.** That is what the scroll was jumping over: one tick
and the rail lost a hundred rows. An ordered value stays listed at zero now,
which `data-empty` was already styled to say, and `UNIVERSE` — every value
each facet holds anywhere in the corpus — is what stops that from listing
values no posting anywhere holds.

**The blank option on a reclassify dropdown is *"no correction of mine"*, which
is not the same as `unknown`.** It read `relevance: unknown` on a posting the
tagger had graded `adjacent`, and choosing it looked like asserting that
nothing was known when it actually deletes the override and restores the
tagger's answer. It names that answer now — `relevance: adjacent ·
tagger` — and an override colours its select, so which of the two a card is
showing is readable at a glance.

**The `export corrections` download is gone, and what replaced it is a retry
queue rather than a button.** The CSV existed because `file://` and a bare
`http.server` have no route to answer the POST, so a correction made there
reached nothing. But the correction is already stored and already showing; the
only open question is whether it has been *delivered*. A failed POST is kept in
`board.pending` and retried on the next correction, on the next page load, and
on a click of the one line in the rail that says how many are waiting —
which says nothing at all when the answer is none. **A failure stops the run
rather than retrying in a loop**, or an offline board spends the session
posting into a void.

**`web/serve.py` sends `Cache-Control: no-store`, and the reason is an hour
lost.** `SimpleHTTPRequestHandler` sends `Last-Modified` and no cache header,
which lets a browser cache heuristically — and it does. A rebuilt `data.js`
kept serving the previous build across a reload *and* a new tab, so the board
showed the old card count while the file on disk was current. The entire point
of that server is to look at the build you just made.

**The gates are the whole list**, in `web/build_data.py`'s `GATES`, in the
order they fire: `withdrawn` and `retired_board` (no longer on offer),
then `off_industry` (another profession), `off_location`, `out_of_reach`
(director, VP, manager, project leader, product owner), `phd_required`,
`rejected` (the tagger read it and it is not this line of work),
`non_markets_board`, `non_markets_employer`, `hand_rejected` and
`unread_census_card`. Each is counted separately on every build, because one
total would hide which of them ate a hub. **The first two are deliberately absent from `tagging.GATES`**:
everything there is a fact about the *posting*, which is what lets
`labels._candidates` build a labelling frame from it, and these are facts about
our *reading* — they would tell a labeller nothing and they change without the
posting changing.

**And the build itself now has the floor every source in this project already
had.** `MIN_EXPECTED` guards each registry and each national board because a
scraper returning zero rows with HTTP 200 is more dangerous than one that
crashes — and `web/build_data.py`, which produces the file the reader actually
looks at, had no such check. **It is not hypothetical**: `tagging.TAGGER` was
bumped, the re-tag had not run, every posting fell out as `untagged`, and the
build wrote a **0-posting `data.js`** and returned normally. `publish.py`
checks that the file exists and that the CLI printed no error; it would have
uploaded it, and the route is ordinary — `daily` runs `tag` in a phase where a
failing step is logged and the run continues, then rebuilds and publishes.

`build_data.MIN_CARDS` is 500 against a recorded range of 4,211 to 8,513 cards,
because this is a catastrophe check and not a regression check: a board that
halves is a story, a board that empties is a broken pipeline. Two causes are
named separately because their remedies differ — `untagged > rendered` says
*run `tag`*, anything else says *read the gate counts above*. **The
diagnostics print before the check and the check runs before the file is
opened**, so a refused build is readable and leaves the last good `data.js` in
place. `publish.py --no-build` skips that step by construction, so it measures
the file again on its way out.

- **The board filters in two stages, and only the first one removes anything.**
  Stage one is a *gate*; everything else in the rail *ranks*. This is the one
  place in the pipeline where a classifier removes rather than reorders, and it
  stays consistent with principle 4 by never touching the database.
- **The board's one *promotion* rule had the gate rule backwards, and it cost
  the whole first screen.** A closing date pinned a card above everything else,
  whatever the sort said. A deadline says a posting expires; it says nothing
  about whether this reader wants it — so pinning every dated card promotes on
  the **absence** of a verdict, which is the gate rule read in a mirror.
  Measured: **776 cards pinned, 763 of them Singapore, and 558 with no verdict
  at all** — `Admin Assistant`, `Desktop Engineer - Shift Based`, a Copenhagen
  hotel night porter — above all 224 cards the board rates `apply_now` or
  `strong`. In the board's own firm tiles that is **426 tiles before the first
  unpinned card**. From the reader's seat an empty-looking board and a board
  with 426 tiles of agency listings in front of it are the same thing, and
  *"there are very few jobs on the board"* is what it gets reported as.
- **Requiring a verdict was the fix and it was not enough, because one source
  owns the field.** Restricting the pin to anything the tagger had read left
  **83 tiles, and 116 of the 118 postings were still Singapore** — a gate on
  evidence cannot rebalance a field 98% of which comes from one place. The pin
  takes `SHORTLIST` (`apply_now`, `strong`) and holds **10 tiles**; the board
  then opens on Flow Traders, Two Sigma and Point72. **Two sets, deliberately
  named separately**: `WORTH` is the "Worth reading" preset (which includes
  `plausible`) and `SHORTLIST` is what `build_data.py` counts when it prints
  *"N worth reading"* — the same phrase already meant two things in this
  project, and naming both is how they stop being confused.
- **A rule written for a *rare* signal becomes the sort order when the signal
  stops being rare.** The pin was designed when JobStream published a closing
  date and almost nothing else did. MyCareersFuture publishes one on **every**
  row and is now **1,777 of the board's 1,813 dated cards, 98%** — so a
  tie-break quietly became the ordering. `mycareersfuture.py`'s own docstring
  predicted this in the sentence beginning *"Note the downstream
  consequence"*, and predicting it was not the same as fixing it. **Whenever a
  source lands that publishes a field the board treats as special, re-read what
  that field now outranks** — this is the `_fit` "outside the focus hubs" notch
  lesson (a gate removed makes downstream branches reachable) with the arrow
  pointing the other way.
- **Read the board before believing a report of it.** *"Very few jobs"* was
  measured against the archived `board` branch and the board had **grown**:
  5,211 cards to 8,469, `apply_now` 16 to 44, `strong` 79 to 180. Nothing had
  been lost; what changed was what stood in front of it. **A complaint about
  volume can be a complaint about order** — check the top of the page, not only
  the totals.
- **A gate must fire on evidence, never on the absence of it.** `out_of_reach`
  reads the rank from the title only and skips `unknown`, so a posting that
  never stated a grade stays on the board. Same reason `unknown` survives the
  geography gate. This is what stops a widened lexicon from quietly emptying the
  page.
- **`rejected` is the widest gate and the one to be most careful with.** It
  removes ~80,000 postings, more than the others combined, and it is the only
  one whose evidence is a *judgement* rather than a named fact. It went in on a
  1,000-posting machine-labelled sample that found no false rejection anywhere
  in it, which is real evidence and not proof: a model grading a model shares
  the grader's blind spots. Delete the line if the board ever looks too empty.
- **`non_markets_board` fires on evidence twice over**: a board publishing no
  markets work **and** a title the tagger could not read. A `non_markets` board
  still carried 27 postings rated `relevant` and 254 `adjacent`, and those stay.
  It lives in `build_data.py` rather than `tagging.py` because a board profile
  needs the whole board and `tagging.run` is incremental — a profile taken there
  would be drawn from whichever postings arrived this morning.
- **`board_profile` was wrong in the one direction it exists for, which is what
  being wired to nothing hides.** It scored `keep + undecided` against the
  total, so **`bosch.com` came out `markets` with `keep = 0`**. An undecided is
  worth a quarter of a keep now, and a board with no keeps can never be
  `markets`. **A function nothing calls is a function nothing has tested against
  real data** — check its output over the corpus before wiring it.
- **A share is the wrong statistic for a large board.** `td.com` carries 58
  markets postings and `dbs.com` 42 and both scored under 5%, because those
  boards are thousands of postings of retail branch work. The floor is absolute
  as well as proportional.
- **`senior_6_10` came off `out_of_reach` at the user's instruction**, and what
  it was eating is the argument: 9,914 postings, 947 in Stockholm and
  Copenhagen, including Nordea's `Quantitative Risk Analyst [Assistant/Regular/
  Senior]`. A Nordic bank stamps *Senior* on a three-to-five-year grade. Real
  leadership is untouched.
- **Taking a gate off makes `_fit` branches reachable that were not, and one of
  them ran backwards.** `_fit` returned `stretch` for any `senior_6_10` posting
  *before* it looked at relevance — harmless while those postings were removed,
  and wrong the moment they were not: **290 of the 466 Nordic cards became
  `Senior <IT consultant>` above every genuine markets posting at `unknown`**.
  **Whenever a gate is removed, re-read what downstream ranking it was hiding.**
- **Promoting a geography is the same move and needs the same re-read.**
  Moving the US into `_FOCUS_HUBS` silently switched off `_fit`'s "outside the
  focus hubs" notch for ~30,000 postings, which is a whole country's worth of
  cards moving up a bucket at once. That is the intended effect and it is why
  the occupation vocabulary had to go in at the same time: the notch had been
  doing the work an unwritten word list should have been doing, and removing it
  without the words would have promoted 23,734 American rejects along with the
  876 wanted ones.

## Reading the numbers

### The `unknown` bucket, which is where every diagnosis starts

- **"Too much junk and too little jobs" was one fault, not two, and the bucket
  holding both is `relevance: unknown`.** 199 Nordic cards, 176 of them
  `unknown` — and that bucket held `Inköpare för UBW Inköp support` thirteen
  times *and* `Commodities Sales to FICC Markets | SEB`, `AP3 söker två globala
  aktieförvaltare` and Swedbank's `APO to Group Treasury`. Emptying it from
  below (occupation words) and from above (a markets reading) is one repair;
  doing only one makes the page worse.
- **Ranking candidate phrases by how many unread board postings each would move
  is the measurement that finds what a needle list is missing.** It found two
  families with nothing to do with language: *word order and synonym* (`model
  risk` was a needle and `risk model` was not, so Denmark's `Risk Model
  Developer` read as unlooked-at), and *the desk vocabulary of firms that are
  not trading firms* — custody, fund services, depositary, trade surveillance,
  syndicate, where State Street, Apex, Euronext and SimCorp advertise.
- **The diagnosis has now been wrong twice in opposite directions, and the
  third reading is the one to keep.** First: **6,604 of 6,852 had no body at
  all**, read as *a body would not have helped* — which is the inference the
  number does not support. Second: the comparison it was missing —
  a posting **with** a body stayed `unknown` **1.0%** of the time and one
  **without** **9.3%**, a ninefold difference — read as *a data gap, and
  `bodies.py` is the lever*. On the board at the time, **2,298 of 3,635 unread
  cards (63%) had no body**, their sources SuccessFactors 991, Oracle 430,
  Workday 282, iCIMS 230 — **only Workday had a fetcher** — and 747 of the
  board's 941 placeless cards simply held NULL in that column. That reading was
  right and the backfill worked: today **1,668 of 1,868 unread cards (89%)
  carry a body**. **So the residual is a method gap again**, and the largest
  single cause is below. What remains is the deliberate backfill queue — bare
  `Analyst`, `Associate`, `Data Scientist` — which `judge` refuses to reject on
  a title alone and should keep refusing.
- **1,406 unread postings were held open by one markets word in a body, and
  the histogram of which word says it is the letterhead.** `asset management`
  180, `investment management` 110, `financial institutions` 94, `treasury`
  76 — the paragraph every bank puts at the top of every advertisement.
  What it rescued: `Senior Furniture Consultant, Interior Workspace Design` on
  *investment management*, `Research Associate II Biotechnology` on *equity
  research*, `Senior Audit Associate` on *trading*, `Corporate Card & Travel
  Expense Associate`, `Workplace Associate`, `UK TAX - Sr. Associate`.
  `lexicon.MARKETS_EMPLOYER` is the fix and `judge` step 8 is where it applies
  — see *Two-sided rules* for why step 7 keeps the full list.
- **`unknown` in Singapore is a vocabulary gap and not a missing body, which is
  the opposite of the corpus-wide finding at the time.** 801 of 1,499 Singapore
  cards carried no verdict and the labellers called **693 of them noise** — but
  only **8% have no usable description**, against 38% in Hong Kong and 44% in
  Stockholm. The tagger is reading these bodies and still cannot place them.
- **`no_markets_signal` fires in proportion to how foreign the language is, and
  that is alarming until you read the postings.** It rejects 63% of
  Switzerland, 27% of Copenhagen, 16% of Stockholm, 3% of Hong Kong — ordered
  by how much of `MARKETS` the hub's language is written in. **Measured, it is
  correct**: the Swiss and Danish rejections are retail bank advisers,
  insurance salespeople and nurses, because those national boards carry almost
  no markets jobs — the Swiss banks advertise in English through their own ATS
  boards. Do not "fix" this; it was checked.

### Which number to compare against which

- **The number that diagnoses a hub is its board *share*, and it splits by how
  the hub is fed.** A hub reached only through **firm ATS boards** (Amsterdam
  22%, Hong Kong 21%) is already a filtered population; a hub fed by a
  **national board** (Singapore 1.6%, Stockholm 2.9%, Switzerland 0.6%,
  Copenhagen 0.5%) carries every job in the country, so the share is low by
  design and the interesting number is what the *ranked* cards look like.
  **Compare a hub only against a hub fed the same way** — New York against
  Amsterdam and Hong Kong, never against Stockholm or Singapore.
- **A hub's positive count is what settles whether it is a focus hub.** The
  table that decided the US split: New York 468, Chicago 107, Boston 75, all
  the rest of the US 148 — against Singapore 530, Hong Kong 186, Stockholm 81,
  Amsterdam 38, Switzerland 35, Copenhagen 17. Boston went in on 75 *and* on
  what its postings are (State Street model risk and quant research); the Bay
  Area's 31, Texas's 31 and Miami's 15 stayed out on that second test — wealth
  advisers, tax principals, real-estate capital markets. **Read the positives
  before trusting the count.**
- **Pick the frame before believing a yield, in the mining direction as well as
  the fingerprinting one.** Mining German trade vocabulary looked obviously
  right — `Spülkraft`, `Vorarbeiter Logistik`, `Lastwagenmechaniker` were all
  on the page — and the compound heads dry-run clean at scale: `-installateur`
  3,517 live titles, `-mechaniker` 1,234, `-monteur` 855, `-techniker` 678,
  none touching a positively-rated posting. **Their board impact is 1, 4, 3 and
  1 cards**: the other 3,500 are already rejected on evidence somewhere else,
  so the whole German trade family is worth about ten cards. **`-arbeiter` is
  the one to keep out** — `sachbearbeiter` and `mitarbeiter`, the `-arbetare`
  mistake in a third language.
- **The source's own taxonomy is a drop list and cannot be a keep list, and the
  number is not close.** Over 215,263 categorised live postings the best
  category in the corpus is MyCareersFuture's `Banking and Finance` at **7.7%
  positively rated** (2,690 postings), then `Banking and Finance, Information
  Technology` at 9.1% on 383; everything else is under 5%. Promoting on that
  would add ~2,500 cards to buy ~200 — and it is unnecessary, since `Banking
  and Finance` holds only 95 `unknown` rows out of 2,690. The drop direction,
  `_MCF_OFF_INDUSTRY`, works for the reason this does not: an off-industry
  label is the whole answer and a finance label is not.
- **And the mirror question was measured too: does an unambiguous quant *title*
  deserve to outrank the source's own field?** Of 116,425 postings gated by a
  source's occupation field, exactly **four** carry a `_QUANT_CORE` word in the
  title — two are the Swedish industrial-maintenance firm literally named
  *Quant* (the title trade heads reject them anyway), one is a `Head of Legal
  Counsel` that `out_of_reach` takes, and one is `(Senior) Quantitative Risk
  Analyst, Credit Risk Model Analysis` in Stockholm, filed by JobStream under
  *Säkerhet och bevakning* and deleted on that basis. A real false rejection,
  and it is one, against a rule that is deliberate and pinned by a test.
  **A documented decision is not overturned by n=1**; the measurement is
  recorded so it does not have to be found again.

### What the labels say, and what they cannot

- **`lexicon.judge`'s `keep` verdict is discarded, and it was measured twice
  before being left alone.** `tag_posting` consumes only `reject`; a keep falls
  through to the markets-title branch and then to `unknown` — **267 postings**,
  half of them boilerplate, where `Network Engineer + low latency trading` and
  `Trade Documentation Associate + financial engineering` are a firm's own
  self-description rescuing a title `_SOFTWARE_SPECIALTY` had just rejected.
- **The sharper version settles it, and is also why the employer rule needs
  `not has_body`.** On the 77 quant boards — where a firm-level rescue is
  *most* defensible — 393 postings still read `unknown` and **every one has a
  real body**. Judge keeps 25 of the first 45, and they are `HR Analyst`,
  `Fund Reporting Associate`, `Identity & Privileged Governance Analyst`,
  `Network Security Engineer`, `Storage and Backup Engineer`, `Database
  Support Engineer` — every one rescued by the two words *systematic investing*
  in Point72's description of itself. A body naming markets is the employer
  talking; a body naming markets *activity* is the branch `quant_body`
  already covers.
- **Reading the *board* is a different exercise from reading a *sample*, and it
  is the one that finds noise.** 24 labellers marked all 1,885 cards in
  Singapore, Hong Kong and Stockholm `noise` or `keep` with a fixed vocabulary:
  **1,318 noise to 548 keep — Singapore 73%, Stockholm 74%, Hong Kong 53%.**
  The reason histogram is the useful part: `enterprise_it` 250, `ops_support`
  224, `other_industry` 205, `consulting` 133, `corporate_function` 131,
  `sales_relationship` 115, `generic_software` 114, `wealth_retail` 94. Saved
  as `board_triage.csv`.
- **Mine the needles from the labels; do not take the rules the labellers
  propose.** Asked for generalisable rules they returned confident lists
  including *firm is HKMA* — which would delete the Market Risk and Fixed
  Income seats that hub had just gained — plus bare `consultant`, bare
  `intern`, `credit analyst`, `C++ developer` and `low latency`, the last two
  being postings this project deliberately keeps. **The counts they produced
  are evidence; the rules they wrote are not.** Every needle shipped came from
  a noise title, appeared in no keep title, and was dry-run over all 382,220
  live postings.
- **The dry-run killed nine of the obvious candidates.** Dropped for reaching a
  posting rated `relevant` or `less_relevant`: `mortgage` (`Quantitative
  Strategist, Mortgage-Backed Securities`), `calypso` (`Quantitative Analyst,
  Front Office (Calypso)`), `murex` (nine, including `Murex Credit Risk System
  Analyst`), `business analyst` (`Product Developer / Business Analyst`),
  `system analyst` (`System Analyst - Quantitative Pricing`), `support analyst`
  (`Options Quant Support Analyst`), `application developer` (`Low Latency
  Trading Application Developer`), `business development` (`Trader - Fixed
  Income Business Development`), `banking industry` (`Credit Analyst (Banking
  Industry)`). Three more went after checking survivors against the labels:
  `control analyst` (`Valuation Control Analyst at Swedbank`), `systems
  analyst` (`Systems Analyst - Equities Trading Systems`), `application
  support` (`Senior Trading Application Support Engineer`). **`business
  analyst` was the largest candidate at 52 hits and still had to go** — volume
  is not the test.
- **A model labeller told to prefer `adjacent` when torn will label almost
  anything `adjacent`.** The instruction was *"when genuinely torn between
  `rejected` and `adjacent`, choose `adjacent`"* — sound on its own, and it
  produced `adjacent` for `Slack Administrator`, `IT Support Engineer`,
  `Network Security Engineer`, `AI Marketing Technologist Lead` and `Account
  Management Lead - SMB`, while the same run labelled `Junior Quantitative
  Analyst (Credit & FI)` **rejected**. **Read what a labeller promotes before
  treating its disagreements as bugs** — the needle dry-run rule applied to the
  grader.
- **Model labels must not go in `labels.csv`.** They were written there once
  and it was wrong: `labels.csv` is the *hand* sheet, and a machine sheet
  becomes evidence only after the user has read and confirmed it — "the step
  that turns it from an echo into evidence". `agent_labels.csv` has since had
  that reading and is scored beside the other two.
- **Scoring a third sheet made the exit criterion unreadable, and naming the
  sheet is the fix.** *No false rejection* went from **0 to 78** the moment
  `agent_labels.csv` joined `labels.SHEETS` — not because the tagger moved but
  because the grader is worse. Every disagreement now carries the file it came
  from and the block leads with the tally, which keeps "the hand sheet still
  has zero" visible instead of buried. **The blended number is the one to
  distrust**: three sheets of unequal quality averaged together measure the
  labellers, not the lexicon.
- **Score the sheets by re-tagging live, not by reading `job_tags`, when the
  question is whether a change helped.** `labels.score` reads stored tags,
  which are whatever the last `tag` run wrote — so a comparison across a
  lexicon edit silently compares the new sheet against the old classifier.
  Measured that way in one process against both: the hand sheet is **67.7%
  before and 68.4% after** the `MARKETS_EMPLOYER` split with zero false
  rejections at both ends, `auto_labels.csv` **77.9% → 79.2%** and
  `agent_labels.csv` **45.0%** unmoved. **The 84.9% recorded here previously is
  stale**, as is the 71.7% → 83.6% progression beside it; both were true of a
  lexicon several versions back and the file kept quoting them.
- **The reader's reclassify clicks measure the direction the labelling sheet
  cannot, and are worth re-reading whenever a batch accumulates.** `sample`
  draws from a frame built to find false *rejections* — the failure this
  project calls expensive — and by that measure the tagger is clean: **zero
  false rejections in 152 hand-labelled rows**. The clicks measure the opposite
  failure and found plenty: of 137 postings marked `rejected`, **97 were
  already gated and 40 were still on the board**. Read them as four families,
  because only two are bugs — a body-markets escape (19), an inflection gap
  (2), the reader's own standing "`discretionary_investing` ranks rather than
  rejects" call (9), and a markets word in the *title* of a back-office seat
  (5). **Check which family a row is in before writing a needle for it**; two
  of the four are working as instructed.
- **A labelled disagreement and a labelled non-answer are different facts, and
  one number hid it.** `labels` prints both: `wrong` is what a lexicon fix can
  move, `unanswered` is not, and only the first is evidence of a bug.
- **Seniority is scored by what it is for, not by agreement on a rung.**
  `labels.containment` asks the two questions with consequences — how much
  labelled leadership the board withholds, and how many wanted postings the
  rank gate removed — and reports them separately, because netting them off
  would hide both.
- **A fixture drawn from the top of the shortlist can only find false
  positives**, while the exit criterion is *no false rejection*. **But
  stratifying over the whole corpus is the opposite mistake**: 30%
  `out_of_scope` is housekeepers and van drivers, and the notes came back
  *"nothing to do with finance"*. **A false rejection can only hide among
  postings that could plausibly be in scope** — `labels._candidates` draws from
  a frame of ~2,000.

### Rules the measurements defended

- **The two the model sheet flagged loudest are both correct.** `desk support`
  removes **9,072** live postings and a hand-read of thirty in focus hubs is
  `CLEANING OPERATIONS MANAGER`, `EV Battery Operations Supervisor`, `Rental
  Operations Agent`, `HR Operations Lead` — bare `operations` and `compliance`
  in `_DESK_ADJACENT` are doing the work, and the *verdict* is right even where
  "desk support" is the wrong *reason*. `crypto_web3` removes **686**, of which
  637 never say crypto in the title — Kraken (`payward.com`, 40), Galaxy,
  BitGo, Blockchain Capital, Castle Island. **Softening either would cost
  hundreds of correct rejections to rescue about twenty postings.**
- **A count threshold does not separate a crypto firm from crypto
  boilerplate.** The obvious fix for the ~20 mainstream managers caught by
  `crypto_web3` (State Street, T. Rowe Price, LSEG, ProFunds) is to demand two
  mentions; measured, the distributions are identical — **445 of 617 correct
  crypto-firm rejections also mention it exactly once**, against 16 of 20 false
  ones. The discriminator is the *board*, not the posting —
  `lexicon.board_profile` again, which is also the answer for a small quant
  shop whose `Machine learning researcher` reads `unknown`.
- **The body-level markets anchor is 96% precise and does not need fixing.**
  102 postings are kept by a single body quant phrase plus a body markets word;
  **`trading` alone does 68 of them and they are XTX and Squarepoint
  engineers**, correctly kept. The bad ones are three: a neuroscience
  `Principal Research Scientist` on *asset management*, an insurance
  `Catastrophe Risk Modeler` on *risk analytics*, and the `Computational
  Chemist` on **`reference data`** — the posting `_markets`'s own docstring
  names as the failure it was written to stop. One each; `reference data` stays
  in `MARKETS` because it is a real markets title on the other 38.
- **An agency signal read off the employer's *name* was measured and refused.**
  Names containing `recruit`, `staffing`, `personnel`, `search` and the rest
  are 86% noise — and the 14% is `Quantitative Researcher` at Qube Research &
  Technologies, a `C++ Quantitative Developer – Pricing` and an `FX Dealer`.
  (`search` matching inside `research` is its own warning.) The employer
  *profile* gets the same firms without the collateral, because it reads what
  the board published rather than what the firm is called.
- **Opening the board on `fit: Worth reading` looks like the answer and is
  not.** It would take Singapore from 1,499 cards to 371 — close to the 403 the
  labellers kept, which is what makes it tempting — but the *sets* disagree: it
  shows 324 cards of which 146 are noise and **hides 225 the labellers would
  have kept, 44% recall**. `fit: unknown` is excluded from `WORTH` and the
  labellers kept 100 of that bucket, so the preset gates on the absence of a
  verdict, which is the one thing the board's gates never do.

### What a good change looks like from outside

- **A list of rejected ids is not a classifier, and the difference is the whole
  point of labelling.** Gating on the model sheets by *row* removed 1,105 named
  cards and took Singapore from 1,499 to 439 — taken back out at the reader's
  word. It does nothing for the posting that arrives tomorrow, grows without
  bound, and makes the board depend on which cards a labeller was shown. **The
  labels are evidence to mine; the mined rules are what ships.**
- **Mining the same labels twice pays much less the second time.** The first
  pass took the high-frequency phrases: three categories, 51 needles. A second
  pass at a lower floor over the same 2,335 labels found 30 more worth **62
  cards**. Title-phrase mining saturates; when it does, the next lever is a
  different *unit*, not a longer list.
- **That unit was the employer, and it is where a national board hides its
  noise.** `board_profile` is keyed on `(ats, token)`, which is right for a
  firm's own board and blind for a portal: ~95,000 MyCareersFuture postings
  share one token, so the profile describes the portal rather than anyone
  hiring. Profiled on `jobs.employer` instead, **3,234 employers come out
  `non_markets`** — `RECRUIT EXPRESS`, `THE SUPREME HR ADVISORY`, `ANRADUS`.
  `non_markets_employer` fires on the same double evidence as the board
  version: `MIN_BOARD` postings and none reading as markets, **and** a posting
  the tagger could not place. `RECRUIT EXPRESS` has nine rated positively and
  all nine survive.
- **The number to read after a tightening is the one that should *not* have
  moved.** Three shapes of the same result, and the shortlist is the constant
  in all three: Singapore 1,499 → 1,014 cards with the shortlist unmoved at
  216 and the whole board 6,086 → 5,521; stages 35–36 together took 8,513
  cards → 6,666 and 1,515 firms → 1,137 with "worth reading" unchanged at 224;
  the `MARKETS_EMPLOYER` split took 4,565 → 4,365, unread cards 41% → 38%, and
  the shortlist 201 → 202. **A shortlist that shrinks with
  the junk means the needle was too wide, and no aggregate count says so.**
- **When it does move, every card has to be attributable.** A quarter of the
  board came off in one stage — 6,120 → 4,459 cards, `unknown` 3,635 → 1,843,
  placeless cards 941 → 251 — and of the 216 cards that were `apply_now` or
  `strong`, **194 stayed and every one of the 22 that left has a named rule**:
  eight PhD-required seats gated, six `Experienced Trader` postings and two
  recruiters demoted, two caught by the department fix, one gated once its
  location arrived. *No unexplained loss* is the claim to make.
- **Twelve model labellers over 471 postings found that the classifier is
  right, which is a result and not a failure.** Seniority containment was
  **14/14 leadership kept off the board, 0 openings lost to the rank gate**; of
  469 model labels only **nine** disagreed in the expensive direction, and
  reading them, seven are the model being wrong or the tagger being defensibly
  right.

## Tagger versioning

- **Changing the lexicon without bumping `TAGGER` leaves stale tags that look
  current.** `tag` only visits postings with no row at the *current* version, so
  after an unbumped edit it reports `tagged 0 postings` and every summary keeps
  serving the old answers.
- **That had happened, and nothing detected it.** 53 postings in this database
  carried a verdict at version 58 that version 58's own code no longer
  produced. `tagging.fingerprint` hashes every needle list both modules hold,
  `tag` stamps it into `tagger_state` on every run — including a run with
  nothing to do, which is the *normal* shape of this failure — and
  `alerts.check` reports a `lexicon` alert when the stored hash and the current
  one part company. It hashes the needles rather than the source, so a comment
  or a refactor is free.
- **A fingerprint over module state has to be ordered, and the first version
  was not.** `_STOPWORD_LANGUAGES` is built by walking `frozenset`s, and set
  order follows string hashing, which Python randomises per process — so the
  hash differed on every run and the alert fired on a database that had *just*
  been re-tagged. **An alert that always fires is worse than no alert**;
  `tests/test_alerts` pins it against a second interpreter rather than a second
  call.
- **`job_tags` does not keep retired lexicon versions.** The primary key omits
  `tagger`, so `INSERT OR REPLACE` overwrites the previous version's row
  whenever a posting keeps the same value — only rows whose value *changed*
  survive, which is the opposite of a diff. Treat "compare two taggers" as
  unavailable, and use `prune` to drop superseded versions.
- **Tag counts must still pin the lexicon version.** An unpinned `COUNT(*)` sums
  whatever survives of every version — the hub table read 49,808 postings in
  `unknown` after `unknown` had already been split out.
- **A body that arrives after the tag is a body the tagger never reads**, and it
  put 585 Swedish postings on the board. `tagging.postings` selects postings
  with no row at the current version, so fetching a description later changes
  nothing until the next bump — and `daily` ran `bodies` *before* `tag`, while
  `bodies.targets` reads `job_tags` to find postings the tagger could not place,
  so a fresh arrival was not in that queue at all. Two changes together:
  `bodies._write` deletes the current version's tags for every posting it fills,
  and `daily` tags **twice**. It is worth settling because for a national board
  a body is nearly decisive: **4% of postings with a body stay `unknown` against
  28% without one.**

# What is actually slow, measured rather than assumed

**Matching is half of a re-tag, and the fix is an index rather than a shorter
list.** A needle can only match if its words are tokens of the text, so
`lexicon._index` files each phrase under one of them and only the intersection
of that key set with the text's tokens is ever looked at. With one translate
pass in `fold`, each field folded once and composed rather than re-folded, and
an inverted stopword index in `posting_language`, a 17,417-posting sample went
**52.7s → 13.8s (3.8x)** with byte-identical output.

**Then a further 1.6x, and the three changes are worth separating because only
one of them is an algorithm.**

- **Take the smaller side.** `set & set` iterates whichever side is shorter, in
  C, and which side that is genuinely varies: a folded title is six tokens
  against a list of hundreds, a folded body is thousands of tokens against a
  list of thirty. Measured over 5,000 real postings: 404,763 matches, 74.6% of
  them against a text holding fewer tokens than the list holds phrases, and
  13.7M phrase tests against 2.9M for taking the smaller side each time. It
  also *removed* a branch — one loop replaced two.
- **File a phrase under its rarest word, not its first.** Any word of the
  phrase is correct — it cannot match unless all of them are present, and the
  padded substring test settles it either way — so the only question is which
  key is most selective. `_SPOKEN_REQUIRED` is 1,386 phrases built from 35
  frames crossed with 12 languages, where *fluent* keys hundreds and
  *portuguese* keys 35.
- **Match a ladder as one index.** `tagging` holds eleven dicts of needle
  lists, the widest fifteen rungs deep, and asking them rung by rung walked the
  same tokens once per rung. Flattened, a rung's position in the
  concatenation *is* its priority, so the lowest matching position is the first
  rung that hits and no ordering has to be reconstructed. 677,000 list walks
  become 180,000.

Two smaller ones beside them: `fold` skips its markup pass when there is no
`<` and its transliteration when the text `isascii()` (both exact, and four
fifths of the corpus takes them), and `lexicon.normalize` is `lru_cache`d
because `judge` and every `tagging._markets` branch normalize the same body.
Measured with both variants alternating **in one process**, so frequency
scaling hits both: **8.44s → 5.17s of CPU per 5,000 postings, 1.6x, output
identical tag for tag**. A full re-tag of 509,561 postings is 10m22s wall.

**Benchmark two variants in the same process or not at all.** The first
measurements of this ran them in separate interpreters and came back anywhere
between 0.9x and 3.0x, because the machine's clock scaling moves more than the
change does. Alternating them inside one process, and alternating the *order*
between rounds so neither always runs on the colder heap, is what made the
number stable.

**The national boards were run one after another against six different
hosts.** `runs` records every Layer 4 poll's start, so consecutive starts are
step durations, and they said: Denmark 33.6 min, Sweden 4.3, Switzerland 0.8,
Singapore ~70, Hong Kong ~50 -- about **160 minutes of sum where the longest
is 70**. `daily` gathers them concurrently now.

**The politeness question is the only one that matters here, and it is
arithmetic rather than judgement.** `http._throttle` books per *host* under a
lock, so this changes how many hosts are in flight and nothing about the rate
any one sees. Measured three ways: 4 slots × 3 hosts go 9.0s → 3.0s
synthetically and 3.53s → 1.22s live, while **12 concurrent callers to a
single host still take 11 seconds** -- identical to one caller making twelve
requests. That last measurement is the one pinned as a test.

**Threads, never subprocesses.** Separate processes each keep their own
`http._last_hit`, so two steps sharing a host -- `jobs` and `pages` both reach
firm domains -- would each grant themselves the full rate and silently double
it.

**And the report has to survive concurrency.** `redirect_stdout` swaps a
process-global, so six steps would each capture the other five;
`cli._ThreadStream` routes by thread instead. That works *only because every
`print` in this project lives in `cli.py`* -- a debug line added inside
`extract` or `pages` would run on a worker thread, escape the capture and
shred the report, visibly only under concurrency. There is a test that walks
the package for stray prints, and it was verified by planting one.

**More workers is the obvious next idea and it is measured wrong.** The
`bodies` queue is 4,015 rows over **178 hosts** against 12 workers, which
looks worker-bound -- and 1,963 of those rows are one host at four seconds, so
the pass is bounded at 2.2 hours by the throttle while eleven workers sit
idle. The tell is **one established TCP connection and flat CPU**. Check what
the pass is actually waiting on before adding threads to it.

**And the sentence above names the whole of `daily --full`, which was the next
thing measured.** A `--full` run was watched live: **3h50m of wall clock for 16
minutes of CPU**, one established connection, and that connection was Hong
Kong. Every one of the six Layer 4 sources had already recorded `ok=1` -- the
gather phase was finished inside 70 minutes and the run was still in `bodies`
three hours later. **95% of a full run is waiting, and about 75% of the waiting
is one host.** Before reaching for threads anywhere in this project, get the
per-host request count: it is the only number that moves a pass bounded by
`http._throttle`, and no arrangement of workers changes it.

**Hong Kong's bodies cost two requests each and now cost about one.** The card
is addressed by a `?order=` token that expires, so `bodies.iesjobs_body` mints
one per posting with a POST search and then fetches the card -- 8 seconds a
posting at this host's four, single file. **The portal's own list prints a
freshly minted card link beside every row it renders, twenty to a page**, which
`iesjobs._job` was already capturing and deliberately throwing away (correctly:
`jobs.url` must not hold a token that dies in hours). `iesjobs.card_links`
returns it to a caller that spends it inside the minute, and
`bodies._iesjobs_pass` walks the job-type slices minting in bulk. Measured on a
live queue of 864 postings: **1,085 requests against 1,728, 72 minutes against
115.**

- **The rate is untouched and that was the reader's explicit call.** Four
  seconds a request stands, because it is what this project offers in exchange
  for reading a board whose `robots.txt` says no. The lever was the request
  *count*, which is the same distinction the 429 note draws one file over:
  slowing down is compliance, and asking for less is engineering.
- **Batching the search was tried first and the portal refuses it.** A
  space-separated list of order numbers matches nothing, a comma-separated one
  matches nothing, and so does a prefix -- all three measured. The token itself
  decodes to 32 bytes of ciphertext, so it cannot be minted locally either.
- **Harvesting is not always cheaper, and a slice that does not pay must be
  abandoned.** For a slice holding W wanted postings the search costs 2W and
  paging costs P + W, so paging wins exactly when **P < W** -- which turns on
  how thinly the wanted postings are spread and is not knowable in advance.
  `Others` wants 331 and reaches them in 80 pages (411 against 662);
  `Management / Administration` wants 23 spread over 41 pages and would cost 64
  against 46. So the loop keeps paging only while the pages spent stay below
  the postings found. **An optimisation with no bail-out is a pessimisation on
  the inputs it was not measured against.**
- **The fallback is the old path in full, so trying costs nothing that matters.**
  A posting no page yields -- withdrawn since the walk, a renamed facet, a
  failed page -- goes to the search unchanged.
- **The expiry check and the identity check are one line, and it fails closed.**
  A stale token answers **HTTP 200** with the vacancy-search page and no card;
  a search that matched the wrong posting answers with somebody else's card.
  Both are the same absent-or-wrong `data-ordno`, both yield nothing, and the
  posting stays in the queue. That is what makes a harvested token safe to
  attempt rather than something to reason about.
- **The split is counted and printed**, because falling back is otherwise
  silent: if the list markup moves, every slice is abandoned on page one, every
  posting takes the slow route, and the only symptom is that Hong Kong is slow
  again. `cli._bodies` prints `harvested` against `searched`.

**`bodies` now runs two strategies at once, and the writer stays in one
thread.** Hong Kong is one host, so `_spread` can do nothing with it and twelve
workers are eleven workers waiting; it is walked sequentially while every other
source goes through the pool, the two feeding a queue that the calling thread
drains. `db.connect` hands out a connection bound to the thread that made it,
which is why the writing did not move. **An exception in a producer is carried
across the thread boundary and re-raised** rather than swallowed -- it no
longer propagates out of `pool.map` on its own, and a fetcher meeting a shape
it does not expect must still end the pass loudly or a schema change reads as a
zero-filled run.

**Classification is the one genuinely CPU-bound stage and it was single
threaded.** 2.99 ms a posting, so a full 509,561-posting re-tag is ~25 minutes
of one core with seven idle. `tagging.run` maps it over a **process** pool --
the only pool in this project that is not threads, because unlike `bodies`,
`jobs`, `pages` and `_gather` it never waits on a socket and so never releases
the GIL. Measured over 40,000 real postings: **36.8s -> 9.4s, 3.9x, with
byte-identical output.**

- **The output being identical is the assertion, not the row count.** A pool
  that classified *differently* writes the same number of rows into the same
  columns and every summary stays plausible; only the verdicts move.
  `tests/test_tagging.ParallelTaggingAgreesTest` pins the tuples.
- **`_QUANT_BOARDS` is module state and a spawned worker inherits none of it.**
  Left unset it does not fail -- it switches both employer branches of
  `tag_posting` off for every posting the pool touches, which is a different
  classifier reporting success. It is measured once in the parent and shipped
  through the pool's `initializer`.
- **There is a floor at 20,000 postings and it is not decoration.** Windows
  spawns rather than forks, so each worker re-imports `tagging` and `lexicon`
  at about a second apiece. A `daily` run tagging a few thousand new postings
  would spend more starting the pool than doing the work.

**`postings()` needed an index nobody had noticed was missing.** It asks "is
this posting tagged at the current version" as a correlated `NOT EXISTS` on
`(ats, token, job_id, tagger)`. The primary key covers the first three and
stops, so SQLite walked every row for that posting to test `tagger`.
`job_tags_by_tagger` makes it a seek: **7.2s to 1.1s**. Whenever a query filters
on a column that is in the table and not in the index, check the plan.

**`jobs` was the only network command running serially, and it is Layer 3.**
Measured on a 36-board sample across 16 ATSes: **32.3s serial, 4.5s parallel —
7.2x**. Politeness is unchanged and that is what makes it safe: `http._throttle`
books its interval **per host** under a lock. Note the shape of the
measurement, because the first attempt said *1.0x*: a sample of 24 boards was
pagination against a handful of hosts, where the per-host throttle is the floor.
**Spread the sample across hosts, or a concurrency change measures nothing.**

**And the same sentence is a bug in the *queue*, not only in the benchmark.**
`bodies` ran twelve threads over a queue ordered `first_seen DESC` — which
arrives clustered by tenant, because a board polled this morning contributes its
whole batch at once. With `MIN_INTERVAL_S` booked per host, twelve workers then
queue behind one tenant's one-second slot, and the run costs the *sum* of those
stretches rather than the longest: **335 consecutive `usbank` rows are 335
seconds however many threads are watching.** Observed live before the fix — 270
postings resolved in half an hour. `bodies._spread` round-robins the queue over
its hosts, keeping each host's own order, which takes the longest same-host run
**335 → 102** and the pass from roughly 90 minutes to roughly 12 for 5,372 rows.

**Selection and fetch order are separate decisions**, and only the second one
changed: `targets` still picks the newest rows, `_spread` only decides which to
fetch first among them. **12 minutes is the floor** — the largest tenant has 723
rows and the throttle allows one a second, so a pass is never shorter than its
biggest board. That is the number to check before suspecting `_spread`.

**A fixture that caches a column the database owns is the expensive kind of
big.** The three labelling sheets were 4.3 MB and **3.6 MB of it was
`jobs.description`, copied verbatim** — in git, rewritten whole on every
redraw. The instinct is to reach for a binary format; measured, every one of
them loses to not storing the column: **SQLite as a table is 4.9 MB — larger**,
CSV+gzip 1.4 MB, CSV+xz 0.9 MB, against **604 KB** for dropping it, and Parquet
would sit with the compressors while costing the stdlib-only rule, the git
diff, the Excel edit and `serve.py`'s write path. **Ask what a file is
duplicating before asking what format it is in.**

**Writes are ~2 minutes per full re-tag and WAL plus `synchronous=NORMAL` is
worth only 1.1x on them** — it is in `db.connect` for the concurrency, not the
speed. `job_tags` grows by ~2.4M rows per version bump; `prune` is a separate
command because it deletes rows, and that is the user's call even in a derived
table.

Read `MIN(tagged_at)` and `MAX(tagged_at)` for the current tagger to time a
re-tag. Those are exact, and trustworthy only for the *newest* version, because
the primary key omits `tagger`.

# Role scope

The user has under a year of experience and has **already graduated**, so
student-only postings requiring a future graduation date are noise.
Python/research-oriented, explicitly not a C++/Rust specialist.

**Include:** quant researcher/analyst/trader/developer, systematic and
algorithmic trading, alpha and signal research, portfolio construction,
execution research, strategist, market and credit risk quant, model validation,
and DS/ML *at financial-markets firms*.

**Exclude:** actuarial and insurance pricing; fintech unconnected to markets;
crypto, DeFi and web3; roles that are primarily heavy systems engineering
(down-rank rather than hard-drop — many quant-dev roles list C++ as secondary
and still fit); and roles too senior (Head of / MD / PM with own book / 10+
years).

**Never filter on job title alone.** Goldman says "Strat", Jane Street says
"Trader", Swedish postings say "kvantitativ analytiker". Classify on the full
description, multilingually.
