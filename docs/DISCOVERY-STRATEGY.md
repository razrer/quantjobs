# Finding less visible employers

Investigation: 12 September 2026. Priorities: Hong Kong, Singapore, Stockholm.
Public, free, local execution. A small public footprint is not evidence that a
firm is deliberately secretive. Employer existence, group affiliation, local
operations, and an advertised vacancy are four separate claims.

## What the pilot actually found

| Check | Result | Implication |
|---|---|---|
| HKEX market-maker/LP code tables | 46 distinct code/name pairs; all names already matched a normalized employer name | Useful prioritization and corroboration, not 46 new employers |
| Yue Kun Research | SFC employer present; domain lookup unresolved; official homepage invites applications | Improve domain resolution and recognize general invitations separately from vacancies |
| UTR8 | Group domain known; careers classified tier B; no board cards; homepage advertises Graduate Trader in Utrecht and Hong Kong | A page watcher looking for job links misses inline vacancies; a direct reader now covers this layout |
| Starfish Bay | Employer present, but “strong” domain pointed to an unrelated author's site | Exact name overlap is insufficient evidence of ownership; reject that particular match |
| Linitics | Absent from employer records; official site describes Singapore quantitative proprietary trading; ACRA confirms live entity 202038529K | Corporate enumeration can find an employer outside our financial-register coverage |
| Lake Toba Trading | Absent from employer records; ACRA confirms live entity 202031319N; FINRA identifies an HRT affiliate | A new legal entity is not necessarily a new recruiting channel |
| Tidan / Volt Capital Management AB | Already in employer records; official careers/contact pages checked | These are outreach/channel questions, not universe-discovery successes |
| Registry freshness | FI, MAS and SFC last successful runs: 22 August; weekly job sequence does not refresh them | A standing job sweep alone cannot find newly registered employers |

These are targeted probes, not a random sample or a market-recall estimate.
Raw captures and local comparison output are under gitignored `logs/`.
The separate outreach file is local only: `docs/OUTREACH-FIRMS.md`.

## Priority 1: follow organizational relationships, not just names

