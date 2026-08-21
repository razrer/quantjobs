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

Make sure to not output neccessary text in the GUI, just write result or other important messages.

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
python -m quantscraper discover --roster      # find boards no careers page named (Layer 2C)
```

```bash
python -m quantscraper jobs --limit 100       # pull postings from resolved boards
```

```bash
python -m quantscraper pages --limit 500      # watch tier-B careers pages (Layer 3B)
```

```bash
python -m quantscraper tag                    # classify postings into tags (Layer 5)
```

```bash
python -m quantscraper list --fit apply_now --hub amsterdam   # filter the tags
```

```bash
python -m quantscraper sample --limit 100     # draw postings to hand-label
```

```bash
python -m quantscraper labels                 # score the lexicon on them
```

```bash
python -m quantscraper list --dimensions      # every filterable value
```

```bash
python -m quantscraper coverage               # how much of the market we see
```

```bash
python -m quantscraper domains --regrade --limit 2000   # re-check strong matches
```

```bash
python -m quantscraper jobstream              # poll Sweden's delta feed
```

```bash
python -m quantscraper switzerland            # poll job-room.ch (Layer 4)
```

```bash
python -m quantscraper sweden                 # sweep Jobbsafari, all of it
```

```bash
python -m quantscraper denmark                # sweep Jobindex, every category
```

```bash
python -m quantscraper denmark --since 2026-08-18   # daily top-up, one query
```

```bash
python -m quantscraper jobstream --since 2026-08-12   # replay a polled window
```

```bash
python -m quantscraper alerts                 # flag sources that broke quietly
```

```bash
python -m unittest discover -s tests          # regression tests
```

The board is a static page. Dump the data, then serve `web/` — it reads
`data.js` with a script tag so `file://` works too, but a server is tidier:

```bash
python web/build_data.py && python web/serve.py
```

`serve.py` is `http.server` plus one write route: the board's reclassify
dropdowns POST a correction there, and it upserts straight into
`quantscraper/labels.csv` — no download, no manual merge. Opening `index.html`
via `file://` or a bare `http.server` still works for reading the board; a
correction made that way only lives in the browser until you export it by
hand.

`data.js` omits every dimension sitting on its "nothing known" default rather
than writing `unknown` a hundred thousand times. The board reads a missing key
as exactly that — do not "fix" it by writing the defaults back in. It was ~33 MB
when that mattered most; the four gates have since taken the board from about
45,000 postings to **9,431 out of a 236,077-row corpus**, so the file is 4.4 MB
and the omission is now worth roughly a third of it rather than a half. If it
ever looks *too* small, the number to read is the per-gate breakdown every
build prints, not the file size.

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
- `discover.py` — Layer 2C: firm name -> board token, guessed then proven
- `extract.py` — Layer 3: one function per ATS format; postings land in `jobs`
- `jobstream.py` — Layer 4: Sweden's national delta feed, cursor in `feed_state`
- `jobroom_ch.py` — Layer 4: Switzerland's public employment service; shares
  `feed_state`, walks from both ends around a 10,000-result window
- `jobindex.py` — Layer 4: Denmark's job board, enumerated by partitioning its
  own subcategory taxonomy under a published 1,000-posting result window
- `jobbsafari.py` — Layer 4: Sweden's widest board, Jobindex's sibling. One
  unfiltered walk of ~98 pages, no result window, robots-clean
- `alerts.py` — per-source volume anomaly detection over the `runs` history
- `registries/` — one module per source
- `web/build_data.py` — Layer 6: dumps `jobs` + `job_tags` to `data.js`
- `web/index.html` — the board: filter rail, card grid, deadline-first ordering

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

**One deliberate exception, at the user's instruction: the *board* gates on
geography.** The universe rule above is unchanged and still absolute — no row
is deleted, no registry is filtered, `jobs` keeps everything, and re-running
the tagger rebuilds the verdict. What changed is what `web/build_data.py`
renders: a posting in Kiruna, Barcelona or Paris is not one this user will
take, so ranking it below Amsterdam answers a question they did not ask. See
`exclusion_reason: off_location`, and `web/build_data.py`'s `GATES` — deleting
a line there puts those postings back on the next build, with no re-tag.

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
- **Workday has a second host and it inverts the URL.** On `myworkdayjobs.com`
  the tenant is the subdomain; on `myworkdaysite.com` the subdomain is a bare
  `wdN` and the tenant moves into the path —
  `wd3.myworkdaysite.com/recruiting/brevanhoward/BH_ExternalCareers`. One
  pattern cannot match both, and every firm on the second host tiered B with a
  live feed behind it. The two patterns capture the same three parts in
  *different orders*, so they capture by name: joining by position built
  `wd3|brevanhoward|BH_ExternalCareers`, which is well-formed and addresses
  nothing. The token takes an optional fourth part for the host.
- **The audit measures the employer universe, not the job pipeline, and the two
  had drifted completely apart.** All six focus hubs report 100% *present*
  while **147 of the 163 roster firms produced no postings at all** — Jane
  Street, Optiver, Citadel, Jump, SIG, DRW, Two Sigma, IMC, Squarepoint and
  Qube among them. Being in `employers` and being polled are different
  properties; `audit` only ever checked the first. When a coverage number looks
  finished, ask which table it counted.
- **The firms that matter were all tier B, and the careers walk is why.** It
  settled on Jane Street's `/join-jane-street/overview/`, on a Cloudinary
  **image** for DRW and on a **PDF** for Man Group — the roles page was never
  fetched. `discover.py` exists because no regex over the page we did fetch can
  fix that: guess the token from the name and prove it against the feed.
- **A guessed board token must be proven by the postings, not by the token.**
  `greenhouse/cfm` is a live board of 9 postings whose first three are *Account
  Executive - Air Distribution* — a heating company, not Capital Fund
  Management — and `recruitee/radix` is a different Radix. Same failure as
  `heyrowan`. Corroboration is a **spaced** needle so the run-together token
  cannot match itself, the same guard `marketfrance.com` taught one layer up,
  and a lone word never counts: *radix* proves nothing about Radix Trading.
- **Verify a discovered board by running the extractor, not by status code.** A
  board Layer 3 cannot read is not a board, and an empty one recorded as
  resolved polls silence forever.
- **A roster trading name is not the board token, and searching it alone finds
  nothing.** The roster says `Akuna`, `Qube`, `Da Vinci`, `Old Mission`,
  `Squarepoint`; the boards are `akunacapital`,
  `quberesearchandtechnologies`, `davinciderivatives`, `oldmissioncapital`,
  `squarepointcapital`. The full names were in `employers` the whole time —
  `discover.Target` carries every name `audit` matched, and corroboration is
  checked against the *same* name each token came from, so a wider search does
  not become a looser test.
- **`domain_lookups.query` is the registry's name for a firm, not the
  roster's.** Looking a roster entry up by exact name found a domain for 40 of
  161 and reported the other 121 as having none; going through `audit.run`'s
  matching found 104 of 120. The same mistake reads as a coverage collapse.
- **But that match is fuzzy, so a discovered board must never displace a
  working one.** `Millennium` matches *Millennium New Horizons Management*, a
  venture firm at `mnh.vc`, and `Two Sigma` resolved to `x.com`. Writing a
  board against a wrong domain mis-attributes postings, which is cheap;
  overwriting a live tier-A board with them loses a feed, which is not.
  `discover.record` upgrades only rows that are tier B/C or tier A with a NULL
  token.
- **A three-character board token is fine; a three-character *domain* guess is
  not.** `domains._labels` refuses labels of three characters or fewer because
  a wrong domain is a silently empty feed, and reusing that rule for board
  tokens cost IMC's board — which is `imc`, worth 165 postings. Token length is
  not the safety check; corroboration is. Only a *distinctive* word earns the
  short form, or "Capital Fund Management" would offer the token `capital`.
- **Some employers write titles in letters that only look Latin.** Jane Street
  publishes `ꓟachine ꓡearning ꓣesearcher` — M, L and R as Lisu MA, LA and ZHA —
  and `fold` kept `a-z0-9+#`, so it arrived as "achine earning esearcher" and
  matched nothing. Scan before writing the map: of 75 suspicious codepoints
  across all 69,961 titles, nearly all are genuine CJK and must be left alone.
  Only letters impersonating an ASCII one are folded.
