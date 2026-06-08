# Deployment Stat

Last update date: 2026-06-07

## Current state

- the system is now defined as a service-oriented local application;
- one-shot installation is preferred for the first setup experience;
- Windows friendliness is a hard requirement for the deployment shape;
- the first implementation stack has been selected and recorded;
- the Windows service wrapper preference is NSSM;
- the bootstrap flow is expected to create the local environment, secret material, and service plumbing;
- the bootstrap and Windows service installer scripts now exist in the repository;
- the backend now has a minimal FastAPI entrypoint and health route scaffold;
- the bootstrap now installs the frontend dependencies as part of the one-shot flow.
- the backend now starts through a runtime wrapper that reads `backend/.env` for host and port;
- the admin panel can now update the backend host/port and persist the change to `backend/.env`;
- changing the backend port requires a backend restart before the new value applies.

## Pending items

- decide how service installation will be exposed on the Unix-like path, if that path is added later;
- decide whether the frontend will be served by the same service process or via a separate build artifact;
- wire the backend dependencies into a real virtual environment and run the first boot locally.
- decide whether the service installer should also expose an explicit restart helper for runtime changes.

## Evidence / validation

- service-oriented runtime requirement recorded;
- one-shot install requirement recorded;
- Windows compatibility requirement recorded;
- FastAPI/SvelteKit/SQLite/Uvicorn stack recorded for the first implementation;
- NSSM recorded as the preferred Windows service wrapper;
- bootstrap.bat and scripts/install-service.ps1 were added as deploy artifacts;
- backend/requirements.txt was added for the initial dependency list;
- backend/app/main.py and backend/app/routes/health.py were added as the first runtime scaffold;
- frontend/package-lock.json was generated and the frontend build passed locally.
- backend/run.py was added as the runtime wrapper entrypoint;
- backend/app/routes/admin.py and backend/app/services/runtime.py now expose editable host/port settings;
- frontend/src/routes/+page.svelte now includes a backend runtime panel tied to the admin API;
- the backend syntax and frontend build were revalidated after the runtime-setting flow was added.

## Commit tracking

- trace_id: `awc-20260607-1624`
- commit status: not done
- hash (optional, after the commit):
- message:
- summary:

## Open risks or doubts

- the installation bootstrap may still need a small wrapper script or release artifact for Unix-like platforms;
- packaging details can change once implementation starts, but the service contract should remain stable;
- the local validation here did not run the app because FastAPI is not installed in the current shell environment.
- the frontend dashboard remains a local scaffold and may need production adapter decisions later.
- runtime changes are persisted in `backend/.env` and still require a restart to take effect in the running process.

## Related

- [deployment.spec](deployment.spec.md)
