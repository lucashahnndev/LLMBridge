param(
    [string]$SourceRoot = "",
    [string]$InstallRoot = "",
    [string]$NssmPath = "",
    [string]$NssmRoot = "",
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

Write-Host "Configurando servico Windows - LLMBridge" -ForegroundColor Cyan
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
$InstallDataRoot = Join-Path $InstallBackendRoot "data"
$InstallFrontendRoot = Join-Path $InstallRoot "frontend"
$InstallPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$InstallRunScript = Join-Path $InstallScriptsRoot "run-service.ps1"
$InstallEnvPath = Join-Path $InstallBackendRoot ".env"
$InstallDbPath = Join-Path $InstallDataRoot "database.db"
$InstallLegacyDbPath = Join-Path $InstallBackendRoot "database.db"
$SourcePython = Join-Path $SourceRoot ".venv\Scripts\python.exe"
$InstallLogsFolder = Join-Path $InstallRoot "logs"
$FrontendBuildStamp = Join-Path $InstallFrontendRoot ".llmkeyrotator-build.sha256"
$ServiceName = "LLMBridge"
$DisplayName = "LLMBridge Full Stack Service"
$PowerShellExe = Join-Path $PSHOME "powershell.exe"
$BootstrapEnvScript = Join-Path $InstallScriptsRoot "bootstrap_env.py"
$BackendRequirements = Join-Path $InstallRoot "backend\requirements.txt"
$FrontendPackageJson = Join-Path $InstallFrontendRoot "package.json"
$SourceEnvPath = Join-Path $SourceRoot "backend\.env"
$SourceDbPath = Join-Path $SourceRoot "backend\data\database.db"
$SourceLegacyDbPath = Join-Path $SourceRoot "backend\database.db"

function Test-IsAdministrator {
    $currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    Write-Host "  x Abra o PowerShell como Administrador." -ForegroundColor Red
    Write-Host "  ! Reabra o terminal e tente de novo." -ForegroundColor DarkYellow
    if (-not $NoPause) {
        Read-Host "Pressione Enter para sair..."
    }
    exit 1
}

function Set-ConsoleTheme {
    if ($Host.UI -and $Host.UI.RawUI) {
        try {
            $Host.UI.RawUI.BackgroundColor = "DarkGray"
            $Host.UI.RawUI.ForegroundColor = "DarkYellow"
            Clear-Host
        } catch {}
    }
}

Set-ConsoleTheme

function Show-Banner {
    Write-Host "LLMBridge Windows Service Installer" -ForegroundColor DarkYellow
    Write-Host "local, safe, stateful" -ForegroundColor DarkYellow
    Write-Host ""
}

function Write-Stage {
    param([string]$Message)
    Write-Host "  > $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  + $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  ! $Message" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  x $Message" -ForegroundColor Red
}

Show-Banner
Write-Host "  source root : $SourceRoot" -ForegroundColor DarkCyan
Write-Host "  install root: $InstallRoot" -ForegroundColor DarkCyan
if ($LogPath) {
    Write-Host "  log path    : $LogPath" -ForegroundColor DarkCyan
}
Write-Host ""

function Invoke-Nssm {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    if (-not $script:NssmExePath) {
        $script:NssmExePath = Ensure-Nssm
    }

    $process = Start-Process -FilePath $script:NssmExePath -ArgumentList $Arguments -Wait -PassThru -NoNewWindow
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

function Get-NssmCandidates {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($path in @($NssmPath, $NssmRoot)) {
        if ($path -and $path.Trim()) {
            $candidates.Add($path.Trim())
        }
    }

    foreach ($root in @(
        (Join-Path $InstallRoot "bin"),
        (Join-Path $SourceRoot "bin")
    )) {
        if ($root -and (Test-Path -LiteralPath $root)) {
            $candidates.Add($root)
        }
    }

    return $candidates
}

function Copy-NssmAssets {
    $sourceBin = Join-Path $SourceRoot "bin"
    if (-not (Test-Path -LiteralPath $sourceBin)) {
        return
    }

    $sourceEntries = Get-ChildItem -LiteralPath $sourceBin -Force -ErrorAction SilentlyContinue
    if (-not $sourceEntries) {
        return
    }

    $destinationBin = Join-Path $InstallRoot "bin"
    if (Test-SameDirectory -Left $sourceBin -Right $destinationBin) {
        return
    }

    Ensure-Directory -Path $destinationBin

    Write-Stage "Preparando NSSM"
    $sourceFiles = Get-ChildItem -LiteralPath $sourceBin -Recurse -File -ErrorAction SilentlyContinue
    foreach ($sourceFile in $sourceFiles) {
        $relative = $sourceFile.FullName.Substring($sourceBin.Length).TrimStart([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
        if (-not $relative) {
            continue
        }

        $destinationFile = Join-Path $destinationBin $relative
        $destinationParent = Split-Path -Parent $destinationFile
        Ensure-Directory -Path $destinationParent

        if (Test-Path -LiteralPath $destinationFile) {
            continue
        }

        Copy-Item -LiteralPath $sourceFile.FullName -Destination $destinationFile -Force
    }
}

function Get-NssmArchiveCandidates {
    param(
        [string[]]$SearchRoots = @()
    )

    $archives = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($path in @($NssmPath, $NssmRoot)) {
        if (-not $path -or -not (Test-Path -LiteralPath $path)) {
            continue
        }

        $item = Get-Item -LiteralPath $path
        if (-not $item.PSIsContainer -and $item.Extension -ieq ".zip") {
            [void]$archives.Add($item.FullName)
            continue
        }

        if ($item.PSIsContainer) {
            Get-ChildItem -LiteralPath $item.FullName -Recurse -File -Filter "*.zip" -ErrorAction SilentlyContinue | ForEach-Object {
                if ($_.Name -match '^nssm.*\.zip$' -or $_.FullName -match '[\\/](?:nssm|nssm-[^\\/]+)[\\/].*\.zip$') {
                    [void]$archives.Add($_.FullName)
                }
            }
        }
    }

    foreach ($root in $SearchRoots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) {
            continue
        }

        Get-ChildItem -LiteralPath $root -Recurse -File -Filter "*.zip" -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Name -match '^nssm.*\.zip$' -or $_.FullName -match '[\\/](?:nssm|nssm-[^\\/]+)[\\/].*\.zip$') {
                [void]$archives.Add($_.FullName)
            }
        }
    }

    return $archives
}

function Expand-NssmArchives {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$SearchRoots,
        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot
    )

    $archives = Get-NssmArchiveCandidates -SearchRoots $SearchRoots
    foreach ($archivePath in ($archives | Sort-Object)) {
        Write-Stage "Descompactando NSSM"
        try {
            Expand-Archive -LiteralPath $archivePath -DestinationPath $DestinationRoot -Force
        } catch {
            Write-Warn "Ignorando expansao do NSSM ja instalado em uso."
        }
    }
}

