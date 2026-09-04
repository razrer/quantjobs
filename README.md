# quant-scraper

Exhaustive quant-job aggregation, built **employer-first**: enumerate the firms
that could hire a quant from registries that are complete by law, resolve each
to its own careers feed, and poll that. Aggregators and national job boards are
a discovery net for employers the registries miss, never the primary source.

The board is live at **https://quantjobs.spawned.app**.

No dependencies today, so there is nothing to install. Third-party packages
are allowed where they cost nothing and remove a measured cost — see
[CLAUDE.md](CLAUDE.md) for the three tests one has to pass.

- Working notes and every documented gotcha: [CLAUDE.md](CLAUDE.md)
- Stage log and what is next: [PLAN.md](PLAN.md)
- Tag dimensions and the labelling method: [TAGGING.md](TAGGING.md)
- Blocked on the user: [ACTION-REQUIRED.md](ACTION-REQUIRED.md)

## Updating the live board

Two things can be out of date and they are fixed differently.

**New listings** — sweep every source, re-tag, rebuild and upload:

```bash
./run.ps1 daily --full --publish
```

**A code change** to the board itself — commit and push; a GitHub Action
re-uploads `index.html` and `robots.txt` automatically:

```bash
git push quantjobs master
```

`web/data.js` never goes through git. It is gitignored, built from the local
SQLite database that exists only on this machine, and CI has no copy — so a data
refresh is always a local `daily --publish`. `infra.json` (one private bucket,
one CloudFront distribution) changes approximately never; `spawned apply
quantjobs` applies it.

## Running it

