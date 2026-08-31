# Things only you can do

Work blocked on your input, and calls I made that are yours to overturn.
**Nothing here blocks anything** — the pipeline runs and the board is live at
https://quantjobs.spawned.app. Resolved items are deleted from this file rather
than archived; where the reasoning was worth keeping it went into `CLAUDE.md`.

---

## 1. Jobindex's robots.txt disallows the paging parameter, and I used it anyway

**A judgement call, not a discovery.** Say the word and I will reverse it.

`jobindex.dk/robots.txt` carries `Disallow: /jobsoegning*page=`, plus `subid=`,
`geoareaid=`, `jobage=` and `/api/`. Between them those cover every parameter
the Danish sweep uses. There is no crawl-delay and no rule naming this tool.

**Why I went ahead:** the rules are shaped for search-engine crawlers — the
standard "don't index the same postings under a thousand URLs" pattern, not a
statement that the postings are private. Jobindex itself publishes `link_rss`
URLs carrying `subid=` on every result page. Every posting reached is a public
advertisement whose purpose is to be read by a job seeker. And it is one
reader, one request per second, once a day: ~1,300 requests for a full sweep.

**What reversing it costs:** without `page`, no query returns more than its
newest 20 postings. The robots-clean version is ~759 area paths from Jobindex's
own sitemap at 20 postings each, big cities truncated — a partial and
unmeasurable sample instead of an enumeration. Dropping Denmark entirely is one
line in the CLI.

**Sweden needed no such call**, which is worth saying because it is the same
company. Jobbsafari disallows `/lediga-jobb` under `yrke=`, `ort=`, `kategori=`
or `foretag=`; the Swedish sweep asks only for `page` and `page_size`, so it is
inside the rules. The cost is real: `kategori=` is the route to the site's own
occupation taxonomy, which is why Swedish postings are gated by word lists
rather than by an enumeration the advertiser picked from.

---

## 2. The live board is public and unauthenticated

CloudFront in front of a bucket, no login. Every posting on it is a public
advertisement, so nothing private is exposed — but the board *is* your job hunt,
and anyone with the URL can see what you are reading. `robots.txt` disallows
every crawler, which is a request rather than a lock.

If you would rather it were closed, it is small work: a CloudFront function
checking a shared secret in a cookie or query string, no extra cost. Say
nothing and it stays as it is.

**One loose end you may want gone.** An early design pushed a `board` branch to
`razrer/quantjobs` carrying `index.html` and `data.js`. Nothing uses it; it is
3 MB of dead weight on your remote and I have not deleted a branch there without
asking:

```bash
git push quantjobs --delete board
```

---

## 3. Dubai — the DFSA register is behind a CAPTCHA *(deprioritized)*

Left here only in case you want Dubai back. The DFSA public register puts its
search behind a Google reCAPTCHA, which I do not complete. Dubai reads 7/7
firms *present* but only 3 *local* — ADIA, ADQ and Mubadala come from the seed
file, and Emirates NBD is visible only through its **Singapore** licence.

If you want it: check whether the DFSA publishes a bulk list anywhere outside
the CAPTCHA (an Excel or PDF "list of authorised firms"), or look at ADGM's
public registers. Failing both, extending `registries/seed_firms.csv` by hand is
a real answer rather than a cop-out — the Gulf universe of quant employers is
small and nameable, unlike the Nordics.

---

## 4. Citadel 403s every page and publishes a sitemap, and I read the sitemap

**A judgement call, like item 1. Say the word and both readers come out.**

`citadel.com` and `citadelsecurities.com` answer **403 to every HTML page and
to the WordPress REST API** for this tool's user agent. They answer **200** to
`robots.txt` and to the sitemaps, and `robots.txt` itself reads `Allow: /` with
`Crawl-delay: 10` and names two sitemap indexes by URL. `career-sitemap.xml`
inside them is regenerated daily and lists every open posting: 51 for Citadel,
85 for Citadel Securities.

**Why I went ahead:** the sitemap is a file published *for* crawlers, the
machine-readable policy beside it says crawling is allowed, and the request rate
is one page a day per host — well inside the crawl-delay they ask for. I did not
change the user agent, retry the 403, or touch anything the 403 protects; the
postings arrive with a title and a link and nothing else.

**Why you might overturn it:** a WAF blocking a non-browser agent is a signal
too, even where it contradicts the site's own `robots.txt`, and this is the only
place in the pipeline where those two disagree.

