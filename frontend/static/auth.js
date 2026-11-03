// Signing in gets a session token from the API. It's kept in localStorage and sent as
// `Authorization: Bearer <token>` on every call. The pages hold nothing private; the API checks
// the token every time, and when it says no, the page sends you to sign in.
const API = window.HOMECLOUD_API || '';

const auth = (() => {
  const KEY = 'homecloud.session';
  const token = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const setToken = t => { try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch { } };

  function toLogin() {
    setToken(null);
    location.assign('/login');
    return new Promise(() => { });  // navigating away
  }

  /** Resolves to null when signed in, or the reason it didn't work. */
  async function signIn(password) {
    try {
      const res = await fetch(API + '/api/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) return body.detail || `Sign-in failed (${res.status})`;
      setToken(body.token);
      return null;
    } catch { return 'Couldn’t reach homecloud. Try again in a moment.'; }
  }

  async function signOut() {
    try { await api('/api/logout', { method: 'POST' }); } catch { }
    setToken(null);
    location.assign('/login');
  }

  /** Call the API. A 401 sends you to sign in; other errors throw with the API's message. */
  async function api(path, opts = {}) {
    const headers = { ...(opts.body ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) };
    if (token()) headers.Authorization = 'Bearer ' + token();
    const res = await fetch(API + path, { ...opts, headers });
    if (res.status === 401 && !path.startsWith('/api/log')) return toLogin();
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`);
    return body;
  }

  return { token, signIn, signOut, api };
})();
