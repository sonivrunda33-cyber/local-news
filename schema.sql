-- LOCAL NEWS - SQLite schema
-- Safe to run repeatedly (every statement uses IF NOT EXISTS).
-- Run manually:  sqlite3 instance/local_news.db < schema.sql

PRAGMA foreign_keys = ON;

-- 1. Citizen database (trusted source of identity for registration/login).
--    citizen_id_code is NEVER stored in plain text: only a salted, peppered hash.
CREATE TABLE IF NOT EXISTS citizens (
    citizen_id    TEXT PRIMARY KEY
                  CHECK (length(citizen_id) = 15 AND citizen_id NOT GLOB '*[^0-9]*'),
    code_hash     TEXT NOT NULL,
    citizen_name  TEXT NOT NULL CHECK (length(trim(citizen_name)) > 0),
    is_dummy      INTEGER NOT NULL DEFAULT 0 CHECK (is_dummy IN (0, 1)),  -- 1 = DUMMY / TEST DATA
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. Locations: State/UT -> City/District -> Locality/Area (self-referencing tree)
CREATE TABLE IF NOT EXISTS locations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id  INTEGER REFERENCES locations(id) ON DELETE CASCADE,
    level      TEXT NOT NULL CHECK (level IN ('state', 'city', 'area')),
    name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
    CHECK ((level = 'state' AND parent_id IS NULL) OR (level <> 'state' AND parent_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_locations_unique
    ON locations (COALESCE(parent_id, 0), level, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_locations_parent ON locations (parent_id);

-- 3. Users. The name is copied from the citizen record and is permanent (no username).
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    citizen_id           TEXT NOT NULL UNIQUE REFERENCES citizens(citizen_id),  -- one account per Citizen ID
    name                 TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'restricted', 'banned')),
    reputation_points   INTEGER NOT NULL DEFAULT 100 CHECK (reputation_points BETWEEN 0 AND 100),
    current_location_id  INTEGER REFERENCES locations(id),
    news_filter_location_id INTEGER REFERENCES locations(id),  -- saved 'Choose news location' filter (NULL = my location)
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 4. Followed locations (many per user)
CREATE TABLE IF NOT EXISTS followed_locations (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    location_id  INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, location_id)
);

-- 5. News posts. Posts are never edited. Deleting is a soft delete (status = 'deleted')
--    so moderation history and ban counting stay consistent.
CREATE TABLE IF NOT EXISTS news_posts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(id),
    title              TEXT NOT NULL CHECK (length(title) BETWEEN 5 AND 150),
    description        TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 1000),
    location_id        INTEGER NOT NULL REFERENCES locations(id),
    state_id           INTEGER NOT NULL REFERENCES locations(id),
    city_id            INTEGER REFERENCES locations(id),
    area_id            INTEGER REFERENCES locations(id),
    status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'hidden', 'deleted')),
    relevant_count     INTEGER NOT NULL DEFAULT 0 CHECK (relevant_count >= 0),
    fake_count         INTEGER NOT NULL DEFAULT 0 CHECK (fake_count >= 0),
    window_expires_at  TEXT,            -- end of the 15-minute deletion window (set at the 2x threshold)
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at         TEXT
);
CREATE INDEX IF NOT EXISTS ix_posts_status_created ON news_posts (status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_posts_user ON news_posts (user_id);
CREATE INDEX IF NOT EXISTS ix_posts_area ON news_posts (area_id, status);
CREATE INDEX IF NOT EXISTS ix_posts_city ON news_posts (city_id, status);
CREATE INDEX IF NOT EXISTS ix_posts_state ON news_posts (state_id, status);

-- 6. Images (max 5 per post). Only a random server-generated file name is stored.
CREATE TABLE IF NOT EXISTS news_images (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id   INTEGER NOT NULL REFERENCES news_posts(id) ON DELETE CASCADE,
    filename  TEXT NOT NULL UNIQUE,
    position  INTEGER NOT NULL CHECK (position BETWEEN 1 AND 5),
    UNIQUE (post_id, position)
);

-- 7. Votes. One vote per user per post. A FAKE vote must carry a reason.
CREATE TABLE IF NOT EXISTS news_votes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER NOT NULL REFERENCES news_posts(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    vote        TEXT NOT NULL CHECK (vote IN ('relevant', 'fake')),
    fake_reason TEXT CHECK (fake_reason IN ('False', 'Misleading', 'Inaccurate')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (post_id, user_id),
    CHECK ((vote = 'fake' AND fake_reason IS NOT NULL) OR (vote = 'relevant' AND fake_reason IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_votes_user ON news_votes (user_id);

-- 8. Saved news (private to the user). Rows survive post deletion/hiding so the
--    profile can show "no longer available" instead of silently losing the entry.
CREATE TABLE IF NOT EXISTS saved_news (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id   INTEGER NOT NULL REFERENCES news_posts(id) ON DELETE CASCADE,
    saved_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, post_id)
);

-- 9. User settings (theme persists across logout/login)
CREATE TABLE IF NOT EXISTS user_settings (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme       TEXT NOT NULL DEFAULT 'light' CHECK (theme IN ('light', 'night')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 10. Account restrictions. 'read_only' = may log in and read, but cannot vote or publish.
CREATE TABLE IF NOT EXISTS account_restrictions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    restriction_type  TEXT NOT NULL CHECK (restriction_type IN ('read_only')),
    reason            TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, restriction_type)
);

-- 11. Moderation events (audit trail of automated decisions)
CREATE TABLE IF NOT EXISTS moderation_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id          INTEGER REFERENCES news_posts(id),
    user_id          INTEGER NOT NULL REFERENCES users(id),   -- the affected creator
    event_type       TEXT NOT NULL CHECK (event_type IN
                       ('threshold_2x', 'hidden_3x', 'chance_restored', 'account_restricted', 'reputation_ban')),
    chance_deducted  INTEGER NOT NULL DEFAULT 0 CHECK (chance_deducted IN (0, 1)),
    points_deducted INTEGER NOT NULL DEFAULT 0 CHECK (points_deducted BETWEEN 0 AND 5),
    penalty_category TEXT CHECK (penalty_category IN ('False', 'Misleading', 'Inaccurate')),
    restored         INTEGER NOT NULL DEFAULT 0 CHECK (restored IN (0, 1)),
    details          TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
-- A post can trigger each threshold only once (prevents duplicate chance deductions).
CREATE UNIQUE INDEX IF NOT EXISTS ux_events_post_threshold
    ON moderation_events (post_id, event_type)
    WHERE event_type IN ('threshold_2x', 'hidden_3x');
CREATE INDEX IF NOT EXISTS ix_events_user ON moderation_events (user_id, event_type);

-- Supporting tables: brute-force protection and rate limiting
CREATE TABLE IF NOT EXISTS login_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,            -- 'citizen:<id>' or 'ip:<address>'
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_login_attempts_key ON login_attempts (key, created_at);

CREATE TABLE IF NOT EXISTS rate_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,            -- e.g. 'user:12'
    action      TEXT NOT NULL,            -- e.g. 'vote', 'post', 'save'
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_rate_events ON rate_events (key, action, created_at);
