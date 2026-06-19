import { ClerkProvider } from '@clerk/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { BYPASS_AUTH } from './lib/auth'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!BYPASS_AUTH && !PUBLISHABLE_KEY) {
  throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY (run `clerk env pull` in frontend/)')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      {BYPASS_AUTH ? (
        <App />
      ) : (
        <ClerkProvider
          publishableKey={PUBLISHABLE_KEY}
          signInUrl="https://auth.gavinf.com"
          afterSignOutUrl="https://gavinf.com"
        >
          <App />
        </ClerkProvider>
      )}
    </BrowserRouter>
  </StrictMode>,
)
