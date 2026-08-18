# AWS

S3-backed backups for Postgres, streamed rather than staged to disk.

## In this section

- [Backups](/aws/backups) — the streaming `pg_dump` → S3 flow, and restore

## Pieces

- `backup.py` / `backup_stream.py` — dump Postgres, stream straight to S3
- `backup_flow.py` — orchestration wrapper (Prefect, matching `wishly`'s backend)
- `restore.py` — pulls a backup back down and replays it

Credentials and the DB connection string come from [Infisical](/infisical/), not env vars
checked into the repo.
