param([string]$IndexUrl = "https://pypi.org/simple")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot ".cache\pyinstaller"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$AppName = -join ([char[]](0x6821, 0x56ED, 0x7F51, 0x52A9, 0x624B))

if (-not (Test-Path -LiteralPath $Python)) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python was not found. Install Python 3.10 or newer and enable PATH."
    }
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed" }
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Virtual environment Python was not created" }

& $Python -m pip --isolated install --index-url $IndexUrl -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
& $Python -m PyInstaller --noconfirm --windowed --name $AppName main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
$OutputExe = Join-Path (Join-Path (Join-Path $PSScriptRoot "dist") $AppName) ($AppName + ".exe")
Write-Host ("Built: " + $OutputExe)
