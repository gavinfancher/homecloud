import { Show, SignIn, UserButton, useAuth } from '@clerk/react'
import { useCallback, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
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
import { APP_VERSION } from './lib/version'
import { StoreProvider, useStore } from './lib/store'
import { Activity } from './views/Activity'
import { Images } from './views/Images'
import { Instances } from './views/Instances'
import { Overview } from './views/Overview'
import { Settings } from './views/Settings'

type ViewId = 'overview' | 'instances' | 'images' | 'activity' | 'settings'

const NAV: { id: ViewId; path: string; label: string; icon: ReactNode }[] = [
  { id: 'overview', path: '/overview', label: 'Overview', icon: <IconOverview /> },
  { id: 'instances', path: '/instances', label: 'Instances', icon: <IconInstances /> },
  { id: 'images', path: '/images', label: 'Images', icon: <IconImages /> },
  { id: 'activity', path: '/activity', label: 'Activity', icon: <IconActivity /> },
  { id: 'settings', path: '/settings', label: 'Settings', icon: <IconSettings /> },
]

export default function App() {
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
  const location = useLocation()
  const current =
    NAV.find((n) => location.pathname === n.path || location.pathname.startsWith(`${n.path}/`)) ??
    NAV[0]

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to="/overview" className="sidebar-brand" title="Overview">
          <IconCloud width={22} height={22} />
          <span>homecloud</span>
        </NavLink>
        <nav className="sidebar-nav">
          {NAV.map((n) => (
            <NavLink
              key={n.id}
              to={n.path}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              {n.icon}
              <span>{n.label}</span>
              {n.id === 'instances' && dashboard && (
                <span className="nav-count">{dashboard.stats.total_vms}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="tailnet-badge">
            <StatusDot status={dashboard?.tailscale_tailnet ? 'running' : 'stopped'} />
            <span>{dashboard?.tailscale_tailnet || 'no tailnet'}</span>
          </div>
          <span className="console-version muted" title="SPA build version (cf-deploy-test)">
            v{APP_VERSION}
          </span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{current.label}</h1>
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
              Can’t reach the controller API — live data may be stale.{' '}
              <span className="muted">({connError})</span>
            </span>
          </div>
        )}

        <div className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<Overview />} />
            <Route path="/instances" element={<Instances />} />
            <Route path="/images" element={<Images />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/overview" replace />} />
          </Routes>
        </div>
      </div>

      {activeJob && <JobDrawer key={activeJob} jobId={activeJob} onClose={closeJob} />}
    </div>
  )
}
