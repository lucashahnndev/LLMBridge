$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $ScriptPath
$SourcePython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $RepoRoot "frontend"
$FrontendStamp = Join-Path $FrontendDir ".llmbridge-build.sha256"
$BackendRequirements = Join-Path $RepoRoot "backend\requirements.txt"
$BootstrapEnvScript = Join-Path $RepoRoot "scripts\bootstrap_env.py"
$InstallRoot = if ($env:ProgramData) { Join-Path $env:ProgramData "LLMBridge" } else { Join-Path $env:LOCALAPPDATA "LLMBridge" }
$FrontendHost = if ($env:FRONTEND_HOST) { $env:FRONTEND_HOST } else { "127.0.0.1" }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "4173" }

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

function Write-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[x] $Message" -ForegroundColor Red
}

function Invoke-LoggedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$SuccessMessage,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = $RepoRoot,
        [string]$LogPath = ""
    )

    Write-Stage $Label
    if ($LogPath -and (Test-Path -LiteralPath $LogPath)) {
        Remove-Item -LiteralPath $LogPath -Force -ErrorAction SilentlyContinue
    }

    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru -RedirectStandardOutput $LogPath -RedirectStandardError $LogPath
    if ($process.ExitCode -ne 0) {
        Write-Fail $Label
        if ($LogPath -and (Test-Path -LiteralPath $LogPath)) {
            Write-Host ""
            Write-Host "===== $Label log =====" -ForegroundColor DarkYellow
            Get-Content -LiteralPath $LogPath -Tail 80
            Write-Host "===== end log =====" -ForegroundColor DarkYellow
        }
        exit $process.ExitCode
    }

    Write-Ok $SuccessMessage
}

function Get-FrontendFingerprint {
    if (-not (Test-Path -LiteralPath $FrontendDir)) {
        return $null
    }

    $digestBuilder = New-Object System.Text.StringBuilder
    $files = Get-ChildItem -LiteralPath $FrontendDir -Recurse -File | Where-Object {
        $normalized = $_.FullName -replace '/', '\'
        $normalized -notmatch '[\\\/](node_modules|\.svelte-kit)[\\\/]' -and $_.Name -ne ".llmbridge-build.sha256"
    } | Sort-Object FullName

    foreach ($file in $files) {
        $relative = $file.FullName.Substring($FrontendDir.Length).TrimStart([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
        $fileHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
        [void]$digestBuilder.AppendLine("$relative|$fileHash")
    }

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($digestBuilder.ToString())
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }

    return ([System.BitConverter]::ToString($digest) -replace '-', '').ToLowerInvariant()
}

Set-InstallerTheme
Write-Host "LLMBridge Windows bootstrap" -ForegroundColor DarkYellow
Write-Host "source root : $RepoRoot" -ForegroundColor DarkYellow
Write-Host "install root: $InstallRoot" -ForegroundColor DarkYellow
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Fail "python nao foi encontrado no PATH."
    Write-Warn "Instale Python 3.10+ com 'Add Python to PATH'."
    exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Fail "Node.js nao foi encontrado no PATH."
    Write-Warn "Instale Node.js 20+ para preparar o frontend."
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".venv"))) {
    Invoke-LoggedProcess -Label "1/7 [RUN] criando ambiente virtual .venv" -SuccessMessage "1/7 [DONE] ambiente virtual .venv criado" -FilePath "python" -ArgumentList @("-m", "venv", ".venv") -WorkingDirectory $RepoRoot -LogPath (Join-Path $env:TEMP "llmbridge-venv.log")
} else {
    Write-Ok "1/7 [SKIP] ambiente virtual .venv ja existe."
}

Invoke-LoggedProcess -Label "2/7 [RUN] atualizando pip" -SuccessMessage "2/7 [DONE] pip atualizado" -FilePath $SourcePython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip", "--quiet", "--disable-pip-version-check", "--no-input") -WorkingDirectory $RepoRoot -LogPath (Join-Path $env:TEMP "llmbridge-pip.log")

if (Test-Path -LiteralPath $BackendRequirements) {
    Invoke-LoggedProcess -Label "3/7 [RUN] instalando dependencias do backend" -SuccessMessage "3/7 [DONE] dependencias do backend instaladas" -FilePath $SourcePython -ArgumentList @("-m", "pip", "install", "-r", $BackendRequirements, "--quiet", "--disable-pip-version-check", "--no-input") -WorkingDirectory $RepoRoot -LogPath (Join-Path $env:TEMP "llmbridge-backend-install.log")
} else {
    Write-Warn "3/7 [SKIP] backend\\requirements.txt ausente; backend pulado."
}

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "backend"))) {
    New-Item -ItemType Directory -Path (Join-Path $RepoRoot "backend") | Out-Null
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "logs"))) {
    New-Item -ItemType Directory -Path (Join-Path $RepoRoot "logs") | Out-Null
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "bin"))) {
    New-Item -ItemType Directory -Path (Join-Path $RepoRoot "bin") | Out-Null
}

