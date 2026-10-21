# One command that proves a change is good (docs/engineering/testing.md).
#   .\tools\check.ps1            # codegen + format + analyze + every app test + the shared package
#   .\tools\check.ps1 -Quick     # skip codegen (when already generated) and the slow widget/golden suite
#   .\tools\check.ps1 -Server    # also run every server test suite (Python and the Dart hub)
#   .\tools\check.ps1 -Live      # also run the opt-in live-server tests
param(
  [switch]$Quick,
  [switch]$Server,
  [switch]$Live
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"
$Repo = (Resolve-Path "$PSScriptRoot\..").Path

function Step($name, [scriptblock]$body) {
  Write-Host "`n=== $name ===" -ForegroundColor Cyan
  & $body
  if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

# ---- the app (Flutter project root: app/)
Set-Location "$Repo\app"

# Generated Drift code is not committed: make it when it is missing, or always in the full run.
if (-not $Quick -or -not (Test-Path 'lib\data\db\app_database.g.dart')) {
  Step 'pub get' { flutter pub get }
  Step 'build_runner (Drift)' { dart run build_runner build --delete-conflicting-outputs }
}

Step 'format' {
  dart format --output=none --set-exit-if-changed lib test
}

Step 'analyze (warnings and infos are errors)' {
  dart analyze --fatal-infos
}

# No test folder is listed by name in the full run, so a new folder can never be forgotten.
# Only two tags are kept out of the main run: 'live' needs a real server, 'perf' measures time.
if ($Quick) {
  Step 'quick tests (no widget/golden suite)' {
    flutter test --no-pub --exclude-tags perf,live test/core test/data test/domain test/playback test/app test/architecture_test.dart
  }
} else {
  Step 'all tests (every folder; tags perf and live excluded)' {
    flutter test --no-pub --exclude-tags perf,live
  }
  Step 'performance budgets (tag perf)' {
    flutter test --no-pub --tags perf
  }
}

if ($Live) {
  Step 'live server tests (read-only)' {
    if (-not $env:ENCORE_SERVER_URL) { throw 'Set ENCORE_SERVER_URL, ENCORE_USER, ENCORE_PASSWORD first.' }
    $env:ENCORE_LIVE = '1'
    flutter test --no-pub test/live
  }
}

# ---- the shared pure-Dart package (Jam rules): own analysis options and test runner, no Flutter
Step 'session package: format, analyze and test' {
  Push-Location "$Repo\packages\encore_session"
  try {
    dart pub get
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    dart format --output=none --set-exit-if-changed lib test
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    dart analyze --fatal-infos
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    dart test
  } finally { Pop-Location }
}

# ---- the server
if ($Server) {
  Step 'jam hub (Dart): analyze and test' {
    Push-Location "$Repo\server\legacy\hub"
    try {
      dart pub get
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
      dart analyze --fatal-infos
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
      dart test
    } finally { Pop-Location }
  }
  foreach ($svc in 'encore-fetch', 'encore-people', 'encore-admin', 'encore-quality', 'encore-recs') {
    Step "server $svc (Python tests)" {
      Push-Location "$Repo\server\legacy\$svc"
      try { python -m unittest discover -s tests } finally { Pop-Location }
    }
  }
}

Write-Host "`nAll checks passed." -ForegroundColor Green
