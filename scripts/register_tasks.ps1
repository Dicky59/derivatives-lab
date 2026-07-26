<#
    register_tasks.ps1
    Registers (or cleanly re-registers) the Windows Task Scheduler entry that drives
    the M0 snapshot collector twice daily. Idempotent: safe to re-run any time the
    schedule needs to change.

    Runs as the CURRENT USER with LogonType Interactive - no admin rights required,
    no password stored. Caveat: Interactive logon means the task only fires while
    this user is logged on. Running it while logged out (or before any interactive
    logon) needs LogonType Password (or an S4U/service-account principal) plus a
    stored password, which requires elevated rights to register - out of scope here.

    DST caveat: the two trigger times below (16:45 / 22:45) are fixed LOCAL (Helsinki)
    clock times. US and EU clocks do not shift for daylight saving on the same
    calendar dates each spring/autumn, so for roughly 1-3 weeks around each transition
    these times will drift up to ~1 hour relative to the actual US market open/close.
    Not auto-corrected in M0 - nudge the times manually during those windows if it
    matters.
#>

$TaskName = "derivatives-lab snapshot"
$RepoRoot = "C:\Users\dicky\projects\derivatives-lab"
$BatPath  = Join-Path $RepoRoot "run_snapshot.bat"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Existing task '$TaskName' found - unregistering before re-creating."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# [datetime]::Today.AddHours(..).AddMinutes(..) avoids culture-dependent string
# parsing that a bare "-At '16:45'" would be subject to on non-US locales.
$Trigger1 = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(16).AddMinutes(45))
$Trigger2 = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(22).AddMinutes(45))

$Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $RepoRoot

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# LogonType Interactive + no -Password: runs only while this user is logged on.
# RunLevel intentionally left at its default (Limited) — setting RunLevel Highest
# is what forces UAC elevation / admin rights, which this task must not require.
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger @($Trigger1, $Trigger2) `
    -Settings $Settings `
    -Principal $Principal | Out-Null

Write-Host ""
Write-Host "Registered scheduled task:"
Write-Host "  Name    : $TaskName"
Write-Host "  Triggers: 16:45 and 22:45 (local time, daily)"
Write-Host "  Action  : $BatPath"
