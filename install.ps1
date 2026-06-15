$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/lucashahnndev/LLMKeyRotator.git"
$InstallRoot = if ($env:LLMBRIDGE_INSTALL_DIR) {
    $env:LLMBRIDGE_INSTALL_DIR
} else {
    Join-Path (Join-Path $HOME "apps") "LLMBridge"
}

function Write-Stage {
    param([string]$Message)
    Write-Host "[>] $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

Write-Host "======================================================="
Write-Host "  LLMBridge Windows installer"
Write-Host "======================================================="
Write-Host "  source repo : $RepoUrl"
Write-Host "  target path : $InstallRoot"
Write-Host "======================================================="
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[x] git nao foi encontrado no PATH." -ForegroundColor Red
    exit 1
}

$InstallParent = Split-Path -Parent $InstallRoot
if ($InstallParent -and -not (Test-Path $InstallParent)) {
    Write-Stage "criando pasta pai em $InstallParent"
    New-Item -ItemType Directory -Path $InstallParent | Out-Null
}

if (Test-Path $InstallRoot) {
    Write-Stage "removendo instalacao anterior em $InstallRoot"
    Remove-Item $InstallRoot -Recurse -Force
}

Write-Stage "clonando repositorio"
git clone $RepoUrl $InstallRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "[x] Falha ao clonar o repositorio." -ForegroundColor Red
    exit $LASTEXITCODE
}

Set-Location $InstallRoot
Write-Ok "Executando bootstrap em $PWD"
& .\bootstrap.bat
