ALTER TABLE jobs ADD COLUMN started_at timestamptz;
ALTER TABLE jobs ADD COLUMN finished_at timestamptz;
ALTER TABLE jobs ADD COLUMN preparation_ms double precision;
ALTER TABLE jobs ADD COLUMN publication_ms double precision;
ALTER TABLE jobs ADD COLUMN lock_wait_ms double precision;