function Resolve-NssmExe {
    $archFolder = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }

    foreach ($candidate in Get-NssmCandidates) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }

        if ((Split-Path -Leaf $candidate).ToLowerInvariant() -eq "nssm.exe") {
            return (Get-Item -LiteralPath $candidate).FullName
        }

        $matches = Get-ChildItem -LiteralPath $candidate -Recurse -File -Filter "nssm.exe" -ErrorAction SilentlyContinue | Where-Object {
            $_.FullName -match "[\\/](?:$archFolder)[\\/](?:nssm\.exe)$"
        } | Select-Object -ExpandProperty FullName

        if ($matches) {
            return $matches | Select-Object -First 1
        }
    }

    foreach ($candidate in Get-NssmCandidates) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }

        $matches = Get-ChildItem -LiteralPath $candidate -Recurse -File -Filter "nssm.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
        if ($matches) {
            return $matches | Select-Object -First 1
        }
    }

    return $null
}

function Ensure-Nssm {
    $resolved = Resolve-NssmExe
    if ($resolved) {
        return $resolved
    }

    Copy-NssmAssets
    Expand-NssmArchives -SearchRoots @(
        (Join-Path $SourceRoot "bin"),
        (Join-Path $InstallRoot "bin")
    ) -DestinationRoot (Join-Path $InstallRoot "bin")

    $resolved = Resolve-NssmExe
    if (-not $resolved) {
        throw "NSSM local nao encontrado. Coloque o executavel em bin/ ou informe -NssmPath/-NssmRoot."
    }

    return $resolved
}

