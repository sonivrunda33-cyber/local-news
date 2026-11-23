"""SQLite access layer: connections, transactions, schema setup and seeding."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app, g

TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def ts(dt: datetime) -> str:
    return dt.strftime(TS_FORMAT)


def now_str() -> str:
    return ts(utcnow())


def minutes_ago_str(minutes: float) -> str:
    return ts(utcnow() - timedelta(minutes=minutes))


def parse_ts(value: str | None):
    return datetime.strptime(value, TS_FORMAT) if value else None


def connect(path: str) -> sqlite3.Connection:
    # isolation_level=None -> we control transactions explicitly (BEGIN IMMEDIATE).
    conn = sqlite3.connect(path, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction(db: sqlite3.Connection):
    """BEGIN IMMEDIATE takes the write lock up front, which prevents race
    conditions between concurrent votes / moderation decisions."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def init_db(app) -> None:
    """Create the schema, load locations and (development only) dummy citizens."""
    from services import citizen_verification, locations

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    db = connect(app.config["DATABASE"])
    try:
        db.executescript(Path(app.config["SCHEMA_FILE"]).read_text(encoding="utf-8"))
        db.execute("PRAGMA foreign_keys = ON")
        # Lightweight migration for existing databases from the chances-based prototype.
        user_cols = {r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()}
        if "reputation_points" not in user_cols:
            db.execute("ALTER TABLE users ADD COLUMN reputation_points INTEGER NOT NULL DEFAULT 100")
        if "news_filter_location_id" not in user_cols:
            db.execute("ALTER TABLE users ADD COLUMN news_filter_location_id INTEGER REFERENCES locations(id)")
        event_cols = {r["name"] for r in db.execute("PRAGMA table_info(moderation_events)").fetchall()}
        if "points_deducted" not in event_cols:
            db.execute("ALTER TABLE moderation_events ADD COLUMN points_deducted INTEGER NOT NULL DEFAULT 0")
        if "penalty_category" not in event_cols:
            db.execute("ALTER TABLE moderation_events ADD COLUMN penalty_category TEXT")
        event_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='moderation_events'").fetchone()[0]
        if "reputation_ban" not in event_sql:
            db.execute("DROP INDEX IF EXISTS ux_events_post_threshold")
            db.execute("DROP INDEX IF EXISTS ix_events_user")
            db.execute("ALTER TABLE moderation_events RENAME TO moderation_events_old")
            db.execute("CREATE TABLE moderation_events (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER REFERENCES news_posts(id), user_id INTEGER NOT NULL REFERENCES users(id), event_type TEXT NOT NULL CHECK (event_type IN ('threshold_2x','hidden_3x','chance_restored','account_restricted','reputation_ban')), chance_deducted INTEGER NOT NULL DEFAULT 0 CHECK (chance_deducted IN (0,1)), restored INTEGER NOT NULL DEFAULT 0 CHECK (restored IN (0,1)), details TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')), points_deducted INTEGER NOT NULL DEFAULT 0 CHECK (points_deducted BETWEEN 0 AND 5), penalty_category TEXT CHECK (penalty_category IN ('False','Misleading','Inaccurate')))")
            db.execute("INSERT INTO moderation_events (id,post_id,user_id,event_type,chance_deducted,restored,details,created_at,points_deducted,penalty_category) SELECT id,post_id,user_id,event_type,chance_deducted,restored,details,created_at,points_deducted,penalty_category FROM moderation_events_old")
            db.execute("DROP TABLE moderation_events_old")
            db.execute("CREATE UNIQUE INDEX ux_events_post_threshold ON moderation_events(post_id,event_type) WHERE event_type IN ('threshold_2x','hidden_3x')")
            db.execute("CREATE INDEX ix_events_user ON moderation_events(user_id,event_type)")
        # Legacy chance fields are intentionally no longer used by the application.
        locations.seed_if_empty(db, app.config["LOCATIONS_SEED_FILE"])
        if app.config["SEED_DUMMY_CITIZENS"]:
            citizen_verification.seed_dummy_citizens(
                db, app.config["DUMMY_CITIZENS_FILE"],
                app.config["CITIZEN_PEPPER"], app.config["HASH_METHOD"])
        if app.config.get("SEED_AHMEDABAD_DEMO_NEWS", False):
            from services import demo_seed
            demo_seed.seed_ahmedabad_demo_news(db, app.config)
    finally:
        db.close()
