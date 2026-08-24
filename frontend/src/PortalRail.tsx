// Shared portal rail — an identical plain-HTML copy lives in the proxmox
// shell inside the gavinf repo's worker.js. Keep the two in sync when
// changing anything here. (dash.gavinf.com uses its own header instead.)
import { useEffect, useState, type ReactNode } from 'react'

type Site = 'dashboard' | 'homecloud' | 'proxmox' | 'docs'

const OPEN_KEY = 'portal-rail-open'

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
  {
    id: 'docs',
    label: 'docs',
    href: 'https://docs.gavinf.com',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
        <path d="M9 13h6" />
        <path d="M9 17h6" />
      </svg>
    ),
  },
]

export function PortalRail({ active, foot }: { active: Site; foot?: ReactNode }) {
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) === '1')
  const toggle = () =>
    setOpen((o) => {
      localStorage.setItem(OPEN_KEY, o ? '0' : '1')
      return !o
    })

  useEffect(() => {
    document.body.classList.toggle('rail-open', open)
    return () => document.body.classList.remove('rail-open')
  }, [open])

  return (
    <nav className={`portal-rail ${open ? 'open' : ''}`}>
      <a
        className={`portal-rail-item portal-rail-brand ${active === 'dashboard' ? 'active' : ''}`}
        href="https://dash.gavinf.com"
        title="Dashboard"
      >
        <span className="portal-rail-icon portal-rail-mark">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A6 6 0 0 0 6.34 9.5 4 4 0 0 0 7 19z"
              stroke="#3fd79a"
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
      <div className="portal-rail-spacer" />
      {foot && <div className="portal-rail-foot">{foot}</div>}
      <button
        type="button"
        className="portal-rail-item portal-rail-toggle"
        onClick={toggle}
        title={open ? 'Collapse' : 'Expand'}
      >
        <span className="portal-rail-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 3v18" />
          </svg>
        </span>
        <span className="portal-rail-label">Collapse</span>
      </button>
    </nav>
  )
}
