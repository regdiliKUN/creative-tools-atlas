param(
  [switch]$Stop,
  [switch]$Status
)
# Creator Atlas Tool Bridge - one-click launcher.
# ASCII-only source. Double-click a shortcut that calls:
#   powershell -ExecutionPolicy Bypass -File start-tool-bridge.ps1
# Use -Status to check, -Stop to kill the running bridge.

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$ErrorActionPreference = 'Continue'

$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$py    = 'python'
$script= Join-Path $here 'tool-bridge.py'
$url   = 'http://127.0.0.1:7843/api/ping'

function Test-Bridge {
  try {
    $r = Invoke-RestMethod -Uri $url -TimeoutSec 2
    return ($r.ok -eq $true)
  } catch { return $false }
}

if ($Status) {
  if (Test-Bridge) { Write-Output 'BRIDGE_RUNNING'; exit 0 }
  else { Write-Output 'BRIDGE_STOPPED'; exit 1 }
}

if ($Stop) {
  $conns = Get-NetTCPConnection -LocalPort 7843 -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 500
  Write-Output ('BRIDGE_STOPPED=' + (-not (Test-Bridge)))
  exit 0
}

if (Test-Bridge) {
  Write-Output 'BRIDGE_ALREADY_RUNNING'
  exit 0
}

# Start hidden, detached from this console.
$code = 'Start-Process -FilePath "' + $py + '" -ArgumentList "' + $script + '" -WindowStyle Hidden'
Invoke-Expression $code
Start-Sleep -Seconds 2

if (Test-Bridge) {
  Write-Output 'BRIDGE_STARTED'
  Write-Output ('URL=' + $url)
} else {
  Write-Output 'BRIDGE_FAILED'
  Write-Output ('Make sure python is on PATH and run: ' + $py + ' ' + $script)
  exit 1
}
