# LOCAL NEWS

India-only hyperlocal community news platform. Built with **Python + Flask**, **SQLite** and plain **HTML / CSS / JavaScript** (no frontend framework).

> Votes are **community feedback**, not proof that news is true or false. Automated moderation is a heuristic and cannot judge truth.


## 1A. Render deployment (Flask backend)

This project is a Flask/Python application. **GitHub stores the source code; it does not run Flask.**
Use the included `render.yaml` to deploy the app on Render. GitHub Pages is not suitable because it
serves static files only and cannot run this Python backend.

1. Push the `LOCAL_NEWS` project folder to a GitHub repository.
2. In Render, choose **New + → Blueprint**, connect that repository, and apply `render.yaml`.
3. The blueprint configures Gunicorn, HTTPS cookies, generated secret keys, and a persistent disk at
   `/var/data` for the SQLite database and uploaded images. The included plan is `starter` because
   persistent disks require a paid Render service; Render's free web service has ephemeral storage.
4. Wait for the `/healthz` health check to pass, then open the Render URL.

The persistent disk is mounted for both `local_news.db` and uploaded images. Keep one web-service
instance when using SQLite; do not scale this configuration to multiple instances. Back up the disk
regularly. For a larger multi-instance deployment, migrate SQLite to PostgreSQL and image files to
object storage.

### Demo content and login records

The Render blueprint enables 24 clearly labelled **SAMPLE / DEMO** posts (8 each for Navrangpura,
Satellite and Maninagar). Some cards have generated illustrative graphics marked as sample images;
they are not photographs and the entries are not verified real-world reports. Replace them with
verified reporting before presenting the site as a live-news service. The sample author is a
non-login service account.

Dummy citizen credentials in `data/dummy_citizens.json` are fictional development-only test data
and are deliberately **not** imported in production. Before real people can register, import an
authorized citizen CSV through the Flask CLI, or use your approved identity-data process. Never
commit real Citizen ID Codes or a plain-text credential CSV to GitHub.

The login and registration screens also show the two informational lines requested for this demo.

## 1. Features

- Citizen ID registration and login (Citizen ID + Citizen ID Code, no username, no password). The account name always comes from the Citizen Database and cannot be changed.
- Cascading location picker: State/UT -> City/District -> Locality/Area; follow multiple locations.
- Home page with a featured slideshow and four sections: Area, City, State, India news (a post appears in only one tier).
- Publish news (title, description up to 1000 characters, up to 5 images). Published news cannot be edited; creators can delete.
- RELEVANT / FAKE voting (Fake requires a reason: False, Misleading or Inaccurate), one vote per user per post.
- Automated moderation (no admin), Save/Unsave news, Profile, Settings, Light and Night mode stored in the database.
- Excluded on purpose: tips/UPI/payments, comments, share button, usernames, admin dashboard.

### Moderation rules (as confirmed by the project owner)

