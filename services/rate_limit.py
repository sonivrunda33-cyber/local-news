"""Persistent (SQLite) rate limiting and login brute-force protection."""
from flask import current_app

from database import minutes_ago_str, transaction


class RateLimited(Exception):
    pass


def check_and_record(db, key: str, action: str) -> None:
    """Record one event; raise RateLimited if the per-action limit is exceeded."""
    limit, window = current_app.config["RATE_LIMITS"][action]
    since = minutes_ago_str(window / 60)
    with transaction(db):
        count = db.execute(
            "SELECT COUNT(*) FROM rate_events WHERE key=? AND action=? AND created_at>=?",
            (key, action, since)).fetchone()[0]
        if count >= limit:
            raise RateLimited(f"Too many requests. Please wait a bit and try again.")
        db.execute("INSERT INTO rate_events (key, action) VALUES (?, ?)", (key, action))
        db.execute("DELETE FROM rate_events WHERE created_at < ?", (minutes_ago_str(120),))


# ---- login brute-force protection -------------------------------------------
def _failures(db, key: str) -> int:
    since = minutes_ago_str(current_app.config["LOGIN_LOCK_MINUTES"])
    return db.execute("SELECT COUNT(*) FROM login_attempts WHERE key=? AND created_at>=?",
                      (key, since)).fetchone()[0]


def login_locked(db, citizen_id: str, ip: str) -> bool:
    cfg = current_app.config
    return (_failures(db, f"citizen:{citizen_id}") >= cfg["LOGIN_MAX_FAILURES"]
            or _failures(db, f"ip:{ip}") >= cfg["LOGIN_IP_MAX_FAILURES"])


def record_login_failure(db, citizen_id: str, ip: str) -> None:
    with transaction(db):
        db.execute("INSERT INTO login_attempts (key) VALUES (?)", (f"citizen:{citizen_id}",))
        db.execute("INSERT INTO login_attempts (key) VALUES (?)", (f"ip:{ip}",))
        db.execute("DELETE FROM login_attempts WHERE created_at < ?", (minutes_ago_str(24 * 60),))


def clear_login_failures(db, citizen_id: str) -> None:
    with transaction(db):
        db.execute("DELETE FROM login_attempts WHERE key=?", (f"citizen:{citizen_id}",))
