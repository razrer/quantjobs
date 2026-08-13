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

Read `PLAN.md` before starting work. It says which stage is next and how that
stage knows it is finished.

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
    per source)         edited)
```

- `models.py` — `Employer`, the one record type registries produce
- `http.py` — throttled, retrying GET; standard library only
- `parsing.py` — minimal HTML table helper for registries that publish web pages
- `db.py` — SQLite schema and upserts
- `resolve.py` — entity resolution
- `registries/` — one module per source

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

- **Focus:** Stockholm, Copenhagen, Amsterdam, Switzerland, Dubai, Hong Kong,
  Singapore
- **Deprioritized:** Germany, US, London/UK, China. Existing US data
  (`sec_adv`, `sec_bd`) stays; it is simply not where the next effort goes.

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

- **Workday** returns an empty `jobPostings` array with **HTTP 200** if `limit`
  exceeds 20 — indistinguishable from "no jobs" unless asserted on. Workday is
  how most large banks publish. Not yet implemented; do not get this wrong.
- **Form ADV** `Website Address` is a LinkedIn page for over 4,000 filers, plus
  ~2,000 more on other social platforms. Useless for domain resolution, and it
  merges the whole long tail into one firm if used as an identity key.
- **SEC broker-dealer file** is UTF-16 with a blank line between every record,
  so roughly half of parsed rows are empty by design.
- **SEC bulk file paths move**, and filenames are inconsistent
  (`bd-070124.txt`, `bd080126.txt`, `bd080122_1_0.txt`, plus malformed
  seven-digit ones). Read the link off the index page; never construct a URL.
- **AFM** exports are semicolon-delimited and cp1252-encoded, neither declared.
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
