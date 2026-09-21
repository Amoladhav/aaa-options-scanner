CREATE TABLE workspace_revisions (id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('screener','preferences')), name TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL, predecessor TEXT REFERENCES workspace_revisions(id), source_artifact_id TEXT REFERENCES artifacts(id), created_at TEXT NOT NULL, code_revision TEXT NOT NULL);
CREATE TABLE workspace_heads (kind TEXT NOT NULL, name TEXT NOT NULL, revision_id TEXT NOT NULL REFERENCES workspace_revisions(id), PRIMARY KEY(kind,name));
CREATE INDEX workspace_revision_history ON workspace_revisions(kind,name,created_at);
CREATE TRIGGER workspace_revisions_no_update BEFORE UPDATE ON workspace_revisions BEGIN SELECT RAISE(ABORT,'SETTINGS_IMMUTABLE'); END;
CREATE TRIGGER workspace_revisions_no_delete BEFORE DELETE ON workspace_revisions BEGIN SELECT RAISE(ABORT,'SETTINGS_IMMUTABLE'); END;
