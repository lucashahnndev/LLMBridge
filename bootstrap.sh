#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR" && pwd)"
FRONTEND_BUILD_STAMP="$REPO_ROOT/frontend/.llmbridge-build.sha256"

cd "$REPO_ROOT"

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'
else
  C_RESET=''
  C_DIM=''
  C_CYAN=''
  C_GREEN=''
  C_YELLOW=''
  C_RED=''
fi

banner() {
  printf '%s\n' "${C_CYAN}==============================================${C_RESET}"
  printf '%s\n' "${C_CYAN}  LLMBridge${C_RESET} ${C_DIM}one-shot installer${C_RESET}"
  printf '%s\n' "${C_CYAN}==============================================${C_RESET}"
}

step() { printf '%s\n' "${C_YELLOW}[>]${C_RESET} $*"; }
ok() { printf '%s\n' "${C_GREEN}[+]${C_RESET} $*"; }
warn() { printf '%s\n' "${C_YELLOW}[!]${C_RESET} $*"; }
fail() { printf '%s\n' "${C_RED}[x]${C_RESET} $*"; }

banner
echo

command -v python3 >/dev/null 2>&1 || {
  fail "python3 nao foi encontrado no PATH."
  warn "Instale Python 3.10+ e tente novamente."
  exit 1
}

command -v node >/dev/null 2>&1 || {
  fail "Node.js nao foi encontrado no PATH."
  warn "Instale Node.js 20+ para preparar o frontend SvelteKit."
  exit 1
}

if [[ ! -d ".venv" ]]; then
  step "1/7 criando ambiente virtual .venv"
  python3 -m venv .venv
else
  ok "Ambiente virtual .venv ja existe."
fi

step "2/7 atualizando pip"
".venv/bin/python" -m pip install --upgrade pip

if [[ -f "backend/requirements.txt" ]]; then
  step "3/7 instalando dependencias do backend"
  ".venv/bin/python" -m pip install -r backend/requirements.txt
else
  warn "backend/requirements.txt nao encontrado. Backend ignorado."
fi

if [[ -f "frontend/package.json" ]]; then
  frontend_fingerprint="$(python3 - <<'PY'
from pathlib import Path
import hashlib

root = Path("frontend")
if not root.exists():
    print("")
    raise SystemExit(0)

digest = hashlib.sha256()
for path in sorted(
    p for p in root.rglob("*")
    if p.is_file() and ".svelte-kit" not in p.parts and "node_modules" not in p.parts
):
    digest.update(str(path.relative_to(root)).encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
)"
  frontend_build_fresh=false
  if [[ -n "$frontend_fingerprint" && -f "$FRONTEND_BUILD_STAMP" ]]; then
    stored_fingerprint="$(head -n 1 "$FRONTEND_BUILD_STAMP" | tr -d '\r\n')"
    if [[ "$stored_fingerprint" == "$frontend_fingerprint" && -d "frontend/.svelte-kit" && -d "frontend/node_modules" ]]; then
      frontend_build_fresh=true
    fi
  fi

  if [[ "$frontend_build_fresh" == true ]]; then
    ok "Frontend ja esta atualizado; npm install e build reutilizados."
  else
    step "4/7 instalando dependencias do frontend"
    (cd frontend && npm install)
    step "4.1/7 gerando build do frontend"
    (cd frontend && npm run build)
    if [[ -n "$frontend_fingerprint" ]]; then
      printf '%s\n' "$frontend_fingerprint" > "$FRONTEND_BUILD_STAMP"
    fi
  fi
else
  warn "frontend/package.json nao encontrado. Frontend ignorado."
fi

mkdir -p backend logs bin

step "5/7 preparando backend/.env e banco SQLite"
python3 scripts/bootstrap_env.py

".venv/bin/python" - <<'PY'
import pathlib, sqlite3
db = pathlib.Path("backend/database.db")
db.parent.mkdir(parents=True, exist_ok=True)
sqlite3.connect(db).close()
PY

step "6/7 aplicando migracoes automaticas"
".venv/bin/python" -m backend.migrate

ok "Bootstrap local concluido."
step "7/7 registrando o servico automatico do Linux"
bash scripts/install-service.sh
