#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/lucashahnndev/LLMKeyRotator.git"
INSTALL_DIR="${LLMBRIDGE_INSTALL_DIR:-$HOME/apps/LLMBridge}"

if ! command -v git >/dev/null 2>&1; then
  echo "[x] git nao foi encontrado no PATH."
  exit 1
fi

mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ -d "$INSTALL_DIR" ]]; then
  rm -rf "$INSTALL_DIR"
fi

git clone "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"
bash bootstrap.sh
