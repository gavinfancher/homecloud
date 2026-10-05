-- One configurable base image replaces the multi-distro source catalog.
--
-- base_image_config is the single editable definition. Every build snapshots
-- it into base_images and produces its own Proxmox template, so editing the
-- config or rebuilding never changes an instance that already exists.

CREATE TABLE base_image_config (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- A cloud image from a dated Ubuntu release directory; its checksum is
    -- read from SHA256SUMS in the same directory at build time.
    image_url       TEXT NOT NULL,
    packages        JSONB NOT NULL DEFAULT '[]',
    -- Extra #cloud-config (YAML mapping) merged into the bake user-data.
    extra_user_data TEXT NOT NULL DEFAULT '',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO base_image_config (image_url, packages) VALUES (
    'https://cloud-images.ubuntu.com/releases/resolute/release-20260927/ubuntu-26.04-server-cloudimg-amd64.img',
    '["curl", "ca-certificates", "btop", "neovim", "tmux", "avahi-daemon"]'
);

CREATE TABLE base_images (
    id              SERIAL PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'building'
                    CHECK (status IN ('building', 'ready', 'failed')),
    image_url       TEXT NOT NULL,
    sha256          TEXT,
    ssh_keys        JSONB NOT NULL DEFAULT '[]',
    packages        JSONB NOT NULL DEFAULT '[]',
    extra_user_data TEXT NOT NULL DEFAULT '',
    template_vmid   INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    built_at        TIMESTAMPTZ
);

-- NULL for instances cloned from a template that predates base images.
ALTER TABLE instances ADD COLUMN base_image_id INTEGER REFERENCES base_images (id) ON DELETE SET NULL;
ALTER TABLE instances ADD COLUMN tailscale_device_id TEXT;
ALTER TABLE instances DROP COLUMN source_id;

DROP TABLE cloud_images;
