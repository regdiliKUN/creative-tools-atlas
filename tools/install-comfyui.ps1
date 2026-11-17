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
if ($pyVer -notmatch '3\.(1[0-9]|[0-9])') {
  Write-Output 'WARN: ComfyUI 2026 typically needs Python 3.10+. Continuing but may fail.'
}

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
if ($LASTEXITCODE -ne 0) { Write-Output 'FAIL: pip upgrade failed'; exit 1 }
Write-Output 'STEP 3/4a: Installing PyTorch CUDA (this is the big one, ~2GB)...'
& $pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
if ($LASTEXITCODE -ne 0) {
  Write-Output 'FAIL: PyTorch CUDA install failed. Check network / CUDA wheel availability.'
  Write-Output 'You can retry with a different CUDA index by editing this script.'
  exit 1
}
Write-Output 'STEP 3/4b: Installing ComfyUI requirements...'
& $pip install -r (Join-Path $InstallDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Write-Output 'FAIL: requirements.txt install failed'; exit 1 }

# [Chinese note omitted - see README for details]
Write-Output '[see README.md]'
$bat = Join-Path $InstallDir 'run_nvidia_gpu.bat'
@"
@echo off
cd /d "%~dp0"
"$py" main.py --gpu-only --enable-manager
pause
"@ | Set-Content -LiteralPath $bat -Encoding UTF8
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
