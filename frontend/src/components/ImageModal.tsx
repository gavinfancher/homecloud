import { useState, type FormEvent } from 'react'
import type { ConfigFile, CustomImageBody, Image } from '../api'
import { IconClose, IconPlus, IconTrash } from './Icons'
import { useStore } from '../lib/store'
import { useToast } from './Toast'

const ID_RE = /^[a-z][a-z0-9-]{1,30}$/
const PATH_RE = /^\/\S/
const MODE_RE = /^0?[0-7]{3}$/

const LIMITS = {
  cores: { min: 1, max: 32 },
  memory_mb: { min: 512, max: 65536 },
  disk_gb: { min: 5, max: 2000 },
}

function emptyFile(): ConfigFile {
  return { path: '', content: '', permissions: '0644' }
}

/**
 * Create or edit a custom image definition.
 *
 * Saving only stores the definition — the caller decides whether to kick off a
 * build, since building takes minutes and boots a VM on the node.
 */
export function ImageModal({ image, onClose }: { image?: Image; onClose: () => void }) {
  const { api, cloudImages, refreshImages } = useStore()
  const toast = useToast()
  const editing = image != null

  const [id, setId] = useState(image?.id ?? '')
  const [name, setName] = useState(image?.name ?? '')
  const [description, setDescription] = useState(image?.description ?? '')
  const [cloudImageId, setCloudImageId] = useState(
    image?.cloud_image_id ?? cloudImages[0]?.id ?? '',
  )
  const [packageText, setPackageText] = useState((image?.packages ?? []).join('\n'))
  const [files, setFiles] = useState<ConfigFile[]>(image?.config_files ?? [])
  const [commandText, setCommandText] = useState((image?.run_commands ?? []).join('\n'))
  const [cores, setCores] = useState(image?.default_cores ?? 2)
  const [memoryMb, setMemoryMb] = useState(image?.default_memory_mb ?? 2048)
  const [diskGb, setDiskGb] = useState(image?.default_disk_gb ?? 10)
  const [busy, setBusy] = useState(false)

  const packages = packageText
    .split('\n')
    .map((p) => p.trim())
    .filter(Boolean)
  const runCommands = commandText
    .split('\n')
    .map((c) => c.trim())
    .filter(Boolean)

  const idValid = editing || ID_RE.test(id)
  const filesValid = files.every(
    (f) => PATH_RE.test(f.path) && (!f.permissions || MODE_RE.test(f.permissions)),
  )
  const canSubmit =
    idValid && name.trim().length > 0 && cloudImageId !== '' && filesValid && !busy

  function updateFile(index: number, patch: Partial<ConfigFile>) {
    setFiles((current) => current.map((f, i) => (i === index ? { ...f, ...patch } : f)))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)

    const body: CustomImageBody = {
      id: id.trim(),
      name: name.trim(),
      description: description.trim(),
      cloud_image_id: cloudImageId,
      packages,
      // Blank permissions mean "let cloud-init decide" — send null, not ''.
      config_files: files.map((f) => ({ ...f, permissions: f.permissions || null })),
      run_commands: runCommands,
      default_cores: cores,
      default_memory_mb: memoryMb,
      default_disk_gb: diskGb,
    }

    try {
      if (editing) {
        // The id is the primary key — PATCH takes everything except it.
        const changes: Partial<CustomImageBody> = { ...body }
        delete changes.id
        await api.updateImage(image.id, changes)
        toast.success(`Saved ${image.id}`)
      } else {
        await api.createImage(body)
        toast.success(`Created ${body.id} — build it when you're ready`)
      }
      await refreshImages()
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
      <div className="modal modal-wide" role="dialog" aria-label={editing ? 'Edit image' : 'New image'}>
        <header className="modal-head">
          <h2>{editing ? `Edit ${image.id}` : 'New image'}</h2>
          <button className="btn-icon" onClick={onClose} title="Close">
            <IconClose />
          </button>
        </header>

        <form className="modal-form" onSubmit={submit}>
          <div className="modal-body">
            {cloudImages.length === 0 && (
              <div className="callout callout-warn">
                No base cloud images available — the controller needs a database
                (set <code>DATABASE_URL</code>) before custom images can be defined.
              </div>
            )}

            {editing && image.built && (
              <div className="callout callout-warn">
                Changing packages, files, commands, or the base image drops this
                image back to draft — rebuild it to apply the changes.
              </div>
            )}

            <div className="form-row">
              <label className="form-field">
                <span>Image ID</span>
                <input
                  autoFocus={!editing}
                  placeholder="web-node"
                  value={id}
                  disabled={editing}
                  onChange={(e) => setId(e.target.value.toLowerCase())}
                />
                <small className={id && !idValid ? 'hint-bad' : 'hint'}>
                  lowercase, starts with a letter, 2–31 chars
                </small>
              </label>

              <label className="form-field">
                <span>Display name</span>
                <input
                  placeholder="Web Node"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
            </div>

            <label className="form-field">
              <span>Description</span>
              <input
                placeholder="Ubuntu with nginx and our TLS config"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>

            <div className="form-field">
              <span>Base cloud image</span>
              <div className="size-options">
                {cloudImages.map((c) => (
                  <button
                    type="button"
                    key={c.id}
                    className={`size-option ${cloudImageId === c.id ? 'selected' : ''}`}
                    onClick={() => setCloudImageId(c.id)}
                  >
                    <span className="size-name">{c.name}</span>
                    <span className="size-specs">
                      {c.arch} · login {c.ssh_user} ·{' '}
                      {c.imported ? `imported #${c.template_id}` : 'downloads on first build'}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <label className="form-field">
              <span>Packages</span>
              <textarea
                rows={5}
                spellCheck={false}
                placeholder={'nginx\nhtop\npostgresql-client'}
                value={packageText}
                onChange={(e) => setPackageText(e.target.value)}
              />
              <small className="hint">
                One per line — installed by cloud-init. {packages.length} package
                {packages.length === 1 ? '' : 's'}.
              </small>
            </label>

            <div className="form-field">
              <span>Config files</span>
              {files.length === 0 && (
                <small className="hint">
                  Nothing yet — add files to bake into every instance built from this image.
                </small>
              )}
              {files.map((file, i) => {
                const pathBad = file.path !== '' && !PATH_RE.test(file.path)
                const modeBad = !!file.permissions && !MODE_RE.test(file.permissions)
                return (
                  <div className="config-file" key={i}>
                    <div className="config-file-head">
                      <input
                        className={pathBad ? 'invalid' : ''}
                        placeholder="/etc/nginx/conf.d/app.conf"
                        value={file.path}
                        onChange={(e) => updateFile(i, { path: e.target.value })}
                      />
                      <input
                        className={`config-file-mode ${modeBad ? 'invalid' : ''}`}
                        placeholder="0644"
                        value={file.permissions ?? ''}
                        onChange={(e) => updateFile(i, { permissions: e.target.value })}
                      />
                      <input
                        className="config-file-owner"
                        placeholder="root:root"
                        value={file.owner ?? ''}
                        onChange={(e) => updateFile(i, { owner: e.target.value })}
                      />
                      <button
                        type="button"
                        className="btn-icon"
                        title="Remove file"
                        onClick={() => setFiles(files.filter((_, j) => j !== i))}
                      >
                        <IconTrash width={14} height={14} />
                      </button>
                    </div>
                    <textarea
                      rows={5}
                      spellCheck={false}
                      className="config-file-content"
                      placeholder="File contents…"
                      value={file.content}
                      onChange={(e) => updateFile(i, { content: e.target.value })}
                    />
                    {pathBad && <small className="hint-bad">Path must be absolute.</small>}
                    {modeBad && <small className="hint-bad">Mode must be octal, e.g. 0644.</small>}
                  </div>
                )
              })}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setFiles([...files, emptyFile()])}
              >
                <IconPlus width={14} height={14} /> Add config file
              </button>
            </div>

            <label className="form-field">
              <span>Run commands</span>
              <textarea
                rows={4}
                spellCheck={false}
                placeholder={'systemctl enable nginx\ncurl -LsSf https://astral.sh/uv/install.sh | sh'}
                value={commandText}
                onChange={(e) => setCommandText(e.target.value)}
              />
              <small className="hint">
                One shell command per line, run after packages are installed.
              </small>
            </label>

            <div className="form-row">
              <label className="form-field">
                <span>Default vCPUs</span>
                <input
                  type="number"
                  min={LIMITS.cores.min}
                  max={LIMITS.cores.max}
                  value={cores}
                  onChange={(e) => setCores(Number(e.target.value))}
                />
              </label>
              <label className="form-field">
                <span>Default memory (MB)</span>
                <input
                  type="number"
                  min={LIMITS.memory_mb.min}
                  max={LIMITS.memory_mb.max}
                  step={512}
                  value={memoryMb}
                  onChange={(e) => setMemoryMb(Number(e.target.value))}
                />
              </label>
              <label className="form-field">
                <span>Default disk (GB)</span>
                <input
                  type="number"
                  min={LIMITS.disk_gb.min}
                  max={LIMITS.disk_gb.max}
                  value={diskGb}
                  onChange={(e) => setDiskGb(Number(e.target.value))}
                />
              </label>
            </div>
          </div>

          <footer className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!canSubmit}>
              {busy ? 'Saving…' : editing ? 'Save changes' : 'Create image'}
            </button>
          </footer>
        </form>
      </div>
    </>
  )
}
