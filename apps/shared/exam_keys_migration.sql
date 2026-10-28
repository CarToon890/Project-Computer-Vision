CREATE TABLE IF NOT EXISTS omr_exam_keys (
  id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{32}$'),
  name text NOT NULL,
  answers jsonb NOT NULL,
  rules jsonb NOT NULL,
  demo_owner_hash text,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE INDEX IF NOT EXISTS omr_exam_keys_owner ON omr_exam_keys(demo_owner_hash, created_at DESC) WHERE deleted_at IS NULL;
ALTER TABLE omr_exam_keys ADD COLUMN IF NOT EXISTS parent_id text;
ALTER TABLE omr_exam_keys ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;
