import { useState } from 'react'
import type { VM } from '../api'
import { CreateInstanceModal } from '../components/CreateInstanceModal'
import {
  IconChevron,
  IconGlobe,
  IconInstances,
  IconPause,
  IconPlay,
  IconPlus,
  IconScan,
  IconStop,
  IconTrash,
} from '../components/Icons'
import { useToast } from '../components/Toast'
import { CopyButton, EmptyState, Field, Mono, Pill } from '../components/ui'
import { useStore } from '../lib/store'
import { InstanceServices } from './InstanceServices'

export function Instances() {
  const { vms, refresh } = useStore()
  const [creating, setCreating] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'running' | 'stopped'>('all')

  const filtered = vms
    .filter((vm) => {
      if (query && !vm.name.toLowerCase().includes(query.toLowerCase())) return false
      if (filter === 'running') return vm.status === 'running'
      if (filter === 'stopped') return vm.status !== 'running'
      return true
    })
    .sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div className="view">
      <div className="toolbar">
        <input
          className="search"
          placeholder="Search instances…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="segmented">
          {(['all', 'running', 'stopped'] as const).map((f) => (
            <button
              key={f}
              className={filter === f ? 'active' : ''}
              onClick={() => setFilter(f)}
            >
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <button className="btn btn-ghost" onClick={refresh}>
          Refresh
        </button>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          <IconPlus width={16} height={16} /> New instance
        </button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<IconInstances width={32} height={32} />}
          title={vms.length === 0 ? 'No instances yet' : 'No matching instances'}
          hint={
            vms.length === 0
              ? 'Create your first instance to get started.'
              : 'Try a different search or filter.'
          }
          action={
            vms.length === 0 ? (
              <button className="btn btn-primary" onClick={() => setCreating(true)}>
                <IconPlus width={16} height={16} /> New instance
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="instance-list">
          {filtered.map((vm) => (
            <InstanceRow
              key={vm.vmid}
              vm={vm}
              open={expanded === vm.vmid}
              onToggle={() => setExpanded(expanded === vm.vmid ? null : vm.vmid)}
            />
          ))}
        </div>
      )}

      {creating && <CreateInstanceModal onClose={() => setCreating(false)} />}
    </div>
  )
}

function InstanceRow({ vm, open, onToggle }: { vm: VM; open: boolean; onToggle: () => void }) {
  const { api, refresh, openJob } = useStore()
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  async function act(fn: () => Promise<unknown>, msg?: string) {
    setBusy(true)
    try {
      await fn()
      if (msg) toast.success(msg)
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const webCount = vm.web?.length ?? 0

  return (
    <div className={`instance ${open ? 'open' : ''}`}>
      <div className="instance-summary" onClick={onToggle}>
        <button className={`chev ${open ? 'rot' : ''}`} aria-label="Expand">
          <IconChevron width={16} height={16} />
        </button>
        <div className="instance-id">
          <span className="instance-name">{vm.name}</span>
          <span className="muted instance-vmid">#{vm.vmid}</span>
        </div>
        <Pill status={vm.status} />
        <span className="instance-specs muted">
          {vm.cores ?? '?'} vCPU · {vm.memory_gb ?? '?'} GB · {vm.disk_gb ?? '?'} GB
        </span>
        {webCount > 0 && (
          <span className="badge" title={`${webCount} published service(s)`}>
            <IconGlobe width={13} height={13} /> {webCount}
          </span>
        )}
        <div className="spacer" />
        <div className="instance-actions" onClick={(e) => e.stopPropagation()}>
          {vm.status === 'running' ? (
            <>
              <button
                className="btn-icon"
                title="Pause"
                disabled={busy}
                onClick={() => act(() => api.suspend(vm.vmid), `Paused ${vm.name}`)}
              >
                <IconPause />
              </button>
              <button
                className="btn-icon"
                title="Stop"
                disabled={busy}
                onClick={() => act(() => api.stop(vm.vmid), `Stopped ${vm.name}`)}
              >
                <IconStop />
              </button>
            </>
          ) : vm.status === 'paused' ? (
            <button
              className="btn-icon ok"
              title="Resume"
              disabled={busy}
              onClick={() => act(() => api.resume(vm.vmid), `Resumed ${vm.name}`)}
            >
              <IconPlay />
            </button>
          ) : (
            <button
              className="btn-icon ok"
              title="Start"
              disabled={busy}
              onClick={() => act(() => api.start(vm.vmid), `Started ${vm.name}`)}
            >
              <IconPlay />
            </button>
          )}
          <button
            className="btn-icon danger"
            title="Delete"
            disabled={busy}
            onClick={() => {
              if (confirm(`Delete ${vm.name}? This permanently destroys the VM.`))
                act(async () => {
                  const { job_id } = await api.remove(vm.vmid, vm.name)
                  openJob(job_id)
                })
            }}
          >
            <IconTrash />
          </button>
        </div>
      </div>

      {open && (
        <div className="instance-detail">
          <div className="detail-grid">
            <section className="detail-block">
              <h4>Connection</h4>
              <Field label="Hostname">
                {vm.private_host || vm.hostname ? (
                  <span className="copyrow">
                    <Mono>{vm.private_host || vm.hostname}</Mono>
                    <CopyButton value={vm.private_host || vm.hostname || ''} />
                  </span>
                ) : (
                  '—'
                )}
              </Field>
              <Field label="MagicDNS">
                {vm.magic_dns ? (
                  <span className="copyrow">
                    <Mono>{vm.magic_dns}</Mono>
                    <CopyButton value={vm.magic_dns} />
                  </span>
                ) : (
                  '—'
                )}
              </Field>
              <Field label="Tailscale IP">
                {vm.tailscale_ip || vm.ip ? (
                  <span className="copyrow">
                    <Mono>{vm.tailscale_ip || vm.ip}</Mono>
                    <CopyButton value={vm.tailscale_ip || vm.ip || ''} />
                  </span>
                ) : (
                  '—'
                )}
              </Field>
              <Field label="SSH">
                {vm.ssh ? (
                  <span className="copyrow">
                    <Mono>{vm.ssh}</Mono>
                    <CopyButton value={vm.ssh} />
                  </span>
                ) : (
                  '—'
                )}
              </Field>
            </section>

            <section className="detail-block">
              <div className="block-head">
                <h4>Open ports</h4>
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const { job_id } = await api.scanPorts(vm.name)
                      openJob(job_id)
                    })
                  }
                >
                  <IconScan width={14} height={14} /> Scan
                </button>
              </div>
              {vm.ports_seen && vm.ports_seen.length > 0 ? (
                <div className="port-chips">
                  {vm.ports_seen.map((p) => (
                    <span className="port-chip" key={p.port}>
                      <strong>{p.port}</strong>
                      {p.proc && <span className="muted">{p.proc}</span>}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="muted small">
                  No ports scanned yet. Run a scan to discover listening services.
                </p>
              )}
            </section>
          </div>

          <InstanceServices vm={vm} />
        </div>
      )}
    </div>
  )
}
