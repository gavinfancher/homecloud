import { ClerkProvider, Show, RedirectToSignIn } from '@clerk/react'
import { Portal } from './views/Portal'
import { Dashboard } from './views/Dashboard'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

// gavinf.com → portal/login, everything else (dash.gavinf.com, localhost) → dashboard
const hostname = window.location.hostname
const isPortal = hostname === 'gavinf.com' || hostname === 'www.gavinf.com'

export default function App() {
  return (
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      {isPortal ? (
        <Portal />
      ) : (
        <>
          <Show when="signed-in">
            <Dashboard />
          </Show>
          <Show when="signed-out">
            <RedirectToSignIn />
          </Show>
        </>
      )}
    </ClerkProvider>
  )
}
