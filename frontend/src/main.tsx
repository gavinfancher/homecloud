import { ClerkProvider } from '@clerk/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { BYPASS_AUTH } from './lib/auth'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!BYPASS_AUTH && !PUBLISHABLE_KEY) {
  throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY (run `clerk env pull` in frontend/)')
}

// Production SPA runs on app.myhomecloud.dev (not the Clerk Accounts host). Satellite
// mode keeps sessions working across that custom domain.
const isSatellite = import.meta.env.VITE_CLERK_IS_SATELLITE === 'true'
const clerkDomain = import.meta.env.VITE_CLERK_DOMAIN
const signInUrl = import.meta.env.VITE_CLERK_SIGN_IN_URL
const signUpUrl = import.meta.env.VITE_CLERK_SIGN_UP_URL

const satelliteProps = isSatellite && clerkDomain && signInUrl
  ? {
      isSatellite: true as const,
      domain: clerkDomain,
      signInUrl,
      signUpUrl: signUpUrl || signInUrl.replace(/sign-in$/, 'sign-up'),
    }
  : {}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {BYPASS_AUTH ? (
      <App />
    ) : (
      <ClerkProvider publishableKey={PUBLISHABLE_KEY} afterSignOutUrl="/" {...satelliteProps}>
        <App />
      </ClerkProvider>
    )}
  </StrictMode>,
)
