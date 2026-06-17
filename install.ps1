$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/lucashahnndev/LLMKeyRotator.git"
$InstallRoot = if ($env:LLMBRIDGE_INSTALL_DIR) {
    $env:LLMBRIDGE_INSTALL_DIR
} else {
    Join-Path (Join-Path $HOME "apps") "LLMBridge"
}
$InstallRootExists = Test-Path -LiteralPath $InstallRoot
$ExistingRepoRoot = $null

function Set-InstallerTheme {
    if ($Host.UI -and $Host.UI.RawUI) {
        try {
            $Host.UI.RawUI.BackgroundColor = "DarkGray"
            $Host.UI.RawUI.ForegroundColor = "DarkYellow"
            Clear-Host
        } catch {}
    }
}

function Write-Stage {
    param([string]$Message)
    Write-Host "[>] $Message" -ForegroundColor DarkYellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor DarkYellow
}

Set-InstallerTheme
Write-Host "LLMBridge Windows installer" -ForegroundColor DarkYellow
Write-Host "source repo : $RepoUrl" -ForegroundColor DarkYellow
Write-Host "clone path  : $InstallRoot" -ForegroundColor DarkYellow
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

if ($InstallRootExists) {
    $gitDir = Join-Path $InstallRoot ".git"
    $bootstrapScript = Join-Path $InstallRoot "bootstrap.ps1"
    if ((Test-Path $gitDir) -and (Test-Path $bootstrapScript)) {
        $ExistingRepoRoot = $InstallRoot
        Write-Ok "clone local existente encontrado em $InstallRoot"
        Write-Host "  ! Reutilizando a copia local para evitar apagar arquivos em uso." -ForegroundColor DarkYellow
    } else {
        Write-Stage "removendo clone local anterior em $InstallRoot"
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force
    }
}

if (-not $ExistingRepoRoot) {
    Write-Stage "clonando repositorio"
    git clone $RepoUrl $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[x] Falha ao clonar o repositorio." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Set-Location $InstallRoot
Write-Ok "Executando bootstrap em $PWD"
& .\bootstrap.ps1
