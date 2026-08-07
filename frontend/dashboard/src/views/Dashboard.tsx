import { useEffect, type ReactNode } from 'react'
import { UserButton } from '@clerk/react'
import { IconCloud, IconHypervisor } from '../Icons'
import { PortalRail } from '../PortalRail'

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
    id: 'homecloud',
    name: 'homecloud',
    desc: 'VM instances, images & self-hosted infrastructure',
    href: 'https://homecloud.gavinf.com',
    icon: <IconCloud />,
    live: true,
  },
  {
    id: 'proxmox',
    name: 'proxmox',
    desc: 'Proxmox hypervisor, VMs & cluster management',
    href: 'https://proxmox.gavinf.com',
    icon: <IconHypervisor />,
    live: true,
  },
]

export function Dashboard() {
  useEffect(() => { document.title = 'Dashboard' }, [])
  return (
    <div className="dash-shell">
      <PortalRail active="dashboard" />
      <header className="dash-header">
        <div className="spacer" />
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
