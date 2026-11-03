output "api_url" {
  value = "https://${local.api_host}"
}

# The Terraform-made part of the cluster's `homecloud` Secret. Copy it into Infisical
# (homecloud project, prod) from:
#
#   terraform output -raw tunnel_token
output "tunnel_token" {
  sensitive = true
  value     = data.cloudflare_zero_trust_tunnel_cloudflared_token.api.token
}
