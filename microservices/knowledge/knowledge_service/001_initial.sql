CREATE TABLE documents (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, created_by uuid NOT NULL,
 external_id text NOT NULL, title text NOT NULL, file_name text NOT NULL,
 checksum text NOT NULL, size_bytes bigint NOT NULL CHECK(size_bytes > 0),
 page_count integer NOT NULL DEFAULT 1, object_key text NOT NULL UNIQUE,
 state text NOT NULL DEFAULT 'PENDING'
   CHECK(state IN ('PENDING','READY','FAILED','DELETING','DELETED')),
 staged_content bytea, chunk_count integer NOT NULL DEFAULT 0,
 error_code text, created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX documents_name_active ON documents(workspace_id,file_name) WHERE state <> 'DELETED';
CREATE UNIQUE INDEX documents_external_active ON documents(workspace_id,external_id) WHERE state <> 'DELETED';
CREATE UNIQUE INDEX documents_checksum_active ON documents(workspace_id,checksum) WHERE state <> 'DELETED';
CREATE INDEX documents_workspace ON documents(workspace_id,state);
CREATE TABLE jobs (
 id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES documents(id),
 workspace_id uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('INDEX','DELETE')),
 status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','RUNNING','DONE','FAILED')),
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 leased_until timestamptz, lease_token uuid, error_code text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_pending ON jobs(status,available_at);
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_documents ON documents USING
 (workspace_id::text = current_setting('app.workspace_id',true))
 WITH CHECK (workspace_id::text = current_setting('app.workspace_id',true));
