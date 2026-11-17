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
  # Round12: retry to avoid false-negative during slow cold start (window race -> 2nd instance)
  for ($i=0; $i -lt 3; $i++) {
    try {
      $r = Invoke-RestMethod -Uri $url -TimeoutSec 1
      if ($r.ok -eq $true) { return $true }
    } catch { }
    if ($i -lt 2) { Start-Sleep -Milliseconds 800 }
  }
  return $false
}

if ($Status) {
  if (Test-Bridge) { Write-Output 'BRIDGE_RUNNING'; exit 0 }
  else { Write-Output 'BRIDGE_STOPPED'; exit 1 }
}

if ($Stop) {
  $conns = Get-NetTCPConnection -LocalPort 7843 -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
      $cl = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $proc.Id) -ErrorAction SilentlyContinue).CommandLine
      if ($proc.ProcessName -match 'python' -and $cl -match 'tool-bridge\.py') {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      } else {
        Write-Output ('SKIP foreign process on port 7843: ' + $proc.ProcessName)
      }
    }
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
Start-Process -FilePath $py -ArgumentList ('"' + $script + '"') -WindowStyle Hidden
Start-Sleep -Seconds 2

if (Test-Bridge) {
  Write-Output 'BRIDGE_STARTED'
  Write-Output ('URL=' + $url)
} else {
  Write-Output 'BRIDGE_FAILED'
  $verOut = & $py --version 2>&1
  Write-Output ('Python detected: ' + $verOut + ' (needs 3.7+)')
  Write-Output ('Make sure python is on PATH and run: ' + $py + ' ' + $script)
  exit 1
}
