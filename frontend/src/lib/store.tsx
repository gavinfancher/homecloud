import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  createApi,
  CONN_FAIL_THRESHOLD,
  type Api,
  type Dashboard,
  type RoleSpec,
  type Size,
  type Source,
  type TokenGetter,
  type VM,
} from '../api'

interface Store {
  api: Api
  dashboard: Dashboard | null
  vms: VM[]
  sizes: Size[]
  /** Stock distro images to clone from. Empty when the controller has no database. */
  sources: Source[]
  /** The Ansible role catalog the create/reconfigure flows render. */
  roles: RoleSpec[]
  ready: boolean
  connError: string | null
  refresh: () => Promise<void>
  refreshSources: () => Promise<void>
  activeJob: string | null
  openJob: (id: string) => void
  closeJob: () => void
}

const StoreContext = createContext<Store | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useStore(): Store {
  const ctx = useContext(StoreContext)
  if (!ctx) throw new Error('useStore must be used within StoreProvider')
  return ctx
}

export function StoreProvider({
  getToken,
  children,
}: {
  getToken: TokenGetter
  children: ReactNode
}) {
  const api = useMemo(() => createApi(getToken), [getToken])

  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [vms, setVms] = useState<VM[]>([])
  const [sizes, setSizes] = useState<Size[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [roles, setRoles] = useState<RoleSpec[]>([])
  const [ready, setReady] = useState(false)
  const [connError, setConnError] = useState<string | null>(null)
  const [activeJob, setActiveJob] = useState<string | null>(null)
  const failCountRef = useRef(0)

  const refresh = useCallback(async () => {
    let gotDashboard = false
    let gotVms = false
    let lastError: string | null = null

    try {
      const d = await api.dashboard()
      setDashboard(d)
      gotDashboard = true
    } catch (e) {
      lastError = e instanceof Error ? e.message : String(e)
    }

    try {
      const v = await api.listVms()
      setVms(v)
      gotVms = true
    } catch (e) {
      lastError = e instanceof Error ? e.message : String(e)
    }

    if (gotDashboard || gotVms) {
      failCountRef.current = 0
      setConnError(null)
    } else if (lastError) {
      failCountRef.current += 1
      if (failCountRef.current >= CONN_FAIL_THRESHOLD) {
        setConnError(lastError)
      }
    }
    setReady(true)
  }, [api])

  const refreshSources = useCallback(async () => {
    try {
      setSources(await api.sources())
    } catch {
      /* 503 when no database is configured — the picker stays empty */
    }
  }, [api])

  useEffect(() => {
    api.sizes().then(setSizes).catch(() => {})
    api.roles().then(setRoles).catch(() => {})
    Promise.resolve().then(refreshSources)
    Promise.resolve().then(refresh)
    const t = setInterval(refresh, activeJob ? 8000 : 5000)
    return () => clearInterval(t)
  }, [api, refresh, refreshSources, activeJob])

  const value = useMemo<Store>(
    () => ({
      api,
      dashboard,
      vms,
      sizes,
      sources,
      roles,
      ready,
      connError,
      refresh,
      refreshSources,
      activeJob,
      openJob: setActiveJob,
      closeJob: () => setActiveJob(null),
    }),
    [
      api,
      dashboard,
      vms,
      sizes,
      sources,
      roles,
      ready,
      connError,
      refresh,
      refreshSources,
      activeJob,
    ],
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}
