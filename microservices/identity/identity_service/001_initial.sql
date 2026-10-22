CREATE TABLE users (
 id uuid PRIMARY KEY, email text NOT NULL UNIQUE, display_name text NOT NULL,
 password_hash text, active boolean NOT NULL DEFAULT true,
 token_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE workspaces (
 id uuid PRIMARY KEY, organization_id uuid NOT NULL, name text NOT NULL,
 active boolean NOT NULL DEFAULT true
);
CREATE TABLE memberships (
 workspace_id uuid NOT NULL REFERENCES workspaces(id),
 user_id uuid NOT NULL REFERENCES users(id),
 role text NOT NULL CHECK (role IN ('VIEWER','EDITOR','ADMIN')),
 PRIMARY KEY(workspace_id,user_id)
);
