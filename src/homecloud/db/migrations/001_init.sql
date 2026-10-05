-- All controller state moves into Postgres: SSH keys, instances and jobs.
--
-- cloud_images predates the migration runner (it was created by
-- SQLAlchemy create_all), so it is created only when missing and keeps the
-- column types that create_all gave it on existing databases.

CREATE TABLE IF NOT EXISTS cloud_images (
    id          VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    distro      VARCHAR(32) NOT NULL,
    version     VARCHAR(32) NOT NULL,
    arch        VARCHAR(16) NOT NULL,
    url         TEXT NOT NULL,
    sha256      VARCHAR(64),
    ssh_user    VARCHAR(32) NOT NULL,
    builtin     BOOLEAN NOT NULL,
    template_id INTEGER,
    imported_at TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

-- Left behind by the image builder that sources replaced.
DROP TABLE IF EXISTS custom_images;

CREATE TABLE ssh_keys (
    id         SERIAL PRIMARY KEY,
    public_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE instances (
    name             TEXT PRIMARY KEY,
    vmid             INTEGER NOT NULL UNIQUE,
    -- NULL for instances cloned from a pre-sources template.
    source_id        TEXT,
    size_id          TEXT NOT NULL DEFAULT 'custom',
    cores            INTEGER,
    memory_mb        INTEGER,
    disk_gb          INTEGER,
    local_ip         TEXT,
    tailscale_ip     TEXT,
    roles            JSONB NOT NULL DEFAULT '[]',
    web              JSONB NOT NULL DEFAULT '[]',
    ports_seen       JSONB,
    ports_scanned_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
    id               TEXT PRIMARY KEY,
    type             TEXT NOT NULL,
    label            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    -- meta is shown in the console; payload is what the handler runs with.
    meta             JSONB NOT NULL DEFAULT '{}',
    payload          JSONB NOT NULL DEFAULT '{}',
    result           JSONB,
    error            TEXT,
    cancel_requested BOOLEAN NOT NULL DEFAULT false,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    heartbeat_at     TIMESTAMPTZ
);

CREATE INDEX jobs_pending_idx ON jobs (created_at) WHERE status = 'pending';
CREATE INDEX jobs_created_idx ON jobs (created_at DESC);

CREATE TABLE job_logs (
    id      BIGSERIAL PRIMARY KEY,
    job_id  TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    level   TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE INDEX job_logs_job_idx ON job_logs (job_id, id);