| Rule | Behaviour |
|---|---|
| Minimum votes | Thresholds only apply once a post has **5 or more total votes** |
| Zero Relevant | Relevant is treated as `max(Relevant, 1)` |
| Rule A (2x) | Fake >= 2 x Relevant: creator loses **1 chance** (each creator starts with 5), once per post |
| Rule B | At 2x the creator gets a **15-minute deletion window**. Deleting inside it **restores the chance** |
| Rule C (3x) | Fake >= 3 x Relevant: the post is **hidden globally** (the creator can still see and delete it) |
| Rule D | When **more than 5 different posts** of a creator reached 2x (restored ones don't count), the account becomes **read-only**: it can log in and read, but **cannot vote or publish**. There is no recovery |

Hiding a post and restricting an account are separate actions. Every decision is recorded in `moderation_events`.

Assumptions I made where the spec was silent (change them in `config.py` / `services/`):
- Creators cannot vote on their own posts.
- Chances never go below 0; reaching 0 chances has no extra effect by itself.
- Restricted accounts may still save/unsave news (saving is private reading).
- Login is required to read any page (the spec only requires login to vote).
- Deleting is a soft delete so moderation history stays consistent; image files are removed from disk.

## 2. Technology stack

Python 3.10+, Flask, SQLite (built into Python), Pillow (image validation), pytest. Vanilla JavaScript.

## 3. Project structure

```
LOCAL_NEWS/
├── app.py                 Flask app factory, CSRF, security headers, error pages
├── config.py              Settings (no hardcoded secrets)
├── database.py            SQLite connections, transactions, schema + seeding
├── cli.py                 flask commands (init-db, import-citizens, import-locations, show-dev-credentials)
├── schema.sql             Complete SQL schema (also reproduced below)
├── requirements.txt
├── routes/                auth, news, profile, locations, settings (+ common helpers)
├── services/              citizen_verification, moderation, voting, news_service, images,
│                          locations, rate_limit, validation
├── templates/             base, login, register, home, news_detail, create_news, profile, settings, ...
├── static/css, static/js  style.css, main.js, theme.js, news.js, locations.js
├── static/uploads/        uploaded images (random file names)
├── data/                  locations_seed.csv, dummy_citizens.json (DEV ONLY)
├── scripts/               generate_dummy_citizens.py
├── instance/              local_news.db, secret.key, pepper.key (generated; never share)
└── tests/                 test_auth.py, test_news.py, test_voting.py
```

## 4. Install and run (Windows)

1. Install Python 3.10+ from python.org (tick "Add Python to PATH"). Check: `python --version`
2. Open a terminal in the project folder.

**PowerShell**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
python app.py
```

**CMD**
```bat
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser. (macOS/Linux: `source venv/bin/activate`.)

## 5. SQLite initialisation

The database `instance/local_news.db` is created automatically on first start: the app runs `schema.sql`, loads locations from `data/locations_seed.csv` and (development only) seeds the dummy citizens. Seeding is idempotent, so restarts never create duplicates.

Manual options:
```bash
python -m flask --app app init-db                 # re-apply schema + seeds
sqlite3 instance/local_news.db < schema.sql       # run only the schema (needs the sqlite3 CLI)
```
```powershell
python -c "import sqlite3; c=sqlite3.connect('instance/local_news.db'); c.executescript(open('schema.sql').read()); print('ok')"
```
Note: running only `schema.sql` creates empty tables; the app (or `init-db`) adds the locations and dummy citizens.

## 6. Citizen Database configuration

- `LOCAL_NEWS_ENV=development` (default): the 22 dummy citizens below are seeded (marked `is_dummy = 1`).
- `LOCAL_NEWS_ENV=production`: **dummy citizens are never seeded**.
```powershell
$env:LOCAL_NEWS_ENV = "production"      # PowerShell
set LOCAL_NEWS_ENV=production           :: CMD
```
- Codes are stored only as hashes: scrypt over an HMAC-SHA256 of `citizen_id:code` using a secret **pepper** (`instance/pepper.key` or env `LOCAL_NEWS_PEPPER`). Keep the pepper safe: without it no code can be verified. Also set `LOCAL_NEWS_SECRET_KEY` for the session key if you do not want the generated `instance/secret.key`.
- Add real citizens securely from a CSV with columns `Citizen_ID,Citizen_ID_Code,Citizen_Name`, then **delete the CSV** (it holds plain codes):
```bash
python -m flask --app app import-citizens my_citizens.csv
```
- Dev-only listing of dummy credentials (refuses outside development): `python -m flask --app app show-dev-credentials`
- Regenerate dummy data: `python scripts/generate_dummy_citizens.py 22` (delete `instance/local_news.db` afterwards).

## 7. Location data

`data/locations_seed.csv` ships all 36 states/UTs and about 200 cities and localities. It is a starter set, **not complete**. To import or update from any reliable source (e.g. an official or Census-based list) prepare a CSV with columns `state,city,area` (city and area may be blank) and run:
```bash
python -m flask --app app import-locations my_locations.csv
```
The import is idempotent: existing rows are kept, missing ones are added.

## 8. Image upload configuration

Edit `config.py`: `MAX_IMAGES_PER_POST` (5), `MAX_IMAGE_BYTES` (2 MB each), `MAX_IMAGE_PIXELS`, `MAX_CONTENT_LENGTH`, `UPLOAD_FOLDER` (defaults to `static/uploads`; Render overrides it to `/var/data/uploads`). Only JPG/PNG/WEBP are accepted, verified by content (not file name), auto-rotated, metadata stripped, re-encoded and saved under a random name. SVG/HTML/other files are rejected.

## 9. Security summary

Hashed + peppered codes, signed HttpOnly SameSite sessions (cleared on login), CSRF tokens on every POST, login lockout (5 failures / 15 min per Citizen ID, 20 per IP), persistent rate limits, parameterised SQL, `BEGIN IMMEDIATE` transactions for votes and moderation, strict Content-Security-Policy, escaped output, masked Citizen ID on the profile. For HTTPS deployments set `LOCAL_NEWS_SECURE_COOKIES=1`. Do not deploy publicly without review.

## 10. Tables

| Table | Purpose |
|---|---|
| citizens | Trusted Citizen Database: ID, hashed code, name, `is_dummy` |
| users | One account per Citizen ID; name copied from citizens; status, chances, current location |
| locations | State -> City -> Area tree (self-referencing) |
| followed_locations | Locations a user follows |
| news_posts | Posts (status active / hidden / deleted, vote counters, deletion window) |
| news_images | Up to 5 images per post |
| news_votes | One vote per user per post; Fake reason stored separately |
| saved_news | Private saved posts (rows survive deletion so the profile can say "no longer available") |
| user_settings | Theme (light / night) |
| account_restrictions | Read-only restrictions |
| moderation_events | Audit trail (2x, 3x hide, restored chance, account restricted) |
| login_attempts, rate_events | Brute-force protection and rate limiting |

## 11. Complete SQL schema (`schema.sql`)

```sql
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
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'restricted')),
    chances_remaining    INTEGER NOT NULL DEFAULT 5 CHECK (chances_remaining >= 0),
    current_location_id  INTEGER REFERENCES locations(id),
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
                       ('threshold_2x', 'hidden_3x', 'chance_restored', 'account_restricted')),
    chance_deducted  INTEGER NOT NULL DEFAULT 0 CHECK (chance_deducted IN (0, 1)),
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
```

## 12. DEVELOPMENT / TESTING ONLY - dummy citizens

**DUMMY / TEST DATA.** Fictional records for local testing only. They are not real identity numbers and must never be shown on a public site, logged in production, or used in production (the app does not seed them when `LOCAL_NEWS_ENV=production`).

| # | Citizen Name | Citizen ID (15 digits) | Citizen ID Code (8 digits) |
|---|---|---|---|
| 1 | Anjali Khan | `635889319243032` | `25410617` |
| 2 | Arjun Iyer | `127410799292396` | `17572781` |
| 3 | Tanvi Naidu | `209156907973168` | `29324929` |
| 4 | Neha Reddy | `676769144414432` | `82764244` |
| 5 | Neha Banerjee | `408618675623253` | `38369916` |
| 6 | Harleen Joshi | `792611814080239` | `34106055` |
| 7 | Rohan Pillai | `429895033025705` | `33085583` |
| 8 | Isha Shetty | `750164473166008` | `32214991` |
| 9 | Sneha Naidu | `452687288395551` | `33132118` |
| 10 | Harleen Iyer | `565267951667314` | `32117762` |
| 11 | Farhan Patel | `696423210298424` | `63198172` |
| 12 | Harleen Mehta | `254633413457772` | `17563496` |
| 13 | Arjun Pillai | `894709096149707` | `85322981` |
| 14 | Aditya Khan | `740210822075431` | `49465141` |
| 15 | Neha Kaur | `726425355532395` | `94929713` |
| 16 | Gurpreet Sharma | `120009937140126` | `68675122` |
| 17 | Meera Naidu | `796500398169543` | `52627495` |
| 18 | Lakshmi Nair | `497951852433977` | `26358645` |
| 19 | Vikram Khan | `620615173735332` | `16766652` |
| 20 | Deepa Menon | `690253648669860` | `92627518` |
| 21 | Rahul Mehta | `497481812511869` | `51084715` |
| 22 | Siddharth Patel | `400065162072900` | `18826164` |

## 13. Tests

```bash
python -m pytest tests -q
```
71 automated tests cover registration/login of all dummy citizens, hashing, lockout, CSRF, publishing limits, malicious uploads, deletion, saved news, location management, theme persistence, home sections, voting, thresholds, deletion window, restrictions and concurrent voting.

## 14. Troubleshooting

| Problem | Fix |
|---|---|
| `python` not found | Reinstall Python with "Add to PATH", or use `py` |
| `ModuleNotFoundError: flask` | Activate the venv and run `pip install -r requirements.txt` |
| PowerShell blocks `Activate.ps1` | `Set-ExecutionPolicy -Scope Process Bypass` |
| Port 5000 in use | Edit the port in the last line of `app.py` |
| "Invalid Citizen ID or Citizen ID Code" | Use values from section 12; make sure the database was created in development mode |
| Logins stopped working after copying the DB | The `instance/pepper.key` must go with the database |
| "Too many failed attempts" | Wait 15 minutes (or clear the `login_attempts` table in development) |
| Upload rejected | JPG/PNG/WEBP only, max 5 images, 2 MB each |
| `database is locked` | Close other programs that have the .db file open |
| Start fresh | Stop the app and delete `instance/local_news.db` |


## Current discussion updates implemented (Nov 2026)

- Reputation Points replace the old chances counter: accounts start at 100 RP and RP is capped between 0 and 100.
- At the 2x Fake-to-Relevant threshold (with the existing minimum-vote guard), the system counts Fake categories and applies one penalty based on the highest-voted category: Completely False = 5 RP, Misleading = 3 RP, Inaccurate = 2 RP. Ties choose the least severe deduction to avoid harsher automatic punishment.
- A post receives only one 2x penalty event. Deleting a post does not reverse its RP penalty.
- RP reaching zero creates a permanent Citizen ID ban event. The account is blocked from login and marked restricted in the database for compatibility.
- Settings shows the user's RP score out of 100.
- Home shows Area News and City News only; State/India sections were removed. News cards use horizontal swipe/scroll rails, showing up to 10 cards per feed section.
- Home includes State, City and Area dropdown filters in a compact row.
- RP reward/increase rules have not been implemented because the amount and qualifying criteria have not yet been finalized.

The moderation system still uses the existing 2x threshold and 3x hide threshold/minimum vote safeguards. Community voting is not treated as verified truth.

---

## Update notes (fake popup, news location, RP rules)

**Run on Windows (CMD):**
```
cd LOCAL_NEWS
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000. Existing databases are upgraded automatically on start (one new column,
`users.news_filter_location_id`, is added; nothing is removed). Run tests with `python -m pytest -q tests`.

**What changed**
1. *Fake popup* - now a fixed overlay moved to `<body>` while open, so cards can never clip it. Bottom sheet on phones;
   closes on outside click, the x button or Esc. (`static/js/news.js`, `static/css/style.css`, `templates/_card.html`)
2. *Choose news location* - `locations.js` was never loaded on the home page; it is now, and pre-selected values are
   restored. "Show news" POSTs to `/news/location`, which validates State>City>Area server-side and saves it in the
   database (survives refresh and logout/login). "My location" clears it. (`routes/news.py`, `templates/home.html`)
3. *RP rule* - the 5-total-votes minimum applies only when Relevant = 0; otherwise Fake >= 2 x Relevant. Counts come from
   the stored `news_votes` rows. (`services/moderation.py`)
4. *Category rule* - percentages computed from stored Fake votes; a strictly highest category uses its existing penalty
   (False 5, Misleading 3, Inaccurate 2); any tie for highest => default 5 RP. One deduction per post (unique DB index),
   stored in `moderation_events`, never reversed by deletion; RP 0 => existing account restriction.

Note: the project's existing third category is named **Inaccurate** (the request called it "Incorrect"); it was left
unchanged so existing data and penalty settings are not altered. Hide rule (3x): Relevant = 0 needs at least 7 total votes (`HIDE_MIN_TOTAL_VOTES` in config.py); Relevant >= 1 has no minimum, only Fake >= 3 x Relevant.
