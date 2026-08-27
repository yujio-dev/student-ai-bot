$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "logs"
$logPath = Join-Path $logDirectory "bot.log"
$stdoutLogPath = Join-Path $logDirectory "bot.stdout.log"
$previousLogPath = Join-Path $logDirectory "bot.previous.log"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found: $pythonPath"
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Set-Location -LiteralPath $projectRoot

while ($true) {
    if (Test-Path -LiteralPath $logPath) {
        if (Test-Path -LiteralPath $previousLogPath) {
            Remove-Item -LiteralPath $previousLogPath -Force
        }
        Move-Item -LiteralPath $logPath -Destination $previousLogPath
    }
    if (Test-Path -LiteralPath $stdoutLogPath) {
        Remove-Item -LiteralPath $stdoutLogPath -Force
    }

    try {
        $process = Start-Process `
            -FilePath $pythonPath `
            -ArgumentList @("-m", "app.bot") `
            -WorkingDirectory $projectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLogPath `
            -RedirectStandardError $logPath `
            -PassThru `
            -Wait
        $exitCode = $process.ExitCode
    }
    catch {
        $exitCode = 1
        Add-Content -LiteralPath $logPath -Value $_.Exception.ToString()
    }

    $stoppedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value (
        "[$stoppedAt] Bot stopped with exit code $exitCode; restarting in 10 seconds"
    )
    Start-Sleep -Seconds 10
}
