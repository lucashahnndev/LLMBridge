# LLMBridge

Local LLM gateway, proxy rotator, and control plane for provider keys, app tokens, queues, and telemetry.

`OpenAI-like proxy` `Anthropic-compatible /v1/messages` `Gemini via Claude Code` `Queue-based routing` `Key rotation` `Usage telemetry` `Local admin panel`

## What It Is

LLMBridge sits between your apps and model providers.

It gives you:

- one local endpoint for multiple providers;
- OpenAI-like output for consumer apps;
- Anthropic-like output for Claude Code-style clients;
- provider key rotation on failure, quota, or rate-limit conditions;
- queues that can try models in order, smart-rank them, or prefer low latency;
- app-token access control and per-project telemetry;
- a dashboard for runtime, usage, queues, keys, and overviews.

Think of it as a local control plane for model traffic.

## Why It Exists

Most teams end up needing the same things:

- multiple provider keys
- fallback when a key fails
- one stable API shape for many clients
- usage tracking by project
- a clear place to manage queues and rotation policy

LLMBridge turns that into a single gateway.

## Core Convention

Use these route styles:

- `provider/model` for a real upstream model route
- `queue/name` for a logical queue that resolves to one or more provider/model candidates

Examples:

- `google/gemini-3.1-flash`
- `openai/gpt-4o-mini`
- `openrouter/anthropic/claude-3.5-sonnet`
- `queue/gemini`
- `queue/production`

## Protocol Model

LLMBridge keeps the client protocol intact at the edge and uses internal adapters for routing and provider translation.

- public Anthropic requests stay Anthropic-shaped;
- public OpenAI-like requests stay OpenAI-shaped;
- Google and other upstream providers are handled by adapters;
- tool calls, ordering, and response intent are preserved;
- the backend converts requests through a richer canonical internal IR before reaching provider adapters;
- optional metadata cleanup can be enabled without changing the public contract.

## Why It Exists

Most teams need the same things:

- multiple provider keys;
- fallback when a key fails;
- one stable API shape for many clients;
- usage tracking by project;
- a clear place to manage queues and rotation policy.

LLMBridge turns that into a single gateway.

## Quick Start

### One-shot install

Linux:

```bash
mkdir -p "$HOME/apps" && git clone https://github.com/lucashahnndev/LLMKeyRotator.git "$HOME/apps/LLMBridge" && cd "$HOME/apps/LLMBridge" && bash bootstrap.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/lucashahnndev/LLMKeyRotator.git; Set-Location LLMBridge; .\bootstrap.bat
```

The Windows bootstrap keeps your working clone local and stages the runnable service workspace under `C:\ProgramData\LLMBridge`.

The bootstrap will create or repair `backend/.env` with the minimum required values:

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
On Windows, the service installer downloads NSSM automatically into the service workspace under `C:\ProgramData\LLMBridge\bin\`.

Logging is controlled through the same `.env` file:

- `LOG_FILE_ENABLED=true` turns on rotating file logs under `logs/`;
- `LOG_LEVEL` sets the backend verbosity (`INFO`, `DEBUG`, `WARNING`, `ERROR`);
- `LOG_FILE_PATH` stores the rotating file log path;
- `LOGGING_CONTROL_KEY` unlocks extra request payload logging when sent as `X-Logging-Key`.
- `TRACE_PROXY_ENABLED=true` writes one redacted JSON trace per request under `traces/`;
- `TRACE_PROXY_DIR` changes the trace output directory;
- `TRACE_PROXY_REDACT=true` keeps auth-like values out of the trace file.

### 1. Bootstrap

- Windows: [`bootstrap.bat`](bootstrap.bat)
- Linux: [`bootstrap.sh`](bootstrap.sh)

### 2. Start the service

The bootstrap already registers the full-stack service automatically. If you need to manage it manually, use:

- Windows service: [`scripts/install-service.ps1`](scripts/install-service.ps1)
- Linux service: [`scripts/install-service.sh`](scripts/install-service.sh)

### 3. Open the UI

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

If you want the technical contract, read:

- [proxy spec](agent/specs/proxy.spec.md)
- [data model spec](agent/specs/data-model.spec.md)
- [observability spec](agent/specs/observability.spec.md)
- [deployment spec](agent/specs/deployment.spec.md)
- [docs overview](docs/overview.md)
