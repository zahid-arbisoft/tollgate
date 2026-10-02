# Local Windows build: portable exe dir + per-user installer + portable zip.
# Run from the repo root on Windows. Requires: uv, Inno Setup (iscc on PATH)
# for the installer step (skipped gracefully if absent).
$ErrorActionPreference = "Stop"
$version = if ($env:TOLLGATE_VERSION) { $env:TOLLGATE_VERSION } else { "0.1.0" }

uv sync --extra desktop --dev
if ($LASTEXITCODE -ne 0) { exit 1 }

uv run pyinstaller packaging/tollgate.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { exit 1 }

# Portable zip — always produced (SmartScreen/AV fallback path).
$zip = "tollgate-portable-$version-windows-x64.zip"
if (TestPath $zip) { Remove-Item $zip }
Compress-Archive -Path dist\Tollgate\* -DestinationPath $zip
Write-Host "portable zip: $zip"

# Per-user installer via Inno Setup (PrivilegesRequired=lowest, no UAC).
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
  $isccPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
  if (Test-Path $isccPath) { $iscc = $isccPath }
}
if ($iscc) {
  $env:TOLLGATE_VERSION = $version
  & $iscc "packaging\windows\tollgate.iss"
  Write-Host "installer: packaging\windows\out\tollgate-setup-$version.exe"
} else {
  Write-Warning "Inno Setup (iscc) not found — skipped installer. Install from https://jrsoftware.org/isdl.php to build it."
}
