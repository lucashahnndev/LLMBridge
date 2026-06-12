# LLMBridge

Local LLM gateway, proxy rotator, and control plane for provider keys, app tokens, queues, and telemetry.

`OpenAI-like proxy` `Anthropic-compatible /v1/messages` `Gemini via Claude Code` `Queue-based routing` `Key rotation` `Usage telemetry` `Local admin panel`

LLMBridge sits between your apps and model providers so you can keep one stable local endpoint while the gateway handles routing, fallback, rotation, and usage tracking behind the scenes.

## Why It Exists

Most teams end up needing the same set of capabilities:

- multiple provider keys;
- fallback when a key fails;
- one stable API shape for many clients;
- usage tracking by project;
- a clear place to manage queues and rotation policy.

LLMBridge turns that into a single gateway.

## What You Get

- one local endpoint for multiple providers;
- OpenAI-like responses for consumer apps;
- Anthropic-like responses for Claude Code-style clients;
- provider key rotation on failure, quota, or rate-limit conditions;
- queues that can try models in order, rank them, or prefer low latency;
- app-token access control and per-project telemetry;
- a dashboard for runtime, usage, queues, keys, and overviews.

## Core Routes

Use these route styles:

- `provider/model` for a real upstream model route;
- `queue/name` for a logical queue that resolves to one or more provider/model candidates.

Examples:

- `google/gemini-3.1-flash`
- `openai/gpt-4o-mini`
- `openrouter/anthropic/claude-3.5-sonnet`
- `queue/gemini`
- `queue/production`

## How It Works

LLMBridge keeps the client protocol intact at the edge and uses internal adapters for routing and provider translation.

- public Anthropic requests stay Anthropic-shaped;
- public OpenAI-like requests stay OpenAI-shaped;
- Google and other upstream providers are handled by adapters;
- tool calls, ordering, and response intent are preserved;
- the backend converts requests through a richer canonical internal IR before reaching provider adapters;
- optional metadata cleanup can be enabled without changing the public contract.

## Quick Start

### 1. One-shot install

Linux:

```bash
mkdir -p "$HOME/apps" && git clone https://github.com/lucashahnndev/LLMKeyRotator.git "$HOME/apps/LLMBridge" && cd "$HOME/apps/LLMBridge" && bash bootstrap.sh
```

Windows PowerShell:

```powershell
mkdir "$HOME\apps" -Force
Set-Location "$HOME\apps"
git clone https://github.com/lucashahnndev/LLMKeyRotator.git LLMBridge
Set-Location .\LLMBridge
.\bootstrap.bat
```

Open PowerShell as Administrator before running the Windows bootstrap.

If you prefer to run the scripts directly:

- Windows: [`bootstrap.bat`](bootstrap.bat)
- Linux: [`bootstrap.sh`](bootstrap.sh)

The bootstrap keeps your working clone local and stages the runnable service workspace under `C:\ProgramData\LLMBridge`.
It uses the NSSM copy bundled with the project under `bin/` or the service workspace `bin/` folder, so it does not need to download NSSM from the internet.

If you are installing offline, place NSSM at:

- `bin/nssm/win64/nssm.exe` on 64-bit Windows;
- `bin/nssm/win32/nssm.exe` on 32-bit Windows.

If you keep a compressed package instead, the installer also accepts a local ZIP under `bin/` or `bin/nssm/`, or a ZIP path passed through `-NssmPath` or `-NssmRoot`.

### 2. What the bootstrap sets up

The bootstrap creates or repairs `backend/.env` with the minimum required values:

- `SECRET_KEY`
- `ADMIN_PASSWORD`
- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `LOG_FILE_ENABLED`
- `LOG_LEVEL`
- `LOG_FILE_PATH`
- `LOGGING_CONTROL_KEY`
- `TRACE_PROXY_ENABLED`
- `TRACE_PROXY_DIR`
- `TRACE_PROXY_REDACT`
- `HOST`
- `PORT`

