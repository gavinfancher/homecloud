import { useState } from 'react'
import { IconImages } from '../components/Icons'
import { useToast } from '../components/Toast'
import { EmptyState, Pill } from '../components/ui'
import { useStore } from '../lib/store'

export function Images() {
  const { images, dashboard, api, openJob, refreshImages } = useStore()
  const toast = useToast()
  const [building, setBuilding] = useState(false)

  async function build() {
    setBuilding(true)
    try {
      const { job_id } = await api.buildBaseImage()
      toast.success('Build started')
      openJob(job_id)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBuilding(false)
      refreshImages()
    }
  }

  if (images.length === 0) {
    return (
      <div className="view">
        <EmptyState
          icon={<IconImages width={32} height={32} />}
          title="No images registered"
          hint="Images define the base template used to deploy instances."
        />
      </div>
    )
  }

  return (
    <div className="view">
      <div className="image-grid">
        {images.map((img) => (
          <div className="image-card" key={img.id}>
            <div className="image-card-head">
              <div className="image-icon">
                <IconImages width={20} height={20} />
              </div>
              <div className="image-titles">
                <h3>{img.name}</h3>
                <code className="muted">{img.id}</code>
              </div>
              <Pill status={img.built ? 'completed' : 'paused'}>
                {img.built ? 'Built' : 'Not built'}
              </Pill>
            </div>

            <p className="image-desc">{img.description}</p>

            <div className="image-specs">
              <span>{img.default_cores} vCPU</span>
              <span>{(img.default_memory_mb / 1024).toFixed(0)} GB RAM</span>
              <span>{img.default_disk_gb} GB disk</span>
              {img.template_id != null && <span>template #{img.template_id}</span>}
            </div>

            {img.packages.length > 0 && (
              <div className="pkg-list">
                {img.packages.slice(0, 12).map((p) => (
                  <span className="pkg" key={p}>
                    {p}
                  </span>
                ))}
                {img.packages.length > 12 && (
                  <span className="pkg muted">+{img.packages.length - 12} more</span>
                )}
              </div>
            )}

            {img.id === 'homecloud-base' && (
              <div className="image-card-foot">
                {!dashboard?.setup_complete && (
                  <span className="muted small">Complete setup (SSH key) before building.</span>
                )}
                <button
                  className="btn btn-primary"
                  disabled={building || !dashboard?.setup_complete}
                  onClick={build}
                >
                  {building ? 'Starting…' : img.built ? 'Rebuild image' : 'Build image'}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
