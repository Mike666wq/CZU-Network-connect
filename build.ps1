param(
    [string]$IndexUrl = "https://pypi.org/simple",
    [string]$PythonCommand = "python",
    [switch]$SkipInstall,
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:OS -ne "Windows_NT") { throw "Build this script on Windows x64, not macOS/Linux." }
Set-Location -LiteralPath $PSScriptRoot
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot ".cache\pyinstaller"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$AppName = -join ([char[]](0x6821, 0x56ED, 0x7F51, 0x52A9, 0x624B))

function Invoke-Python {
    param([string[]]$Arguments)
    & $script:Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw ("Python command failed: " + ($Arguments -join " ")) }
}
if (-not (Test-Path -LiteralPath $Python)) {
    if (-not (Get-Command $PythonCommand -ErrorAction SilentlyContinue)) { throw "Install Python 3.12 x64 and enable PATH." }
    & $PythonCommand -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed" }
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Virtual environment Python was not created" }
Invoke-Python -Arguments @("-c", "import sys,struct; assert sys.version_info[:2] == (3,12), 'Use Python 3.12 for the pinned Windows build'; assert struct.calcsize('P') == 8, 'Use x64 Python'")
if (-not $SkipInstall) {
    Invoke-Python -Arguments @("-m", "pip", "--isolated", "install", "--index-url", $IndexUrl, "--timeout", "30", "--retries", "3", "-r", "requirements-windows.txt")
}
$Version = (& $Python -c "from campus_assistant import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { throw "Cannot read project version" }
if (-not $SkipTests) {
    $OldQt = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        Invoke-Python -Arguments @("-m", "pytest", "-q", "--junitxml=.cache\windows-tests.xml")
    } finally {
        if ($null -eq $OldQt) { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
        else { $env:QT_QPA_PLATFORM = $OldQt }
    }
}
Invoke-Python -Arguments @("tools\windows_version.py", ".cache\windows-version.txt")
Invoke-Python -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--noupx", "--name", $AppName, "--icon", "assets\app-icon.ico", "--add-data", "assets\app-icon.png;.", "--version-file", ".cache\windows-version.txt", "main.py")
# Console-subsystem helper is hidden by CREATE_NO_WINDOW; no Qt in its entry path.
Invoke-Python -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "--console", "--noupx", "--name", "campus-http-worker", "http_worker.py")

# Feed the exact project version into the Inno preprocessor via version.ini.
$BuildDir = Join-Path $PSScriptRoot "build"
if (-not (Test-Path -LiteralPath $BuildDir)) { New-Item -ItemType Directory -Path $BuildDir | Out-Null }
[System.IO.File]::WriteAllText((Join-Path $BuildDir "version.ini"), "[version]`nvalue=$Version`n")

$AppDir = Join-Path (Join-Path $PSScriptRoot "dist") $AppName
$WorkerBuild = Join-Path $PSScriptRoot "dist\campus-http-worker"
$WorkerTarget = Join-Path $AppDir "http-worker"
if (Test-Path -LiteralPath $WorkerTarget) { throw "Unexpected pre-existing worker directory after clean build" }
Copy-Item -LiteralPath $WorkerBuild -Destination $WorkerTarget -Recurse
$OutputExe = Join-Path $AppDir ($AppName + ".exe")

# Compile the Inno Setup installer when iscc is available. The installer packs
# the SAME verified onedir directory, so no extra smoke test is needed beyond
# the portable one below; a missing iscc only skips the installer, not the zip.
$Iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
$SetupExe = $null
if ($Iscc) {
    & $Iscc.Source "installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }
    $SetupExe = Join-Path $PSScriptRoot ("dist\installer\campus-network-assistant-Setup-v" + $Version + ".exe")
    if (-not (Test-Path -LiteralPath $SetupExe)) { throw "Expected installer output missing: $SetupExe" }
} else {
    Write-Warning "iscc.exe (Inno Setup) not found; skipping Setup.exe. The portable ZIP is still produced."
}

# Use stdout-independent report files: the GUI executable has no console streams.
$SmokeReport = Join-Path $PSScriptRoot ".cache\windows-smoke.json"
if (Test-Path -LiteralPath $SmokeReport) { Remove-Item -LiteralPath $SmokeReport }
$SmokeProcess = Start-Process -FilePath $OutputExe -ArgumentList @("--smoke-test", ('"' + $SmokeReport + '"')) -PassThru
if (-not $SmokeProcess.WaitForExit(45000)) {
    $SmokeProcess.Kill()
    throw "Packaged smoke test timed out"
}
$SmokeProcess.Refresh()
if ($SmokeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $SmokeReport)) { throw "Packaged smoke test failed; see .cache\windows-smoke.json" }
$Report = Get-Content -LiteralPath $SmokeReport -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Report.ok) { throw "Packaged HTTP / UI verification did not pass" }
$TestsState = if ($SkipTests) { "tests-skipped" } else { "tests-passed" }
Invoke-Python -Arguments @("tools\windows_build_info.py", ".cache\windows-build-info.json", $TestsState)
if ($SkipTests) {
    Write-Warning "Build complete, but tests were skipped. Release ZIP will not be generated."
} else {
    $ReleaseDir = Join-Path $PSScriptRoot ("dist\release-v" + $Version)
    $PackageArgs = @("tools\package_release.py", "windows", "--app-dir", $AppDir, "--output", $ReleaseDir, "--smoke-report", $SmokeReport, "--build-metadata", ".cache\windows-build-info.json")
    if ($SetupExe -and (Test-Path -LiteralPath $SetupExe)) {
        $PackageArgs += @("--setup-exe", $SetupExe)
    }
    Invoke-Python -Arguments $PackageArgs
    Write-Host ("Release assets: " + $ReleaseDir)
}
Write-Host ("Built: " + $OutputExe)
