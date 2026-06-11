param(
    [string]$SourceRoot = "",
    [string]$InstallRoot = "",
    [switch]$Uninstall,
    [switch]$RemoveFiles,
    [string]$LogPath = "",
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

$transcriptStarted = $false
if ($LogPath) {
    $logParent = Split-Path -Parent $LogPath
    if ($logParent -and -not (Test-Path $logParent)) {
        New-Item -ItemType Directory -Path $logParent | Out-Null
    }
    Start-Transcript -Path $LogPath -Append | Out-Null
    $transcriptStarted = $true
}

trap {
    if ($transcriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {}
        $transcriptStarted = $false
    }
    throw
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Configurando Servico Windows - LLMBridge" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $SourceRoot) {
    $SourceRoot = Split-Path -Parent $ScriptPath
}
if (-not $InstallRoot) {
    $InstallRoot = if ($env:ProgramData) { Join-Path $env:ProgramData "LLMBridge" } else { Join-Path $env:LOCALAPPDATA "LLMBridge" }
}
$InstallScriptsRoot = Join-Path $InstallRoot "scripts"
$InstallBackendRoot = Join-Path $InstallRoot "backend"
$InstallFrontendRoot = Join-Path $InstallRoot "frontend"
$InstallPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$InstallRunScript = Join-Path $InstallScriptsRoot "run-service.ps1"
$InstallEnvPath = Join-Path $InstallBackendRoot ".env"
$InstallDbPath = Join-Path $InstallBackendRoot "database.db"
$SourcePython = Join-Path $SourceRoot ".venv\Scripts\python.exe"
$InstallLogsFolder = Join-Path $InstallRoot "logs"
$FrontendBuildStamp = Join-Path $InstallFrontendRoot ".llmkeyrotator-build.sha256"
$NssmSourceFolder = Join-Path $InstallRoot "bin"
$NssmZip = Join-Path $NssmSourceFolder "nssm-2.24.zip"
$NssmRoot = Join-Path $NssmSourceFolder "nssm-2.24"
$ArchFolder = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
$NssmExe = Join-Path $NssmRoot "$ArchFolder\nssm.exe"
$ServiceName = "LLMBridge"
$DisplayName = "LLMBridge Full Stack Service"
$PowerShellExe = Join-Path $PSHOME "powershell.exe"
$BootstrapEnvScript = Join-Path $InstallScriptsRoot "bootstrap_env.py"
$BackendRequirements = Join-Path $InstallRoot "backend\requirements.txt"
$FrontendPackageJson = Join-Path $InstallFrontendRoot "package.json"
$SourceEnvPath = Join-Path $SourceRoot "backend\.env"
$SourceDbPath = Join-Path $SourceRoot "backend\database.db"

function Write-Stage {
    param([string]$Message)
    Write-Host "[>] $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[x] $Message" -ForegroundColor Red
}

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

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        [System.IO.Directory]::CreateDirectory($Path) | Out-Null
    }
}

function Normalize-PathForComparison {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar).ToLowerInvariant()
}

function Get-FrontendBuildFingerprint {
    if (-not (Test-Path -LiteralPath $SourceRoot)) {
        return $null
    }

    $sourceFrontendRoot = Join-Path $SourceRoot "frontend"
    if (-not (Test-Path -LiteralPath $sourceFrontendRoot)) {
        return $null
    }

    $hashBuilder = New-Object System.Text.StringBuilder
    $files = Get-ChildItem -LiteralPath $sourceFrontendRoot -Recurse -File | Where-Object {
        $normalized = $_.FullName -replace '/', '\'
        $normalized -notmatch '[\\\/](node_modules|\.svelte-kit)[\\\/]'
    } | Sort-Object FullName

    foreach ($file in $files) {
        $relative = $file.FullName.Substring($sourceFrontendRoot.Length).TrimStart([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
        $fileHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
        [void]$hashBuilder.AppendLine("$relative|$fileHash")
    }

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($hashBuilder.ToString())
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }

    return ([System.BitConverter]::ToString($digest) -replace '-', '').ToLowerInvariant()
}

function Test-SameDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    return (Normalize-PathForComparison $Left) -eq (Normalize-PathForComparison $Right)
}

function Test-SameFile {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    return (Normalize-PathForComparison $Left) -eq (Normalize-PathForComparison $Right)
}

