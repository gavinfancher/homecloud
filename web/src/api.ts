// Typed client for the homecloud controller API. All calls attach the Clerk
// session token as a Bearer credential (no-op in dev when auth is disabled).

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export type TokenGetter = () => Promise<string | null>

export interface VM {
  vmid: number
  name: string
  status: string
  cores?: number
  memory_gb?: number
  disk_gb?: number
  hostname?: string
  tailscale_ip?: string
  ssh?: string
  web?: WebService[]
}

export interface WebService {
  service: string
  port: number
  public_host: string
  public: boolean
}

export interface Size {
  id: string
  label: string
  cores: number
  memory_gb: number
  disk_gb: number
}

export interface JobLog {
  ts: string
  level: string
  message: string
}

export interface Job {
  id: string
  type: string
  label: string
  status: string
  logs: JobLog[]
  result: unknown
  error: string | null
  cancel_requested?: boolean
}

export interface Dashboard {
  setup_complete: boolean
  base_image_built: boolean
  tailscale_tailnet: string
  proxmox_node: string
  stats: { total_vms: number; running: number; stopped: number; templates: number }
  recent_jobs: Job[]
}

export interface DeployBody {
  name: string
  size_id?: string
  cores?: number
  memory_gb?: number
  disk_gb?: number
  image_id?: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function createApi(getToken: TokenGetter) {
  async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
    // A Clerk token hiccup must not block data loading — attach it when we can,
    // otherwise fall through (the API rejects with 401 itself when auth is on).
    let token: string | null = null
    try {
      token = await getToken()
    } catch {
      token = null
    }
    const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
    if (token) headers['Authorization'] = `Bearer ${token}`
    if (init.body) headers['Content-Type'] = 'application/json'

    const resp = await fetch(`${API_BASE}${path}`, { ...init, headers })
    if (!resp.ok) {
      let detail = resp.statusText
      try {
        const body = await resp.json()
        detail = body.detail ?? detail
      } catch {
        /* non-JSON error */
      }
      throw new ApiError(resp.status, detail)
    }
    if (resp.status === 204) return undefined as T
    return resp.json() as Promise<T>
  }

  return {
    dashboard: () => req<Dashboard>('/api/dashboard'),
    listVms: () => req<VM[]>('/api/vms'),
    sizes: () => req<Size[]>('/api/sizes'),
    deploy: (body: DeployBody) =>
      req<{ job_id: string }>('/api/vms', { method: 'POST', body: JSON.stringify(body) }),
    job: (id: string) => req<Job>(`/api/jobs/${id}`),
    cancelJob: (id: string) => req(`/api/jobs/${id}/cancel`, { method: 'POST' }),
    start: (vmid: number) => req(`/api/vms/${vmid}/start`, { method: 'POST' }),
    stop: (vmid: number) => req(`/api/vms/${vmid}/stop`, { method: 'POST' }),
    suspend: (vmid: number) => req(`/api/vms/${vmid}/suspend`, { method: 'POST' }),
    resume: (vmid: number) => req(`/api/vms/${vmid}/resume`, { method: 'POST' }),
    remove: (vmid: number, name?: string) =>
      req(`/api/vms/${vmid}${name ? `?name=${encodeURIComponent(name)}` : ''}`, {
        method: 'DELETE',
      }),
    scanPorts: (name: string) =>
      req<{ job_id: string }>(`/api/vms/${name}/scan-ports`, { method: 'POST' }),
    publish: (name: string, service: string, port: number, isPublic: boolean) =>
      req(`/api/vms/${name}/services`, {
        method: 'POST',
        body: JSON.stringify({ service, port, public: isPublic }),
      }),
    unpublish: (name: string, service: string) =>
      req(`/api/vms/${name}/services/${service}`, { method: 'DELETE' }),
  }
}

export type Api = ReturnType<typeof createApi>
