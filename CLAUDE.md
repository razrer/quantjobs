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
| 4 | `jobstream` | Sweden's national delta feed (`--since` replays a window) |
| 4 | `switzerland` | job-room.ch |
| 4 | `sweden` | Jobbsafari, all of it |
| 4 | `denmark` | Jobindex, every category (`--since` tops up with one query) |
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
`bodies.targets` reads the current tagger to know what to fetch. **It is
deliberately manual**: the search is
the expensive half, free here and billable anywhere else, so nothing schedules
it — what is deployed is the *output*, not the scraper. A failing step does not
stop the run, because a board redesigned underneath us should cost its own
postings and not the other eight sources', nor the re-tag, nor the rebuild —
which would otherwise leave yesterday's file up with no sign of why. `alerts`
says which one went quiet and the exit code says whether any did.

`--full` sweeps every Jobindex category and MyCareersFuture as well, and widens
the page and body queues. Without it, Denmark tops up with one query from where
the data already reaches: `_denmark_since` reads the newest Danish row we hold
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

**The board's reclassify clicks needed a way off a static site, and the answer
is one Function, not a database.** `functions/correction_writer` (`infra.json`'s
`correction-writer`, at `quantjobs-api.spawned.app`) appends into one JSON blob
in the same bucket (`_corrections/corrections.json`); `corrections` reads it
back and calls the same `labels.upsert` that `serve.py` calls. One blob rather
than one object per correction, and no DynamoDB table: this is one person
clicking a handful of corrections a month, so a read-modify-write race is not a
real risk, and it keeps the added cost to one component (~$3.89/mo for a
Function, billed per second regardless of invocation count).

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
- `parsing.py` — minimal HTML table and `.xlsx` readers, standard library only
- `db.py` — SQLite schema and upserts
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

**No third-party dependencies.** Standard library only. Keep it that way.

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

- **Workday's real trap is `total`, not `limit`.** It reports the true `total`
  on the first page and **`total: 0` on every page after it**, so stopping when
  `len(jobs) >= total` truncates every board at 20 postings with no error at
  all. Cap the page at 20, page by `offset`, stop only on a short page.
  `tests/test_workday.py` pins all three.
- **Workday needs `tenant|wdN|site`.** A tenant alone builds a URL that 404s on
  every poll while the board looks resolved.
- **A URL built unconditionally from a missing field becomes a link to the
  vendor's landing page, which is worse than no link.** `extract.workday` did
  `url=f"{origin}/en-US/{site}{path}"` with `path = externalPath or ""`, so an
  entry Workday published without a path produced the board's own front door.
  **42 Workday boards held exactly one each** — empty `job_id`, empty `title`,
  and a card that opens a recruiting site — and the reader found two of them,
  at Nasdaq and Sun Life. The two halves are handled separately on purpose: a
  posting with a **title and no path** is kept with `url=None`, because it is a
  posting however badly it was published, while an entry with **neither** is not
  a posting at all — nothing about it can ever be read and there is no id to
  re-fetch it by. `web/build_data.py` counts `untitled` separately as the guard
  for the next source that does this.
- **Every live SmartRecruiters row had a NULL URL — 1,507 of them, across all 12
  boards — and the code carried a comment describing the cause.** `ref` is a
  dict of links on some boards and a bare API self-link string on others; where
  it is a string, `applyUrl` is `null` too, so `ref.get("jobAd") or applyUrl`
  resolved to nothing and the board rendered cards nobody could open. The public
  ad is `jobs.smartrecruiters.com/{company}/{id}`, verified against the live
  board, and the title slug some boards append is optional. **A comment noting
  that a field comes in two shapes is not the same as handling the second one.**
- **Workday has a second host and it inverts the URL.** On `myworkdayjobs.com`
  the tenant is the subdomain; on `myworkdaysite.com` the subdomain is a bare
  `wdN` and the tenant moves into the path. The two patterns capture the same
  three parts in *different orders*, so they capture by name — joining by
  position built `wd3|brevanhoward|BH_ExternalCareers`, which is well-formed and
  addresses nothing.
