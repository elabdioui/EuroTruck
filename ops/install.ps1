#Requires -Version 5.1
<#
.SYNOPSIS
    Idempotent bootstrap for a fresh Windows VM running eurotruck-bot.
.NOTES
    Run once as Administrator AFTER: repo cloned, MT5 installed and logged in, .env copied.
    Safe to re-run — every step checks before acting and prints [OK]/[SKIP]/[FAIL].
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Paths ─────────────────────────────────────────────────────────────────────
$RepoRoot        = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile         = Join-Path $RepoRoot ".env"
$RequirementsTxt = Join-Path $RepoRoot "requirements.txt"
$VenvDir         = Join-Path $RepoRoot ".venv"
$VenvPython      = Join-Path $VenvDir "Scripts\python.exe"
$DetectorBat     = Join-Path $RepoRoot "start_detector.bat"
$NssmSearch      = @(
    (Join-Path $PSScriptRoot "bin\nssm.exe"),
    "C:\nssm\nssm.exe",
    "C:\tools\nssm\nssm.exe"
)

$BackendService  = "eurotruck-backend"
$DetectorTask    = "eurotruck-detector"
$BackendDir      = Join-Path $RepoRoot "backend"
$BackendMain     = "main:app"
$LogDir          = Join-Path $RepoRoot "logs"
$BackendLog      = Join-Path $LogDir "backend.log"
$BackendErrLog   = Join-Path $LogDir "backend-error.log"

# ── Helpers ───────────────────────────────────────────────────────────────────
$step = 0
function Step-Header {
    param([string]$title)
    $script:step++
    Write-Host ""
    Write-Host "[$script:step] $title" -ForegroundColor Yellow
}
function Write-OK   { param([string]$msg) Write-Host "    [OK]   $msg" -ForegroundColor Green }
function Write-SKIP { param([string]$msg) Write-Host "    [SKIP] $msg" -ForegroundColor Cyan }
function Write-FAIL { param([string]$msg) Write-Host "    [FAIL] $msg" -ForegroundColor Red; throw "INSTALL FAILED: $msg" }
function Write-WARN { param([string]$msg) Write-Host "    [WARN] $msg" -ForegroundColor Magenta }
function Write-INFO { param([string]$msg) Write-Host "           $msg" }

function Set-EnvVar {
    param([string]$Key, [string]$Value)
    if (Test-Path $EnvFile) {
        $content = Get-Content $EnvFile -Raw
        if ($content -match "(?m)^$Key=") {
            $content = $content -replace "(?m)^$Key=.*", "$Key=$Value"
        } else {
            $content = $content.TrimEnd() + "`n$Key=$Value`n"
        }
        Set-Content $EnvFile $content -Encoding utf8 -NoNewline
    }
}

function New-Shortcut {
    param([string]$ShortcutPath, [string]$Target, [string]$Args, [string]$WorkDir)
    $shell = New-Object -ComObject WScript.Shell
    $lnk   = $shell.CreateShortcut($ShortcutPath)
    $lnk.TargetPath       = $Target
    $lnk.Arguments        = $Args
    $lnk.WorkingDirectory = $WorkDir
    $lnk.Save()
}

# ── STEP 1: Preflight ─────────────────────────────────────────────────────────
Step-Header "Preflight checks"

$missing = @()
$pyVer = & python --version 2>$null
if ($LASTEXITCODE -ne 0 -or -not ($pyVer -match '3\.(1[2-9]|[2-9]\d)')) {
    $missing += "Python >= 3.12 not found on PATH (found: $pyVer)"
}
$gitVer = & git --version 2>$null
if ($LASTEXITCODE -ne 0) { $missing += "git not found on PATH" }
if (-not (Test-Path $EnvFile)) { $missing += ".env not found at $EnvFile" }
if (-not (Test-Path $RepoRoot)) { $missing += "Repo root not detected: $RepoRoot" }

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "PREFLIGHT FAILED — fix the following before re-running:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

