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

  const refreshImages = useCallback(async () => {
    try {
      setImages(await api.images())
    } catch {
      /* non-fatal */
    }
  }, [api])

  useEffect(() => {
    api.sizes().then(setSizes).catch(() => {})
    Promise.resolve().then(refreshImages)
    Promise.resolve().then(refresh)
    const t = setInterval(refresh, activeJob ? 8000 : 5000)
    return () => clearInterval(t)
  }, [api, refresh, refreshImages, activeJob])

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
