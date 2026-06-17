<p align="center">
  <img src="docs/assets/readme/llmbridge-banner.svg" alt="LLMBridge banner" width="100%" />
</p>

# LLMBridge

LLMBridge is a local gateway for AI apps. It gives you one endpoint, multiple providers, key rotation, queues, and usage tracking without forcing every client to speak every provider's native API.

`OpenAI-like proxy` `Anthropic-compatible /v1/messages` `Gemini via Claude Code` `Queue-based routing` `Key rotation` `Usage telemetry` `Local admin panel`

If you are new to the project, start here:

1. Install it on your machine.
2. Open the UI.
3. Point your app or Claude Code at `http://127.0.0.1:8009`.

## See It In Action

The admin UI gives you a live view of usage, queues, provider health, and latency.

<p align="center">
  <img src="docs/assets/readme/dashboard-overview-top-dark.png" alt="LLMBridge overview dashboard in dark mode" width="48%" />
  <img src="docs/assets/readme/dashboard-overview-stats-dark.png" alt="LLMBridge usage and metrics dashboard in dark mode" width="48%" />
</p>

## What It Does

LLMBridge sits between your apps and your model providers.

It helps you:

- keep one local endpoint for many clients;
- use provider keys more safely with rotation and fallback;
- route requests through queues when you want ordered fallback;
- track usage per app token and per project;
- inspect runtime, queues, keys, logs, and telemetry in the admin UI;
- talk to Claude Code through an Anthropic-compatible surface.

## Best For

- people who want a stable local AI gateway;
- teams with multiple provider keys;
- apps that need a single place for routing and telemetry;
- Claude Code users who want to point at a local bridge.

## Quick Start

### 1. Install

Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/lucashahnndev/LLMBridge/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/lucashahnndev/LLMBridge/main/install.ps1 | iex
```

These installers always start from a clean clone, so rerunning them pulls a fresh copy of the repository.

Run PowerShell as Administrator on Windows before starting the installer.

### 2. What the installer prepares

The bootstrap will:

- create a local Python virtual environment;
- install backend dependencies;
- install frontend dependencies and build the UI;
- create or repair `backend/.env`;
- create the local SQLite database;
- run the database migrations;
- register the service automatically on Linux or Windows.

If `SECRET_KEY` is missing, the installer generates it for you.
If `ADMIN_PASSWORD` is missing, the first launch sends you to the setup screen so you can create the initial admin password in the UI.

### 3. Build and first launch

On first launch:

1. Open the UI after the installer finishes.
2. If no admin password exists yet, the app redirects to the setup screen.
3. Create the initial admin password once.
4. After that, use the normal login screen.

If you already cloned the repository, run [`install.sh`](install.sh) or [`install.ps1`](install.ps1) from the repo root.

For the full project docs, see [docs overview](docs/overview.md).
