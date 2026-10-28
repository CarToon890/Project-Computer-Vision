CREATE TABLE IF NOT EXISTS omr_exam_sessions (
  id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{32}$'),
  name text NOT NULL,
  demo_owner_hash text,
  grading jsonb NOT NULL,
  revision integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE TABLE IF NOT EXISTS omr_session_sheets (
  id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{32}$'),
  session_id text NOT NULL REFERENCES omr_exam_sessions(id),
  ordinal integer NOT NULL,
  student_label text NOT NULL DEFAULT '',
  current_job_id text NOT NULL REFERENCES omr_jobs(id),
  UNIQUE(session_id, ordinal)
);
CREATE TABLE IF NOT EXISTS omr_session_grading_history (
  session_id text NOT NULL REFERENCES omr_exam_sessions(id),
  revision integer NOT NULL,
  grading jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(session_id,revision)
);
ALTER TABLE omr_jobs ADD COLUMN IF NOT EXISTS session_sheet_id text REFERENCES omr_session_sheets(id);
CREATE INDEX IF NOT EXISTS omr_session_owner_idx ON omr_exam_sessions(demo_owner_hash,created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS omr_job_session_sheet_idx ON omr_jobs(session_sheet_id) WHERE session_sheet_id IS NOT NULL;
