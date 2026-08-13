# Things only you can do

Work that is blocked on your input, in priority order. Each item says what to
do, where to put the result, and what I will build once it is there.

Nothing here is urgent — the project runs fine without any of it. These are the
places where I hit a wall that needed a human, not a decision I should make for
you.

**Since deprioritizing Germany, the US, London and China, nothing in the
near-term plan is blocked at all.** Item 1 was the only true blocker and it is
now optional. Item 2 is a small convenience and item 3 is a judgement call.

---

## 1. FCA API key — unblocks the UK *(deprioritized — only if you want London back)*

**You have since deprioritized London, so this is now optional.** Nothing in the
current plan waits on it; the FCA was the only blocked source, so the near-term
work is now entirely unblocked. Left here in full in case you change your mind.

**Why it is blocked:** every FCA route (register API, bulk download) returns
401/403 without credentials, and getting them means creating an account. I don't
create accounts on your behalf, so this one is yours.

**What to do:**

1. Go to https://register.fca.org.uk/Developer/s/ and sign up.
2. You get an **email address** and an **API key**.
3. Put them in a file called `.env` in the repo root:

   ```
   FCA_EMAIL=you@example.com
   FCA_KEY=your-key-here
   ```

   `.env` is already in `.gitignore`, so it will not be committed. Do not paste
   the key into chat — the file is enough, I will read it from there.

**Set expectations, because this one disappointed me:** the FCA API has no
"list all firms" endpoint, only per-firm lookups. So it *cannot* enumerate a UK
universe the way the other registries do. What it is genuinely good for is
enrichment — specifically the `Dealing in investments as principal` permission,
which the plan calls the single best proprietary-trading signal available. So
the realistic UK plan is: discover UK firms from other sources, then use FCA to
check permissions on them.

If enumerating UK firms matters more to you than the permission flag, say so —
Companies House has a free bulk product that lists every UK company, and SIC
codes 64/66 narrow it to financials. It is noisier but it does enumerate.

---

## 2. Confirm the msys2 Python workaround, or let me pin the interpreter

**Resolved — (b) implemented.** `run.ps1` and `run.sh` now call the Windows
Python directly. Use either:

```powershell
.\run.ps1 fetch
.\run.ps1 stats
```

```bash
./run.sh fetch
```

---

## 3. A decision I need from you: how hard to chase sponsored-access firms

**Resolved — (b) and (c) both implemented.**

**Cboe Europe (`cboe_europe`)** — new registry added. Fetches the 52-firm
trading participant list from Cboe's European equities venues live. Run
`.\run.ps1 fetch` to ingest them.

**Seed file (`seed`)** — new registry backed by
`quantscraper/registries/seed_firms.csv`. Pre-populated from an online search
with:
- Amsterdam: Da Vinci Derivatives, Maverick Derivatives, ORA Traders, Nino
  Options, Five Rings (AMS office), VivCourt Trading (AMS office)
- Stockholm: AP1–AP4, AP6 (buffer funds governed by AP-fondlagen, not
  FI-supervised)

Edit `seed_firms.csv` freely — lines starting with `#` are comments. Add any
firm you encounter that belongs in the universe; the format is:
`name,city,country,category,website`

---

## 4. Optional: tell me if any of the plan's named roster is stale

**Answered — researched online, August 2026.** All of it is now encoded in
`quantscraper/roster.csv`, which `python -m quantscraper audit` reads. Stale
entries are marked so they no longer read as coverage bugs.

**If you want to add or remove firms, edit that file** — same idea as
`seed_firms.csv`. One caveat: keep names specific. A bare `Grasshopper` entry
matched an unrelated `GRASSHOPPER ESCAPEMENT, LLC` and reported Singapore
better covered than it was. `audit -v` shows what every entry matched, which is
how to check one.

Note this file is the *audit set*, not the universe — adding a firm here makes
me measure whether we found it, it does not add it to the database. Use
`seed_firms.csv` for that.

Known stale or changed entries (do not treat absence as a coverage bug):

- **IPM** — wound down December 2021. Correctly absent.
- **AP1–AP4 and AP6** — not FI-supervised; seeded via `seed_firms.csv` (item 3c).
- **GAM Systematic** — GAM's quantitative unit shed assets from $500M to ~$120M
  under restructuring in 2024–2025; the lead quant left. The parent GAM Holding
  still operates but the systematic/quant arm is effectively defunct. Roster
  entry "GAM" for Switzerland can be kept but treat it as low-priority.
- **Norron** — selling its fund management business to Simplicity AB (announced
  July 2026). Still operating under the Norron name for now; revisit once the
  transfer completes.
- **Webb Traders** — being acquired by Marex Group (deal announced February
  2026, expected Q2/Q3 2026). Not closed; will operate as part of Marex.
  Update the audit fixture if/when it stops appearing under its own name.

Everything else in the named roster checked out as active (Atlant, Nordkinn,
Captor, Norron, Coeli all confirmed operating as of mid-2026; Unigestion merged
its PE platform with Sagard but quant/liquid alts still active).

---

## Answered already — no action needed

Recording these so they don't get re-asked:

- **Storage** → SQLite. *(you chose this)*
- **Classification** → keyword-only for now, no LLM spend. *(you chose this)*
- **Build order** → Layer 1 registries before ATS extraction. *(you chose this)*
- **Does the SEC ADV bulk file include state-registered advisers?** No. The plan
  listed this as an open verification question; the answer is no, `Firm Type` is
  uniformly `Registered`, and the sub-$110M US adviser tail needs its own
  source. No input needed from you — just don't expect those firms to be there.
- **Python interpreter workaround** → `run.ps1` / `run.sh` wrappers added.
- **Sponsored-access gap** → Cboe Europe registry + seed file both wired in.
- **Roster staleness** → researched; stale entries recorded above in item 4.
