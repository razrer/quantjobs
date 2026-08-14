# Things only you can do

Work that is blocked on your input, in priority order. Each item says what to
do, where to put the result, and what I will build once it is there.

Nothing here is urgent — the project runs fine without any of it. These are the
places where I hit a wall that needed a human, not a decision I should make for
you.

**One thing is genuinely waiting on you** — item 1. Everything below it is
resolved or optional.

---

## 1. Label 100 postings, so the classifier has a fixture

**This is the last thing standing between Stage 11 and done**, and it is the
only kind of work I cannot do for you: it needs your judgement about your own
career, not mine.

**Why it matters.** The tagger currently rates 13 postings `apply_now` and 264
`strong` out of 55,455. I believe that is roughly right, and *believing* is the
problem. Stage 2 hit this exact wall with coverage: the numbers were checked by
ad-hoc greps until `roster.csv` made them repeatable, and that fixture
immediately found a false hit nobody had suspected. Tagging has no equivalent
yet, so "the lexicon improved" and "the market moved" are indistinguishable.

Six false positives have already been found by reading output by hand — a
recruiter role scored as a trading role, an insurance accounting role scored as
core quant three times over, `Graduate Trader` scored as a managing director.
Each was found by luck, in whatever happened to be on screen. A fixture finds
them on purpose.

**What to do.** Run this to get a spread across formats, hubs and verdicts:

```bash
python -m quantscraper list --limit 100 > sample.txt
```

Then for each posting write one line in `quantscraper/labels.csv`:

    ats,token,job_id,relevance,seniority,note

`relevance` is one of `core`, `adjacent`, `rejected`. `seniority` is one of
`intern`, `student_only`, `new_grad`, `junior_0_2`, `mid_3_5`, `senior_6_10`,
`lead`, `head_or_md`. The `note` is free text and is the most valuable column —
it is where "this says Trader but the body is an ops role" goes.

**The one rule that matters:** label what the posting *is*, not what the tagger
said. If you find yourself agreeing with a tag because it is already there, the
fixture is measuring nothing.

**What I will build once it exists.** `python -m quantscraper labels`, which
scores the current lexicon against your sample and prints every disagreement.
The exit criterion in `TAGGING.md` is ≥90% on `relevance` and `seniority` and
**no false `rejected`** — a wrongly rejected posting is the expensive failure,
a false positive costs you a few seconds of reading.

**Effort:** an hour or so, once. It does not need doing again unless the
lexicon changes shape.

---

## A. FINMA (Switzerland) — **done, and I was wrong about why it was blocked**

**Resolved. Nothing needed from you.** `finma_ch` is in, 2,824 institutions, and
Switzerland went from 6/11 *local* to **9/11**.

I had written this up as "FINMA serves an incomplete TLS chain, so urllib cannot
reach it", and offered you three unpleasant workarounds. That diagnosis was
wrong. FINMA's chain is fine. The problem was at our end: **Windows populates
its certificate store lazily**, so a fresh Python process trusted only the 38
roots that happened to be cached, and FINMA's was not one of them.

`curl` reached the site immediately, which is what gave it away — it ships its
own 152-certificate bundle. Two such bundles were already on this machine, from
Git and from msys2. `http.py` now loads one. No committed certificate, no X.509
parsing, none of the trade-offs I asked you to arbitrate.

The lesson is in `CLAUDE.md`: on Windows, `CERTIFICATE_VERIFY_FAILED` usually
means our trust store is short, not that their server is broken. Test with curl
before blaming the server.

---

## 0. DFSA public register — Dubai *(deprioritized; leave it unless you want Dubai back)*

**Why it is blocked:** the DFSA's public register at
https://www.dfsa.ae/public-register puts its search behind a Google reCAPTCHA.
I don't complete CAPTCHAs, so I can't reach it.

Dubai currently reads 7/7 firms *present* but only 3 *local* — ADIA, ADQ and
Mubadala come from the hand-maintained seed file, and Emirates NBD is visible
only through its **Singapore** banking licence. No Gulf-registered row exists
for any of them.

**What would help, in rough order of usefulness:**

1. **Check whether the DFSA publishes a bulk list** anywhere that isn't behind
   the CAPTCHA — an Excel or PDF "list of authorised firms". If you find one,
   put the URL here and I'll write the adapter.
2. **ADGM (Abu Dhabi)** — https://www.adgm.com/public-registers. I found no
   export link, but I did not get far. Worth a look if you're in there anyway.
3. If neither pans out, say so and I'll fall back to extending
   `seed_firms.csv` by hand for the DIFC firms that matter. That is a real
   answer, not a cop-out: the Gulf universe of quant employers is small and
   nameable, unlike the Nordics.

**You have since deprioritized Dubai, so none of this is needed.** Left in full
in case you change your mind. The six remaining focus hubs are all at 100%
present, and Dubai's roster firms are in the universe via the seed file — what
is missing is only a *locally registered* row for them.

---

## 1. FCA API key — **done**

**Resolved.** You supplied the credentials; they are in `.env`, which is
gitignored and has not been committed. `python -m quantscraper fca` works.

**One security note:** the key was pasted into chat, so it now exists in that
transcript as well as in `.env`. If that bothers you, regenerate it at
https://register.fca.org.uk/Developer/s/ and replace the value in `.env` — I do
not need to see the new one, and nothing else needs changing.

**What it turned out to be good for.** Not enumeration — that is now settled
rather than assumed:

- there is no bulk download;
- queries shorter than three characters are rejected;
- broad queries ("trading", "capital") return `Request Entity Too Large`, so the
  letter-sweep that enumerates the Danish register does not transfer;
- the only other handle is the FRN, a numeric space of about a million.

So `fca.py` sits outside `registries/` on purpose. Calling it a registry would
overstate coverage: it can only return what we thought to ask for.

**What it does do is supply websites**, which are the scarce resource — no
focus-region registry publishes a single one. `Firm/{FRN}/Address` carries a
`Website Address` and a `Country`. First 200 firms looked up: 29 domains, of
which 13 were non-UK entities (Cyprus, Ireland, Belgium, Spain, Luxembourg,
Germany, Slovakia). It also corrected one of my own guesses — Commonwealth Bank
of Australia resolves to `commbank.com.au`, where the guesser had offered
`commonwealth.com`.

Still available if you ever want UK *enumeration*: Companies House has a free
bulk product listing every UK company, with SIC codes 64/66 narrowing to
financials. Noisier, but it does enumerate. Not built — London is deprioritized.

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
