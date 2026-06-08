# LLMKeyRotator

Local LLM gateway, proxy rotator, and control plane for provider keys, app tokens, queues, and telemetry.

`OpenAI-like proxy` `Anthropic-compatible /v1/messages` `Gemini via Claude Code` `Queue-based routing` `Key rotation` `Usage telemetry` `Local admin panel`

## What It Is

LLMKeyRotator sits between your apps and model providers.

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

LLMKeyRotator turns that into a single gateway.

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

## Tags

If you want the shortest mental model:

- `proxy rotator`
- `gemini for Claude Code`
- `gemini for OpenAI-like clients`
- `Anthropic-compatible gateway`
- `OpenAI-compatible gateway`
- `provider key failover`
- `queue orchestration`
- `model routing`
- `local LLM gateway`

## How It Works

1. You set the runtime host and port.
2. You create an app token for each consumer project.
3. You register provider keys.
4. You build queues from provider/model candidates.
5. Clients call the gateway with either:
   - a direct provider/model route, or
   - a queue alias.
6. If the upstream call fails, the proxy can rotate and retry.
7. Telemetry is stored in SQLite and surfaced in the dashboard.

## The Product Flow

This is the order I recommend for a fresh install:

1. Start the service.
2. Open the admin panel.
3. Confirm the runtime values.
4. Create an app token.
5. Add provider keys.
6. Build a queue.
7. Point your client at the gateway.
8. Watch usage in the overview and queue detail screens.

## Quick Start

### One-shot install

Linux:

```bash
git clone https://github.com/lucashahnndev/LLMKeyRotator.git && cd LLMKeyRotator && bash bootstrap.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/lucashahnndev/LLMKeyRotator.git; Set-Location LLMKeyRotator; .\bootstrap.bat
```

The bootstrap will create or repair `backend/.env` with the minimum required values:

- `SECRET_KEY`
- `ADMIN_PASSWORD`
- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `HOST`
- `PORT`

If `SECRET_KEY` or `ADMIN_PASSWORD` is missing or blank, the bootstrap generates them automatically.
After that, it registers the full-stack service automatically on Linux or Windows.

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

- Claude Code talks to your local gateway
- the gateway authenticates with your app token
- the model comes from a queue alias
- the queue can rotate, fallback, and re-rank behind the scenes

If you want a direct route instead of a queue, use:

- `google/gemini-3.1-flash`
- `openai/gpt-4o-mini`

## OpenAI-Like Clients

Use `POST /v1/chat/completions` when the client expects OpenAI-style traffic.

Example:

```json
{
  "model": "google/gemini-3.1-flash",
  "messages": [
    { "role": "user", "content": "Resuma este texto." }
  ]
}
```

The gateway normalizes the response so the consumer still sees an OpenAI-like contract.

## Anthropic-Compatible Clients

Use `POST /v1/messages` when the client expects Anthropic-style traffic.

Example:

```json
{
  "model": "queue/gemini",
  "messages": [
    { "role": "user", "content": "olá" }
  ]
}
```

This is the preferred path for Claude Code-style integrations.

## Queue Strategies

Supported strategies:

- `ordered`
- `smart`
- `latency`

Behavior:

- `ordered`: follows the list order exactly
- `smart`: re-ranks candidates using observed failures, success history, and latency
- `latency`: prefers faster candidates

## Dashboard Areas

The admin UI includes:

- overview
- provider keys
- app tokens
- model queues
- usage
- runtime
- dedicated overview pages for app tokens, provider keys, and queues
- docs

## SemVer and Migrations

The project uses semantic versioning for:

- app version
- schema version
- automatic startup migrations

Current versions:

- app: `0.2.0`
- schema: `0.2.0`

Migration entrypoint:

```bash
.venv/bin/python -m backend.migrate
```

## Testing

Backend tests:

```bash
.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
```

Frontend build:

```bash
cd frontend && npm run build
```

## Runtime Commands

- backend: `.venv/bin/python -m backend.run`
- schema migrations: `.venv/bin/python -m backend.migrate`
- frontend preview: `cd frontend && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort`
- Windows restart: `Restart-Service -Name "LLMKeyRotator"`
- Linux restart: `systemctl restart llmkeyrotator`

## Stack

- backend: `FastAPI`
- server: `Uvicorn`
- UI: `SvelteKit`
- persistence: `SQLite`
- ORM: `SQLAlchemy 2 async`
- validation/config: `Pydantic`
- HTTP client: `httpx`

## Docs

The service includes a built-in docs page:

- `http://127.0.0.1:4173/docs`

## Entry Points

- [built-in docs](frontend/src/routes/docs/+page.svelte)
- [frontend app](frontend/package.json)

## Notes

- Provider secrets are stored encrypted at rest.
- App tokens are shown only under controlled administrative actions.
- The dashboard keeps usage and overview pages separate from routing logic.
- The proxy is intended to normalize client-facing output, not force every upstream provider to look identical internally.
