import { useEffect, useRef, useState } from 'react'
import type { Job } from '../api'
import { clock } from '../lib/format'
import { absoluteTime, duration, elapsed, jobDetails, jobKind, logLevel } from '../lib/jobs'
import { useStore } from '../lib/store'
import { useToast } from './Toast'
import { IconClose } from './Icons'
import { CopyButton, Pill, Spinner } from './ui'

const TERMINAL = ['completed', 'failed', 'cancelled']

export function JobDrawer({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const { api, refresh } = useStore()
  const toast = useToast()
  const [job, setJob] = useState<Job | null>(null)
  const logRef = useRef<HTMLPreElement>(null)
  const autoScroll = useRef(true)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const j = await api.job(jobId)
        if (alive) setJob(j)
        if (j && TERMINAL.includes(j.status)) refresh()
      } catch {
        /* ignore transient errors */
      }
    }
    poll()
    const t = setInterval(poll, 1200)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [jobId, api, refresh])

  useEffect(() => {
    if (autoScroll.current && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [job])

  const done = job ? TERMINAL.includes(job.status) : false
  const details = job ? jobDetails(job) : ''
  const logText = job
    ? [
        ...job.logs.map((l) => `${l.ts}  ${logLevel(l.level).toUpperCase().padEnd(5)}  ${l.message}`),
        ...(job.error ? [`ERROR  ${job.error}`] : []),
      ].join('\n')
    : ''

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Job details">
        <header className="drawer-head">
          <div className="drawer-title">
            <span className="drawer-type">{job ? jobKind(job.type) : 'Job'}</span>
            <strong>{job?.label}</strong>
          </div>
          <Pill status={job?.status} />
          <div className="spacer" />
          {job && !done && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() =>
                api
                  .cancelJob(jobId)
                  .then(() => toast.info('Cancellation requested'))
                  .catch((e) => toast.error(e instanceof Error ? e.message : String(e)))
              }
            >
              Cancel
            </button>
          )}
          <button className="btn-icon" onClick={onClose} title="Close">
            <IconClose />
          </button>
        </header>

        {job && (
          <div className="drawer-summary">
            {details && <div className="drawer-details">{details}</div>}
            <dl className="drawer-facts">
              <div>
                <dt>Started</dt>
                <dd>{absoluteTime(job.started_at || job.created_at) ?? '—'}</dd>
              </div>
              <div>
                <dt>{done ? 'Took' : 'Running for'}</dt>
                <dd>{job.started_at ? duration(job.started_at, job.finished_at) : 'queued'}</dd>
              </div>
              <div>
                <dt>Job</dt>
                <dd className="mono">{job.id}</dd>
              </div>
              <div className="drawer-copy">
                <CopyButton value={logText} label="Copy log" />
              </div>
            </dl>
            {job.error && <div className="drawer-error">{job.error}</div>}
          </div>
        )}

        <pre
          className="log"
          ref={logRef}
          onScroll={(e) => {
            const el = e.currentTarget
            autoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
          }}
        >
          {!job && (
            <div className="log-loading">
              <Spinner /> Loading job…
            </div>
          )}
          {job?.logs.map((l, i) => {
            const level = logLevel(l.level)
            // Indented lines are output copied from the guest, not homecloud's own steps.
            const sub = l.message.startsWith('  ')
            return (
              <div key={i} className={`line line-${level} ${sub ? 'line-sub' : ''}`}>
                <span className="line-ts" title={`${clock(l.ts)} — ${absoluteTime(l.ts) ?? ''}`}>
                  {elapsed(job.started_at || job.created_at, l.ts)}
                </span>
                <span className="line-lvl">{level === 'info' ? '' : level}</span>
                <span className="line-msg">{sub ? l.message.slice(2) : l.message}</span>
              </div>
            )
          })}
          {job && done && job.logs.length === 0 && !job.error && (
            <div className="line line-pending">No log output.</div>
          )}
          {job && !done && (
            <div className="line line-pending">
              <Spinner size={12} /> working…
            </div>
          )}
        </pre>
      </aside>
    </>
  )
}
