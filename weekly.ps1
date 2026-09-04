# The Wednesday sweep: `daily --full --publish`, run unattended by Windows
# Task Scheduler. Register it with `install-weekly.ps1`.
#
# **This reverses a decision `CLAUDE.md` had recorded, and it is worth saying
# out loud.** That file says the pipeline is "deliberately manual, because the
# search is the expensive half, free here and billable anywhere else, so
# nothing schedules it". The reasoning was about *where the cost lands*, and it
# still holds: this runs on this machine, at this machine's expense, once a
# week. What is deployed is still the output, not the scraper.
#
# A wrapper rather than a command line in the task, because four things have to
# be true and not one of them is by default:
#
#   * **The interpreter.** Bare `python` here is the msys2 build, which ships
#     no CA bundle, so every HTTPS request dies with
#     `CERTIFICATE_VERIFY_FAILED` -- and from a 3am task nobody would see the
#     traceback. `run.ps1` names the Windows interpreter and this uses the
#     same path, checked before anything starts.
#   * **The encoding.** `PYTHONIOENCODING=utf-8`, or the first non-ASCII firm
#     name raises `UnicodeEncodeError` and takes the run with it.
#   * **Both streams, unmangled.** `daily` writes its results to stdout and
#     every `FAIL` -- the lines that say which source went quiet -- to stderr.
#     Windows PowerShell 5.1 wraps a native command's redirected stderr in
#     `NativeCommandError` records, so `*>&1 | Out-File` would bury exactly
#     the lines worth reading. `Start-Process` with two redirect files keeps
#     both verbatim, and they are concatenated afterwards so there is one
#     transcript to open.
#   * **A log at all.** `daily` deliberately does not stop on a failed step: a
#     board redesigned underneath us should cost its own postings and not the
#     other eight sources'. So the interesting output is *which* step failed,
#     and unattended that exists nowhere but here.
#
# The exit code is passed through, so Task Scheduler's Last Run Result is the
# answer `daily` gave: 0 if every step succeeded, 1 if any did not.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'

$logs = Join-Path $root 'logs'
if (-not (Test-Path $logs)) { New-Item -ItemType Directory -Path $logs | Out-Null }
$stamp = Get-Date -Format 'yyyy-MM-dd'
$log = Join-Path $logs "weekly-$stamp.log"
$outFile = Join-Path $logs "weekly-$stamp.out.tmp"
$errFile = Join-Path $logs "weekly-$stamp.err.tmp"

function Write-Log([string]$line) {
    Add-Content -Path $log -Value $line -Encoding UTF8
}

# Keep the last twelve weeks. A run's transcript is a few hundred KB; twelve is
# enough to watch a source go quiet across a season and few enough that nobody
# has to think about it.
Get-ChildItem -Path $logs -Filter 'weekly-*.log' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 12 |
    Remove-Item -Force -ErrorAction SilentlyContinue

Set-Content -Path $log -Encoding UTF8 -Value (
    "=== quantscraper daily --full --publish : {0} ===" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

if (-not (Test-Path $python)) {
    # The one failure that must not be quiet: without this interpreter every
    # HTTPS request fails, which from outside looks like nine dead sources.
    Write-Log "FAIL the Windows interpreter is not at $python"
    exit 2
}

$env:PYTHONIOENCODING = 'utf-8'

try {
    $run = Start-Process -FilePath $python `
        -ArgumentList '-m', 'quantscraper', 'daily', '--full', '--publish' `
        -WorkingDirectory $root `
        -RedirectStandardOutput $outFile `
        -RedirectStandardError $errFile `
        -NoNewWindow -Wait -PassThru
    $code = $run.ExitCode
} catch {
    Write-Log "FAIL could not start the sweep: $_"
    exit 2
}

foreach ($part in @(@('stdout', $outFile), @('stderr', $errFile))) {
    if (Test-Path $part[1]) {
        # **`-Encoding UTF8` is load-bearing.** The child writes UTF-8 because
        # `PYTHONIOENCODING` says so, and `Start-Process` puts those bytes in
        # the file untouched -- but Windows PowerShell 5.1's `Get-Content`
        # defaults to the ANSI codepage, so reading them back without this
        # turns `Öhman` into `Ã–hman` and every Hong Kong title into noise.
        # Measured on a probe run before it could reach a real transcript.
        $body = Get-Content -Path $part[1] -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($body) {
            Write-Log ""
            Write-Log ("--- {0} ---" -f $part[0])
            Write-Log $body.TrimEnd()
        }
        Remove-Item -Path $part[1] -Force -ErrorAction SilentlyContinue
    }
}

Write-Log ""
Write-Log ("=== finished {0}, exit {1} ===" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $code)
exit $code
