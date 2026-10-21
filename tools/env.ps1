# Dot-source from a PowerShell prompt:  . .\tool\env.ps1
# Sets up the toolchain used on the dev machine (see docs/08-dev-environment.md).
# Nothing here needs administrator rights.

$ErrorActionPreference = 'Stop'

$jdk = Get-ChildItem 'C:\dev\jdk' -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if ($jdk) { $env:JAVA_HOME = $jdk.FullName }
$env:ANDROID_HOME     = 'C:\dev\android-sdk'
$env:ANDROID_SDK_ROOT = 'C:\dev\android-sdk'

$paths = @(
  'C:\dev\flutter\bin',
  "$env:JAVA_HOME\bin",
  "$env:ANDROID_HOME\platform-tools",
  "$env:ANDROID_HOME\emulator",
  "$env:ANDROID_HOME\cmdline-tools\latest\bin"
) | Where-Object { $_ -and (Test-Path $_) }

$env:Path = ($paths -join ';') + ';' + $env:Path

# Brave is the user's browser (Flutter web debugging).
$brave = 'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe'
if (Test-Path $brave) { $env:CHROME_EXECUTABLE = $brave }

Write-Host "Flutter : $(flutter --version 2>$null | Select-Object -First 1)"
Write-Host "JAVA    : $env:JAVA_HOME"
Write-Host "ANDROID : $env:ANDROID_HOME"
