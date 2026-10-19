# Build BG Spotter for Windows 10/11 (64-bit).
#
#   powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
#
# Output: dist\BG-Spotter-<version>-win64.zip  — unzip anywhere, run
# "BG Spotter\BG Spotter.exe". No Python install is needed on the target machine.
#
# Windows notes:
#   - PyInstaller cannot cross-compile, so this must run on Windows itself.
#   - The build is unsigned: SmartScreen may warn "Windows protected your PC" on
#     first launch ("More info" -> "Run anyway"). An EV/OV certificate removes it.
#   - ffprobe is optional. Without it the app uses OpenCV for metadata, which
#     cannot read embedded source timecode, so start TC defaults to 01:00:00:00.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Version comes from pyproject.toml so the exe, the zip name and the package
# metadata can never disagree.
$Version = (Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"(.+)"' |
            Select-Object -First 1).Matches.Groups[1].Value
if (-not $Version) { throw "Could not read version from pyproject.toml" }

# --- interpreter ---------------------------------------------------------
if (Test-Path ".venv\Scripts\python.exe") {
    $Py = ".venv\Scripts\python.exe"
} else {
    Write-Host "Creating .venv ..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create a virtual environment" }
    $Py = ".venv\Scripts\python.exe"
}

& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install -e ".[dev]" --quiet

# --- tests: refuse to package a broken build -----------------------------
$env:QT_QPA_PLATFORM = "offscreen"
Write-Host "`nRunning test suite ..."
& $Py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - refusing to build" }

# --- icon + version resource --------------------------------------------
& $Py assets\make_ico.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

$v = $Version.Split(".")
$vs = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($v[0]), $($v[1]), $($v[2]), 0),
    prodvers=($($v[0]), $($v[1]), $($v[2]), 0),
    mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo(
      [StringTable('040904B0', [
        StringValue('CompanyName', 'Akahon Audio LLC'),
        StringValue('FileDescription', 'BG Spotter - edit-point guide-track AAF generator'),
        StringValue('FileVersion', '$Version'),
        StringValue('InternalName', 'BG Spotter'),
        StringValue('LegalCopyright', 'Akahon Audio LLC'),
        StringValue('OriginalFilename', 'BG Spotter.exe'),
        StringValue('ProductName', 'BG Spotter'),
        StringValue('ProductVersion', '$Version')])]),
    VarFileInfo([VarTranslation(0x409, 1200)])
  ]
)
"@
$vs | Out-File -Encoding ascii version_info.txt

# --- build ---------------------------------------------------------------
& $Py -m PyInstaller --noconfirm --windowed --clean `
    --name "BG Spotter" `
    --icon assets\AppIcon.ico `
    --version-file version_info.txt `
    --paths src `
    src\bg_spotter\__main__.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = "dist\BG Spotter\BG Spotter.exe"
if (-not (Test-Path $exe)) { throw "No executable produced" }

# --- package -------------------------------------------------------------
$Zip = "dist\BG-Spotter-$Version-win64.zip"
Remove-Item $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path "dist\BG Spotter" -DestinationPath $Zip

Write-Host "`nBuilt: $Zip"
Write-Host "Ship this zip. Recipients unzip it and run 'BG Spotter\BG Spotter.exe'."