function Wait-ForServiceRemoval {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($null -eq (Get-ServiceState)) {
            return $true
        }

        Start-Sleep -Seconds 1
    }

    return $false
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
        return $true
    }

        Write-Warn "Servico antigo encontrado."
    try {
        if ($state -ne "Stopped") {
            Invoke-Nssm -Arguments @("stop", $ServiceName)
        }
    } catch {
        Write-Warn "Stop ignorado; limpando mesmo assim."
    }

    try {
        Invoke-Nssm -Arguments @("remove", $ServiceName, "confirm")
    } catch {
        if ($_.Exception.Message -match 'marked for deletion') {
            Write-Warn "O Windows ainda segura o servico."
        } else {
            throw
        }
    }

    if (Wait-ForServiceRemoval -TimeoutSeconds 30) {
        return $true
    }

    Write-Warn "O Windows ainda segura o servico. Feche o gerenciador e tente de novo."
    Write-Warn "Se persistir, reinicie o Windows."
    return $false
}

function Remove-InstallFiles {
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        return
    }

    Write-Warn "Limpando arquivos antigos do install root."
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force
}

function Sync-SourceTree {
    if (-not (Test-Path -LiteralPath $SourceRoot)) {
        throw "Diretorio de origem nao encontrado em $SourceRoot"
    }

    if (Test-SameDirectory -Left $SourceRoot -Right $InstallRoot) {
        Write-Warn "SourceRoot e InstallRoot sao iguais; pulando copia."
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
        "backend\database.db",
        "backend\data\database.db"
    )

    Write-Stage "Sincronizando workspace"

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
        [string]$ExistingDbBackup,
        [string]$ExistingLegacyDbBackup
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

    Ensure-Directory -Path $InstallDataRoot
    if ($ExistingDbBackup -and (Test-Path -LiteralPath $ExistingDbBackup)) {
        Copy-Item -LiteralPath $ExistingDbBackup -Destination $InstallDbPath -Force
    } elseif ($ExistingLegacyDbBackup -and (Test-Path -LiteralPath $ExistingLegacyDbBackup)) {
        Copy-Item -LiteralPath $ExistingLegacyDbBackup -Destination $InstallDbPath -Force
    } elseif (-not (Test-Path -LiteralPath $InstallDbPath) -and (Test-Path -LiteralPath $SourceDbPath)) {
        Copy-Item -LiteralPath $SourceDbPath -Destination $InstallDbPath -Force
    } elseif (-not (Test-Path -LiteralPath $InstallDbPath) -and (Test-Path -LiteralPath $SourceLegacyDbPath)) {
        Copy-Item -LiteralPath $SourceLegacyDbPath -Destination $InstallDbPath -Force
    }

    if (-not (Test-Path -LiteralPath $InstallDbPath)) {
        Push-Location $InstallRoot
        try {
            & $SourcePython -c "import pathlib, sqlite3; db = pathlib.Path('backend/data/database.db'); db.parent.mkdir(parents=True, exist_ok=True); sqlite3.connect(db).close()"
        } finally {
            Pop-Location
        }
    }
}

function Ensure-InstallPython {
    if (Test-Path -LiteralPath $InstallPython) {
        return
    }

    Write-Stage "Criando .venv dedicado"
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

    Write-Stage "Atualizando pip"
    Push-Location $InstallRoot
    try {
        & $InstallPython -m pip install --upgrade pip --disable-pip-version-check --quiet
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao atualizar pip no ambiente do servico."
        }

        Write-Stage "Instalando backend"
        & $InstallPython -m pip install -r $BackendRequirements --disable-pip-version-check --quiet
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
                Write-Ok "Frontend pronto."
            } else {
                Write-Stage "Preparando frontend"
                Push-Location $InstallFrontendRoot
                try {
                    & npm install --no-audit --no-fund --loglevel=error
                    if ($LASTEXITCODE -ne 0) {
                        throw "Falha ao instalar as dependencias do frontend."
                    }

                    Write-Stage "Gerando build"
                    & npm run build --silent
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
            Write-Warn "Frontend ausente; pulando."
        }
    } finally {
        Pop-Location
    }
}

function Ensure-Nssm {
    Copy-NssmAssets

    $resolved = Resolve-NssmExe
    if (-not $resolved) {
        throw "NSSM local nao encontrado. Coloque o executavel em bin/ ou informe -NssmPath/-NssmRoot."
    }

    return $resolved
}

