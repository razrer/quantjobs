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
python -m quantscraper stats
```

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
  a residual hole that no public list closes. Realistic fixes are the Cboe
  Europe participant list, the AFM's separate own-account-trader notification
  list, or accepting a small hand-maintained seed file.
- **State-registered US advisers are absent.** The ADV bulk file is SEC
  registrants only (`Firm Type` is uniformly `Registered`); advisers under
  roughly $110M AUM register with their state. This resolves the plan's open
  verification question — the answer is no, and the sub-$110M US tail needs a
  separate source.
- **AP1–AP4 and AP6 are absent.** Only AP7 is FI-supervised; the other buffer
  funds are governed by their own act and appear in no FI category. They are
  significant Stockholm employers and need seeding separately.
- **IPM is absent, and that is correct** — the firm wound down. The plan's
  named roster is slightly stale here.
- **The UK is not covered.** Every FCA route — register API, bulk download —
  returns 401/403 without an API key, and the key needs an account you have to
  register for yourself. Worse, the API has no "list all firms" endpoint, only
  per-firm lookups, so even with a key it cannot enumerate a universe. FCA is
  therefore an *enrichment* source (checking the `dealing in investments as
  principal` permission on firms found elsewhere), not a registry. London is
  currently reachable only via `sec_adv`/`fia_epta` entities.

**Entity resolution is the next real problem.** Firms hide behind legal names:
Tower Research trades as `LATOUR TRADING LLC`, HRT as `HRT FINANCIAL LP`. Name
matching across sources will need the alias table the plan describes.

## Adding a registry

Drop a module in `quantscraper/registries/` exposing `NAME`, `JURISDICTION`,
`MIN_EXPECTED` and `fetch() -> list[Employer]`, then add it to `REGISTRIES` in
that package's `__init__.py`. Nothing else needs to change.

Highest-value next sources, by coverage per unit of effort:

1. **Entity resolution**, before more sources. At 30,500 rows the same firm now
   appears up to four times under different legal names, and every further
   registry makes it worse rather than better.
2. **Nasdaq Stockholm and Cboe Europe participant lists** — same shape as
   `eurex`; Cboe is also the best remaining shot at the sponsored-access firms.
3. **Finanstilsynet** (Denmark) and **BaFin** (Germany) — same shape as the
   registries already built.
4. **AMAC** (China) — the Shanghai quant funds; expect anti-bot friction.
5. **FCA** (UK) — needs an API key you must register for, and only works as
   enrichment rather than enumeration. See `ACTION-REQUIRED.md`.