Write-OK "Python: $pyVer"
Write-OK "git: $gitVer"
Write-OK ".env present"
Write-OK "Repo root: $RepoRoot"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# ── STEP 2: Venv + deps ───────────────────────────────────────────────────────
Step-Header "Python venv + dependencies"

if (-not (Test-Path $VenvDir)) {
    & python -m venv $VenvDir
    Write-OK "Created venv at $VenvDir"
} else {
    Write-SKIP "Venv already exists"
}

Write-INFO "Running pip install -r requirements.txt ..."
& $VenvPython -m pip install --quiet -r $RequirementsTxt
Write-OK "Dependencies installed"

# ── STEP 3: MT5 path discovery ────────────────────────────────────────────────
Step-Header "MT5 terminal64.exe path"

$mt5StandardDirs = @(
    "C:\Program Files\MetaTrader 5",
    "C:\Program Files (x86)\MetaTrader 5",
    "$env:APPDATA\MetaQuotes\Terminal"
)

$foundMt5 = $null
foreach ($dir in $mt5StandardDirs) {
    $candidate = Get-ChildItem -Path $dir -Recurse -Filter "terminal64.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { $foundMt5 = $candidate.FullName; break }
}

if (-not $foundMt5) {
    Write-WARN "terminal64.exe not found in standard locations."
    $foundMt5 = Read-Host "    Enter full path to terminal64.exe (or press Enter to skip)"
}

if ($foundMt5 -and (Test-Path $foundMt5)) {
    Set-EnvVar "MT5_PATH" $foundMt5
    Write-OK "MT5_PATH=$foundMt5 written to .env"

    # Warn if mt5_client.py still calls initialize() without path=
    $mt5Client = Join-Path $RepoRoot "detector\mt5_client.py"
    if (Test-Path $mt5Client) {
        $content = Get-Content $mt5Client -Raw
        if ($content -match 'mt5\.initialize\(\s*\)') {
            Write-WARN "detector\mt5_client.py calls mt5.initialize() without path= argument."
            Write-WARN "See docs\SPEC_mt5_connect_fix.md to apply the MT5_PATH fix."
        }
    }
} else {
    Write-SKIP "MT5_PATH not configured — set it manually in .env"
}

# ── STEP 4: NSSM / backend service ───────────────────────────────────────────
Step-Header "NSSM backend service: $BackendService"

$nssm = $null
foreach ($p in $NssmSearch) { if (Test-Path $p) { $nssm = $p; break } }
if (-not $nssm) {
    $nssmCmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($nssmCmd) { $nssm = $nssmCmd.Source }
}

if (-not $nssm) {
    Write-WARN "nssm.exe not found in ops\bin\ or system PATH."
    Write-WARN "Place nssm.exe in ops\bin\nssm.exe and re-run to register the backend service."
    Write-SKIP "Backend service registration skipped"
} else {
    $uvicorn = Join-Path $VenvDir "Scripts\uvicorn.exe"
    if (-not (Test-Path $uvicorn)) { $uvicorn = Join-Path $VenvDir "Scripts\uvicorn" }

    $existing = Get-Service -Name $BackendService -ErrorAction SilentlyContinue
    if (-not $existing) {
        & $nssm install $BackendService $uvicorn "$BackendMain --host 0.0.0.0 --port 8000" 2>$null
        Write-OK "Service '$BackendService' registered"
    } else {
        Write-SKIP "Service '$BackendService' already registered — updating paths"
        & $nssm set $BackendService Application $uvicorn 2>$null
        & $nssm set $BackendService AppParameters "$BackendMain --host 0.0.0.0 --port 8000" 2>$null
    }

    & $nssm set $BackendService AppDirectory $BackendDir 2>$null
    & $nssm set $BackendService AppStdout $BackendLog 2>$null
    & $nssm set $BackendService AppStderr $BackendErrLog 2>$null
    & $nssm set $BackendService Start SERVICE_AUTO_START 2>$null
    Write-OK "NSSM service configured (stdout→backend.log, stderr→backend-error.log)"
}