- **A closing date is published as a field by exactly one source, and mining it
  out of prose is a trap.** JobStream sets `application_deadline` on every ad;
  no other ATS in the set publishes one at all. The temptation is to read it
  out of `description` instead — don't. Hundreds of Swedish ads carry *"tjänsten
  kan tillsättas innan sista ansökningsdag"* with **no date in the sentence**,
  and Ashby prints *"unless a specific application deadline is stated"* on every
  posting it hosts, so a phrase sweep is almost all false positives. The board
  sorts an approaching deadline above everything else, so a wrong one nails the
  wrong card to the top of the page for weeks. Same asymmetry as the roster's
  `GRASSHOPPER ESCAPEMENT, LLC`, two layers up.
- **Platsbanken is not a census, and three files claimed it was.** Publishing
  there is **voluntary** for private employers — only state agencies must
  announce openings — so "every job advertised in Sweden is published to
  Platsbanken" was false, and "JobStream makes a hub complete" followed from
  it. Measured against our own data: of the Stockholm employers reached through
  their *own* board, JobStream carries **0 of 55**. Not a shortfall, a disjoint
  set — Swedbank, Nordnet, Tink, Qliro, Intrum and Svea all advertise on their
  own Teamtailor and Workday boards and nowhere in the feed. It is a wide net,
  not a backstop, and `coverage.blindspot` prints the number every run so the
  assumption cannot creep back. The capture-recapture estimator was never wrong
  — it *requires* both samples to be incomplete — but the two turn out to be
  near-disjoint rather than independent, which biases the population down and
  makes any share it reports a ceiling.
- **A platform domain is not an employer, and it leaks into three layers.**
  Over 4,000 Form ADV filers publish a LinkedIn page as their website.
  `resolve.is_platform_domain` is the one answer: Stage 1 must not merge 6,688
  firms onto it, Layer 2C must not file Point72's 229 postings under
  `linkedin.com` (it did), and the Stage 10 miss list must not top out with
  `youtube.com` and `instagram.com` (it did). Match the registrable suffix —
  the junk arrives as `uk.linkedin.com` as often as the bare form.
- **Half of JobStream's ads have no resolvable employer URL**, so `domain` is
  NULL and the board showed 1,737 postings from nobody. `jobs.employer` holds
  the advertiser name verbatim for the sources whose board is not one firm's
  own; everywhere else the domain *is* the employer and a second name would be
  a second identity to keep in step.
- **A withdrawn JobStream ad arrives with `id` set and every other field null.**
  Feeding one through the normal upsert leaves the row and wipes its title,
  employer and description — still counted, no longer readable, nothing
  announced. Withdrawals take a separate path touching only `removed_at`. They
  are the majority of a poll: 2,826 of 5,053 changes on the first run.
- **JobStream's cursor is `timestamp`, epoch milliseconds** — not
  `publication_date`. Resume rewound by a few minutes, because a duplicate
  costs an idempotent upsert and a gap costs a posting.
- **An ATS board often lives on the firm's own hostname, and every host
  pattern misses it.** `careers.lynxhedge.se` is Lynx Asset Management,
  `jobs.swedbank.com` is Swedbank — Teamtailor boards that never spell
  `{board}.teamtailor.com` anywhere on the page, so both tiered B with a live
  feed behind them. The vendor's asset CDN is still in the markup and the
  custom host is the token. **Verify it**: the CDN proves the firm *uses*
  Teamtailor, not where its board lives, and the first three domains matched
  this way — 3stepit, Enfuce, Infovista — all 404'd on `/jobs.rss`.
- **Tier A with a NULL token is a board nobody can poll, and a tier-B sweep
  never touches it.** 98 rows sat in that state, `lynxhedge.se` among them.
  When re-probing for a fingerprinting fix, clear tier A with no token too.
- **The careers walk must try every candidate and go two hops.** The loop used
  to `return` tier B on the first readable careers page, so candidates two and
  three were fetched by nobody; and Swedbank's board is a link *off* its
  careers page. Six fetches per domain is the ceiling.
- **A registry's own website field can be malformed, and two guards can each
  assume the other caught it.** AFM publishes `http//www.optiver.com` — no
  colon — for 68 firms, Optiver and IMC Trading among them. `domain_of`
  returned None, so the harvester skipped them for having no parseable website
  *and* `targets` excluded them for having one. `domains` reported "nothing
  left to probe" while they had never been looked at.
- **A careers page can link to a board that is not the firm's.**
  `palmersquare.com` linked to `jobs.lever.co/heyrowan` — syndicated content
  with a Google `srsltid` parameter still attached — and the feed delivered 90
  jewellery-retail postings under a credit manager's domain. Well-formed token,
  real ATS, live feed, wrong company. Read the postings, not just the token.
- **A page-count guard is a silent cap on the boards that matter most.** The
  Workday reader stopped after 40 pages "as a guard against a broken stop
  condition", and LSEG and State Street both came back at exactly **800**
  postings — State Street really has 1,295. A round number in the output is
  what a cap looks like from the outside, and nothing said so. The bound is
  1,000 pages now, paging stops on a short page *or* one that repeats the
  previous (a tenant ignoring `offset` serves page one forever), and both are
  tested. Whenever a per-board count is suspiciously round, suspect our guard
  before their register.
- **A regex over fetched markup is a denial-of-service waiting to happen, and
  it fails as a *stall*, not an error.** Two `ats` runs sat at 100% CPU for two
  and a half hours, wrote nothing, and looked exactly like slow network. Two
  causes, both quadratic: `[^"']*(?:career|jobs|…)[^"']*` over an href that
  never closes, and `([a-z0-9-]+)\.host\.com` over an inline base64 data URI,
  which is a long run of label characters containing no dot. Extract hrefs with
  a bounded pattern and match words in Python; bound every host label to 63
  characters and prefix it with `(?<![a-z0-9-])` so a label cannot start
  mid-label. `tests/test_ats.py` times both. Cap fetched markup too — 23
  patterns over an unbounded body blocks every other thread through the GIL.
- **Fingerprinting an ATS and reading it are separate capabilities, and the gap
  is silent.** `ats.py` recognised 22 systems while `extract.py` read 11, so 88
  boards sat tier A with a token, counted as resolved everywhere, polling
  nothing. Whenever a host pattern is added, check `extract.EXTRACTORS` has a
  matching key — `tests/test_icims.py` pins the registration for exactly this.
- **A vendor's asset URL is the evidence when a firm fronts the board on its own
  hostname.** `careers.sig.com` names its board nowhere; the only occurrence of
  `sig` in the markup is `cookie-policy-scripts.icims.com/sig/…`, the cookie
  banner's script path. Worth 237 postings, and the same shape as the Teamtailor
  CDN rule — expect it wherever a careers page tiers B with a live feed behind it.
- **A board page serving a dead end does not mean there is no feed.** Varbi's
  `/{lang}/what:list/` answers *404 Unallowed call* for every language, and
  Homerun's board is script-rendered and links out to the firm's own host
  (`jobs.tiqets.work`). Both publish a feed — `/what:rssfeed/` on the Varbi
  host, `feed.homerun.co/{token}` — and both carry the description the board
  page does not. Read the page's own link shapes before concluding a vendor has
  no feed; guessing paths found neither.
- **A trailing slash was a silent 50-posting cap.** Jobvite pages at
  `/{token}/search/?p=1`; `/{token}/search?p=1` — no slash — serves the first
  page while looking like it paged, so `?p=2` returning nothing read as "there
  is no second page". Sikich's own pagination text says `1-50 of 73`, which is
  the check: the board states its own size, so compare against it.
- **Taleo needs a per-board portal id and does not publish one.** `POST
  /careersection/rest/jobboard/searchjobs` is the right shape — it answers with
  `requisitionList` and `pagingData` — but without the right `portal=` it
  returns `careerSectionUnAvailable: true`, and the section page is a 1,534-byte
  redirect stub. Eightfold's `/api/apply/v2/jobs` returns the page *config*
  rather than postings, and Join 422s on every `page`/`pageSize` value tried.
- **iCIMS has no feed.** The vendor's `format=rss` 302s to a staff login page,
  so the portal HTML is the only public surface. Job links are
  `/jobs/{id}/{slug}/job`, `pr` pages 50 at a time, and the list page carries
  **no anchor text** — the slug is the title, which loses casing and `c++`.
  Stop paging when a page adds no *new* id: a portal ignoring `pr` serves page
  one forever and never returns an empty page.
- **The infrastructure-token list is an *all-pieces* rule, and that is only
  half right.** It must be, or `jane-street` and `da-vinci` get thrown away. But
  `jobs.jobvite.com/__assets__` was recorded as a board against three unrelated
  firms at once — `assets` was already on the list and only the underscores hid
  it — and `vs-errors.eightfold.ai` passed because `vs` means nothing while
  `errors` is the vendor's host. Split on `_` as well as `-`, and check the
  unambiguous words (`assets`, `cdn`, `errors`, `sentry`, `staging`) with *any*
  rather than *all*.
