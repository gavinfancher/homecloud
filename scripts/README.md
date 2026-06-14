# Scripts

Shell helpers for local dev and control-node operations. Run from repo root or via
`make` targets in the root `Makefile`.

| Script | Purpose |
|--------|---------|
| `bootstrap-control-node.sh` | First-time VM setup: clone repo, restore `.env` / state, deploy |
| `control-node-deploy.sh` | **Production deploy**: `git fetch` + reset to `main`, rebuild controller, `compose up` |
| `deploy-stack.sh` | Local compose rebuild; delegates to `control-node-deploy.sh` if in a git clone |
| `deploy-remote.sh` | From laptop: SSH to control node and run `control-node-deploy.sh` |
| `deploy-frontend.sh` | Build SPA and `wrangler deploy` (backup; primary path is Cloudflare Workers Git) |
| `install-github-runner.sh` | Register a self-hosted Actions runner on the control node VM |

Stack commands use `infra/docker/docker-compose.yml` and the repo-root `.env`:

```bash
docker compose -f infra/docker/docker-compose.yml --env-file .env up -d
```

Automated backend deploy: GitHub Actions self-hosted runner runs `control-node-deploy.sh`
on push to `main`. See [deploy-backend.md](../docs/deploy-backend.md).
