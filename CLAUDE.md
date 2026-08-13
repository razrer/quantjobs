# CLAUDE.md

Guidance for Claude Code working in this repo.

## What this is

A personal job-hunt tool that aggregates quantitative-finance job listings.
**Exhaustiveness is the hard requirement** — a missed listing is the expensive
failure, a duplicate is not.

The architecture is **employer-first, not aggregator-first**: enumerate the
firms that could hire a quant from registries that are complete by law, resolve
each to its own careers feed, and poll that. Aggregators are a discovery net for
employers we lack, never the primary content source.

- **Acquisition methodology:** `C:\Users\razre\.claude\plans\snoopy-growing-hoare.md`
- **Execution order and exit criteria:** `PLAN.md`
- **Work blocked on the user:** `ACTION-REQUIRED.md`

Make sure to wrote to `ACTION-REQUIRED.md` when something needs to be reviewed or manual input is needed, and remmove it when it has been resolved.

Read `PLAN.md` before starting work. It says which stage is next and how that
stage knows it is finished. When you finish a stage, make sure to update the plan.

## Running it

```bash
python -m quantscraper fetch     # pull employers from registries
```

```bash
python -m quantscraper resolve   # group raw rows into firms
```

```bash
python -m quantscraper stats     # what is in the database
```

```bash
python -m quantscraper audit     # check the universe against the named roster
```

```bash
python -m quantscraper domains --limit 1000   # resolve firm names to domains
```

```bash
python -m quantscraper fca --limit 300        # enrich domains from the FCA register
```

```bash
python -m quantscraper ats --limit 800        # fingerprint careers hosts to an ATS
```

```bash
python -m quantscraper jobs --limit 100       # pull postings from resolved boards
```

```bash
python -m unittest discover -s tests          # the Workday regression tests
```

`fca` needs `FCA_EMAIL` and `FCA_KEY` in `.env` (gitignored, never committed).

`run.ps1` / `run.sh` wrap these with the correct interpreter (see below).

**Interpreter gotcha — this will waste your time otherwise.** Bare `python`
here resolves to the msys2 build, which ships without a CA bundle, so every
HTTPS request dies with `CERTIFICATE_VERIFY_FAILED`. Use the Windows Python:

```bash
"/c/Users/razre/AppData/Local/Programs/Python/Python313/python" -m quantscraper fetch
```

Also set `PYTHONIOENCODING=utf-8` when printing firm names, or non-ASCII names
raise `UnicodeEncodeError` on this console.

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
- `domains.py` — Layer 2: firm name -> domain, guessed then verified
- `fca.py` — Layer 2 enrichment from the FCA register; needs `.env`
- `ats.py` — Layer 2: domain -> `(ats, token)` by fingerprint, else tier B/C
- `extract.py` — Layer 3: one function per ATS format; postings land in `jobs`
- `registries/` — one module per source

`roster.csv` is the *audit set*, never the universe. A firm's absence from it
says nothing about whether it belongs. When adding entries, keep names specific:
a bare `Grasshopper` matched an unrelated `GRASSHOPPER ESCAPEMENT, LLC` and
reported a hub better covered than it was. A false hit hides a miss, so it is
worse than a false miss — the same bias as principle 3 below.

**No third-party dependencies.** Standard library only, so there is nothing to
install. Keep it that way unless there is a strong reason not to.

## Adding a registry

Drop a module in `quantscraper/registries/` exposing `NAME`, `JURISDICTION`,
`MIN_EXPECTED` and `fetch() -> list[Employer]`, then add it to `REGISTRIES` in
that package's `__init__.py`. Nothing else changes.

Prefer sources you can **enumerate** over sources you must **query**. A search
endpoint only returns what you thought to ask for, which is a hard ceiling on
recall; a category listing or a bulk file has no such ceiling. This is why
`fi_se` walks regulatory categories instead of searching, and why the SEC
broker-dealer bulk file was chosen over FINRA's search API.

## Principles that must not be quietly violated

These are load-bearing. If a change appears to require breaking one, stop and
raise it rather than working around it.

