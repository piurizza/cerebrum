CREATE TABLE IF NOT EXISTS notes (
    path         TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    tags         TEXT NOT NULL DEFAULT '[]',
    created      TEXT,
    updated      TEXT,
    content_hash TEXT NOT NULL,
    mtime        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    link_text   TEXT,
    PRIMARY KEY (source_path, target_path, link_text)
);

CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_path);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_path);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    path UNINDEXED,
    title,
    body,
    tokenize='porter'
);

CREATE TABLE IF NOT EXISTS tasks (
    source_path TEXT NOT NULL,
    line        INTEGER NOT NULL,
    checked     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    PRIMARY KEY (source_path, line)
);

CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source_path);