function Copy-FileIfNeeded {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (Test-SameFile -Left $Source -Right $Destination) {
        return
    }

    $destinationParent = Split-Path -Parent $Destination
    Ensure-Directory -Path $destinationParent
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Read-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not ($trimmed -match "=")) {
            continue
        }

        $parts = $trimmed.Split("=", 2)
        if ($parts[0].Trim() -eq $Key) {
            return $parts[1]
        }
    }

    return $null
}

function Get-ServiceState {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        return $null
    }

    return $service.Status
}

function Stop-And-RemoveService {
    $state = Get-ServiceState
    if ($null -eq $state) {
        return
    }

    Write-Warn "Servico '$ServiceName' ja existe. Reconfigurando."
    try {
        if ($state -ne "Stopped") {
            Invoke-Nssm -Arguments @("stop", $ServiceName)
        }
    } catch {
        Write-Warn "O servico nao respondeu ao stop; removendo mesmo assim."
    }

    Invoke-Nssm -Arguments @("remove", $ServiceName, "confirm")
}

function Remove-InstallFiles {
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        return
    }

    Write-Warn "Removendo arquivos de instalacao em $InstallRoot"
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force
}

function Sync-SourceTree {
    if (-not (Test-Path -LiteralPath $SourceRoot)) {
        throw "Diretorio de origem nao encontrado em $SourceRoot"
    }

    if (Test-SameDirectory -Left $SourceRoot -Right $InstallRoot) {
        Write-Warn "SourceRoot e InstallRoot apontam para o mesmo diretorio. Pulando sincronizacao."
        return
    }

    Ensure-Directory -Path $InstallRoot

    $excludedSegments = @(
        ".git",
        ".venv",
        "node_modules",
        ".svelte-kit",
        "logs",
        "bin"
    )

    $excludedFiles = @(
        "backend\.env",
        "backend\database.db"
    )

    Write-Stage "Sincronizando arquivos para $InstallRoot"

    $allFiles = Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force -File
    foreach ($file in $allFiles) {
        $relative = $file.FullName.Substring($SourceRoot.Length).TrimStart([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
        if (-not $relative) {
            continue
        }

        $normalized = $relative -replace '/', '\'
        $skip = $false

        foreach ($segment in $excludedSegments) {
            if ($normalized -match "(^|\\)$([regex]::Escape($segment))(\\|$)") {
                $skip = $true
                break
            }
        }

        foreach ($pattern in $excludedFiles) {
            if ($normalized -ieq $pattern) {
                $skip = $true
                break
            }
        }

        if ($skip) {
            continue
        }

        $destination = Join-Path $InstallRoot $relative
        Copy-FileIfNeeded -Source $file.FullName -Destination $destination
    }
}

function Restore-DataFiles {
    param(
        [string]$ExistingEnvBackup,
        [string]$ExistingDbBackup
    )

    if ($ExistingEnvBackup -and (Test-Path -LiteralPath $ExistingEnvBackup)) {
        Ensure-Directory -Path $InstallBackendRoot
        Copy-Item -LiteralPath $ExistingEnvBackup -Destination $InstallEnvPath -Force
    } elseif (-not (Test-Path -LiteralPath $InstallEnvPath) -and (Test-Path -LiteralPath $SourceEnvPath)) {
        Ensure-Directory -Path $InstallBackendRoot
        Copy-Item -LiteralPath $SourceEnvPath -Destination $InstallEnvPath -Force
    }

    Push-Location $InstallRoot
    try {
        & $SourcePython $BootstrapEnvScript
    } finally {
        Pop-Location
    }

    if ($ExistingDbBackup -and (Test-Path -LiteralPath $ExistingDbBackup)) {
        Ensure-Directory -Path $InstallBackendRoot
        Copy-Item -LiteralPath $ExistingDbBackup -Destination $InstallDbPath -Force
    } elseif (-not (Test-Path -LiteralPath $InstallDbPath) -and (Test-Path -LiteralPath $SourceDbPath)) {
        Ensure-Directory -Path $InstallBackendRoot
        Copy-Item -LiteralPath $SourceDbPath -Destination $InstallDbPath -Force
    }

    if (-not (Test-Path -LiteralPath $InstallDbPath)) {
        Push-Location $InstallRoot
        try {
            & $SourcePython -c "import sqlite3, pathlib; db = pathlib.Path('backend/database.db'); db.parent.mkdir(parents=True, exist_ok=True); sqlite3.connect(db).close()"
        } finally {
            Pop-Location
        }
    }
}

function Ensure-InstallPython {
    if (Test-Path -LiteralPath $InstallPython) {
        return
    }

    Write-Stage "Criando ambiente virtual dedicado em $InstallRoot"
    Push-Location $InstallRoot
    try {
        & python -m venv .venv
    } finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $InstallPython)) {
        throw "Falha ao criar o ambiente virtual do servico em $InstallRoot"
    }
}

