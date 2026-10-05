from __future__ import annotations

import time
from datetime import datetime

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

    @staticmethod
    def device_id(device: dict) -> str:
        """API path id — prefer nodeId over numeric id."""
        node_id = device.get("nodeId")
        if node_id:
            return str(node_id)
        device_id = device.get("id")
        if device_id is None:
            raise ValueError("Tailscale device record has no id or nodeId")
        return str(device_id)

    def delete_device(self, device_id: str) -> None:
        """Remove a device from the tailnet (DELETE /api/v2/device/{id})."""
        self._request("DELETE", f"/device/{device_id}")

    def delete_device_by_hostname(self, hostname: str) -> bool:
        """Delete tailnet device matching short hostname or FQDN. Returns True if removed."""
        device = self.get_device_by_hostname(hostname)
        if device is None:
            return False
        self.delete_device(self.device_id(device))
        return True

    def get_device_ip(self, hostname: str) -> str | None:
        device = self.get_device_by_hostname(hostname)
        return self.tailnet_ip(device) if device else None

    @staticmethod
    def tailnet_ip(device: dict) -> str | None:
        for addr in device.get("addresses", []):
            ip = addr.split("/")[0]
            if ip.startswith("100."):
                return ip
        return None

    def find_new_device(self, hostname: str, *, since: datetime) -> dict | None:
        """The device named *hostname* that joined at or after *since*.

        A stale device with the same name (a VM deleted without its tailnet
        cleanup) would otherwise be matched; the newest new one wins.
        """
        matches = []
        for device in self.list_devices():
            if device.get("hostname") != hostname:
                continue
            created = device.get("created")
            if not created:
                continue
            joined = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if joined >= since:
                matches.append((joined, device))
        return max(matches, key=lambda m: m[0])[1] if matches else None

    def create_vm_auth_key(self, hostname: str, *, expiry_seconds: int = 3600) -> str:
        """A single-use, pre-authorized key for one VM's first boot.

        It reaches the VM on the cloud-init seed, so it is short-lived and
        spent on first use; the seed itself is deleted once cloud-init is done.
        """
        create: dict = {"reusable": False, "ephemeral": False, "preauthorized": True}
        tags = [t.strip() for t in settings.tailscale_tags.split(",") if t.strip()]
        if tags:
            create["tags"] = tags
        payload = {
            "capabilities": {"devices": {"create": create}},
            "expirySeconds": expiry_seconds,
            "description": f"homecloud {hostname}"[:50],
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
