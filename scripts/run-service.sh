#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_PYTHON_ROOT="$REPO_ROOT/.venv/bin/python"
BACKEND_PYTHON_LEGACY="$REPO_ROOT/backend/.venv/bin/python"
if [[ -x "$BACKEND_PYTHON_ROOT" ]]; then
  BACKEND_PYTHON="$BACKEND_PYTHON_ROOT"
elif [[ -x "$BACKEND_PYTHON_LEGACY" ]]; then
  BACKEND_PYTHON="$BACKEND_PYTHON_LEGACY"
else
  BACKEND_PYTHON="$BACKEND_PYTHON_ROOT"
fi
FRONTEND_DIR="$REPO_ROOT/frontend"
FRONTEND_PORT="${FRONTEND_PORT:-4173}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"

export FRONTEND_HOST
export FRONTEND_PORT

if [[ ! -x "$BACKEND_PYTHON" ]]; then
  echo "[ERRO] Ambiente virtual do backend nao encontrado em $BACKEND_PYTHON_ROOT ou $BACKEND_PYTHON_LEGACY"
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "[ERRO] Diretorio frontend nao encontrado em $FRONTEND_DIR"
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/.svelte-kit" ]]; then
  echo "[ERRO] Frontend nao foi buildado. Execute 'npm run build' em frontend/ antes de iniciar o servico."
  exit 1
fi

cleanup() {
  local exit_code=$?
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait "${BACKEND_PID:-}" 2>/dev/null || true
  wait "${FRONTEND_PID:-}" 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

cd "$REPO_ROOT"

echo "[*] Aplicando migracoes automaticas..."
"$BACKEND_PYTHON" -m backend.migrate

echo "[*] Iniciando backend..."
"$BACKEND_PYTHON" -m backend.run &
BACKEND_PID=$!

echo "[*] Iniciando frontend preview em ${FRONTEND_HOST}:${FRONTEND_PORT}..."
(cd "$FRONTEND_DIR" && npm run preview -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort) &
FRONTEND_PID=$!

wait -n "$BACKEND_PID" "$FRONTEND_PID"