- **A page-count guard is a silent cap on the boards that matter most.** The
  Workday reader stopped after 40 pages and LSEG and State Street both came back
  at exactly **800** postings; State Street really has 1,295. A round number in
  the output is what a cap looks like from outside. The bound is 1,000 pages
  now, and paging stops on a short page *or* one that repeats the previous (a
  tenant ignoring `offset` serves page one forever). **Whenever a per-board
  count is suspiciously round, suspect our guard before their register.**
- **Fingerprinting an ATS and reading it are separate capabilities, and the gap
  is silent.** `ats.py` once recognised 22 systems while `extract.py` read 11,
  so 88 boards sat tier A with a token, counted as resolved everywhere, polling
  nothing. `tests/test_oracle_hcm.EveryFingerprintHasAReaderTest` is the guard:
  every name in `ATS_PATTERNS` must be in `extract.EXTRACTORS` or listed in that
  test's `INVESTIGATED` map with the reason there is no reader.
- **ATS board tokens are easy to extract wrongly, and the wrong answer looks
  right.** `boards-api.greenhouse.io/v1/boards/{token}` puts an API version
  before the board, so matching the host alone yields `v1` for every Greenhouse
  user; `www.teamtailor.com` fits `{board}.teamtailor.com` and yields `www`.
  Both are filtered against a list of infrastructure hostnames. **Always read
  the first handful of tokens before trusting a batch.**
- **The infrastructure-token list is an *all-pieces* rule, and that is only half
  right.** It must be, or `jane-street` and `da-vinci` get thrown away. But
  `jobs.jobvite.com/__assets__` was recorded as a board against three unrelated
  firms at once, and `vs-errors.eightfold.ai` passed because `vs` means nothing
  while `errors` is the vendor's host. Split on `_` as well as `-`, and check
  the unambiguous words (`assets`, `cdn`, `errors`, `sentry`, `staging`) with
  *any* rather than *all*.
- **`tbe.taleo.net` is Taleo Business Edition, a host every small tenant
  shares.** `varde.com` and `hanoverco.com` both resolved to the board `tbe` — a
  token several unrelated domains agree on is the vendor's infrastructure, which
  is the signal `_NOT_A_TOKEN` exists for.
- **An ATS board often lives on the firm's own hostname, and every host pattern
  misses it.** `careers.lynxhedge.se` is Lynx and `jobs.swedbank.com` is
  Swedbank — Teamtailor boards that never spell `{board}.teamtailor.com`
  anywhere. The vendor's asset CDN is still in the markup and the custom host is
  the token. **Verify it**: the CDN proves the firm *uses* Teamtailor, not where
  its board lives, and the first three domains matched this way all 404'd on
  `/jobs.rss`. `careers.sig.com` is the same shape via a cookie-banner script
  path, worth 237 postings.
- **A board URL escaped inside a JSON island matches no host pattern.** Julius
  Baer ships its navigation as JSON inside an HTML attribute, so its Workday
  board arrives as `&quot;https:\/\/juliusbaer.wd3.myworkdayjobs.com\/...`.
  `fingerprint` unescapes before matching. On a random tier-B sample that
  rescues 1 page in 400 and among tier-B *roster* firms it rescued one in ten —
  **pick the frame before believing a yield.**
- **Tier A with a NULL token is a board nobody can poll, and a tier-B sweep
  never touches it.** 98 rows sat in that state. When re-probing for a
  fingerprinting fix, clear tier A with no token too.
- **The careers walk must try every candidate and go two hops.** The loop used
  to `return` tier B on the first readable careers page, so candidates two and
  three were fetched by nobody — and Swedbank's board is a link *off* its
  careers page. Six fetches per domain is the ceiling.
- **A careers page can link to a board that is not the firm's.**
  `palmersquare.com` linked to `jobs.lever.co/heyrowan` — syndicated content
  with a Google `srsltid` still attached — and the feed delivered 90
  jewellery-retail postings under a credit manager's domain. Well-formed token,
  real ATS, live feed, wrong company. **Read the postings, not just the token.**
