import { useState, type FormEvent } from 'react'
import { IconClose, IconSettings } from './Icons'
import { useStore } from '../lib/store'
import { useToast } from './Toast'

const LIMITS = {
  cores: { min: 1, max: 32, step: 1 },
  memory_gb: { min: 0.5, max: 64, step: 0.5 },
  disk_gb: { min: 10, max: 2000, step: 10 },
}

const CUSTOM = 'custom'

export function CreateInstanceModal({ onClose }: { onClose: () => void }) {
  const { api, sizes, images, dashboard, refresh, openJob } = useStore()
  const toast = useToast()
  const [name, setName] = useState('')
  const [sizeId, setSizeId] = useState(sizes[0]?.id ?? 'small')
  const [cores, setCores] = useState(2)
  const [memoryGb, setMemoryGb] = useState(4)
  const [diskGb, setDiskGb] = useState(40)
  const [busy, setBusy] = useState(false)

  const baseReady = dashboard?.base_image_built ?? true
  const nameValid = /^[a-z][a-z0-9-]{1,30}$/.test(name)
  const isCustom = sizeId === CUSTOM

  const inRange = (v: number, k: keyof typeof LIMITS) =>
    Number.isFinite(v) && v >= LIMITS[k].min && v <= LIMITS[k].max
  const customValid =
    inRange(cores, 'cores') && inRange(memoryGb, 'memory_gb') && inRange(diskGb, 'disk_gb')
  const canSubmit = nameValid && (!isCustom || customValid)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    try {
      const body = isCustom
        ? { name, size_id: CUSTOM, cores, memory_gb: memoryGb, disk_gb: diskGb }
        : { name, size_id: sizeId }
      const { job_id } = await api.deploy(body)
      toast.success(`Deploying ${name}…`)
      openJob(job_id)
      refresh()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const baseImage = images.find((i) => i.id === 'homecloud-base')

  return (
    <>
      <div className="modal-scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-label="Create instance">
        <header className="modal-head">
          <h2>Create instance</h2>
          <button className="btn-icon" onClick={onClose} title="Close">
            <IconClose />
          </button>
        </header>

        <form className="modal-body" onSubmit={submit}>
          {!baseReady && (
            <div className="callout callout-warn">
              The base image is not built yet. Build it from the Images tab first.
            </div>
          )}

          <label className="form-field">
            <span>Instance name</span>
            <input
              autoFocus
              placeholder="instance name"
              value={name}
              onChange={(e) => setName(e.target.value.toLowerCase())}
            />
            <small className={name && !nameValid ? 'hint-bad' : 'hint'}>
              lowercase, starts with a letter, 2–31 chars
            </small>
          </label>

          <div className="form-field">
            <span>Size</span>
            <div className="size-options">
              {sizes.map((s) => (
                <button
                  type="button"
                  key={s.id}
                  className={`size-option ${sizeId === s.id ? 'selected' : ''}`}
                  onClick={() => setSizeId(s.id)}
                >
                  <span className="size-name">{s.label}</span>
                  <span className="size-specs">
                    {s.cores} vCPU · {s.memory_gb} GB RAM · {s.disk_gb} GB disk
                  </span>
                </button>
              ))}
              <button
                type="button"
                className={`size-option ${isCustom ? 'selected' : ''}`}
                onClick={() => setSizeId(CUSTOM)}
              >
                <span className="size-name">
                  <IconSettings width={14} height={14} /> Custom
                </span>
                <span className="size-specs">
                  {isCustom
                    ? `${cores} vCPU · ${memoryGb} GB RAM · ${diskGb} GB disk`
                    : 'Set your own vCPU, memory, and disk'}
                </span>
              </button>
            </div>
          </div>

          {isCustom && (
            <div className="custom-specs">
              <NumberField
                label="vCPUs"
                unit="cores"
                value={cores}
                limits={LIMITS.cores}
                onChange={setCores}
              />
              <NumberField
                label="Memory"
                unit="GB"
                value={memoryGb}
                limits={LIMITS.memory_gb}
                onChange={setMemoryGb}
              />
              <NumberField
                label="Disk"
                unit="GB"
                value={diskGb}
                limits={LIMITS.disk_gb}
                onChange={setDiskGb}
              />
            </div>
          )}

          {baseImage && (
            <div className="form-note">
              Image: <code>{baseImage.name}</code> — {baseImage.description}
            </div>
          )}

          <footer className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={busy || !canSubmit}>
              {busy ? 'Creating…' : 'Create instance'}
            </button>
          </footer>
        </form>
      </div>
    </>
  )
}

function NumberField({
  label,
  unit,
  value,
  limits,
  onChange,
}: {
  label: string
  unit: string
  value: number
  limits: { min: number; max: number; step: number }
  onChange: (v: number) => void
}) {
  const clamp = (v: number) => Math.min(limits.max, Math.max(limits.min, v))
  const valid = Number.isFinite(value) && value >= limits.min && value <= limits.max
  return (
    <label className={`num-field ${valid ? '' : 'invalid'}`}>
      <span className="num-label">{label}</span>
      <div className="num-control">
        <button
          type="button"
          className="num-step"
          onClick={() => onChange(clamp(Number((value - limits.step).toFixed(1))))}
          aria-label={`Decrease ${label}`}
        >
          −
        </button>
        <input
          type="number"
          value={Number.isFinite(value) ? value : ''}
          min={limits.min}
          max={limits.max}
          step={limits.step}
          onChange={(e) => onChange(e.target.value === '' ? NaN : Number(e.target.value))}
        />
        <button
          type="button"
          className="num-step"
          onClick={() => onChange(clamp(Number((value + limits.step).toFixed(1))))}
          aria-label={`Increase ${label}`}
        >
          +
        </button>
      </div>
      <small className="num-hint">
        {unit} · {limits.min}–{limits.max}
      </small>
    </label>
  )
}
