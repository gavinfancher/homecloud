# Infisical

Secrets management, pulled into `wishly/infra/infisical/` from the standalone
`infisical-test` prototype repo.

## Fetching secrets

```bash
uv sync
uv run get_secrets.py
```

Requires `INFISICAL_PROJECT_ID`, `INFISICAL_ENV`, and `INFISICAL_TOKEN` (a machine identity
access token) in `.env`.

## Getting a token

With a Universal Auth client ID + secret:

```bash
export INFISICAL_TOKEN=$(infisical login \
  --method=universal-auth \
  --client-id=YOUR_CLIENT_ID \
  --client-secret=YOUR_CLIENT_SECRET \
  --plain --silent)
```

Access tokens expire after a few hours — long-running apps should log in with the client
ID/secret directly in code rather than storing a token.

## See also

- [Backups](/aws/backups) — the S3 backup flow this project prototyped