For Hong Kong and Singapore, inspect the **Organization Affiliates** section of
US broker disclosures for firms with local exchange activity. The [HRT FINANCIAL
LP report, page 19](https://files.brokercheck.finra.org/firm/firm_152144.pdf)
identifies Starfish Bay in Hong Kong and Lake Toba in Singapore under the same
corporate parent. This is a concrete route from obscure legal names to a known
group. Follow the group's official careers channel, then verify the local role.
Do not assume every group vacancy is employed by either subsidiary.

Store relationships as evidence-backed edges: `affiliate_of`, `former_name`,
`managed_by`, `advised_by`, `careers_at`. **Do not merge legal entities merely
because they share a parent, office, administrator, or recruitment platform.**
This also avoids “discovering” a large firm's subsidiary as a new boutique.

The [HKEX product market-maker/LP list](https://www.hkex.com.hk/Products/Listed-Derivatives/Market-Maker-Program/List-of-Market-Makers_Liquidity-Providers?sc_lang=en)
is a better starting queue than generic searches for “quant firms”: it establishes
specific market activity. Preserve product memberships when unioning names.
Exchange participation does not by itself establish a staffed local office.
This pilot does not justify another registry adapter solely on name novelty.

## Priority 2: Singapore corporate records beyond MAS

[ACRA's open-data initiative](https://www.acra.gov.sg/resources/open-data-initiative/)
provides monthly public entity information. Its [corporate collection](https://data.gov.sg/collections/2/view)
has 27 alphabet/other partitions. The live metadata and a filtered request to the
[documented datastore endpoint](https://guide.data.gov.sg/developer-guide/dataset-apis/search-and-filter-within-dataset)
worked without an account or key. Both pilot entities were returned from the
[L partition](https://data.gov.sg/datasets/d_a2141adf93ec2a3c2ec2837b78d6d46e/view).

Both had primary activity code **64999**, while their descriptive activity fields
were `na`. A narrow “proprietary trading” text query or a guessed industry code
would miss them. Do not pretend the two name lookups constitute enumeration.

Implementation strategy: retain the full monthly corporate snapshot locally;
queue primary and secondary finance activities, technology/research descriptions,
former names and evidenced group links for review. Add an exploration sample of
the residual population so ranking cannot become a permanent exclusion. Keep
corporate-registration evidence distinct from evidence that an entity hires quants.
Never infer trading activity from an industry code alone.

Before building the bulk adapter, verify every partition, advertised counts,
stable UENs, snapshot dates, and schema changes. Collection-level coverage dates
were stale compared with individual dataset dates in the live response: use
partition metadata, and report discrepancies. Bulk refresh is proposed, not yet
implemented. The pilot only verified metadata and two exact-name lookups.

## Priority 3: Stockholm fund platforms and investment teams

The licensed manager is not always the brand or team doing the research.
Enumerate public fund-platform client lists and fund reports, then follow the
named investment managers and advisers to their own sites. [ISEC's fund-hotel
offering](https://www.isec.com/our-offerings-isec/manco) provides a concrete entry
point. Its [2025 RAIF report, page 3](https://www.isec.com/wp-content/uploads/2023/09/Annual-report-ISEC-SICAV-RAIF-31.12.2025.pdf)
separately names the AIFM, investment managers and administrator, including
Stockholm-based Finserve Nordic. Preserve those roles instead of treating them
all as the employer. Fund domicile is not the research team's location.

[Brummer's 2024 commentary](https://www.brummer.se/en/newsroom/2025/Brummer-Multi-Strategy-commentary-2024/)
describes infrastructure for onboarding investment teams as pods. Monitor new
team and strategy announcements as well as new company names: some hiring will
remain on the platform's central careers page. Do not invent a separate firm
for a strategy name. This route is verified as a source of relationships; its
incremental employer/job yield has not yet been measured.

Secondary discovery samples: public university thesis acknowledgements, employer
fair exhibitors, quant-competition sponsors, and market-infrastructure customer
stories. Extract organizations and public organizational links, not personal
contact graphs. A historical sponsor is a lead, not proof of current hiring.

## Make discovery recurrent and accountable

Proposed local cadence, without creating another scheduled task in this change:

- Monthly: refresh FI/MAS/SFC and relevant exchange lists, resolve new records,
  revisit unresolved domains and careers channels, and compare corporate snapshots.
- Weekly: review newly evidenced target-hub employers, inline careers pages,
  group hiring channels, and source failures alongside the existing job sweep.
- Monthly: inspect a bounded sample of low-ranked/unresolved candidates and public
  ecosystem sources. Carry forward unvisited work by oldest attempt; don't keep
  spending the entire discovery budget on familiar firms.

Track per route: organizations observed, genuinely new entities, new independent
groups, verified local careers channels, actual jobs acquired, unresolved identity
cases, and age of oldest unvisited candidate. Report zero-yield pilots too.
Record source URL, observed date and relationship type for each candidate. Keep
unverified leads pending; keep verified firms with no vacancy in the private
outreach Markdown, never as invented job cards.

## Duplicate strategy

Retain the existing conservative exact/near-copy folds and all raw source rows.
For remaining same-firm, same-title, same-stated-place cards, add a **similar
postings** display bundle. Every version retains its link, eligibility, tags,
deadline, save state and correction controls. Filters run before bundling.
Missing locations do not group. Different requisitions are not declared identical.
The reader can choose stacking off to see every card individually.

Measured on the 4,854-card baseline: 91 cards form 40 bundles, reducing repeated
card slots by 51 compared with stacking off. All 4,854 IDs remain available,
including all 216 shortlisted cards. Browser checks opened three Jane Street
Hong Kong versions with their distinct fit ratings and links intact.

This reduces repeated cards without lowering the text-similarity threshold or
conflating separate graduate/experienced openings. It is a display strategy,
not a claim that every bundled pair is a confirmed duplicate.
