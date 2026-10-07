import { useCallback, useEffect, useState } from 'react'
import type { Job } from '../api'
import { IconActivity } from '../components/Icons'
import { EmptyState, Pill, Spinner } from '../components/ui'
import { relativeTime } from '../lib/format'
import { absoluteTime, duration, jobDetails, jobHeadline, jobKind, logLevel } from '../lib/jobs'
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
              <th>Job</th>
              <th>Details</th>
              <th>Started</th>
              <th>Duration</th>
              <th className="job-logs">Log</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <ActivityJobRow key={j.id} job={j} onOpen={() => openJob(j.id)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ActivityJobRow({ job, onOpen }: { job: Job; onOpen: () => void }) {
  const active = job.status === 'pending' || job.status === 'in_progress'
  const failed = job.status === 'failed'
  const details = jobDetails(job)
  const headline = jobHeadline(job)
  const warnings = job.logs.filter((l) => logLevel(l.level) === 'warn').length
  const errors = job.logs.filter((l) => logLevel(l.level) === 'error').length + (job.error ? 1 : 0)
  const started = job.started_at || job.created_at

  return (
    <tr className="job-row" onClick={onOpen}>
      <td>
        <Pill status={job.status} />
      </td>
      <td className="job-name">
        <span className="job-kind">{jobKind(job.type)}</span>
        <span className="job-target">{job.label}</span>
      </td>
      <td className="job-details">
        {details && <span className="job-detail-line">{details}</span>}
        {headline && (active || failed || !details) && (
          <span className={`job-headline ${failed ? 'job-headline-error' : ''}`} title={headline}>
            {headline}
          </span>
        )}
      </td>
      <td className="muted nowrap" title={absoluteTime(started)}>
        {relativeTime(started)}
      </td>
      <td className="muted nowrap" title={job.finished_at ? `Finished ${absoluteTime(job.finished_at)}` : undefined}>
        {job.started_at ? duration(job.started_at, job.finished_at) : '—'}
      </td>
      <td className="job-logs">
        <span className="muted">{job.logs.length} lines</span>
        {warnings > 0 && <span className="log-count log-count-warn">{warnings} warn</span>}
        {errors > 0 && <span className="log-count log-count-error">{errors} err</span>}
      </td>
    </tr>
  )
}
