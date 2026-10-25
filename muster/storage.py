import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(root: Path):
    db = sqlite3.connect(root / "muster.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    for directory in ("sources", "knowledge", "publications", "browser-profile"):
        (root / directory).mkdir(exist_ok=True)
    with connect(root) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 11:
            raise RuntimeError("This database needs a newer version of Muster.")
        if version == 0:
            db.executescript("""
                BEGIN;
                CREATE TABLE collections (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY,
                    collection_id INTEGER NOT NULL REFERENCES collections(id),
                    url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued'
                        CHECK(status IN ('queued','collecting','captured','failed','blocked')),
                    error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(collection_id, url)
                );
                CREATE TABLE import_previews (
                    token TEXT PRIMARY KEY, name TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                PRAGMA user_version = 1;
                COMMIT;
            """)
        if version < 2:
            db.executescript("""
                BEGIN;
                CREATE TABLE captures (
                    id TEXT PRIMARY KEY,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    captured_at TEXT NOT NULL,
                    final_url TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('captured','blocked','failed')),
                    error TEXT,
                    metadata TEXT NOT NULL
                );
                CREATE INDEX captures_job ON captures(job_id);
                PRAGMA user_version = 2;
                COMMIT;
            """)
        if version < 3:
            db.executescript("""
                BEGIN;
                CREATE TABLE collection_schemas (
                    collection_id INTEGER PRIMARY KEY REFERENCES collections(id),
                    revision INTEGER NOT NULL DEFAULT 0,
                    fields TEXT NOT NULL DEFAULT '[]',
                    guidance TEXT NOT NULL DEFAULT '',
                    schema_id TEXT, accepted_json TEXT, accepted_at TEXT,
                    proposal_id TEXT REFERENCES schema_requests(id),
                    CHECK ((accepted_at IS NULL AND schema_id IS NULL AND accepted_json IS NULL)
                        OR (accepted_at IS NOT NULL AND schema_id IS NOT NULL AND accepted_json IS NOT NULL))
                );
                CREATE TABLE schema_requests (
                    id TEXT PRIMARY KEY,
                    collection_id INTEGER NOT NULL REFERENCES collection_schemas(collection_id),
                    revision INTEGER NOT NULL,
                    provider TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('preview','sending','suggested','failed','discarded')),
                    result TEXT, error TEXT, consent_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TRIGGER accepted_schema_no_update BEFORE UPDATE ON collection_schemas
                    WHEN OLD.accepted_at IS NOT NULL
                    BEGIN SELECT RAISE(ABORT, 'Accepted fields cannot be changed.'); END;
                CREATE TRIGGER accepted_schema_no_delete BEFORE DELETE ON collection_schemas
                    WHEN OLD.accepted_at IS NOT NULL
                    BEGIN SELECT RAISE(ABORT, 'Accepted fields cannot be deleted.'); END;
                PRAGMA user_version = 3;
                COMMIT;
            """)
        if version < 4:
            db.executescript("""
                BEGIN;
                ALTER TABLE jobs ADD COLUMN input_rows TEXT NOT NULL DEFAULT '[]';
                PRAGMA user_version = 4;
                COMMIT;
            """)
        if version < 5:
            db.executescript("""
                BEGIN;
                CREATE TABLE extraction_batches (
                    id TEXT PRIMARY KEY,
                    collection_id INTEGER NOT NULL REFERENCES collections(id),
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('preview','running','complete','failed')),
                    consent_at TEXT, error TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE extractions (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES extraction_batches(id),
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    capture_id TEXT NOT NULL REFERENCES captures(id), schema_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('preview','queued','running','complete','failed')),
                    result TEXT, error TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    finished_at TEXT
                );
                CREATE INDEX extractions_job ON extractions(job_id,created_at);
                PRAGMA user_version = 5;
                COMMIT;
            """)
        if version < 6:
            db.executescript("""
                BEGIN;
                CREATE TABLE reviews (
                    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
                    extraction_id TEXT NOT NULL REFERENCES extractions(id),
                    values_json TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'needs_review'
                        CHECK(status IN ('needs_review','reviewed','excluded')),
                    exclusion_reason TEXT NOT NULL DEFAULT '',
                    corrections TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    reviewed_at TEXT
                );
                PRAGMA user_version = 6;
                COMMIT;
            """)
        if version < 7:
            db.executescript("""
                BEGIN;
                CREATE TABLE knowledge_articles (
                    id TEXT PRIMARY KEY, collection_id INTEGER NOT NULL REFERENCES collections(id),
                    title TEXT NOT NULL, body TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    path TEXT, updated_at TEXT
                );
                CREATE TABLE knowledge_revisions (
                    id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES knowledge_articles(id),
                    revision INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                    path TEXT NOT NULL, provenance TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(article_id,revision)
                );
                CREATE TABLE knowledge_requests (
                    id TEXT PRIMARY KEY, collection_id INTEGER NOT NULL REFERENCES collections(id),
                    article_id TEXT REFERENCES knowledge_articles(id), article_revision INTEGER,
                    job_id INTEGER REFERENCES reviews(job_id), review_revision INTEGER,
                    provider TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL
                        CHECK(status IN ('preview','sending','suggested','failed','accepted','dismissed')),
                    result TEXT, error TEXT, consent_at TEXT, resolved_at TEXT,
                    accepted_article_id TEXT REFERENCES knowledge_articles(id), accepted_title TEXT, accepted_body TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                PRAGMA user_version = 7;
                COMMIT;
            """)
        if version < 8:
            db.executescript("""
                BEGIN;
                CREATE TABLE publication_exclusions (
                    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
                    reason TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE publications (
                    id TEXT PRIMARY KEY, collection_id INTEGER NOT NULL REFERENCES collections(id),
                    version INTEGER NOT NULL, path TEXT NOT NULL, manifest_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL, example_count INTEGER NOT NULL,
                    UNIQUE(collection_id,version)
                );
                CREATE TRIGGER publication_no_update BEFORE UPDATE ON publications
                    BEGIN SELECT RAISE(ABORT, 'Published versions cannot be changed.'); END;
                CREATE TRIGGER publication_no_delete BEFORE DELETE ON publications
                    BEGIN SELECT RAISE(ABORT, 'Published versions cannot be deleted.'); END;
                PRAGMA user_version = 8;
                COMMIT;
            """)
        if version < 9:
            db.executescript("""
                BEGIN;
                ALTER TABLE jobs ADD COLUMN removed INTEGER NOT NULL DEFAULT 0 CHECK(removed IN (0,1));
                ALTER TABLE import_previews ADD COLUMN collection_id INTEGER REFERENCES collections(id);
                PRAGMA user_version = 9;
                COMMIT;
            """)
        if version < 10:
            db.executescript("""
                BEGIN;
                CREATE TABLE connector_permissions (
                    collection_id INTEGER NOT NULL REFERENCES collections(id), name TEXT NOT NULL,
                    config_hash TEXT NOT NULL, PRIMARY KEY(collection_id,name)
                );
                CREATE TABLE connector_calls (
                    id TEXT PRIMARY KEY, collection_id INTEGER NOT NULL REFERENCES collections(id),
                    name TEXT NOT NULL, tool TEXT NOT NULL, arguments TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT, error TEXT, created_at TEXT NOT NULL
                );
                PRAGMA user_version = 10;
                COMMIT;
            """)
        if version < 11:
            db.executescript("""
                BEGIN;
                CREATE TABLE rebuild_observations (
                    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
                    collection_id INTEGER NOT NULL REFERENCES collections(id), observations TEXT NOT NULL
                );
                PRAGMA user_version = 11;
                COMMIT;
            """)
        db.execute(
            "UPDATE connector_calls SET status='failed',error='Lookup interrupted. Retry explicitly.' WHERE status='running'"
        )
        db.execute(
            "UPDATE knowledge_requests SET status='failed',error='The suggestion was interrupted. Articles are unchanged. Check the preview and consent again to retry.' WHERE status='sending'"
        )
        db.execute(
            "UPDATE extractions SET status='failed',error='Extraction was interrupted. Prepare a new preview and consent again; original sources and earlier results are unchanged.' WHERE status IN ('queued','running')"
        )
        db.execute(
            "UPDATE extraction_batches SET status='failed',error='Extraction was interrupted. No requests are resumed automatically.' WHERE status='running'"
        )
        db.execute(
            "UPDATE schema_requests SET status='failed', error='The suggestion was interrupted. Your saved fields and original pages are unchanged. Check the preview and consent again to retry.' WHERE status='sending'"
        )
        # An interrupted browser visit must never look successful after restart.
        db.execute(
            "UPDATE jobs SET status='failed', error='Collection was interrupted. Retry this page.' WHERE status='collecting'"
        )
