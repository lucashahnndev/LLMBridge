#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR" && pwd)"

cd "$REPO_ROOT"

echo "======================================================="
echo "    LLMKeyRotator - Instalador One-Shot (Linux)"
echo "======================================================="
echo

command -v python3 >/dev/null 2>&1 || {
  echo "[ERRO] python3 nao foi encontrado no PATH."
  echo "Instale Python 3.10+ e tente novamente."
  exit 1
}

command -v node >/dev/null 2>&1 || {
  echo "[ERRO] Node.js nao foi encontrado no PATH."
  echo "Instale Node.js 20+ para preparar o frontend SvelteKit."
  exit 1
}

if [[ ! -d ".venv" ]]; then
  echo "[1/6] Criando ambiente virtual .venv..."
  python3 -m venv .venv
else
  echo "[*] Ambiente virtual .venv ja existe."
fi

echo "[2/6] Atualizando pip..."
".venv/bin/python" -m pip install --upgrade pip

if [[ -f "backend/requirements.txt" ]]; then
  echo "[3/6] Instalando dependencias do backend..."
  ".venv/bin/python" -m pip install -r backend/requirements.txt
else
  echo "[!] backend/requirements.txt nao encontrado. Instalacao do backend ignorada."
fi

if [[ -f "frontend/package.json" ]]; then
  echo "[4/6] Instalando dependencias do frontend..."
  (cd frontend && npm install)
  echo "[4.1/6] Gerando build do frontend..."
  (cd frontend && npm run build)
else
  echo "[!] frontend/package.json nao encontrado. Instalacao do frontend ignorada."
fi

mkdir -p backend logs bin

echo "[5/6] Preparando arquivo backend/.env e banco SQLite..."
if [[ ! -f "backend/.env" ]]; then
  SECRET_KEY=$(".venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(32))")
  ADMIN_PASSWORD=$(".venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(24))")
  cat > backend/.env <<EOF
SECRET_KEY=${SECRET_KEY}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
DATABASE_URL=sqlite+aiosqlite:///./backend/database.db
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
HOST=127.0.0.1
PORT=8009
EOF
  echo "[+] backend/.env criado."
  echo "[+] ADMIN_PASSWORD inicial: ${ADMIN_PASSWORD}"
else
  echo "[*] backend/.env ja existe. Mantendo configuracao atual."
fi

".venv/bin/python" - <<'PY'
import pathlib, sqlite3
db = pathlib.Path("backend/database.db")
db.parent.mkdir(parents=True, exist_ok=True)
sqlite3.connect(db).close()
PY

echo "[5.1/6] Aplicando migracoes automaticas do schema..."
".venv/bin/python" -m backend.migrate

echo "[6/6] Bootstrap local concluido."
echo
read -r -p "Deseja registrar o LLMKeyRotator como servico automatico do Linux? (S/N) " INSTALL_SERVICE

if [[ "${INSTALL_SERVICE^^}" == "S" ]]; then
  bash scripts/install-service.sh
else
  echo
  echo "[*] Instalacao concluida sem servico automatico."
  echo "Para iniciar manualmente:"
  echo "    .venv/bin/python -m backend.run"
  echo
  echo "Para iniciar o frontend em desenvolvimento:"
  echo "    cd frontend && npm run dev"
fi
