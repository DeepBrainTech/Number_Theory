#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-dev}"
BOOK="${2:-}"

if [[ "$MODE" == "dev" ]]; then
  COMPOSE_FILE="docker-compose.dev.yml"
else
  COMPOSE_FILE="docker-compose.yml"
fi

echo "== RAG sync ($MODE) =="

if curl -fsS http://localhost:8000/api/library/stats >/dev/null 2>&1; then
  curl -fsS http://localhost:8000/api/library/stats
  echo
fi

if [[ -n "$BOOK" ]]; then
  docker compose -f "$COMPOSE_FILE" run --rm ingest python -m app.ingest --book "$BOOK"
else
  docker compose -f "$COMPOSE_FILE" --profile ingest run --rm ingest
fi

if curl -fsS http://localhost:8000/api/library/stats >/dev/null 2>&1; then
  curl -fsS http://localhost:8000/api/library/stats
  echo
fi
