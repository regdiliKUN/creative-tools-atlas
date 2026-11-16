param()
# Creator Atlas - one-shot diagnostics for end users.
# ASCII-only source (PS 5.1 reads BOM-less .ps1 as ANSI).
# Usage: powershell -ExecutionPolicy Bypass -File diagnose.ps1
# Reports: core files, browser availability, shortcut target, integrity.

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$ErrorActionPreference = 'Continue'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pkg  = Split-Path -Parent $here
$pass = 0
$fail = 0
$warn = 0
$advice = @()

function Warn([string]$label, [string]$detail) {
  Write-Output ('[WARN] ' + $label + '  ' + $detail)
  $script:warn++
}

function Report([bool]$ok, [string]$label, [string]$detail) {
  if ($ok) {
    Write-Output ('[OK]   ' + $label + '  ' + $detail)
    $script:pass++
  } else {
    Write-Output ('[FAIL] ' + $label + '  ' + $detail)
    $script:fail++
  }
}

Write-Output '=== Creator Atlas Diagnostics ==='
Write-Output ('PACKAGE=' + $pkg)

# --- Check 1: core files ---------------------------------------------------
$core = @('index.html','github-creative-tools-atlas.html','route-a-painter-workstation.html',
          'MANIFEST.md','CHANGELOG.md','icon.ico','icon.png')
$exeName = [char]0x521B + [char]0x4F5C + [char]0x5DE5 + [char]0x5177 + [char]0x661F + [char]0x56FE + '.exe'
$core += $exeName
$missing = @()
foreach ($f in $core) {
  if (-not (Test-Path -LiteralPath (Join-Path $pkg $f))) { $missing += $f }
}
Report ($missing.Count -eq 0) 'CoreFiles' (($core.Count - $missing.Count).ToString() + '/' + $core.Count + ' present')
if ($missing.Count -gt 0) {
  foreach ($m in $missing) { Write-Output ('       missing: ' + $m) }
  $advice += 'Restore the missing files from the original package.'
}

# --- Check 2: browser availability (same candidates as launcher) ----------
$browsers = @(
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
)
$found = @()
foreach ($b in $browsers) { if (Test-Path -LiteralPath $b) { $found += $b } }
# Browser absence is NOT a failure: the launcher has a fallback chain.
if ($found.Count -gt 0) {
  Report $true 'AppBrowser' ($found.Count.ToString() + ' candidate(s) found')
} else {
  Warn 'AppBrowser' 'none found (launcher will use fallback)'
  $advice += 'No Edge/Chrome found; the launcher will fall back to the default browser.'
}

# --- Check 4: desktop shortcut points at this exe -------------------------
$resolvePs1 = Join-Path $here 'resolve-desktop.ps1'
$shortcutPs1 = Join-Path $here 'shortcut.ps1'
$desktopFile = Join-Path $env:TEMP 'atlas-diag-desktop.txt'
$readCfg = Join-Path $env:TEMP 'atlas-diag-read.json'
$readOut = Join-Path $env:TEMP 'atlas-diag-read.txt'
try {
  & $resolvePs1 -OutFile $desktopFile | Out-Null
  $desktop = [System.IO.File]::ReadAllText($desktopFile).Trim()
  $lnkName = [char]0x521B + [char]0x4F5C + [char]0x5DE5 + [char]0x5177 + [char]0x661F + [char]0x56FE + '.lnk'
  $lnk = Join-Path $desktop $lnkName
  $cfg = @{ read = $true; readOut = $readOut; links = @(@{ linkPath = $lnk }) }
  $cfg | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $readCfg -Encoding UTF8
  & $shortcutPs1 -ConfigPath $readCfg | Out-Null
  $line = ''
  foreach ($l in (Get-Content -LiteralPath $readOut -Encoding UTF8)) {
    if ($l.StartsWith('READ|')) { $line = $l; break }
  }
  $target = ($line -split '\|')[2]
  $expected = Join-Path $pkg $exeName
  $ok = ($target -eq $expected)
  Report $ok 'Shortcut' ('target=' + $target)
  if (-not $ok) {
    $advice += 'Shortcut is missing or points elsewhere; run rebuild-shortcut.ps1.'
  }
} catch {
  Warn 'Shortcut' 'unable to read (skipped)'
}

# --- Check 3: runtime dependencies ----------------------------------------
$internal = Join-Path $pkg '_internal'
$runtime = Join-Path $internal 'python313.dll'
Report ((Test-Path -LiteralPath $internal) -and (Test-Path -LiteralPath $runtime)) 'Runtime' '_internal/ present'
if (-not (Test-Path -LiteralPath $internal)) {
  $advice += 'The _internal folder is missing; restore it from the original package.'
}

# --- Check 5: integrity sample (self-contained; verify-package.ps1 uses
#     exit and would terminate this diagnostic script when invoked with &) ---
$bad = @()
$checked = 0
foreach ($l in (Get-Content -LiteralPath (Join-Path $pkg 'MANIFEST.md') -Encoding UTF8)) {
  if ($l -match '^\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([0-9a-fA-F]+)') {
    $rel = $matches[1]; $size = [int]$matches[2]; $hash = $matches[3].ToLower()
    $target = Join-Path $pkg $rel
    if (-not (Test-Path -LiteralPath $target)) { $bad += ($rel + ' missing'); continue }
    $item = Get-Item -LiteralPath $target
    $checked++
    if ($item.Length -ne $size) { $bad += ($rel + ' size'); continue }
    if (-not (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower().StartsWith($hash)) {
      $bad += ($rel + ' hash')
    }
  }
}
Report ($bad.Count -eq 0 -and $checked -gt 0) 'Integrity' ($checked.ToString() + ' files verified')
if ($bad.Count -gt 0) {
  foreach ($b in $bad) { Write-Output ('       bad: ' + $b) }
  $advice += 'Run verify-package.ps1 for details; consider restoring the package.'
}

Write-Output '---'
Write-Output ('RESULT: PASS=' + $pass + ' WARN=' + $warn + ' FAIL=' + $fail)
Write-Output ''
if ($fail -gt 0) {
  Write-Output 'DIAG_FAIL'
  Write-Output 'NEXT: fix the items above, then run this diagnostic again.'
  foreach ($a in $advice) { Write-Output ('ADVICE| ' + $a) }
  exit 1
} else {
  Write-Output 'DIAG_OK'
  Write-Output 'NEXT: double-click the exe (or the desktop shortcut) to start the app.'
  Write-Output '      The app opens in a standalone window, offline.'
  if ($warn -gt 0) {
    Write-Output 'NOTE: warnings are non-blocking; the launcher has fallbacks.'
    foreach ($a in $advice) { Write-Output ('ADVICE| ' + $a) }
  }
  exit 0
}