`run.sh` / `run.ps1` wrap these with the right interpreter — see the
[environment gotcha](#one-environment-gotcha).

**Layer 1 — the employer universe**

```bash
python -m quantscraper fetch      # pull employers from registries
python -m quantscraper resolve    # group raw rows into firms
python -m quantscraper stats      # what is in the database
python -m quantscraper audit      # check the universe against the named roster
```

**Layer 2 — resolve each firm to a careers feed**

```bash
python -m quantscraper domains --limit 1000   # firm name -> domain, guessed then verified
python -m quantscraper fca --limit 300        # enrich domains from the FCA register (needs .env)
python -m quantscraper ats --limit 800        # fingerprint careers hosts to an ATS
python -m quantscraper discover --roster      # find boards no careers page named
```

**Layers 3 and 3B — poll the feeds**

```bash
python -m quantscraper jobs --limit 100       # postings from resolved boards
python -m quantscraper pages --limit 500      # watch tier-B careers pages
```

**Layer 4 — national boards, polled directly**

```bash
python -m quantscraper jobstream              # Sweden's national delta feed
python -m quantscraper switzerland            # job-room.ch
python -m quantscraper sweden                 # Jobbsafari, all of it
python -m quantscraper denmark                # Jobindex, every category
python -m quantscraper denmark --since 2026-08-18   # daily top-up, one query
```

**Layers 5 and 6 — classify and read**

```bash
python -m quantscraper tag                    # classify postings into tags
python -m quantscraper list --fit apply_now --hub amsterdam
python -m quantscraper list --dimensions      # every filterable value
python -m quantscraper coverage               # how much of the market we see
python -m quantscraper sample --limit 100     # draw postings to hand-label
python -m quantscraper labels                 # score the lexicon against them
python -m quantscraper corrections            # pull reclassify clicks off the live board
```

The deployed board has no server, so a correction clicked there posts to a small
Lambda (`functions/correction_writer`) which appends to one JSON blob in the
bucket. `corrections` reads that back and upserts it into `labels.csv`, exactly
as `web/serve.py` does for a board run locally. It is the first step of `daily`,
so a normal day picks these up on its own.

**The standing sequence**

```bash
python -m quantscraper daily                  # corrections, the four national boards,
                                              # jobs, pages, bodies, tag, alerts, rebuild
python -m quantscraper daily --full --publish # weekly: every category, then push live
python -m quantscraper alerts                 # which source went quiet, on its own
```

`daily` is deliberately manual — the search is the expensive half, it is free
here and billable anywhere else, so nothing schedules it. What is deployed is
the *output*, not the scraper. A failing step does not stop the run, because a
board redesigned underneath us should cost its own postings and not the other
eight sources'; `alerts` says which one went quiet and the exit code says
whether any did.

```bash
python -m unittest discover -s tests          # regression tests
```

### One environment gotcha

Bare `python` on this machine resolves to the msys2 build, which ships **without
a CA bundle**, so every HTTPS request fails with `CERTIFICATE_VERIFY_FAILED`.
Use the Windows Python — `run.sh` / `run.ps1` already do:

```bash
"/c/Users/razre/AppData/Local/Programs/Python/Python313/python" -m quantscraper fetch
```

Also set `PYTHONIOENCODING=utf-8` when printing firm names, or non-ASCII names
raise `UnicodeEncodeError` on this console.

## What it collects

Fourteen registries, ~79,000 employer rows resolving to ~70,000 firms; run
`python -m quantscraper stats` for the current split.

| Registry | Jurisdiction | Notes |
|---|---|---|
| `finanstilsynet_dk` | DK | Danish FSA; no enumerable endpoint, so it is swept by letter |
| `sec_adv` | US | Form ADV monthly bulk CSV, registered + exempt reporting |
| `esma_eea` | EU | EEA-wide investment firms, AIFMs and UCITS managers |
| `afm_nl` | NL | AFM investment firms, fund managers, both AIFM registers |
| `sfc_hk` | HK | SFC licensed corporations, by regulated activity |
| `sec_bd` | US | SEC active broker-dealers — where the US prop firms are |
| `finma_ch` | CH | FINMA authorised institutions |
| `mas_sg` | SG | MAS Financial Institutions Directory, by category |
| `fi_se` | SE | Finansinspektionen, by regulatory category |
| `eurex`, `euronext`, `cboe_europe` | EU | admitted exchange participants |
| `fia_epta` | EU | European Principal Traders Association members |
| `seed` | manual | firms no public register carries; hand-maintained CSV |

`sec_adv` supplies a website for ~92% of its firms, which is most of Layer 2's
domain resolution for free. The exchange lists are small and do work nothing
else does: hundreds of firms are reachable only through membership, among them
3Red Partners, AlphaGrep, ABC Arbitrage, Transtrend and Mint Tower.

## Design notes

**Enumerate, never query.** FI is walked category by category, MAS by category,
SFC by regulated activity, ESMA by a Solr query returning the whole set. A
search endpoint only returns what you thought to ask for, which is a hard
ceiling on recall; a category listing has no such ceiling.

Denmark is the exception that proves the rule. Finanstilsynet exposes six
service operations and none of them lists anything — its own "list extract" page
renders an empty shell. So `finanstilsynet_dk` sweeps: the search matches a
**substring**, so querying "a" returns every name containing one, and the union
over the alphabet is the register. It **saturates** part way through, and that
saturation is the evidence of completeness rather than of a cap.

**ESMA is the highest-leverage source, and not for its size.** Three quarters of
its records carry an **LEI** and no national register we hold publishes one. LEI
is the strongest key entity resolution has, so it merges firms held under names
that match nothing: cross-registry firms went from 2,595 to 4,234 when it landed.

**Never filter membership.** Every firm a registry returns is kept forever and
rows are never deleted. `category` is stored verbatim so later layers can set
*polling frequency* from it — a mis-tuned heuristic must cost latency, not
coverage.

**An implausibly small result is a failure.** Each registry declares
`MIN_EXPECTED` and raises rather than quietly writing a near-empty table. A
scraper that breaks and returns zero rows with HTTP 200 is far more dangerous
than one that crashes, because nothing announces it. Every fetch appends to
`runs`, which is the volume history `alerts` reads.

## Firm identity

`employers` holds raw registry rows and one company can occupy several.
`resolve` groups them into `firms` on deterministic keys — LEI, SEC CRD, domain,
normalized name — plus a small curated table for groups whose legal names share
nothing, like Tower Research trading as `LATOUR TRADING LLC`.

Normalization strips legal forms (`AB`, `B.V.`, `LLC`) and **nothing else**,
because the expensive mistake is a false merge: a duplicate costs a second of
reading, a wrong merge silently deletes an employer. Citadel and Citadel
Securities stay separate for exactly that reason.

## Coverage audit

`python -m quantscraper audit` checks the universe against a hand-named roster
in `quantscraper/roster.csv`. **The roster measures coverage; it never defines
it.** A firm's absence from it says nothing, and the audit reads no table it can
write to.

Two numbers per hub, because the first is easy to overstate:

| | |
|---|---|
| **present** | the firm is in the universe under some name |
| **local** | some row places the firm in that hub's country |

Hong Kong is why both are reported: at one point all nine of its roster firms
were *present* and exactly one was *local*, the rest visible only through US
registrations. A single number would have claimed Hong Kong was solved before
any HK register had been ingested.

Every miss carries a written reason in the roster's `note` column and the audit
prints it, so a miss is never just a blank. Firms that have ceased to exist
(IPM, AP1, AP6) are marked `stale` and excluded from the rates.

**The audit measures the employer universe, not the job pipeline**, and the two
had drifted completely apart — every focus hub read 100% present while 147 of
163 roster firms produced no postings at all. `audit --pipeline` asks the second
question. When a coverage number looks finished, ask which table it counted.

Matching is **token-aligned anywhere in the name**, never anchored to the start:
registries prepend qualifiers (`Bank Julius Bär & Co. AG`,
`Fondsmæglerselskabet Maj Invest A/S`) and anchoring silently loses them.
**A false hit is the failure this guards against**, because it hides a miss —
`-v` prints what each entry actually matched.

## Domain resolution

A firm name has to become a careers feed, and **the focus-region registries
publish no websites at all** — not one of `fi_se`, `afm_nl`,
`finanstilsynet_dk`, `mas_sg` or `sfc_hk` carries a single URL. So the domains
are derived: `domains.py` builds candidates from the name and accepts one only
if the page that answers **names the firm**. A live host proves only that
somebody owns the name.

**An unverified guess is worse than no domain**, because it points Layer 3 at
someone else's careers page and the result is a silently empty feed rather than
a visible error. Matches are graded:

| grade | bar | counted? |
|---|---|---|
| `registry` | the register published it | yes |
| `name-strong` | the page carries the full name, or its first two identity-bearing words | yes |
| `name-weak` | the page carries one word of a multi-word name | **no** |
| `unresolved` | nothing verified | no |

Weak matches are kept with their evidence rather than discarded — `nomura.com`
really is right for *Nomura Financial Products Europe GmbH* — but nothing
downstream may use one until it is confirmed. Four false positives shaped these
rules: `australia.com` (the tourism board) for *Australia and New Zealand
Banking Group*, `societe.com` for *Societe Generale*, `citadel.com` for *Citadel
Securities* — a different employer with a different careers page — and
`marketfrance.com`, which "proved" itself by printing the domain we had guessed.
Matching is on spaced phrases only, so evidence cannot be circular.

The cache is keyed on the firm's **name**, not its id, because `firms` rebuilds
from scratch on demand and ids are not a durable handle. Failures are cached
too: most firms are unresolvable, and re-probing them every run is the bulk of
the cost.

## Known coverage gaps

Real holes, not bugs.

- **Own-account prop firms can appear in no register at all.** A firm dealing
  exclusively on its own account is exempt from investment-firm licensing under
  MiFID II Art. 2(1)(d). Exchange participant lists cover most of them; a firm
  trading via **sponsored access** under someone else's membership is covered by
  nothing public. Da Vinci Derivatives is the standing example and reaches the
  universe only through `seed`.
- **State-registered US advisers are absent.** The ADV bulk file is SEC
  registrants only; advisers under roughly $110M AUM register with their state.
- **Sovereign wealth funds appear in no financial register.** ADIA, ADQ,
  Mubadala, GIC and Temasek are significant quant employers reachable by no
  registry anywhere. The seed file is the only realistic route.
- **Dubai has no reachable register** — the DFSA's is behind a reCAPTCHA.
- **Most small Hong Kong funds run no public board.** All 51 roster firms were
  probed by name across every discoverable ATS and the sweep found two, and 21
  were later re-probed by hand against their own careers pages: eight 404 on
  every path and most of the rest publish a careers page carrying no postings.
  The rest hire through recruiters and personal networks, which no scraper
  reaches. This is a finding, not a gap.
- **A few large firms simply refuse us.** ABN AMRO answers 503, Nasdaq times
  out, Citadel Securities and Jyske Bank answer 403; `curl` with a browser UA
  reaches all four. Julius Baer refuses `curl` too, so there is no header that
  reaches it. **Citadel is no longer among them**, and the way out was not a
  header: both Citadel hosts serve `robots.txt` and their sitemaps with HTTP
  200 while every HTML page 403s, and one of those sitemaps is a daily list of
  every open posting. The 403 said "not this door", not "no".
- **Three ATS vendors are closed for stated reasons.** Eightfold's
  `/api/apply/v2/jobs` answers 403, Paylocity renders its board client-side
  with no reachable data endpoint, and Jefferies' Lumesse `tal.net` portal sits
  behind an Altcha CAPTCHA. Morgan Stanley, XR Trading and Jefferies are the
  roster firms behind them.
- **Denmark carries no company type or city.** The register gives a name and a
  GUID; type and city need one request per company, which is 26,000 requests for
  a register enumerable in 39. Deferred deliberately — the rows are in the
  universe and the attribute backfills without re-scraping.
- **Corporate pension foundations are excluded** (807 Swedish ones). An asset
  pool ring-fencing one employer's pension liability is not a firm; its capital
  is managed under mandate by managers already listed.
- **Thousands of Form ADV filers give a social page as their website.** Over
  4,000 list a LinkedIn URL, plus ~2,000 on other platforms. Kept as-is in
  `employers` — raw data is never edited — and excluded from identity matching
  by `resolve.is_platform_domain`.
- **The UK is deprioritized and would not enumerate anyway.** FCA has no "list
  all firms" endpoint and no bulk download, so it is enrichment only.

Two gaps listed here previously were wrong, which is worth recording because
both were plausible. "Dutch pension managers are DNB-supervised" — they are not,
and the real cause was `afm_nl` reading only AFM's CSV exports while the AIFM
registers are published as spreadsheets on the same page. "Julius Baer is
missing because there is no Swiss register" — it was in `eurex` from the start,
and the audit's matching was anchored to the start of the name.

## Adding a registry

Drop a module in `quantscraper/registries/` exposing `NAME`, `JURISDICTION`,
`MIN_EXPECTED` and `fetch() -> list[Employer]`, then add it to `REGISTRIES` in
that package's `__init__.py`. Nothing else changes.

Prefer sources you can **enumerate** over sources you must **query**, and verify
against the real endpoint before writing the adapter — several sources here
published formats nothing like what their documentation implied.

Focus hubs are **Stockholm, Copenhagen, Amsterdam, Switzerland, Hong Kong,
Singapore, New York, Chicago and Boston**, with the rest of the US shown and
ranked below them; Germany, London, China and Dubai are deprioritized. That
governs what gets built next, never what gets ingested — collected data is never
dropped for being out of area. The one exception is the *board*, which gates on
geography at the user's instruction; see `web/build_data.py`.

The US is three metros plus a residual rather than one national hub, for the
same reason Stockholm is a city and not Sweden: a focus hub is a commuting belt.
Measured over the corpus, those three metros hold 74% of the American postings
the board rates positively in 27% of its American volume.