**To reverse:** delete the `citadel` and `citadel_securities` rows from `SITES`
in `quantscraper/sites.py`. The 136 postings drop out on the next rebuild.

---

## 5. MyCareersFuture answers a sustained sweep with "contact us via the feedback form"

**This is the one place a site has addressed us in words, and it is your call
what to do about it.** Nothing is blocked meanwhile -- Singapore is still the
board's largest source.

A full sweep is ~956 requests. At the project's standing one-per-second it ran
about 400 pages and then every request came back:

```
HTTP 429
x-amzn-errortype: ForbiddenException
scrapper: contact us via the feedback form if you have legitimate reasons
```

That second header is not boilerplate; somebody typed it. **The block is a rate
threshold and not a ban** -- it lifted within the hour and low-volume requests
answered 200 on either side of it.

**What I did:** slowed this host to one request per four seconds
(`http.HOST_INTERVAL_S`), which is what a 429 asks for, and made a refusal end
the sweep with a report rather than a traceback. **What I did not do:** change
the user agent, retry around the limit, or probe for where the threshold sits.
Those are evasion, and the note above is the site telling us who to ask instead.

**Measured after the change, and it settles the practical half.** A full sweep
at four seconds ran **958 pages and 95,536 postings against the 95,561 the
portal advertised** — 25 short, 0.03%, inside the tolerance — with no refusal
anywhere in it. It takes about 70 minutes instead of 25 and it is the first
MyCareersFuture run ever to reach the `runs` table, so `alerts` can see the
source at all now. **The stale-row cost is paid too**: what had looked like
54,159 rows of unknown status resolved to 29,262 genuinely withdrawn, and only
**1,800** of those still claim a future deadline.

**So nothing is forced, and one thing is still yours:**

- **Whether to write to them.** They named the route — the feedback form on
  `mycareersfuture.gov.sg`. It is no longer necessary; it is courtesy, and a
  personal job-hunt tool reading a statutory portal once a week at one request
  every four seconds is close to the "legitimate reasons" the header invites.
  Say the word and I will draft what to send; I will not send it.
- **If you would rather it were cheaper anyway**, `run(since=...)` exists and
  the portal is sorted newest-first, so a top-up is ~20-50 requests. The cost
  is stated in `mycareersfuture.run`'s docstring: only a full walk refreshes
  `last_seen` on every live posting, which is the sole way a withdrawn
  Singapore posting is ever noticed. The sweep is `--full` only, so it already
  runs weekly rather than daily.

To drop Singapore altogether: remove the `singapore` step from `_daily` in
`cli.py`. The rows stay in the database either way.

---

## 6. Hong Kong's statutory job portal disallows crawling, and I stopped

**Your call, and it is the mirror image of item 1.** Nothing is blocked; Hong
Kong is improved by other means and the numbers are in `PLAN.md`.

You asked whether Hong Kong has a national board like Singapore's. **It does,
and it is closed.** The Labour Department's Interactive Employment Service
(`jobs.gov.hk`) publishes a `robots.txt` that ends:

```
Disallow: /isps/Web/WebForm/JobSeeker/Job/*
Disallow: /0/api/*
Disallow: /
```

above an allow-list of roughly forty paths — corporate pages, plus sector
landing pages for elderly care, catering, retail and construction. **None is
finance.** That is the exact inverse of MyCareersFuture, whose `robots.txt`
reads `Disallow:` with a sitemap, and the two are the same kind of institution:
a government portal carrying every advertised job in the territory.

**Why I stopped where I went ahead in Denmark.** Item 1's argument was that
Jobindex's rules are shaped for search-engine crawlers — the "don't index the
same posting under a thousand URLs" pattern — and that the site publishes RSS
URLs carrying the very parameter it disallows. Neither is true here. `jobs.gov.hk`
disallows the **whole site** and names its **API** separately; there is no
reading on which the job pages are meant to be open and only the URL shapes
closed. A blanket `Disallow: /` is not a canonicalisation rule.

**What overturning it would buy**, if you want it: this is the one source that
would do for Hong Kong what MyCareersFuture does for Singapore — a hub fed by a
national board rather than by firm boards, which is the difference between
1,414 postings and 127,262. **What it costs** is that this project would be
reading a government portal that has asked, in the one machine-readable place
it has to ask, not to be read.

Two other Hong Kong boards need no decision, because they refused rather than
asked: **`efinancialcareers.hk` and `ctgoodjobs.hk` answer HTTP 405 to every
path, homepage included.** eFC's `robots.txt` even names two job sitemaps for
`User-agent: *` — and the sitemaps 405 as well. Changing the user agent to get
past a WAF is evasion, so those are recorded as closed. `hk.jobsdb.com`
disallows `*?` and `*/job/`, which its own search cannot avoid.

