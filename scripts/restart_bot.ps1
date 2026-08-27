$ErrorActionPreference = "Stop"

$taskName = "StudentAIBot"
$lockPort = 38473

if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    throw "Scheduled task '$taskName' is not installed."
}

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -match '(^|\s)-m\s+app\.bot(\s|$)'
    } |
    Sort-Object ProcessId -Descending |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-ScheduledTask -TaskName $taskName

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Seconds 1
    $listener = Get-NetTCPConnection `
        -State Listen `
        -LocalPort $lockPort `
        -ErrorAction SilentlyContinue
} until ($listener -or (Get-Date) -ge $deadline)

if (-not $listener) {
    throw "Student AI Bot did not become ready within 30 seconds. Check logs\bot.log."
}

Write-Output "Student AI Bot restarted successfully (PID $($listener.OwningProcess))."
