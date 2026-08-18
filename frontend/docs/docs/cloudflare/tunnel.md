# Tunnel & DNS

- Cloudflare holds the zone for `homecloud.dev`.
- Each published web service gets a `CNAME → <tunnel-id>.cfargotunnel.com`, proxied.
- The tunnel ingress sends **all** hostnames to Caddy on the control node.
- Caddy routes by `Host` header to the instance's tailnet IP : port.

> Constraint: Cloudflare doesn't proxy multi-label wildcards (`*.app.homecloud.dev`) on
> non-Enterprise plans — explicit records per published service instead.

Full writeup: `homecloud/docs/plan/00-architecture.md`.