function Install-Or-UpgradeService {
    $script:NssmExePath = Ensure-Nssm

    $serviceLogs = Join-Path $InstallLogsFolder "service.log"
    Ensure-Directory -Path $InstallLogsFolder

    if (-not (Stop-And-RemoveService)) {
        throw "Servico '$ServiceName' ainda esta marcado para exclusao. Reinicie o Windows e execute o bootstrap novamente."
    }

    $installDeadline = (Get-Date).AddSeconds(30)
    while ($true) {
        try {
            Invoke-Nssm -Arguments @("install", $ServiceName, $PowerShellExe)
            break
        } catch {
            $errorText = $_.Exception.Message
            if (($errorText -match 'marked for deletion') -or ($errorText -match 'exit code 1072')) {
                if ((Get-Date) -lt $installDeadline) {
                    Write-Warn "O Windows ainda segura o servico; tentando de novo..."
                    Start-Sleep -Seconds 2
                    continue
                }

                throw "Servico '$ServiceName' ainda esta marcado para exclusao. Reinicie o Windows e execute o bootstrap novamente."
            }

            throw
        }
    }

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
    Write-Host "  +----------------------------------------+" -ForegroundColor Green
    Write-Host "  |                 Pronto!                |" -ForegroundColor Green
    Write-Host "  | Backend  http://${hostValue}:${portValue}" -ForegroundColor Green
    Write-Host "  | Frontend http://127.0.0.1:4173" -ForegroundColor Green
    Write-Host "  +----------------------------------------+" -ForegroundColor Green
    Write-Host ""
}

function Uninstall-Service {
    $state = Get-ServiceState
    if ($null -eq $state) {
        Write-Warn "Servico nao encontrado."
    } else {
        Write-Stage "Removendo servico"
        if (Stop-And-RemoveService) {
            Write-Ok "Servico removido."
        } else {
            Write-Warn "Servico pode pedir reboot."
        }
    }

    if ($RemoveFiles) {
        Remove-InstallFiles
        Write-Ok "Arquivos removidos."
    } else {
        Write-Warn "Arquivos mantidos."
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
    Write-Fail "Nao encontrei o .venv."
    Write-Warn "Execute o bootstrap primeiro."
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
    $existingLegacyDbBackup = $null
    if (Test-Path $InstallEnvPath) {
        $existingEnvBackup = Join-Path $env:TEMP "llmkeyrotator-env-backup-$([Guid]::NewGuid().ToString('N')).env"
        Copy-Item -LiteralPath $InstallEnvPath -Destination $existingEnvBackup -Force
    }
    if (Test-Path $InstallDbPath) {
        $existingDbBackup = Join-Path $env:TEMP "llmkeyrotator-db-backup-$([Guid]::NewGuid().ToString('N')).db"
        Copy-Item -LiteralPath $InstallDbPath -Destination $existingDbBackup -Force
    } elseif (Test-Path $InstallLegacyDbPath) {
        $existingLegacyDbBackup = Join-Path $env:TEMP "llmkeyrotator-db-legacy-backup-$([Guid]::NewGuid().ToString('N')).db"
        Copy-Item -LiteralPath $InstallLegacyDbPath -Destination $existingLegacyDbBackup -Force
    }

    Write-Stage "1/5 workspace"
    Sync-SourceTree

    Write-Stage "2/5 dados"
    Restore-DataFiles -ExistingEnvBackup $existingEnvBackup -ExistingDbBackup $existingDbBackup -ExistingLegacyDbBackup $existingLegacyDbBackup

    Write-Stage "3/5 ambiente"
    Ensure-InstallPython
    Install-Dependencies

    Write-Stage "4/5 migracoes"
    Push-Location $InstallRoot
    try {
        & $InstallPython -m backend.migrate
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao aplicar migracoes automaticas."
        }
    } finally {
        Pop-Location
    }

    Write-Stage "5/5 servico"
    Install-Or-UpgradeService

    Write-Host ""
    Write-Host "  +----------------------------------------+" -ForegroundColor Green
    Write-Host "  |                 Feito!                 |" -ForegroundColor Green
    Write-Host "  |     Servico configurado com sucesso    |" -ForegroundColor Green
    Write-Host "  +----------------------------------------+" -ForegroundColor Green
    Write-Host ""
} finally {
    foreach ($tempFile in @($existingEnvBackup, $existingDbBackup)) {
        if ($tempFile -and (Test-Path $tempFile)) {
            Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
        }
    }
    if ($existingLegacyDbBackup -and (Test-Path $existingLegacyDbBackup)) {
        Remove-Item -LiteralPath $existingLegacyDbBackup -Force -ErrorAction SilentlyContinue
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