- **A regex over fetched markup is a denial-of-service waiting to happen, and it
  fails as a *stall*, not an error.** Two `ats` runs sat at 100% CPU for two and
  a half hours, wrote nothing, and looked exactly like slow network. Two causes,
  both quadratic: `[^"']*(?:career|jobs|…)[^"']*` over an href that never
  closes, and `([a-z0-9-]+)\.host\.com` over an inline base64 data URI. Extract
  hrefs with a bounded pattern and match words in Python; bound every host label
  to 63 characters and prefix it with `(?<![a-z0-9-])`. Cap fetched markup too —
  23 patterns over an unbounded body blocks every other thread through the GIL.
- **A trailing slash was a silent 50-posting cap.** Jobvite pages at
  `/{token}/search/?p=1`; without the slash it serves the first page while
  looking like it paged. Sikich's own pagination text says `1-50 of 73`, which
  is the check: **the board states its own size, so compare against it.**
- **iCIMS has no feed.** The vendor's `format=rss` 302s to a staff login, so the
  portal HTML is the only public surface. Job links are `/jobs/{id}/{slug}/job`,
  `pr` pages 50 at a time, and the list page carries **no anchor text** — the
  slug is the title, which loses casing and `c++`. Stop paging when a page adds
  no *new* id: a portal ignoring `pr` serves page one forever and never returns
  an empty page.
- **Oracle Fusion's board token is `podhost|siteNumber`, and neither half works
  alone.** `CX_1001` is Oracle's default site number that most tenants keep, so
  a token of the site alone collides across every firm on the platform.
  `TotalJobsCount` is honest on every page, so Oracle has no `total: 0` trap —
  it is still used as a *check* against what arrived rather than as the stop
  condition. UKG's token is `code|boardGuid`, the same both-halves shape.
- **A board page serving a dead end does not mean there is no feed.** Varbi's
  `/{lang}/what:list/` answers *404 Unallowed call* for every language, and
  Homerun's board is script-rendered and links out to the firm's own host. Both
  publish a feed — `/what:rssfeed/` and `feed.homerun.co/{token}` — and both
  carry the description the board page does not. **Read the page's own link
  shapes before concluding a vendor has no feed**; guessing paths found neither.
- **Taleo needs a per-board portal id and does not publish one.** Without the
  right `portal=` the search endpoint returns `careerSectionUnAvailable: true`,
  and the section page is a 1,534-byte redirect stub. Eightfold's
  `/api/apply/v2/jobs` returns the page *config* rather than postings, and Join
  422s on every `page`/`pageSize` tried. **SuccessFactors puts the board in the
  query string** (`?company=pfapensionP`), and reading it is a dead end
  regardless: the career site answers 206 KB of shell with no job id, with or
  without a session, and the vendor's RSS path 404s. PFA and Swiss Re are here.
- **Paylocity, Rippling and Phenom render their lists client-side** — the 41
  "job ids" a naive count finds in Paylocity's HTML are analytics and CSS.
  Recorded as investigated.
- **Greenhouse's own copy-paste snippet did not match the Greenhouse
  pattern, and 29 boards sat unread because of it.** The rule allowed
  `boards.greenhouse.io/embed/job_board?for={board}`; what a firm actually
  pastes onto its careers page is **`/embed/job_board/js?for={board}`**, with a
  path segment before the query string. The general host rule underneath then
  matched and captured `embed`, which `_NOT_A_TOKEN` correctly refused — so the
  domain landed at **tier A with a NULL token**, the one state `discover.targets`
  calls out as a board nobody can poll and no sweep revisits. Maven Securities
  (39 postings across Amsterdam, Chicago and Hong Kong), GSA Capital, Geneva
  Trading, Acadian and Vatic were all in it. **A NULL token on a recognised ATS
  is not a small gap; it is a firm that reads as resolved everywhere and yields
  nothing forever.**
- **`job_app?for=` names the board too, and refusing it looked like the careful
  choice.** That embed is one posting's application form rather than a list, so
  the first version of the fix skipped it — and `for=` is the *board* in every
  Greenhouse embed whatever is being embedded. GSA Capital publishes its whole
  careers page as a list of `job_app` forms and names the board nowhere else, so
  it stayed tokenless through the fix meant to clear exactly that.
