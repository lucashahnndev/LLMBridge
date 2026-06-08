# Deployment Spec

This spec defines how the system is installed and run.

## Contract

- the system must run as an automatic service rather than requiring a manual foreground process for normal use;
- the preferred installation flow is a one-shot bootstrap from a cloned repository, so a fresh machine can be prepared with a small number of commands;
- the service must be easy to run on Windows as well as on a local Unix-like environment;
- the deployment shape must support local operation without requiring external infrastructure;
- the first implementation stack is FastAPI for the backend, SvelteKit for the admin UI, Uvicorn for the ASGI server, SQLAlchemy 2 async for database access, SQLite for local persistence, Pydantic for validation and settings, and httpx for outbound provider calls;
- the preferred Windows service wrapper is NSSM, installed or downloaded by the local bootstrap flow if needed;
- the bootstrap flow is represented by `bootstrap.bat` and `scripts/install-service.ps1`;
- the bootstrap flow should create the local `.env`, `.venv`, SQLite file, and service plumbing with a small number of commands;
- the backend dependency list is expected to live in `backend/requirements.txt`;
- the deployment model should keep the operational surface small so installation, startup, and troubleshooting stay simple on a local machine.

## Scope notes

- this spec is about installation and runtime expectations, not business logic;
- service supervision and autostart are part of the contract;
- the implementation may use platform-specific tooling where needed, as long as the user-facing installation remains simple.

## Related

- [project.spec](project.spec.md)
