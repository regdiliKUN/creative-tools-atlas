# ComfyUI installer - fixed for local env (Python 3.12 + CUDA 12.4)
# Why: system Python 3.14 has NO PyTorch CUDA wheel; use the installed Python 3.12.
# ASCII-only source (PS 5.1 reads BOM-less .ps1 as ANSI).
param(
  [string]$InstallDir = 'C:\ComfyUI'
)

$ErrorActionPreference = 'Continue'
$py312 = 'C:\Users\xukunhang\AppData\Local\Programs\Python\Python312\python.exe'
$uv    = 'C:\Users\xukunhang\.local\bin\uv.exe'

Write-Output "=== ComfyUI install (Python 3.12 + CUDA 12.4) ==="
if (-not (Test-Path $py312)) { Write-Output "FAIL: Python 3.12 not found at $py312"; exit 1 }
& $py312 --version
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Output "FAIL: git not in PATH"; exit 1 }

# 1) clone repo
if (-not (Test-Path $InstallDir)) {
  Write-Output "STEP 1/5: git clone ComfyUI -> $InstallDir"
  git clone https://github.com/Comfy-Org/ComfyUI.git $InstallDir
  if ($LASTEXITCODE -ne 0) { Write-Output "FAIL: git clone"; exit 1 }
} else {
  Write-Output "STEP 1/5: repo already exists at $InstallDir"
}

# 2) venv with Python 3.12
$venv = Join-Path $InstallDir 'venv'
$vpy  = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $vpy)) {
  Write-Output "STEP 2/5: create venv with Python 3.12"
  & $py312 -m venv $venv
  if (-not (Test-Path $vpy)) { Write-Output "FAIL: venv create"; exit 1 }
} else {
  Write-Output "STEP 2/5: venv exists"
}

# 3) PyTorch CUDA 12.4 (driver 621 supports it; Python 3.12 has cp312 wheels)
Write-Output "STEP 3/5: install PyTorch CUDA 12.4 (~2.5GB, takes a while)..."
if (Test-Path $uv) {
  & $uv pip install --python $vpy torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
} else {
  & $vpy -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
}
if ($LASTEXITCODE -ne 0) { Write-Output "WARN: torch cu124 failed, retry cu121..."; & $vpy -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 }

# 4) ComfyUI requirements
Write-Output "STEP 4/5: install ComfyUI requirements.txt"
if (Test-Path $uv) {
  & $uv pip install --python $vpy -r (Join-Path $InstallDir 'requirements.txt')
} else {
  & $vpy -m pip install -r (Join-Path $InstallDir 'requirements.txt')
}
if ($LASTEXITCODE -ne 0) { Write-Output "WARN: requirements install had errors" }

# 5) launcher + verify
Write-Output "STEP 5/5: write launcher and verify"
$bat = Join-Path $InstallDir 'run_nvidia_gpu.bat'
@"
@echo off
cd /d "%~dp0"
"$vpy" main.py --gpu-only --enable-manager
pause
"@ | Set-Content -LiteralPath $bat -Encoding ASCII
& $vpy -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
Write-Output "DONE: launcher at $bat"