- **And GSA then added no postings, because its board was already polled under
  another of its own domains** -- `gsa-coral.com`, a sibling of the same group,
  resolving to the same Greenhouse token. `jobs`'s upsert keys on
  `(ats, token, job_id)` and does not move `domain`, so the rows stayed where
  they first landed. **A tier-A row with a NULL token can be a duplicate of a
  board already reached; check `SELECT domain FROM jobs WHERE token = ?` before
  counting the fix as postings.**
- **Avature serves each customer from the customer's own hostname**, so
  `careers.twosigma.com` matches no `{board}.vendor.com` pattern and the board
  *is* the host — the `careers.lynxhedge.se` shape, and the reason
  `_VENDOR_ASSETS` exists. The giveaway is the vendor's CDN,
  `templates-static-assets.avacdn.net`. **Its list page is named by the tenant
  rather than by the vendor**: Two Sigma calls it `/careers/OpenRoles` and
  Avature's default is `/careers/SearchJobs`, so both the reader and the
  fingerprint try a list of names — a wrong one answers 404, which cannot be
  mistaken for an empty board. `extract.AVATURE_LIST_PATHS` is the single
  definition both read, because two copies of it are two sides of a comparison
  free to drift.
- **`_VENDOR_ASSETS` is a second fingerprinting table and had no
  reader guard.** `EveryFingerprintHasAReaderTest` walked `ATS_PATTERNS` only,
  so a vendor recognised by its CDN could resolve tier A with a token and poll
  nothing — the 88-board silence of Stage 14, one table over. It checks both now.
- **Ranking vendors by how many firms they rescue is the right sweep and the
  wrong order to build in.** The measured list put Avature ninth at 3 firms.
  One of those three is **Two Sigma**, which is worth more to this project than
  ADP's nineteen — the count answers "what is most common", and the question
  here is "who do I want to work for". **Weight that list by the firms on it
  before picking the next reader.**
- **Which ATS to build next is a measurable question, not a guess.** 1,400
  tier-B careers pages were swept for unrecognised third-party *hiring* hosts,
  ranked by how many distinct firms each would rescue: ADP 19, Paylocity 18,
  Radancy 12, Rippling 11, Phenom 7, UKG 5, HiBob 5, Talentsoft 4, Avature 3,
  JazzHR 3, Dayforce 3, Zoho 3, Cornerstone 2. Build down that list, not down a
  list of vendors you have heard of.
- **ADP's `meta.links` looks like a location map and is a filter facet.** It
  pairs an id with a readable place — "Hong Kong - Wanchai, HK" — and joining it
  to the requisition's `itemID` yields a confident location matching nothing:
  those are *location* ids, the places you may search by. **A wrong location is
  worse than none**, because the board gates on geography and `unknown` survives
  the gate while a wrong city does not.
- **Some employers write titles in letters that only look Latin.** Jane Street
  publishes `ꓟachine ꓡearning ꓣesearcher` — M, L and R as Lisu — so it arrived
  as "achine earning esearcher" and matched nothing. Scan before writing the
  map: of 75 suspicious codepoints across all titles, nearly all are genuine CJK
  and must be left alone. Only letters impersonating an ASCII one are folded.
- **Entities were never decoded, and HTML-sourced formats carry them.** Coeli's
  `Business &amp; Risk Operations` folded to the token `amp`; Swedish spells `ä`
  as `&#xE4;`, which would fold to nothing. `extract._text` runs
  `html.unescape`.

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
  Captor and Norron have one line saying there are no vacancies. `_prose_board`
  requires *either* a posting *or* the no-vacancies phrase.
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
- **Three vendors are confirmed closed, and re-checking them cost an hour
  each.** Eightfold's `/api/apply/v2/jobs` answers **403** on Morgan Stanley's
  tenant with or without `domain=`; Paylocity's board is still client-rendered,
  with `/Recruiting/Content/public-jobs-list` serving a stylesheet rather than
  an app bundle; and Jefferies' `tal.net` portal now answers with an **Altcha
  CAPTCHA**, which this project does not complete — the same answer as the DFSA
  register. All three are recorded so the next reader does not re-derive them.
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

