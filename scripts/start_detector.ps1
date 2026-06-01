$script = @'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"
$DetectorDir = Join-Path $Root "detector"

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

Set-Location $DetectorDir
& "C:\Users\BotVm\AppData\Local\Programs\Python\Python311\python.exe" main.py
'@
$script | Out-File -FilePath "C:\Users\BotVm\Desktop\xauusd\scripts\start_detector.ps1" -Encoding utf8