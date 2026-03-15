#!/usr/bin/env bash
set -euo pipefail
MAESTRO_URL=${MAESTRO_URL:-http://172.20.0.1:23000}
HERMES_URL=${HERMES_URL:-http://localhost:8080}
MAESTRO_API_KEY=${MAESTRO_API_KEY:-}
SECRET=${WEBHOOK_SECRET:-}

curl -sf -X POST "$MAESTRO_URL/api/webhooks" \
  -H "Content-Type: application/json" \
  ${MAESTRO_API_KEY:+-H "Authorization: Bearer $MAESTRO_API_KEY"} \
  -d "{\"url\": \"$HERMES_URL/webhook\", \"events\": [\"agent.created\",\"agent.deleted\",\"agent.updated\",\"task.updated\"], \"secret\": \"$SECRET\"}"

echo "Webhook registered: $HERMES_URL/webhook"
