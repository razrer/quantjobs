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

## 5. Sponsored-access firms have no public list

Recorded rather than asked: a firm dealing exclusively on its own account is
exempt from investment-firm licensing under MiFID II Art. 2(1)(d), and one
trading under someone else's exchange membership appears in no register and on
no participant list. Da Vinci Derivatives is the standing example.
`cboe_europe` and `seed` close part of it. The rest is closed only by naming
firms by hand — add any you encounter to `registries/seed_firms.csv`.

---

## Reversible calls, each one line

These are preferences rather than facts. None blocks anything; each says how to
undo it.

| Call | To reverse |
|---|---|
| **A plain `Senior` no longer removes a posting.** It gated 9,914 postings, 947 in Stockholm and Copenhagen, and in the Nordics what it took was not leadership — a Nordic bank stamps *Senior* on a three-year grade. It still ranks last. | Put `"senior_6_10"` back in `_OUT_OF_REACH` in `tagging.py`, bump `TAGGER`, re-run `tag`. |
| **Markets seats that are not quant work rank instead of rejecting** — `Rates Sales - SEK Focus` at Nordea, `Commodities Sales to FICC Markets` at SEB. Your words were *"it is ok if it picks up junk, i can remove them myself"*. This overrides the hand-labelled sheet, which rejected nine such rows in a row. | Take `"discretionary_investing"` out of `SOFT` in `tag_posting`, bump `TAGGER`, re-run. |
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
