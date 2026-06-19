import { ClerkProvider, ClerkLoading, ClerkLoaded, Show, RedirectToSignIn } from '@clerk/react'
import { Landing } from './views/Landing'
import { Portal } from './views/Portal'
import { Dashboard } from './views/Dashboard'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

const hostname = window.location.hostname
const devView = new URLSearchParams(window.location.search).get('view')
const isLanding = !devView && (hostname === 'gavinf.com' || hostname === 'www.gavinf.com' || hostname === 'localhost')
const isAuth = hostname === 'auth.gavinf.com' || devView === 'auth'
const isDash = hostname === 'dash.gavinf.com' || devView === 'dash'

export default function App() {
  if (isLanding) return <Landing />

  return (
    <ClerkProvider
      publishableKey={PUBLISHABLE_KEY}
      localization={{ signIn: { start: { title: 'Sign in' } } }}
    >
      <ClerkLoading>
        <div style={{ color: '#8d99a8', padding: 32 }}>Loading…</div>
      </ClerkLoading>
      <ClerkLoaded>
        {isAuth ? (
          <Portal />
        ) : isDash ? (
          <>
            <Show when="signed-in">
              <Dashboard />
            </Show>
            <Show when="signed-out">
              <RedirectToSignIn signInUrl="https://auth.gavinf.com" />
            </Show>
          </>
        ) : null}
      </ClerkLoaded>
    </ClerkProvider>
  )
}
