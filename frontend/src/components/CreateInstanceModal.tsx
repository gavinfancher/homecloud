import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import type { RoleSelection } from '../api'
import { IconClose, IconSettings } from './Icons'
import { RoleEditor, defaultSelection, selectionValid } from './RoleEditor'
import { useStore } from '../lib/store'
import { useToast } from './Toast'

const LIMITS = {
  cores: { min: 1, max: 32, step: 1 },
  memory_gb: { min: 0.5, max: 64, step: 0.5 },
  disk_gb: { min: 10, max: 2000, step: 10 },
}

const CUSTOM = 'custom'

export function CreateInstanceModal({ onClose }: { onClose: () => void }) {
  const { api, sizes, sources, roles, refresh, openJob } = useStore()
  const toast = useToast()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [sizeId, setSizeId] = useState(sizes[0]?.id ?? 'small')
  const [cores, setCores] = useState(2)
  const [memoryGb, setMemoryGb] = useState(4)
  const [diskGb, setDiskGb] = useState(40)
  const imported = sources.filter((s) => s.imported)
  // Sources and roles can arrive after the modal opens; until the user picks,
  // follow the first imported source and the catalog defaults.
  const [pickedSource, setSourceId] = useState<string | null>(null)
  const sourceId = pickedSource ?? imported[0]?.id ?? ''
  const [edited, setSelection] = useState<RoleSelection[] | null>(null)
  const selection = edited ?? defaultSelection(roles)
  const [busy, setBusy] = useState(false)

  const nameValid = /^[a-z][a-z0-9-]{1,30}$/.test(name)
  const isCustom = sizeId === CUSTOM

  const inRange = (v: number, k: keyof typeof LIMITS) =>
    Number.isFinite(v) && v >= LIMITS[k].min && v <= LIMITS[k].max
  const customValid =
    inRange(cores, 'cores') && inRange(memoryGb, 'memory_gb') && inRange(diskGb, 'disk_gb')
  const canSubmit =
    nameValid && (!isCustom || customValid) && sourceId !== '' && selectionValid(selection)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    try {
      const size = isCustom
        ? { size_id: CUSTOM, cores, memory_gb: memoryGb, disk_gb: diskGb }
        : { size_id: sizeId }
      const { job_id } = await api.deploy({ name, ...size, source_id: sourceId, roles: selection })
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

  return (
    <>
      <div className="modal-scrim" onClick={onClose} />
      <div className="modal modal-wide" role="dialog" aria-label="Create instance">
        <header className="modal-head">
          <h2>Create instance</h2>
          <button className="btn-icon" onClick={onClose} title="Close">
            <IconClose />
          </button>
        </header>

        <form className="modal-form" onSubmit={submit}>
          <div className="modal-body">
          {imported.length === 0 && (
            <div className="callout callout-warn">
              <div>No source image is imported yet. Import one before creating instances.</div>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  onClose()
                  navigate('/sources')
                }}
              >
                Go to Sources
              </button>
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

          {imported.length > 0 && (
            <div className="form-field">
              <span>Source image</span>
              <div className="size-options">
                {imported.map((src) => (
                  <button
                    type="button"
                    key={src.id}
                    className={`size-option ${sourceId === src.id ? 'selected' : ''}`}
                    onClick={() => setSourceId(src.id)}
                  >
                    <span className="size-name">{src.name}</span>
                    <span className="size-specs">
                      {src.arch} · template #{src.template_id}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="form-field">
            <span>Configure</span>
            <small className="hint">
              Ansible roles applied after the VM boots. You can change them later from the
              instance.
            </small>
            <RoleEditor catalog={roles} value={selection} onChange={setSelection} />
          </div>
          </div>

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