- **Hong Kong has no national board this project can read, and that is settled
  rather than pending.** The question is the obvious one to ask -- Singapore's
  statutory portal is the board's largest source, so where is Hong Kong's? It
  exists and it is closed. The Labour Department's **Interactive Employment
  Service** (`jobs.gov.hk`, `www2.jobs.gov.hk`) publishes a `robots.txt` whose
  last line is `Disallow: /`, above it `Disallow: /0/api/*` and
  `Disallow: /isps/Web/WebForm/JobSeeker/Job/*`, and an allow-list of about
  forty paths that are corporate pages plus four *sector* landing pages --
  elderly care, catering, retail, construction. None is finance. **That is the
  exact inverse of MyCareersFuture**, whose `robots.txt` reads `Disallow:` with
  a sitemap, and the two portals are the same kind of institution. The
  commercial boards close the rest: `hk.jobsdb.com`, the dominant one, disallows
  `*?` and `*/job/`, so a search sweep is outside its rules by construction;
  **`efinancialcareers.hk` and `ctgoodjobs.hk` answer HTTP 405 to every path
  including their own homepages** -- a WAF refusing this client, and changing
  the user agent to get past it is evasion. `recruit.com.hk` pages by ASP.NET
  `__doPostBack` and publishes no hitcount, so a sweep of it could not be
  checked for truncation. `jobmarket.com.hk` is the one that is open,
  enumerable and honest -- its own taxonomy, GET paging, and `Record=N` on
  every page -- and its **entire board is 3,639 postings**, of which
  banking-finance is 234. Measured before building anything: it is not a
  Singapore, and Hong Kong's supply has to come from employers instead.
  `data.gov.hk` carries no vacancy dataset either.

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
  stays `relevant` and the posting comes off through `GATES`. **Bare `phd` must
  never gate** — 220 titles carry it and 29 are rated positively.
- **`vikarie` is a contract, not a profession**, and gating on it would delete a
  temporary quant seat on evidence about its duration. **An apprenticeship is
  likewise a contract** — Swiss-German `Lehrstelle` and `Lernende/r` belong in
  `STUDENT_PROGRAMME`. **`Praktikum` is not one of them**: it is German for
  *internship*, and its one positively-rated hit is `Praktikum Private Equity`.
- **`student_intern` is not a seniority.** It was the one value on that ladder
  read from a *body*, so the labelling sheet kept asking a question the tagger
  does not answer. Being a student is `hard_gates: student_only`, and a
  contract.

## Geography

- **A country name in a city's list claims a city it does not know.** `sweden`
  sat in the `stockholm` tuple, so every Swedish ad read Stockholm. Harmless
  while geography ranked; under a gate it deletes postings for being somewhere
  they are not.
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

**Six gates, and they are the whole list**, in `web/build_data.py`'s `GATES`:
`off_industry` (another profession), `off_location`, `out_of_reach` (director,
VP, manager, project leader, product owner), `phd_required`, `rejected` (the
tagger read it and it is not this line of work), and `non_markets_board`. Each
is counted separately on every build, because one total would hide which of them
ate a hub.

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

- **"Too much junk and too little jobs" was one fault, not two, and the bucket
  holding both is `relevance: unknown`.** 199 Nordic cards, of which 176 were
  `unknown` — and that bucket held `Inköpare för UBW Inköp support` thirteen
  times *and* `Commodities Sales to FICC Markets | SEB`, `AP3 söker två globala
  aktieförvaltare` and Swedbank's `APO to Group Treasury`. Emptying `unknown`
  from below (occupation words) and from above (a markets reading) are the same
  repair, and doing only one makes the page worse.
- **Ranking candidate phrases by how many board postings still sit at
  `relevance: unknown` is the measurement that finds what a needle list is
  missing.** It found two families with nothing to do with language: *word order
  and synonym* (`model risk` was a needle and `risk model` was not, so Denmark's
  `Risk Model Developer` read as unlooked-at), and *the desk vocabulary of firms
  that are not trading firms* — custody, fund services, depositary, trade
  surveillance, syndicate, where State Street, Apex, Euronext and SimCorp
  advertise.
