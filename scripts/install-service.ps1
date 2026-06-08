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
$PowerShellExe = Join-Path $PSHOME "powershell.exe"

function Invoke-Nssm {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $process = Start-Process -FilePath $NssmExe -ArgumentList $Arguments -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) {
        throw "NSSM returned exit code $($process.ExitCode) while running: $($Arguments -join ' ')"
    }
}

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
    try {
        Invoke-Nssm -Arguments @("stop", $ServiceName)
    } catch {
        Write-Host "[*] O servico nao estava em execucao ou nao respondeu ao stop." -ForegroundColor DarkYellow
    }
    Invoke-Nssm -Arguments @("remove", $ServiceName, "confirm")
}

Invoke-Nssm -Arguments @("install", $ServiceName, $PowerShellExe)

$AppParameters = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $RunScript
) -join " "

Invoke-Nssm -Arguments @("set", $ServiceName, "AppParameters", $AppParameters)
Invoke-Nssm -Arguments @("set", $ServiceName, "AppDirectory", $RepoRoot)
Invoke-Nssm -Arguments @("set", $ServiceName, "DisplayName", $DisplayName)
Invoke-Nssm -Arguments @("set", $ServiceName, "Start", "SERVICE_AUTO_START")
Invoke-Nssm -Arguments @("set", $ServiceName, "AppStdout", (Join-Path $LogsFolder "service.log"))
Invoke-Nssm -Arguments @("set", $ServiceName, "AppStderr", (Join-Path $LogsFolder "service.log"))

Write-Host "[3/3] Iniciando servico..." -ForegroundColor Yellow
Start-Service -Name $ServiceName

Start-Sleep -Seconds 2
if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
    throw "O servico '$ServiceName' nao apareceu na lista do Windows apos a instalacao."
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
