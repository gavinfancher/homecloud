from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Proxmox
    proxmox_host: str = "localhost"
    proxmox_user: str = "root@pam"
    proxmox_token_name: str = ""
    proxmox_token_value: str = ""
    proxmox_verify_ssl: bool = False
    proxmox_node: str = "pve-root"
    proxmox_storage: str = "ssd-pool"
    proxmox_bridge: str = "vmbr0"
    proxmox_snippets_dir: str = "/var/lib/vz/snippets"
    proxmox_ssh_host: str = ""
    proxmox_base_template_id: int = 9000

    # Tailscale — VMs join tailnet; SSH via MagicDNS (name.tailnet.ts.net)
    tailscale_api_key: str = ""
    tailscale_tailnet: str = ""
    tailscale_auth_key: str = ""

    # VM SSH user
    vm_ssh_user: str = "ubuntu"

    # Controller (AGENT_HOST/AGENT_PORT still accepted for back-compat)
    controller_host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("CONTROLLER_HOST", "AGENT_HOST"),
    )
    controller_port: int = Field(
        default=8080,
        validation_alias=AliasChoices("CONTROLLER_PORT", "AGENT_PORT"),
    )

    # Public domain
    domain: str = "myhomecloud.dev"

    # Cloudflare
    cloudflare_api_token: str = ""
    cloudflare_zone_id: str = ""
    cloudflare_tunnel_id: str = ""
    cloudflare_tunnel_cname: str = ""

    # Caddy
    caddy_config_dir: str = "/etc/caddy/sites"
    caddy_reload_cmd: str = ""

    # Local resolver (split DNS)
    coredns_zone_path: str = "/etc/coredns/db.myhomecloud.dev"
    coredns_reload_cmd: str = ""
    control_node_tailscale_ip: str = ""

    # Default primary web port for an instance's base hostname
    default_web_port: int = 80

    # Owner (single-user model) — namespacing label used in public hostnames:
    #   <service>.<instance>.<owner_username>.<domain>
    # Leave empty to keep the flat <service>.<instance>.<domain> scheme.
    owner_username: str = ""

    # Clerk auth (phase 09). All optional: when jwks_url + issuer are unset,
    # auth is DISABLED (fail-open dev mode, logged loudly) so local runs/tests
    # work without infra. In production set both → fail-closed.
    clerk_jwks_url: str = ""           # https://<slug>.clerk.accounts.dev/.well-known/jwks.json
    clerk_issuer: str = ""            # https://<slug>.clerk.accounts.dev
    clerk_authorized_parties: str = ""  # comma-separated allowed azp (e.g. https://app.myhomecloud.dev)
    clerk_publishable_key: str = ""   # public; surfaced to the SPA via GET /api/config

    # Frontend / API exposure (phases 09–11)
    frontend_origin: str = ""          # comma-separated CORS origins for the Pages SPA
    api_public_host: str = ""          # e.g. api.myhomecloud.dev (tunnel/Caddy route)
    console_url: str = ""              # e.g. https://app.myhomecloud.dev — login redirect target

    # Caddy forward-auth (phase 11). When set, every published site is gated by
    # a forward_auth to this upstream's /auth/verify. Empty → no auth block.
    caddy_forward_auth_upstream: str = ""  # e.g. controller:8080


settings = Settings()
