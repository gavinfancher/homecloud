import { useEffect, type ReactNode } from 'react'
import { UserButton } from '@clerk/react'
import { IconCloud, IconCloudMark, IconNas } from '../Icons'

type Service = {
  id: string
  name: string
  desc: string
  href: string
  icon: ReactNode
  live: boolean
}

const SERVICES: Service[] = [
  {
    id: 'mycloud',
    name: 'mycloud',
    desc: 'VM instances, images & self-hosted infrastructure',
    href: 'https://mycloud.gavinf.com',
    icon: <IconCloud />,
    live: true,
  },
  {
    id: 'nas',
    name: 'nas',
    desc: 'TrueNAS storage, datasets & file shares',
    href: 'https://nas.gavinf.com',
    icon: <IconNas />,
    live: true,
  },
]

export function Dashboard() {
  useEffect(() => { document.title = 'Dashboard' }, [])
  return (
    <div className="dash-shell">
      <header className="dash-header">
        <div className="dash-brand">
          <div className="land-logo-mark">
            <IconCloudMark size={18} />
          </div>
          <span>Dashboard</span>
        </div>
        <UserButton />
      </header>

      <main className="dash-content">
        <p className="dash-section-label">Services</p>
        <div className="service-grid">
          {SERVICES.map((s) => (
            <a
              key={s.id}
              className="service-card"
              href={s.href}
            >
              <div className="service-card-icon">{s.icon}</div>
              <p className="service-card-name">{s.name}</p>
              <p className="service-card-desc">{s.desc}</p>
              <div className="service-card-status">
                <span className={`dot ${s.live ? 'dot-live' : ''}`} />
                {s.live ? 'live' : 'coming soon'}
              </div>
            </a>
          ))}
        </div>
      </main>
    </div>
  )
}
