// gavinf-prod: one Worker for every gavinf.com site. Hostname routing:
//   homecloud.gavinf.com → console SPA (assets under /console)
//   docs.gavinf.com      → VitePress docs site (assets under /docs; static
//                          multi-page build, no SPA-fallback needed)
//   proxmox.gavinf.com   → portal-rail shell for navigations, passthrough
//                          (XHR, assets, WebSocket consoles) to the tunnel origin
//   everything else      → portal SPA (assets under /portal; the app itself
//                          switches views for gavinf.com / auth / dash)
// The proxmox rail below mirrors frontend/src/PortalRail.tsx — keep in sync.

const CONSOLE_HOST = "homecloud.gavinf.com";
const DOCS_HOST = "docs.gavinf.com";
const PROXMOX_HOST = "proxmox.gavinf.com";

const PROXMOX_SHELL = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>proxmox - Proxmox Virtual Environment</title>
<style>
  html, body { margin: 0; height: 100%; background: #0a0d12; }
  .portal-rail {
    position: fixed; top: 0; left: 0; bottom: 0; z-index: 1000;
    width: 56px; overflow: hidden;
    background: #0e131a; border-right: 1px solid #232c39;
    display: flex; flex-direction: column; gap: 2px;
    padding: 10px 11px; box-sizing: border-box;
    transition: width 0.16s ease;
    font-family: ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
  }
  .portal-rail.open { width: 220px; }
  .portal-rail-item {
    display: flex; align-items: center; gap: 12px; flex-shrink: 0;
    height: 38px; padding: 0 2px; border-radius: 7px;
    color: #8d99a8; text-decoration: none; white-space: nowrap;
    font-size: 13.5px; font-weight: 600;
  }
  .portal-rail-item:hover, .portal-rail-item.active { background: #131a23; color: #e7edf4; }
  .portal-rail-icon {
    width: 30px; height: 30px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
  }
  .portal-rail-mark { background: #16263f; border-radius: 7px; }
  .portal-rail-brand { height: 42px; color: #e7edf4; font-size: 15px; margin-bottom: 6px; }
  .portal-rail-label { opacity: 0; transition: opacity 0.12s ease; }
  .portal-rail.open .portal-rail-label { opacity: 1; }
  .portal-rail-sep { height: 1px; flex-shrink: 0; background: #232c39; margin: 4px 2px 8px; }
  .portal-rail-spacer { flex: 1; }
  .portal-rail-toggle { background: none; border: 0; cursor: pointer; font: inherit; width: 100%; text-align: left; }
  iframe { display: block; margin-left: 56px; width: calc(100vw - 56px); height: 100vh; border: 0; transition: margin-left 0.16s ease, width 0.16s ease; }
  body.rail-open iframe { margin-left: 220px; width: calc(100vw - 220px); }
</style>
</head>
<body>
<nav class="portal-rail">
  <a class="portal-rail-item portal-rail-brand" href="https://dash.gavinf.com" title="Dashboard">
    <span class="portal-rail-icon portal-rail-mark">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <path d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A6 6 0 0 0 6.34 9.5 4 4 0 0 0 7 19z"
          stroke="#3b82f6" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </span>
    <span class="portal-rail-label">Dashboard</span>
  </a>
  <div class="portal-rail-sep"></div>
  <a class="portal-rail-item" href="https://homecloud.gavinf.com" title="homecloud">
    <span class="portal-rail-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>
      </svg>
    </span>
    <span class="portal-rail-label">homecloud</span>
  </a>
  <a class="portal-rail-item active" href="https://proxmox.gavinf.com" title="proxmox">
    <span class="portal-rail-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1"/>
        <rect x="14" y="3" width="7" height="7" rx="1"/>
        <rect x="3" y="14" width="7" height="7" rx="1"/>
        <rect x="14" y="14" width="7" height="7" rx="1"/>
      </svg>
    </span>
    <span class="portal-rail-label">proxmox</span>
  </a>
  <a class="portal-rail-item" href="https://docs.gavinf.com" title="docs">
    <span class="portal-rail-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <path d="M14 2v6h6"/>
        <path d="M9 13h6"/>
        <path d="M9 17h6"/>
      </svg>
    </span>
    <span class="portal-rail-label">docs</span>
  </a>
  <div class="portal-rail-spacer"></div>
  <button type="button" class="portal-rail-item portal-rail-toggle" id="rail-toggle" title="Expand">
    <span class="portal-rail-icon">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <path d="M9 3v18"/>
      </svg>
    </span>
    <span class="portal-rail-label">Collapse</span>
  </button>
</nav>
<iframe id="pve" title="Proxmox VE"></iframe>
<script>
  document.getElementById('pve').src =
    location.pathname + location.search + location.hash;
  var rail = document.querySelector('.portal-rail');
  if (localStorage.getItem('portal-rail-open') === '1') {
    rail.classList.add('open');
    document.body.classList.add('rail-open');
  }
  document.getElementById('rail-toggle').addEventListener('click', function () {
    var open = rail.classList.toggle('open');
    document.body.classList.toggle('rail-open', open);
    localStorage.setItem('portal-rail-open', open ? '1' : '0');
  });
</script>
</body>
</html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.hostname === PROXMOX_HOST) {
      if (request.method === "GET" &&
          request.headers.get("Sec-Fetch-Dest") === "document") {
        return new Response(PROXMOX_SHELL, {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      }
      return fetch(request);
    }

    if (url.hostname === DOCS_HOST) {
      const assetUrl = new URL(url);
      assetUrl.pathname = `/docs${url.pathname}`;
      return env.ASSETS.fetch(new Request(assetUrl, request));
    }

    const app = url.hostname === CONSOLE_HOST ? "console" : "portal";
    const assetUrl = new URL(url);
    assetUrl.pathname = `/${app}${url.pathname}`;
    let resp = await env.ASSETS.fetch(new Request(assetUrl, request));
    if (resp.status === 404) {
      assetUrl.pathname = `/${app}/`;
      resp = await env.ASSETS.fetch(new Request(assetUrl, request));
    }
    return resp;
  },
};
