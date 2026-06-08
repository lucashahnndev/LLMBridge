@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LLMKeyRotator - One-Shot Installer

set "ROOT=%~dp0"
pushd "%ROOT%" >nul
set "OK=[+]"
set "STEP=[>]"
set "WARN=[!]"
set "ERR=[x]"

echo =======================================================
echo   LLMKeyRotator ^| one-shot installer ^| Windows
echo =======================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo %ERR% Python nao foi encontrado no PATH.
    echo %WARN% Instale Python 3.10+ e marque "Add Python to PATH".
    pause
    popd
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo %ERR% Node.js nao foi encontrado no PATH.
    echo %WARN% Instale Node.js 20+ para preparar o frontend SvelteKit.
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
".venv\Scripts\python.exe" -m pip install --upgrade pip

if exist "backend\requirements.txt" (
    echo %STEP% 3/7 instalando dependencias do backend
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo %ERR% Falha ao instalar as dependencias.
        pause
        popd
        exit /b 1
    )
) else (
    echo %WARN% backend\requirements.txt nao encontrado. Backend ignorado.
)

if exist "frontend\package.json" (
    echo %STEP% 4/7 instalando dependencias do frontend
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo %ERR% Falha ao instalar as dependencias do frontend.
        popd
        pause
        popd
        exit /b 1
    )
    echo %STEP% 4.1/7 gerando build do frontend
    call npm run build
    if errorlevel 1 (
        echo %ERR% Falha ao gerar o build do frontend.
        popd
        pause
        popd
        exit /b 1
    )
    popd
) else (
    echo %WARN% frontend\package.json nao encontrado. Frontend ignorado.
)

if not exist "backend" mkdir backend
if not exist "logs" mkdir logs
if not exist "bin" mkdir bin

echo %STEP% 5/7 preparando backend\.env e banco SQLite
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

echo %STEP% 6/7 aplicando migracoes automaticas
".venv\Scripts\python.exe" -m backend.migrate
if errorlevel 1 (
    echo %ERR% Falha ao aplicar migracoes automaticas.
    pause
    popd
    exit /b 1
)

echo %OK% Bootstrap local concluido.
echo %STEP% 7/7 registrando o servico automatico do Windows
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p = Start-Process -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','scripts\install-service.ps1') -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 (
    echo %ERR% Falha ao registrar o servico automatico do Windows.
    pause
    popd
    exit /b 1
)

echo.
echo %OK% Instalacao concluida.
pause
popd
