# ============================================================
# [Chinese note omitted - see README for details]
# ============================================================
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
#
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
#
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
#
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
#      powershell -ExecutionPolicy Bypass -File install-comfyui.ps1
# [Chinese note omitted - see README for details]
#      powershell -ExecutionPolicy Bypass -File install-comfyui.ps1 -WithModels
#
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
# [Chinese note omitted - see README for details]
# ============================================================

param(
  [switch]$WithModels,
  [string]$InstallDir = 'C:\ComfyUI'
)

$ErrorActionPreference = 'Continue'
Write-Output '[see README.md]'
Write-Output ('[see README.md]' + $InstallDir)

# [Chinese note omitted - see README for details]
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Output '[see README.md]'; exit 1
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Output '[see README.md]'; exit 1
}

$pyVer = python --version 2>&1
Write-Output ('Python: ' + $pyVer)

# [Chinese note omitted - see README for details]
if (-not (Test-Path $InstallDir)) {
  Write-Output '[see README.md]'
  git clone https://github.com/Comfy-Org/ComfyUI.git $InstallDir
  if ($LASTEXITCODE -ne 0) { Write-Output '[see README.md]'; exit 1 }
} else {
  Write-Output '[see README.md]'
}

# [Chinese note omitted - see README for details]
$venv = Join-Path $InstallDir 'venv'
if (-not (Test-Path $venv)) {
  Write-Output '[see README.md]'
  python -m venv $venv
}
$py = Join-Path $venv 'Scripts\python.exe'
$pip = Join-Path $venv 'Scripts\pip.exe'

# [Chinese note omitted - see README for details]
Write-Output '[see README.md]'
& $pip install --upgrade pip
& $pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
& $pip install -r (Join-Path $InstallDir 'requirements.txt')

# [Chinese note omitted - see README for details]
Write-Output '[see README.md]'
$bat = Join-Path $InstallDir 'run_nvidia_gpu.bat'
@"
@echo off
cd /d "%~dp0"
"$py" main.py --gpu-only --enable-manager
pause
"@ | Set-Content -LiteralPath $bat -Encoding ASCII
Write-Output ('[see README.md]' + $bat)

# [Chinese note omitted - see README for details]
if ($WithModels) {
  Write-Output '[see README.md]'
  Write-Output '[see README.md]'
  Write-Output '[see README.md]'
  Write-Output '[see README.md]'
  Write-Output '[see README.md]'
  Write-Output '[see README.md]'
}

Write-Output '[see README.md]'
Write-Output ('[see README.md]' + $bat)
Write-Output '[see README.md]'
