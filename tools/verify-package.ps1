param()
# Creator Atlas - verify package integrity against MANIFEST.md (hash-accurate).
# ASCII-only source (PowerShell 5.1 + ANSI issue). Reads UTF-8 manifest.
# Usage: powershell -ExecutionPolicy Bypass -File verify-package.ps1

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pkg  = Split-Path -Parent $here
$manifest = Join-Path $pkg 'MANIFEST.md'

if (-not (Test-Path -LiteralPath $manifest)) {
  Write-Output 'VERIFY_FAIL: MANIFEST.md missing'
  exit 1
}

$lines = Get-Content -LiteralPath $manifest -Encoding UTF8
$checked = 0
$failed = @()

foreach ($line in $lines) {
  # Table rows: | `file` | 1234 | `abcd1234...` |
  if ($line -match '^\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([0-9a-fA-F]+)') {
    $rel = $matches[1]
    $expectSize = [int]$matches[2]
    $expectHash = $matches[3]
    $target = Join-Path $pkg $rel
    if (-not (Test-Path -LiteralPath $target)) {
      $failed += ($rel + ' (missing)')
      continue
    }
    $item = Get-Item -LiteralPath $target
    $checked++
    if ($item.Length -ne $expectSize) {
      $failed += ($rel + ' (size ' + $item.Length + ' != ' + $expectSize + ')')
      continue
    }
    # Guard against a weakened baseline: manifest hash prefix must be >=8 chars.
    if ($expectHash.Length -lt 8) {
      $failed += ($rel + ' (manifest hash too short)')
      continue
    }
    $actualHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower()
    if (-not $actualHash.StartsWith($expectHash.ToLower())) {
      $failed += ($rel + ' (hash mismatch)')
    }
  }
}

Write-Output ('CHECKED=' + $checked)
if ($failed.Count -gt 0) {
  Write-Output 'VERIFY_FAIL'
  foreach ($f in $failed) { Write-Output ('BAD|' + $f) }
  exit 1
} else {
  Write-Output 'VERIFY_OK'
  exit 0
}
