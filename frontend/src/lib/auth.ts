import type { TokenGetter } from '../api'

// Local-dev auth bypass. Enabled only when running the Vite dev server
// (`import.meta.env.DEV`) AND `VITE_DEV_BYPASS_AUTH=true` is set. Gating on DEV
// guarantees a production build can never ship with auth disabled, even if the
// flag leaks into an env file.
export const BYPASS_AUTH =
  import.meta.env.DEV && import.meta.env.VITE_DEV_BYPASS_AUTH === 'true'

// Stable no-op token getter for bypass mode. The controller runs fail-open in
// dev (no Clerk issuer/JWKS configured), so requests need no bearer token.
export const noToken: TokenGetter = async () => null
