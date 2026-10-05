import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Job } from '../api'
import { IconActivity, IconImages, IconInstances, IconPlay, IconStop } from '../components/Icons'
import { InstanceActions } from '../components/InstanceActions'
import { Pill } from '../components/ui'
import { relativeTime, titleCase } from '../lib/format'
import { useStore } from '../lib/store'

export function Overview() {
  const navigate = useNavigate()
  const { dashboard, vms } = useStore()
  const stats = dashboard?.stats
  const jobs = dashboard?.recent_jobs ?? []

  const cards = [
    { label: 'Instances', value: stats?.total_vms ?? 0, icon: <IconInstances />, tone: 'accent' },
    { label: 'Running', value: stats?.running ?? 0, icon: <IconPlay />, tone: 'ok' },
    { label: 'Stopped', value: stats?.stopped ?? 0, icon: <IconStop />, tone: 'danger' },
    { label: 'Templates', value: stats?.templates ?? 0, icon: <IconImages />, tone: 'muted' },
  ]

  return (
    <div className="view">
      {dashboard && !dashboard.base_image_ready && (
        <div className="callout callout-warn">
          <div>
            <strong>No base image built yet.</strong> Build one before creating instances.
          </div>
          <button className="btn btn-sm" onClick={() => navigate('/base-image')}>
            Go to Base image
          </button>
        </div>
      )}

      <div className="stat-grid">
        {cards.map((c) => (
          <div className={`stat-card stat-${c.tone}`} key={c.label}>
            <div className="stat-icon">{c.icon}</div>
            <div>
              <div className="stat-value">{c.value}</div>
              <div className="stat-label">{c.label}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="two-col">
        <section className="panel">
          <header className="panel-head">
            <h2>System</h2>
          </header>
          <div className="info-list">
            <Row label="Proxmox node" value={dashboard?.proxmox_node || '—'} />
            <Row label="Storage" value={dashboard?.proxmox_storage || '—'} />
            <Row label="Tailnet" value={dashboard?.tailscale_tailnet || 'not configured'} />
            <Row
              label="Base image"
              value={
                <Pill status={dashboard?.base_image_ready ? 'completed' : 'failed'}>
                  {dashboard?.base_image_ready ? 'Ready' : 'Not built'}
                </Pill>
              }
            />
            <Row
              label="Setup"
              value={
                <Pill status={dashboard?.setup_complete ? 'completed' : 'paused'}>
                  {dashboard?.setup_complete ? 'Complete' : 'Incomplete'}
                </Pill>
              }
            />
          </div>
        </section>

        <section className="panel">
          <header className="panel-head">
            <h2>Recent activity</h2>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/activity')}>
              View all
            </button>
          </header>
          {jobs.length === 0 ? (
            <div className="panel-empty">
              <IconActivity width={28} height={28} />
              <span>No activity yet</span>
            </div>
          ) : (
            <ul className="activity-list">
              {jobs.slice(0, 6).map((j) => (
                <ActivityRow key={j.id} job={j} />
              ))}
            </ul>
          )}
        </section>
      </div>

      {vms.length > 0 && (
        <section className="panel">
          <header className="panel-head">
            <h2>Instances</h2>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/instances')}>
              Manage
            </button>
          </header>
          <div className="mini-vms">
            {vms.map((vm) => (
              <div key={vm.vmid} className="mini-vm-card">
                <button
                  className="mini-vm-main"
                  type="button"
                  onClick={() => navigate('/instances')}
                >
                  <Pill status={vm.status} />
                  <span className="mini-vm-name">{vm.name}</span>
                  <span className="muted mini-vm-specs">
                    {vm.cores ?? '?'} vCPU · {vm.memory_gb ?? '?'} GB
                  </span>
                </button>
                <InstanceActions vm={vm} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  )
}

function ActivityRow({ job }: { job: Job }) {
  const { openJob } = useStore()
  return (
    <li className="activity-row" onClick={() => openJob(job.id)}>
      <Pill status={job.status} />
      <div className="activity-main">
        <span className="activity-title">
          {titleCase(job.type)} · <strong>{job.label}</strong>
        </span>
      </div>
      <span className="muted activity-time">
        {relativeTime(job.finished_at || job.started_at || job.created_at)}
      </span>
    </li>
  )
}
