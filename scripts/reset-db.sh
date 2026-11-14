#!/bin/bash
# Reset database and run migrations
# Usage: ./scripts/reset-db.sh
#
# Note: This only resets the schema. To seed demo data, run:
#   ./scripts/seed-demo.sh

set -e

echo "Resetting database..."

# Helper to exec in a container: prefer `-T` when supported, fall back otherwise.
docker_exec() {
  service="$1"
  shift
  # Prefer the modern `docker compose` CLI, but fall back to `docker-compose`
  # if the host doesn't support the subcommand. Also prefer `-T` when
  # supported to avoid allocating a TTY for non-interactive commands.
  # The probes read from /dev/null: otherwise they swallow the caller's
  # stdin, and a heredoc meant for the real command (the DROP block below)
  # never reaches it.
  if docker compose version >/dev/null 2>&1; then
    if docker compose exec -T "$service" true </dev/null >/dev/null 2>&1; then
      docker compose exec -T "$service" "$@"
    else
      docker compose exec "$service" "$@"
    fi
    return
  fi

  # Fallback to docker-compose
  if docker-compose version >/dev/null 2>&1; then
    if docker-compose exec -T "$service" true </dev/null >/dev/null 2>&1; then
      docker-compose exec -T "$service" "$@"
    else
      docker-compose exec "$service" "$@"
    fi
    return
  fi

  echo "Neither 'docker compose' nor 'docker-compose' are available." >&2
  exit 1
}

# Reset alembic version
docker_exec db psql -U dental -d dental_clinic -c "DELETE FROM alembic_version;" 2>/dev/null || true

# Drop all tables (in correct order to handle foreign keys)
docker_exec db psql -U dental -d dental_clinic -v ON_ERROR_STOP=1 << 'EOF'
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename != 'alembic_version')
    LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END $$;
EOF

# Run migrations
docker_exec backend alembic upgrade heads

# Restart the backend so the module registry reconciles against the
# fresh schema. Without this, `core_module` stays empty until the next
# manual restart — which makes `/api/v1/modules/-/active` return no
# installed modules and the sidebar collapses to host-shell-only nav.
echo ""
echo "Restarting backend to reconcile module registry..."
docker compose restart backend >/dev/null
# Wait for FastAPI to finish lifespan startup (which runs the module
# registry reconcile) before we return — early callers would race it.
for i in {1..30}; do
  count=$(docker_exec db psql -U dental -d dental_clinic -tA -c \
    "SELECT COUNT(*) FROM core_module WHERE state='installed';" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$count" ] && [ "$count" -gt 0 ]; then
    echo "  registry reconciled ($count modules installed)"
    break
  fi
  sleep 1
done

echo ""
echo "Database reset complete!"
echo "Run ./scripts/seed-demo.sh to create demo data."
