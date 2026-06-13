// Typed client for the homecloud controller API. All calls attach the Clerk
// session token as a Bearer credential (no-op in dev when auth is disabled).

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export type TokenGetter = () => Promise<string | null>

export interface WebService {
  service: string
  port: number
  public_host: string
  public: boolean
}

export interface SeenPort {
  port: number
  proc?: string
}

export interface VM {
  vmid: number
  name: string
  status: string
  cores?: number
  memory_gb?: number
  disk_gb?: number
  hostname?: string
  private_host?: string
  magic_dns?: string
  tailscale_ip?: string
  ip?: string
  ssh?: string
  size_id?: string
  image_id?: string
  web?: WebService[]
  ports_seen?: SeenPort[]
  ports_scanned_at?: string | null
}

export interface Size {
  id: string
  label: string
  cores: number
  memory_gb: number
  disk_gb: number
}

export interface Image {
  id: string
  name: string
  description: string
  built: boolean
  template_id: number | null
  default_cores: number
  default_memory_mb: number
  default_disk_gb: number
  packages: string[]
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
  created_at?: string
  started_at?: string
  finished_at?: string
}

export interface Dashboard {
  setup_complete: boolean
  base_image_built: boolean
  tailscale_tailnet: string
  proxmox_node: string
  proxmox_storage?: string
  stats: { total_vms: number; running: number; stopped: number; templates: number }
  recent_jobs: Job[]
}

export interface SetupStatus {
  setup_complete: boolean
  base_image_built: boolean
  tailscale_tailnet: string
  proxmox_node: string
  proxmox_storage: string
  vm_ssh_user: string
  ssh_public_keys_count: number
  ssh_public_keys: string[]
  rebuild_note: string
}

export interface PortsResult {
  ports_seen: SeenPort[]
  ports_scanned_at: string | null
}

export interface DeployBody {
  name: string
  size_id?: string
  cores?: number
  memory_gb?: number
  disk_gb?: number
  image_id?: string
}

export const REQUEST_TIMEOUT_MS = 45_000
export const CONN_FAIL_THRESHOLD = 3

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
      /* token unavailable — fall through; API enforces auth itself */
    }
    const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
    if (token) headers['Authorization'] = `Bearer ${token}`
    if (init.body) headers['Content-Type'] = 'application/json'

    try {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
      const resp = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers,
        signal: controller.signal,
      })
      clearTimeout(timer)
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
    } catch (e) {
      if (e instanceof ApiError) throw e
      if (e instanceof DOMException && e.name === 'AbortError') {
        throw new Error(
          `Timed out calling ${API_BASE || 'same-origin'}${path} — the controller may be busy (Proxmox deploy/delete)`,
        )
      }
      if (e instanceof TypeError) {
        throw new Error(
          `Network error calling ${API_BASE || 'same-origin'}${path} — API unreachable (check api.myhomecloud.dev / tunnel)`,
          { cause: e },
        )
      }
      throw e
    }
  }

  return {
    dashboard: () => req<Dashboard>('/api/dashboard'),
    listVms: () => req<VM[]>('/api/vms'),
    getVm: (vmid: number) => req<VM>(`/api/vms/${vmid}`),
    sizes: () => req<Size[]>('/api/sizes'),
    images: () => req<Image[]>('/api/images'),
    buildBaseImage: () => req<{ job_id: string }>('/api/images/homecloud-base/build', { method: 'POST' }),
    deploy: (body: DeployBody) =>
      req<{ job_id: string }>('/api/vms', { method: 'POST', body: JSON.stringify(body) }),
    listJobs: (limit = 30) => req<Job[]>(`/api/jobs?limit=${limit}`),
    job: (id: string) => req<Job>(`/api/jobs/${id}`),
    cancelJob: (id: string) => req(`/api/jobs/${id}/cancel`, { method: 'POST' }),
    start: (vmid: number) => req(`/api/vms/${vmid}/start`, { method: 'POST' }),
    stop: (vmid: number) => req(`/api/vms/${vmid}/stop`, { method: 'POST' }),
    suspend: (vmid: number) => req(`/api/vms/${vmid}/suspend`, { method: 'POST' }),
    resume: (vmid: number) => req(`/api/vms/${vmid}/resume`, { method: 'POST' }),
    remove: (vmid: number, name?: string) =>
      req<{ job_id: string }>(`/api/vms/${vmid}${name ? `?name=${encodeURIComponent(name)}` : ''}`, {
        method: 'DELETE',
      }),
    scanPorts: (name: string) =>
      req<{ job_id: string }>(`/api/vms/${name}/scan-ports`, { method: 'POST' }),
    ports: (name: string) => req<PortsResult>(`/api/vms/${name}/ports`),
    setupStatus: () => req<SetupStatus>('/api/setup'),
    saveSetup: (sshPublicKeys: string[]) =>
      req<{ setup_complete: boolean; ssh_public_keys_count: number; rebuild_note: string }>(
        '/api/setup',
        { method: 'POST', body: JSON.stringify({ ssh_public_keys: sshPublicKeys }) },
      ),
    sshConfig: () => req<{ config: string }>('/api/ssh-config'),
    publish: (name: string, service: string, port: number, isPublic: boolean, force = false) =>
      req(`/api/vms/${name}/services`, {
        method: 'POST',
        body: JSON.stringify({ service, port, public: isPublic, force }),
      }),
    unpublish: (name: string, service: string) =>
      req(`/api/vms/${name}/services/${service}`, { method: 'DELETE' }),
  }
}

export type Api = ReturnType<typeof createApi>
