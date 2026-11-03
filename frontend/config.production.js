// Replaces static/config.js in the production build: the pages call the API on its own
// hostname, a Cloudflare Tunnel to the cluster (infra/terraform/tunnel.tf).
window.HOMECLOUD_API = 'https://homecloud-api.gavinf.com';
