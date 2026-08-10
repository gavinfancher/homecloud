import { useState } from 'react'
import type { Image } from '../api'
import { IconImages, IconPlus, IconTrash } from '../components/Icons'
import { ImageModal } from '../components/ImageModal'
import { useToast } from '../components/Toast'
import { EmptyState, Pill } from '../components/ui'
import { useStore } from '../lib/store'

const STATUS_TONE: Record<string, string> = {
  built: 'completed',
  building: 'in_progress',
  failed: 'failed',
  draft: 'paused',
}

const STATUS_LABEL: Record<string, string> = {
  built: 'Built',
  building: 'Building',
  failed: 'Failed',
  draft: 'Not built',
}

export function Images() {
  const { images, cloudImages, api, openJob, refreshImages } = useStore()
  const toast = useToast()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Image | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const canCreate = cloudImages.length > 0

  async function build(image: Image) {
    setBusyId(image.id)
    try {
      const { job_id } =
        image.kind === 'builtin' ? await api.buildBaseImage() : await api.buildImage(image.id)
      toast.success(`Building ${image.id}…`)
      openJob(job_id)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
      refreshImages()
    }
  }

  async function remove(image: Image) {
    if (!confirm(`Delete the image definition "${image.id}"? The Proxmox template is kept.`)) return
    setBusyId(image.id)
    try {
      await api.deleteImage(image.id)
      toast.success(`Deleted ${image.id}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
      refreshImages()
    }
  }

  return (
    <div className="view">
      <div className="toolbar">
        <div className="spacer" />
        <button className="btn btn-ghost" onClick={refreshImages}>
          Refresh
        </button>
        <button
          className="btn btn-primary"
          disabled={!canCreate}
          title={canCreate ? undefined : 'Custom images need a controller database'}
          onClick={() => setCreating(true)}
        >
          <IconPlus width={16} height={16} /> New image
        </button>
      </div>

      {images.length === 0 ? (
        <EmptyState
          icon={<IconImages width={32} height={32} />}
          title="No images registered"
          hint="Images define the template used to deploy instances."
        />
      ) : (
        <div className="image-grid">
          {images.map((img) => (
            <ImageCard
              key={img.id}
              image={img}
              busy={busyId === img.id}
              onBuild={() => build(img)}
              onEdit={() => setEditing(img)}
              onDelete={() => remove(img)}
            />
          ))}
        </div>
      )}

      {creating && <ImageModal onClose={() => setCreating(false)} />}
      {editing && <ImageModal image={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function ImageCard({
  image,
  busy,
  onBuild,
  onEdit,
  onDelete,
}: {
  image: Image
  busy: boolean
  onBuild: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const { dashboard, cloudImages } = useStore()
  const isCustom = image.kind === 'custom'
  const base = cloudImages.find((c) => c.id === image.cloud_image_id)
  const setupDone = dashboard?.setup_complete ?? false
  const building = image.status === 'building'

  return (
    <div className="image-card">
      <div className="image-card-head">
        <div className="image-icon">
          <IconImages width={20} height={20} />
        </div>
        <div className="image-titles">
          <h3>{image.name}</h3>
          <code className="muted">{image.id}</code>
        </div>
        <Pill status={STATUS_TONE[image.status] ?? 'paused'}>
          {STATUS_LABEL[image.status] ?? image.status}
        </Pill>
      </div>

      {image.description && <p className="image-desc">{image.description}</p>}

      <div className="image-specs">
        <span>{image.default_cores} vCPU</span>
        <span>{(image.default_memory_mb / 1024).toFixed(0)} GB RAM</span>
        <span>{image.default_disk_gb} GB disk</span>
        {base && <span>{base.name}</span>}
        {image.template_id != null && <span>template #{image.template_id}</span>}
      </div>

      {image.packages.length > 0 && (
        <div className="pkg-list">
          {image.packages.slice(0, 12).map((p) => (
            <span className="pkg" key={p}>
              {p}
            </span>
          ))}
          {image.packages.length > 12 && (
            <span className="pkg muted">+{image.packages.length - 12} more</span>
          )}
        </div>
      )}

      {image.config_files.length > 0 && (
        <div className="pkg-list">
          {image.config_files.slice(0, 6).map((f) => (
            <span className="pkg pkg-file" key={f.path} title={f.path}>
              {f.path}
            </span>
          ))}
          {image.config_files.length > 6 && (
            <span className="pkg muted">+{image.config_files.length - 6} more</span>
          )}
        </div>
      )}

      {image.status === 'failed' && image.build_error && (
        <div className="callout callout-warn image-error">{image.build_error}</div>
      )}

      <div className="image-card-foot">
        {!setupDone && <span className="muted small">Complete setup (SSH key) before building.</span>}
        {isCustom && (
          <>
            <button className="btn btn-ghost btn-sm" disabled={busy || building} onClick={onEdit}>
              Edit
            </button>
            <button
              className="btn btn-ghost btn-sm btn-danger"
              disabled={busy || building}
              onClick={onDelete}
              title="Delete image definition"
            >
              <IconTrash width={14} height={14} />
            </button>
          </>
        )}
        <button
          className="btn btn-primary"
          disabled={busy || building || !setupDone}
          onClick={onBuild}
        >
          {busy ? 'Starting…' : building ? 'Building…' : image.built ? 'Rebuild image' : 'Build image'}
        </button>
      </div>
    </div>
  )
}
