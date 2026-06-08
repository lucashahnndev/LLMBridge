@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LLMKeyRotator - One-Shot Installer

set "ROOT=%~dp0"
pushd "%ROOT%" >nul

echo =======================================================
echo     LLMKeyRotator - Instalador One-Shot (Windows)
echo =======================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao foi encontrado no PATH.
    echo Instale Python 3.10+ e marque "Add Python to PATH".
    pause
    popd
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Node.js nao foi encontrado no PATH.
    echo Instale Node.js 20+ para preparar o frontend SvelteKit.
    pause
    popd
    exit /b 1
)

if not exist ".venv" (
    echo [1/6] Criando ambiente virtual .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar o ambiente virtual.
        pause
        popd
        exit /b 1
    )
) else (
    echo [*] Ambiente virtual .venv ja existe.
)

echo [2/6] Atualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

if exist "backend\requirements.txt" (
    echo [3/6] Instalando dependencias do backend...
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar as dependencias.
        pause
        popd
        exit /b 1
    )
) else (
    echo [!] backend\requirements.txt nao encontrado. Instalacao de dependencias ignorada.
)

if exist "frontend\package.json" (
    echo [4/6] Instalando dependencias do frontend...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar as dependencias do frontend.
        popd
        pause
        popd
        exit /b 1
    )
    echo [4.1/6] Gerando build do frontend...
    call npm run build
    if errorlevel 1 (
        echo [ERRO] Falha ao gerar o build do frontend.
        popd
        pause
        popd
        exit /b 1
    )
    popd
) else (
    echo [!] frontend\package.json nao encontrado. Instalacao do frontend ignorada.
)

if not exist "backend" mkdir backend
if not exist "logs" mkdir logs
if not exist "bin" mkdir bin

echo [5/6] Preparando arquivo backend\.env e banco SQLite...
if not exist "backend\.env" (
    for /f "delims=" %%i in ('".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))"') do set "SECRET_KEY=%%i"
    for /f "delims=" %%i in ('".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(24))"') do set "ADMIN_PASSWORD=%%i"

    > "backend\.env" (
        echo SECRET_KEY=!SECRET_KEY!
        echo ADMIN_PASSWORD=!ADMIN_PASSWORD!
        echo DATABASE_URL=sqlite+aiosqlite:///./backend/database.db
        echo TELEGRAM_BOT_TOKEN=
        echo TELEGRAM_CHAT_ID=
        echo HOST=127.0.0.1
        echo PORT=8009
    )

    echo [+] backend\.env criado.
    echo [+] ADMIN_PASSWORD inicial: !ADMIN_PASSWORD!
) else (
    echo [*] backend\.env ja existe. Mantendo configuracao atual.
)

".venv\Scripts\python.exe" -c "import sqlite3, pathlib; db = pathlib.Path('backend/database.db'); db.parent.mkdir(parents=True, exist_ok=True); sqlite3.connect(db).close()"
if errorlevel 1 (
    echo [ERRO] Falha ao inicializar o banco SQLite.
    pause
    popd
    exit /b 1
)

echo [5.1/6] Aplicando migracoes automaticas do schema...
".venv\Scripts\python.exe" -m backend.migrate
if errorlevel 1 (
    echo [ERRO] Falha ao aplicar migracoes automaticas.
    pause
    popd
    exit /b 1
)

echo [6/6] Bootstrap local concluido.
echo.
echo Deseja registrar o LLMKeyRotator como servico automatico do Windows? (S/N)
set /p INSTALL_SERVICE=

if /i "!INSTALL_SERVICE!"=="S" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Start-Process powershell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"scripts\install-service.ps1\"' -Verb RunAs"
) else (
    echo.
    echo [*] Instalacao concluida sem servico automatico.
    echo Para iniciar manualmente:
    echo     .venv\Scripts\python.exe -m backend.run
    echo.
    echo Para iniciar o frontend em desenvolvimento:
    echo     cd frontend ^&^& npm run dev
)

echo.
pause
popd