1. **Never filter the employer universe.** Every firm a registry returns is kept
   forever, and rows are never deleted. Regulatory attributes and geography set
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
   not.
5. **Raw tables are append-only.** `employers` is never edited; derived tables
   like `firms` rebuild from scratch on demand.

## Geographic priority

Priority affects **what to build next**, not what to ingest. Never drop
collected data for being out of area — the methodology is explicit that
geography ranks results rather than gating the universe.

- **Focus:** Stockholm, Copenhagen, Amsterdam, Switzerland, Hong Kong,
  Singapore
- **Deprioritized:** Germany, US, London/UK, China, Dubai. Existing US data
  (`sec_adv`, `sec_bd`) stays; it is simply not where the next effort goes.

All six focus hubs are at 100% of the audit roster *present*. The number that
still varies is *local* — whether a registry covering that hub reported the firm,
rather than it being visible only through a foreign registration: Stockholm
20/20, Copenhagen 7/7, Amsterdam 13/13, Switzerland 9/11, Hong Kong 8/9,
Singapore 7/10.

## Scope discipline

The user has asked for minimal, readable, maintainable code and for the work to
proceed methodically rather than opportunistically. Concretely:

- Work the current `PLAN.md` stage to its exit criterion, then stop.
- Do not add sources because they are interesting. Add them because the audit
  says they are missing.
- Verify against real endpoints before writing an adapter — every source in
  here needed reconnaissance, and several published formats nothing like what
  their documentation implied.
- **Do not create accounts or register for API keys.** Put those in
  `ACTION-REQUIRED.md` for the user.

## Source gotchas already discovered

Each of these silently produced wrong results before being caught:

- **Workday's real trap is `total`, not `limit`.** The long-standing note here
  said `limit > 20` returns an empty array with HTTP 200; against the tenants
  we poll it returns **HTTP 400**, which is loud. The silent one is that
  Workday reports the true `total` on the first page and **`total: 0` on every
  page after it** — so stopping when `len(jobs) >= total` truncates every board
  at 20 postings with no error at all. Cap the page at 20, page by `offset`,
  stop only on a short page. `tests/test_workday.py` pins all three; both
  protections are mutation-tested.
- **Workday needs `tenant|wdN|site`.** A tenant alone builds a URL that 404s on
  every poll while the board looks resolved.
- **ATS board tokens are easy to extract wrongly, and the wrong answer looks
  right.** `boards-api.greenhouse.io/v1/boards/{token}` puts an API version
  before the board, so matching the host alone yields `v1` for every Greenhouse
  user; `www.teamtailor.com` fits the `{board}.teamtailor.com` shape and yields
  `www`. `ats.py` filters both against a list of infrastructure hostnames.
  Always read the first handful of tokens before trusting a batch.
- **Form ADV** `Website Address` is a LinkedIn page for over 4,000 filers, plus
  ~2,000 more on other social platforms. Useless for domain resolution, and it
  merges the whole long tail into one firm if used as an identity key.
- **SEC broker-dealer file** is UTF-16 with a blank line between every record,
  so roughly half of parsed rows are empty by design.
- **SEC bulk file paths move**, and filenames are inconsistent
  (`bd-070124.txt`, `bd080126.txt`, `bd080122_1_0.txt`, plus malformed
  seven-digit ones). Read the link off the index page; never construct a URL.
- **AFM** exports are semicolon-delimited and cp1252-encoded, neither declared.
- **AFM's CSV exports are not the whole register.** The AIFM manager registers
  are published only as `.xlsx` files further down the same page, while the CSV
  export link sits at the top and looks complete. Missing them cost PGGM and APG
  Asset Management. Always scroll the register page for spreadsheet links.
- **FI publishes 495 category codes**, not the 139 an earlier note claimed, and
  most are permissions rather than company types. Occupational pension
  undertakings are filed under *three* separate codes by legal form — walking
  only `TJPAB` misses Alecta, which is a mutual (`TJPÖMS`).
