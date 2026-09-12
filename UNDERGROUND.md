# The firms with no recruiting pipeline

Historical notes below. The [September 2026 investigation](docs/DISCOVERY-STRATEGY.md)
tests additional public routes: corporate snapshots, affiliate disclosures and
fund-platform relationships. Sparse recruiting evidence does not make a firm
undiscoverable. Verified outreach leads are in local `docs/OUTREACH-FIRMS.md`.

Notes for curiosity. **Nothing here is read by any code** — `seed.py` reads
`registries/seed_firms.csv` and nothing else, so a name can sit in this file
indefinitely without touching the employer universe. That is the point: these
are names I could not verify well enough to put in the pipeline.

The premise comes from a practitioner forum thread describing a tier of firm
that reportedly pays above Citadel and Jane Street with better hours, but has no
campus milkround, no recruiter relationships and no job board — so the applicant
pool stays small. Whether that is true is exactly what is hard to establish,
because a firm with no recruiting pipeline also leaves no recruiting evidence.

## The four unverifiable names

**QBR**, **Tricore Financial**, **MQI** and **Mostrum** surfaced together in one
comment and nowhere else. Three independent checks, all negative: web search
returns unrelated companies, the 79,000-row employer universe holds none of
them, and US Department of Labor LCA disclosures (`h1bdata.info`, queryable by
employer) return zero for all four.

**But zero LCA records does not mean a firm is fictional**, and the same query
returns zero for *Headlands Technologies*, *Aquatic Capital* and *Domeyard* —
all three unambiguously real and in our own database. A firm that hires only
citizens and green-card holders never files. So the honest reading is not "these
four do not exist"; it is **"these checks did not verify their identity"**.
Corporate and affiliate evidence remains worth investigating. Two of the four read
like internal initialisms, which would explain a name that circulates verbally
and appears nowhere else.

They are deliberately out of `seed_firms.csv`: a row there costs a domain probe
and returns no listings forever.

## The tier that *is* real, and is nearly as quiet

More interesting, because it is checkable — genuinely tiny shops, some under ten
people, that do appear in wage disclosures. One or two offices, a handful of
filings, no graduate programme.

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
offered wage; at these firms the bonus is usually the larger half and is
disclosed nowhere. Read the column as a ranking signal, not an offer.

Two details worth the detour. **Tanius files from Alamo, California** — a town
of 14,000 in the East Bay hills with no financial district anywhere near it,
which is the clearest illustration of what this tier looks like. And **Radix's
17 filings across three cities make it the most visible firm on the list**,
which is the calibration: if 17 is "visible", the shops filing one or two are
less visible through this particular source. Zero filings does not establish
that other public sources cannot identify them.

## Why this tier is structurally hard to find

The same reason the scraper needs a hand-written seed file at all. A firm
becomes easier to enumerate when it appears in a public list — a licence, an
exchange membership, a corporate registration. A small partnership trading its
own capital may be absent from the financial-register and exchange lists we
collect, especially with sponsored access. Referral-only hiring can also leave
no job-board evidence. None of these absences proves it leaves no other trace.

Referrals can help, but public corporate records, group disclosures and service
relationships can reveal firms absent from licensing and job-board searches.
Those routes are incomplete too; record what was checked and what remains unknown.

If you want to chase the four, the one route that might work is asking someone
who would know, in the same forums the names came from. A reply naming the
actual legal entity would be enough: with a legal name, the LCA database and the
SEC files both become searchable and the firm either appears or is settled as
folklore. Some of these names do turn out to be folklore, and a firm that does
not exist but is believed in is worse than one you never heard of — the same
asymmetry as a bare `Grasshopper` in the audit roster matching `GRASSHOPPER
ESCAPEMENT, LLC`.