function Install-Dependencies {
    if (-not (Test-Path -LiteralPath $BackendRequirements)) {
        throw "backend/requirements.txt nao encontrado em $BackendRequirements"
    }

    Write-Stage "Atualizando pip do ambiente do servico"
    Push-Location $InstallRoot
    try {
        & $InstallPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao atualizar pip no ambiente do servico."
        }

        Write-Stage "Instalando dependencias do backend"
        & $InstallPython -m pip install -r $BackendRequirements
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao instalar as dependencias do backend."
        }

        if (Test-Path -LiteralPath $FrontendPackageJson) {
            $frontendFingerprint = Get-FrontendBuildFingerprint
            $frontendNodeModules = Join-Path $InstallFrontendRoot "node_modules"
            $frontendBuildIsFresh = $false
            if ($frontendFingerprint -and (Test-Path -LiteralPath $FrontendBuildStamp)) {
                $storedFingerprint = (Get-Content -LiteralPath $FrontendBuildStamp -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
                $frontendBuildIsFresh = $storedFingerprint -eq $frontendFingerprint -and (Test-Path -LiteralPath (Join-Path $InstallFrontendRoot ".svelte-kit"))
            }

            if ($frontendBuildIsFresh -and (Test-Path -LiteralPath $frontendNodeModules)) {
                Write-Ok "Frontend ja esta atualizado; npm install e build reutilizados."
            } else {
                Write-Stage "Instalando dependencias do frontend"
                Push-Location $InstallFrontendRoot
                try {
                    & npm install
                    if ($LASTEXITCODE -ne 0) {
                        throw "Falha ao instalar as dependencias do frontend."
                    }

                    Write-Stage "Gerando build do frontend"
                    & npm run build
                    if ($LASTEXITCODE -ne 0) {
                        throw "Falha ao gerar o build do frontend."
                    }

                    if ($frontendFingerprint) {
                        Set-Content -LiteralPath $FrontendBuildStamp -Value $frontendFingerprint -Encoding ASCII
                    }
                } finally {
                    Pop-Location
                }
            }
        } else {
            Write-Warn "frontend/package.json nao encontrado. Frontend ignorado."
        }
    } finally {
        Pop-Location
    }
}

function Ensure-Nssm {
    Ensure-Directory -Path $NssmSourceFolder

    if (Test-Path -LiteralPath $NssmExe) {
        return
    }

    Write-Stage "Baixando NSSM"
    $NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip
    Expand-Archive -Path $NssmZip -DestinationPath $NssmSourceFolder -Force
    Remove-Item $NssmZip -Force
    Write-Ok "NSSM pronto em $NssmExe"
}

function Install-Or-UpgradeService {
    Ensure-Nssm

    $serviceLogs = Join-Path $InstallLogsFolder "service.log"
    Ensure-Directory -Path $InstallLogsFolder

    Stop-And-RemoveService

    Invoke-Nssm -Arguments @("install", $ServiceName, $PowerShellExe)

    $AppParameters = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $InstallRunScript
    ) -join " "

    Invoke-Nssm -Arguments @("set", $ServiceName, "AppParameters", $AppParameters)
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppDirectory", $InstallRoot)
    Invoke-Nssm -Arguments @("set", $ServiceName, "DisplayName", $DisplayName)
    Invoke-Nssm -Arguments @("set", $ServiceName, "Start", "SERVICE_AUTO_START")
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppStdout", $serviceLogs)
    Invoke-Nssm -Arguments @("set", $ServiceName, "AppStderr", $serviceLogs)

    Write-Stage "Iniciando servico"
    Start-Service -Name $ServiceName

    Start-Sleep -Seconds 2
    if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
        throw "O servico '$ServiceName' nao apareceu na lista do Windows apos a instalacao."
    }

    $hostValue = Read-EnvValue -Path $InstallEnvPath -Key "HOST"
    $portValue = Read-EnvValue -Path $InstallEnvPath -Key "PORT"
    if (-not $hostValue) { $hostValue = "127.0.0.1" }
    if (-not $portValue) { $portValue = "8000" }

    Write-Host ""
    Write-Host "=======================================================" -ForegroundColor Green
    Write-Ok "LLMBridge configurado como servico automatico do Windows"
    Write-Host "    Instalação: $InstallRoot" -ForegroundColor Gray
    Write-Host "    Backend   : http://${hostValue}:${portValue}" -ForegroundColor Gray
    Write-Host "    Frontend  : http://127.0.0.1:4173" -ForegroundColor Gray
    Write-Host "    Logs      : $serviceLogs" -ForegroundColor Gray
    Write-Host "=======================================================" -ForegroundColor Green
    Write-Host ""
}

