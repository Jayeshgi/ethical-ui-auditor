# Database workflow

## Why the application needs a database

The trained BERT and YOLO files answer prediction questions, but they do not
store product state. PostgreSQL stores the information that must survive an API
restart:

- user accounts, password hashes, and roles;
- asynchronous scan jobs and their status;
- completed scan results and scan history;
- reviewer decisions, severity, notes, and timestamps;
- autonomous flow job stages and safe request summaries;
- paired goal results, state-graph nodes and transitions, structural findings,
  and finding reviews;
- stored scan and autonomous-flow regression comparisons.

Autonomous test usernames, passwords, and one-time codes are deliberately never
stored. They remain in worker memory for the active run, while PostgreSQL keeps
only a `has_credentials` flag. Screenshots are filesystem artifacts referenced
by the graph records rather than binary database rows.

The image/text datasets and trained model weights are not stored in PostgreSQL.
They remain files or model artifacts because they have different versioning and
storage requirements.

## Local default: native PostgreSQL

PostgreSQL 17 runs as the automatic Windows service `postgresql-x64-17` on
`127.0.0.1:5432`. The local application database is `ethical_ui_auditor` and
the application role is `auditor`. The git-ignored `.env` contains the local
connection URL. `app.core.config` loads this file automatically.

Apply schema migrations and start the backend from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\backend"
& '.\.venv\Scripts\python.exe' -m alembic -c alembic.ini upgrade head
& '.\tools\start_native_backend.ps1'
```

## Optional Docker database

Docker Compose remains available for reproducible demonstrations, CI, and team
deployment. Its API receives an explicit container-only `DATABASE_URL`, so the
container connects to the Docker `database` service while local Python connects
to native PostgreSQL.

Start the container stack with:

```powershell
docker compose up --detach --wait
```

## Synchronizing development data

Preview a synchronization first:

```powershell
& '.\tools\database\sync_postgres.ps1' -Direction NativeToDocker
```

Apply it only after confirming the direction:

```powershell
& '.\tools\database\sync_postgres.ps1' -Direction NativeToDocker -Apply
```

To replace native data with Docker data:

```powershell
& '.\tools\database\sync_postgres.ps1' -Direction DockerToNative -Apply
```

The script creates custom-format source and pre-sync destination backups in
`runtime_data/database_backups/` before restoring. That directory is ignored by
Git. A direction error can overwrite newer destination data, so keep the
automatic backups until the result is verified.

Do not commit database dumps to Git. Dumps can contain password hashes, URLs,
scan evidence, and reviewer notes. Team members should normally synchronize
schema through Alembic migrations and create their own development accounts.
When shared sample data is genuinely required, use a sanitized dump and transfer
it through an access-controlled file channel rather than the source repository.
