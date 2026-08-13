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

`resolve` groups the raw registry rows into real-world firms; run it after
`fetch`. It rebuilds from scratch every time, so it is safe to re-run.

`audit` checks the universe against the named roster in
`quantscraper/roster.csv` and reports, per hub, how many of those firms it
found. `-v` lists what each hit actually matched, which is how a wrong match
gets caught — see [Coverage audit](#coverage-audit).

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
| `sec_adv` | US | ~23,300 | SEC Form ADV monthly bulk CSV, registered + exempt reporting |
| `sec_bd` | US | ~3,300 | SEC active broker-dealers; this is where the US prop firms are |
| `afm_nl` | NL | ~2,700 | AFM investment firms + fund managers, via CSV export |
| `fi_se` | SE | ~650 | Finansinspektionen, enumerated by regulatory category |
| `eurex` | EU | ~330 | Eurex admitted exchange participants, via CSV |
| `euronext` | EU | ~280 | Euronext trading members (AMS/BRU/DUB/LIS/MIL/OSL/PAR) |
| `fia_epta` | EU | 20 | European Principal Traders Association members |

About 30,500 employers in total.

`sec_adv` supplies a website for ~92% of its firms and `euronext` for ~36% of
its own, which is most of Layer 2's domain resolution for free.

The two exchange lists are small but do work nothing else does: **365 firms are
reachable only through exchange membership**, among them 3Red Partners,
AlphaGrep, ABC Arbitrage, Transtrend and Mint Tower Capital. See the gap note
on licence-exempt firms for why.

Coverage of the plan's named roster is good: `sec_bd` has Jane Street, HRT,
Jump, DRW, Citadel Securities, Optiver, SIG, XTX and Virtu; `afm_nl` has the
Amsterdam cluster (Optiver V.O.F., IMC, Flow Traders, Webb, All Options, 323
Trading, Mako, Maven, Tower Research Europe, Jane Street Netherlands).

## Design notes

**Enumerate, never query.** FI is walked category by category rather than
searched, so coverage does not depend on guessing the right keyword.

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
- **`fi_se` walks 20 of FI's 139 categories**, and the omissions are not all
  funds. Alecta, Sweden's largest occupational pension manager, is a mutual
  (*ömsesidigt*) undertaking rather than a `Tjänstepensionsaktiebolag`, so it
  falls outside every category walked. Found by the coverage audit; fixable by
  adding the category.
- **Dutch pension asset managers are DNB-supervised, not AFM.** PGGM is absent
  entirely and APG is present only through its US entity, because only the AFM
  register is ingested. The methodology names the DNB register; it is not built.
- **Sovereign wealth funds appear in no financial register.** ADIA, ADQ,
  Mubadala, GIC and Temasek are all significant quant employers and none is
  reachable by any registry. The seed file is the only realistic route.
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

Current state: 30,590 rows → 28,747 firms. The collapse is modest because most
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

Current focus-hub results:

| Hub | Present | Local |
|---|---|---|
| Stockholm | 19/20 | 19 |
| Amsterdam | 12/13 | 11 |
| Switzerland | 9/11 | 5 |
| Copenhagen | 5/7 | 3 |
| Singapore | 7/10 | 2 |
| Hong Kong | 9/9 | 1 |
| Dubai | 3/7 | 0 |

Every miss carries a written reason in the roster's `note` column, and the audit
prints it, so a miss is never just a blank. Stale entries (IPM, wound down in
2021) and entries that never named a real firm (AP5 — there is no *Femte
AP-fonden*) are marked and excluded from the rates, so they stop reading as bugs.

**A false hit is the failure this guards against**, because it hides a miss.
`-v` prints the employer names each entry actually matched: a bare
`Grasshopper` matching `GRASSHOPPER ESCAPEMENT, LLC` reported Singapore as
covered when it was not, and was only visible because the matched name is shown.

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
