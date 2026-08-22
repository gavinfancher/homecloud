# VM status API

`GET /api2/json/nodes/{node}/qemu/{vmid}/status/current` is the single richest
read-only call in the Proxmox VE API. One request returns live CPU, memory,
disk, network, per-block-device and host-pressure counters for one VM.

This page documents what it returns, how to call it, and the traps in the
payload.

## Calling it

```bash
curl -k -H "Authorization: PVEAPIToken=USER@REALM!TOKENID=SECRET" \
  https://<host>:8006/api2/json/nodes/<node>/qemu/<vmid>/status/current
```

For this deployment the pieces come out of `.env` at the repo root:

| Placeholder | `.env` key | Value here |
|---|---|---|
| `<host>` | `PROXMOX_HOST` | `100.106.79.65` (Tailscale IP — you must be on the tailnet) |
| `USER@REALM` | `PROXMOX_USER` | `root@pam` |
| `TOKENID` | `PROXMOX_TOKEN_NAME` | — |
| `SECRET` | `PROXMOX_TOKEN_VALUE` | — |
| `<node>` | `PROXMOX_NODE` | `pve-root` |

So a runnable version that never echoes the secret:

```bash
set -a; . ./.env; set +a
curl -s -k \
  -H "Authorization: PVEAPIToken=${PROXMOX_USER}!${PROXMOX_TOKEN_NAME}=${PROXMOX_TOKEN_VALUE}" \
  "https://${PROXMOX_HOST}:8006/api2/json/nodes/${PROXMOX_NODE}/qemu/500/status/current"
```

### The header format

The `Authorization` value is one string with a very particular shape:

```
PVEAPIToken=root@pam!homecloud=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
             └─user─┘ └─token┘ └────────── secret ──────────────┘
                   ^         ^
                   │         └── literal '=' before the secret
                   └── literal '!' between user and token id
```

Getting the `!` or the second `=` wrong produces a bare **401 with an empty
body** — no JSON, no error message. If you get a silent 401, check the header
shape before anything else.

### `-k` and TLS

Proxmox ships a self-signed certificate, so `-k` (`--insecure`) is required
unless you have trusted the node's CA. `PROXMOX_VERIFY_SSL=false` in `.env` is
the same decision for the Python client. This is acceptable here only because
the transport is already a Tailscale WireGuard tunnel — do not carry the habit
onto a public endpoint.

### Finding a vmid

```bash
curl -s -k -H "Authorization: PVEAPIToken=..." \
  "https://${PROXMOX_HOST}:8006/api2/json/nodes/${PROXMOX_NODE}/qemu"
```

Current VMs on `pve-root`: `500` (`homecloud`, running), `8001`
(`tpl-homecloud-base`, template), `9100` (`cloudimg-debian-12`, template).

### Required privileges

The token needs `VM.Audit` on `/vms/<vmid>`. Read-only — this endpoint cannot
change VM state. Note that a token created with privilege separation on
(the default) has *no* permissions until you grant them explicitly, even when
the underlying user is `root@pam`.

## The response

Everything is wrapped in a top-level `data` object. Real output from VM 500:

```json
{"data":{"pressureiosome":0,"proxmox-support":{...},"freemem":861749248,
"nics":{"tap500i0":{"netout":813055780,"netin":1496334773}},"ballooninfo":{...},
"diskread":1519260870,"maxdisk":32212254720,"running-machine":"pc-i440fx-10.1+pve0",
"name":"homecloud","qmpstatus":"running","pid":3056761,"uptime":1020293,
"diskwrite":9051177984,"maxmem":4294967296,"vmid":500,"status":"running",
"memhost":3768188928,"cpus":2,"netin":1496334773,"netout":813055780,"disk":0,
"ha":{"managed":0},"serial":1,"balloon":4294967296,"mem":3244339200,
"blockstat":{...},"running-qemu":"10.1.2","agent":1,"cpu":0.0183502895686479}}
```

**Key order is not stable between calls.** It comes from a Perl hash, so it
varies run to run. Always parse by key, never by position.

### Identity and state

| Field | Meaning |
|---|---|
| `vmid` | Numeric VM id |
| `name` | Configured VM name |
| `status` | `running` or `stopped` — the coarse PVE-level state |
| `qmpstatus` | Finer QEMU monitor state: `running`, `paused`, `prelaunch`, `io-error`, … |
| `uptime` | Seconds since the VM started; `0` when stopped |
| `pid` | Host PID of the `qemu` process; absent when stopped |
| `template` | `1` if this is a template. **Only present when true** — do not expect `0` |
| `agent` | `1` if the guest agent is enabled in the VM config |
| `serial` | `1` if a serial console is configured |
| `ha.managed` | `1` if under the HA manager |
| `clipboard` | VNC clipboard mode; `null` when unset |
| `running-qemu` | QEMU version, e.g. `10.1.2` |
| `running-machine` | Machine type, e.g. `pc-i440fx-10.1+pve0` |

`status` vs `qmpstatus` matters: a **suspended VM still reports
`status: "running"`** while `qmpstatus` reads `paused`. If you care about the
difference between running and paused, read `qmpstatus`.