function Uninstall-Service {
    $state = Get-ServiceState
    if ($null -eq $state) {
        Write-Warn "Servico '$ServiceName' nao encontrado."
    } else {
        Write-Stage "Removendo servico '$ServiceName'"
        Stop-And-RemoveService
        Write-Ok "Servico '$ServiceName' removido."
    }

    if ($RemoveFiles) {
        Remove-InstallFiles
        Write-Ok "Arquivos de instalacao removidos."
    } else {
        Write-Warn "Arquivos de instalacao mantidos em $InstallRoot"
    }
}

if ($Uninstall) {
    try {
        Uninstall-Service
    } finally {
        if ($transcriptStarted) {
            try {
                Stop-Transcript | Out-Null
            } catch {}
            $transcriptStarted = $false
        }
    }

    if (-not $NoPause) {
        Read-Host "Pressione Enter para fechar esta janela..."
    }
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot ".venv\Scripts\python.exe"))) {
    Write-Fail "Ambiente virtual (.venv) nao encontrado em $SourceRoot."
    Write-Warn "Execute o 'bootstrap.bat' primeiro."
    if ($transcriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {}
        $transcriptStarted = $false
    }
    if (-not $NoPause) {
        Read-Host "Pressione Enter para sair..."
    }
    exit 1
}

try {
    Ensure-Directory -Path $InstallRoot

    $existingEnvBackup = $null
    $existingDbBackup = $null
    if (Test-Path $InstallEnvPath) {
        $existingEnvBackup = Join-Path $env:TEMP "llmkeyrotator-env-backup-$([Guid]::NewGuid().ToString('N')).env"
        Copy-Item -LiteralPath $InstallEnvPath -Destination $existingEnvBackup -Force
    }
    if (Test-Path $InstallDbPath) {
        $existingDbBackup = Join-Path $env:TEMP "llmkeyrotator-db-backup-$([Guid]::NewGuid().ToString('N')).db"
        Copy-Item -LiteralPath $InstallDbPath -Destination $existingDbBackup -Force
    }

    Write-Stage "1/5 sincronizando workspace do servico"
    Sync-SourceTree

    Write-Stage "2/5 restaurando configuracao e dados preservados"
    Restore-DataFiles -ExistingEnvBackup $existingEnvBackup -ExistingDbBackup $existingDbBackup

    Write-Stage "3/5 preparando ambiente isolado do servico"
    Ensure-InstallPython
    Install-Dependencies

    Write-Stage "4/5 aplicando migracoes automaticas"
    Push-Location $InstallRoot
    try {
        & $InstallPython -m backend.migrate
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao aplicar migracoes automaticas."
        }
    } finally {
        Pop-Location
    }

    Write-Stage "5/5 instalando/atualizando servico"
    Install-Or-UpgradeService

    Write-Host ""
    Write-Host "=======================================================" -ForegroundColor Green
    Write-Ok "Instalacao concluida."
    Write-Host "=======================================================" -ForegroundColor Green
    Write-Host ""
} finally {
    foreach ($tempFile in @($existingEnvBackup, $existingDbBackup)) {
        if ($tempFile -and (Test-Path $tempFile)) {
            Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
        }
    }

    if ($transcriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {}
        $transcriptStarted = $false
    }
}

if (-not $NoPause) {
    Read-Host "Pressione Enter para fechar esta janela..."
}
