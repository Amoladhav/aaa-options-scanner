CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL);
CREATE TABLE settings_revisions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, content_hash TEXT NOT NULL, predecessor TEXT REFERENCES settings_revisions(id));
CREATE TABLE master_versions (id TEXT PRIMARY KEY, observed_at TEXT, content_hash TEXT NOT NULL UNIQUE);
CREATE TABLE master_members (master_id TEXT NOT NULL REFERENCES master_versions(id), symbol TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(master_id,symbol));
CREATE TABLE runs (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, profile TEXT NOT NULL, provider TEXT NOT NULL, operation TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('succeeded','partial')), started_at TEXT NOT NULL, ended_at TEXT NOT NULL, display_timezone TEXT NOT NULL, observation_cutoff TEXT, code_revision TEXT NOT NULL, settings_id TEXT REFERENCES settings_revisions(id), master_id TEXT REFERENCES master_versions(id));
CREATE TABLE artifacts (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE, schema_version INTEGER NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL CHECK(size>=0), availability TEXT NOT NULL CHECK(availability IN ('available','missing','changed')), UNIQUE(run_id,kind));
CREATE TABLE run_inputs (run_id TEXT NOT NULL REFERENCES runs(id), artifact_id TEXT NOT NULL REFERENCES artifacts(id), ordinal INTEGER NOT NULL, PRIMARY KEY(run_id,ordinal), UNIQUE(run_id,artifact_id));
CREATE INDEX artifacts_kind ON artifacts(kind);
