import { useState, type ReactNode } from 'react'
import { statusTone, titleCase } from '../lib/format'
import { IconCheck, IconCopy } from './Icons'

export function StatusDot({ status }: { status?: string }) {
  return <span className={`dot dot-${statusTone(status)}`} aria-hidden />
}

export function Pill({ status, children }: { status?: string; children?: ReactNode }) {
  const tone = statusTone(status)
  return (
    <span className={`pill pill-${tone}`}>
      <StatusDot status={status} />
      {children ?? titleCase(status ?? 'unknown')}
    </span>
  )
}

export function CopyButton({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="copy-btn"
      title="Copy to clipboard"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value)
          setCopied(true)
          setTimeout(() => setCopied(false), 1400)
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      {copied ? <IconCheck width={14} height={14} /> : <IconCopy width={14} height={14} />}
      {label && <span>{copied ? 'Copied' : label}</span>}
    </button>
  )
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-label="loading" />
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="empty">
      {icon && <div className="empty-icon">{icon}</div>}
      <div className="empty-title">{title}</div>
      {hint && <p className="empty-hint">{hint}</p>}
      {action}
    </div>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="field-value">{children}</div>
    </div>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return <code className="mono">{children}</code>
}
