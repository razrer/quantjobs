# quant-scraper

Personal quant-job search, built employer-first: enumerate employers, resolve
careers feeds, collect postings, then classify and display them. Exhaustiveness
is the objective; public registries and job boards do not prove total coverage.

Live board: [quantjobs.spawned.app](https://quantjobs.spawned.app).

## Setup

Use Windows Python 3.13. The wrappers select it; bare
`python` may resolve to the msys2 installation with different dependencies.
Set `$env:PYTHONIOENCODING='utf-8'` before commands that print non-ASCII names.

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pip install -r requirements.txt
./run.ps1 --help
```

The SQLite database is local and gitignored. FCA enrichment alone needs
`FCA_EMAIL` and `FCA_KEY` in `.env`; never commit credentials. No new accounts or
paid services are required for this refactor.

## Routine use

```powershell
./run.ps1 daily --full --publish  # complete weekly sweep and publication
./run.ps1 jobs --limit 100       # poll a limited queue of employer boards
./run.ps1 tag                    # classify new or invalidated postings
./run.ps1 list --fit apply_now --hub amsterdam
./run.ps1 alerts
./run.ps1 audit --pipeline
./run.ps1 coverage
```

Wednesdays at 03:00, Windows Task Scheduler runs `weekly.ps1`. It uses the user's
logged-in profile and catches up when available. `install-weekly.ps1` manages
registration; logs are in `logs/`, with the last twelve weekly transcripts kept.
The full sweep includes Singapore and Hong Kong. Never move the build into CI:
only this machine has the database.

For a local board, run `web/build_data.py`, then `web/serve.py` with Windows
Python. The server defaults to port 8731 and saves reclassification clicks to
`quantscraper/labels.csv`. Opening `web/index.html` directly supports reading;
corrections in that mode need manual export.

## Commands by layer

| Layer | Commands |
|---|---|
| Employer universe | `fetch`, `resolve`, `stats`, `audit` |
| Careers resolution | `domains`, `fca`, `ats`, `discover` |
| Collection | `jobs`, `pages`, `bodies` |
| National boards | `jobstream`, `switzerland`, `sweden`, `denmark`, `singapore`, `hongkong` |
| Classification | `tag`, `list`, `sample`, `labels`, `corrections` |
| Operations | `coverage`, `alerts`, `daily` |

Use `./run.ps1 <command> --help` for options. Labelling instructions and audit
sampling are in [TAGGING.md](TAGGING.md).

## Verify and publish

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m unittest discover -s tests
```

Compare the shortlist and card identities after changes. A classifier change
requires a `TAGGER` bump and re-tagging before building.

Code goes to `quantjobs` / `master`; a push deploys `index.html` and `robots.txt`
through GitHub Actions. Data is separate: `web/publish.py` builds and uploads
`data.js` from this machine. `--no-build` uploads an already verified build.
For this refactor, commit verified units and push/publish once at the end.

## Reference

- [Methodology](METHODOLOGY.md) and [independent proposal/comparison](REFACTOR-METHODOLOGY.md)
- [Current work and verification](PLAN.md)
- [Refactor results and measurements](docs/REFACTOR-RESULTS.md)
- [Agent rules](AGENTS.md)
- [Human input still needed](ACTION-REQUIRED.md)
- [Historical incidents and measurements](docs/history/README.md)

Known structural gaps include sponsored-access firms absent from public lists,
the US state-registered adviser tail, inaccessible careers channels, and roles
never advertised. National boards supplement employer feeds; none is a census
of quant hiring.
