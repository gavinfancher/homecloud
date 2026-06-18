import { SignIn, Show } from '@clerk/react'
import { useEffect } from 'react'
import { IconGlobe } from '../Icons'

export function Portal() {
  return (
    <>
      <Show when="signed-out">
        <div className="portal-wrap">
          <div className="portal-brand">
            <div className="portal-logo">
              <IconGlobe size={24} />
            </div>
            <h1>gavinf.com</h1>
            <p className="portal-tagline">Personal cloud portal</p>
          </div>
          <SignIn
            routing="hash"
            fallbackRedirectUrl="https://dash.gavinf.com"
            forceRedirectUrl="https://dash.gavinf.com"
          />
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
    <div className="portal-wrap">
      <p className="muted">Redirecting to dashboard…</p>
    </div>
  )
}