If `SECRET_KEY` or `ADMIN_PASSWORD` is missing or blank, the bootstrap generates them automatically.
After that, it registers the full-stack service automatically on Linux or Windows.

On Windows, the service installer expects NSSM to be available locally in `bin/` and copies it into the service workspace under `C:\ProgramData\LLMBridge\bin\`.
If Windows keeps the old service entry around after removal, a reboot may be required before reinstalling.

### 3. Logging and traces

Logging is controlled through the same `.env` file:

- `LOG_FILE_ENABLED=true` turns on rotating file logs under `logs/`;
- `LOG_LEVEL` sets backend verbosity (`INFO`, `DEBUG`, `WARNING`, `ERROR`);
- `LOG_FILE_PATH` stores the rotating file log path;
- `LOGGING_CONTROL_KEY` unlocks extra request payload logging when sent as `X-Logging-Key`;
- `TRACE_PROXY_ENABLED=true` writes one redacted JSON trace per request under `traces/`;
- `TRACE_PROXY_DIR` changes the trace output directory;
- `TRACE_PROXY_REDACT=true` keeps auth-like values out of the trace file.

### 4. Start or manage the service

The bootstrap already registers the full-stack service automatically. If you need to manage it manually, use:

- Windows service: [`scripts/install-service.ps1`](scripts/install-service.ps1)
- Linux service: [`scripts/install-service.sh`](scripts/install-service.sh)

### 5. Open the UI

- frontend: `http://127.0.0.1:4173`
- backend: `http://127.0.0.1:8009`

## Claude Code

Claude Code can point at the gateway using Anthropic-compatible configuration.

Recommended pattern:

```json
{
  "claudeCode.preferredLocation": "panel",
  "claudeCode.environmentVariables": [
    {
      "name": "ANTHROPIC_BASE_URL",
      "value": "http://127.0.0.1:8009"
    },
    {
      "name": "ANTHROPIC_AUTH_TOKEN",
      "value": "app-token-example"
    },
    {
      "name": "ANTHROPIC_MODEL",
      "value": "queue/gemini"
    }
  ]
}
```

That means:

- Claude Code talks to your local gateway;
- the gateway authenticates with your app token;
- the model can be a queue alias or a direct provider route;
- the queue can rotate, fallback, and re-rank behind the scenes;
- the public Anthropic surface stays Anthropic-like.

### Terminal setup

For a one-off terminal session on Linux or macOS:

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8009"
export ANTHROPIC_AUTH_TOKEN="app-token-example"
export ANTHROPIC_MODEL="queue/gemini"
claude
```

To make it the default on Linux or macOS, add the exports to your shell profile:

```bash
cat <<'EOF' >> ~/.bashrc
export ANTHROPIC_BASE_URL="http://127.0.0.1:8009"
export ANTHROPIC_AUTH_TOKEN="app-token-example"
export ANTHROPIC_MODEL="queue/gemini"
EOF
source ~/.bashrc
```

For Windows CMD, persist the values with `setx`, then reopen the terminal:

```cmd
setx ANTHROPIC_BASE_URL "http://127.0.0.1:8009"
setx ANTHROPIC_AUTH_TOKEN "app-token-example"
setx ANTHROPIC_MODEL "queue/gemini"
```

## Reference Docs

If you want the technical contract, read:

- [proxy spec](agent/specs/proxy.spec.md)
- [data model spec](agent/specs/data-model.spec.md)
- [observability spec](agent/specs/observability.spec.md)
- [deployment spec](agent/specs/deployment.spec.md)
- [docs overview](docs/overview.md)

## Project Map

- [`frontend/`](frontend/) - admin UI and docs experience;
- [`backend/`](backend/) - API, routing, telemetry, and persistence;
- [`scripts/`](scripts/) - service and bootstrap helpers;
- [`agent/specs/`](agent/specs/) - normative contracts;
- [`docs/`](docs/) - human context, decisions, guides, and reports;
- [`bin/`](bin/) - offline install assets such as NSSM.
