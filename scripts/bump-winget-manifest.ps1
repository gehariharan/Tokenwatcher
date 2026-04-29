# Bumps the winget manifest for a new TokenWatcher release.
#
# Downloads the GitHub Release asset, computes SHA-256, and writes a fresh
# winget/<version>/ directory ready to copy into your microsoft/winget-pkgs fork.
#
# Usage:
#   .\scripts\bump-winget-manifest.ps1 -Version 0.2.0

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)] [string] $Version
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$installerName = "TokenWatcher-Setup-$Version.exe"
$installerUrl  = "https://github.com/gehariharan/Tokenwatcher/releases/download/v$Version/$installerName"
$tempPath      = Join-Path $env:TEMP $installerName

Write-Host "Downloading $installerUrl ..."
Invoke-WebRequest -Uri $installerUrl -OutFile $tempPath -UseBasicParsing

$sha256 = (Get-FileHash $tempPath -Algorithm SHA256).Hash
Remove-Item $tempPath -Force
Write-Host "SHA256: $sha256"

$dest = Join-Path $repoRoot "winget\$Version"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$today = (Get-Date).ToString("yyyy-MM-dd")

@"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.version.1.6.0.schema.json

PackageIdentifier: gehariharan.TokenWatcher
PackageVersion: $Version
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
"@ | Set-Content (Join-Path $dest "gehariharan.TokenWatcher.yaml") -Encoding utf8

@"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.installer.1.6.0.schema.json

PackageIdentifier: gehariharan.TokenWatcher
PackageVersion: $Version
InstallerType: nullsoft
Scope: user
InstallModes:
  - interactive
  - silent
  - silentWithProgress
UpgradeBehavior: install
ReleaseDate: $today

Installers:
  - Architecture: x64
    InstallerUrl: $installerUrl
    InstallerSha256: $sha256

ManifestType: installer
ManifestVersion: 1.6.0
"@ | Set-Content (Join-Path $dest "gehariharan.TokenWatcher.installer.yaml") -Encoding utf8

# Reuse the locale file from a prior version if present, otherwise generate one.
$localeSource = Get-ChildItem (Join-Path $repoRoot "winget") -Filter "*.locale.en-US.yaml" -Recurse |
  Where-Object { $_.Directory.Name -ne $Version } | Select-Object -First 1
if ($localeSource) {
  $content = (Get-Content $localeSource.FullName -Raw) -replace 'PackageVersion:.*', "PackageVersion: $Version"
  $content | Set-Content (Join-Path $dest "gehariharan.TokenWatcher.locale.en-US.yaml") -Encoding utf8
} else {
  Write-Warning "No prior locale file found; copy gehariharan.TokenWatcher.locale.en-US.yaml manually."
}

Write-Host ""
Write-Host "Wrote winget\$Version\"
Get-ChildItem $dest | Format-Table Name, Length

Write-Host "Validate with:  winget validate --manifest $dest"
