"""Orchestration helpers for publishing / unpublishing web services.

``publish_web`` coordinates three things:
  1. Write a Caddy site file (reverse proxy ``<service>.<instance>.<domain>``
     → ``upstream_host:port``).
  2. Create a Cloudflare CNAME (if ``public=True``).
  3. Record the mapping in instance state under ``web[]``.

``unpublish_web`` reverses all three in the same order.

Both functions no-op the external parts (Caddy reload, Cloudflare API) when
their respective settings are not configured, but **always** update local
state and write/remove Caddy site files (which is safe because the controller
owns the shared ``caddy_sites`` volume).

Phase 05 wires these helpers to the ``/services`` endpoints + port discovery;
they are intentionally not wired to the VM create flow here.
"""
from __future__ import annotations

import logging
import os

from homecloud.cloudflare.dns import CloudflareDNS
from homecloud.config import settings
from homecloud.proxy.caddy import CaddyProxy
from homecloud.state import remove_instance_web_service, set_instance_web_service

logger = logging.getLogger(__name__)


def publish_web(
    instance_name: str,
    service: str,
    port: int,
    *,
    upstream_host: str,
    public: bool = True,
) -> dict:
    """Publish a web service for *instance_name*.

    Args:
        instance_name: Instance name (e.g. ``"app"``).
        service: Service label (e.g. ``"grafana"``).
        port: Port the service listens on (e.g. ``3000``).
        upstream_host: Tailnet IP or hostname of the VM.
        public: When True, create a Cloudflare CNAME record.

    Returns:
        Dict with keys ``hostname``, ``caddy_config``, ``cloudflare_record_id``.
    """
    host_label = f"{service}.{instance_name}"
    domain = settings.domain
    public_host = f"{host_label}.{domain}"

    # 1. Write / update Caddy site file.
    caddy = CaddyProxy()
    caddy_result = caddy.ensure_route(
        host_label,
        upstream_host=upstream_host,
        upstream_port=port,
    )
    # caddy_config stores just the filename, not the full path.
    caddy_filename = os.path.basename(caddy_result["config"])

    # 2. Cloudflare DNS record (no-op when unconfigured).
    cloudflare_record_id = ""
    if public:
        cf = CloudflareDNS()
        dns_result = cf.ensure_record(host_label)
        cloudflare_record_id = dns_result.get("record_id", "")

    # 3. Persist to state.
    set_instance_web_service(
        instance_name,
        service=service,
        port=port,
        public_host=public_host,
        public=public,
        cloudflare_record_id=cloudflare_record_id,
        caddy_config=caddy_filename,
    )

    logger.info(
        "Published web service: %s → %s:%s (public=%s)",
        public_host,
        upstream_host,
        port,
        public,
    )
    return {
        "hostname": public_host,
        "caddy_config": caddy_filename,
        "cloudflare_record_id": cloudflare_record_id,
    }


def unpublish_web(instance_name: str, service: str) -> None:
    """Reverse the publish for *service* on *instance_name*.

    Removes the Caddy site file, deletes the Cloudflare CNAME (no-op when
    Cloudflare is unconfigured), and removes the state entry.  No-op if the
    service is not currently published.
    """
    host_label = f"{service}.{instance_name}"

    # 1. Remove Caddy site file (reload happens inside remove_route).
    caddy = CaddyProxy()
    caddy.remove_route(host_label)

    # 2. Remove Cloudflare record (no-op when unconfigured).
    cf = CloudflareDNS()
    cf.delete_record(host_label)

    # 3. Remove from state.
    remove_instance_web_service(instance_name, service)

    logger.info("Unpublished web service: %s.%s", service, instance_name)