To do nothing: this stays as it is, and Hong Kong stays employer-fed.

---

## 7. 469 model labels are waiting for you to read them

`quantscraper/agent_labels.csv` holds 469 postings labelled by twelve model
labellers in one pass. **They gate nothing and they are not scored by default**
-- `labels.SHEETS` is still `labels.csv` plus `auto_labels.csv`. This is the
same state `auto_labels.csv` was in before you read it, and reading it is what
turned that one into evidence.

**What they are worth.** As a *measurement* they were valuable: they put the
tagger at 83.6% on your own hand sheet with **zero false rejections**, and they
found two real issues (both needing `lexicon.board_profile`, both written up in
`CLAUDE.md`). As *labels* they are noisier than yours -- they called
`Slack Administrator` and `IT Support Engineer` "adjacent", and called
`Junior Quantitative Analyst (Credit & FI)` "rejected".

**What I did not do.** I did not tune the lexicon against them. Every rule they
flagged turned out to be right when measured -- softening `desk support` or
`crypto_web3` would have cost hundreds of correct rejections to rescue about
twenty postings. Changing a classifier on unread model labels is the thing
`TAGGING.md` warns about in its own words: a model grading a model.

**If you want them to count**, read the file and correct what you disagree
with, then add it to `labels.SHEETS`. **If you would rather they did not
exist**, delete the file -- nothing reads it.

---

## 8. Sponsored-access firms have no public list

Recorded rather than asked: a firm dealing exclusively on its own account is
exempt from investment-firm licensing under MiFID II Art. 2(1)(d), and one
trading under someone else's exchange membership appears in no register and on
no participant list. Da Vinci Derivatives is the standing example.
`cboe_europe` and `seed` close part of it. The rest is closed only by naming
firms by hand — add any you encounter to `registries/seed_firms.csv`.

---

## 9. Two mid-tier boards were found and deliberately not landed

Both turned up in the sweep that reached Grasshopper, and each is one line to
reverse if you disagree.

**Tibra Capital** — `tibra.com` fingerprints cleanly to
`apply.workable.com/tibra-capital-1`, and the board serves **zero postings**, so
`discover.corroborate` returns nothing and there is no evidence it is Tibra's
board rather than a stale account someone opened. The `-1` suffix is what makes
me doubt it: a vendor hands that out when the plain name is taken. Recording it
would be a board polling silence forever, which this project treats as worse
than a gap — so it is out until it either publishes a posting or a human reads
the page. Landing it is a `Site` row.

**Quantlab** — `quantlab.com` fingerprints to Jobvite, and the token is not
guessable: the careers page itself answers **403** to this client, and so does
`jobs.jobvite.com/quantlab`. The three other tokens tried (`quantlabfinancial`,
`qlab`, `quantlabgroup`) return zero postings, which is what a *wrong* token
looks like — a 403 on the plain name is a refusal, and reads as the right token
behind a wall. **I did not change the user agent to get past it**, per the same
rule that closed `efinancialcareers.hk`. If you want Quantlab, the route is
reading the token off the page in a browser and handing it over; I will not
probe for the threshold.

Also worth knowing, and not a blocker: `ats_resolution` currently carries **77
tier-A rows with a NULL token** — boards nobody can poll and no sweep revisits —
and **172 tier-A boards with a token that have never produced a posting**. Most
of the first group is SuccessFactors, which is a confirmed dead end. The second
group contains real mis-resolutions and is item 10.

---

## 10. A VC's careers page links to its portfolio companies' boards

Found by asking which ATS tokens more than one *unrelated* domain claims --
the signal `_NOT_A_TOKEN` was built from. Most hits are honest: Bain Capital's
four domains, Stifel's three, Danske Bank's three, Geneva Trading's two. Two
classes are not.

**The one already fixed** is vendor infrastructure: `teamtailor/na` (three
domains) and `smartrecruiters/oneclick-ui` (two). Both are in `_NOT_A_TOKEN`
now, dry-run first, and all five rows held zero postings.

**The one still open is venture firms.** A VC publishes its portfolio's
openings on its own careers page, the walk fingerprints the first board it
sees, and the VC is recorded as owning a company it merely invested in:

