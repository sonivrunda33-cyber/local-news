import re
import sqlite3

import pytest

from app import create_app
from conftest import CITIZENS, Client, db_of, location_ids, user_row


def test_at_least_20_unique_dummy_citizens_with_valid_formats(app):
    assert len(CITIZENS) >= 20
    assert len({c["Citizen_ID"] for c in CITIZENS}) == len(CITIZENS)
    assert len({c["Citizen_ID_Code"] for c in CITIZENS}) == len(CITIZENS)
    for c in CITIZENS:
        assert re.fullmatch(r"\d{15}", c["Citizen_ID"])
        assert re.fullmatch(r"\d{8}", c["Citizen_ID_Code"])
    db = db_of(app)
    assert db.execute("SELECT COUNT(*) FROM citizens WHERE is_dummy=1").fetchone()[0] == len(CITIZENS)


def test_codes_are_hashed_never_plain(app):
    db = db_of(app)
    hashes = [r["code_hash"] for r in db.execute("SELECT code_hash FROM citizens")]
    for c in CITIZENS:
        assert all(c["Citizen_ID_Code"] not in h for h in hashes)
    assert all(h.startswith(("pbkdf2:", "scrypt:")) for h in hashes)


def test_seeding_is_idempotent_across_restarts(app, tmp_path):
    before = db_of(app).execute("SELECT COUNT(*) FROM citizens").fetchone()[0]
    create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "HASH_METHOD": "pbkdf2:sha256:1000",
                "UPLOAD_FOLDER": app.config["UPLOAD_FOLDER"]})
    assert db_of(app).execute("SELECT COUNT(*) FROM citizens").fetchone()[0] == before


def test_production_mode_does_not_seed_dummy_citizens(tmp_path):
    prod = create_app({"TESTING": True, "ENV_NAME": "production", "SEED_DUMMY_CITIZENS": False,
                       "DATABASE": str(tmp_path / "prod.db"), "UPLOAD_FOLDER": str(tmp_path / "u")})
    assert db_of(prod).execute("SELECT COUNT(*) FROM citizens").fetchone()[0] == 0


def test_all_dummy_citizens_can_register_logout_and_login(app):
    for citizen in CITIZENS:
        cl = Client(app, citizen)
        assert cl.register().status_code == 302
        row = user_row(app, cl)
        assert row["name"] == citizen["Citizen_Name"]          # name comes from Citizen Database
        assert cl.logout().status_code == 302
        resp = cl.login()
        assert resp.status_code == 302 and resp.headers["Location"].endswith("/")
        assert cl.c.get("/").status_code == 200


def test_register_page_has_no_username_or_display_name_field(app):
    html = Client(app).c.get("/register").get_data(as_text=True)
    field_names = set(re.findall(r'<(?:input|select|textarea)[^>]*\bname="([^"]+)"', html))
    assert field_names == {"csrf_token", "citizen_id", "citizen_id_code", "state_id", "city_id", "area_id"}


def test_wrong_code_and_bad_formats_rejected_with_generic_error(app, make_user):
    cl = make_user()
    cl.logout()
    resp = cl.login(code="00000000")
    assert resp.status_code == 401 and "Invalid Citizen ID or Citizen ID Code" in resp.get_data(as_text=True)
    assert cl.form("/login", {"citizen_id": "123", "citizen_id_code": "1"}).status_code == 401
    unknown = cl.form("/login", {"citizen_id": "9" * 15, "citizen_id_code": "12345678"})
    assert unknown.status_code == 401 and "Invalid Citizen ID" in unknown.get_data(as_text=True)


def test_registration_rejects_wrong_code_and_unknown_id(app):
    cl = Client(app, CITIZENS[0])
    s, c, a = location_ids(app, "Karnataka", "Bengaluru", "Indiranagar")
    bad = cl.form("/register", {"citizen_id": CITIZENS[0]["Citizen_ID"], "citizen_id_code": "11111111",
                                "state_id": s, "city_id": c, "area_id": a})
    assert bad.status_code == 400
    unknown = cl.form("/register", {"citizen_id": "1" * 15, "citizen_id_code": "11111111",
                                    "state_id": s, "city_id": c, "area_id": a})
    assert unknown.status_code == 400
    assert db_of(app).execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_one_citizen_id_one_account(app, make_user):
    first = make_user()
    second = Client(app, first.citizen)
    resp = second.register()
    assert resp.status_code in (400, 409)
    assert db_of(app).execute("SELECT COUNT(*) FROM users WHERE citizen_id=?",
                              (first.citizen["Citizen_ID"],)).fetchone()[0] == 1


def test_database_enforces_unique_account_per_citizen(app, make_user):
    cl = make_user()
    db = db_of(app)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO users (citizen_id, name) VALUES (?, 'X')", (cl.citizen["Citizen_ID"],))


def test_registration_requires_valid_location_chain(app):
    cl = Client(app, CITIZENS[0])
    s, c, a = location_ids(app, "Karnataka", "Bengaluru", "Indiranagar")
    s2, c2, _ = location_ids(app, "Maharashtra", "Mumbai")
    resp = cl.form("/register", {"citizen_id": CITIZENS[0]["Citizen_ID"],
                                 "citizen_id_code": CITIZENS[0]["Citizen_ID_Code"],
                                 "state_id": s2, "city_id": c, "area_id": a})   # city not in state
    assert resp.status_code == 400
    assert db_of(app).execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_login_bruteforce_lockout(app, make_user):
    cl = make_user()
    cl.logout()
    for _ in range(5):
        assert cl.login(code="00000000").status_code == 401
    locked = cl.login()                      # even the CORRECT code is refused while locked
    assert locked.status_code == 429


def test_csrf_blocks_post_without_token(app):
    cl = Client(app, CITIZENS[0])
    cl.c.get("/login")
    resp = cl.c.post("/login", data={"citizen_id": CITIZENS[0]["Citizen_ID"],
                                     "citizen_id_code": CITIZENS[0]["Citizen_ID_Code"]})
    assert resp.status_code == 400


def test_login_required_for_pages_and_api(app):
    cl = Client(app)
    assert cl.c.get("/").status_code == 302
    assert cl.c.get("/profile").status_code == 302
    assert cl.json("/api/news/1/vote", {"vote": "relevant"}).status_code == 401


def test_profile_shows_name_masked_id_and_no_code(app, make_user):
    cl = make_user()
    html = cl.c.get("/profile").get_data(as_text=True)
    cid = cl.citizen["Citizen_ID"]
    assert cl.citizen["Citizen_Name"] in html
    assert cid not in html and cid[:3] in html and cid[-3:] in html
    assert cl.citizen["Citizen_ID_Code"] not in html


def test_open_redirect_prevented(app, make_user):
    cl = make_user()
    cl.logout()
    s = cl.c.post("/login?next=//evil.example", data={"citizen_id": cl.citizen["Citizen_ID"],
                                                      "citizen_id_code": cl.citizen["Citizen_ID_Code"],
                                                      "csrf_token": cl.csrf()})
    assert s.status_code == 302 and "evil.example" not in s.headers["Location"]


def test_security_headers_present(app):
    resp = Client(app).c.get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]
