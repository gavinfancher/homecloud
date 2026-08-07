// Shared portal rail — identical markup/styles live in the homecloud console
// (frontend/src/PortalRail.tsx) and the proxmox-frame worker shell. Keep the
// three in sync when changing anything here.
import type { ReactNode } from 'react'

type Site = 'dashboard' | 'homecloud' | 'proxmox'

const SITES: { id: Site; label: string; href: string; icon: ReactNode }[] = [
  {
    id: 'homecloud',
    label: 'homecloud',
    href: 'https://homecloud.gavinf.com',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
      </svg>
    ),
  },
  {
    id: 'proxmox',
    label: 'proxmox',
    href: 'https://proxmox.gavinf.com',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
    ),
  },
]

export function PortalRail({ active }: { active: Site }) {
  return (
    <nav className="portal-rail">
      <a
        className={`portal-rail-item portal-rail-brand ${active === 'dashboard' ? 'active' : ''}`}
        href="https://dash.gavinf.com"
        title="Dashboard"
      >
        <span className="portal-rail-icon portal-rail-mark">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A6 6 0 0 0 6.34 9.5 4 4 0 0 0 7 19z"
              stroke="#3b82f6"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <span className="portal-rail-label">Dashboard</span>
      </a>
      <div className="portal-rail-sep" />
      {SITES.map((s) => (
        <a
          key={s.id}
          className={`portal-rail-item ${active === s.id ? 'active' : ''}`}
          href={s.href}
          title={s.label}
        >
          <span className="portal-rail-icon">{s.icon}</span>
          <span className="portal-rail-label">{s.label}</span>
        </a>
      ))}
    </nav>
  )
}