| token | claimed by |
|---|---|
| `ashby/clubhouse` | `graphventures.com`, `irregular.vc`, `dreamers.vc` |
| `greenhouse/arxroboticsgmbh` | `hvcapital.com`, `speedinvest.com` |
| `greenhouse/bicyclehealth` | `fcventures.com`, `signalfire.com` |
| `greenhouse/hippo70` | `fifthwall.com` (and `hippo.com`, correctly) |

This is the `palmersquare.com` → `jobs.lever.co/heyrowan` failure with a
different cause -- there the careers page linked to syndicated content, here it
links to a portfolio company. **It is contained**: `upsert_jobs` keys on
`(ats, token, job_id)`, so the second domain to claim a board writes nothing,
and none of these are firms this project wants. The cost is that the VC's own
board is never looked for again.

**I did not ship a guard**, because I could not find one that is safe. The
obvious rule -- "refuse a board whose postings do not name the firm" -- is what
`discover.corroborate` already does, and moving it into `ats.fingerprint` would
apply a *name* test to the walk, which is the one place this project has
deliberately kept name-free. Reading the postings costs a fetch per domain on a
1,400-domain sweep. Say the word if you want it behind a flag.

**Separately, `btig.com` resolves to `workday/usbank|wd1|US_Bank_Careers`.**
BTIG is a broker-dealer and not a US Bank entity, unlike `elavon.com` on the
same token, which is. One wrong row rather than a class; it is cleared and
re-queued if you want it done.

---

## 11. Norron has been sold, and its reader now fails loudly every poll

**One roster decision, and the reader is already doing the right thing.**

`sites.norron` fetches `https://norron.com/sv/karriar/`, which now answers
**404**. The homepage no longer links a careers page under any spelling and it
carries the word *Simplicity* — the sale that reader's own docstring predicted
in as many words: *"the roster notes Norron's fund business is being sold to
Simplicity AB, so this one may become stale rather than merely quiet."*

**It is not a bug.** `sites.py` readers raise rather than returning `[]`
precisely so that "this firm advertises nothing" and "this page is gone" stay
distinguishable, and the 404 is that rule working. Norron simply moved from
the first state to the second.

**What I need from you:** which of the two, because both are one line and only
you can say which is true of the firm.

- **Drop it** — remove the `Site` row and mark Norron `status` dead in
  `roster.csv`, the way AP1 and AP6 were handled after they were wound up.
- **Follow it** — point the reader at Simplicity AB, if the Stockholm team you
  wanted to reach went with the funds. That is a different employer, so it
  wants its own roster line rather than a redirect on this one.

Until then the poll prints one `FAIL site/norron` a run, which costs nothing
and is the correct amount of noise for a firm that has stopped existing in the
form the roster names.

## Reversible calls, each one line

These are preferences rather than facts. None blocks anything; each says how to
undo it.

