from __future__ import annotations

import time

import httpx

from homecloud.config import settings

TAILSCALE_API = "https://api.tailscale.com/api/v2"
RETRYABLE = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.NetworkError,
)


class TailscaleClient:
    """Tailscale admin API — auth keys, device listing, DNS names."""

    def __init__(self) -> None:
        self.tailnet = settings.tailscale_tailnet
        self._headers = {"Authorization": f"Bearer {settings.tailscale_api_key}"}

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=TAILSCALE_API, headers=self._headers, timeout=30.0)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                with self._client() as client:
                    resp = client.request(method, path, **kwargs)
                    resp.raise_for_status()
                    return resp
            except RETRYABLE as exc:
                last_exc = exc
                time.sleep(min(2**attempt, 8))
        raise last_exc or RuntimeError("Tailscale API request failed")

    def list_devices(self) -> list[dict]:
        resp = self._request("GET", f"/tailnet/{self.tailnet}/devices")
        return resp.json().get("devices", [])

    def get_device_by_hostname(self, hostname: str) -> dict | None:
        for device in self.list_devices():
            name = device.get("name", "")
            short = name.split(".")[0] if name else ""
            if short == hostname or name == hostname:
                return device
        return None

    def get_device_ip(self, hostname: str) -> str | None:
        device = self.get_device_by_hostname(hostname)
        if not device:
            return None
        for addr in device.get("addresses", []):
            ip = addr.split("/")[0]
            if ip.startswith("100."):
                return ip
        return None

    def create_reusable_auth_key(
        self,
        *,
        description: str = "homecloud-vm",
        tags: list[str] | None = None,
        expiry_seconds: int = 86400 * 90,
    ) -> str:
        """Create a pre-auth key for cloud-init. Requires API key with key creation scope."""
        payload: dict = {
            "capabilities": {
                "devices": {
                    "create": {
                        "reusable": True,
                        "ephemeral": False,
                        "preauthorized": True,
                        "tags": tags or ["tag:homecloud"],
                    }
                }
            },
            "expirySeconds": expiry_seconds,
            "description": description,
        }
        resp = self._request("POST", f"/tailnet/{self.tailnet}/keys", json=payload)
        return resp.json()["key"]

    @staticmethod
    def fqdn(hostname: str) -> str:
        tailnet = settings.tailscale_tailnet
        if tailnet and not hostname.endswith(tailnet):
            return f"{hostname}.{tailnet}"
        return hostname

    @staticmethod
    def magic_dns_url(hostname: str, port: int | None = None) -> str:
        fqdn = TailscaleClient.fqdn(hostname)
        if port:
            return f"{fqdn}:{port}"
        return fqdn
