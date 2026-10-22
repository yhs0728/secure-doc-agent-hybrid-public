ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ALTER COLUMN document_id DROP NOT NULL;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('INDEX','DELETE','REBUILD'));
CREATE UNIQUE INDEX one_workspace_rebuild ON jobs(workspace_id) WHERE kind='REBUILD' AND status IN ('PENDING','RUNNING');
