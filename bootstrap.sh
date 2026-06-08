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
python3 scripts/bootstrap_env.py

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
echo "[7/7] Registrando o servico automatico do Linux..."
bash scripts/install-service.sh
