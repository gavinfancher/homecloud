import { useEffect, useState, type ReactNode } from 'react'
import type { BaseImageBuild, BaseImageConfig, BuildStatus } from '../api'
import { IconImages, IconInfo } from '../components/Icons'
import { useToast } from '../components/Toast'
import { CopyButton, EmptyState, Field, Mono, Pill, Spinner } from '../components/ui'
import { baseVersion, relativeTime } from '../lib/format'
import { useStore } from '../lib/store'

type Draft = Pick<BaseImageConfig, 'image_url' | 'packages' | 'extra_user_data'>

const STATUS_PILL: Record<BuildStatus, { status: string; label: string }> = {
  building: { status: 'in_progress', label: 'Building' },
  ready: { status: 'completed', label: 'Ready' },
  failed: { status: 'failed', label: 'Failed' },
}

const fileName = (url: string) => url.split('/').pop() || url
const clean = (d: Draft): Draft => ({
  ...d,
  image_url: d.image_url.trim(),
  packages: d.packages.map((p) => p.trim()).filter(Boolean),
})
const sameDraft = (a: Draft, b: Draft) => JSON.stringify(clean(a)) === JSON.stringify(clean(b))

export function BaseImage() {
  const { api, baseImage, refreshBaseImage, dashboard, openJob } = useStore()
  const toast = useToast()
  const [edited, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState<'save' | 'build' | null>(null)

  const config = baseImage?.config
  const draft: Draft | null =
    edited ??
    (config
      ? {
          image_url: config.image_url,
          packages: config.packages,
          extra_user_data: config.extra_user_data,
        }
      : null)
  const dirty = !!(draft && config && !sameDraft(draft, config))
  const builds = baseImage?.builds ?? []
  const building = builds.some((b) => b.status === 'building')

  // Follow a running build until it settles.
  useEffect(() => {
    if (!building) return
    const t = setInterval(refreshBaseImage, 4000)
    return () => clearInterval(t)
  }, [building, refreshBaseImage])

  const jobFor = (b: BaseImageBuild) =>
    dashboard?.recent_jobs.find(
      (j) => j.type === 'build_base_image' && Number(j.meta?.build_id) === b.id,
    )

  async function save(): Promise<boolean> {
    if (!draft) return false
    setBusy('save')
    try {
      await api.saveBaseImage(clean(draft))
      await refreshBaseImage()
      setDraft(null)
      toast.success('Base image definition saved')
      return true
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setBusy(null)
    }
  }

  async function build() {
    // A build snapshots the *saved* definition, so save pending edits first.
    if (dirty && !(await save())) return
    setBusy('build')
    try {
      const { job_id, build_id } = await api.buildBaseImage()
      toast.success(`Building base image ${baseVersion(build_id)}…`)
      openJob(job_id)
      refreshBaseImage()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  if (!baseImage || !draft) {
    return (
      <div className="view">
        <div className="panel-empty">
          <Spinner /> Loading base image…
        </div>
      </div>
    )
  }

  const current = baseImage.current

  return (
    <div className="view">
      <div className="toolbar">
        <p className="muted small toolbar-note">
          One Ubuntu cloud image definition every instance is cloned from. Each build snapshots
          the definition and your SSH keys into a new versioned template; new instances use the
          newest ready version, and existing instances never change.
        </p>
        <div className="spacer" />
        <button className="btn btn-ghost" onClick={refreshBaseImage}>
          Refresh
        </button>
      </div>

      <section className="panel">
        <header className="panel-head">
          <h2>Current version</h2>
          {current && <Pill status="completed">{baseVersion(current.id)}</Pill>}
        </header>
        {current ? (
          <div className="panel-body">
            <div>
              <Field label="Template">
                <Mono>#{current.template_vmid ?? '—'}</Mono>
              </Field>
              <Field label="Built">
                <span title={current.built_at ?? undefined}>{relativeTime(current.built_at)}</span>
              </Field>
              <Field label="Image">
                <span title={current.image_url}>
                  <Mono>{fileName(current.image_url)}</Mono>
                </span>
              </Field>
              <Field label="SHA-256">
                {current.sha256 ? (
                  <span className="copyrow" title={current.sha256}>
                    <Mono>{current.sha256.slice(0, 12)}</Mono>
                    <CopyButton value={current.sha256} />
                  </span>
                ) : (
                  '—'
                )}
              </Field>
              <Field label="Packages">
                {current.packages.length ? current.packages.join(', ') : '—'}
              </Field>
              <Field label="SSH keys">{current.ssh_keys.length}</Field>
            </div>
          </div>
        ) : (
          <EmptyState
            icon={<IconImages width={32} height={32} />}
            title={building ? 'First build in progress' : 'No base image built yet'}
            hint="Instances can't be created until a build succeeds. Review the definition below and build the first version."
          />
        )}
      </section>

      <section className="panel">
        <header className="panel-head">
          <h2>Definition</h2>
          {dirty && <span className="muted small">unsaved changes</span>}
        </header>
        <div className="panel-body">
          <label className="form-field">
            <span>Cloud image URL</span>
            <input
              spellCheck={false}
              value={draft.image_url}
              onChange={(e) => setDraft({ ...draft, image_url: e.target.value })}
            />
            <small className="hint">
              An Ubuntu cloud image (<code>.img</code> or <code>.qcow2</code>) from a dated
              release directory; its checksum is checked against that directory's SHA256SUMS.
            </small>
          </label>

          <label className="form-field">
            <span>Packages</span>
            <textarea
              rows={Math.min(10, Math.max(3, draft.packages.length + 1))}
              spellCheck={false}
              value={draft.packages.join('\n')}
              // Blank lines are kept while typing; they are dropped on save.
              onChange={(e) => setDraft({ ...draft, packages: e.target.value.split('\n') })}
            />
            <small className="hint">
              One apt package per line, baked into the image. The QEMU guest agent and Tailscale
              are always included.
            </small>
          </label>

          <label className="form-field">
            <span>Extra user-data</span>
            <textarea
              rows={8}
              spellCheck={false}
              placeholder={'# extra #cloud-config, e.g.\ntimezone: America/New_York'}
              value={draft.extra_user_data}
              onChange={(e) => setDraft({ ...draft, extra_user_data: e.target.value })}
            />
            <small className="hint">
              Extra <code>#cloud-config</code> (a YAML mapping) merged into the bake. The keys{' '}
              <code>users</code>, <code>user</code>, <code>hostname</code> and <code>fqdn</code>{' '}
              are reserved.
            </small>
          </label>

          <p className="note-line">
            <IconInfo width={14} height={14} />
            <span>
              Changes apply to the next build only. Builds also pick up the SSH keys from
              Settings at the moment they start.
            </span>
          </p>
        </div>
        <div className="panel-actions" style={{ gap: 8 }}>
          {dirty && (
            <button className="btn btn-ghost" disabled={!!busy} onClick={() => setDraft(null)}>
              Discard
            </button>
          )}
          <button className="btn" disabled={!!busy || !dirty} onClick={save}>
            {busy === 'save' ? 'Saving…' : 'Save'}
          </button>
          <button
            className="btn btn-primary"
            disabled={!!busy || building}
            title={building ? 'A build is already running' : undefined}
            onClick={build}
          >
            {busy === 'build' ? 'Starting…' : dirty ? 'Save & build new version' : 'Build new version'}
          </button>
        </div>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h2>Builds</h2>
          <span className="count-pill">{builds.length}</span>
        </header>
        {builds.length === 0 ? (
          <div className="panel-empty">
            <IconImages width={28} height={28} />
            <span>No builds yet</span>
          </div>
        ) : (
          <table className="jobs-table">
            <thead>
              <tr>
                <th>Version</th>
                <th>Status</th>
                <th>Template</th>
                <th>Created</th>
                <th>Built</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {builds.map((b) => (
                <BuildRow
                  key={b.id}
                  build={b}
                  current={b.id === current?.id}
                  jobId={jobFor(b)?.id}
                  onOpenJob={openJob}
                />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

function BuildRow({
  build,
  current,
  jobId,
  onOpenJob,
}: {
  build: BaseImageBuild
  current: boolean
  jobId?: string
  onOpenJob: (id: string) => void
}) {
  const pill = STATUS_PILL[build.status] ?? { status: build.status, label: build.status }
  let details: ReactNode = <span className="muted">{build.packages.length} packages</span>
  if (build.error) details = <div className="image-error hint-bad">{build.error}</div>

  return (
    <tr
      className={jobId ? 'job-row' : undefined}
      onClick={jobId ? () => onOpenJob(jobId) : undefined}
      title={jobId ? 'Open build log' : undefined}
    >
      <td>
        <strong>{baseVersion(build.id)}</strong>
        {current && <span className="role-tag">current</span>}
      </td>
      <td>
        <Pill status={pill.status}>{pill.label}</Pill>
      </td>
      <td className="muted">{build.template_vmid != null ? `#${build.template_vmid}` : '—'}</td>
      <td className="muted" title={build.created_at ?? undefined}>
        {relativeTime(build.created_at)}
      </td>
      <td className="muted" title={build.built_at ?? undefined}>
        {build.built_at ? relativeTime(build.built_at) : '—'}
      </td>
      <td>{details}</td>
    </tr>
  )
}
