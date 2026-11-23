import io
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402

CITIZENS = json.loads((ROOT / "data" / "dummy_citizens.json").read_text(encoding="utf-8"))["citizens"]


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "HASH_METHOD": "pbkdf2:sha256:1000",       # fast hashing for tests only
        "RATE_LIMITS": {"post": (100, 3600), "vote": (1000, 60), "save": (1000, 60),
                        "register": (1000, 3600), "location": (1000, 60)},
    })


def db_of(app):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def location_ids(app, state, city, area=None):
    db = db_of(app)
    s = db.execute("SELECT id FROM locations WHERE level='state' AND name=?", (state,)).fetchone()["id"]
    c = db.execute("SELECT id FROM locations WHERE level='city' AND parent_id=? AND name=?", (s, city)).fetchone()["id"]
    a = None
    if area:
        a = db.execute("SELECT id FROM locations WHERE level='area' AND parent_id=? AND name=?", (c, area)).fetchone()["id"]
    db.close()
    return s, c, a


def png_bytes(size=(40, 30), color=(30, 90, 200), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


class Client:
    """Thin wrapper around Flask's test client that handles CSRF tokens."""

    def __init__(self, app, citizen=None):
        self.app = app
        self.c = app.test_client()
        self.citizen = citizen

    def csrf(self):
        for url in ("/profile", "/login", "/register"):
            html = self.c.get(url).get_data(as_text=True)
            m = re.search(r'csrf-token" content="([^"]+)"', html)
            if m:
                return m.group(1)
        raise AssertionError("no csrf token found")

    def form(self, url, data=None, **kw):
        data = dict(data or {})
        data["csrf_token"] = self.csrf()
        return self.c.post(url, data=data, **kw)

    def json(self, url, payload=None):
        return self.c.post(url, json=payload or {}, headers={"X-CSRF-Token": self.csrf(),
                                                             "X-Requested-With": "fetch"})

    def register(self, state="Karnataka", city="Bengaluru", area="Indiranagar", citizen=None):
        citizen = citizen or self.citizen
        s, c, a = location_ids(self.app, state, city, area)
        return self.form("/register", {
            "citizen_id": citizen["Citizen_ID"], "citizen_id_code": citizen["Citizen_ID_Code"],
            "state_id": s, "city_id": c, "area_id": a or ""})

    def login(self, citizen=None, code=None):
        citizen = citizen or self.citizen
        return self.form("/login", {"citizen_id": citizen["Citizen_ID"],
                                    "citizen_id_code": code or citizen["Citizen_ID_Code"]})

    def logout(self):
        return self.form("/logout")

    def publish(self, title="Water supply disrupted in the area", description="Pipeline repair work is ongoing.",
                images=()):
        files = [(io.BytesIO(data), name) for name, data in images]
        return self.form("/news/create", {"title": title, "description": description,
                                          "images": files}, content_type="multipart/form-data")


@pytest.fixture
def make_user(app):
    counter = {"n": 0}

    def _make(state="Karnataka", city="Bengaluru", area="Indiranagar"):
        citizen = CITIZENS[counter["n"]]
        counter["n"] += 1
        cl = Client(app, citizen)
        resp = cl.register(state, city, area)
        assert resp.status_code == 302, resp.get_data(as_text=True)
        return cl
    return _make


def user_row(app, client):
    db = db_of(app)
    row = db.execute("SELECT * FROM users WHERE citizen_id=?", (client.citizen["Citizen_ID"],)).fetchone()
    db.close()
    return row


def last_post_id(app):
    db = db_of(app)
    pid = db.execute("SELECT MAX(id) FROM news_posts").fetchone()[0]
    db.close()
    return pid


def sections(html):
    """Split the home page into {section_key: html}."""
    parts = re.split(r'id="section-(\w+)"', html)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
