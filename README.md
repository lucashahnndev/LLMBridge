# LLMKeyRotator

Local unified LLM gateway and key rotator under the agent-workspace convention.

## Current focus

- proxy requests through provider-specific drivers;
- keep the public proxy contract OpenAI-compatible first while also exposing an Anthropic-compatible `/v1/messages` adapter on the same routing core;
- expose an Anthropic-compatible `/v1/messages` adapter for Claude Code-style clients while reusing the same provider/model and queue routing core;
- document the provider/model alias convention in the Runtime panel;
- manage provider keys with cooldown, invalidation, suspension, and reactivation;
- protect secrets in a local vault;
- expose admin access, app tokens, metrics, alerts, and runtime controls;
- remember dashboard section and filter state across reloads;
- support bulk selection and bulk actions on provider keys and app tokens;
- reveal provider secrets through a deliberate admin-confirmed peek flow;
- show context-rich detail panels for selected provider keys and app tokens;
- auto-refresh the dashboard and show backend health in the panel;
- surface action feedback through in-app notifications;
- keep a recent activity timeline in the dashboard overview;
- polish the hero and summary cards with a stronger product feel;
- align the cards, tables, and detail surfaces into a more cohesive visual system;
- refine typography, focus states, and microinteractions across the dashboard;
- split the UI into a dedicated login screen and a separate admin panel shell;
- add a top bar with operator profile, logout, and theme switching;
- keep the visual language technical, muted, and minimal, with gray surfaces and restrained amber accents;
- keep the layout flat, with thin borders, tight radii, and minimal visual noise;
- adjust the backend host/port from the admin panel and restart when needed;
- run as a single service that starts backend and frontend together, with a simple one-shot install path on Windows and Linux.
- apply schema migrations automatically during bootstrap and service start, tracked with semver.

## Installation

- Windows one-shot bootstrap: [`bootstrap.bat`](bootstrap.bat)
- Linux one-shot bootstrap: [`bootstrap.sh`](bootstrap.sh)
- Windows service installer: [`scripts/install-service.ps1`](scripts/install-service.ps1)
- Linux service installer: [`scripts/install-service.sh`](scripts/install-service.sh)
- combined service launcher: [`scripts/run-service.ps1`](scripts/run-service.ps1), [`scripts/run-service.sh`](scripts/run-service.sh)
- Frontend app: [`frontend/package.json`](frontend/package.json)
- Frontend source: [`frontend/src/routes/login/+page.svelte`](frontend/src/routes/login/+page.svelte)
- Frontend shell: [`frontend/src/routes/app/+page.svelte`](frontend/src/routes/app/+page.svelte)

## Testing

- Backend unit tests: `.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'`
- Backend syntax check: `python3 -m py_compile $(find backend/app -name '*.py' | sort)`

## Runtime

- model routing: use `provider/model-name` for real provider routes; `queue/{queue-name}` is the higher-level orchestration alias when defined
- queue routing: define ordered provider/model candidates inside the admin queue manager, then route with `queue/{queue-name}`
- Anthropic-compatible client support is available at `POST /v1/messages`; it shares the same internal `provider/model-name` and `queue/{queue-name}` routing core, and the usage log now records `protocol_in`, `protocol_out`, `route_kind`, and `tool_calling`
- Claude Code example:
  - `ANTHROPIC_BASE_URL=http://127.0.0.1:8009`
  - `ANTHROPIC_AUTH_TOKEN=<valid app token>`
  - use `queue/google` for a queue alias or `google/gemini-3.1-flash` for a direct provider route
- backend entrypoint: `.venv/bin/python -m backend.run`
- schema migration entrypoint: `.venv/bin/python -m backend.migrate`
- frontend preview entrypoint: `cd frontend && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort`
- admin runtime settings: use the dashboard panel to edit host and port, then restart the full-stack service
- Windows restart: `Restart-Service -Name "LLMKeyRotator"`
- Linux restart: `systemctl restart llmkeyrotator`

## Stack

- backend: `FastAPI`
- server: `Uvicorn`
- UI: `SvelteKit`
- persistence: `SQLite`
- ORM/data access: `SQLAlchemy 2 async`
- validation/config: `Pydantic`
- outbound HTTP: `httpx`

## Entry points

- [project overview](project.overview.md)
- [agent start here](agent-start-here.md)
- [project spec](agent/specs/project.spec.md)
- [frontend app](frontend/package.json)
