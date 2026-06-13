import { useEffect, useRef, useState } from 'react'
import type { Job } from '../api'
import { clock, titleCase } from '../lib/format'
import { useStore } from '../lib/store'
import { useToast } from './Toast'
import { IconClose } from './Icons'
import { Pill, Spinner } from './ui'

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

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Job details">
        <header className="drawer-head">
          <div className="drawer-title">
            <span className="drawer-type">{job ? titleCase(job.type) : 'Job'}</span>
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
          {job?.logs.map((l, i) => (
            <div key={i} className={`line line-${l.level}`}>
              <span className="line-ts">{clock(l.ts)}</span>
              <span className="line-lvl">{l.level}</span>
              <span className="line-msg">{l.message}</span>
            </div>
          ))}
          {job?.error && <div className="line line-error">{job.error}</div>}
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
