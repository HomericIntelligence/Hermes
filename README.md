# ProjectHermes

ProjectHermes bridges [ai-maestro](https://github.com/HomericIntelligence/ai-maestro) webhooks to [NATS JetStream](https://docs.nats.io/nats-concepts/jetstream) for pub/sub fan-out and event replay across the HomericIntelligence ecosystem.

## Purpose

ai-maestro fires HTTP webhooks when agents and tasks change state. Hermes receives those webhooks, validates them, and publishes structured messages to NATS subjects. Downstream services (Argus, Keystone, Telemachy) subscribe to relevant subjects and react accordingly. JetStream provides durable storage so late-joining subscribers can replay missed events.

```
ai-maestro ──HTTP POST /webhook──► Hermes ──publish──► NATS JetStream
                                                              │
                              ┌───────────────────────────────┤
                              ▼               ▼               ▼
                            Argus         Keystone       Telemachy
```

## Quick Start

```bash
# Start NATS (if not already running via Odysseus)
just nats-start

# Start Hermes
just start

# Check health
just health
```

## Integration

Register Hermes as a webhook receiver with ai-maestro:

```bash
just register-webhook
```

This calls `POST /api/webhooks` on the ai-maestro instance and subscribes to:
- `agent.created`
- `agent.deleted`
- `agent.updated`
- `task.updated`

## Subject Schema

### Agent Events

```
hi.agents.{host}.{name}.{event}
```

| Token  | Description                              |
|--------|------------------------------------------|
| host   | Hostname of the agent's Docker host      |
| name   | Agent container/service name             |
| event  | created, updated, deleted                |

Example: `hi.agents.docker-desktop.researcher.created`

### Task Events

```
hi.tasks.{team_id}.{task_id}.{event}
```

| Token   | Description                             |
|---------|-----------------------------------------|
| team_id | ai-maestro team identifier              |
| task_id | Unique task identifier                  |
| event   | updated, completed, failed              |

Example: `hi.tasks.team-alpha.task-42.updated`

## Configuration

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

| Variable        | Default                        | Description                       |
|-----------------|--------------------------------|-----------------------------------|
| MAESTRO_URL     | http://172.20.0.1:23000        | ai-maestro base URL               |
| MAESTRO_API_KEY |                                | API key for ai-maestro auth       |
| NATS_URL        | nats://localhost:4222          | NATS server URL                   |
| HERMES_PORT     | 8080                           | Port Hermes listens on            |
| WEBHOOK_SECRET  |                                | HMAC secret for webhook validation|

## Development

```bash
just dev      # hot-reload dev server
just test     # run tests
just lint     # ruff check
just format   # ruff format
```
