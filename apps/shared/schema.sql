-- Apply only after the free database is linked and environment keys are verified.
CREATE TABLE IF NOT EXISTS omr_jobs (
  id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{32}$'),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','ready','processing','complete','failed','interrupted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  images_expires_at timestamptz NOT NULL DEFAULT now() + interval '7 days',
  sources jsonb NOT NULL DEFAULT '{}',
  result jsonb,
  reviews jsonb NOT NULL DEFAULT '{"cnn":{},"cla":{}}',
  grading jsonb,
  revision integer NOT NULL DEFAULT 0,
  attempt_id text,
  error_code text,
  error_message text
);
CREATE TABLE IF NOT EXISTS omr_engine_slot (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  job_id text REFERENCES omr_jobs(id),
  attempt_id text,
  expires_at timestamptz
);
ALTER TABLE omr_jobs ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE omr_jobs ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false;
INSERT INTO omr_engine_slot(singleton) VALUES (true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS omr_storage_usage (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  used_bytes bigint NOT NULL DEFAULT 0 CHECK (used_bytes >= 0),
  cap_bytes bigint NOT NULL DEFAULT 800000000 CHECK (cap_bytes > 0)
);
INSERT INTO omr_storage_usage(singleton) VALUES (true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS omr_blobs (
  pathname text PRIMARY KEY,
  job_id text REFERENCES omr_jobs(id),
  bytes bigint NOT NULL CHECK (bytes >= 0),
  status text NOT NULL CHECK (status IN ('reserved','live','deleting')),
  kind text NOT NULL CHECK (kind IN ('model','source','derived')),
  expires_at timestamptz,
  CHECK ((kind = 'model' AND job_id IS NULL AND expires_at IS NULL)
      OR (kind <> 'model' AND job_id IS NOT NULL AND expires_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS omr_blobs_expiry ON omr_blobs(expires_at) WHERE expires_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS omr_sessions (
  token_hash text PRIMARY KEY,
  password_version text NOT NULL,
  expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS omr_login_attempts (
  ip_hash text PRIMARY KEY,
  window_start timestamptz NOT NULL,
  failures integer NOT NULL DEFAULT 0
);
