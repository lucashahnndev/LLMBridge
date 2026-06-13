$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/lucashahnndev/LLMKeyRotator.git"
$InstallRoot = if ($env:LLMBRIDGE_INSTALL_DIR) {
    $env:LLMBRIDGE_INSTALL_DIR
} else {
    Join-Path (Join-Path $HOME "apps") "LLMBridge"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[x] git nao foi encontrado no PATH." -ForegroundColor Red
    exit 1
}

$InstallParent = Split-Path -Parent $InstallRoot
if ($InstallParent -and -not (Test-Path $InstallParent)) {
    New-Item -ItemType Directory -Path $InstallParent | Out-Null
}

if (Test-Path $InstallRoot) {
    Remove-Item $InstallRoot -Recurse -Force
}

git clone $RepoUrl $InstallRoot
Set-Location $InstallRoot
& .\bootstrap.bat
