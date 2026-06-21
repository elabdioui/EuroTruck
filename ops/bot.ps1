#Requires -Version 5.1
<#
.SYNOPSIS
    Single entry-point for the eurotruck-bot lifecycle.
.USAGE
    .\ops\bot.ps1 <command> [options]
    Commands: status | start | stop | restart [-All] | update [-All] | logs [backend|stats] | disconnect
#>

param(
    [Parameter(Position=0)] [string]$Command = "status",
    [Parameter(Position=1)] [string]$SubCommand = "",
    [switch]$All,
    [switch]$Wait
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configurable names (change here only) ────────────────────────────────────
$BackendService = "eurotruck-backend"
$DetectorTask   = "eurotruck-detector"

# ── Paths derived from script location — never hardcoded ─────────────────────
$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir     = Join-Path $RepoRoot "logs"
$DetectorLog = Join-Path $LogDir "detector-wrapper.log"
$BackendLog  = Join-Path $LogDir "backend.log"
$DetectorBat = Join-Path $RepoRoot "start_detector.bat"

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-OK   { param([string]$msg) Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-SKIP { param([string]$msg) Write-Host "  [SKIP] $msg" -ForegroundColor Cyan }
function Write-FAIL { param([string]$msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-INFO { param([string]$msg) Write-Host "         $msg" }

function Get-DetectorPid {
    # Match only processes whose command line contains "detector"
    # Example match: python.exe C:\...\detector\main.py
    $proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'detector' }
    return $proc
}

function Get-DetectorAlive {
    if (-not (Test-Path $DetectorLog)) { return $false }
    $last = Get-Item $DetectorLog
    $ageMinutes = (New-TimeSpan -Start $last.LastWriteTime -End (Get-Date)).TotalMinutes
    return ($ageMinutes -lt 15)
}

function Get-ActiveSessionId {
    $raw = & query session 2>$null | Select-String "Active"
    if ($raw -match '\s+(\d+)\s+Active') { return $Matches[1] }
    # Fallback: current session
    return $env:SESSIONNAME
}

# ── COMMANDS ──────────────────────────────────────────────────────────────────

function Invoke-Status {
    Write-Host ""
    Write-Host "=== eurotruck-bot status ===" -ForegroundColor Yellow

    # Backend service
    $svc = Get-Service -Name $BackendService -ErrorAction SilentlyContinue
    $backendOk = $false
    if ($svc -and $svc.Status -eq "Running") {
        Write-OK "Backend service '$BackendService': Running"
        $backendOk = $true
    } elseif ($svc) {
        Write-FAIL "Backend service '$BackendService': $($svc.Status)"
    } else {
        Write-FAIL "Backend service '$BackendService': NOT FOUND"
    }

    # Detector liveness
    $detectorOk = Get-DetectorAlive
    if (Test-Path $DetectorLog) {
        $lastLine = (Get-Content $DetectorLog -Tail 1)
        $age = [math]::Round((New-TimeSpan -Start (Get-Item $DetectorLog).LastWriteTime -End (Get-Date)).TotalMinutes, 1)
        $label = if ($detectorOk) { "ALIVE" } else { "DEAD (log > 15 min old)" }
        if ($detectorOk) {
            Write-OK "Detector log: $label  (${age} min ago)"
        } else {
            Write-FAIL "Detector log: $label  (${age} min ago)"
        }
        Write-INFO "Last line: $lastLine"
    } else {
        Write-FAIL "Detector log not found: $DetectorLog"
    }

    # Git commit
    Push-Location $RepoRoot
    $commit = & git log --oneline -1 2>$null
    Pop-Location
    Write-INFO "Git HEAD: $commit"

    # MT5 process
    $mt5 = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
    if ($mt5) {
        Write-OK "MT5 process: present (PID $($mt5.Id))"
    } else {
        Write-FAIL "MT5 process: NOT running"
    }

    # Active session
    $sessionId = Get-ActiveSessionId
    Write-INFO "Active session ID: $sessionId"

    Write-Host ""
    if ($backendOk -and $detectorOk) {
        Write-Host "FINAL: OK — backend running, detector alive" -ForegroundColor Green
        return 0
    } else {
        Write-Host "FINAL: FAIL — see above" -ForegroundColor Red
        return 1
    }
}

function Invoke-Start {
    Write-Host ""
    Write-Host "=== Starting eurotruck-bot ===" -ForegroundColor Yellow

    # Backend
    $svc = Get-Service -Name $BackendService -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne "Running") {
        Start-Service -Name $BackendService
        Write-OK "Backend service started"
    } elseif ($svc -and $svc.Status -eq "Running") {
        Write-SKIP "Backend service already running"
    } else {
        Write-FAIL "Backend service '$BackendService' not found — skipping"
    }

    # Detector via Task Scheduler (preferred) or bat fallback
    $task = Get-ScheduledTask -TaskName $DetectorTask -ErrorAction SilentlyContinue
    if ($task) {
        Start-ScheduledTask -TaskName $DetectorTask
        Write-OK "Detector task '$DetectorTask' started via Task Scheduler"
    } elseif (Test-Path $DetectorBat) {
        Start-Process cmd -ArgumentList "/c `"$DetectorBat`"" -WindowStyle Normal
        Write-OK "Detector started via $DetectorBat (Task Scheduler task not found)"
    } else {
        Write-FAIL "Cannot start detector: task '$DetectorTask' not registered and $DetectorBat not found"
    }

    Write-INFO "Waiting 15 s for processes to settle..."
    Start-Sleep -Seconds 15

    $exit = Invoke-Status
    return $exit
}

function Invoke-Stop {
    Write-Host ""
    Write-Host "=== Stopping eurotruck-bot ===" -ForegroundColor Yellow

    # Find detector python — match on 'detector' in command line only
    # Example: python.exe "C:\...\detector\main.py" — never matches a generic python.exe
    $procs = Get-DetectorPid
    if ($procs) {
        foreach ($p in $procs) {
            Stop-Process -Id $p.ProcessId -Force
            Write-OK "Killed detector python PID $($p.ProcessId) (cmd: $($p.CommandLine))"
        }
    } else {
        Write-SKIP "No detector python process found"
    }

    # Backend service
    $svc = Get-Service -Name $BackendService -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        Stop-Service -Name $BackendService -Force
        Write-OK "Backend service '$BackendService' stopped"
    } elseif ($svc) {
        Write-SKIP "Backend service already stopped ($($svc.Status))"
    } else {
        Write-SKIP "Backend service '$BackendService' not found"
    }

    Write-Host ""
    Write-Host "FINAL: OK — stop complete" -ForegroundColor Green
    return 0
}

function Invoke-Restart {
    Write-Host ""
    Write-Host "=== Restarting eurotruck-bot ===" -ForegroundColor Yellow

    # Stop detector always; stop backend only with -All
    $procs = Get-DetectorPid
    if ($procs) {
        foreach ($p in $procs) {
            Stop-Process -Id $p.ProcessId -Force
            Write-OK "Killed detector PID $($p.ProcessId)"
        }
    } else {
        Write-SKIP "No detector process found"
    }

    if ($All) {
        $svc = Get-Service -Name $BackendService -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq "Running") {
            Stop-Service -Name $BackendService -Force
            Write-OK "Backend service stopped"
        }
    } else {
        Write-INFO "Backend not restarted (use -All to include it)"
    }

    return (Invoke-Start)
}

function Invoke-Update {
    Write-Host ""
    Write-Host "=== Updating eurotruck-bot ===" -ForegroundColor Yellow

    Push-Location $RepoRoot

    # 1. git pull
    $pullOut = & git pull 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-FAIL "git pull failed (possible merge conflict). Output:"
        $pullOut | Write-Host
        Pop-Location
        return 1
    }
    Write-OK "git pull succeeded"
    Write-INFO ($pullOut | Select-Object -Last 1)

    # 2. Did backend/ change?
    $changedFiles = & git diff --name-only HEAD@{1} HEAD 2>$null
    $backendChanged = ($changedFiles | Where-Object { $_ -match '^backend/' }).Count -gt 0

    Pop-Location

    # 3. Always restart detector
    $procs = Get-DetectorPid
    if ($procs) {
        foreach ($p in $procs) {
            Stop-Process -Id $p.ProcessId -Force
            Write-OK "Killed detector PID $($p.ProcessId)"
        }
    }

    # 4. Restart backend only if backend/ changed or -All
    if ($backendChanged -or $All) {
        $svc = Get-Service -Name $BackendService -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq "Running") {
            Stop-Service -Name $BackendService -Force
            Write-OK "Backend service stopped (backend/ changed: $backendChanged)"
        }
        Start-Service -Name $BackendService -ErrorAction SilentlyContinue
        Write-OK "Backend service started"
    } else {
        Write-SKIP "Backend not restarted (no changes in backend/)"
    }

    # Restart detector
    $task = Get-ScheduledTask -TaskName $DetectorTask -ErrorAction SilentlyContinue
    if ($task) {
        Start-ScheduledTask -TaskName $DetectorTask
        Write-OK "Detector task started"
    } elseif (Test-Path $DetectorBat) {
        Start-Process cmd -ArgumentList "/c `"$DetectorBat`"" -WindowStyle Normal
        Write-OK "Detector started via bat"
    }

    Write-INFO "Waiting 15 s..."
    Start-Sleep -Seconds 15

    if (Test-Path $DetectorLog) {
        Write-INFO "--- Last 5 lines of detector-wrapper.log ---"
        Get-Content $DetectorLog -Tail 5 | ForEach-Object { Write-INFO $_ }
    }

    return (Invoke-Status)
}

function Invoke-Logs {
    param([string]$Target = "detector")

    switch ($Target.ToLower()) {
        "backend" {
            $logFile = $BackendLog
        }
        "stats" {
            if (Test-Path $DetectorLog) {
                Get-Content $DetectorLog | Where-Object { $_ -match 'SCAN_STATS' }
            } else {
                Write-FAIL "Detector log not found"
            }
            return 0
        }
        default {
            $logFile = $DetectorLog
        }
    }

    if (-not (Test-Path $logFile)) {
        Write-FAIL "Log file not found: $logFile"
        return 1
    }

    Get-Content $logFile -Tail 30 -Wait:$Wait
    return 0
}

function Invoke-Disconnect {
    Write-Host ""
    Write-Host "=== Safe RDP disconnect ===" -ForegroundColor Yellow

    # Parse current active session id from 'query session'
    $raw = & query session 2>$null
    $activeLine = $raw | Where-Object { $_ -match 'Active' } | Select-Object -First 1
    if ($activeLine -match '\s+(\d+)\s+Active') {
        $sessionId = $Matches[1]
    } else {
        # Fallback: extract from USERNAME line
        $activeLine = $raw | Where-Object { $_ -match $env:USERNAME } | Select-Object -First 1
        if ($activeLine -match '\s+(\d+)\s+') {
            $sessionId = $Matches[1]
        } else {
            Write-FAIL "Could not determine active session ID. Run 'query session' manually."
            return 1
        }
    }

    Write-INFO "Disconnecting session $sessionId via tscon (keeps session Active for MT5 IPC)"
    & tscon $sessionId /dest:console
    # If we reach this line the tscon succeeded (or we're already on console)
    Write-OK "Disconnect issued for session $sessionId"
    return 0
}

# ── DISPATCH ──────────────────────────────────────────────────────────────────
$exitCode = 0
switch ($Command.ToLower()) {
    "status"     { $exitCode = Invoke-Status }
    "start"      { $exitCode = Invoke-Start }
    "stop"       { $exitCode = Invoke-Stop }
    "restart"    { $exitCode = Invoke-Restart }
    "update"     { $exitCode = Invoke-Update }
    "logs"       { $exitCode = Invoke-Logs -Target $SubCommand }
    "disconnect" { $exitCode = Invoke-Disconnect }
    default {
        Write-Host "Unknown command: $Command"
        Write-Host "Usage: .\ops\bot.ps1 <status|start|stop|restart [-All]|update [-All]|logs [backend|stats]|disconnect>"
        $exitCode = 2
    }
}

exit $exitCode
