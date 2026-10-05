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
    proxmox_storage: str = "local-lvm"
    proxmox_bridge: str = "vmbr0"
    # Directory storage that holds cloud-init seed ISOs (content "iso") and
    # downloaded distro cloud images (content "import").
    proxmox_image_storage: str = "local"

    # Database (source image catalog).
    # Empty → sources are unavailable, so nothing can be deployed.
    database_url: str = ""

    # Tailscale — the API key lists/deletes devices and mints per-VM auth keys
    tailscale_api_key: str = ""
    tailscale_tailnet: str = ""

    # VM SSH user
    vm_ssh_user: str = "ubuntu"

    # Controller listen address
    controller_host: str = "0.0.0.0"
    controller_port: int = 8080
    # Public path prefix the tunnel routes under (api.gavinf.com/homecloud).
    # Requests work with or without it; /docs and redirects include it.
    root_path: str = ""

    # Private zone for instance names: <vm>.<domain> and *.<vm>.<domain>,
    # served by CoreDNS to the tailnet through Tailscale split DNS.
    domain: str = "vm.dns.gavinf.com"
    # Older zones still served with the same records while clients move over
    # (comma-separated, e.g. "vm.homecloud.gavinf.com").
    dns_legacy_domains: str = ""

    # CoreDNS reads db.<zone> from here and reloads it on change.
    coredns_zone_dir: str = "/etc/coredns"
    control_node_tailscale_ip: str = ""

    # Owner (single-user model) — optional namespace in instance names:
    #   <instance>.<owner_username>.<domain>. Empty → <instance>.<domain>.
    owner_username: str = ""

    # Clerk auth (phase 09). All optional: when jwks_url + issuer are unset,
    # auth is DISABLED (fail-open dev mode, logged loudly) so local runs/tests
    # work without infra. In production set both → fail-closed.
    clerk_jwks_url: str = ""           # https://<slug>.clerk.accounts.dev/.well-known/jwks.json
    clerk_issuer: str = ""            # https://<slug>.clerk.accounts.dev
    clerk_authorized_parties: str = ""  # comma-separated allowed azp (e.g. https://homecloud.gavinf.com)
    clerk_publishable_key: str = ""   # public; surfaced to the SPA via GET /api/config

    # Console
    frontend_origin: str = ""          # comma-separated CORS origins for the console SPA
    console_url: str = ""              # e.g. https://homecloud.gavinf.com


settings = Settings()
