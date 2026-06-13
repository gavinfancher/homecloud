# 07 — Bake imported SSH key into the base image

## Objective

Let the user import their SSH public key once; ensure it is baked into the base image so every
instance trusts it, and confirm the controller can SSH to instances (needed by Phase 05 port
scanning).

## Context

- Setup already stores an SSH public key (`POST /api/setup` → `state.ssh_public_key`).
- The base image build (`src/homecloud/images/builder.py`) applies cloud-init with the key, and
  per-instance deploy (`src/homecloud/images/specs/deploy.yaml.j2`) also injects
  `ssh_authorized_keys`. This phase verifies/cleans that path and adds key management.

## Changes

1. **Confirm bake-in**: the base-image cloud-init (`images/specs/base-image.yaml.j2`) writes the
   key into the default user's `~/.ssh/authorized_keys` and `prepare_for_template` does not strip
   it. Per-instance deploy also injects it (belt and suspenders). Verify both; fix if the key is
   missing after templating.
2. **Multiple keys**: allow `state.ssh_public_keys: list[str]` (keep `ssh_public_key` as the
   first for backward compat). `GET/POST /api/setup` accept one or many; dedupe.
3. **Controller→instance SSH**: ensure the controller container has the **private** key mounted
   (already `./ssh:/mnt/ssh:ro` + entrypoint copies to `/root/.ssh`). Document that the public
   key baked into images must match this private key so Phase 05 scans work non-interactively.
4. **Rebuild prompt**: changing keys only affects **new** images/instances. Surface a note in
   the API/UI that a base-image rebuild is required to bake new keys; existing instances can get
   keys appended via `guest_exec`/SSH if desired (optional helper
   `append_key_to_instance(name, key)`).

## Acceptance criteria

- After `POST /api/setup` with a key and a base-image build, a freshly created instance accepts
  `ssh <user>@<instance>.<tailnet>.ts.net` with that key, non-interactively from the controller.
- Multiple keys can be stored and all are baked in.
- `uv run pytest -q` and `uv run ruff check src/` pass.

## Testing

- Unit-test setup accepting one vs many keys and dedupe/validation.
- Manual: build base image, create instance, `ssh` in with the imported key; run a port scan
  (Phase 05) to confirm non-interactive SSH works.

## Out of scope

- Key rotation automation across existing instances (optional helper only).
