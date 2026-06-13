import { useCallback, useEffect, useState, type ReactNode } from 'react'
import type { SetupStatus } from '../api'
import { IconInfo, IconKey } from '../components/Icons'
import { useToast } from '../components/Toast'
import { CopyButton, Spinner } from '../components/ui'
import { useStore } from '../lib/store'

export function Settings() {
  const { api, refresh } = useStore()
  const toast = useToast()
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [newKeys, setNewKeys] = useState('')
  const [saving, setSaving] = useState(false)
  const [sshConfig, setSshConfig] = useState<string | null>(null)

  const load = useCallback(() => {
    api.setupStatus().then(setStatus).catch((e) => toast.error(String(e)))
  }, [api, toast])

  useEffect(() => {
    load()
  }, [load])

  async function save() {
    const keys = newKeys
      .split('\n')
      .map((k) => k.trim())
      .filter(Boolean)
    if (keys.length === 0) {
      toast.error('Paste at least one SSH public key')
      return
    }
    setSaving(true)
    try {
      await api.saveSetup(keys)
      toast.success('SSH keys saved — rebuild the base image to apply')
      setNewKeys('')
      load()
      refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  async function loadSshConfig() {
    try {
      const { config } = await api.sshConfig()
      setSshConfig(config || '# No registered instances yet')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  if (!status) {
    return (
      <div className="view">
        <div className="panel-empty">
          <Spinner /> Loading settings…
        </div>
      </div>
    )
  }

  return (
    <div className="view settings">
      <section className="panel">
        <header className="panel-head">
          <h2>SSH keys</h2>
          <span className="count-pill">{status.ssh_public_keys_count}</span>
        </header>

        <div className="panel-body">
          {status.ssh_public_keys.length > 0 ? (
            <div className="key-list">
              {status.ssh_public_keys.map((k, i) => (
                <div className="key-item" key={i}>
                  <span className="key-glyph">
                    <IconKey width={15} height={15} />
                  </span>
                  <code className="key-text">{k}</code>
                  <CopyButton value={k} />
                </div>
              ))}
            </div>
          ) : (
            <div className="inline-empty">
              <IconKey width={18} height={18} />
              <div>
                <strong>No keys registered</strong>
                <span className="muted small">Add a public key below to enable SSH access.</span>
              </div>
            </div>
          )}

          <label className="form-field">
            <span>Add public key(s)</span>
            <textarea
              className="key-input"
              rows={4}
              placeholder="ssh-ed25519 AAAA... user@host"
              value={newKeys}
              onChange={(e) => setNewKeys(e.target.value)}
            />
            <small className="hint">One key per line. Keys are baked into new images.</small>
          </label>

          <p className="note-line">
            <IconInfo width={14} height={14} />
            <span>{status.rebuild_note}</span>
          </p>
        </div>

        <div className="panel-actions">
          <button className="btn btn-primary" onClick={save} disabled={saving || !newKeys.trim()}>
            {saving ? 'Saving…' : 'Save keys'}
          </button>
        </div>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h2>Environment</h2>
        </header>
        <div className="info-list">
          <Row label="Proxmox node" value={status.proxmox_node || '—'} />
          <Row label="Storage" value={status.proxmox_storage || '—'} />
          <Row label="Tailnet" value={status.tailscale_tailnet || 'not configured'} />
          <Row label="VM SSH user" value={status.vm_ssh_user || '—'} />
        </div>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h2>SSH config export</h2>
          <button className="btn btn-ghost btn-sm" onClick={loadSshConfig}>
            Generate
          </button>
        </header>
        <div className="panel-body">
          {sshConfig === null ? (
            <p className="muted small">
              Generate a <code>~/.ssh/config</code> snippet for all registered instances.
            </p>
          ) : (
            <div className="ssh-config-out">
              <div className="ssh-config-bar">
                <CopyButton value={sshConfig} label="Copy" />
              </div>
              <pre className="code-block">{sshConfig}</pre>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  )
}