- **ATS board tokens are easy to extract wrongly, and the wrong answer looks
  right.** `boards-api.greenhouse.io/v1/boards/{token}` puts an API version
  before the board, so matching the host alone yields `v1` for every Greenhouse
  user; `www.teamtailor.com` fits the `{board}.teamtailor.com` shape and yields
  `www`. `ats.py` filters both against a list of infrastructure hostnames.
  Always read the first handful of tokens before trusting a batch.
- **A board URL escaped inside a JSON island matches no host pattern.** Julius
  Baer ships its navigation as JSON inside an HTML attribute, so its Workday
  board arrives as
  `&quot;https:\/\/juliusbaer.wd3.myworkdayjobs.com\/en-US\/External&quot;`
  — neither the slashes nor the quotes are what the pattern expects, and a
  Switzerland roster firm sat in tier B with a live feed behind it. `fingerprint`
  unescapes before matching. On a random tier-B sample that rescues 1 page in
  400 and the number is not the argument: tier B at large is wealth advisers
  with WordPress sites, and among the tier-B *roster* firms it rescued one in
  ten. Pick the frame before believing a yield.
- **A social profile is not a careers page, and it out-ranks the real one.**
  `careers_candidates` ranks off-site links first — an off-site careers link is
  usually the ATS itself — so a firm linking "Jobs" to LinkedIn or "werken bij"
  to Instagram puts a platform URL at the top, and only three candidates are
  ever fetched. `handelsbanken.se` and `pggm.nl` both resolved that way; 53
  domains tiered B on a social page. `resolve.is_platform_domain` is the answer
  here as in the three layers it already guards.
- **Oracle Fusion's board token is `podhost|siteNumber`, and neither half works
  alone.** The pod host (`ejqi.fa.ocs.oraclecloud.eu`) is the customer's own
  Fusion instance, and `CX_1001` is Oracle's default site number that most
  tenants keep — so a token of the site collides across every firm on the
  platform. `TotalJobsCount` is honest on every page, including one past the
  end, so Oracle has no `total: 0` trap; it is still used as a *check* against
  what arrived rather than as the stop condition, which is the rule that caught
  Jobvite's missing slash.
- **`tbe.taleo.net` is Taleo Business Edition, a host every small tenant
  shares.** `varde.com` and `hanoverco.com` both resolved to the board `tbe`
  and `uhgcu.org` to `baxter` — a token several unrelated domains agree on is
  the vendor's infrastructure, which is the signal `_NOT_A_TOKEN` exists for.
  Taleo is unreadable *and* mis-tokenised; treat its 11 rows as unresolved.
- **SuccessFactors puts the board in the query string, not the host.** 59
  boards carry `career{N}.successfactors.{eu,com}` with a NULL token because
  the company is `?company=pfapensionP`. Reading it is a dead end regardless:
  the career site answers 206 KB of shell with no job id, with or without a
  session and its `_s.crb` token, and the vendor's RSS path 404s. PFA and Swiss
  Re are here.
- **Guessing careers paths rescues tier C into tier B and no further.** 150
  tier-C domains re-walked with `/careers`, `/jobb`, `/karriere` and the rest:
  23 became readable pages, **none fingerprinted to any ATS**. Same answer
  Stage 13 got about tier B — that population has no board, and the firms that
  matter are reached by `discover`.
- **Some roster firms run no ATS at all, and Stockholm is where that shows.**
  `audit --pipeline` put Stockholm at 7/20 and hand-probing the misses found
  AP4 publishing five openings as ordinary links, AP7 four as bolded titles
  linking out to two different recruiters, Brummer one as a paragraph, and
  Nordea 112 through a JSON endpoint on its own domain. There is no vendor to
  fingerprint. `sites.py` is the answer and is deliberately a short list: each
  reader rides Layer 3 as `ats='site'`, and each **raises** rather than
  returning `[]` when the anchor it keys on is missing, because an empty board
  and a broken parser are opposite facts that look identical from outside.
- **A firm that advertises nothing says so, and that sentence is the anchor.**
  Captor and Norron have no board -- one line saying there are no vacancies and
  an email address. A reader returning `[]` for them would be indistinguishable
  from one whose page had been redesigned underneath it, so `_prose_board`
  requires *either* a posting *or* the no-vacancies phrase.
- **A hand-edited careers page has no house style.** AP7 writes three of its
  four openings as `<a><strong>Title</strong></a>` and the fourth as
  `<strong><a>Title</a></strong>` -- and the fourth is the Senior Portfolio
  Manager, Asset Allocation seat. One nesting cost the most relevant row on the
  page.
- **`sjunde.se` is not AP7.** It is *Sjunde Konsultbolaget*, a Stockholm IT
  consultancy, and it resolved on a weak name match while `fi_se` publishes no
  website for the fund. `discover._domain_for` asked only that a domain be
  non-NULL, so a weak row on the roster's spelling beat a registry-published
  one on the full name. It prefers non-weak now over both sources before
  falling back -- *excluding* weak outright was tried and is worse, because
  Coeli resolves to `coeli.com` weakly and by no other route.
