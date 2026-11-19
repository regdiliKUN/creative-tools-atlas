# Exit 0 if the running bridge serves the studio page AND runs the code currently on disk; else exit 1.
# ASCII-only source (PS 5.1 reads BOM-less scripts as ANSI).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
try {
  $ping = Invoke-RestMethod 'http://127.0.0.1:7843/api/ping' -TimeoutSec 3
  $page = Invoke-WebRequest 'http://127.0.0.1:7843/studio.html' -UseBasicParsing -TimeoutSec 3
} catch { Write-Output 'BRIDGE_UNREACHABLE'; exit 1 }
if ($page.StatusCode -ne 200) { Write-Output 'BRIDGE_NO_PAGE'; exit 1 }
$bytes = @()
foreach ($n in @('tool-bridge.py', 'automation.py')) {
  $f = Join-Path $here $n
  if (Test-Path $f) { $bytes += [IO.File]::ReadAllBytes($f) }
}
$sha = [Security.Cryptography.SHA256]::Create()
$hex = -join ($sha.ComputeHash([byte[]]$bytes) | ForEach-Object { $_.ToString('x2') })
$want = $hex.Substring(0, 12)
if ($ping.stamp -ne $want) { Write-Output ('BRIDGE_STALE running=' + $ping.stamp + ' disk=' + $want); exit 1 }
Write-Output ('BRIDGE_FRESH ' + $want)
exit 0