- **The number that diagnoses a hub is its board *share*, and it splits by how
  the hub is fed.** A hub reached only through **firm ATS boards** (Amsterdam
  22%, Hong Kong 21%) is already a filtered population. A hub fed by a
  **national board** (Singapore 1.6%, Stockholm 2.9%, Switzerland 0.6%,
  Copenhagen 0.5%) carries every job in the country, so the share is low by
  design and the interesting number is what the *ranked* cards look like.
  **Compare a hub only against a hub fed the same way.** The US metros are the
  first case: they are fed by **firm ATS boards**, so compare New York against
  Amsterdam and Hong Kong, never against Stockholm or Singapore.
- **A hub's positive count is what settles whether it is a focus hub, and it is
  worth recomputing before adding one.** The table that decided the US split:
  New York 468, Chicago 107, Boston 75, all the rest of the US 148 — against
  Singapore 530, Hong Kong 186, Stockholm 81, Amsterdam 38, Switzerland 35,
  Copenhagen 17. Boston went in on 75 *and* on what its postings are (State
  Street model risk and quant research); the Bay Area's 31, Texas's 31 and
  Miami's 15 stayed out on the same second test — wealth advisers, tax
  principals and real-estate capital markets. **Read the positives before
  trusting the count**: it is the same rule as reading what a needle promotes.
- **`no_markets_signal` fires in proportion to how foreign the language is, and
  that is alarming until you read the postings.** It rejects 63% of
  Switzerland, 27% of Copenhagen, 16% of Stockholm, 3% of Hong Kong — exactly
  ordered by how much of `MARKETS` the hub's language is written in. **Measured,
  it is correct**: the Swiss and Danish rejections are retail bank advisers,
  insurance salespeople and nurses, because the national boards carry almost no
  markets jobs at all — the Swiss banks advertise through their own ATS boards,
  in English. Do not "fix" this; it was checked.
- **The `unknown` bucket is a vocabulary gap, not a broken rule, and only volume
  showed it.** **6,604 of 6,852 had no body at all**, so it was never going to
  be fixed by reading descriptions better; it needed occupation words. The
  residual is mostly the deliberate backfill queue — bare `Analyst`,
  `Associate`, `Data Scientist` — which `judge` refuses to reject on a title
  alone and should keep refusing.
- **A fifth of the board came off and the shortlist did not move, which is what
  a good tightening looks like from outside.** Stages 35 and 36 together: 8,513
  cards → 6,666, 1,515 firms → 1,137, and **"worth reading" unchanged at 224**.
  The hand sheet's relevance agreement went **71.7% → 83.6% with zero false
  rejections in it at either end**. When a change removes volume, the number to
  read is the one that should *not* have moved — a shortlist that shrinks with
  the junk means the needle was too wide, and no aggregate count says so.
- **The reader's reclassify clicks measure the direction the labelling sheet
  cannot, and they are worth re-reading whenever a batch accumulates.** `sample`
  draws from a frame built to find false *rejections* — the failure this project
  calls expensive — and by that measure the tagger is clean: **zero false
  rejections in 152 hand-labelled rows**. The clicks measure the opposite
  failure and found plenty: of 137 postings marked `rejected`, **97 were already
  gated and 40 were still on the board**. Read them as four families, because
  only two are bugs — a body-markets escape (19), an inflection gap (2), the
  reader's own standing "`discretionary_investing` ranks rather than rejects"
  call (9), and a markets word in the *title* of a back-office seat (5). **Check
  which family a row is in before writing a needle for it**; two of the four are
  working as instructed.
- **Twelve model labellers were run over 471 postings and the finding was that
  the classifier is right, which is a result and not a failure.** Scored
  separately: the **hand sheet is 83.6% on relevance with zero false
  rejections**, and seniority containment is **14/14 leadership kept off the
  board, 0 openings lost to the rank gate**. Of 469 model labels only **nine**
  disagreed in the expensive direction, and reading them, seven are the model
  being wrong or the tagger being defensibly right.
- **Model labels must not go in `labels.csv`, and that is what the two sheets
  are for.** They were written there once and it was wrong: `labels.csv` is the
  *hand* sheet and `auto_labels.csv`'s own comment says a machine sheet becomes
  evidence only after **the user has read and confirmed it** -- "the step that
  turns it from an echo into evidence". Unreviewed model labels live in
  `agent_labels.csv` and gate nothing.