- **Two roster firms had ceased to exist.** AP1 and AP6 were both wound up at
  the end of 2025 by riksdag decision (`ap1.se`: "AP1:s verksamhet upphörde vid
  utgången av 2025"; `ap6.se`: "Sjätte AP-fondens verksamhet upphörde"), and
  their domains now serve AP4's and AP2's sites. A roster line that names a
  dead firm is a permanent miss nobody can close -- check the page before
  building a reader for it.
- **Some boards name the firm only in the location field.** Hailey HR labels
  every card with a *workplace*, so Coeli's eight postings say `Coeli Stockholm
  HK` and name the firm nowhere else -- titles are ordinary, bodies are Swedish
  prose. `discover.corroboration_text` reads location for this reason; the URL
  is still never read, because a guessed board carries the guess in every link.
- **Entities were never decoded, and HTML-sourced formats carry them.** Coeli's
  `Business &amp; Risk Operations` folded to the token `amp`; Swedish spells
  `ä` as `&#xE4;`, which would fold to nothing a needle matches. `extract._text`
  runs `html.unescape` now -- same class of silent damage as the `fold` bug.
- **Handelsbanken publishes its Swedish jobs on LinkedIn only.** Its careers
  page links there and nowhere else; the `careers.handelsbanken.co.uk` API its
  own bundle names is the **UK** board (46 jobs, all UK). A structural limit,
  not a gap -- LinkedIn is deliberately out of scope.
- **Which ATS to build next is a measurable question, not a guess.** 1,400
  tier-B careers pages were swept for third-party *hiring* hosts we do not
  recognise, ranked by how many distinct firms each would rescue: ADP 19,
  Paylocity 18, Radancy 12, Rippling 11, Phenom 7, UKG 5, HiBob 5, Talentsoft
  4, Avature 3, JazzHR 3, Dayforce 3, Zoho 3, Cornerstone 2. Build down that
  list, not down a list of vendors you have heard of.
- **ADP's `meta.links` looks like a location map and is a filter facet.** It
  pairs an id with a readable place — "Hong Kong - Wanchai, HK" — and joining
  it to the requisition's `itemID` yields a confident location for every
  posting while matching nothing: those are *location* ids, the places you may
  search by. The real location is on the requisition and is coarse, often just
  a country. A wrong location is worse than none because the board gates on
  geography; `unknown` survives the gate and a wrong city does not.
- **Paylocity, Rippling and Phenom render their lists client-side** — Paylocity
  ships a `public-site-react-list` bundle and the 41 "job ids" a naive count
  finds in its HTML are analytics and CSS. Recorded as investigated. ADP and
  UKG (formerly UltiPro) both answer with clean JSON and are read; UKG's token
  is `code|boardGuid`, the same both-halves-required shape as Oracle.
- **`tests/test_oracle_hcm.EveryFingerprintHasAReaderTest` is the exhaustiveness
  guard.** Every name in `ATS_PATTERNS` must be in `extract.EXTRACTORS` or
  listed in that test's `INVESTIGATED` map with the reason there is no reader.
  Adding a pattern without a reader now fails the suite instead of quietly
  parking boards in tier A, which is how 88 of them once sat resolved and
  polling nothing.
- **Naming the firm is necessary and not sufficient.** `athoscap.com` prints
  "Athos Capital" on the page and passes the spaced-phrase rule — and it is
  *Athos Capital Partners*, a real-estate private equity firm, not the Hong
  Kong hedge fund Athos Capital Limited. Same trap as `citadel.com` matching
  Citadel Securities. When a firm name is two common words, read the title
  before recording the domain.
- **A merged firm can inherit a social page as its website, and that field is
  load-bearing.** `resolve._best` picks the most common value among a group's
  rows, so Two Sigma's `firms.website` came out `https://x.com/twosigma` while
  the seed registry carried `twosigma.com` for the same firm.
  `harvest_registry_domains` seeds `domain_lookups` from that field,
  `discover._domain_for` reads that, and the board is attached to a host
  thousands of firms claim — or to nothing, once the platform guard rejects it.
  `_best_website` prefers any real domain the group holds. Fourth layer
  `is_platform_domain` has had to guard.
- **A verified board with no domain polls nowhere.** `ats_resolution` is keyed
  on the domain, so `discover.record` silently drops a proved board when the
  firm has none — Akuna, Voleon, Belvedere and Quadrature, 113 postings between
  them. Voleon and Quadrature publish a LinkedIn page as their Form ADV
  website; Akuna's only name match in the universe was `Hakuna GmbH`. The seed
  registry is the route, the same one AP7 needed.
- **Most small Hong Kong funds run no public board at all**, and this is a
  finding rather than a gap. All 51 roster firms were probed by name across
  every discoverable ATS; the sweep found two — Eclipse Trading and Quantbot
  Technologies. The rest hire through recruiters and personal networks, which
  no scraper reaches. Expect the HK rate to sit far below Stockholm's for
  structural reasons, not for want of effort.
- **A one-word firm name is always a *strong* needle, and that is the last
  hole in board discovery.** `bamboohr/blackrock` is BlackRock **Asphalt** of
  Tampa — Asphalt Laborer, Lowboy Driver, Milling Machine Operator — and its
  postings contain "blackrock" because that is genuinely the company's name.
  No text rule separates it from BlackRock the asset manager, so
  `discover._reads_as_another_industry` reads the postings with
  `lexicon.judge` instead and rejects a one-word match when *every* posting is
  an unrelated occupation or carries no signal at all. Both halves are load
  bearing: requiring a `keep` throws away Coeli (eight ordinary
  asset-management titles, one of which rejects on `chef`, Swedish for
  *manager*), and requiring merely "some rejection" keeps the asphalt board. A
  narrower rule was tried first — reject when the word is always followed by
  the same next word — and it failed both ways, because Coeli's location chip
  is always "Coeli Stockholm".
- **A three-letter alias will find a fund, not the firm.** The roster already
  warned about a bare `Nasdaq`; a bare `AQR` matched *LUMYNA – AQR GLOBAL
  RELATIVE VALUE UCITS FUND* and put AQR's board on `lumyna.com`, a UCITS
  platform hosting other managers' strategies. Marshall Wace landed on the same
  host for the same reason. When adding an alias, check what it matches before
  trusting it.
- **A 401 can be our own URL, and it cost this project a source for months.**
  job-room.ch was recorded as blocked on a registered API programme on the
  strength of a 401 from `/api/jobadservice/api/jobAdvertisements/_search` --
  one `/api/` too many. The real path is `/jobadservice/api/...`, it is what
  the public site itself calls, and it answers a bare unauthenticated POST with
  full postings. Read the site's own network traffic before believing an auth
  wall. The registered API that wants an email is real and is a *different*
  thing: it lets an employer manage its **own** postings and no read endpoint
  on it returns the register, so the key would not have helped.
- **`X-Total-Count` is not `x-total-count`, and the guard it feeds went silent.**
  HTTP/2 normalises header names to lowercase and HTTP/1.1 sends whatever the
  server typed, so a case-sensitive lookup found nothing, the advertised total
  read as **0**, and `jobroom_ch`'s truncation check -- whose entire job is
  comparing collected against advertised -- passed a walk that had stopped dead
  on the result window at a suspiciously round 10,000. `http._send` lowercases
  header names for this reason. The deeper lesson is the guard's, not the
  header's: **a check whose evidence is missing must fail, not pass.** A
  missing total is now a problem in its own right.
- **job-room.ch's `Link` header advertises a last page that 412s.** With
  `size=1` it offers `rel="last"` at page 80,459; any request whose
  `page * size` reaches **10,000** returns HTTP 412. Elasticsearch's
  `max_result_window`, and the same trap as MyCareersFuture's 418 one country
  over. The fix that works without a partition is a **two-ended walk**:
  `sort=date_asc` is the exact reverse of `date_desc` (verified over a whole
  canton -- same set, precisely reversed), so reading the first 10,000 forwards
  and the last `T - 10,000` backwards covers any slice up to 20,000. Proved on
  a live poll: 12,033 advertised, 12,033 collected, 967 overlapping in the
  middle, where a single-ended walk returns exactly 10,000 and reports success.
- **Swiss cantons are not a partition, and two separate things break it.** They
  sum to 78,355 against a total of 80,460: `FL` (Liechtenstein) is a 27th code
  no list of Swiss cantons contains, and ~2,100 postings carry **no canton at
  all**, which no value of the filter can reach. Same shape as MCF's missing
  `Telecommunications` except the gap is somewhere a better-spelled list cannot
  close. Measure a partition against the unfiltered total before trusting it.
- **A publication window is not an application deadline.** job-room.ch sets
  `publication.endDate` on every ad and it is tempting, because the board pins
  an approaching deadline above everything else. Measured: **81% sit exactly 30
  days after the start date and 12.8% exactly 60** -- two round defaults, which
  is a "how long should this run?" dropdown, not a date an employer chose. It
  is when the *advertisement* stops being displayed. Writing it would hand
  ~80,000 Swiss postings a fabricated deadline that outranks every posting
  publishing a real one. JobStream remains the only source with a true one.
- **A published "company website" is often the recruiter's, and one flag tells
  them apart.** On job-room.ch the field is present on 19% of ads and the top
  six domains are all staffing agencies -- MediPersonal, fachkraft.ch,
  stellentreff.ch. `company.surrogate` marks an agency standing in for an
  employer it does not name, and **372 of 379 websites in a 2,000-ad sample
  came from surrogate rows**; the seven that did not are `post.ch` and
  `pfister.ch`, the real employers. Record a domain only from a non-surrogate
  company: 0.3% of rows, every one correct, against 19% that would file
  postings under firms that never advertised them.
- **A few large firms simply refuse us**, and it is not our trust store this
  time: ABN AMRO answers 503, Nasdaq times out, Citadel Securities and Jyske
  Bank answer 403. `curl` with a browser UA reaches all four. Recorded as a
  structural limit rather than chased.
- **Jobindex (DK) publishes its own result window, and the answer to it is to
  partition rather than to shrug.** Every search page carries `hitcount` and
  `max_page: 50`, so no query yields more than 1,000 postings and page 51 is a
  404 -- loud, unlike Workday's `total: 0`. The board is enumerated through its
  own 81-subcategory taxonomy (measured: 200 of 200 sampled postings carry at
  least one), and the four slices bigger than the window are **split again**
  rather than truncated. Retail, childcare, care and hospitality are exactly
  the four, and "the tagger gates those anyway" is the write-time filtering
  principle 4 forbids -- a posting dropped at ingest cannot be recovered by
  re-running a classifier.
- **A split dimension is only a cover if the site publishes an "unspecified"
  bucket for it.** `workinghours_type`, `employment_type` and `employment_place`
  each have one (`-1`, `-1`, and "Vis uden denne information"), which is what
  makes them safe to cut a slice along; without it every ad that left the field
  blank is dropped and nothing says so. Measured on all four overflowing
  slices, the parts sum to *at least* the whole every time -- 2,105 against
  1,846 for Pædagog, the excess being ads offered as either full or part time.
  The obvious partition, publication date, is closed: `jobage=archive` answers
  HTTP 401 anonymously.
- **Jobindex prints two dates on every posting and only one is a deadline.**
  `apply_deadline` is the employer's stated closing date and is set on about
  half the rows; `lastdate` is when the *advertisement* comes down and is set
  on all of them. They are distinguishable because the board says so --
  `apply_deadline_asap` marks the other half as *snarest muligt*. Reading
  `lastdate` would hand a deadline-first board 17,000 confident dates nobody
  promised, which is the `GRASSHOPPER ESCAPEMENT` asymmetry again.
- **A national board's search results can carry the employer's own website,
  and Jobindex's does.** `company.homeurl` resolves on 486 of 561 postings in a
  two-category sample -- a live bridge into `firms` that JobStream manages for
  half its ads and MyCareersFuture not at all. It still goes through
  `resolve.is_platform_domain`; that is the fifth layer needing the guard.
- **Jobindex writes a postcode and a town, never the city, and that gap gated
  1,444 Copenhagen postings off the board.** The `area` field is `2650
  Hvidovre`, so the `copenhagen` needle `kobenhavn` never fired and the rows
  read as `other` — "we looked, and it was somewhere else". More than half the
  Danish corpus landed there, 9,449 postings, every one of them in Denmark.
  Whenever a new source lands, bucket its `hub` values before believing the
  board: `other` filling up is what a place-list gap looks like from outside.
- **A leading four-digit number is a postcode in Denmark and a street number in
  North America.** The tempting fix above is to read `^\d{4}` as a postcode and
  map 1000–2999 to Copenhagen. Measured over all 187,960 postings, that claims
  **225 US and Canadian street addresses as Copenhagen** — `2005 Market Street,
  Philadelphia`, `1966 Yonge Street, Toronto` — and Copenhagen is a focus hub,
  so those go *on* the board. Tightening it to "postcode plus a town, no
  commas" still keeps 26 of them (`2925 VIRTUAL WAY:VANCOUVER`). The names went
  in a list instead, each dry-run over the corpus, which is what the Stockholm
  and Amsterdam belts already did.
- **Danish occupation words are caught by nothing in `tagging.py`.** The
  needle lists are English and Swedish, and Danish is close enough to look
  covered and far enough not to be: `sygeplejerske`, `pædagog`, `lærer` and
  `rengøring` match no Swedish needle. This is why the Jobindex gate is the
  board's own taxonomy and not a word list -- the same argument JobStream's
  `occupation_field` makes, with more riding on it.
- **A source that collected nothing looks exactly like a source nobody asked
  about.** job-room.ch was built, guarded and proved against a live portal, and
  `jobs` held **not one Swiss row** — 187,960 postings, none of them from it,
  and `feed_state` carrying only JobStream's cursor. Every report in this
  pipeline is per source, so a source with no rows simply does not appear.
  `alerts` is the thing whose job is noticing silence and it reads the `runs`
  table, which none of the Layer 4 pollers writes to. Check `SELECT ats,
  COUNT(*) FROM jobs GROUP BY ats` against the list of modules before believing
  a stage is live.
- **A short page is not the end of a board, and only a floor caught it.**
  Jobbsafari's first live sweep reported **5,421 postings, cleanly** — page 11
  had returned 499 rows instead of the 500 asked for, an advertisement
  withdrawn between the count and the render, and the walk read that as the
  last page. 43,000 postings were missing and the arithmetic looked perfect,
  because a short page is exactly what the *real* last page looks like too.
  Stop on an **empty** page, and check what arrived against the total the board
  publishes. `MIN_EXPECTED` is what actually announced it.
- **A place name folds into somebody else's word, and the dry-run is the only
  thing that finds it.** Sweden's 315 municipalities went in as hub needles and
  seven had to come straight back out: **`Åre` folds to `are`, the ISO code for
  the United Arab Emirates, and reaches 83 Workday postings in Dubai and Abu
  Dhabi**; `Vara` is Dubai's virtual-asset regulator; `Eda` is electronic
  design automation; `Sala` is a Venetian waiter (*Commis di Sala*); `Malå` is
  Sichuan food; `Mark` is Singapore's Green Mark; `Salem` is Oregon. Take the
  candidate list from the *source's own* taxonomy — anything it does not carry
  is not that country, which is what kept `Island`, `Bangalore` and `Paris` out
  of the Swedish list even though a Swedish board advertises all three.
- **A national board writes the *administrative* place, and each country picks
  a different one.** Jobindex writes a postcode and a town (`2650 Hvidovre`),
  Jobbsafari writes a municipality (`Ludvika`), and job-room.ch writes a town
  and a **canton code** (`Wallisellen, ZH`) -- so each of the three landed with
  most of its corpus in `hub: other`, which the board gates. Switzerland was
  the loudest: **18,562 of 22,946 postings in a focus hub** read as somewhere
  they are not. The handle is the source's own administrative unit, matched
  against the **location alone** for the same reason US state codes are: `SO`,
  `BE`, `AG`, `UR` and `GE` are ordinary words in a title. Three cantons are
  deliberately absent -- `AR`, `NE` and `FL` are also Arkansas, Nebraska and
  Florida, both readings are live here, and a false hit in a focus hub is worse
  than a false miss.
- **A word can be the asset class and the kitchen.** `råvaror` is Swedish for
  commodities and Swedish for raw ingredients: it matches 49 bodies and every
  one is a cook's posting. It is not in `_ASSET_CLASS`, and bare `handel` is
  not in `role_class` either — it is *commerce* (e-handel, detaljhandel) and
  names a shop as often as a desk. The Nordic markets words that survive are
  the compounds.
- **Swedish and Danish inflect the occupational head, so the singular needle
  cannot see the plural.** `underskoterska` was a needle while
  `Undersköterskor` sat on the board 269 times, and `_TRADE_HEADS` missed
  `dackmontorer`, `taxichaufforer` and `maskinoperatorer` for the same reason.
  Two more shapes leak with it: the **workplace** where it is the only thing
  naming the profession (`äldreboende`, `hemtjänsten`, `ungdomsboende`), and
  the **assignment** where nothing else does — 33 postings headed *Veteraner
  till städuppdrag!* carry no occupation word at all.
- **Five Nordic compound heads are the `-arbetare` mistake in a new language,**
  and `_NOT_A_TRADE_HEAD` records them: `-arbejder` is *medarbejder*
  ("employee", 1,711 titles), `-medhjaelper` and `-hjaelper` are
  *studentermedhjælper* and half of those are IT and data work, `-vagt` is
  *aftenvagt* and *nattevagt* — shifts, not security guards — and
  `-assistenter` is *Forskningsassistenter*, which is why the singular went
  years ago.
- **`vikarie` is a contract, not a profession**, and gating on it would delete
  a temporary quant seat on evidence about its duration. Same shape as
  `student_intern` leaving the seniority ladder. It is `contract: fixed_term`.
- **`heavy_systems` is the one exclusion that reads differently in a title and
  a body, and both halves are load-bearing.** In a *body* it must not reject:
  `fpga` appearing in a paragraph about the stack was removing 295 postings,
  `Senior Software Engineer, C++` at Flow Traders and `Low-Latency Engineer` at
  **Jane Street** among them. In a *title* it must: `Junior FPGA Engineer` at
  Eagle Seven is a hand-labelled rejection whose note reads "electronics work".
  Excluding the category outright fixed the first and broke the second. The
  filter that builds `rejecting` and the one that builds `hard` are different
  lists for this reason -- check both when either changes.
- **A needle can pass the stated test and still be wrong to add.** `-ingenjör`
  reaches 926 Swedish and 46 Danish compounds — *Automationsingenjör*,
  *Processingenjör*, *Byggingenjör* — and touches no positively-rated posting,
  which is the check every other gate needle is held to. It is out anyway,
  because the same suffix reaches *Softwareingeniør*, and `software engineer`
  and `developer` are deliberately absent from `_SOFTWARE_SPECIALTY` because a
  quant-dev posting calls itself one. What it would have removed is 972 rows
  already sitting at `relevance: unknown`, which rank last: **a gate that could
  delete a wanted posting is worse than a page with a scroll on it.** When the
  measurement says yes and the principle says no, the principle is the one that
  was written down first.
- **The Nordic quant vocabulary has almost no signal, because the Nordic quant
  postings are written in English.** Measured over every live title and all
  126,983 bodies: `obligationer` 1, `renter` 0, `volatilitet` 0,
  `algoritmisk handel` 0, `modellvalidering` 0. Translating the *negative* half
  — the occupation words — is what moves a Nordic board; translating the
  positive half is insurance.
- **`hub` is multi-valued, and a country bucket is a complement rather than a
  second place.** A posting open in Amsterdam and London carries a row for
  each, and `off_location` fires only when none of them is somewhere the reader
  would go. But `sweden_other` means "in Sweden and *not* Stockholm", and
  Jobbsafari writes `Stockholm, Sverige` for a regional Stockholm ad — so a
  residual is dropped when **every needle it matched was the country's own
  name**. Collapsing on the bucket instead throws `Copenhagen, Aarhus`'s second
  city away, which is the multi-location bug arriving by the back door.
- **A scalar subquery over a multi-valued dimension picks a row at random.**
  Three places read `hub` that way (`tagging.search`, `tagging.shortlist`,
  `labels._candidates`) and all three had to become `group_concat`.
  `shortlist`'s copy was also unpinned to a lexicon version, so it summed every
  retired tagger as well — two bugs in one line, and the second one is the
  standing warning in this file.
- **`lexicon.board_profile` is implemented, tested and wired to nothing.** It
  measures whether a board is a markets employer from what it actually
  publishes, which is the firm-level signal the hand-labelled notes keep
  reaching for ("nothing to do with finance", "non finance company"). Before
  adding a new rule for that, check whether this is the rule.
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

**But the title decides what the role *is*, and the body decides everything
else.** That rule is about *inclusion*: a title carrying no signal must fall
through to the body, and it does. Scoring relevance *over* the body made
`Insurance Accounting & Reporting Specialist` a core quant role three times
over, because "strong quantitative skills" is boilerplate and every bank's
about-us names market and credit risk. Seniority is the same: a body saying
"you will report to the Head of Trading" made `Graduate Trader` a `head_or_md`
posting. The body reaches rank through **two** doors only: an explicit years
figure, which states the posting's own bar rather than describing somebody
else's rank, and `student_intern`, read from the body first,
because no title announces "must be graduating in 2028".

**`job_tags` does not actually keep retired lexicon versions, and the docs say
it does.** The primary key is `(ats, token, job_id, dimension, value)` with
**no `tagger` column in it**, so `INSERT OR REPLACE` overwrites the previous
version's row whenever a posting keeps the same value in the same dimension.
Only rows whose value *changed* survive, which is the opposite of a diff.
Measured: lexicon 15 has been erased outright and 16 retains 67,870 of the
1,065,834 rows it wrote. Adding `tagger` to the key fixes it going forward; the
history already lost cannot be recovered. Until then, treat "compare two
taggers" as unavailable rather than merely unused.

**Tag counts must still pin the lexicon version.** An unpinned `COUNT(*)` sums
whatever survives of every version —
the hub table read 49,808 postings in `unknown` after `unknown` had already
been split out, because six earlier taggers still said so.

**Changing the lexicon without bumping `TAGGER` leaves stale tags that look
current.** `tag` only visits postings with no row at the *current* version, so
after an unbumped edit it reports `tagged 0 postings` and every summary keeps
serving the old lexicon's answers. Bump, then re-run; the old version stays for
diffing, which is what it is there for.

**A title-only rule is not implemented until the fall-through is closed too.**
"The rank is in the title" was written down, tested, and then quietly undone by
`_first(_SENIORITY, title) or _first(_SENIORITY, text)` — whenever a title
carried no grade word, the body decided after all, and in a body every
authority word is furniture. A `partner` in Schonfeld's diversity paragraph
made an internship a `head_or_md` posting and moved it out of the shortlist.
The body now reaches rank through two named doors only: the student gate and an
explicit years figure.

**Boilerplate is the default failure mode of any body-matched rule.** Two more
of the same shape, both caught by reading three postings by hand: exclusions
fired `support_function` on "maintain strong stakeholder communications", and
asset class read `rates` off the firm's own "we invest across Quant, Tactical,
Fundamental Equity and Fixed Income" paragraph. Match the title; fall back to
the body only for words no posting uses in passing, and grade the fallback
`weak`.

**`Ph.D.` is two tokens.** It folds to `ph d`, so every needle spelled `phd`
missed the majority of postings that punctuate it. Fold it to one word before
matching — and check the negation, because " no phd required " contains
" phd required ".

**A fixture drawn from the top of the shortlist can only find false
positives.** `list` sorts by fit, so labelling its first hundred rows measures
the tagger against the rows it already likes — while the exit criterion is *no
false rejection*. `sample` hides the tagger's verdict, and scatters the rows,
because writing the draw in bucket order leaks that verdict through position
just as plainly as a column would.

**But stratifying over the whole corpus is the opposite mistake, and it wasted
the reader's first seven rows.** 30% `out_of_scope` across 69,961 postings is
housekeepers, van drivers and dental nurses; the notes came back *"totally
irrelevant"*, *"nothing to do with finance"*. **A false rejection can only hide
among postings that could plausibly be in scope.** `labels._candidates` draws
from a frame of ~2,000 instead — live with a URL, not `off_industry`, English
or Swedish, and carrying an actual markets or quant word — stratified over
`lexicon.judge`'s verdicts, with `unrelated_occupation` and `corporate_function`
never put to a human at all.

**`judge` returning `undecided` is not evidence of anything.** It is the
default for a title matching no list, which in this corpus is `Regional Sales
Manager` and `Field Service Delivery` by the thousand. Require a real anchor
before treating an `undecided` as a near miss.

**`lexicon.judge` is the last word on relevance, and it must stay last.** It
carries the long occupation lists — wealth advisers, counsel, named trades —
while `_EXCLUSION` in `tagging.py` carries seven categories, so a `Wealth
Advisor` fell through both and was reported `unknown`: "nothing looked at
this", when three rules had. It runs only on the branch that would otherwise
emit `unknown`, so it can convert a non-answer and can never overturn a
positive — which is what stops it manufacturing a false rejection in the rows
that matter. It also costs ~0.1 ms per posting.

**A department is nothing but the desk's name, so it must never reject the
role.** `Senior Trading Associate` sits in a department called *Trading
Operations* and the desk-support rule read title and department together — so
the desk's name rejected a seat on the desk. That was the first false rejection
the hand-labelled fixture found, which is exactly what it exists for. Desk
support is read from the **job title alone**.

**A management title outranks a weak positive, the same way an exclusion
does.** `Director of Trading`, `Head of Managed Accounts`, `Applied Science
Leader` and `Product Manager - B2C Credit` all reached `adjacent` on one
ordinary word — *trading*, *data science*, *model validation* — while what the
title announces is that somebody else does the work. An unambiguous quant word
still wins, so `Head of Quantitative Research` stays `relevant` and its
seniority is what says it is out of reach. `associate director` is guarded:
a bank stamps it on a five-year hire.

**Investing by judgement is not quant work, and the lexicon had it as a
positive.** `investment analyst` and `portfolio analyst` were weak positives
while the hand-labelled sheet rejected nine such rows in a row — `Senior
Investment Analyst`, `Portfolio Associate`, `Asset Management Analyst`,
`Partner, Private Equity`. They are an exclusion now, matched on the title and
read after the core check, so `Quantitative Analyst, Private Equity` keeps its
quant reading. The qualifier is the whole difference, as with `Credit Risk
Operations`.

**A weak positive needs a markets word beside it — the test is two-sided.**
`judge` already reasoned this way about engineering titles and nothing else
did, so a `Computational Chemist` whose body says "model validation" once, a
`Thermal - Fluids Analyst` and a `Cloud Engineer` all came back as quant work.
`Data Scientist` is a quant hire at a systematic fund and a growth-analytics
hire at a payments company, and this corpus holds both. No markets anchor, no
positive — the posting falls through to `judge` instead.

**One quant phrase in a body is not a quant role.** `Data Management Analyst —
Data Governance` says "model validation" once, the way every governance
document does, and came back as research work. A body-only reading now needs a
second distinct phrase before it can reach `relevant` — the same corroboration
rule `domains.py` uses one layer down, for the same reason.

**But counting phrases is the wrong rule, and only a dry-run showed it.**
`Thermal - Fluids Analyst` carries *model validation* **and** *numerical
methods*; a payments company's `Data Scientist` carries *time series* **and**
*statistical modelling*. Two distinct phrases each, neither anywhere near
markets, both rejected by hand. **The quantitative *method* vocabulary belongs
to every technical field and the markets vocabulary does not** — `monte carlo`
is derivatives pricing at a bank and radiation shielding at a reactor,
`backtests` is alpha research at a fund and demand forecasting at a retailer.
So `lexicon` splits its body list in two: `QUANT_MARKETS_BODY` names markets
activity and carries a body alone, `QUANT_METHOD_BODY` needs a markets anchor
beside it. 103 postings moved, 85 distinct titles, hand-read in full — a
radiation-shielding engineer kept by *monte carlo*, a robotaxi tech lead by
*time series*, and a **garage-door salesman by *options pricing***.

Which bucket a phrase goes in is asymmetric, so put the doubtful ones in the
method bucket: a wrong entry there costs nothing unless the posting mentions
markets nowhere at all, which no genuine quant advertisement manages. A wrong
entry in the markets bucket costs a false keep. `quantitative finance` reads
like the strongest phrase on the list and sits in the method bucket, because
TF Bank's core-ledger posting carries it.

**A bare adjective is not one of the phrases.** `tagging.py`'s body-only branch
counted `quantitative` and `quant` toward its two, so `Cloud Engineer` reached
`adjacent` on "body only 'quantitative', once" — the one word every employer
writes about every role. `lexicon.GENERIC_IN_BODY` had named that set already
and the other module was not reading from it; `_QUANT_CORE_BODY` now subtracts
it. In a *title* the same word is the whole job, which is why there are two
lists rather than one edit.

**`fold` deleted every non-ASCII letter, so every Swedish rule in `tagging.py`
was dead.** The strip keeps `a-z0-9+#`, so `ö` became a *space*:
`Sjuksköterska` folded to `sjuksk terska` while the needle said
`sjukskoterska`, and `Göteborg` to `g teborg` against `goteborg`. Not one of
the accented Swedish needles had ever matched — nurses, cleaners, drivers,
teachers and shop staff were all reaching the board, which is exactly what
"the filtering is lacking in Swedish ads" looks like from outside. `_terms`
folds needles the same way and its docstring calls that "folding both sides",
which is the right discipline and does nothing when the fold is lossy in
different directions: `francais` folds to `francais`, `français` folded to
`fran ais`. `fold` transliterates now (`ö`→`o`, `ß`→`ss`, `æ`→`ae`), so both
spellings converge and a needle may be written either way. **1,013 postings
were gated by that one change, with no needle edited.**

**A Swedish occupation is one token, so a needle cannot see inside it.**
`Elsäljare`, `Fältsäljare`, `Tandsköterska` and `Inköpschef` all survive a word
list, because Swedish compounds. Match the occupational *head* as a suffix —
`lexicon.SWEDISH_HEADS` had this and `tagging.py` did not. Same asymmetry as
everywhere else when picking heads: `-arbetare` catches *medarbetare*, which is
just "employee", and `-assistent` catches *Forskningsassistent*, a research
assistant worth keeping. Both were dropped after the dry-run.

**A country name in a city's list claims a city it does not know.** `sweden`
sat in the `stockholm` tuple, so every Swedish ad read Stockholm — Kiruna,
Lund, Visby, Kalmar. Harmless while geography ranked; under a gate it deletes
postings for being somewhere they are not. Focus hubs are the city plus a real
commuting belt now, and the rest of the country is `sweden_other`,
`denmark_other`, `netherlands_other`.

**A gate makes every gap in a place list a deleted posting**, which is the
opposite of the pressure a ranking list is under. Two found by measuring rather
than reading: `2 Locations` is what Workday publishes for 6,281 multi-site
postings and reading it as `other` claimed we had looked — it is `unknown`, and
`unknown` is kept. And 5,987 US postings said only `Cincinnati, OH`, so they
gated as elsewhere while the US is semi-target; the state code is the handle,
matched against the **location alone** because hub matching reads the title too
and `IN`, `OR`, `ME` and `DE` are all English words as well as states.

**Language requirements were caught nine times in ten by nothing.** The
`_SPOKEN_REQUIRED` list was three phrasings per language — "fluent in X", "X is
required", "native X" — and hit 151 postings out of 69,961. Advertisements also
say "proficiency in", "good command of", "written and spoken", "C1",
"verhandlungssicher", "i tal och skrift". Built from frames × language names
now, 690 postings. Requirement phrasings only: `X a plus` is not a requirement,
and this is a soft filter, so a generous frame costs a rank notch where a
missing one costs a surprise at interview.

**Language detection cannot use `fold`.** `fold` strips everything outside
`a-z0-9+#`, so `är` becomes `r` and `från` becomes `frn` — and function words
are the whole method. `posting_language` keeps diacritics, and returns
`unknown` below four stopword hits rather than guessing, because 81% of the
corpus is a six-word title.

**The board has four gates now, not one, and they are the whole list.** They
live in `web/build_data.py`'s `GATES`: `off_industry` (another profession),
`off_location` (outside the target and semi-target geography), `out_of_reach`
(director, VP, manager, project leader, product owner — a rank nobody reaches
from under a year of experience) and `rejected` (the tagger read it and it is
not this line of work). Each is counted separately on every build, because one
total would hide which of the four ate a hub.

**`rejected` is the widest gate and the one to be most careful with.** It
removes 12,637 postings, more than the other three combined, and it is the only
one whose evidence is a *judgement* rather than a named fact — the others read a
place, a rank or an occupation. It went in on the strength of a 1,000-posting
machine-labelled sample that found no false rejection anywhere in it, which is
real evidence and not proof: a model grading a model shares the grader's blind
spots. Delete the line if the board ever looks too empty; it needs no re-tag,
and `list --exclude rejected` shows what it ate.

**`student_intern` is not a seniority.** It was the one value on that ladder
read from a *body* rather than a title, so the labelling sheet kept asking a
question the tagger does not answer, and every intern-titled row disagreed. It
was carrying 67 postings while `contract: internship` carried 1,307. Being a
student is an eligibility fact — `hard_gates: student_only` — and a contract,
and both were already recorded.

**The `unknown` bucket is a vocabulary gap, not a broken rule, and only volume
showed it.** A 1,000-posting machine-labelled sample's largest single
disagreement was `relevance: unknown` on rows any reader rejects on sight —
`Event Coordinator (Casual)`, `Universal Banker`, `Usher/Ticket Taker`. **6,604
of the 6,852 had no body at all**, so it was never going to be fixed by reading
descriptions better; it needed occupation words. Adding them took the board's
`unknown` from 6,852 to 5,109 and moved no posting out of a positive verdict.

The residual is mostly the deliberate backfill queue — bare `Analyst`,
`Associate`, `Data Scientist`, `Financial Analyst` — which `judge` refuses to
reject on a title alone and should keep refusing.

**Check the form the corpus advertises, not the form the dictionary uses.**
`environmental inspector` did not match `Environmental Inspectors (Field
Based)`, because token matching is exact and the postings are plural. Same
shape as `Elsäljare` needing a compound rule: the needle has to be written
against real titles, which is what the dry-run is for.

**A needle's head count is not the safety check — whether it touches a positive
is.** Every occupation word added this way was measured against the postings
the tagger already rates `relevant`, `less_relevant` or `adjacent`, and any
needle touching one is read by hand before it goes in. `landscape` was dropped
on that test: it caught `Managing Technical Consultant, Landscape
Architecture`, and a *data* landscape is one usage away.

**A gate must fire on evidence, never on the absence of it.** `out_of_reach`
reads the rank from the title only and skips `unknown`, so a posting that
simply never stated a grade stays on the board. Same reason `unknown` survives
the geography gate. The gate can only remove something it actually read — which
is what stops a widened lexicon from quietly emptying the page.

**The board filters in two stages, and only the first one removes anything.**
Stage one is a *gate*: a nurse, a welder and a `Medical AI Specialist` are not
distant quant roles, they are other professions, so `build_data.py` drops them
and they never reach `data.js`. Everything else in the rail *ranks*. This is
the one place in the pipeline where a classifier removes rather than reorders,
so it is deliberately the narrowest rule in `tagging.py`, and it stays
consistent with principle 4 by never touching the database: `jobs` keeps the
row, `job_tags` keeps `exclusion_reason: off_industry` with the evidence, and
re-running the tagger rebuilds the verdict. Every build prints the count, and
`list --exclude off_industry` shows what it ate. A gate that removes silently
is how a widened lexicon quietly eats a hub.

**Prefer the source's own taxonomy to any word list you would write.**
JobStream files every Swedish ad under one of 21 `occupation_field` values —
that is an enumeration written by the employer, and 15 of them can never hold a
quant job, which is 2,800 postings gated on evidence rather than on guesswork.
`jobs.category` exists for this. The keep list is deliberately a *drop* list:
an unrecognised field passes, because failing towards keeping is the direction
this project always picks. Only the ATS boards, which publish no taxonomy at
all, need occupation words.

**Every needle in a hard gate must be dry-run over the whole corpus first.**
Five words that look like trades name jobs this project might want, and each
matched something real: `coach` is *Portfolio Manager/Agile Coach*, `pilot` is
*Paint Pilot Projects*, `librarian` is *ECAD Librarian*, `translator` is DBS's
*Data Translator*, `interpreter` is *Parts Interpreter*. `chef` is worse — it
is Swedish for *manager*, so it would have dropped `Ekonomichef`, a CFO. `driver`
cost one true positive in 70,000 rows and would eventually have caught
something like *Value Driver Analyst*.

**Most postings with "Trader" in the title are not quant trading**, and one
word in the title is the whole difference. `trading_style` splits `Agency MBS
Trader` and `Precious Metals Trader` from `Quantitative`, `Systematic` and
`Algorithmic Trader` — 108 against 14 in this corpus. Two things it got wrong
first: it keyed on `role_class: trading`, whose lexicon includes bare
*trading*, which is the name of a **department** — that made `Backend Engineer
— Trading & Asset Optimization` a pure trader. It matches the nouns for the
seat now (`_TRADER_SEAT`). And `_QUANT_CORE` held only the participle forms, so
`Algorithmic Trader` is not "algorithmic trading" and read as a trader with no
quant signal at all. When a needle is a phrase, check the noun form of it too.

**A body can overturn a title-based occupation rejection, and it is the same
boilerplate bug one level up.** `lexicon.judge` step 6 rejects a named
non-quant occupation, and its escape hatch was a single `quant_body` phrase —
so `Wealth Advisor` **with no body rejects, and the same title with a
28,572-character body came back `undecided`**, rescued by one phrase out of the
firm's own description of itself. `Cloud Engineer` went further and reached
`keep`. The escape now needs a phrase from `QUANT_MARKETS_BODY`, which names
markets *activity*: nothing writes *statistical arbitrage* in passing, and step
5 has already let every quantitative title through before step 6 runs, so the
hatch was never protecting a quant title in the first place. Counting phrases
is not the fix here either — a finance title guarantees the markets context
that made counting look like evidence one layer down.

**Where a specialty is the job, no markets context around it changes that.**
`lexicon.ENGINEERING` is deliberately two-sided and must stay so — `Software
Engineer, Trading Systems` at Optiver is in scope. `tagging._SOFTWARE_SPECIALTY`
is the proper subset where the ambiguity does not exist: frontend, devops, SRE,
cloud, infrastructure, QA, IT support. Six hand-labelled rows were rejected on
sight and every one had reached `adjacent` or `unknown` on the bare word
*trading* — the name of the platform, not the work. Bare `software engineer`
and `developer` are deliberately absent, because a quant-dev role calls itself
one. A body naming markets activity still holds one open, which is pinned by a
test: a `Cloud Engineer` at a firm running *statistical arbitrage* is a real
posting shape.

**One word, two lists, two answers — check the other list.** `_MANAGEMENT` had
treated `vp`, `vice president` and bare `director` as unreachable since the user
asked for director titles to go, while `_SENIORITY` still called them
`senior_6_10`. The gate and the ladder disagreed about the same word, and four
hand-labelled rows all read *"filter out becuase VP role"*. Moving them needed a
`_NOT_HEAD_GRADE` guard, because bare `director` swallows `Associate Director`
— a bank's five-year grade — and `Art Director`, where the word is not a rank at
all. `_first` takes the first bucket that hits, so ordering cannot express this.

**Seniority was reading the title *and the department*, under comments arguing
twice over that it must not.** `rank = _first(_SENIORITY, title)` where `title`
is `fold(row["title"], row["department"])`. It went unnoticed while the needles
were phrases like `head of` that a department rarely carries; bare `director` is
not one of those, and `Associate - Fund Governance` sits in a department called
*Director Services* — the exact posting the comments there name as the case not
to get wrong. Whenever a needle gets shorter, re-check what text it is matched
against.

**A compulsory doctorate is an eligibility fact, not a verdict.** Two rows were
labelled `rejected` with the note *"perfect fit — but has hard requirement of
phd"*, and *perfect fit* is the half that decides where it belongs: relevance
stays `relevant` and the posting comes off the board through `GATES` instead.
Same shape as `student_intern` leaving the seniority ladder, at the user's own
decision. **Bare `phd` in a title must never gate** — 220 titles carry it and 29
are rated positively, including `Campus Quantitative Researcher, PhD`. It names
the audience a posting is open to, not a bar it sets. Only the compulsory
phrasings gate, and `phd+` is one of them because `+` survives folding.

**A labelled disagreement and a labelled non-answer are different facts, and
one number hid it.** `seniority` scored 39.5% against the hand-labelled sheet
and most of the gap was the tagger returning `unknown` on titles that state no
grade — which is the behaviour chosen deliberately after a stray *partner* in a
diversity paragraph made an internship a managing director. `labels` prints
both now: `wrong` is what a lexicon fix can move, `unanswered` is not, and only
the first is evidence of a bug.


## What is actually slow, measured rather than assumed

**`jobs` was the only network command running serially, and it is Layer 3.**
`ats`, `domains`, `pages`, `discover` and `bodies` have all used a 12-worker
pool for a long time; `extract.run` was a plain `for` loop over all 911 boards.
Measured on a 36-board sample spread across 16 ATSes: **32.3s serial, 4.5s
parallel — 7.2x**, and a full run goes from roughly 14 minutes to 2. Politeness
is unchanged and that is what makes it safe: `http._throttle` books its
interval **per host** under a lock, so two workers on different boards never
share a slot and two on the same host still queue a second apart. The comment
on `_last_hit` had already made that argument for `domains`.

Note the shape of the measurement, because the first attempt said *1.0x*: a
sample taken with `targets(con, 24)` was 1,363 postings from 24 boards, so it
was pagination against a handful of hosts, where the per-host throttle is the
floor and parallelism cannot help. **Spread the sample across hosts, or a
concurrency change measures nothing.**

**A re-tag is not "dominated by writing rows", and this file used to say it
was.** Profiled over the real corpus:

| phase | cost |
|---|---|
| classifying 157,464 postings | **5.5 min** — 2.11 ms each, `_hit` is 52% of it |
| writing ~2.4M rows | ~2 min |
| `postings()`, finding what to tag | 7.2s, now 1.1s |

So classification dominates, by roughly three to one. WAL plus
`synchronous=NORMAL` is worth only 1.1x on the writes — it is in `db.connect`
for the concurrency, not the speed.

**Measured again at 259,083 postings and 4.17M tags: 13m17s end to end**, so
about 19,500 postings a minute against the 28,400 the 2.11 ms figure implies.
Two things changed since that profile and both are real work rather than a
regression: the lexicon roughly doubled in its two largest lists
(`_OFF_INDUSTRY` is 369 needles, `_HUBS` over 450), and far more of the corpus
now carries a body — Singapore, Denmark and Switzerland are all at 100%.
`_hit` is linear in both. Read `MIN(tagged_at)` and `MAX(tagged_at)` for the
current tagger to measure it; those are exact, and they are trustworthy only
for the *newest* version, because the primary key omits `tagger` and a later
run eats the rows of an earlier one.

**`postings()` needed an index nobody had noticed was missing.** It asks "is
this posting tagged at the current version" as a correlated `NOT EXISTS` on
`(ats, token, job_id, tagger)`. The primary key covers the first three and
stops, so SQLite walked every row for that posting — about fifteen dimensions
per lexicon version, across every version still in the table — to test
`tagger`. `job_tags_by_tagger` makes it a seek: **7.2s to 1.1s**, and the plan
goes from `sqlite_autoindex_job_tags_1` to a covering index. Whenever a query
filters on a column that is in the table and not in the index, check the plan
before assuming the primary key covers it.

**`job_tags` grows by ~2.4M rows per version bump and does not shed the old
ones.** The retention was already known to be broken — the primary key omits
`tagger`, so a version's rows are partially overwritten rather than kept — so
the table accumulates cost for a history it cannot actually serve. Pruning
superseded taggers after a successful re-tag is the obvious fix and is
deliberately *not* done here: it deletes rows, and that is the user's call even
in a derived table.

**Do not speed the pipeline up by filtering at ingest.** It is the first thing
that suggests itself and it breaks principle 4. Every lexicon bug in this
project has been fixed by re-running the tagger over stored rows; a posting
dropped at write time cannot be recovered without re-scraping. The legitimate
version of the idea is to filter the *work* rather than the *data*, which
`bodies.py` already does — it fetches a description only for postings whose
verdict a body could change.


**A years figure may raise a rank and must never lower one the title stated.**
The carve-out from "the rank is in the title" was written for a title that
*under-sells* itself -- `Quantitative Trading Associate` says associate and
demands "3+ years", so the bar is the fact. Read in the other direction it is a
leadership escape: `Senior Software Engineer` whose body mentions three years
came out `mid_3_5` and cleared `out_of_reach`, because a body's smallest number
is routinely the *entry* bar on a senior posting ("3+ required, 8+ preferred"
floors at three). Measured on the machine sheet, leadership containment was
46.1% and every miss was this shape. It promotes only now, and 3,517 postings
newly gate -- 38 of them rated positively, all "Senior" titles that had been
escaping a rung `_OUT_OF_REACH` already contained.

**Seniority is scored by what it is for, not by agreement on a rung.** The
reader wants it "for filtering out leadership positions", and rung agreement
answers a different question badly: a third of the labelled rows are titles
stating no grade, where the tagger answers `unknown` on purpose, and a
`Senior X` posting the reader calls `mid_3_5` and the tagger calls
`senior_6_10` is a disagreement about a word and an agreement about the
decision. `labels.containment` asks the two questions with consequences --
how much labelled leadership the board withholds, and how many postings rated
worth reading the rank gate removed -- and reports them separately, because the
two errors are not interchangeable and netting them off would hide both.
