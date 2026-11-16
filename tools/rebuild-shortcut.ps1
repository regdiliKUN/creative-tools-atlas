param([switch]$ReadBack)
# Creator Atlas - rebuild desktop shortcut.
# ASCII-only source (PowerShell 5.1 reads BOM-less .ps1 as ANSI; non-ASCII
# literals would be mangled). All Chinese strings come from UTF-8 JSON.
# Usage:
#   powershell -ExecutionPolicy Bypass -File rebuild-shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File rebuild-shortcut.ps1 -ReadBack

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pkg  = Split-Path -Parent $here
$ps1  = Join-Path $here 'shortcut.ps1'

# Resolve real Desktop (redirected / OneDrive safe) via helper, output to UTF-8 file.
$resolvePs1 = Join-Path $here 'resolve-desktop.ps1'
$desktopFile = Join-Path $env:TEMP 'atlas-desktop.txt'
& $resolvePs1 -OutFile $desktopFile | Out-Null
$desktop = [System.IO.File]::ReadAllText($desktopFile).Trim()
Write-Output ("DESKTOP=" + $desktop)

$exe = Join-Path $pkg ([char]0x521B + [char]0x4F5C + [char]0x5DE5 + [char]0x5177 + [char]0x661F + [char]0x56FE + '.exe')
$lnk = Join-Path $desktop ([char]0x521B + [char]0x4F5C + [char]0x5DE5 + [char]0x5177 + [char]0x661F + [char]0x56FE + '.lnk')
$desc = [char]0x521B + [char]0x4F5C + [char]0x5DE5 + [char]0x5177 + [char]0x661F + [char]0x56FE + ' - local app'

$cfgObj = @{
  links = @(@{
    linkPath    = $lnk
    target      = $exe
    workDir     = $pkg
    icon        = ($exe + ',0')
    description = $desc
  })
}
$cfgPath = Join-Path $env:TEMP 'creator-atlas-rebuild-config.json'
$cfgObj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $cfgPath -Encoding UTF8

if ($ReadBack) {
  $rb = @{
    read = $true
    readOut = (Join-Path $env:TEMP 'atlas-readback.txt')
    links = @(@{ linkPath = $lnk })
  }
  $rbPath = Join-Path $env:TEMP 'creator-atlas-readback-config.json'
  $rb | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $rbPath -Encoding UTF8
  & $ps1 -ConfigPath $rbPath
  Get-Content -LiteralPath (Join-Path $env:TEMP 'atlas-readback.txt') -Encoding UTF8
} else {
  & $ps1 -ConfigPath $cfgPath
}
