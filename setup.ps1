$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie utworzyc srodowiska Python.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zainstalowac bibliotek.' }
& '.\.venv\Scripts\python.exe' main.py doctor
if ($LASTEXITCODE -ne 0) { throw 'Sprawdzenie srodowiska zakonczylo sie bledem.' }
Write-Host 'Gotowe. Uruchom: .\.venv\Scripts\python.exe main.py demo'
