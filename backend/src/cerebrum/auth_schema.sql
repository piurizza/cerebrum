CREATE TABLE IF NOT EXISTS users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT NOT NULL UNIQUE,
    password_hash         TEXT NOT NULL,
    is_admin              INTEGER NOT NULL DEFAULT 0,
    is_active             INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until          TEXT
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL,
    family_id  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family_id ON refresh_tokens(family_id);
-- Every refresh rotation looks this up by exact token_hash (accounts/sessions.py's
-- refresh_session()); without this index, a table that only ever grows (rotation
-- inserts a new row per refresh and never prunes) forces a full scan on a lookup
-- that runs roughly every access-token TTL for every active session.
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);

CREATE TABLE IF NOT EXISTS api_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    name         TEXT NOT NULL,
    token_hash   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_user_id ON api_tokens(user_id);
-- Every request authenticated by a personal API token looks this up by
-- exact token_hash (auth.py's _verify_api_token()) -- same rationale as
-- refresh_tokens.token_hash above.
CREATE INDEX IF NOT EXISTS idx_api_tokens_token_hash ON api_tokens(token_hash);

CREATE TABLE IF NOT EXISTS invites (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT NOT NULL,
    created_by   INTEGER NOT NULL REFERENCES users(id),
    expires_at   TEXT NOT NULL,
    consumed_at  TEXT,
    consumed_by  INTEGER REFERENCES users(id)
);
-- Same rationale as the two token_hash indexes above -- invite redemption
-- (accounts/service.py's _find_valid_invite_token_hash()) looks this up by
-- exact hash too; cheap to add alongside the other two while touching this
-- file, even though invite volume is low at this app's household scale.
CREATE INDEX IF NOT EXISTS idx_invites_token_hash ON invites(token_hash);
