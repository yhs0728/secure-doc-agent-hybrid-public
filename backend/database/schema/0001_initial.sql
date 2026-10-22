-- SecureDoc Agent PostgreSQL baseline schema (revision 0001)
-- This file is immutable after release. Add later changes as new migrations.

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS content;
CREATE SCHEMA IF NOT EXISTS rag;
CREATE SCHEMA IF NOT EXISTS chat;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE TABLE content.storage_objects (
	id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	provider VARCHAR(20) NOT NULL, 
	bucket VARCHAR(255) NOT NULL, 
	object_key TEXT NOT NULL, 
	region VARCHAR(100), 
	etag VARCHAR(255), 
	version_id VARCHAR(255) DEFAULT '' NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	checksum_sha256 VARCHAR(64) NOT NULL, 
	encryption_type VARCHAR(50), 
	provider_metadata JSONB DEFAULT '{}'::jsonb NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	verified_at TIMESTAMP WITH TIME ZONE, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_storage_objects PRIMARY KEY (id), 
	CONSTRAINT uq_storage_objects_provider UNIQUE (provider, bucket, object_key, version_id), 
	CONSTRAINT ck_storage_objects_valid_provider CHECK (provider IN ('LOCAL', 'OCI', 'S3', 'MINIO'))
);
CREATE TABLE identity.users (
	id UUID NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	display_name VARCHAR(200) NOT NULL, 
	status VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL, 
	locale VARCHAR(20) DEFAULT 'ko-KR' NOT NULL, 
	timezone VARCHAR(50) DEFAULT 'Asia/Seoul' NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT ck_users_valid_status CHECK (status IN ('ACTIVE', 'SUSPENDED', 'DELETED')), 
	CONSTRAINT uq_users_email UNIQUE (email)
);
CREATE TABLE identity.organizations (
	id UUID NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	slug VARCHAR(100) NOT NULL, 
	status VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_organizations PRIMARY KEY (id), 
	CONSTRAINT ck_organizations_valid_status CHECK (status IN ('ACTIVE', 'SUSPENDED', 'DELETED')), 
	CONSTRAINT uq_organizations_slug UNIQUE (slug)
);
CREATE TABLE identity.auth_identities (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	provider VARCHAR(50) NOT NULL, 
	provider_subject VARCHAR(500) NOT NULL, 
	password_hash TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_auth_identities PRIMARY KEY (id), 
	CONSTRAINT uq_auth_identities_provider UNIQUE (provider, provider_subject), 
	CONSTRAINT fk_auth_identities_user_id_users FOREIGN KEY(user_id) REFERENCES identity.users (id) ON DELETE CASCADE
);
CREATE TABLE identity.organization_members (
	organization_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	status VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL, 
	joined_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_organization_members PRIMARY KEY (organization_id, user_id), 
	CONSTRAINT ck_organization_members_valid_role CHECK (role IN ('OWNER', 'ADMIN', 'MEMBER', 'AUDITOR')), 
	CONSTRAINT ck_organization_members_valid_status CHECK (status IN ('ACTIVE', 'INVITED', 'SUSPENDED')), 
	CONSTRAINT fk_organization_members_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES identity.organizations (id) ON DELETE CASCADE, 
	CONSTRAINT fk_organization_members_user_id_users FOREIGN KEY(user_id) REFERENCES identity.users (id) ON DELETE CASCADE
);
CREATE TABLE identity.workspaces (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	slug VARCHAR(100) NOT NULL, 
	status VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL, 
	settings JSONB DEFAULT '{}'::jsonb NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_workspaces PRIMARY KEY (id), 
	CONSTRAINT uq_workspaces_organization_id UNIQUE (organization_id, slug), 
	CONSTRAINT ck_workspaces_valid_status CHECK (status IN ('ACTIVE', 'ARCHIVED', 'DELETED')), 
	CONSTRAINT fk_workspaces_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES identity.organizations (id) ON DELETE RESTRICT
);
CREATE TABLE identity.api_keys (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	key_prefix VARCHAR(20) NOT NULL, 
	key_hash VARCHAR(255) NOT NULL, 
	scopes JSONB DEFAULT '[]'::jsonb NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_api_keys PRIMARY KEY (id), 
	CONSTRAINT fk_api_keys_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES identity.organizations (id) ON DELETE CASCADE, 
	CONSTRAINT fk_api_keys_user_id_users FOREIGN KEY(user_id) REFERENCES identity.users (id) ON DELETE CASCADE, 
	CONSTRAINT uq_api_keys_key_prefix UNIQUE (key_prefix)
);
CREATE INDEX ix_api_keys_owner_active ON identity.api_keys (user_id, revoked_at);
CREATE TABLE chat.conversations (
	id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	title VARCHAR(500) NOT NULL, 
	status VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL, 
	model_name VARCHAR(500), 
	generation_options JSONB DEFAULT '{}'::jsonb NOT NULL, 
	archived_at TIMESTAMP WITH TIME ZONE, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_conversations PRIMARY KEY (id), 
	CONSTRAINT ck_conversations_valid_status CHECK (status IN ('ACTIVE', 'ARCHIVED', 'DELETED')), 
	CONSTRAINT fk_conversations_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE, 
	CONSTRAINT fk_conversations_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES identity.users (id) ON DELETE RESTRICT
);
CREATE INDEX ix_conversations_workspace_user_recent ON chat.conversations (workspace_id, created_by_user_id, updated_at) WHERE deleted_at IS NULL;
CREATE TABLE content.documents (
	id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	current_version_id UUID, 
	title VARCHAR(500) NOT NULL, 
	description TEXT, 
	lifecycle_status VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_documents PRIMARY KEY (id), 
	CONSTRAINT ck_documents_valid_lifecycle_status CHECK (lifecycle_status IN ('ACTIVE', 'DELETING', 'DELETED')), 
	CONSTRAINT fk_documents_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_documents_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES identity.users (id) ON DELETE RESTRICT
);
CREATE INDEX ix_documents_workspace_active ON content.documents (workspace_id, created_at) WHERE deleted_at IS NULL;
CREATE TABLE identity.workspace_members (
	workspace_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_workspace_members PRIMARY KEY (workspace_id, user_id), 
	CONSTRAINT ck_workspace_members_valid_role CHECK (role IN ('ADMIN', 'EDITOR', 'VIEWER')), 
	CONSTRAINT fk_workspace_members_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE, 
	CONSTRAINT fk_workspace_members_user_id_users FOREIGN KEY(user_id) REFERENCES identity.users (id) ON DELETE CASCADE
);
CREATE TABLE ops.outbox_events (
	id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	aggregate_type VARCHAR(100) NOT NULL, 
	aggregate_id UUID NOT NULL, 
	event_type VARCHAR(100) NOT NULL, 
	payload JSONB NOT NULL, 
	status VARCHAR(20) DEFAULT 'PENDING' NOT NULL, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	locked_at TIMESTAMP WITH TIME ZONE, 
	published_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_outbox_events PRIMARY KEY (id), 
	CONSTRAINT ck_outbox_events_valid_status CHECK (status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'FAILED')), 
	CONSTRAINT fk_outbox_events_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_outbox_events_available ON ops.outbox_events (available_at, created_at) WHERE status IN ('PENDING', 'FAILED');
