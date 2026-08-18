# Backups

`backup_stream.py` runs `pg_dump` inside the Postgres container and pipes its stdout straight
into an S3 multipart upload — no intermediate dump file on disk.

```python
proc = subprocess.Popen(
    ["docker", "exec", CONTAINER, "pg_dump", "-U", DB_USER, "-d", DB_NAME, "-F", "c"],
    stdout=subprocess.PIPE,
)
s3.upload_fileobj(proc.stdout, BUCKET, key)
```

Object key: `backups/<db>-<UTC timestamp>.dump`. Credentials come from
[Infisical](/infisical/), not env vars checked into the repo.

`restore.py` reverses the flow: pull the object back from S3 and replay it with `pg_restore`.
