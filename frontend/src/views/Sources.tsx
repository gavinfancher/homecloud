import { useState } from 'react'
import type { Source } from '../api'
import { IconImages } from '../components/Icons'
import { useToast } from '../components/Toast'
import { EmptyState, Pill } from '../components/ui'
import { useStore } from '../lib/store'

export function Sources() {
  const { sources, dashboard, api, openJob, refreshSources } = useStore()
  const toast = useToast()
  const [busyId, setBusyId] = useState<string | null>(null)

  // An import is a job; a source counts as importing while its job runs.
  const importing = new Set(
    (dashboard?.recent_jobs ?? [])
      .filter((j) => j.type === 'import_source' && ['pending', 'running'].includes(j.status))
      .map((j) => j.label),
  )

  async function startImport(source: Source) {
    setBusyId(source.id)
    try {
      const { job_id } = await api.importSource(source.id)
      toast.success(`Importing ${source.name}…`)
      openJob(job_id)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
      refreshSources()
    }
  }

  return (
    <div className="view">
      <div className="toolbar">
        <p className="muted small toolbar-note">
          Stock distro images. Importing downloads one onto the node and bakes in the QEMU
          guest agent; instances are cloned from it and configured with Ansible.
        </p>
        <div className="spacer" />
        <button className="btn btn-ghost" onClick={refreshSources}>
          Refresh
        </button>
      </div>

      {sources.length === 0 ? (
        <EmptyState
          icon={<IconImages width={32} height={32} />}
          title="No sources available"
          hint="The controller needs a database (DATABASE_URL) to list source images."
        />
      ) : (
        <div className="image-grid">
          {sources.map((src) => (
            <SourceCard
              key={src.id}
              source={src}
              busy={busyId === src.id}
              importing={importing.has(src.id)}
              onImport={() => startImport(src)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SourceCard({
  source,
  busy,
  importing,
  onImport,
}: {
  source: Source
  busy: boolean
  importing: boolean
  onImport: () => void
}) {
  const status = importing ? 'in_progress' : source.imported ? 'completed' : 'paused'
  const label = importing ? 'Importing' : source.imported ? 'Ready' : 'Not imported'

  return (
    <div className="image-card">
      <div className="image-card-head">
        <div className="image-icon">
          <IconImages width={20} height={20} />
        </div>
        <div className="image-titles">
          <h3>{source.name}</h3>
        </div>
        <Pill status={status}>{label}</Pill>
      </div>

      <div className="image-specs">
        <span>{source.distro} {source.version}</span>
        <span>{source.arch}</span>
        {source.template_id != null && <span>template #{source.template_id}</span>}
      </div>

      <div className="image-card-foot">
        {!source.imported && (
          <button className="btn btn-primary" disabled={busy || importing} onClick={onImport}>
            {busy ? 'Starting…' : importing ? 'Importing…' : 'Import'}
          </button>
        )}
      </div>
    </div>
  )
}
