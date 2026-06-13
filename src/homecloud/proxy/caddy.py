"""Caddy reverse-proxy config writer.

Reload mechanism: the controller POSTs to the Caddy admin API
(``POST {caddy_reload_cmd}/reload``).  Set ``CADDY_RELOAD_CMD`` to the admin
API base URL, e.g. ``http://caddy:2019`` when running in compose.  Leave it
empty for local/dev runs — reload is then a no-op (Caddy never restarts, so
any file writes accumulate but don't take effect until Caddy is restarted
separately).

TLS notes: each generated ``.caddy`` site is prefixed with ``http://`` so
Caddy does **not** attempt auto-HTTPS.  TLS is terminated at the Cloudflare
edge; Caddy speaks plain HTTP toward the tunnel.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from homecloud.config import settings

logger = logging.getLogger(__name__)


class CaddyProxy:
    """Write per-host ``*.caddy`` site files and reload Caddy via its admin API."""

    def __init__(self) -> None:
        self.config_dir = Path(settings.caddy_config_dir)
        self.domain = settings.domain

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def fqdn(self, hostname: str) -> str:
        """Return the fully-qualified domain name for a bare label or label+domain."""
        if hostname.endswith(f".{self.domain}") or hostname == self.domain:
            return hostname
        return f"{hostname}.{self.domain}"

    def ensure_route(
        self,
        hostname: str,
        *,
        upstream_host: str,
        upstream_port: int = 80,
    ) -> dict:
        """Write (or overwrite) the Caddy site file for *hostname* and reload.

        Args:
            hostname: bare label (``grafana.app``), multi-label, or full FQDN.
            upstream_host: tailnet IP or hostname of the backend VM.
            upstream_port: port the backend service listens on.

        Returns:
            Dict with ``hostname``, ``upstream``, and ``config`` keys.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        fqdn = self.fqdn(hostname)
        config_path = self._config_path(fqdn)

        # ``http://`` prefix disables Caddy auto-HTTPS for this site.
        config_path.write_text(self._render_site(fqdn, upstream_host, upstream_port))
        logger.info("Wrote Caddy site config: %s → %s:%s", fqdn, upstream_host, upstream_port)
        self._reload()
        return {
            "hostname": fqdn,
            "upstream": f"{upstream_host}:{upstream_port}",
            "config": str(config_path),
        }

    def _render_site(self, fqdn: str, upstream_host: str, upstream_port: int) -> str:
        """Render the ``.caddy`` site body, gating it behind Clerk forward-auth
        when ``CADDY_FORWARD_AUTH_UPSTREAM`` is set."""
        forward_auth = ""
        upstream = settings.caddy_forward_auth_upstream.strip()
        if upstream:
            forward_auth = (
                f"    forward_auth {upstream} {{\n"
                f"        uri /auth/verify\n"
                f"        copy_headers X-Auth-Sub\n"
                f"    }}\n"
            )
        return (
            f"http://{fqdn} {{\n"
            f"{forward_auth}"
            f"    reverse_proxy {upstream_host}:{upstream_port}\n"
            f"}}\n"
        )

    def remove_route(self, hostname: str) -> None:
        """Delete the Caddy site file for *hostname* and reload."""
        fqdn = self.fqdn(hostname)
        config_path = self._config_path(fqdn)
        if config_path.exists():
            config_path.unlink()
            logger.info("Removed Caddy site config: %s", fqdn)
            self._reload()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _config_path(self, fqdn: str) -> Path:
        """Return the Path for the ``.caddy`` file corresponding to *fqdn*.

        Strips the domain suffix to get the label, then uses that label as the
        filename (dots preserved, e.g. ``grafana.app.caddy``).
        """
        suffix = f".{self.domain}"
        if fqdn.endswith(suffix):
            label = fqdn[: -len(suffix)]
        else:
            label = fqdn
        return self.config_dir / f"{label}.caddy"

    def _reload(self) -> None:
        """POST to the Caddy admin API to reload config.

        The ``CADDY_RELOAD_CMD`` setting is the admin API **base URL**
        (e.g. ``http://caddy:2019``).  When empty, reload is skipped silently.
        """
        admin_url = settings.caddy_reload_cmd.strip()
        if not admin_url:
            logger.debug("Caddy reload skipped (CADDY_RELOAD_CMD not set)")
            return
        try:
            resp = httpx.post(f"{admin_url}/reload", timeout=10.0)
            resp.raise_for_status()
            logger.info("Caddy reloaded via %s", admin_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Caddy reload failed: %s", exc)
