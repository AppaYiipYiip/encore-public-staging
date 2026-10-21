#Requires -RunAsAdministrator
<#
.SYNOPSIS
  OPTIONAL one-time setup that removes the last Windows prompts during Android
  development. Review it, then run it yourself once from an elevated PowerShell.

.DESCRIPTION
  Claude/Encore tooling runs fine WITHOUT administrator rights. These items only
  remove prompts or speed things up. Nothing here downloads or installs software.
  Every change is listed below and is idempotent (safe to re-run).

    1. Windows Firewall: inbound ALLOW rules, Private network profile only, for the
       Android emulator/adb/JDK/Dart executables in C:\dev (so no "Allow access"
       dialogs appear). Loopback traffic works without them; this just silences
       the dialogs.
    2. Long paths: enables Win32 long path support (Gradle/NDK can exceed 260
       characters).
    3. Developer Mode: lets non-admin users create symlinks, which Flutter
       needs for Windows/Linux desktop plugin builds (not needed for Android).
    4. (opt-in, -ExcludeFromDefender) Microsoft Defender real-time scan
       exclusions for C:\dev and the project folder: builds are often 2-3x
       faster. This is a security trade-off, so it is OFF unless you pass the
       switch.

  To undo: delete the firewall rules named "Encore dev: *", set the two
  registry values back to 0, and remove the Defender exclusions.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tool\admin-once.ps1
  powershell -ExecutionPolicy Bypass -File tool\admin-once.ps1 -ExcludeFromDefender
#>
param(
  [switch]$ExcludeFromDefender
)

$ErrorActionPreference = 'Stop'

function Write-Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

# ------------------------------------------------------------------ firewall
Write-Step 'Firewall rules (Private profile, inbound allow)'
$jdk = Get-ChildItem 'C:\dev\jdk' -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
$programs = @(
  @{ Name = 'Android emulator (qemu)';
     Path = 'C:\dev\android-sdk\emulator\qemu\windows-x86_64\qemu-system-x86_64.exe' },
  @{ Name = 'Android emulator';
     Path = 'C:\dev\android-sdk\emulator\emulator.exe' },
  @{ Name = 'adb';
     Path = 'C:\dev\android-sdk\platform-tools\adb.exe' },
  @{ Name = 'Dart';
     Path = 'C:\dev\flutter\bin\cache\dart-sdk\bin\dart.exe' },
  @{ Name = 'Flutter tester';
     Path = 'C:\dev\flutter\bin\cache\artifacts\engine\windows-x64\flutter_tester.exe' }
)
if ($jdk) {
  $programs += @{ Name = 'Java (Gradle)'; Path = (Join-Path $jdk.FullName 'bin\java.exe') }
}

foreach ($p in $programs) {
  $display = "Encore dev: $($p.Name)"
  if (-not (Test-Path $p.Path)) { Write-Host "skip (not found): $($p.Path)"; continue }
  if (Get-NetFirewallRule -DisplayName $display -ErrorAction SilentlyContinue) {
    Write-Host "exists: $display"; continue
  }
  New-NetFirewallRule -DisplayName $display -Direction Inbound -Action Allow `
    -Program $p.Path -Profile Private | Out-Null
  Write-Host "created: $display"
}

# ---------------------------------------------------------------- long paths
Write-Step 'Enable long path support'
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
  -Name 'LongPathsEnabled' -Value 1 -Type DWord
Write-Host 'LongPathsEnabled = 1'

# ------------------------------------------------------------ developer mode
Write-Step 'Enable Developer Mode (symlinks without admin)'
$key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
Set-ItemProperty -Path $key -Name 'AllowDevelopmentWithoutDevLicense' -Value 1 -Type DWord
Write-Host 'AllowDevelopmentWithoutDevLicense = 1'

# ------------------------------------------------------------------ defender
if ($ExcludeFromDefender) {
  Write-Step 'Defender real-time scan exclusions (opt-in)'
  $paths = @('C:\dev', 'C:\Users\you\Desktop\encore-workspace')
  foreach ($path in $paths) {
    Add-MpPreference -ExclusionPath $path
    Write-Host "excluded: $path"
  }
} else {
  Write-Host "`nDefender exclusions skipped (pass -ExcludeFromDefender to enable)."
}

Write-Host "`nDone. No restart needed; sign out/in once for Developer Mode to apply everywhere." -ForegroundColor Green
