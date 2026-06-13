import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  createApi,
  type Api,
  type Dashboard,
  type Image,
  type Size,
  type TokenGetter,
  type VM,
} from '../api'

interface Store {
  api: Api
  dashboard: Dashboard | null
  vms: VM[]
  sizes: Size[]
  images: Image[]
  ready: boolean
  connError: string | null
  refresh: () => Promise<void>
  refreshImages: () => Promise<void>
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
  const [images, setImages] = useState<Image[]>([])
  const [ready, setReady] = useState(false)
  const [connError, setConnError] = useState<string | null>(null)
  const [activeJob, setActiveJob] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [d, v] = await Promise.all([api.dashboard(), api.listVms()])
      setDashboard(d)
      setVms(v)
      setConnError(null)
    } catch (e) {
      // Polling failures (e.g. the controller can't reach Proxmox) surface as a
      // single persistent banner instead of a toast on every interval tick.
      setConnError(e instanceof Error ? e.message : String(e))
    } finally {
      setReady(true)
    }
  }, [api])

  const refreshImages = useCallback(async () => {
    try {
      setImages(await api.images())
    } catch {
      /* non-fatal */
    }
  }, [api])

  useEffect(() => {
    api.sizes().then(setSizes).catch(() => {})
    // Run initial loads off the effect body so state updates land in a
    // microtask callback (avoids synchronous cascading renders on mount).
    Promise.resolve().then(refreshImages)
    Promise.resolve().then(refresh)
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [api, refresh, refreshImages])

  const value = useMemo<Store>(
    () => ({
      api,
      dashboard,
      vms,
      sizes,
      images,
      ready,
      connError,
      refresh,
      refreshImages,
      activeJob,
      openJob: setActiveJob,
      closeJob: () => setActiveJob(null),
    }),
    [api, dashboard, vms, sizes, images, ready, connError, refresh, refreshImages, activeJob],
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}
