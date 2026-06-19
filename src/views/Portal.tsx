import { SignIn, Show } from '@clerk/react'
import { useEffect } from 'react'
import { IconCloudMark } from '../Icons'

export function Portal() {
  useEffect(() => { document.title = 'Sign in' }, [])
  return (
    <>
      <Show when="signed-out">
        <div className="land-shell">
          <header className="land-header">
            <div className="land-logo-mark">
              <IconCloudMark size={18} />
            </div>
            <a className="btn-login" href="https://gavinf.com">← Back</a>
          </header>
          <main className="portal-main">
            <SignIn
              routing="hash"
              fallbackRedirectUrl="https://dash.gavinf.com"
              forceRedirectUrl="https://dash.gavinf.com"
            />
          </main>
        </div>
      </Show>
      <Show when="signed-in">
        <RedirectToDash />
      </Show>
    </>
  )
}

function RedirectToDash() {
  useEffect(() => {
    window.location.href = 'https://dash.gavinf.com'
  }, [])

  return (
    <div className="portal-main">
      <p className="muted">Redirecting to dashboard…</p>
    </div>
  )
}
