<#
.SYNOPSIS
    Offline setup script for the dots.ocr pricelist parser on Windows.

.DESCRIPTION
    Prepares a Windows machine for fully offline operation:
    1. Creates/activates a Python virtual environment
    2. Installs all pip dependencies (run while online)
    3. Downloads the DotsOCR model weights from HuggingFace
    4. Creates the .env file with offline flags
    5. Verifies the setup

.NOTES
    Run this script ONCE while connected to the internet.
    After that, the system will work fully offline.

.USAGE
    .\scripts\setup_offline.ps1
#>

param(
    [string]$VenvPath = ".\.venv",
    [string]$ModelRepo = "rednote-hilab/dots.ocr",
    [string]$WeightsDir = ".\weights\DotsOCR"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  dots.ocr Offline Setup (Windows)" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ---------------------------------------------------------------
# Step 1: Virtual environment
# ---------------------------------------------------------------
Write-Host "[1/5] Checking virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path "$VenvPath\Scripts\python.exe")) {
    Write-Host "  Creating venv at $VenvPath ..."
    python -m venv $VenvPath
}
$pythonExe = "$VenvPath\Scripts\python.exe"
Write-Host "  Python: $($pythonExe)" -ForegroundColor Green

# ---------------------------------------------------------------
# Step 2: Install dependencies
# ---------------------------------------------------------------
Write-Host "`n[2/5] Installing dependencies..." -ForegroundColor Yellow

# CPU-only PyTorch
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# All other requirements
& $pythonExe -m pip install -r requirements.txt

Write-Host "  Dependencies installed." -ForegroundColor Green

# ---------------------------------------------------------------
# Step 3: Download model weights
# ---------------------------------------------------------------
Write-Host "`n[3/5] Downloading model weights..." -ForegroundColor Yellow
if (Test-Path "$WeightsDir\config.json") {
    Write-Host "  Weights already present at $WeightsDir — skipping download." -ForegroundColor Green
} else {
    Write-Host "  Downloading from HuggingFace: $ModelRepo ..."
    & $pythonExe -c @"
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='$ModelRepo',
    local_dir='$WeightsDir',
    local_dir_use_symlinks=False,
)
print('  Download complete.')
"@
}

# ---------------------------------------------------------------
# Step 4: Create .env for offline mode
# ---------------------------------------------------------------
Write-Host "`n[4/5] Creating .env file..." -ForegroundColor Yellow
$envContent = @"
# Offline mode flags — prevent any network calls at runtime
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1

# Server configuration
DOTS_HOST=127.0.0.1
DOTS_PORT=8080
DOTS_BACKEND=hf
DOTS_DEVICE=cpu
DOTS_MODEL_PATH=$WeightsDir
"@
$envContent | Out-File -Encoding utf8 -FilePath ".\.env"
Write-Host "  .env created." -ForegroundColor Green

# ---------------------------------------------------------------
# Step 5: Verify
# ---------------------------------------------------------------
Write-Host "`n[5/5] Verifying setup..." -ForegroundColor Yellow

$checks = @(
    @{ Name = "Python venv";     OK = (Test-Path $pythonExe) },
    @{ Name = "torch installed"; OK = (& $pythonExe -c "import torch; print('ok')" 2>$null) -eq "ok" },
    @{ Name = "fastapi";         OK = (& $pythonExe -c "import fastapi; print('ok')" 2>$null) -eq "ok" },
    @{ Name = "transformers";    OK = (& $pythonExe -c "import transformers; print('ok')" 2>$null) -eq "ok" },
    @{ Name = "Model weights";   OK = (Test-Path "$WeightsDir\config.json") },
    @{ Name = ".env file";       OK = (Test-Path ".\.env") }
)

$allOk = $true
foreach ($check in $checks) {
    if ($check.OK) {
        Write-Host "  ✓ $($check.Name)" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $($check.Name)" -ForegroundColor Red
        $allOk = $false
    }
}

Write-Host ""
if ($allOk) {
    Write-Host "Setup complete! Start the server with:" -ForegroundColor Cyan
    Write-Host "  $VenvPath\Scripts\python.exe -m api.app" -ForegroundColor White
} else {
    Write-Host "Setup incomplete — check errors above." -ForegroundColor Red
}
