import { useCallback, useEffect, useState } from 'react'
import type { Job, VM } from '../api'
import { IconActivity } from '../components/Icons'
import { InstanceActions } from '../components/InstanceActions'
import { EmptyState, Pill, Spinner } from '../components/ui'
import { relativeTime, titleCase } from '../lib/format'
import { useStore } from '../lib/store'

const INSTANCE_JOB_TYPES = new Set(['deploy_vm', 'delete_vm', 'scan_ports', 'provision_vm'])

export function Activity() {
  const { api, openJob, vms } = useStore()
  const [jobs, setJobs] = useState<Job[] | null>(null)

  const load = useCallback(() => {
    api
      .listJobs(50)
      .then(setJobs)
      .catch(() => setJobs([]))
  }, [api])

  useEffect(() => {
    load()
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [load])

  if (jobs === null) {
    return (
      <div className="view">
        <div className="panel-empty">
          <Spinner /> Loading activity…
        </div>
      </div>
    )
  }

  if (jobs.length === 0) {
    return (
      <div className="view">
        <EmptyState
          icon={<IconActivity width={32} height={32} />}
          title="No activity yet"
          hint="Jobs from deploys, scans, and builds will show up here."
        />
      </div>
    )
  }

  return (
    <div className="view">
      <div className="panel">
        <table className="jobs-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Type</th>
              <th>Target</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Actions</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <ActivityJobRow key={j.id} job={j} vms={vms} onOpen={() => openJob(j.id)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ActivityJobRow({
  job,
  vms,
  onOpen,
}: {
  job: Job
  vms: VM[]
  onOpen: () => void
}) {
  const vm =
    INSTANCE_JOB_TYPES.has(job.type) ? vms.find((v) => v.name === job.label) : undefined
  const deleting =
    job.type === 'delete_vm' && (job.status === 'pending' || job.status === 'in_progress')

  return (
    <tr className="job-row" onClick={onOpen}>
      <td>
        <Pill status={job.status} />
      </td>
      <td>{titleCase(job.type)}</td>
      <td className="job-target">{job.label}</td>
      <td className="muted">{relativeTime(job.started_at || job.created_at)}</td>
      <td className="muted">{job.finished_at ? relativeTime(job.finished_at) : '—'}</td>
      <td className="job-actions" onClick={(e) => e.stopPropagation()}>
        {vm && !deleting ? <InstanceActions vm={vm} /> : <span className="muted">—</span>}
      </td>
      <td className="muted job-logs">{job.logs.length} log{job.logs.length === 1 ? '' : 's'}</td>
    </tr>
  )
}
