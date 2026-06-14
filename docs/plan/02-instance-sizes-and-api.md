# 02 — Instance sizes + create API

## Objective

Let users pick an instance **size** (preset) or **custom** resources when creating an instance,
and surface sizes through the API. Keep the current custom path working.

## Context

- Create flow today: `POST /api/vms` with `name, cores, memory_gb, disk_gb, image_id` →
  `VMDeployer.deploy(...)` runs as a job (`src/homecloud/api/routes.py`,
  `src/homecloud/images/deployer.py`, `src/homecloud/api/schemas.py`).
- Image specs already carry defaults (`src/homecloud/images/registry.py`).

## Design

Add a **sizes catalog** (analogous to cloud machine types). Suggested presets:

| size_id  | vCPU | RAM (GB) | Disk (GB) |
| -------- | ---- | -------- | --------- |
| micro    | 1    | 1        | 10        |
| small    | 1    | 2        | 20        |
| medium   | 2    | 4        | 40        |
| large    | 4    | 8        | 80        |
| xlarge   | 8    | 16       | 160       |
| custom   | user-provided                |

## Changes

1. **New module** `src/homecloud/sizes.py`:
   ```python
   from dataclasses import dataclass

   @dataclass(frozen=True)
   class Size:
       id: str
       label: str
       cores: int
       memory_gb: float
       disk_gb: int

   SIZES = { ... }  # the table above, excluding custom
   def list_sizes() -> list[Size]: ...
   def get_size(size_id: str) -> Size | None: ...
   ```
2. **Schema** (`src/homecloud/api/schemas.py`): extend `DeployVMRequest`:
   - add `size_id: str | None = None`.
   - make `cores/memory_gb/disk_gb` optional; when `size_id` is set and not `custom`, the size
     fills them. Validate: either a valid `size_id` (non-custom) **or** explicit
     cores/memory/disk must be present. Reject conflicting combos with a clear 400.
3. **Routes** (`src/homecloud/api/routes.py`):
   - add `GET /api/sizes` → list of sizes (id, label, cores, memory_gb, disk_gb).
   - in `deploy_vm`, resolve `size_id` → resources before creating the job; store `size_id` in
     the instance record/meta.
4. **Deployer** (`src/homecloud/images/deployer.py`): accept and persist `size_id` in the
   registered VM record and the job result (already persists cores/memory/disk).
5. **State**: include `size_id` in the instance record.

## Acceptance criteria

- `GET /api/sizes` returns the presets.
- `POST /api/vms {name, size_id:"medium", image_id}` creates a 2c/4G/40G instance.
- `POST /api/vms {name, cores, memory_gb, disk_gb}` (no size) still works (size_id = "custom").
- Mixed/invalid combos return 400 with a helpful message.
- `uv run pytest -q` and `uv run ruff check src/` pass.

## Testing

- Unit test `sizes.get_size` and the request resolution helper (size → resources, custom passthrough,
  invalid combos).

## Out of scope

- UI (Phase 08). This phase only needs the API + sizes catalog.
