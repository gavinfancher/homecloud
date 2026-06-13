import { useCallback, useEffect, useState } from 'react'
import type { Job } from '../api'
import { IconActivity } from '../components/Icons'
import { EmptyState, Pill, Spinner } from '../components/ui'
import { relativeTime, titleCase } from '../lib/format'
import { useStore } from '../lib/store'

export function Activity() {
  const { api, openJob } = useStore()
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
              <th />
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className="job-row" onClick={() => openJob(j.id)}>
                <td>
                  <Pill status={j.status} />
                </td>
                <td>{titleCase(j.type)}</td>
                <td className="job-target">{j.label}</td>
                <td className="muted">{relativeTime(j.started_at || j.created_at)}</td>
                <td className="muted">{j.finished_at ? relativeTime(j.finished_at) : '—'}</td>
                <td className="muted">
                  {j.logs.length} log{j.logs.length === 1 ? '' : 's'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
