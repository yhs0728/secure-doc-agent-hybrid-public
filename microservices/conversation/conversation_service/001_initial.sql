CREATE TABLE conversations (
 id uuid PRIMARY KEY, workspace_id uuid NOT NULL, user_id uuid NOT NULL,
 title text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_recent ON conversations(workspace_id,user_id,updated_at DESC);
CREATE TABLE messages (
 id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 workspace_id uuid NOT NULL, user_id uuid NOT NULL,
 role text NOT NULL CHECK(role IN ('USER','ASSISTANT')),
 content text NOT NULL, citations jsonb NOT NULL DEFAULT '[]',
 requires_human_review boolean NOT NULL DEFAULT false,
 sequence bigint GENERATED ALWAYS AS IDENTITY,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_order ON messages(conversation_id,sequence);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;
CREATE POLICY own_conversations ON conversations USING
 (workspace_id::text = current_setting('app.workspace_id',true)
  AND user_id::text = current_setting('app.user_id',true))
 WITH CHECK (workspace_id::text = current_setting('app.workspace_id',true)
  AND user_id::text = current_setting('app.user_id',true));
CREATE POLICY own_messages ON messages USING
 (workspace_id::text = current_setting('app.workspace_id',true)
  AND user_id::text = current_setting('app.user_id',true))
 WITH CHECK (workspace_id::text = current_setting('app.workspace_id',true)
  AND user_id::text = current_setting('app.user_id',true));
