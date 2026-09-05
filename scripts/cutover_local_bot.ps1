param(
    [ValidateSet("Status", "Stop", "Start")]
    [string]$Action = "Status"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run_bot_forever.ps1"
$stateDirectory = Join-Path $projectRoot "backups"
$statePath = Join-Path $stateDirectory "local-bot-cutover-state.json"
$taskName = "StudentAIBot"
$lockPort = 38473

function Get-Supervisors {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^powershell(\.exe)?$' -and
        $_.CommandLine -match 'run_bot_forever\.ps1'
    })
}

function Get-BotProcesses {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -match '(^|\s)-m\s+app\.bot(\s|$)'
    })
}

function Get-LockListeners {
    @(Get-NetTCPConnection -State Listen -LocalPort $lockPort -ErrorAction SilentlyContinue)
}

function Get-Status {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    [pscustomobject]@{
        Supervisors = @(Get-Supervisors).Count
        BotProcesses = @(Get-BotProcesses).Count
        LockListeners = @(Get-LockListeners).Count
        ScheduledTask = if ($task) { [string]$task.State } else { "Missing" }
    }
}

if ($Action -eq "Status") {
    Get-Status
    exit 0
}

if ($Action -eq "Stop") {
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    @{ TaskExisted = [bool]$task; TaskWasEnabled = [bool]($task -and $task.State -ne "Disabled") } |
        ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    if ($task) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $taskName | Out-Null
    }
    Get-Supervisors | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Get-BotProcesses | Sort-Object ProcessId -Descending | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 12
    $status = Get-Status
    if ($status.Supervisors -ne 0 -or $status.BotProcesses -ne 0 -or
            $status.LockListeners -ne 0) {
        throw "Local polling did not stop cleanly"
    }
    Write-Output "LOCAL_POLLING_STOPPED_AUTORESTART_DISABLED"
    exit 0
}

$status = Get-Status
if ($status.Supervisors -ne 0 -or $status.BotProcesses -ne 0 -or
        $status.LockListeners -ne 0) {
    throw "Local bot is already running"
}
$saved = if (Test-Path -LiteralPath $statePath) {
    Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
} else { $null }
if ($saved -and $saved.TaskExisted -and $saved.TaskWasEnabled) {
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    Start-ScheduledTask -TaskName $taskName
} else {
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner
    ) -WorkingDirectory $projectRoot -WindowStyle Hidden
}
$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 1
    $listeners = Get-LockListeners
} until ($listeners.Count -eq 1 -or (Get-Date) -ge $deadline)
if ($listeners.Count -ne 1) {
    throw "Local bot did not acquire its single-instance lock"
}
Write-Output "LOCAL_POLLING_STARTED_SINGLE_LOCK"
