from __future__ import annotations

import logging

import httpx

from homecloud.config import settings

logger = logging.getLogger(__name__)

CF_API = "https://api.cloudflare.com/client/v4"


class CloudflareDNS:
    """Manage proxied CNAME records for the homecloud domain via Cloudflare API."""

    def __init__(self) -> None:
        self.token = settings.cloudflare_api_token
        self.zone_id = settings.cloudflare_zone_id
        self.domain = settings.domain
        self.tunnel_cname = settings.cloudflare_tunnel_cname

    @property
    def enabled(self) -> bool:
        """True only when all required credentials are set."""
        return bool(self.token and self.zone_id and self.tunnel_cname)

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=CF_API,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30.0,
        )

    def _normalize(self, host_label: str) -> tuple[str, str]:
        """Return (label, fqdn) from a bare label, multi-label, or full FQDN.

        Examples (domain = myhomecloud.dev):
            "app"                      → ("app", "app.myhomecloud.dev")
            "grafana.app"              → ("grafana.app", "grafana.app.myhomecloud.dev")
            "app.myhomecloud.dev"      → ("app", "app.myhomecloud.dev")
            "grafana.app.myhomecloud.dev" → ("grafana.app", "grafana.app.myhomecloud.dev")
        """
        suffix = f".{self.domain}"
        if host_label.endswith(suffix):
            label = host_label[: -len(suffix)]
        else:
            label = host_label
        return label, f"{label}.{self.domain}"

    def ensure_record(self, host_label: str) -> dict:
        """Create or update a proxied CNAME for <host_label>.<domain> → tunnel CNAME.

        Idempotent: looks up existing record by name and PUTs if found, POSTs otherwise.
        host_label may be a bare label ("app"), multi-label ("grafana.app"),
        or a full FQDN ("app.myhomecloud.dev").

        Returns:
            {"hostname": str, "record_id": str, "content": str}  on success
            {"skipped": True, "hostname": str}                    when not enabled
        """
        label, fqdn = self._normalize(host_label)
        if not self.enabled:
            logger.warning("Cloudflare DNS not configured — skipping record for %s", fqdn)
            return {"skipped": True, "hostname": fqdn}

        payload: dict = {
            "type": "CNAME",
            "name": label,
            "content": self.tunnel_cname,
            "proxied": True,
            "comment": "homecloud-managed",
        }

        with self._client() as client:
            existing = client.get(
                f"/zones/{self.zone_id}/dns_records",
                params={"type": "CNAME", "name": fqdn},
            )
            existing.raise_for_status()
            records = existing.json().get("result", [])

            if records:
                record_id = records[0]["id"]
                resp = client.put(
                    f"/zones/{self.zone_id}/dns_records/{record_id}", json=payload
                )
            else:
                resp = client.post(f"/zones/{self.zone_id}/dns_records", json=payload)

            resp.raise_for_status()
            result = resp.json()["result"]
            return {
                "hostname": fqdn,
                "record_id": result["id"],
                "content": result["content"],
            }

    def delete_record(self, host_label: str) -> None:
        """Remove all CNAME records matching host_label. No-op when disabled."""
        label, fqdn = self._normalize(host_label)
        if not self.enabled:
            logger.warning("Cloudflare DNS not configured — skipping delete for %s", fqdn)
            return

        with self._client() as client:
            existing = client.get(
                f"/zones/{self.zone_id}/dns_records",
                params={"type": "CNAME", "name": fqdn},
            )
            existing.raise_for_status()
            for record in existing.json().get("result", []):
                client.delete(f"/zones/{self.zone_id}/dns_records/{record['id']}")


# ---------------------------------------------------------------------------
# Module-level helpers for callers in later phases (Phase 04/05)
# TODO(phase-04): wire publish_dns / unpublish_dns into the Caddy + tunnel publish flow
# ---------------------------------------------------------------------------


def publish_dns(hostname: str) -> dict:
    """Ensure a proxied CNAME record exists for hostname. Returns the ensure_record result."""
    return CloudflareDNS().ensure_record(hostname)


def unpublish_dns(hostname: str) -> None:
    """Remove the CNAME record for hostname. No-op when Cloudflare is not configured."""
    CloudflareDNS().delete_record(hostname)
