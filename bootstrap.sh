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
  cat <<EOF
${C_YELLOW}==============================================================${C_RESET}
${C_YELLOW}█     █     █   █ ████  ████  ███ ████   ███  █████${C_RESET}
${C_YELLOW}█     █     ██ ██ █   █ █   █  █  █   █ █     █${C_RESET}
${C_YELLOW}█     █     █ █ █ ████  ████   █  █   █ █  ██ ████${C_RESET}
${C_YELLOW}█     █     █   █ █   █ █  █   █  █   █ █   █ █${C_RESET}
${C_YELLOW}█████ █████ █   █ ████  █   █ ███ ████   ███  █████${C_RESET}
${C_DIM}                        LLMBridge${C_RESET}
${C_DIM}                  local one-shot installer${C_RESET}
${C_YELLOW}==============================================================${C_RESET}
EOF
}

step() { printf '%s\n' "${C_YELLOW}[>]${C_RESET} $*"; }
ok() { printf '%s\n' "${C_GREEN}[+]${C_RESET} $*"; }
warn() { printf '%s\n' "${C_YELLOW}[!]${C_RESET} $*"; }
fail() { printf '%s\n' "${C_RED}[x]${C_RESET} $*"; }

run_quiet() {
  local label="$1"
  local success="$2"
  shift 2

  local logfile
  logfile="$(mktemp)"

  step "$label"
  if "$@" >"$logfile" 2>&1; then
    ok "$success"
    rm -f "$logfile"
    return 0
  fi

  fail "$label"
  warn "Mostrando os ultimos registros do passo que falhou:"
  tail -n 80 "$logfile"
  rm -f "$logfile"
  exit 1
}

run_attempt() {
  local label="$1"
  local success="$2"
  shift 2

  local logfile
  logfile="$(mktemp)"

  step "$label"
  if "$@" >"$logfile" 2>&1; then
    ok "$success"
    rm -f "$logfile"
    return 0
  fi

  warn "$label falhou; tentando proxima estrategia."
  tail -n 40 "$logfile"
  rm -f "$logfile"
  return 1
}

as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  return 1
}

node_major_version() {
  if ! command -v node >/dev/null 2>&1; then
    return 1
  fi
  node -p "process.versions.node.split('.')[0]"
}

ensure_nodejs() {
  local current_major=''
  if current_major="$(node_major_version 2>/dev/null)"; then
    if [[ "$current_major" =~ ^[0-9]+$ ]] && (( current_major >= 20 )); then
      return 0
    fi
    warn "Node.js $current_major detectado, mas o bootstrap precisa de Node.js 20+."
  else
    warn "Node.js nao foi encontrado no PATH."
  fi

  local installed=false
  if command -v apt-get >/dev/null 2>&1; then
    run_attempt "0/7 atualizando indice APT" "indice APT atualizado" as_root apt-get update && \
    run_attempt "0/7 instalando Node.js via apt-get" "Node.js instalado via apt-get" as_root apt-get install -y nodejs npm && \
    installed=true
  elif command -v dnf >/dev/null 2>&1; then
    run_attempt "0/7 instalando Node.js via dnf" "Node.js instalado via dnf" as_root dnf install -y nodejs npm && \
    installed=true
  elif command -v yum >/dev/null 2>&1; then
    run_attempt "0/7 instalando Node.js via yum" "Node.js instalado via yum" as_root yum install -y nodejs npm && \
    installed=true
  elif command -v pacman >/dev/null 2>&1; then
    run_attempt "0/7 sincronizando repositorios pacman" "repositorios pacman sincronizados" as_root pacman -Sy --noconfirm && \
    run_attempt "0/7 instalando Node.js via pacman" "Node.js instalado via pacman" as_root pacman -S --noconfirm nodejs npm && \
    installed=true
  elif command -v zypper >/dev/null 2>&1; then
    run_attempt "0/7 instalando Node.js 20 via zypper" "Node.js instalado via zypper" as_root zypper --non-interactive install nodejs20 npm20 && \
    installed=true
    if [[ "$installed" != true ]]; then
      run_attempt "0/7 instalando Node.js via zypper" "Node.js instalado via zypper" as_root zypper --non-interactive install nodejs npm && \
      installed=true
    fi
  elif command -v apk >/dev/null 2>&1; then
    run_attempt "0/7 instalando Node.js via apk" "Node.js instalado via apk" as_root apk add --no-cache nodejs npm && \
    installed=true
  elif command -v brew >/dev/null 2>&1; then
    run_attempt "0/7 instalando Node.js via Homebrew" "Node.js instalado via Homebrew" brew install node && \
    installed=true
  fi

  hash -r
  if current_major="$(node_major_version 2>/dev/null)"; then
    if [[ "$current_major" =~ ^[0-9]+$ ]] && (( current_major >= 20 )); then
      ok "Node.js $current_major pronto para uso."
      return 0
    fi
    fail "Node.js foi instalado, mas a versao detectada e $current_major e o bootstrap precisa de 20+."
    warn "Atualize o repositório da distribuicao ou instale uma versao mais nova do Node.js e rode o bootstrap novamente."
    exit 1
  fi

  if [[ "$installed" == true ]]; then
    fail "Node.js foi instalado, mas nao entrou no PATH da sessao atual."
    warn "Abra um novo terminal ou carregue o ambiente novamente e execute o bootstrap outra vez."
    exit 1
  fi

  fail "Nao foi possivel instalar Node.js automaticamente nesta distribuicao."
  warn "Use uma distribuicao com apt, dnf, yum, pacman, zypper, apk ou brew, ou instale Node.js 20+ manualmente."
  exit 1
}

banner
echo

command -v python3 >/dev/null 2>&1 || {
  fail "python3 nao foi encontrado no PATH."
  warn "Instale Python 3.10+ e tente novamente."
  exit 1
}

ensure_nodejs

if [[ ! -d ".venv" ]]; then
  step "1/7 criando ambiente virtual .venv"
  python3 -m venv .venv
else
  ok "Ambiente virtual .venv ja existe."
fi

run_quiet "2/7 atualizando pip" "pip atualizado" ".venv/bin/python" -m pip install --upgrade pip --quiet --disable-pip-version-check --no-input

if [[ -f "backend/requirements.txt" ]]; then
  run_quiet "3/7 instalando dependencias do backend" "dependencias do backend instaladas" ".venv/bin/python" -m pip install -r backend/requirements.txt --quiet --disable-pip-version-check --no-input
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
    run_quiet "4/7 instalando dependencias do frontend" "dependencias do frontend instaladas" bash -lc 'cd frontend && npm ci --silent --no-audit --no-fund'
    run_quiet "5/7 gerando build do frontend" "build do frontend concluido" bash -lc 'cd frontend && npm run build --silent'
    if [[ -n "$frontend_fingerprint" ]]; then
      printf '%s\n' "$frontend_fingerprint" > "$FRONTEND_BUILD_STAMP"
    fi
  fi
else
  warn "frontend/package.json nao encontrado. Frontend ignorado."
fi

mkdir -p backend logs bin

step "6/7 preparando backend/.env, banco SQLite e migracoes"
python3 scripts/bootstrap_env.py

".venv/bin/python" - <<'PY'
import pathlib, sqlite3
db = pathlib.Path("backend/database.db")
db.parent.mkdir(parents=True, exist_ok=True)
sqlite3.connect(db).close()
PY

".venv/bin/python" -m backend.migrate

step "7/7 registrando o servico automatico do Linux"
bash scripts/install-service.sh
ok "Bootstrap local concluido."
