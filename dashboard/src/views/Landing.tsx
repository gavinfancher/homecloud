import { useEffect } from 'react'
import { IconCloudMark } from '../Icons'

export function Landing() {
  useEffect(() => { document.title = 'gavinf.com' }, [])
  return (
    <div className="land-shell">
      <header className="land-header">
        <div className="land-logo-mark">
          <IconCloudMark size={18} />
        </div>
        <a className="btn-login" href="https://auth.gavinf.com">Login</a>
      </header>

      <main className="land-hero">
        <div className="land-hero-content">
          <h1 className="land-title">Personal Cloud Infrastructure</h1>
          <p className="land-desc">
            My portal for managing self-hosted infrastructure,{' '}
            <br />VM instances, and other services.
          </p>
          <div className="land-footer-row">
            <span className="land-about-label">More about me</span>
            <a
              className="land-about-btn"
              href="https://gavinfancher.com"
              target="_blank"
              rel="noopener noreferrer"
            >
              gavinfancher.com
            </a>
          </div>
        </div>
      </main>
    </div>
  )
}