`agent: 1` means the agent is *configured*, not that it is *responding*. To
know it actually answers, call `/agent/ping`.

### CPU

| Field | Meaning |
|---|---|
| `cpu` | Load as a fraction `0.0`–`1.0` of **all** assigned vCPUs |
| `cpus` | Number of assigned vCPUs |

`cpu` is already normalised across vCPUs, so the percentage is
`cpu * 100` — not `cpu * 100 * cpus`. VM 500's `0.0183` is 1.83% of its 2-vCPU
allocation, not 3.7%.

It is a short-window average sampled by the host, so consecutive calls a second
apart will differ noticeably (we saw 0.0112 → 0.0184 → 0.0104 across three
calls). For anything user-facing, smooth it or read `rrddata` instead.

### Memory

| Field | Meaning |
|---|---|
| `mem` | Guest memory in use, bytes |
| `maxmem` | Configured RAM ceiling, bytes |
| `memhost` | Host-side resident memory for the QEMU process, bytes |
| `freemem` | Guest-reported free memory, bytes — **agent/balloon only** |
| `balloon` | Current balloon target, bytes |
| `ballooninfo` | Detailed balloon counters (see below) |

`ballooninfo` carries `actual`, `total_mem`, `free_mem`, `max_mem`,
`major_page_faults`, `minor_page_faults`, `mem_swapped_in`, `mem_swapped_out`,
and a `last_update` unix timestamp.

Two traps:

- `total_mem` (4106088448) is *less* than `maxmem` (4294967296). The guest
  kernel reserves memory for itself, so guest-visible RAM is always a bit under
  the configured amount. Compute "percent used" against a consistent
  denominator, and say which one you picked.
- `freemem` and `ballooninfo` are populated **only when the guest agent /
  balloon driver is running**. Without it these fields are absent or stale, and
  `mem` becomes a host-side estimate that typically overstates real guest usage,
  because it counts pages the guest freed but never returned.

### Disk

| Field | Meaning |
|---|---|
| `disk` | Disk bytes in use — **always `0` here** |
| `maxdisk` | Configured disk size, bytes |
| `diskread` / `diskwrite` | Cumulative bytes since VM start |

**`disk` is always `0` on LVM- and ZFS-backed VMs.** Proxmox cannot cheaply
introspect a raw block device to find the used bytes inside the guest
filesystem. This storage is `local-lvm`, so the field is permanently `0` — it
is not a bug and not a "VM uses no disk" signal. For real usage you must ask the
guest: `GET /nodes/{node}/qemu/{vmid}/agent/get-fsinfo`, which needs the agent.

`diskread` / `diskwrite` reset to `0` on every VM start. They are counters since
the current boot, not lifetime totals.

### Network

| Field | Meaning |
|---|---|
| `netin` / `netout` | Cumulative bytes since VM start, all interfaces summed |
| `nics` | Per-interface breakdown, keyed by host tap device |

```json
"nics": { "tap500i0": { "netin": 1496334773, "netout": 813055780 } }
```

Keys are host-side tap names (`tap<vmid>i<index>`), so `tap500i0` is `net0` of
VM 500. These are **totals, not rates** — to get bandwidth, sample twice and
divide by elapsed time, or use `rrddata`, which reports rates directly.

Direction is from the VM's point of view: `netin` is traffic *into* the guest.

### `blockstat`

Per-block-device counters straight from QEMU, keyed by device name (`scsi0`,
`ide2`, …). The interesting ones:

| Field | Meaning |
|---|---|
| `rd_bytes` / `wr_bytes` | Bytes read / written |
| `rd_operations` / `wr_operations` | Request counts |
| `rd_total_time_ns` / `wr_total_time_ns` | Cumulative service time, nanoseconds |
| `flush_operations` / `flush_total_time_ns` | Cache flushes and their cost |
| `unmap_*` | Discard / TRIM activity |
| `wr_highest_offset` | Highest byte offset ever written — rough proxy for allocated size |
| `idle_time_ns` | Nanoseconds since the last operation on this device |
| `failed_*` / `invalid_*` | Error counters, per operation type |
| `account_failed` / `account_invalid` | Whether the above are being tallied |
| `zone_append_*` | Zoned-block-device counters; always `0` on normal disks |
| `timed_stats` | Empty unless you configure interval stats in QEMU |

Average write latency is `wr_total_time_ns / wr_operations`. For VM 500 that is
1254574285382 / 405739 ≈ **3.09 ms**.

`wr_highest_offset` (14207811584 ≈ 13.2 GiB of a 30 GiB disk) is the closest
thing to a disk-usage number available without the guest agent. It is a
high-water mark, so it never decreases — deleting files in the guest will not
bring it down.

Note `ide2` — the cloud-init drive. Its `idle_time_ns` of ~324113 seconds ≈ 3.75
days is much larger than the VM's 11.8-day uptime would suggest for a never-used
device, because it was read at boot and never touched again.

### Host pressure (PSI)

