$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Configurando Servico Windows - LLMKeyRotator" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $ScriptPath
$BinFolder = Join-Path $RepoRoot "bin"
$LogsFolder = Join-Path $RepoRoot "logs"
$NssmZip = Join-Path $BinFolder "nssm-2.24.zip"
$NssmRoot = Join-Path $BinFolder "nssm-2.24"
$ArchFolder = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
$NssmExe = Join-Path $NssmRoot "$ArchFolder\nssm.exe"
$ServiceName = "LLMKeyRotator"
$DisplayName = "LLMKeyRotator Full Stack Service"
$RunScript = Join-Path $RepoRoot "scripts\run-service.ps1"

if (-not (Test-Path (Join-Path $RepoRoot ".venv\Scripts\python.exe"))) {
    Write-Host "[ERRO] Ambiente virtual (.venv) nao encontrado em $RepoRoot." -ForegroundColor Red
    Write-Host "Execute o 'bootstrap.bat' primeiro." -ForegroundColor Red
    Read-Host "Pressione Enter para sair..."
    exit 1
}

if (-not (Test-Path $BinFolder)) {
    New-Item -ItemType Directory -Path $BinFolder | Out-Null
}

if (-not (Test-Path $LogsFolder)) {
    New-Item -ItemType Directory -Path $LogsFolder | Out-Null
}

if (-not (Test-Path $NssmExe)) {
    Write-Host "[1/3] Baixando NSSM..." -ForegroundColor Yellow
    $NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip
    Expand-Archive -Path $NssmZip -DestinationPath $BinFolder -Force
    Remove-Item $NssmZip -Force
    Write-Host "[+] NSSM instalado em $NssmExe" -ForegroundColor Green
}

if (-not (Test-Path $NssmExe)) {
    Write-Host "[ERRO] nssm.exe nao foi encontrado apos o download." -ForegroundColor Red
    Read-Host "Pressione Enter para sair..."
    exit 1
}

Write-Host "[2/3] Instalando ou atualizando o servico '$ServiceName'..." -ForegroundColor Yellow

if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Write-Host "[*] Servico '$ServiceName' ja existe. Reconfigurando..." -ForegroundColor Yellow
} else {
    & $NssmExe install $ServiceName "powershell.exe" | Out-Null
}

$AppParameters = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $RunScript
) -join " "

& $NssmExe set $ServiceName AppParameters $AppParameters | Out-Null
& $NssmExe set $ServiceName AppDirectory $RepoRoot | Out-Null
& $NssmExe set $ServiceName DisplayName $DisplayName | Out-Null
& $NssmExe set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $NssmExe set $ServiceName AppStdout (Join-Path $LogsFolder "service.log") | Out-Null
& $NssmExe set $ServiceName AppStderr (Join-Path $LogsFolder "service.log") | Out-Null

Write-Host "[3/3] Iniciando servico..." -ForegroundColor Yellow
try {
    Start-Service -Name $ServiceName
} catch {
    Write-Host "[!] O servico foi registrado, mas nao foi possivel iniciar automaticamente." -ForegroundColor Yellow
    Write-Host "    Verifique os logs em $LogsFolder." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host " [+] SUCESSO: o LLMKeyRotator foi configurado como" -ForegroundColor Green
Write-Host "     servico automatico do Windows." -ForegroundColor Green
Write-Host "     Backend: http://127.0.0.1:8009" -ForegroundColor Green
Write-Host "     Frontend: http://127.0.0.1:4173" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Pressione Enter para fechar esta janela..."
