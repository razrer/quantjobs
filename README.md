# quant-scraper

Exhaustive quant-job aggregation, built employer-first.

This repo currently implements **Layer 1 of the plan: the employer universe.**
Regulatory registries are the backbone because financial firms are *legally
required* to register, so those lists are complete by construction. Later
layers resolve each employer to a careers feed (Layer 2) and poll it (Layer 3).

Full methodology: `C:\Users\razre\.claude\plans\snoopy-growing-hoare.md`.

## Running it

No dependencies — standard library only, so there is nothing to install.

```bash
python -m quantscraper fetch
```

```bash
python -m quantscraper resolve
```

```bash
python -m quantscraper stats
```

```bash
python -m quantscraper audit
```

```bash
python -m quantscraper domains --limit 1000
```

`resolve` groups the raw registry rows into real-world firms; run it after
`fetch`. It rebuilds from scratch every time, so it is safe to re-run.

`audit` checks the universe against the named roster in
`quantscraper/roster.csv` and reports, per hub, how many of those firms it
found. `-v` lists what each hit actually matched, which is how a wrong match
gets caught — see [Coverage audit](#coverage-audit).

`domains` resolves firm names to domains, `--limit` firms at a time. Results are
cached, including failures, so re-running is cheap and the work survives a
`resolve` rebuild — see [Domain resolution](#domain-resolution).

`fetch` takes optional registry names (`python -m quantscraper fetch fi_se`).
Data lands in `employers.sqlite3`; override with `--db`.

### One environment gotcha

`python` on this machine resolves to the msys2 build, which ships **without a
CA bundle**, so every HTTPS request fails with `CERTIFICATE_VERIFY_FAILED`.
Either use the Windows Python:

```bash
"$LOCALAPPDATA/Programs/Python/Python313/python" -m quantscraper fetch
```

or point msys2's OpenSSL at the bundle it already has:

```bash
export SSL_CERT_FILE=C:/msys64/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
```

## What it collects

| Registry | Jurisdiction | Firms | Notes |
|---|---|---|---|
| `finanstilsynet_dk` | DK | ~26,500 | Danish FSA; swept by letter, see the design note |
| `sec_adv` | US | ~23,300 | SEC Form ADV monthly bulk CSV, registered + exempt reporting |
| `afm_nl` | NL | ~3,700 | AFM investment firms, fund managers, and both AIFM registers |
| `sfc_hk` | HK | ~3,600 | SFC licensed corporations, by regulated activity |
| `sec_bd` | US | ~3,300 | SEC active broker-dealers; this is where the US prop firms are |
| `mas_sg` | SG | ~2,000 | MAS Financial Institutions Directory, by category |
| `fi_se` | SE | ~660 | Finansinspektionen, enumerated by regulatory category |
| `eurex` | EU | ~330 | Eurex admitted exchange participants, via CSV |
| `euronext` | EU | ~280 | Euronext trading members (AMS/BRU/DUB/LIS/MIL/OSL/PAR) |
| `cboe_europe` | EU | 52 | Cboe Europe equities trading participants |
| `fia_epta` | EU | 20 | European Principal Traders Association members |
| `seed` | manual | 16 | Firms no public register carries; hand-maintained CSV |

About 63,700 employers in total, resolving to 58,600 firms.

`sec_adv` supplies a website for ~92% of its firms and `euronext` for ~36% of
its own, which is most of Layer 2's domain resolution for free.

The two exchange lists are small but do work nothing else does: **365 firms are
reachable only through exchange membership**, among them 3Red Partners,
AlphaGrep, ABC Arbitrage, Transtrend and Mint Tower Capital. See the gap note
on licence-exempt firms for why.

All seven focus hubs now hold every firm on the audit roster — see
[Coverage audit](#coverage-audit) for what that does and does not mean.

## Design notes

**Enumerate, never query.** FI is walked category by category, MAS by category,
SFC by regulated activity, rather than searched — coverage should not depend on
guessing the right keyword.

Denmark is the exception that proves the rule. Finanstilsynet exposes six
service operations and none of them lists anything; its own "list extract" page
renders an empty shell. So `finanstilsynet_dk` sweeps: its search matches a
**substring**, so querying "a" returns every name containing an "a", and the
union over the alphabet is the whole register. The union **saturates** part way
through — the digits and Danish letters that follow add nothing — and that is
the evidence it is complete rather than capped.

**Never filter membership.** Every firm a registry returns is kept forever, and
rows are never deleted. `category` is stored verbatim so later layers can use
it to set *polling frequency* — a mis-tuned heuristic should cost latency, not
coverage.

**An implausibly small result is a failure.** Each registry declares
`MIN_EXPECTED`; returning fewer rows raises rather than quietly writing a near
empty table. A scraper that breaks and returns zero rows with HTTP 200 is far
more dangerous than one that crashes, because nothing announces it. Every fetch
also appends a row to `runs`, which is the volume history that per-source
anomaly detection will need.

## Known coverage gaps

Found while verifying this layer against the plan's audit roster. All are real
holes, not bugs:

- **Own-account prop firms can appear in no register at all.** A firm dealing
  exclusively on its own account is exempt from investment-firm licensing under
  MiFID II Art. 2(1)(d), so it need not appear in any regulator's register.
  `eurex` and `euronext` were added to cover this, and they help — 365 firms
  come from exchange membership alone. But **Da Vinci Derivatives, the firm that
  prompted the fix, is still missing**: it is in neither AFM register, neither
  EPTA, and is a direct member of neither venue, most likely trading via
  sponsored access under someone else's membership. Sponsored-access firms are
  a residual hole that no public list closes. **Partly closed since:**
  `cboe_europe` adds the 52 Cboe European trading participants, and `seed`
  carries a hand-maintained file (`registries/seed_firms.csv`) that Da Vinci and
  five other Amsterdam shops now come from. The structural hole remains — the
  seed file only contains firms someone thought to name.
- **State-registered US advisers are absent.** The ADV bulk file is SEC
  registrants only (`Firm Type` is uniformly `Registered`); advisers under
  roughly $110M AUM register with their state. This resolves the plan's open
  verification question — the answer is no, and the sub-$110M US tail needs a
  separate source.
- **AP1–AP4 and AP6 appear in no FI category.** Only AP7 is FI-supervised; the
  other buffer funds are governed by their own act. **Closed since** — they come
  from `seed`.
- **Sovereign wealth funds appear in no financial register.** ADIA, ADQ,
  Mubadala, GIC and Temasek are all significant quant employers and none is
  reachable by any registry, anywhere. **Closed** via the seed file, which is
  the only realistic route and will stay that way.
- **Dubai has no local register.** The DFSA puts its public register behind a
  reCAPTCHA, so it is not reachable here. Dubai reads 7/7 present but 3 local:
  Emirates NBD is visible only through its *Singapore* banking licence. This is
  the one open item in `ACTION-REQUIRED.md`.
- **Switzerland has no local register.** 11/11 present, 6 local — the rest come
  from Dutch, Danish and US registrations. FINMA would fix it and is not built.
- **Denmark carries no company type or city.** The Danish register gives a name
  and a GUID; type and city need one request per company, which is 26,000
  requests for a register enumerable in 39. Deferred deliberately — the rows are
  in the universe and the attribute can be backfilled without re-scraping.
- **Corporate pension foundations are excluded** (807 Swedish ones). An asset
  pool ring-fencing one employer's pension liability is not a firm; its capital
  is managed under mandate by managers already listed. Same rule as funds.

Two gaps listed here previously turned out to be wrong, which is worth recording
because both were plausible:

- **"Dutch pension managers are DNB-supervised."** They are not, and DNB's
  register does not contain PGGM at all. The real cause was `afm_nl` reading
  only AFM's two CSV exports while the AIFM manager registers are published as
  spreadsheets on the same page. Fixed.
- **"Julius Baer is missing because there is no Swiss register."** It was never
  missing — `Bank Julius Bär & Co. AG` had been in `eurex` from the start. The
  audit's matching was anchored to the start of the name, and the registry name
  begins with "Bank". Fixed in `audit.py`, not by adding a source.
- **IPM is absent, and that is correct** — the firm wound down. The plan's
  named roster is slightly stale here.
- **The UK is not covered.** Every FCA route — register API, bulk download —
  returns 401/403 without an API key, and the key needs an account you have to
  register for yourself. Worse, the API has no "list all firms" endpoint, only
  per-firm lookups, so even with a key it cannot enumerate a universe. FCA is
  therefore an *enrichment* source (checking the `dealing in investments as
  principal` permission on firms found elsewhere), not a registry. London is
  currently reachable only via `sec_adv`/`fia_epta` entities.

- **Thousands of Form ADV filers give a social page as their website.** Over
  4,000 list a LinkedIn URL in the `Website Address` field, plus ~2,000 more on
  Facebook, X and Instagram. They are kept as-is in `employers` (raw data is
  never edited) but they are useless for Layer 2 domain resolution, and they are
  excluded from identity matching — see `resolve.py`.

## Firm identity

`employers` holds raw registry rows; one company can occupy several. `resolve`
groups them into `firms` using deterministic keys — LEI, SEC CRD, domain,
normalized name — plus a small hand-curated table for corporate groups whose
legal names share nothing, like Tower Research trading as `LATOUR TRADING LLC`.

Normalization strips legal forms (`AB`, `B.V.`, `LLC`) and **nothing else**, and
the curated prefixes are deliberately specific, because the expensive mistake
here is a false merge: a duplicate costs a second of reading, a wrong merge
silently deletes an employer. Citadel and Citadel Securities are kept separate
for exactly this reason — different employers, different careers pages.

Current state: 63,724 rows → 58,638 firms. The collapse is modest because most
rows carry no website; Stage 4 (domain resolution) is what will improve it, and
`firms` is rebuilt from scratch on demand so re-running then is free.

## Coverage audit

`python -m quantscraper audit` checks the universe against the methodology's
named roster — 163 entries across 11 hubs, checked in as
`quantscraper/roster.csv`. **The roster measures coverage; it never defines it.**
A firm's absence from that file says nothing about whether it belongs in the
universe, and the audit reads no table it can write to.

Two numbers per hub, because the first one is easy to overstate:

| | |
|---|---|
| **present** | the firm is in the universe under some name |
| **local** | some row places the firm in that hub's country |

Hong Kong is why both are reported. All nine of its roster firms are *present*
and exactly one is *local*: the rest are visible only through US registrations,
so a single number would have claimed Hong Kong was solved when no HK register
has been ingested at all.

Current focus-hub results — every hub holds every roster firm, and *local* is
now where the remaining work is:

| Hub | Present | Local |
|---|---|---|
| Stockholm | 20/20 | 20 |
| Copenhagen | 7/7 | 7 |
| Amsterdam | 13/13 | 13 |
| Singapore | 10/10 | 7 |
| Hong Kong | 9/9 | 8 |
| Switzerland | 11/11 | 6 |
| Dubai | 7/7 | 3 |

Every miss carries a written reason in the roster's `note` column, and the audit
prints it, so a miss is never just a blank. Stale entries (IPM, wound down in
2021) and entries that never named a real firm (AP5 — there is no *Femte
AP-fonden*) are marked and excluded from the rates, so they stop reading as bugs.

**A recorded reason is a hypothesis until someone checks it.** Two of the
reasons written during Stage 2 were wrong — see the last two bullets under
[Known coverage gaps](#known-coverage-gaps). Both are kept in the file, corrected
rather than deleted.

Matching is **token-aligned anywhere in the name**, not anchored to the start.
Registries prepend qualifiers to legal names — `Bank Julius Bär & Co. AG`,
`Fondsmæglerselskabet Maj Invest A/S` — and anchoring silently loses them.

**A false hit is the failure this guards against**, because it hides a miss.
`-v` prints the employer names each entry actually matched: a bare
`Grasshopper` matching `GRASSHOPPER ESCAPEMENT, LLC` reported Singapore as
covered when it was not, and was only visible because the matched name is shown.

## Domain resolution

A firm name has to become a careers feed. **The focus-region registries publish
no websites at all** — not one of `fi_se`, `afm_nl`, `finanstilsynet_dk`,
`mas_sg` or `sfc_hk` carries a single URL. Of the 34,047 firms they report, 2.3%
had a domain, and 95% of even those came from a US registration rather than a
local one. So the domains have to be derived.

`domains.py` builds candidate domains from the firm's name and accepts one only
if the page that answers **names the firm**. A live host proves only that
somebody owns the name.

**An unverified guess is worse than no domain.** It points Layer 3 at someone
else's careers page, and the result is a silently empty feed rather than a
visible error. So matches are graded:

| Grade | Bar | Counted? |
|---|---|---|
| `registry` | the register published it | yes |
| `name-strong` | page contains the full name, or its first two identity-bearing words | yes |
| `name-weak` | page contains only one word of a multi-word name | **no** |
| `unresolved` | nothing verified | no |

Weak matches are kept with their evidence rather than discarded — `nomura.com`
really is right for *Nomura Financial Products Europe GmbH* — but nothing
downstream may use one until it is confirmed.

Four false positives shaped those rules, and all four are instructive:

- `australia.com`, the **tourism board**, for *Australia and New Zealand Banking
  Group* — one word out of six is not evidence.
- `societe.com` for *Societe Generale*, the same way.
- `citadel.com` for *Citadel Securities* — a different employer with a different
  careers page, and exactly the merge the roster is careful to keep apart. It
  happened because the bare first word was tried before `citadelsecurities`.
- `marketfrance.com` for *Market Securities France SA*, which "proved" itself by
  printing its own domain on the page. The domain was what we guessed, so the
  evidence was circular. Matching is on spaced phrases only for this reason.

The cache is keyed on the firm's **name**, not its id, because `firms` is
rebuilt from scratch on demand and ids are not a durable handle. Failures are
cached too — most firms are unresolvable, and re-probing them every run is the
bulk of the cost.

## Adding a registry

Drop a module in `quantscraper/registries/` exposing `NAME`, `JURISDICTION`,
`MIN_EXPECTED` and `fetch() -> list[Employer]`, then add it to `REGISTRIES` in
that package's `__init__.py`. Nothing else needs to change.

`PLAN.md` holds the build order and the geographic priority. In short: focus is
**Stockholm, Copenhagen, Amsterdam, Switzerland, Dubai, Hong Kong, Singapore**;
Germany, the US, London and China are deprioritized. That governs what gets
built next, never what gets ingested — collected data is never dropped for
being out of area.

Next sources, in order: Finanstilsynet (DK), FINMA (CH), SFC (HK), MAS (SG),
DFSA/FSRA (UAE), then the Nasdaq Stockholm and Cboe Europe participant lists.