`pressurecpusome`, `pressurecpufull`, `pressureiosome`, `pressureiofull`,
`pressurememorysome`, `pressurememoryfull` are Linux PSI metrics from the host
cgroup backing this VM. They measure the share of time tasks were **stalled
waiting** on a resource.

- `some` — at least one task stalled
- `full` — all tasks stalled (much more serious)

All six are `0` on this node, which is the healthy case. Sustained nonzero
`pressureiofull` is the clearest signal that a VM is starved by host storage
contention rather than by its own workload.

### `proxmox-support`

Feature flags of the running QEMU binary, mostly backup-related
(`pbs-dirty-bitmap`, `backup-fleecing`, `backup-max-workers`, …). Useful to
check what a *running* VM supports, since it reflects the binary the VM was
started with — after a PVE upgrade, a long-running VM can report older
capabilities than a freshly started one.

## Stopped VMs and templates return much less

A stopped VM has no QEMU process, so everything sourced from QMP disappears.
Template `8001` in full:

```json
{"data":{"cpus":2,"memhost":0,"name":"tpl-homecloud-base","maxdisk":21474836480,
"netin":0,"netout":0,"clipboard":null,"ha":{"managed":0},"disk":0,
"qmpstatus":"stopped","uptime":0,"serial":1,"template":1,"maxmem":2147483648,
"mem":0,"status":"stopped","agent":1,"vmid":8001,"cpu":0}}
```

Gone entirely: `blockstat`, `nics`, `ballooninfo`, `freemem`, `balloon`, `pid`,
`running-qemu`, `running-machine`, `proxmox-support`, and every `pressure*`
field. Present but zeroed: `cpu`, `mem`, `memhost`, `netin`, `netout`, `uptime`.

Any consumer must treat the running-only fields as optional. Reaching straight
into `data["blockstat"]["scsi0"]` will `KeyError` the first time it meets a
stopped VM.

## Errors

| Condition | Status | Body |
|---|---|---|
| Success | `200` | `{"data":{...}}` |
| Bad or missing token | `401` | **empty** — no JSON at all |
| Nonexistent vmid | `500` | `{"message":"Configuration file 'nodes/pve-root/qemu-server/999.conf' does not exist\n","data":null}` |

Two things to code around:

- A bad vmid is a **500, not a 404**. Do not treat 5xx as "server broken, retry
  with backoff" here — retrying a bad vmid will never succeed.
- A 401 has an **empty body**, so `response.json()` raises a decode error rather
  than returning something useful. Check the status code before parsing.

## Related endpoints

**Cheap bulk listing** — one call for every VM on the cluster, no QMP round
trips. Best choice for a dashboard list view:

```bash
GET /api2/json/cluster/resources?type=vm
```

Returns the summary fields only (`vmid`, `name`, `status`, `cpu`, `maxcpu`,
`mem`, `maxmem`, `disk`, `maxdisk`, `netin`, `netout`, `diskread`, `diskwrite`,
`uptime`, `node`, `template`) — no `blockstat`, `nics`, `ballooninfo`, or
pressure data. Note it is `maxcpu` here, where `status/current` says `cpus`.

**Time series** — pre-averaged history from the RRD files:

```bash
GET /api2/json/nodes/{node}/qemu/{vmid}/rrddata?timeframe=hour
```

`timeframe` is `hour`, `day`, `week`, `month`, or `year`; `hour` returns 60
points at 1-minute resolution. Each point has a `time` (unix seconds) plus the
usual metrics.

The critical difference: **rrddata reports rates, status/current reports
totals.** The same VM shows `netin: 2422.07` (bytes/sec) in `rrddata` against
`netin: 1496491505` (bytes total) in `status/current`. Do not mix them in one
chart.

## Using it from this repo

`ProxmoxClient` (`src/homecloud/proxmox/client.py`) wraps `proxmoxer` and
already holds the host, token and node from `settings`. The equivalent call:

```python
from homecloud.proxmox.client import ProxmoxClient

client = ProxmoxClient()
status = client.api.nodes(client.node).qemu(500).status.current.get()

print(status["status"], status["cpu"], status["mem"])
```

`proxmoxer` unwraps the `data` envelope for you, so you get the inner object
directly.

Two conventions worth keeping to:

- `list_vms()` deliberately avoids per-VM calls and caches for 4 seconds
  (`_VM_LIST_CACHE_TTL`). Reach for `status/current` only when you need the
  detail it uniquely provides — it is a live QMP round trip per call, so it does
  not belong in a loop over every VM on a page load.
- The existing helpers normalise units at the boundary (`maxmem` → `memory_mb`,
  `maxdisk` → `disk_gb`). Raw bytes should not leak into the frontend.

## Polling notes

`status/current` queries QEMU live rather than reading a cache, so it is
meaningfully more expensive than `cluster/resources`. The host's own sampling
runs about every 10 seconds, so polling faster than that returns fresher
counters but no genuinely new CPU or memory information.

A reasonable split: `cluster/resources` on a short interval for list views,
`status/current` only for a focused single-VM view, and `rrddata` for anything
drawn as a graph.
