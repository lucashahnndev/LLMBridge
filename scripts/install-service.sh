#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="llmkeyrotator"
SERVICE_FILE_ROOT="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_FILE_USER="${HOME}/.config/systemd/user/${SERVICE_NAME}.service"
RUN_SCRIPT="${REPO_ROOT}/scripts/run-service.sh"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"

if [[ ! -x "$RUN_SCRIPT" ]]; then
  chmod +x "$RUN_SCRIPT"
fi

stage() { echo "[>] $*"; }
ok() { echo "[+] $*"; }
warn() { echo "[!] $*"; }

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  stage "Instalando servico systemd (root)"
  cat > "$SERVICE_FILE_ROOT" <<EOF
[Unit]
Description=LLMKeyRotator full-stack service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${REPO_ROOT}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${REPO_ROOT}/backend/.env
ExecStart=${RUN_SCRIPT}
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"

  ok "Servico '${SERVICE_NAME}' instalado e reiniciado."
  echo "    Logs: journalctl -u ${SERVICE_NAME} -f"
else
  stage "Instalando servico systemd (usuario)"
  mkdir -p "${HOME}/.config/systemd/user"
  cat > "$SERVICE_FILE_USER" <<EOF
[Unit]
Description=LLMKeyRotator full-stack service
After=default.target

[Service]
Type=simple
WorkingDirectory=${REPO_ROOT}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-${REPO_ROOT}/backend/.env
ExecStart=${RUN_SCRIPT}
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable "$SERVICE_NAME"
  systemctl --user restart "$SERVICE_NAME"

  ok "Servico de usuario '${SERVICE_NAME}' instalado e reiniciado."
  echo "    Logs: journalctl --user -u ${SERVICE_NAME} -f"
fi
