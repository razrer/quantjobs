# The firms with no recruiting pipeline

Notes for curiosity, not for the scraper. **Nothing here is read by any code.**
`seed.py` reads `registries/seed_firms.csv` and nothing else, so a name can sit
in this file indefinitely without touching the employer universe. That is the
point: these are names I could not verify well enough to put in the pipeline,
kept where they cost nothing.

The premise comes from a practitioner forum thread describing a tier of firm
that reportedly pays above Citadel and Jane Street with better hours, but has
no campus milkround, no recruiter relationships and no job board — so the
applicant pool stays small and the bar, in relative terms, is easier to clear.
Whether that is true is exactly what is hard to establish, because a firm with
no recruiting pipeline also leaves no recruiting evidence.

## The four unverifiable names

These surfaced together in one comment and nowhere else:

| Name | Web presence | In any registry we hold | US visa filings |
|---|---|---|---|
| QBR | none | none | 0 |
| Tricore Financial | none (name collides with a New Mexico medical lab) | none | 0 |
| MQI | none | none | 0 |
| Mostrum | none | none | 0 |

Three independent checks, all negative:

1. **Web search** — every query returns unrelated companies.
2. **The 79,000-row employer universe** — 13 registries including the full SEC
   adviser and broker-dealer files. Nothing.
3. **US Department of Labor LCA disclosures** (`h1bdata.info`, queryable by
   employer) — the strongest test, because any firm sponsoring a foreign hire
   must file a public wage record. Zero for all four.

**But zero LCA records does not mean a firm is fictional**, and it is worth
being precise about that, because the same query returns zero for *Headlands
Technologies*, *Aquatic Capital* and *Domeyard* — all three unambiguously real,
all three sitting in our own database. A firm that hires only citizens and
green-card holders never files. So the honest reading is not "these four do not
exist"; it is **"if they exist, they leave no trace any tool can follow"** —
which for a job hunt amounts to the same thing. You cannot apply to a company
you cannot find. Two of the four (QBR, MQI) read like internal initialisms,
which would explain a name that circulates verbally and appears nowhere else.

I left them out of `seed_firms.csv` deliberately. A row there costs a domain
probe and returns no listings forever; the file's job is firms the pipeline can
eventually reach.

## The tier that *is* real, and is nearly as quiet

More interesting, because it is checkable. These are genuinely tiny shops —
some under ten people — that do appear in wage disclosures. The pattern is
consistent: one or two offices, a handful of filings, no graduate programme.

| Firm | Records | Median base | Where |
|---|---|---|---|
| TGS Management | 5 | $275,000 | California |
| Linden Shore | 2 | $200,000 | New York |
| Evergreen Statistical Trading | 1 | $200,000 | Washington |
| Boerboel | 12 | $180,437 | Chicago, New York |
| Radix Trading | 17 | $175,000 | Chicago, Boston, New York |
| Vatic Labs | 3 | $175,000 | California, New York |
| Quest Partners | 5 | $170,000 | New York |
| Nebula Research & Development | 4 | $169,587 | New York |
| Jocassee Quantitative | 2 | $162,500 | New York |
| Tanius Technology | 24 | $100,000 | Alamo, California |

**These are base-salary floors, not total compensation.** An LCA states the
offered wage; at these firms the bonus is usually the larger half and is not
disclosed anywhere. So TGS at $275,000 base is not in tension with forum
claims of seven-figure total comp — the two numbers measure different things.
Read the column as a ranking signal, not an offer.

A few observations worth the detour:

- **Tanius Technology files from Alamo, California** — a town of about 14,000
  in the East Bay hills, no financial district anywhere near it. Twenty-four
  filings from there is the clearest single illustration of what this tier
  looks like: a serious quant employer operating somewhere nobody would think
  to look, at a nominal base that undersells it.
- **Evergreen Statistical Trading files from Washington state**, not Chicago,
  despite being a Radix spinout. Spinouts scatter geographically far more than
  the parent firms do.
- **Radix's 17 filings across three cities** make it the most visible firm on
  this list, which is a useful calibration: if 17 is "visible", the shops
  filing one or two are effectively invisible, and the ones filing zero are
  beyond reach entirely.

## Why this tier is structurally hard to find

It is the same reason the scraper needs a hand-written seed file at all. A firm
becomes enumerable when something forces it into a public list — a licence, an
exchange membership, a securities registration. A small partnership trading its
own capital triggers none of those. It has no clients, so no regulator
registers it; it trades through someone else's membership, so no exchange names
it; it hires by referral, so no job board indexes it.

The practical consequence for a job hunt: **this tier is reached through people,
not through search.** Every automated route — including this scraper — is
structurally blind to it. The scraper's job is to exhaustively cover the firms
that *are* reachable, so that whatever time you spend on networking is spent on
the ones that aren't.

## If you want to chase the four anyway

The one route that might work is asking someone who would know, in a venue
where the answer is cheap to give — the same forums the names came from. A
reply naming the actual legal entity would be enough; with a legal name, the
LCA database and the SEC files both become searchable, and the firm either
appears or is settled as folklore.

Worth knowing that some of these names do turn out to be folklore. The
methodology file already records the cost of a false positive: a bare
`Grasshopper` in the audit roster matched an unrelated `GRASSHOPPER ESCAPEMENT,
LLC` and reported a hub better covered than it was. A firm that does not exist,
believed in, is worse than one you never heard of.
