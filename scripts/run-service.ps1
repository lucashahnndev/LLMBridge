$ErrorActionPreference = "Stop"

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $ScriptPath
$BackendPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BackendRequirements = Join-Path $RepoRoot "backend\requirements.txt"
$FrontendDir = Join-Path $RepoRoot "frontend"
$FrontendHost = if ($env:FRONTEND_HOST) { $env:FRONTEND_HOST } else { "127.0.0.1" }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "4173" }

if (-not (Test-Path $BackendPython)) {
    throw "Ambiente virtual do backend nao encontrado em $BackendPython"
}

if (-not (Test-Path (Join-Path $FrontendDir ".svelte-kit"))) {
    throw "Frontend nao foi buildado. Execute 'npm run build' em frontend/ antes de iniciar o servico."
}

function Stop-Children {
    param(
        [System.Diagnostics.Process]$BackendProcess,
        [System.Diagnostics.Process]$FrontendProcess
    )

    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        try { $BackendProcess.Kill() } catch {}
        try { $BackendProcess.WaitForExit() } catch {}
    }

    if ($FrontendProcess -and -not $FrontendProcess.HasExited) {
        try { $FrontendProcess.Kill() } catch {}
        try { $FrontendProcess.WaitForExit() } catch {}
    }
}

function Ensure-BackendDependencies {
    if (-not (Test-Path $BackendRequirements)) {
        throw "backend/requirements.txt nao encontrado em $BackendRequirements"
    }

    $probe = Start-Process -FilePath $BackendPython -ArgumentList @("-c", "import annotated_types") -WorkingDirectory $RepoRoot -Wait -PassThru -NoNewWindow
    if ($probe.ExitCode -ne 0) {
        Write-Host "[!] Dependencias do backend ausentes; reinstalando requirements..." -ForegroundColor DarkYellow
        $install = Start-Process -FilePath $BackendPython -ArgumentList @("-m", "pip", "install", "-r", $BackendRequirements) -WorkingDirectory $RepoRoot -Wait -PassThru -NoNewWindow
        if ($install.ExitCode -ne 0) {
            throw "Falha ao reinstalar dependencias do backend (exit code $($install.ExitCode))."
        }
    }
}

try {
    Ensure-BackendDependencies

    Write-Host "[*] Aplicando migracoes automaticas..." -ForegroundColor Yellow
    & $BackendPython -m backend.migrate

    Write-Host "[*] Iniciando backend..." -ForegroundColor Yellow
    $backendArgs = @("-m", "backend.run")
    $backendProcess = Start-Process -FilePath $BackendPython -ArgumentList $backendArgs -WorkingDirectory $RepoRoot -PassThru

    Write-Host "[*] Iniciando frontend preview em $FrontendHost`:$FrontendPort..." -ForegroundColor Yellow
    $frontendProcess = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "preview", "--", "--host", $FrontendHost, "--port", $FrontendPort, "--strictPort") -WorkingDirectory $FrontendDir -PassThru

    while ($true) {
        Start-Sleep -Seconds 2
        if ($backendProcess.HasExited -or $frontendProcess.HasExited) {
            if ($backendProcess.HasExited) {
                Write-Host "[!] Backend finalizou; encerrando frontend." -ForegroundColor Yellow
                throw "Backend process exited."
            }
            if ($frontendProcess.HasExited) {
                Write-Host "[!] Frontend finalizou; encerrando backend." -ForegroundColor Yellow
                throw "Frontend process exited."
            }
        }
    }
}
finally {
    Stop-Children -BackendProcess $backendProcess -FrontendProcess $frontendProcess
}
