@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LLMBridge - One-Shot Installer

set "ROOT=%~dp0"
pushd "%ROOT%" >nul
set "OK=[+]"
set "STEP=[>]"
set "WARN=[!]"
set "ERR=[x]"
set "INSTALL_ROOT=%ProgramData%\LLMBridge"

for %%I in ("%ROOT%") do set "ROOT_FULL=%%~fI"
for %%I in ("%INSTALL_ROOT%") do set "INSTALL_ROOT_FULL=%%~fI"

if /I "%ROOT_FULL%"=="%INSTALL_ROOT_FULL%" (
    echo %ERR% Este bootstrap nao deve rodar de dentro de %INSTALL_ROOT%.
    echo %WARN% Use um clone local, por exemplo: %USERPROFILE%\apps\LLMBridge
    echo %WARN% Depois execute bootstrap.bat nesse clone para copiar a instalacao para ProgramData.
    pause
    popd
    exit /b 1
)

echo =======================================================
color 0E
echo █     █     █   █ ████  ████  ███ ████   ███  █████
echo █     █     ██ ██ █   █ █   █  █  █   █ █     █
echo █     █     █ █ █ ████  ████   █  █   █ █  ██ ████
echo █     █     █   █ █   █ █  █   █  █   █ █   █ █
echo █████ █████ █   █ ████  █   █ ███ ████   ███  █████
echo.
echo                          LLMBridge
echo                    local one-shot installer
color 07
echo =======================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo %ERR% Python nao encontrado no PATH.
    echo %WARN% Instale Python 3.10+ com "Add Python to PATH".
    pause
    popd
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo %ERR% Node.js nao encontrado no PATH.
    echo %WARN% Instale Node.js 20+ para preparar o frontend.
    pause
    popd
    exit /b 1
)

if not exist ".venv" (
    echo %STEP% 1/7 criando ambiente virtual .venv
    python -m venv .venv
    if errorlevel 1 (
        echo %ERR% Falha ao criar o ambiente virtual.
        pause
        popd
        exit /b 1
    )
) else (
    echo %OK% Ambiente virtual .venv ja existe.
)

echo %STEP% 2/7 atualizando pip
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check --no-input

if exist "backend\requirements.txt" (
    echo %STEP% 3/7 instalando bibliotecas
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt --quiet --disable-pip-version-check --no-input
    if errorlevel 1 (
        echo %ERR% Falha ao instalar as bibliotecas.
        pause
        popd
        exit /b 1
    )
) else (
    echo %WARN% backend\requirements.txt ausente; backend pulado.
)

if not exist "backend" mkdir backend
if not exist "logs" mkdir logs
if not exist "bin" mkdir bin

if not exist "%INSTALL_ROOT%" mkdir "%INSTALL_ROOT%" >nul 2>&1

echo %STEP% 4/7 preparando backend\.env e banco SQLite
python scripts\bootstrap_env.py
if errorlevel 1 (
    echo %ERR% Falha ao preparar backend\.env.
    pause
    popd
    exit /b 1
)

".venv\Scripts\python.exe" -c "import sqlite3, pathlib; db = pathlib.Path('backend/database.db'); db.parent.mkdir(parents=True, exist_ok=True); sqlite3.connect(db).close()"
if errorlevel 1 (
    echo %ERR% Falha ao inicializar o banco SQLite.
    pause
    popd
    exit /b 1
)

echo %STEP% 5/7 aplicando migracoes automaticas
".venv\Scripts\python.exe" -m backend.migrate
if errorlevel 1 (
    echo %ERR% Falha ao aplicar migracoes automaticas.
    pause
    popd
    exit /b 1
)

set "FRONTEND_LOG=%TEMP%\llmbridge-frontend-install.log"
set "FRONTEND_BUILD_LOG=%TEMP%\llmbridge-frontend-build.log"
if exist "%FRONTEND_LOG%" del /f /q "%FRONTEND_LOG%" >nul 2>&1
if exist "%FRONTEND_BUILD_LOG%" del /f /q "%FRONTEND_BUILD_LOG%" >nul 2>&1

echo %STEP% 6/7 instalando dependencias e build do frontend
pushd frontend >nul
npm ci --silent --no-audit --no-fund > "%FRONTEND_LOG%" 2>&1
if errorlevel 1 (
    popd
    echo %ERR% Falha ao instalar dependencias do frontend.
    echo.
    echo ===== frontend install log =====
    type "%FRONTEND_LOG%"
    echo ===== end log =====
    pause
    popd
    exit /b 1
)

npm run build --silent > "%FRONTEND_BUILD_LOG%" 2>&1
if errorlevel 1 (
    popd
    echo %ERR% Falha ao gerar o build do frontend.
    echo.
    echo ===== frontend build log =====
    type "%FRONTEND_BUILD_LOG%"
    echo ===== end log =====
    pause
    popd
    exit /b 1
)
popd >nul
if exist "%FRONTEND_LOG%" del /f /q "%FRONTEND_LOG%" >nul 2>&1
if exist "%FRONTEND_BUILD_LOG%" del /f /q "%FRONTEND_BUILD_LOG%" >nul 2>&1
echo %OK% Dependencias e build do frontend concluido.

echo %STEP% 7/7 registrando o servico automatico do Windows
set "SERVICE_INSTALL_LOG=%TEMP%\llmbridge-install-service.log"
if exist "%SERVICE_INSTALL_LOG%" del /f /q "%SERVICE_INSTALL_LOG%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$repo = (Get-Location).Path; $installRoot = Join-Path $env:ProgramData 'LLMBridge'; $log = '%SERVICE_INSTALL_LOG%'; $script = Join-Path $repo 'scripts\install-service.ps1'; $serviceArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$script,'-SourceRoot',$repo,'-InstallRoot',$installRoot,'-LogPath',$log,'-NoPause'); $p = Start-Process -FilePath powershell -ArgumentList $serviceArgs -WorkingDirectory $installRoot -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 (
    echo %ERR% Falha ao registrar o servico.
    if exist "%SERVICE_INSTALL_LOG%" (
        echo.
        echo ===== service installer log =====
        type "%SERVICE_INSTALL_LOG%"
        echo ===== end log =====
    )
    pause
    popd
    exit /b 1
)

echo.
echo %OK% Bootstrap local concluido.
echo %OK% Instalacao concluida.
if exist "%SERVICE_INSTALL_LOG%" del /f /q "%SERVICE_INSTALL_LOG%" >nul 2>&1
pause
popd
