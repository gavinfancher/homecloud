import type { Job } from '../api'
import { titleCase } from './format'

const KINDS: Record<string, string> = {
  deploy_vm: 'Deploy',
  delete_vm: 'Delete',
  provision_vm: 'Reconfigure',
  scan_ports: 'Port scan',
  build_base_image: 'Base image build',
}

/** Short human name for a job type: `deploy_vm` → `Deploy`. */
export function jobKind(type: string): string {
  return KINDS[type] ?? titleCase(type)
}

type Bag = Record<string, unknown>

function num(v: unknown): number | undefined {
  return typeof v === 'number' ? v : undefined
}

function list(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
}

/** One line of what the job did (or will do), from its meta and result. */
export function jobDetails(job: Job): string {
  const meta = (job.meta ?? {}) as Bag
  const result = (job.result && typeof job.result === 'object' ? job.result : {}) as Bag
  const parts: string[] = []

  switch (job.type) {
    case 'deploy_vm': {
      const cores = num(result.cores) ?? num(meta.cores)
      const memMb = num(result.memory_mb)
      const mem = memMb !== undefined ? memMb / 1024 : num(meta.memory_gb)
      const disk = num(result.disk_gb) ?? num(meta.disk_gb)
      const specs = [
        cores !== undefined && `${cores} vCPU`,
        mem !== undefined && `${mem} GB`,
        disk !== undefined && `${disk} GB disk`,
      ].filter(Boolean)
      if (specs.length) parts.push(specs.join(' · '))
      else if (typeof meta.size_id === 'string') parts.push(meta.size_id)
      if (typeof result.tailscale_ip === 'string') parts.push(result.tailscale_ip)
      const roles = list(meta.roles)
      if (roles.length) parts.push(roles.join(', '))
      break
    }
    case 'provision_vm': {
      const roles = list(meta.roles)
      if (roles.length) parts.push(roles.join(', '))
      break
    }
    case 'delete_vm': {
      const vmid = num(result.vmid) ?? num(meta.vmid)
      if (vmid !== undefined) parts.push(`VM ${vmid}`)
      break
    }
    case 'scan_ports': {
      const count = num(result.count)
      if (count !== undefined) parts.push(`${count} listening port${count === 1 ? '' : 's'}`)
      else if (typeof meta.tailscale_ip === 'string' && meta.tailscale_ip) parts.push(meta.tailscale_ip)
      break
    }
    case 'build_base_image': {
      const vmid = num(result.template_vmid)
      if (vmid !== undefined) parts.push(`template ${vmid}`)
      break
    }
  }
  return parts.join(' · ')
}

/** The most useful single line about where a job is: its error, else its latest log. */
export function jobHeadline(job: Job): string {
  if (job.error) return job.error.split('\n')[0]
  const last = job.logs[job.logs.length - 1]
  return last ? last.message.trim() : ''
}

/** Treat `warning` and `warn` (both used by the backend) as one level. */
export function logLevel(level: string): 'info' | 'warn' | 'error' | 'debug' {
  if (level === 'warning' || level === 'warn') return 'warn'
  if (level === 'error' || level === 'critical') return 'error'
  if (level === 'debug') return 'debug'
  return 'info'
}

/** `42s`, `3m 12s`, `1h 4m`. */
export function duration(start?: string | null, end?: string | null): string {
  if (!start) return '—'
  const from = new Date(start).getTime()
  const to = end ? new Date(end).getTime() : Date.now()
  if (Number.isNaN(from) || Number.isNaN(to)) return '—'
  const s = Math.max(0, Math.round((to - from) / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

/** Offset of *ts* from *start* as `+m:ss`. */
export function elapsed(start: string | undefined, ts: string): string {
  if (!start) return ''
  const s = Math.max(0, Math.round((new Date(ts).getTime() - new Date(start).getTime()) / 1000))
  if (Number.isNaN(s)) return ''
  return `+${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function absoluteTime(iso?: string | null): string | undefined {
  if (!iso) return undefined
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? undefined : d.toLocaleString()
}
