"""Application configuration. No secrets are hardcoded.

Secrets (session key + hashing pepper) come from environment variables
LOCAL_NEWS_SECRET_KEY / LOCAL_NEWS_PEPPER, or are generated on first run and
stored in instance/ (which must never be committed or shared).
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _read_or_create_secret(filename: str, env_name: str) -> str:
    value = os.environ.get(env_name)
    if value:
        return value
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    path = INSTANCE_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_hex(32)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def build_config() -> dict:
    env = os.environ.get("LOCAL_NEWS_ENV", "development").lower()
    return {
        "ENV_NAME": env,                                   # 'development' or 'production'
        # Dummy citizens are only ever seeded in development.
        "SEED_DUMMY_CITIZENS": env == "development",
        "SECRET_KEY": _read_or_create_secret("secret.key", "LOCAL_NEWS_SECRET_KEY"),
        "CITIZEN_PEPPER": _read_or_create_secret("pepper.key", "LOCAL_NEWS_PEPPER"),
        "HASH_METHOD": "scrypt",
        "DATABASE": os.environ.get("LOCAL_NEWS_DATABASE", str(INSTANCE_DIR / "local_news.db")),
        "SCHEMA_FILE": str(BASE_DIR / "schema.sql"),
        "LOCATIONS_SEED_FILE": str(BASE_DIR / "data" / "locations_seed.csv"),
        "DUMMY_CITIZENS_FILE": str(BASE_DIR / "data" / "dummy_citizens.json"),
        # Sessions / cookies
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": os.environ.get("LOCAL_NEWS_SECURE_COOKIES", "0") == "1",
        "PERMANENT_SESSION_LIFETIME": 60 * 60 * 24 * 7,
        # Uploads
        "UPLOAD_FOLDER": os.environ.get("LOCAL_NEWS_UPLOAD_FOLDER", str(BASE_DIR / "static" / "uploads")),
        # Optional, clearly labelled Ahmedabad sample content for a demo deployment.
        "SEED_AHMEDABAD_DEMO_NEWS": os.environ.get("LOCAL_NEWS_SEED_AHMEDABAD_DEMO_NEWS", "0") == "1",
        "MAX_IMAGE_BYTES": 2 * 1024 * 1024,                # 2 MB per image
        "MAX_IMAGES_PER_POST": 5,
        "MAX_IMAGE_PIXELS": 40_000_000,
        "MAX_CONTENT_LENGTH": 12 * 1024 * 1024,            # whole request
        # News limits
        "TITLE_MIN": 5,
        "TITLE_MAX": 150,
        "DESCRIPTION_MAX": 1000,
        # Moderation rules (confirmed by the project owner)
        "MIN_TOTAL_VOTES": 5,              # thresholds only apply from this many votes
        "HIDE_MIN_TOTAL_VOTES": 7,         # hiding with Relevant = 0 needs this many total votes
        "ZERO_RELEVANT_BASE": 1,           # Relevant is treated as max(Relevant, 1)
        "HIDE_MULTIPLIER": 3,              # Fake >= 3x Relevant  -> hide globally
        "WARN_MULTIPLIER": 2,              # Fake >= 2x Relevant  -> chance deducted + window
        "DELETION_WINDOW_MINUTES": 15,
        "INITIAL_REPUTATION": 100,
        "MAX_REPUTATION": 100,
        "NEWS_PUBLISH_REWARD": 3,             # +3 RP for each successfully published post
        "RESTRICT_AFTER_POSTS": 5,         # MORE than 5 distinct 2x posts -> read-only account
        # Brute-force protection
        "LOGIN_MAX_FAILURES": 5,
        "LOGIN_IP_MAX_FAILURES": 20,
        "LOGIN_LOCK_MINUTES": 15,
        # Rate limits: action -> (max events, window seconds)
        "RATE_LIMITS": {
            "post": (5, 3600),
            "vote": (40, 60),
            "save": (60, 60),
            "register": (10, 3600),
            "location": (30, 60),
        },
    }
