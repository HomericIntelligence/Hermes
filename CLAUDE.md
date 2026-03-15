# ProjectHermes — CLAUDE.md

## Project Overview

ProjectHermes is a lightweight Python service that bridges ai-maestro webhooks to NATS JetStream. It sits between the ai-maestro orchestration platform and the rest of the HomericIntelligence ecosystem, translating HTTP webhook payloads into durable, replayable NATS messages.

## Architecture

```
ai-maestro
    │
    │  HTTP POST /webhook
    ▼
Hermes (FastAPI)
    │  validate HMAC signature
    │  parse event type + data
    │  route to NATS subject
    ▼
NATS JetStream
    │  hi.agents.{host}.{name}.{event}
    │  hi.tasks.{team_id}.{task_id}.{event}
    │
    ├──► Argus     (monitoring / alerting)
    ├──► Keystone  (state management)
    └──► Telemachy (task routing)
```

**Subject schema:**
- Agent events: `hi.agents.{host}.{name}.{event}`
- Task events:  `hi.tasks.{team_id}.{task_id}.{event}`

JetStream streams should be pre-created (by Odysseus or `nats-start`) to capture messages before subscribers connect.

## Key Principles

1. **Stateless HTTP layer** — Hermes itself holds no state; NATS JetStream is the source of truth for event history.
2. **Fail fast on invalid payloads** — HMAC validation and Pydantic parsing reject bad data at the boundary.
3. **Subject granularity** — Fine-grained subjects let subscribers filter precisely; wildcards (`hi.agents.>`) catch everything.
4. **Async throughout** — FastAPI + nats-py are both async; never block the event loop.
5. **Config via environment** — All tunables come from env vars / `.env`; no hard-coded URLs.

## Repository Structure

```
ProjectHermes/
├── src/
│   └── hermes/
│       ├── __init__.py      # package, version
│       ├── config.py        # Settings via env vars
│       ├── models.py        # Pydantic models
│       ├── publisher.py     # NATS JetStream publisher
│       ├── registrar.py     # webhook registration with ai-maestro
│       └── server.py        # FastAPI app + routes
├── tests/
│   ├── __init__.py
│   ├── test_publisher.py    # subject routing tests
│   └── test_webhook.py      # endpoint tests
├── .env.example
├── .github/workflows/ci.yml
├── CLAUDE.md
├── README.md
├── justfile
└── pixi.toml
```

## Development Guidelines

- **Type hints everywhere** — all function signatures must be fully typed.
- **Async handlers** — all FastAPI route handlers and NATS interactions must be `async def`.
- **Pydantic v2** — use `model_validator` / `field_validator` patterns, not v1 `@validator`.
- **No global mutable state** — pass the NATS client via FastAPI's `app.state` or dependency injection.
- **Test subject routing** — subject construction logic must have unit tests; do not rely solely on integration tests.
- **Ruff for linting + formatting** — no flake8/black/isort separately.
- **Secrets never in code** — use `.env` / environment variables; `.env` is gitignored.

## Common Commands

```bash
just            # list all recipes
just start      # run production server
just dev        # hot-reload dev server (uvicorn --reload)
just test       # pytest
just lint       # ruff check src tests
just format     # ruff format src tests
just health     # curl /health endpoint
just register-webhook   # register Hermes with ai-maestro
just nats-start         # start NATS server
```