CREATE TABLE ops.idempotency_keys (
	id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	key VARCHAR(255) NOT NULL, 
	operation VARCHAR(100) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	response_snapshot JSONB, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_idempotency_keys PRIMARY KEY (id), 
	CONSTRAINT uq_idempotency_keys_workspace_id UNIQUE (workspace_id, operation, key), 
	CONSTRAINT ck_idempotency_keys_valid_status CHECK (status IN ('PROCESSING', 'COMPLETED', 'FAILED')), 
	CONSTRAINT fk_idempotency_keys_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_idempotency_keys_expires ON ops.idempotency_keys (expires_at);
CREATE TABLE ops.audit_logs (
	id BIGSERIAL NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	actor_user_id UUID, 
	action VARCHAR(100) NOT NULL, 
	resource_type VARCHAR(100) NOT NULL, 
	resource_id UUID, 
	request_id VARCHAR(100), 
	ip_address VARCHAR(64), 
	user_agent TEXT, 
	result VARCHAR(30) NOT NULL, 
	details JSONB DEFAULT '{}'::jsonb NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
	CONSTRAINT fk_audit_logs_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES identity.organizations (id) ON DELETE SET NULL, 
	CONSTRAINT fk_audit_logs_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE SET NULL, 
	CONSTRAINT fk_audit_logs_actor_user_id_users FOREIGN KEY(actor_user_id) REFERENCES identity.users (id) ON DELETE SET NULL
);
CREATE INDEX ix_audit_logs_resource ON ops.audit_logs (resource_type, resource_id);
CREATE INDEX ix_audit_logs_workspace_created ON ops.audit_logs (workspace_id, created_at);
CREATE TABLE ops.usage_events (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	workspace_id UUID, 
	user_id UUID, 
	event_type VARCHAR(100) NOT NULL, 
	quantity BIGINT NOT NULL, 
	unit VARCHAR(50) NOT NULL, 
	model_name VARCHAR(500), 
	request_id VARCHAR(100), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_usage_events PRIMARY KEY (id), 
	CONSTRAINT ck_usage_events_nonnegative_quantity CHECK (quantity >= 0), 
	CONSTRAINT fk_usage_events_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES identity.organizations (id) ON DELETE CASCADE, 
	CONSTRAINT fk_usage_events_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE SET NULL, 
	CONSTRAINT fk_usage_events_user_id_users FOREIGN KEY(user_id) REFERENCES identity.users (id) ON DELETE SET NULL
);
CREATE INDEX ix_usage_events_org_created ON ops.usage_events (organization_id, created_at);
CREATE TABLE rag.index_profiles (
	id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	embedding_model VARCHAR(500) NOT NULL, 
	embedding_model_revision VARCHAR(200), 
	embedding_dimension INTEGER NOT NULL, 
	embedding_normalization BOOLEAN DEFAULT 'true' NOT NULL, 
	chunk_size INTEGER NOT NULL, 
	chunk_overlap INTEGER NOT NULL, 
	distance_metric VARCHAR(30) NOT NULL, 
	retrieval_k INTEGER DEFAULT '3' NOT NULL, 
	parser_version VARCHAR(100) NOT NULL, 
	search_options JSONB DEFAULT '{}'::jsonb NOT NULL, 
	config_hash VARCHAR(64) NOT NULL, 
	active BOOLEAN DEFAULT 'false' NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_index_profiles PRIMARY KEY (id), 
	CONSTRAINT uq_index_profiles_workspace_id UNIQUE (workspace_id, name), 
	CONSTRAINT ck_index_profiles_positive_embedding_dimension CHECK (embedding_dimension > 0), 
	CONSTRAINT ck_index_profiles_positive_chunk_size CHECK (chunk_size > 0), 
	CONSTRAINT ck_index_profiles_nonnegative_chunk_overlap CHECK (chunk_overlap >= 0), 
	CONSTRAINT ck_index_profiles_positive_retrieval_k CHECK (retrieval_k > 0), 
	CONSTRAINT ck_index_profiles_valid_distance_metric CHECK (distance_metric IN ('cosinesimil', 'l2', 'innerproduct')), 
	CONSTRAINT fk_index_profiles_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE, 
	CONSTRAINT fk_index_profiles_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES identity.users (id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX ux_index_profiles_workspace_active ON rag.index_profiles (workspace_id) WHERE active = true;
CREATE TABLE chat.messages (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	parent_message_id UUID, 
	created_by_user_id UUID, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	model_name VARCHAR(500), 
	prompt_version VARCHAR(100), 
	input_tokens INTEGER, 
	output_tokens INTEGER, 
	retrieval_duration_ms INTEGER, 
	generation_duration_ms INTEGER, 
	latency_ms INTEGER, 
	requires_human_review BOOLEAN DEFAULT 'false' NOT NULL, 
	error_code VARCHAR(100), 
	metadata JSONB DEFAULT '{}'::jsonb NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_messages PRIMARY KEY (id), 
	CONSTRAINT ck_messages_valid_role CHECK (role IN ('SYSTEM', 'USER', 'ASSISTANT', 'TOOL')), 
	CONSTRAINT ck_messages_valid_status CHECK (status IN ('PENDING', 'STREAMING', 'COMPLETED', 'FAILED', 'CANCELLED')), 
	CONSTRAINT ck_messages_nonnegative_input_tokens CHECK (input_tokens IS NULL OR input_tokens >= 0), 
	CONSTRAINT ck_messages_nonnegative_output_tokens CHECK (output_tokens IS NULL OR output_tokens >= 0), 
	CONSTRAINT fk_messages_conversation_id_conversations FOREIGN KEY(conversation_id) REFERENCES chat.conversations (id) ON DELETE CASCADE, 
	CONSTRAINT fk_messages_parent_message_id_messages FOREIGN KEY(parent_message_id) REFERENCES chat.messages (id) ON DELETE SET NULL, 
	CONSTRAINT fk_messages_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES identity.users (id) ON DELETE SET NULL
);
CREATE INDEX ix_messages_conversation_created ON chat.messages (conversation_id, created_at);
CREATE TABLE content.document_versions (
	id UUID NOT NULL, 
	document_id UUID NOT NULL, 
	version_no INTEGER NOT NULL, 
	original_filename VARCHAR(500) NOT NULL, 
	normalized_filename VARCHAR(500) NOT NULL, 
	media_type VARCHAR(255) NOT NULL, 
	file_extension VARCHAR(20) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	page_count INTEGER DEFAULT '1' NOT NULL, 
	checksum_sha256 VARCHAR(64) NOT NULL, 
	processing_status VARCHAR(30) DEFAULT 'PENDING' NOT NULL, 
	parser_name VARCHAR(100), 
	parser_version VARCHAR(50), 
	created_by_user_id UUID NOT NULL, 
	metadata JSONB DEFAULT '{}'::jsonb NOT NULL, 
	failure_code VARCHAR(100), 
	failure_message TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	ready_at TIMESTAMP WITH TIME ZONE, 
	failed_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_document_versions PRIMARY KEY (id), 
	CONSTRAINT uq_document_versions_document_id UNIQUE (document_id, version_no), 
	CONSTRAINT ck_document_versions_positive_version_no CHECK (version_no >= 1), 
	CONSTRAINT ck_document_versions_nonnegative_size CHECK (size_bytes >= 0), 
	CONSTRAINT ck_document_versions_positive_page_count CHECK (page_count >= 1), 
	CONSTRAINT ck_document_versions_valid_processing_status CHECK (processing_status IN ('PENDING', 'UPLOADING', 'UPLOADED', 'PARSING', 'CHUNKING', 'EMBEDDING', 'INDEXING', 'READY', 'FAILED', 'DELETING', 'DELETED')), 
	CONSTRAINT fk_document_versions_document_id_documents FOREIGN KEY(document_id) REFERENCES content.documents (id) ON DELETE CASCADE, 
	CONSTRAINT fk_document_versions_created_by_user_id_users FOREIGN KEY(created_by_user_id) REFERENCES identity.users (id) ON DELETE RESTRICT
);
CREATE INDEX ix_document_versions_document ON content.document_versions (document_id, version_no);
CREATE TABLE rag.search_indexes (
	id UUID NOT NULL, 
	index_profile_id UUID NOT NULL, 
	workspace_id UUID, 
	backend VARCHAR(20) NOT NULL, 
	physical_index_name VARCHAR(255) NOT NULL, 
	alias_name VARCHAR(255), 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	document_count INTEGER DEFAULT '0' NOT NULL, 
	chunk_count INTEGER DEFAULT '0' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	activated_at TIMESTAMP WITH TIME ZONE, 
	retired_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_search_indexes PRIMARY KEY (id), 
	CONSTRAINT uq_search_indexes_backend UNIQUE (backend, physical_index_name), 
	CONSTRAINT ck_search_indexes_valid_backend CHECK (backend IN ('FAISS', 'OPENSEARCH')), 
	CONSTRAINT ck_search_indexes_valid_status CHECK (status IN ('BUILDING', 'VALIDATING', 'ACTIVE', 'RETIRED', 'FAILED')), 
	CONSTRAINT fk_search_indexes_index_profile_id_index_profiles FOREIGN KEY(index_profile_id) REFERENCES rag.index_profiles (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_search_indexes_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE
);
CREATE TABLE chat.message_feedback (
	id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	rating SMALLINT NOT NULL, 
	reason_code VARCHAR(100), 
	comment TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_message_feedback PRIMARY KEY (id), 
	CONSTRAINT uq_message_feedback_message_id UNIQUE (message_id, user_id), 
	CONSTRAINT ck_message_feedback_valid_rating CHECK (rating IN (-1, 1)), 
	CONSTRAINT fk_message_feedback_message_id_messages FOREIGN KEY(message_id) REFERENCES chat.messages (id) ON DELETE CASCADE, 
	CONSTRAINT fk_message_feedback_user_id_users FOREIGN KEY(user_id) REFERENCES identity.users (id) ON DELETE CASCADE
);
CREATE TABLE content.document_artifacts (
	id UUID NOT NULL, 
	document_version_id UUID NOT NULL, 
	storage_object_id UUID NOT NULL, 
	artifact_type VARCHAR(30) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_document_artifacts PRIMARY KEY (id), 
	CONSTRAINT uq_document_artifacts_document_version_id UNIQUE (document_version_id, artifact_type), 
	CONSTRAINT ck_document_artifacts_valid_artifact_type CHECK (artifact_type IN ('SOURCE', 'EXTRACTED_TEXT', 'PREVIEW', 'THUMBNAIL', 'OCR_RESULT')), 
	CONSTRAINT fk_document_artifacts_document_version_id_document_versions FOREIGN KEY(document_version_id) REFERENCES content.document_versions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_document_artifacts_storage_object_id_storage_objects FOREIGN KEY(storage_object_id) REFERENCES content.storage_objects (id) ON DELETE RESTRICT
);
CREATE TABLE rag.document_chunks (
	id UUID NOT NULL, 
	document_version_id UUID NOT NULL, 
	ordinal INTEGER NOT NULL, 
	page_start INTEGER, 
	page_end INTEGER, 
	char_start INTEGER, 
	char_end INTEGER, 
	content_hash VARCHAR(64) NOT NULL, 
	token_count INTEGER, 
	heading VARCHAR(500), 
	metadata JSONB DEFAULT '{}'::jsonb NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_document_chunks PRIMARY KEY (id), 
	CONSTRAINT uq_document_chunks_document_version_id UNIQUE (document_version_id, ordinal), 
	CONSTRAINT ck_document_chunks_nonnegative_ordinal CHECK (ordinal >= 0), 
	CONSTRAINT ck_document_chunks_nonnegative_tokens CHECK (token_count IS NULL OR token_count >= 0), 
	CONSTRAINT fk_document_chunks_document_version_id_document_versions FOREIGN KEY(document_version_id) REFERENCES content.document_versions (id) ON DELETE CASCADE
);
CREATE INDEX ix_chunks_version_ordinal ON rag.document_chunks (document_version_id, ordinal);
CREATE TABLE rag.document_index_states (
	id UUID NOT NULL, 
	document_version_id UUID NOT NULL, 
	search_index_id UUID NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	expected_chunk_count INTEGER DEFAULT '0' NOT NULL, 
	indexed_chunk_count INTEGER DEFAULT '0' NOT NULL, 
	source_checksum VARCHAR(64) NOT NULL, 
	indexed_at TIMESTAMP WITH TIME ZONE, 
	verified_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(100), 
	error_message TEXT, 
	CONSTRAINT pk_document_index_states PRIMARY KEY (id), 
	CONSTRAINT uq_document_index_states_document_version_id UNIQUE (document_version_id, search_index_id), 
	CONSTRAINT ck_document_index_states_valid_status CHECK (status IN ('PENDING', 'INDEXING', 'INDEXED', 'FAILED', 'DELETED')), 
	CONSTRAINT fk_document_index_states_document_version_id_document_versions FOREIGN KEY(document_version_id) REFERENCES content.document_versions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_document_index_states_search_index_id_search_indexes FOREIGN KEY(search_index_id) REFERENCES rag.search_indexes (id) ON DELETE CASCADE
);
CREATE TABLE rag.ingestion_jobs (
	id UUID NOT NULL, 
	workspace_id UUID NOT NULL, 
	document_version_id UUID, 
	job_type VARCHAR(30) NOT NULL, 
	status VARCHAR(20) DEFAULT 'PENDING' NOT NULL, 
	priority INTEGER DEFAULT '0' NOT NULL, 
	attempt_count INTEGER DEFAULT '0' NOT NULL, 
	max_attempts INTEGER DEFAULT '3' NOT NULL, 
	available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	locked_at TIMESTAMP WITH TIME ZONE, 
	locked_by VARCHAR(200), 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(100), 
	error_message TEXT, 
	error_details JSONB DEFAULT '{}'::jsonb NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_ingestion_jobs PRIMARY KEY (id), 
	CONSTRAINT ck_ingestion_jobs_valid_job_type CHECK (job_type IN ('INGEST_DOCUMENT', 'REINDEX_DOCUMENT', 'DELETE_DOCUMENT', 'REBUILD_INDEX', 'GENERATE_PREVIEW')), 
	CONSTRAINT ck_ingestion_jobs_valid_status CHECK (status IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'FAILED', 'CANCELLED')), 
	CONSTRAINT ck_ingestion_jobs_nonnegative_attempts CHECK (attempt_count >= 0), 
	CONSTRAINT ck_ingestion_jobs_positive_max_attempts CHECK (max_attempts >= 1), 
	CONSTRAINT fk_ingestion_jobs_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE, 
	CONSTRAINT fk_ingestion_jobs_document_version_id_document_versions FOREIGN KEY(document_version_id) REFERENCES content.document_versions (id) ON DELETE CASCADE
);
CREATE INDEX ix_ingestion_jobs_available ON rag.ingestion_jobs (priority, available_at, created_at) WHERE status IN ('PENDING', 'RETRY_WAIT');
CREATE TABLE chat.message_citations (
	id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	document_id UUID, 
	document_version_id UUID, 
	chunk_id UUID, 
	citation_rank INTEGER NOT NULL, 
	relevance_score FLOAT, 
	filename_snapshot VARCHAR(500) NOT NULL, 
	page_start_snapshot INTEGER, 
	page_end_snapshot INTEGER, 
	quote_snapshot TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_message_citations PRIMARY KEY (id), 
	CONSTRAINT uq_message_citations_message_id UNIQUE (message_id, citation_rank), 
	CONSTRAINT ck_message_citations_positive_rank CHECK (citation_rank >= 1), 
	CONSTRAINT fk_message_citations_message_id_messages FOREIGN KEY(message_id) REFERENCES chat.messages (id) ON DELETE CASCADE, 
	CONSTRAINT fk_message_citations_document_id_documents FOREIGN KEY(document_id) REFERENCES content.documents (id) ON DELETE SET NULL, 
	CONSTRAINT fk_message_citations_document_version_id_document_versions FOREIGN KEY(document_version_id) REFERENCES content.document_versions (id) ON DELETE SET NULL, 
	CONSTRAINT fk_message_citations_chunk_id_document_chunks FOREIGN KEY(chunk_id) REFERENCES rag.document_chunks (id) ON DELETE SET NULL
);
ALTER TABLE content.documents ADD CONSTRAINT fk_documents_current_version_id_document_versions FOREIGN KEY(current_version_id) REFERENCES content.document_versions (id) ON DELETE SET NULL;
ALTER TABLE content.storage_objects ADD CONSTRAINT fk_storage_objects_workspace_id_workspaces FOREIGN KEY(workspace_id) REFERENCES identity.workspaces (id) ON DELETE CASCADE;

-- Application roles should set app.user_id inside each transaction with SET LOCAL.
ALTER TABLE content.documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY documents_workspace_access ON content.documents
USING (
    EXISTS (
        SELECT 1
        FROM identity.workspace_members wm
        WHERE wm.workspace_id = documents.workspace_id
          AND wm.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
);

ALTER TABLE content.storage_objects ENABLE ROW LEVEL SECURITY;
CREATE POLICY storage_objects_workspace_access ON content.storage_objects
USING (
    EXISTS (
        SELECT 1 FROM identity.workspace_members wm
        WHERE wm.workspace_id = storage_objects.workspace_id
          AND wm.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
);

ALTER TABLE content.document_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY document_versions_workspace_access ON content.document_versions
USING (
    EXISTS (
        SELECT 1
        FROM content.documents d
        JOIN identity.workspace_members wm ON wm.workspace_id = d.workspace_id
        WHERE d.id = document_versions.document_id
          AND wm.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
);

ALTER TABLE rag.document_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY document_chunks_workspace_access ON rag.document_chunks
USING (
    EXISTS (
        SELECT 1
        FROM content.document_versions dv
        JOIN content.documents d ON d.id = dv.document_id
        JOIN identity.workspace_members wm ON wm.workspace_id = d.workspace_id
        WHERE dv.id = document_chunks.document_version_id
          AND wm.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
);

ALTER TABLE chat.conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY conversations_workspace_access ON chat.conversations
USING (
    EXISTS (
        SELECT 1
        FROM identity.workspace_members wm
        WHERE wm.workspace_id = conversations.workspace_id
          AND wm.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
);

ALTER TABLE chat.messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY messages_workspace_access ON chat.messages
USING (
    EXISTS (
        SELECT 1
        FROM chat.conversations c
        JOIN identity.workspace_members wm ON wm.workspace_id = c.workspace_id
        WHERE c.id = messages.conversation_id
          AND wm.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
    )
);
