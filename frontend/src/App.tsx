import { Show, SignIn, UserButton, useAuth } from '@clerk/react'
import { useCallback, useState, type ReactNode } from 'react'
import './App.css'
import {
  IconActivity,
  IconCloud,
  IconImages,
  IconInstances,
  IconOverview,
  IconSettings,
} from './components/Icons'
import { JobDrawer } from './components/JobDrawer'
import { ToastProvider } from './components/Toast'
import { StatusDot } from './components/ui'
import { BYPASS_AUTH, noToken } from './lib/auth'
import { StoreProvider, useStore } from './lib/store'
import { Activity } from './views/Activity'
import { Images } from './views/Images'
import { Instances } from './views/Instances'
import { Overview } from './views/Overview'
import { Settings } from './views/Settings'

type ViewId = 'overview' | 'instances' | 'images' | 'activity' | 'settings'

const NAV: { id: ViewId; label: string; icon: ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <IconOverview /> },
  { id: 'instances', label: 'Instances', icon: <IconInstances /> },
  { id: 'images', label: 'Images', icon: <IconImages /> },
  { id: 'activity', label: 'Activity', icon: <IconActivity /> },
  { id: 'settings', label: 'Settings', icon: <IconSettings /> },
]

export default function App() {
  // Local dev: skip Clerk entirely and run the console with a no-op token.
  if (BYPASS_AUTH) {
    return (
      <ToastProvider>
        <StoreProvider getToken={noToken}>
          <Console devBypass />
        </StoreProvider>
      </ToastProvider>
    )
  }

  return (
    <ToastProvider>
      <Show when="signed-out">
        <div className="signin-wrap">
          <div className="signin-brand">
            <IconCloud width={40} height={40} />
            <h1>homecloud</h1>
          </div>
          <p className="tagline">Your self-hosted cloud control plane.</p>
          <SignIn />
        </div>
      </Show>
      <Show when="signed-in">
        <ClerkStoreProvider>
          <Console />
        </ClerkStoreProvider>
      </Show>
    </ToastProvider>
  )
}

// Bridges Clerk's session token into the (Clerk-agnostic) store. Only rendered
// inside ClerkProvider, so calling useAuth here is safe.
function ClerkStoreProvider({ children }: { children: ReactNode }) {
  const { getToken, isLoaded, isSignedIn } = useAuth()

  const tokenGetter = useCallback(async () => {
    if (!isSignedIn) return null
    return getToken()
  }, [getToken, isSignedIn])

  if (!isLoaded) {
    return (
      <div className="signin-wrap">
        <p className="muted">Loading session…</p>
      </div>
    )
  }

  return <StoreProvider getToken={tokenGetter}>{children}</StoreProvider>
}

function Console({ devBypass = false }: { devBypass?: boolean }) {
  const { dashboard, ready, connError, activeJob, closeJob } = useStore()
  const [view, setView] = useState<ViewId>('overview')

  const current = NAV.find((n) => n.id === view)

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <IconCloud width={22} height={22} />
          <span>homecloud</span>
        </div>
        <nav className="sidebar-nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`nav-item ${view === n.id ? 'active' : ''}`}
              onClick={() => setView(n.id)}
            >
              {n.icon}
              <span>{n.label}</span>
              {n.id === 'instances' && dashboard && (
                <span className="nav-count">{dashboard.stats.total_vms}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="tailnet-badge">
            <StatusDot status={dashboard?.tailscale_tailnet ? 'running' : 'stopped'} />
            <span>{dashboard?.tailscale_tailnet || 'no tailnet'}</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{current?.label}</h1>
          </div>
          <div className="spacer" />
          {!ready && <span className="muted small">connecting…</span>}
          {devBypass ? (
            <span className="dev-badge" title="Auth bypassed for local dev">
              <StatusDot status="paused" /> dev · no auth
            </span>
          ) : (
            <UserButton />
          )}
        </header>

        {connError && (
          <div className="conn-banner" role="status">
            <span className="dot dot-danger" />
            <span>
              Can’t reach the controller API — live data is paused.{' '}
              <span className="muted">({connError})</span>
            </span>
          </div>
        )}

        <div className="content">
          {view === 'overview' && <Overview onNavigate={(v) => setView(v as ViewId)} />}
          {view === 'instances' && <Instances />}
          {view === 'images' && <Images />}
          {view === 'activity' && <Activity />}
          {view === 'settings' && <Settings />}
        </div>
      </div>

      {activeJob && <JobDrawer key={activeJob} jobId={activeJob} onClose={closeJob} />}
    </div>
  )
}