- **Finanstilsynet (DK) has no enumerable endpoint.** Six service operations,
  none of them a listing; the site's own "list extract" and "explore data" pages
  render empty shells. `searchVUT` matches a substring, so the register is swept
  by single letters and unioned. Saturation is the completeness evidence.
- **SFC (HK) returns `totalCount: 0` rather than an error** when the session
  cookie or the `nameStartLetter` field is missing. Both are required. Fetch the
  search page first; `http.post_form` shares one cookie jar for this.
- **MAS (SG) ignores every page-size parameter** — ten rows per page, no
  override. An out-of-range page returns zero rows rather than wrapping to the
  first, which is what makes the walk terminate correctly.
- **A guessed domain must be verified against the page, and one word is not
  proof.** `australia.com` (the tourism board) "matched" Australia and New
  Zealand Banking Group, `societe.com` matched Societe Generale, and
  `citadel.com` matched *Citadel Securities* — a different employer with a
  different careers page. `domains.py` grades matches strong/weak for this
  reason; only strong ones count. A wrong domain yields a silently empty job
  feed, which is worse than no domain at all.
- **Evidence must not be circular.** `marketfrance.com` proved itself by
  printing its own domain on the page — and the domain was what we guessed.
  Match on spaced phrases, never on the run-together form.
- **Fold both sides the same way before matching text.** The register says
  "J.P. Morgan SE" (normalizing to `jp morgan`) while the page says
  "J.P. Morgan"; comparing a normalized name against raw page text silently
  matches nothing.
- **FCA: Cloudflare returns 403 "error 1010" to any request without a
  `User-Agent`**, which is indistinguishable from a bad API key. If FCA calls
  start failing, check the header before you doubt the credentials.
- **FCA `CommonSearch` returns "No search result found" for everything**, for
  any query, forever. The working endpoint is `Search?q=...&type=firm`. Paging
  is `pgnp=N` — not `page`, which is silently ignored while the response
  helpfully advertises `pgnp` in its own `Next` URL.
- **FCA cannot enumerate, and this is now settled.** Queries under three
  characters are rejected, and broad ones ("trading", "capital") return
  `Request Entity Too Large`, so the Danish letter-sweep trick does not
  transfer. There is no bulk download. It is enrichment only — `fca.py` lives
  outside `registries/` deliberately, because calling it a registry would
  overstate coverage.
- **FCA search is fuzzy**: a query for "barclays" returns `PEAC Business
  Finance Limited` first. Accept a result only on a token-aligned name match.
- **ESMA's Solr endpoint is open and is a real enumeration** — `q=entity_type:ae`
  returns all 13,930 EEA firms, paged. Always pass `sort=id asc`: deep paging
  without a stable sort silently repeats and skips rows. The child documents
  (`aeActivity*`, 87,000 of them) are per-permission rows, not firms.
- **`CERTIFICATE_VERIFY_FAILED` on Windows usually means our trust store, not
  their server.** Windows populates its root store *lazily*, so a fresh Python
  process trusts only the roots already cached — 38 here, against 152 in a real
  bundle. FINMA was diagnosed as "serves an incomplete chain" on that evidence
  and the diagnosis was wrong. **Test with `curl` first**: it ships its own
  bundle, so if curl connects and Python does not, the server is fine and the
  store is short. `http.py` now loads a full bundle from Git or msys2.
- **Form ADV covers SEC registrants only.** Advisers under roughly $110M AUM
  register with their state and are absent.

## Known structural gaps

Documented in the README, but the load-bearing one: a firm dealing exclusively
on its own account can be exempt from investment-firm licensing under MiFID II
Art. 2(1)(d), so it appears in **no** register. Exchange participant lists cover
most of these. Firms trading via sponsored access under someone else's
membership are covered by nothing public — Da Vinci Derivatives is the standing
example.

## Role scope for later classification

Not yet implemented, recorded so it is not lost. The user has under a year of
experience and has **already graduated**, so student-only postings requiring a
future graduation date are noise. Python/research-oriented, explicitly not a
C++/Rust specialist.

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
