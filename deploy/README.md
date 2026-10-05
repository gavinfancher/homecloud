# Deploying homecloud

One Ubuntu VM runs the whole control plane: `api`, `postgres`, `cloudflared`
and `coredns` (`compose.yml`). Every secret comes from Infisical, so the only
credential on the box is the Infisical machine identity in
`/etc/homecloud/infisical.env`.

## Fresh VM

1. **Join the tailnet** with `tailscale up`. CoreDNS binds the VM's tailnet IP,
   and Tailscale split DNS (`vm.dns.gavinf.com` → that IP) points at it.
2. **Run `sudo deploy/bootstrap.sh`.** It installs Docker and the Infisical
   CLI and creates `/etc/homecloud/infisical.env`.
3. **Fill in `/etc/homecloud/infisical.env`** with a Universal Auth machine
   identity that can read env `prod` of the `homecloud` project. Every key in
   `.env.example` must be set there.
4. **Run `sudo deploy/deploy.sh sha-<short>`** with the image tag of a commit
   on `main`.
5. **Register the self-hosted runner** (labels `self-hosted,linux,homecloud`)
   so merges to `main` deploy themselves. The repo's
   Settings → Actions → Runners page shows the commands; run it as `ubuntu`,
   which needs passwordless sudo for `deploy.sh`.

## Day to day

- **Ship**: merge to `main`. `release.yml` builds `sha-<short>`, then the
  runner on the VM runs `deploy.sh`, which health-checks the api and rolls
  back to the previous tag on failure.
- **Change a secret**: edit it in Infisical, then redeploy the current tag
  with `sudo /opt/homecloud/deploy.sh $(cat /opt/homecloud/.tag)`. Containers
  read their environment only when they are created.
- **Logs**: `docker logs -f homecloud-api`.
- **Database shell**: `docker exec -it homecloud-postgres psql -U homecloud`.
