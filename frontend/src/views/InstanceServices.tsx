import { useState, type FormEvent } from 'react'
import type { VM } from '../api'
import { IconExternal, IconGlobe, IconLock, IconPlus, IconTrash } from '../components/Icons'
import { useToast } from '../components/Toast'
import { Mono } from '../components/ui'
import { useStore } from '../lib/store'

export function InstanceServices({ vm }: { vm: VM }) {
  const { api, refresh } = useStore()
  const toast = useToast()
  const [adding, setAdding] = useState(false)
  const [service, setService] = useState('')
  const [port, setPort] = useState<number | ''>(vm.ports_seen?.[0]?.port ?? '')
  const [isPublic, setIsPublic] = useState(false)
  const [busy, setBusy] = useState(false)

  const services = vm.web ?? []
  const seen = vm.ports_seen ?? []
  const serviceValid = /^[a-z][a-z0-9-]{1,30}$/.test(service)
  const portKnown = typeof port === 'number' && seen.some((p) => p.port === port)

  async function publish(e: FormEvent) {
    e.preventDefault()
    if (!serviceValid || typeof port !== 'number') return
    setBusy(true)
    try {
      await api.publish(vm.name, service, port, isPublic, !portKnown)
      toast.success(`Published ${service} → :${port}`)
      setService('')
      setAdding(false)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function unpublish(name: string) {
    if (!confirm(`Unpublish ${name}?`)) return
    try {
      await api.unpublish(vm.name, name)
      toast.success(`Unpublished ${name}`)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <section className="detail-block services-block">
      <div className="block-head">
        <h4>Web services</h4>
        <button className="btn btn-ghost btn-sm" onClick={() => setAdding((v) => !v)}>
          <IconPlus width={14} height={14} /> Publish
        </button>
      </div>

      {services.length === 0 && !adding && (
        <p className="muted small">No services published. Expose a port to the web or tailnet.</p>
      )}

      {services.length > 0 && (
        <div className="service-list">
          {services.map((s) => (
            <div className="service-item" key={s.service}>
              <span className={`service-icon ${s.public ? 'pub' : 'priv'}`}>
                {s.public ? <IconGlobe width={15} height={15} /> : <IconLock width={15} height={15} />}
              </span>
              <div className="service-main">
                <span className="service-name">{s.service}</span>
                <a
                  className="service-host"
                  href={`https://${s.public_host}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {s.public_host} <IconExternal width={12} height={12} />
                </a>
              </div>
              <span className={`tag ${s.public ? 'tag-pub' : 'tag-priv'}`}>
                {s.public ? 'Public' : 'Private'}
              </span>
              <Mono>:{s.port}</Mono>
              <button
                className="btn-icon danger"
                title="Unpublish"
                onClick={() => unpublish(s.service)}
              >
                <IconTrash width={15} height={15} />
              </button>
            </div>
          ))}
        </div>
      )}

      {adding && (
        <form className="publish-form" onSubmit={publish}>
          <div className="publish-row">
            <label className="form-field">
              <span>Service name</span>
              <input
                placeholder="e.g. grafana"
                value={service}
                onChange={(e) => setService(e.target.value.toLowerCase())}
              />
            </label>
            <label className="form-field port-field">
              <span>Port</span>
              {seen.length > 0 ? (
                <select
                  value={port}
                  onChange={(e) => setPort(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">Select…</option>
                  {seen.map((p) => (
                    <option key={p.port} value={p.port}>
                      {p.port}
                      {p.proc ? ` (${p.proc})` : ''}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  placeholder="8080"
                  value={port}
                  onChange={(e) => setPort(e.target.value ? Number(e.target.value) : '')}
                />
              )}
            </label>
          </div>

          <label className="toggle-row">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
            />
            <span>
              <strong>Expose to the public internet</strong>
              <small className="muted">
                {isPublic
                  ? 'Creates a Cloudflare route reachable off-tailnet.'
                  : 'Private: reachable only on the tailnet.'}
              </small>
            </span>
          </label>

          {typeof port === 'number' && !portKnown && (
            <p className="hint-bad small">
              Port {port} was not in the last scan — it will be force-published.
            </p>
          )}

          <div className="publish-actions">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(false)}>
              Cancel
            </button>
            <button className="btn btn-primary btn-sm" disabled={busy || !serviceValid || !port}>
              {busy ? 'Publishing…' : 'Publish'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
