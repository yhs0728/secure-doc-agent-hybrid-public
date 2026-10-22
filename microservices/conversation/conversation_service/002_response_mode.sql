-- Additive metadata; previous images can keep writing the existing fields.
ALTER TABLE messages ADD COLUMN response_mode text NOT NULL DEFAULT 'generated';
ALTER TABLE messages ADD COLUMN response_reason text NOT NULL DEFAULT '';