Invoke-LoggedProcess -Label "4/7 [RUN] preparando backend.env e banco SQLite" -SuccessMessage "4/7 [DONE] backend.env e SQLite prontos" -FilePath $SourcePython -ArgumentList @($BootstrapEnvScript) -WorkingDirectory $RepoRoot -LogPath (Join-Path $env:TEMP "llmbridge-bootstrap-env.log")
Invoke-LoggedProcess -Label "4/7 [RUN] validando banco SQLite" -SuccessMessage "4/7 [DONE] banco SQLite validado" -FilePath $SourcePython -ArgumentList @("-c", "import sqlite3, pathlib; db = pathlib.Path('backend/database.db'); db.parent.mkdir(parents=True, exist_ok=True); sqlite3.connect(db).close()") -WorkingDirectory $RepoRoot -LogPath (Join-Path $env:TEMP "llmbridge-sqlite.log")

Invoke-LoggedProcess -Label "5/7 [RUN] aplicando migracoes automaticas" -SuccessMessage "5/7 [DONE] migracoes automaticas aplicadas" -FilePath $SourcePython -ArgumentList @("-m", "backend.migrate") -WorkingDirectory $RepoRoot -LogPath (Join-Path $env:TEMP "llmbridge-migrate.log")

if (Test-Path -LiteralPath (Join-Path $FrontendDir "package.json")) {
    $frontendFingerprint = Get-FrontendFingerprint
    $frontendBuildFresh = $false
    if ($frontendFingerprint -and (Test-Path -LiteralPath $FrontendStamp)) {
        $storedFingerprint = (Get-Content -LiteralPath $FrontendStamp -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        $frontendBuildFresh = $storedFingerprint -eq $frontendFingerprint -and (Test-Path -LiteralPath (Join-Path $FrontendDir ".svelte-kit")) -and (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules"))
    }

    if ($frontendBuildFresh) {
        Write-Ok "6/7 [SKIP] frontend ja estava atualizado."
    } else {
        Invoke-LoggedProcess -Label "6/7 [RUN] instalando dependencias do frontend" -SuccessMessage "6/7 [DONE] dependencias do frontend instaladas" -FilePath "npm.cmd" -ArgumentList @("ci", "--silent", "--no-audit", "--no-fund") -WorkingDirectory $FrontendDir -LogPath (Join-Path $env:TEMP "llmbridge-frontend-install.log")
        Invoke-LoggedProcess -Label "6/7 [RUN] gerando build do frontend" -SuccessMessage "6/7 [DONE] build do frontend concluido" -FilePath "npm.cmd" -ArgumentList @("run", "build", "--silent") -WorkingDirectory $FrontendDir -LogPath (Join-Path $env:TEMP "llmbridge-frontend-build.log")

        if ($frontendFingerprint) {
            Set-Content -LiteralPath $FrontendStamp -Value $frontendFingerprint -Encoding ASCII
        }
    }
} else {
    Write-Warn "6/7 [SKIP] frontend/package.json ausente; frontend ignorado."
}

Write-Stage "7/7 [RUN] registrando o servico automatico do Windows"
Write-Warn "Uma janela elevada pode abrir para concluir essa etapa."
$serviceInstaller = Join-Path $RepoRoot "scripts\install-service.ps1"
$serviceLog = Join-Path $env:TEMP "llmbridge-install-service.log"
if (Test-Path -LiteralPath $serviceLog) {
    Remove-Item -LiteralPath $serviceLog -Force -ErrorAction SilentlyContinue
}

$serviceArgs = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $serviceInstaller,
    "-SourceRoot",
    $RepoRoot,
    "-InstallRoot",
    $InstallRoot,
    "-LogPath",
    $serviceLog,
    "-NoPause"
)

$serviceProcess = Start-Process -FilePath (Join-Path $PSHOME "powershell.exe") -ArgumentList $serviceArgs -WorkingDirectory $InstallRoot -Verb RunAs -Wait -PassThru
if ($serviceProcess.ExitCode -ne 0) {
    Write-Fail "7/7 [FAIL] nao foi possivel registrar o servico."
    if (Test-Path -LiteralPath $serviceLog) {
        Write-Host ""
        Write-Host "===== service installer log =====" -ForegroundColor DarkYellow
        Get-Content -LiteralPath $serviceLog -Tail 80
        Write-Host "===== end log =====" -ForegroundColor DarkYellow
    }
    exit $serviceProcess.ExitCode
}

Write-Ok "7/7 [DONE] servico automatico configurado."
Write-Host ""
Write-Host "[+] Bootstrap local concluido." -ForegroundColor DarkYellow
Write-Host "[+] Instalacao concluida." -ForegroundColor DarkYellow
