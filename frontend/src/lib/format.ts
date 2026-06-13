export function relativeTime(iso?: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Date.now() - then
  const s = Math.round(diff / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  return `${d}d ago`
}

export function clock(iso?: string): string {
  if (!iso) return ''
  return iso.slice(11, 19)
}

export function titleCase(s: string): string {
  return s.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Map a job/VM status to a semantic tone used for pills and dots. */
export function statusTone(status?: string): 'ok' | 'warn' | 'danger' | 'busy' | 'idle' {
  switch (status) {
    case 'running':
    case 'completed':
      return 'ok'
    case 'paused':
    case 'cancelled':
      return 'warn'
    case 'stopped':
    case 'failed':
      return 'danger'
    case 'pending':
    case 'in_progress':
    case 'running_job':
      return 'busy'
    default:
      return 'idle'
  }
}
