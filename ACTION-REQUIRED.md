# Things only you can do

Nothing is open. Every judgement call previously parked here has been settled,
and the settled list below is kept so none of it gets re-asked. The pipeline
runs and the board is live at https://quantjobs.spawned.app.

Add an item here when something genuinely needs your input; delete it when it
is resolved, and move the reasoning worth keeping into `CLAUDE.md`.

---

## Settled

### Crawling

- **robots.txt is not honoured, at your instruction.** The compensation is
  rate: every disallowed host runs at one request per four seconds
  (`http.HOST_INTERVAL_S`), which is slower than the default one per second,
  and no host is swept more than weekly. Nothing else about the request
  changes.
- **What that does *not* cover, and will not:** CAPTCHAs (Dubai's DFSA,
  Jefferies' Altcha) and WAFs that refuse this client outright
  (`efinancialcareers.hk` and `ctgoodjobs.hk` answer HTTP 405 to every path,
  Quantlab's Jobvite 403s). Getting past those means completing a
  bot-detection challenge or changing the user agent to look like something
  else, which is a different act from ignoring a text file. Those stay closed.
  If you want Quantlab, read its board token off the page in a browser and
  hand it over.
- **Hong Kong's statutory board is now read** — `quantscraper/iesjobs.py`,
  `python -m quantscraper hongkong`. `jobs.gov.hk` disallows the whole site;
  it is swept anyway — all 14,287 postings, walked as the portal's own
  29-way job-type partition, ~50 minutes, weekly in `daily --full`. Every
  slice prints its own hitcount and the union is audited against the whole
  board, so the sweep checks itself thirty times over. To drop it: remove the
  `hongkong` step from `_daily` in `cli.py`.
  - **Its cards carry no link, on purpose.** The portal addresses a job card
    by a token it mints per render and that token **expires**, so a stored one
    lands on a search box — `CLAUDE.md`'s *worse than no link*. The Job Order
    Number is the posting's id and the portal finds it. One line in
    `iesjobs._job` puts the links back if you would rather have them working
    for a few hours after each sweep and dead after.
  - **Its employers and descriptions arrive over time.** They live on the job
    card, which costs two requests per posting (search, then read), so the
    ~2,900-posting backlog is several hours of `bodies` spread over runs.
    Until a posting is reached it groups under `~unknown` on the board.
- **Jobindex (Denmark)** uses the `page=` parameter its robots.txt disallows.
  Without it no query returns more than 20 postings.
- **Citadel** 403s every page and answers 200 to the sitemaps its own
  `robots.txt` names; `career-sitemap.xml` is the whole board, 136 postings.
- **MyCareersFuture (Singapore) is not a robots question** — its `robots.txt`
  reads `Disallow:` with a sitemap. It is a rate threshold, and four seconds
  clears it: 958 pages, 95,536 postings against 95,561 advertised, no refusal.
  You chose not to write to the feedback form their 429 header names, and
  nothing needs it.

### The board

- **Published, and re-published every Wednesday at 03:00.** The sweeps now run
  concurrently (different hosts, same per-host rate), which takes the source
  half of the run from about 160 minutes to about 70.
  A Windows
  Task Scheduler task runs `weekly.ps1` -> `daily --full --publish`; the
  machine is woken for it and sleeps afterwards. `install-weekly.ps1 -Remove`
  takes it away, and `logs/weekly-<date>.log` is the transcript. It has to be
  a local timer because `data.js` is built from the local database. Note it
  runs as your logged-on user and no password is stored, so a fully
  logged-out machine skips the week and catches up at the next opportunity.
- **Public and unauthenticated**, by your choice. Every posting on it is a
  public advertisement, `robots.txt` disallows every crawler, and closing it
  would be a CloudFront function checking a cookie if you ever want that.
- **The dead `board` branch on `razrer/quantjobs` is deleted.**

### Labels and the tagger

- **`agent_labels.csv` counts.** All three sheets are in `labels.SHEETS` and
  scored, each on its own line, because they do not agree: hand 84.9%, auto
  77.9%, agent 45.0%. The false-rejection list names the sheet each row came
  from — **41 agent, 37 auto, 0 hand**, and the hand sheet is still the exit
  criterion.
- **`prune` had nothing to do, twice.** `job_tags` holds only the current
  lexicon and nothing else — checked before the re-tag and again after it. The
  primary key omits `tagger`, so a full re-tag rewrites every row in place
  rather than leaving a second copy, which is why the superseded versions the
  item described had already vanished. `VACUUM` is what returns the freed
  pages to the filesystem. There is no subcommand for it, deliberately — it
  rewrites the whole 3.5 GB file and needs that much free space again while it
  runs, so it is a thing you do knowingly:

  ```bash
  python -c "import sqlite3; sqlite3.connect('employers.sqlite3').execute('VACUUM')"
  ```
- **Every reversible call stands** — they are listed in `CLAUDE.md` with the
  one-line reversal for each: wealth advisory rejects, the three mined
  exclusion categories, a plain `Senior` no longer gating, markets seats
  ranking rather than rejecting, the closing-date pin restricted to the
  shortlist, a body markets word no longer stopping `no_markets_signal`,
  `non_markets_board`, `Hide pure trader roles` starting off, Södertälje in
  Stockholm, heavy systems down-ranking rather than dropping.

### Firms and sources

- **Norron is dropped.** Sold to Simplicity AB; `norron.com/sv/karriar/` 404s.
  The reader and its `Site` row are gone and the roster row is `stale`, so a
  miss there reads as correct. Simplicity is a different employer and would
  want its own roster line.
- **Tibra stays out.** `apply.workable.com/tibra-capital-1` fingerprints
  cleanly and serves zero postings — re-checked, still zero — so there is no
  evidence it is Tibra's board rather than a stale account. Recording it would
  poll silence forever.
- **Dubai is closed.** The DFSA register is behind a reCAPTCHA. If you want
  the Gulf, the route is naming firms by hand in `registries/seed_firms.csv`;
  that universe is small and nameable, unlike the Nordics.
- **Sponsored-access firms are in no register.** A firm dealing only on its own
  account is exempt under MiFID II Art. 2(1)(d) and one trading under someone
  else's exchange membership appears nowhere public — Da Vinci Derivatives is
  the standing example. `cboe_europe` and `seed` close part of it; the rest is
  `seed_firms.csv`, by hand.
- **A VC's careers page can claim its portfolio's board.** `ashby/clubhouse`,
  `greenhouse/arxroboticsgmbh`, `greenhouse/bicyclehealth`,
  `greenhouse/hippo70` are each claimed by two or three venture firms. It is
  contained — `upsert_jobs` keys on `(ats, token, job_id)`, so the second
  claimant writes nothing — and no guard shipped, because the safe one
  (reading the postings, as `discover.corroborate` does) would put a *name*
  test inside `ats.fingerprint`, the one place this project keeps name-free.
  Say the word if you want it behind a flag.

### Older calls

- **Storage** → SQLite. **Classification** → keyword-only, no LLM spend.
  **Build order** → registries before ATS extraction.
- **The SEC ADV bulk file is SEC registrants only.** `Firm Type` is uniformly
  `Registered`; the sub-$110M US tail needs a source that does not exist.
- **`roster.csv` is the audit set, never the universe.** Its `status` column
  marks a dead firm so a miss stops reading as a bug. Keep names specific — a
  bare `Grasshopper` matched `GRASSHOPPER ESCAPEMENT, LLC`. Use
  `seed_firms.csv` to add a firm to the database.
- **The FCA key is supplied**, in `.env`, gitignored. It cannot enumerate, so
  `fca.py` sits outside `registries/` deliberately — it is a source of
  *websites*. The key was pasted into a chat transcript; regenerate it at
  https://register.fca.org.uk/Developer/s/ if that bothers you.
- **The msys2 Python** → `run.ps1` / `run.sh` call the Windows interpreter.
- **Switzerland and Denmark's national registers** → both open, both built.
  The Swiss 401 was our own URL bug; Denmark's `jobnet.dk` needs a MitID, so
  Jobindex serves it instead.