# ── STEP 5: Task Scheduler — detector ────────────────────────────────────────
Step-Header "Task Scheduler: $DetectorTask"

if (-not (Test-Path $DetectorBat)) {
    Write-WARN "start_detector.bat not found at $DetectorBat — creating minimal shim"
    # Shim: one-liner calling bot.ps1 disconnect (kept for desktop habit + start)
    $shim = "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\bot.ps1`" start 2>&1"
    # Actually the bat should launch detector, not bot.ps1 — write a real shim
    $detectorDir = Join-Path $RepoRoot "detector"
    $shim = "@echo off`r`ncd /d `"$detectorDir`"`r`n`"$VenvPython`" main.py`r`n"
    Set-Content $DetectorBat $shim -Encoding ascii
    Write-OK "Created start_detector.bat shim at $DetectorBat"
}

$existing = Get-ScheduledTask -TaskName $DetectorTask -ErrorAction SilentlyContinue
if ($existing) {
    Write-SKIP "Task '$DetectorTask' already registered — updating action"
    Unregister-ScheduledTask -TaskName $DetectorTask -Confirm:$false
}

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$DetectorBat`"" -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -DisallowStartOnRemoteAppSession $false

# RunOnlyIfLoggedOn = interactive session requirement for MT5 IPC
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $DetectorTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "eurotruck detector — must run in interactive session for MT5 IPC" | Out-Null

Write-OK "Task '$DetectorTask' registered (AtLogOn, interactive, user=$env:USERNAME)"

# ── STEP 6: Desktop shortcuts ─────────────────────────────────────────────────
Step-Header "Desktop shortcuts"

$desktop = [Environment]::GetFolderPath("Desktop")
$botPs1  = Join-Path $PSScriptRoot "bot.ps1"

$statusLnk = Join-Path $desktop "Bot Status.lnk"
if (-not (Test-Path $statusLnk)) {
    New-Shortcut -ShortcutPath $statusLnk `
        -Target "powershell.exe" `
        -Args "-NoProfile -ExecutionPolicy Bypass -File `"$botPs1`" status" `
        -WorkDir $RepoRoot
    Write-OK "Created 'Bot Status.lnk' on desktop"
} else {
    Write-SKIP "'Bot Status.lnk' already exists"
}

$discLnk = Join-Path $desktop "Deconnexion Safe.lnk"
if (-not (Test-Path $discLnk)) {
    New-Shortcut -ShortcutPath $discLnk `
        -Target "powershell.exe" `
        -Args "-NoProfile -ExecutionPolicy Bypass -File `"$botPs1`" disconnect" `
        -WorkDir $RepoRoot
    Write-OK "Created 'Deconnexion Safe.lnk' on desktop"
} else {
    Write-SKIP "'Deconnexion Safe.lnk' already exists"
}

# ── STEP 7: Autologon reminder ────────────────────────────────────────────────
Step-Header "Autologon (manual step required)"

Write-Host ""
Write-Host "    !! ACTION REQUIRED for unattended reboots !!" -ForegroundColor Magenta
Write-Host "    The detector needs an interactive user session after every restart."
Write-Host "    Configure Windows auto-logon for the bot user:"
Write-Host "      1. Download Sysinternals Autologon: https://learn.microsoft.com/sysinternals/downloads/autologon"
Write-Host "      2. Run Autologon.exe as Administrator"
Write-Host "      3. Enter bot user credentials and click Enable"
Write-Host "    Without this, the detector will NOT start automatically after a reboot."
Write-Host ""

# ── STEP 8: Final status ──────────────────────────────────────────────────────
Step-Header "Final status"

$botPs1 = Join-Path $PSScriptRoot "bot.ps1"
if (Test-Path $botPs1) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $botPs1 status
} else {
    Write-WARN "bot.ps1 not found at $botPs1 — run it manually after install"
}

Write-Host ""
Write-Host "=== install.ps1 complete ===" -ForegroundColor Green