- **A model labeller told to prefer `adjacent` when torn will label almost
  anything `adjacent`.** The instruction was *"when genuinely torn between
  `rejected` and `adjacent`, choose `adjacent`"* -- sound on its own and it
  produced `adjacent` for `Slack Administrator`, `IT Support Engineer`,
  `Network Security Engineer`, `AI Marketing Technologist Lead` and
  `Account Management Lead - SMB`. The same run labelled
  `Junior Quantitative Analyst (Credit & FI)` **rejected**. **Read what a
  labeller promotes before treating its disagreements as bugs** -- it is the
  needle dry-run rule applied to the grader instead of the lexicon.
- **The two rules the model sheet flagged loudest are both correct, and the
  measurement is what settles it.** `desk support` removes **9,072** live
  postings and a hand-read of thirty in focus hubs is `CLEANING OPERATIONS
  MANAGER`, `EV Battery Operations Supervisor`, `Rental Operations Agent`,
  `HR Operations Lead` -- bare `operations` and `compliance` in
  `_DESK_ADJACENT` are doing the work, and the *verdict* is right even where
  "desk support" is the wrong *reason*. `crypto_web3` removes **686**, of which
  637 never say crypto in the title -- and they are Kraken (`payward.com`, 40),
  Galaxy, BitGo, Blockchain Capital, Castle Island. **Softening either would
  cost hundreds of correct rejections to rescue about twenty postings.**
- **A count threshold does not separate a crypto firm from crypto boilerplate.**
  The obvious fix for the ~20 mainstream managers caught by `crypto_web3`
  (State Street, T. Rowe Price, LSEG, ProFunds) is to demand two mentions.
  Measured, the distributions are identical: **445 of 617 correct crypto-firm
  rejections also mention it exactly once**, against 16 of 20 false ones. The
  discriminator is the *board*, not the posting -- `lexicon.board_profile`
  again, which is also the answer for a small quant shop whose
  `Machine learning researcher` reads `unknown`.
- **The body-level markets anchor is 96% precise and does not need fixing.**
  102 postings are kept by a single body quant phrase plus a body markets word;
  **`trading` alone does 68 of them and they are XTX and Squarepoint
  engineers**, correctly kept. The bad ones are three: a neuroscience
  `Principal Research Scientist` anchored on *asset management*, an insurance
  `Catastrophe Risk Modeler` on *risk analytics*, and the `Computational
  Chemist` on **`reference data`** -- the same posting `_markets`'s own
  docstring names as the failure it was written to stop. One posting each;
  `reference data` stays in `MARKETS` because it is a real markets title on the
  other 38.
- **A labelled disagreement and a labelled non-answer are different facts, and
  one number hid it.** `labels` prints both: `wrong` is what a lexicon fix can
  move, `unanswered` is not, and only the first is evidence of a bug.
- **Seniority is scored by what it is for, not by agreement on a rung.**
  `labels.containment` asks the two questions with consequences — how much
  labelled leadership the board withholds, and how many wanted postings the rank
  gate removed — and reports them separately, because netting them off would
  hide both.
- **A fixture drawn from the top of the shortlist can only find false
  positives**, while the exit criterion is *no false rejection*. **But
  stratifying over the whole corpus is the opposite mistake**: 30% `out_of_scope`
  is housekeepers and van drivers, and the notes came back *"nothing to do with
  finance"*. **A false rejection can only hide among postings that could
  plausibly be in scope.** `labels._candidates` draws from a frame of ~2,000.

## Tagger versioning

- **Changing the lexicon without bumping `TAGGER` leaves stale tags that look
  current.** `tag` only visits postings with no row at the *current* version, so
  after an unbumped edit it reports `tagged 0 postings` and every summary keeps
  serving the old answers.
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
list.** A needle can only match if its first word is a token of the text, so
`lexicon._index` skips most of a 600-needle list on a set lookup. With one
translate pass in `fold`, each field folded once and composed rather than
re-folded, and an inverted stopword index in `posting_language`, a 17,417-posting
sample went **52.7s → 13.8s (3.8x)** with byte-identical output.

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
