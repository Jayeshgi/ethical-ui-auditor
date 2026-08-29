#!/usr/bin/env sh
set -eu

attempt=1
max_attempts=30
until alembic -c /app/alembic.ini upgrade head; do
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "Database migration failed after $max_attempts attempts." >&2
        exit 1
    fi
    echo "Database is not ready; retrying migration in 2 seconds ($attempt/$max_attempts)." >&2
    attempt=$((attempt + 1))
    sleep 2
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
