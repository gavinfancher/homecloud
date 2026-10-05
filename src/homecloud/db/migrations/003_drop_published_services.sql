-- Public web-service publishing (Caddy + Cloudflare records) is gone;
-- services on an instance are reached over the tailnet by name instead.
ALTER TABLE instances DROP COLUMN web;
