# Things only you can do

Work that is blocked on your input, in priority order. Each item says what to
do, where to put the result, and what I will build once it is there.

Nothing here is urgent — the project runs fine without any of it. These are the
places where I hit a wall that needed a human, not a decision I should make for
you.

---

## 1. FCA API key — unblocks the UK

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

**Why it is blocked:** it is your machine and your preference.

`python` on this box resolves to the msys2 build, which ships without a CA
bundle, so every HTTPS request dies with `CERTIFICATE_VERIFY_FAILED`. I have
been working around it by calling the Windows Python explicitly:

```bash
"$LOCALAPPDATA/Programs/Python/Python313/python" -m quantscraper fetch
```

**Pick one and tell me:**

- **(a)** Leave it — you will remember to use the full path. *(current state)*
- **(b)** I add a one-line `run.sh` / `run.ps1` wrapper that picks the right
  interpreter, so `./run.sh fetch` always works.
- **(c)** You set `SSL_CERT_FILE` permanently in your shell profile:

  ```bash
  export SSL_CERT_FILE=C:/msys64/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
  ```

My recommendation is **(b)** — it survives you forgetting, and costs nothing.

---

## 3. A decision I need from you: how hard to chase sponsored-access firms

**Why it is blocked:** this is a cost/benefit call about your job hunt, not a
technical question.

Da Vinci Derivatives is a real Amsterdam prop shop that is in **no** public list
I have found: not the AFM registers (it is licence-exempt under MiFID II Art.
2(1)(d)), not FIA EPTA, and not a direct member of Eurex or Euronext. It almost
certainly trades through sponsored access under another firm's membership, and
sponsored-access firms are invisible to every source in this design.

I don't know how many firms are in this category. It is probably small, but it
is exactly the "12-person prop shop" segment the plan argues is highest-value
for someone with under a year of experience.

**Options:**

- **(a)** Accept the gap. Move on to Layer 2. *(my recommendation for now)*
- **(b)** I add the Cboe Europe participant list — cheap, and the most likely
  remaining public source to catch some of them.
- **(c)** You hand-maintain a small seed file of firms you know about, and I
  wire it in as just another registry. Honest, unglamorous, and it works.

**(b) and (c) are not exclusive**, and (c) is probably worth doing eventually
regardless — you will run into names I never will.

---

## 4. Optional: tell me if any of the plan's named roster is stale

**Why it is blocked:** you know this market better than the plan document does.

Two roster entries were already wrong when I checked them:

- **IPM** — absent because the firm wound down. Correctly absent, not a bug.
- **AP1–AP4 and AP6** — absent because only AP7 is FI-supervised; the other
  buffer funds are governed by their own act and appear in no FI category. They
  are real Stockholm employers and need seeding separately.

If you spot other names in the plan's roster that no longer exist, have merged,
or have left a city, tell me and I will stop treating their absence as a
coverage bug worth chasing.

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