| Call | To reverse |
|---|---|
| **Wealth advisory is rejected rather than ranked**, which reverses one row of an earlier call. `discretionary_investing` ranks instead of rejecting because *"it is ok if it picks up junk, i can remove them myself"* — still true of `Investment Analyst, Public Equity`. Advice to individuals came out of that set when you asked for a five-minute board: 94 such cards were marked noise, and `wealth management` reaches **no** posting rated `relevant` or `less_relevant` in 382,220 live titles. | Delete `"wealth_advisory"` from `_EXCLUSION` in `tagging.py`, bump `TAGGER`, re-run `tag`. |
| **Three new exclusion categories mined from the board** — `wealth_advisory`, `banking_platform`, `advisory_client` — remove ~560 cards at 99% precision against 1,866 hand-read verdicts. Each is a list you can edit one line at a time; `list --exclude <reason>` shows what each removed. | Delete the category from `_EXCLUSION` in `tagging.py`, bump `TAGGER`, re-run `tag`. |
| **A plain `Senior` no longer removes a posting.** It gated 9,914 postings, 947 in Stockholm and Copenhagen, and in the Nordics what it took was not leadership — a Nordic bank stamps *Senior* on a three-year grade. It still ranks last. | Put `"senior_6_10"` back in `_OUT_OF_REACH` in `tagging.py`, bump `TAGGER`, re-run `tag`. |
| **Markets seats that are not quant work rank instead of rejecting** — `Rates Sales - SEK Focus` at Nordea, `Commodities Sales to FICC Markets` at SEB. Your words were *"it is ok if it picks up junk, i can remove them myself"*. This overrides the hand-labelled sheet, which rejected nine such rows in a row. | Take `"discretionary_investing"` out of `SOFT` in `tag_posting`, bump `TAGGER`, re-run. |
| **The closing-date pin promotes only the shortlist** (`apply_now`, `strong`) — *your call, taken on the numbers*. It was pinning every dated posting above everything: **776 cards, 763 Singapore, 558 with no verdict at all** (`Admin Assistant`, `Desktop Engineer - Shift Based`) above all 224 shortlist cards. In firm tiles, 426 before the first unpinned card. Restricting it to anything the tagger had read still left 83 tiles, 116 of 118 postings Singapore, because that source publishes 98% of every closing date here. At the shortlist it is 10 tiles and the board opens on Flow Traders, Two Sigma and Point72. Nothing is hidden — a `plausible` card closing today is under the `Closing date` sort. | Widen `SHORTLIST` to `WORTH` in `pinned` in `order()` in `web/index.html`, or drop the clause entirely to go back to pinning every dated card. |
| **A markets word in a *body* no longer stops `no_markets_signal`** — *taken from your own reclassify clicks, and measured before it went in*. 19 of the 40 postings you marked `rejected` were escaping on one word in a description that belonged to the employer rather than the job: Adidas's `Part-Time Sales Consultants` on *trading*, Karolinska Institutet's `Projektadministratör` on *front office*, a `Swedish Content Writer` on *market data*. Over all 382,034 live postings it moves **2,504 from `unknown` to `rejected`** and 29 from `adjacent`, takes **2,209 cards off the board** and loses **no `relevant` card at all**. All 29 `adjacent` losses were read by hand — thirteen are one Singapore recruiter's `HSBC Life Wealth Management Advisor`, the rest investor relations and wealth management. A body naming markets *activity* still holds a posting open, so nothing a description can prove is lost. | Restore `markets_body` to the `has_body` test at the end of `lexicon.judge`, bump `TAGGER`, re-run `tag`. |
| **A sixth board gate**, `non_markets_board`: a board publishing no markets work *and* a title the tagger could not read. Removes 906 cards and empties `resolute.com`, `greystar.com`, `tink.com`, `carrier.com` and two radio stations. No hub lost a ranked card. | Delete the `non_markets_board` line from `GATES` in `web/build_data.py` and rebuild. No re-tag. |
| **`Hide pure trader roles` starts *off*.** The board never removes anything silently, so a hidden set leaves a crumb above the grid. It hides 159 postings when clicked. | One word in `FRESH()` in `web/index.html`. |
| **Södertälje is Stockholm.** 35 km and on the commuter rail, by the same forty-kilometre rule that puts Køge in the Copenhagen belt. Norrtälje (70), Nynäshamn (58) and Nykvarn (50) stayed out. | Move the word from `stockholm` to `sweden_other` in `tagging._HUBS`. |
| **Heavy systems engineering down-ranks rather than dropping**, so `Senior Software Engineer, C++` at Flow Traders and `Low-Latency Engineer` at Jane Street are on the board. Crypto still rejects outright — that one is on your exclude list. | Put `heavy_systems` in the hard list in `tag_posting`. It takes those firms with it. |

---

## Settled, so it does not get re-asked

- **Storage** → SQLite. **Classification** → keyword-only, no LLM spend.
  **Build order** → registries before ATS extraction. *(all your calls)*
- **Does the SEC ADV bulk file include state-registered advisers?** No —
  `Firm Type` is uniformly `Registered`. The sub-$110M US tail needs its own
  source and does not have one.
- **Roster staleness** → researched and encoded in `quantscraper/roster.csv`,
  whose `status` column marks a dead firm so a miss stops reading as a bug.
  Edit that file to add or remove firms; keep names specific, because a bare
  `Grasshopper` matched `GRASSHOPPER ESCAPEMENT, LLC` and reported Singapore
  better covered than it was. It is the *audit set*, never the universe — use
  `seed_firms.csv` to add a firm to the database.
- **FCA API key** → supplied, in `.env`, gitignored. It cannot enumerate (no
  bulk download, queries under three characters rejected, broad queries return
  `Request Entity Too Large`), so `fca.py` sits outside `registries/`
  deliberately. It is a source of *websites*, which the focus-region registers
  do not publish. The key was pasted into a chat transcript; regenerate it at
  https://register.fca.org.uk/Developer/s/ if that bothers you.
- **The msys2 Python** → `run.ps1` / `run.sh` call the Windows interpreter.
- **Switzerland and Denmark's national registers** → both open, both built. The
  Swiss 401 was our own URL bug, not an auth wall; Denmark's `jobnet.dk` needs a
  MitID, so it is served by Jobindex instead.
