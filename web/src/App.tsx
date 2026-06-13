import { Show, SignIn, UserButton, useAuth } from '@clerk/react'
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { createApi, type Dashboard, type Job, type Size, type VM } from './api'
import './App.css'

export default function App() {
  return (
    <>
      <Show when="signed-out">
        <div className="signin-wrap">
          <h1 className="brand">☁ homecloud</h1>
          <p className="tagline">Your self-hosted cloud control plane.</p>
          <SignIn />
        </div>
      </Show>
      <Show when="signed-in">
        <Console />
      </Show>
    </>
  )
}

function Console() {
  const { getToken } = useAuth()
  const api = useMemo(() => createApi(getToken), [getToken])

  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [vms, setVms] = useState<VM[]>([])
  const [sizes, setSizes] = useState<Size[]>([])
  const [activeJob, setActiveJob] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [d, v] = await Promise.all([api.dashboard(), api.listVms()])
      setDashboard(d)
      setVms(v)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [api])

  useEffect(() => {
    api.sizes().then(setSizes).catch(() => {})
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [api, refresh])

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">☁ homecloud</span>
        <div className="spacer" />
        {dashboard && (
          <span className="tailnet">{dashboard.tailscale_tailnet || 'no tailnet'}</span>
        )}
        <UserButton />
      </header>

      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error} (click to dismiss)
        </div>
      )}

      <main>
        {dashboard && <Stats d={dashboard} />}

        <section className="card">
          <h2>Create instance</h2>
          <CreateForm
            sizes={sizes}
            onCreated={(jobId) => {
              setActiveJob(jobId)
              refresh()
            }}
            onError={setError}
            api={api}
          />
        </section>

        <section className="card">
          <h2>Instances ({vms.length})</h2>
          <Instances
            vms={vms}
            api={api}
            onJob={setActiveJob}
            onError={setError}
            onChange={refresh}
          />
        </section>
      </main>

      {activeJob && (
        <JobDrawer
          jobId={activeJob}
          api={api}
          onClose={() => {
            setActiveJob(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

function Stats({ d }: { d: Dashboard }) {
  const cells = [
    { label: 'Instances', value: d.stats.total_vms },
    { label: 'Running', value: d.stats.running },
    { label: 'Stopped', value: d.stats.stopped },
    { label: 'Templates', value: d.stats.templates },
  ]
  return (
    <div className="stats">
      {cells.map((c) => (
        <div className="stat" key={c.label}>
          <div className="stat-value">{c.value}</div>
          <div className="stat-label">{c.label}</div>
        </div>
      ))}
      {!d.base_image_built && (
        <div className="stat warn">Base image not built — build it before creating instances.</div>
      )}
    </div>
  )
}

function CreateForm({
  sizes,
  api,
  onCreated,
  onError,
}: {
  sizes: Size[]
  api: ReturnType<typeof createApi>
  onCreated: (jobId: string) => void
  onError: (msg: string) => void
}) {
  const [name, setName] = useState('')
  const [sizeId, setSizeId] = useState('small')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const { job_id } = await api.deploy({ name, size_id: sizeId })
      onCreated(job_id)
      setName('')
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="create" onSubmit={submit}>
      <input
        placeholder="instance name (e.g. dagster)"
        value={name}
        pattern="[a-z][a-z0-9-]{1,30}"
        title="lowercase, starts with a letter, 2–31 chars"
        required
        onChange={(e) => setName(e.target.value)}
      />
      <select value={sizeId} onChange={(e) => setSizeId(e.target.value)}>
        {sizes.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label} — {s.cores} vCPU / {s.memory_gb} GB / {s.disk_gb} GB
          </option>
        ))}
      </select>
      <button disabled={busy || !name}>{busy ? 'Creating…' : 'Create'}</button>
    </form>
  )
}

function Instances({
  vms,
  api,
  onJob,
  onError,
  onChange,
}: {
  vms: VM[]
  api: ReturnType<typeof createApi>
  onJob: (id: string) => void
  onError: (msg: string) => void
  onChange: () => void
}) {
  async function act(fn: () => Promise<unknown>) {
    try {
      await fn()
      onChange()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  if (vms.length === 0) return <p className="muted">No instances yet.</p>

  return (
    <table className="vms">
      <thead>
        <tr>
          <th>Name</th>
          <th>Status</th>
          <th>Resources</th>
          <th>Hostname</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {vms.map((vm) => (
          <tr key={vm.vmid}>
            <td>{vm.name}</td>
            <td>
              <span className={`pill ${vm.status}`}>{vm.status}</span>
            </td>
            <td className="muted">
              {vm.cores ?? '?'} vCPU · {vm.memory_gb ?? '?'} GB · {vm.disk_gb ?? '?'} GB
            </td>
            <td className="muted">{vm.hostname ?? '—'}</td>
            <td className="actions">
              {vm.status === 'running' ? (
                <>
                  <button onClick={() => act(() => api.suspend(vm.vmid))}>Pause</button>
                  <button onClick={() => act(() => api.stop(vm.vmid))}>Stop</button>
                </>
              ) : vm.status === 'paused' ? (
                <button onClick={() => act(() => api.resume(vm.vmid))}>Resume</button>
              ) : (
                <button onClick={() => act(() => api.start(vm.vmid))}>Start</button>
              )}
              <button
                onClick={() =>
                  act(async () => {
                    const { job_id } = await api.scanPorts(vm.name)
                    onJob(job_id)
                  })
                }
              >
                Scan ports
              </button>
              <button
                className="danger"
                onClick={() => {
                  if (confirm(`Delete ${vm.name}? This destroys the VM.`))
                    act(() => api.remove(vm.vmid, vm.name))
                }}
              >
                Delete
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function JobDrawer({
  jobId,
  api,
  onClose,
}: {
  jobId: string
  api: ReturnType<typeof createApi>
  onClose: () => void
}) {
  const [job, setJob] = useState<Job | null>(null)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const j = await api.job(jobId)
        if (alive) setJob(j)
      } catch {
        /* ignore transient errors */
      }
    }
    poll()
    const t = setInterval(poll, 1500)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [jobId, api])

  const done = job && ['completed', 'failed', 'cancelled'].includes(job.status)

  return (
    <div className="drawer">
      <div className="drawer-head">
        <strong>
          {job?.type} · {job?.label}
        </strong>
        <span className={`pill ${job?.status}`}>{job?.status ?? '…'}</span>
        <div className="spacer" />
        {job && !done && (
          <button onClick={() => api.cancelJob(jobId).catch(() => {})}>Cancel</button>
        )}
        <button onClick={onClose}>Close</button>
      </div>
      <pre className="log">
        {job?.logs.map((l, i) => (
          <div key={i} className={`line ${l.level}`}>
            <span className="ts">{l.ts.slice(11, 19)}</span> {l.message}
          </div>
        ))}
        {job?.error && <div className="line error">{job.error}</div>}
      </pre>
    </div>
  )
}
