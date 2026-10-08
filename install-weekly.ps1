# Registers the Wednesday 03:00 sweep in Windows Task Scheduler, and is
# idempotent -- re-running it replaces the task rather than adding a second.
#
# **It has to be a local timer, and that is not a preference.** `CLAUDE.md`
# records why: `data.js` is built from the SQLite database, which exists only
# on this machine, so the build cannot run in CI. The existing GitHub workflow
# re-uploads `index.html` and `robots.txt` on push and deliberately nothing
# else, for the same reason.
#
#   powershell -ExecutionPolicy Bypass -File install-weekly.ps1
#   powershell -ExecutionPolicy Bypass -File install-weekly.ps1 -Remove
#
# **`LogonType Interactive` is the deliberate choice.** The alternative, `S4U`,
# runs whether or not anyone is logged on -- and this run needs the user's own
# profile: the interpreter under `%LOCALAPPDATA%`, the `.env` holding the FCA
# key, and the Spawned CLI's stored login that `publish.py` uses. Interactive
# keeps all three and stores no password anywhere. The cost is that a fully
# logged-out machine skips the week; `StartWhenAvailable` then runs it at the
# next opportunity rather than waiting seven days.

param([switch]$Remove)

$name = 'QuantScraper weekly sweep'
$root = $PSScriptRoot

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    "removed '$name'"
    return
}

$script = Join-Path $root 'weekly.ps1'
if (-not (Test-Path $script)) { throw "weekly.ps1 is not beside this script" }

# WakeToRun cannot wake this laptop on battery while the active power plan
# disables wake timers. Keep both AC and battery wake timers enabled so the
# Wednesday task can wake the machine when the active power plan allows it.
foreach ($supply in @('ac', 'dc')) {
    & powercfg "/set${supply}valueindex" SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
    if ($LASTEXITCODE -ne 0) { throw "Could not enable $supply wake timers" }
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -IfNeeded" `
    -WorkingDirectory $root

$trigger = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At 3am
    # A wake-time catch-up has twice died before writing its first log line.
    # Try at noon each day until this week's build succeeds. The launcher
    # skips a completed or still-running sweep, so this does not add reads.
    New-ScheduledTaskTrigger -Daily -At 12pm
)

# A lid-close can suspend a sweep for hours. The time limit counts elapsed wall
# time, so leave room for the machine to wake and finish the same run.
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -DontStopOnIdleEnd `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 24) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description ('Runs quantscraper daily --full --publish: both national portals, ' +
                  'every Jobindex category, the ATS boards, tag, bodies, re-tag, ' +
                  'rebuild, then upload to https://quantjobs.spawned.app. ' +
                  'Transcript in logs\weekly-<timestamp>.log.') | Out-Null

Get-ScheduledTaskInfo -TaskName $name | Select-Object NextRunTime, LastTaskResult
