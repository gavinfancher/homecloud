import type { RoleFile, RoleSelection, RoleSpec, RoleVar, RoleVarValue } from '../api'
import { IconPlus, IconTrash } from './Icons'

const PATH_RE = /^\/\S/
const MODE_RE = /^0?[0-7]{3,4}$/

function defaultValue(v: RoleVar): RoleVarValue {
  if (v.default != null) return structuredClone(v.default)
  switch (v.type) {
    case 'bool':
      return false
    case 'list':
    case 'files':
      return []
    default:
      return ''
  }
}

function roleDefaults(role: RoleSpec): RoleSelection {
  return { id: role.id, vars: Object.fromEntries(role.vars.map((v) => [v.name, defaultValue(v)])) }
}

/** The catalog's pre-selected roles with their default variables. */
// eslint-disable-next-line react-refresh/only-export-components
export function defaultSelection(catalog: RoleSpec[]): RoleSelection[] {
  return catalog.filter((r) => r.default_enabled).map(roleDefaults)
}

/**
 * Fill a stored selection out against the current catalog: required roles are
 * added and variables the catalog gained since are given their defaults.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function normalizeSelection(
  catalog: RoleSpec[],
  selection: RoleSelection[],
): RoleSelection[] {
  const byId = new Map(selection.map((s) => [s.id, s]))
  return catalog
    .filter((r) => r.required || byId.has(r.id))
    .map((r) => {
      const base = roleDefaults(r)
      const given = byId.get(r.id)
      return given ? { id: r.id, vars: { ...base.vars, ...given.vars } } : base
    })
}

// eslint-disable-next-line react-refresh/only-export-components
export function selectionValid(selection: RoleSelection[]): boolean {
  return selection.every((s) =>
    Object.values(s.vars).every(
      (value) =>
        !Array.isArray(value) ||
        value.every(
          (item) =>
            typeof item === 'string' ||
            (PATH_RE.test(item.path) && (!item.mode || MODE_RE.test(item.mode))),
        ),
    ),
  )
}

/** Toggle roles from the catalog on and off and fill in their variables. */
export function RoleEditor({
  catalog,
  value,
  onChange,
}: {
  catalog: RoleSpec[]
  value: RoleSelection[]
  onChange: (next: RoleSelection[]) => void
}) {
  const selected = new Map(value.map((s) => [s.id, s]))

  function toggle(role: RoleSpec) {
    if (role.required) return
    const next = selected.has(role.id)
      ? value.filter((s) => s.id !== role.id)
      : [...value, roleDefaults(role)]
    // Keep the play order stable: catalog order, not click order.
    onChange(catalog.flatMap((r) => next.filter((s) => s.id === r.id)))
  }

  function setVar(roleId: string, name: string, v: RoleVarValue) {
    onChange(
      value.map((s) => (s.id === roleId ? { ...s, vars: { ...s.vars, [name]: v } } : s)),
    )
  }

  if (catalog.length === 0) {
    return <small className="hint">No roles available from the controller.</small>
  }

  return (
    <div className="role-list">
      {catalog.map((role) => {
        const sel = selected.get(role.id)
        return (
          <div className={`role-card ${sel ? 'selected' : ''}`} key={role.id}>
            <label className="role-head">
              <input
                type="checkbox"
                checked={!!sel}
                disabled={role.required}
                onChange={() => toggle(role)}
              />
              <span className="role-titles">
                <span className="size-name">
                  {role.label}
                  {role.required && <span className="role-tag">required</span>}
                </span>
                <span className="size-specs">{role.description}</span>
              </span>
            </label>
            {sel && role.vars.length > 0 && (
              <div className="role-vars">
                {role.vars.map((v) => (
                  <VarField
                    key={v.name}
                    spec={v}
                    value={sel.vars[v.name] ?? defaultValue(v)}
                    onChange={(next) => setVar(role.id, v.name, next)}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function VarField({
  spec,
  value,
  onChange,
}: {
  spec: RoleVar
  value: RoleVarValue
  onChange: (v: RoleVarValue) => void
}) {
  switch (spec.type) {
    case 'bool':
      return (
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={value === true}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span>
            {spec.label}
            {spec.description && <small className="muted">{spec.description}</small>}
          </span>
        </label>
      )
    case 'list': {
      const items = value as string[]
      return (
        <label className="form-field">
          <span>{spec.label}</span>
          <textarea
            rows={Math.min(8, Math.max(3, items.length + 1))}
            spellCheck={false}
            value={items.join('\n')}
            // Blank lines are kept while typing; the controller drops them.
            onChange={(e) => onChange(e.target.value.split('\n'))}
          />
          <small className="hint">{spec.description || 'One per line.'}</small>
        </label>
      )
    }
    case 'files':
      return <FilesField label={spec.label} files={value as RoleFile[]} onChange={onChange} />
    case 'text':
      return (
        <label className="form-field">
          <span>{spec.label}</span>
          <textarea
            rows={4}
            spellCheck={false}
            value={value as string}
            onChange={(e) => onChange(e.target.value)}
          />
          {spec.description && <small className="hint">{spec.description}</small>}
        </label>
      )
    default:
      return (
        <label className="form-field">
          <span>{spec.label}</span>
          <input value={value as string} onChange={(e) => onChange(e.target.value)} />
          {spec.description && <small className="hint">{spec.description}</small>}
        </label>
      )
  }
}

function FilesField({
  label,
  files,
  onChange,
}: {
  label: string
  files: RoleFile[]
  onChange: (files: RoleFile[]) => void
}) {
  function update(index: number, patch: Partial<RoleFile>) {
    onChange(files.map((f, i) => (i === index ? { ...f, ...patch } : f)))
  }

  return (
    <div className="form-field">
      <span>{label}</span>
      {files.map((file, i) => {
        const pathBad = file.path !== '' && !PATH_RE.test(file.path)
        const modeBad = !!file.mode && !MODE_RE.test(file.mode)
        return (
          <div className="config-file" key={i}>
            <div className="config-file-head">
              <input
                className={pathBad ? 'invalid' : ''}
                placeholder="/etc/nginx/conf.d/app.conf"
                value={file.path}
                onChange={(e) => update(i, { path: e.target.value })}
              />
              <input
                className={`config-file-mode ${modeBad ? 'invalid' : ''}`}
                placeholder="0644"
                value={file.mode ?? ''}
                onChange={(e) => update(i, { mode: e.target.value })}
              />
              <input
                className="config-file-owner"
                placeholder="root:root"
                value={file.owner ?? ''}
                onChange={(e) => update(i, { owner: e.target.value })}
              />
              <button
                type="button"
                className="btn-icon"
                title="Remove file"
                onClick={() => onChange(files.filter((_, j) => j !== i))}
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
              onChange={(e) => update(i, { content: e.target.value })}
            />
            {(pathBad || file.path === '') && (
              <small className="hint-bad">Path must be absolute.</small>
            )}
            {modeBad && <small className="hint-bad">Mode must be octal, e.g. 0644.</small>}
          </div>
        )
      })}
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={() => onChange([...files, { path: '', content: '', mode: '0644' }])}
      >
        <IconPlus width={14} height={14} /> Add file
      </button>
    </div>
  )
}
