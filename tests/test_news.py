import io
import os

from conftest import (Client, db_of, last_post_id, location_ids, png_bytes, sections, user_row)


# ---------------------------------------------------------------- publishing
def test_publish_and_view_news(app, make_user):
    cl = make_user()
    resp = cl.publish("Road closed near the market", "Heavy waterlogging; avoid MG Road today.")
    assert resp.status_code == 302
    page = cl.c.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Road closed near the market" in page and cl.citizen["Citizen_Name"] in page
    assert "Indiranagar" in page and "Bengaluru" in page


def test_description_limit_1000_chars(app, make_user):
    cl = make_user()
    exactly_1000 = ("abcd " * 250)[:1000]
    assert len(exactly_1000) == 1000
    assert cl.publish(description=exactly_1000).status_code == 302
    too_long = cl.publish(title="Another valid title", description=exactly_1000 + "x")
    assert too_long.status_code == 400
    assert db_of(app).execute("SELECT COUNT(*) FROM news_posts").fetchone()[0] == 1


def test_title_and_description_required(app, make_user):
    cl = make_user()
    assert cl.publish(title="abc").status_code == 400
    assert cl.publish(description="   ").status_code == 400


def test_max_5_images(app, make_user):
    cl = make_user()
    five = [(f"{i}.png", png_bytes()) for i in range(5)]
    assert cl.publish(title="Five images post", images=five).status_code == 302
    six = [(f"{i}.png", png_bytes()) for i in range(6)]
    assert cl.publish(title="Six images post", images=six).status_code == 400
    db = db_of(app)
    assert db.execute("SELECT COUNT(*) FROM news_images").fetchone()[0] == 5
    assert len(os.listdir(app.config["UPLOAD_FOLDER"])) == 5          # nothing orphaned from the rejected post


def test_image_upload_is_validated_and_reencoded(app, make_user):
    cl = make_user()
    ok = cl.publish(title="Valid image post", images=[("../../evil name.png", png_bytes())])
    assert ok.status_code == 302
    stored = db_of(app).execute("SELECT filename FROM news_images").fetchone()["filename"]
    assert stored.endswith(".png") and "evil" not in stored and "/" not in stored   # random server-side name
    assert os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], stored))


def test_malicious_and_invalid_uploads_rejected(app, make_user):
    cl = make_user()
    fake_png = ("shell.png", b"<?php system($_GET['c']); ?>")
    svg = ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    html_as_png = ("page.png", b"<html><script>alert(1)</script></html>")
    exe = ("run.exe", b"MZ\x90\x00")
    for i, bad in enumerate((fake_png, svg, html_as_png, exe)):
        resp = cl.publish(title=f"Bad upload number {i}", images=[bad])
        assert resp.status_code == 400, bad[0]
    assert db_of(app).execute("SELECT COUNT(*) FROM news_posts").fetchone()[0] == 0


def test_oversized_image_rejected(app, make_user):
    cl = make_user()
    big = ("big.png", png_bytes() + b"\x00" * (app.config["MAX_IMAGE_BYTES"] + 10))
    assert cl.publish(title="Huge image post", images=[big]).status_code == 400


def test_script_content_rejected_and_html_is_escaped(app, make_user):
    cl = make_user()
    assert cl.publish(title="Nice title here", description="<script>alert(1)</script>").status_code == 400
    ok = cl.publish(title="Bold <b>claim</b> today", description="Uses <i>tags</i> & ampersands")
    assert ok.status_code == 302
    page = cl.c.get(ok.headers["Location"]).get_data(as_text=True)
    assert "<b>claim</b>" not in page and "&lt;b&gt;claim&lt;/b&gt;" in page


def test_duplicate_title_spam_blocked(app, make_user):
    cl = make_user()
    assert cl.publish(title="Same title again").status_code == 302
    assert cl.publish(title="Same title again").status_code == 400


def test_published_news_cannot_be_edited(app, make_user):
    cl = make_user()
    cl.publish()
    pid = last_post_id(app)
    for url in (f"/news/{pid}/edit", f"/api/news/{pid}/edit"):
        assert cl.form(url, {"title": "x" * 10}).status_code in (404, 405)


# ---------------------------------------------------------------- deleting
def test_creator_can_delete_own_post_and_files_removed(app, make_user):
    cl = make_user()
    cl.publish(images=[("a.png", png_bytes())])
    pid = last_post_id(app)
    assert os.listdir(app.config["UPLOAD_FOLDER"])
    assert cl.form(f"/news/{pid}/delete").status_code == 302
    assert db_of(app).execute("SELECT status FROM news_posts WHERE id=?", (pid,)).fetchone()["status"] == "deleted"
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == []
    assert cl.c.get(f"/news/{pid}").status_code == 404


def test_cannot_delete_someone_elses_post(app, make_user):
    a, b = make_user(), make_user()
    a.publish()
    pid = last_post_id(app)
    resp = b.json(f"/news/{pid}/delete")
    assert resp.status_code == 403
    assert db_of(app).execute("SELECT status FROM news_posts WHERE id=?", (pid,)).fetchone()["status"] == "active"


# ---------------------------------------------------------------- saved news
def test_save_unsave_and_private(app, make_user):
    a, b = make_user(), make_user()
    a.publish(title="Saved news candidate")
    pid = last_post_id(app)
    assert b.json(f"/api/news/{pid}/save").get_json() == {"saved": True}
    def saved_block(client):
        html = client.c.get("/profile").get_data(as_text=True)
        return html.split("<h2>Saved news")[1].split("<h2>My published news")[0]
    assert "Saved news candidate" in saved_block(b)
    assert "Saved news candidate" not in saved_block(a)           # saved news is private
    assert b.json(f"/api/news/{pid}/save").get_json() == {"saved": False}
    assert db_of(app).execute("SELECT COUNT(*) FROM saved_news").fetchone()[0] == 0


def test_saved_reference_updates_when_original_deleted(app, make_user):
    a, b = make_user(), make_user()
    a.publish(title="Soon to be deleted news")
    pid = last_post_id(app)
    b.json(f"/api/news/{pid}/save")
    a.form(f"/news/{pid}/delete")
    html = b.c.get("/profile").get_data(as_text=True)
    assert "deleted by its creator" in html and f"/news/{pid}\"" not in html
    assert b.json(f"/api/news/{pid}/save").get_json() == {"saved": False}      # can still remove it
    assert db_of(app).execute("SELECT COUNT(*) FROM saved_news").fetchone()[0] == 0


def test_cannot_save_deleted_post(app, make_user):
    a, b = make_user(), make_user()
    a.publish()
    pid = last_post_id(app)
    a.form(f"/news/{pid}/delete")
    assert b.json(f"/api/news/{pid}/save").status_code == 404


# ---------------------------------------------------------------- home sections
def test_home_sections_area_city_state_india(app, make_user):
    me = make_user("Karnataka", "Bengaluru", "Indiranagar")
    same_area = make_user("Karnataka", "Bengaluru", "Indiranagar")
    same_city = make_user("Karnataka", "Bengaluru", "Koramangala")
    same_state = make_user("Karnataka", "Mysuru", "Vijayanagar")
    other = make_user("Maharashtra", "Mumbai", "Andheri")
    for u, t in ((same_area, "AREA news item here"), (same_city, "CITY news item here"),
                 (same_state, "STATE news item here"), (other, "INDIA news item here")):
        assert u.publish(title=t).status_code == 302
    secs = sections(me.c.get("/").get_data(as_text=True))
    assert "AREA news item here" in secs["area"]
    assert "CITY news item here" in secs["city"]
    page = "".join(secs.values())
    assert "STATE news item here" not in page and "INDIA news item here" not in page   # outside area/city
    assert "AREA news item here" not in secs["city"]          # each post appears in exactly one tier


def test_followed_location_prioritised(app, make_user):
    me = make_user("Karnataka", "Bengaluru", "Indiranagar")
    mum = make_user("Maharashtra", "Mumbai", "Andheri")
    mum.publish(title="Mumbai Andheri local item")
    assert "Mumbai Andheri local item" not in "".join(sections(me.c.get("/").get_data(as_text=True)).values())
    s, c, a = location_ids(app, "Maharashtra", "Mumbai", "Andheri")
    assert me.form("/settings/follow", {"state_id": s, "city_id": c, "area_id": a}).status_code == 302
    assert "Mumbai Andheri local item" in sections(me.c.get("/").get_data(as_text=True))["area"]


def test_featured_slideshow_lists_posts_with_images(app, make_user):
    me = make_user()
    me.publish(title="No image story here")
    me.publish(title="Story with a picture", images=[("a.png", png_bytes())])
    html = me.c.get("/").get_data(as_text=True)
    feat = html.split('id="slideshow"')[1].split("</section>")[0]
    assert "Story with a picture" in feat and "No image story here" not in feat
    assert "slide-btn prev" not in feat            # a single slide needs no arrows
    me.publish(title="Second picture story", images=[("b.png", png_bytes())])
    feat = me.c.get("/").get_data(as_text=True).split('id="slideshow"')[1].split("</section>")[0]
    assert "slide-btn prev" in feat and "slide-btn next" in feat


# ---------------------------------------------------------------- locations
def test_cascading_location_api(app):
    cl = Client(app)
    states = cl.c.get("/api/locations/children").get_json()
    assert len(states) >= 36
    karnataka = next(s for s in states if s["name"] == "Karnataka")
    cities = cl.c.get(f"/api/locations/children?parent_id={karnataka['id']}").get_json()
    assert "Bengaluru" in [c["name"] for c in cities]
    blr = next(c for c in cities if c["name"] == "Bengaluru")
    areas = cl.c.get(f"/api/locations/children?parent_id={blr['id']}").get_json()
    assert "Indiranagar" in [a["name"] for a in areas]
    assert cl.c.get("/api/locations/children?parent_id=abc").status_code == 400


def test_change_current_location_and_follow_unfollow(app, make_user):
    me = make_user("Karnataka", "Bengaluru", "Indiranagar")
    s, c, a = location_ids(app, "Tamil Nadu", "Chennai", "Adyar")
    assert me.form("/settings/location", {"state_id": s, "city_id": c, "area_id": a}).status_code == 302
    assert "Adyar, Chennai, Tamil Nadu" in me.c.get("/settings").get_data(as_text=True)
    assert user_row(app, me)["current_location_id"] == a

    ks, kc, _ = location_ids(app, "Kerala", "Kochi")
    me.form("/settings/follow", {"state_id": ks, "city_id": kc})                 # follow a whole city
    me.form("/settings/follow", {"state_id": ks})                                # follow a whole state
    me.form("/settings/follow", {"state_id": ks})                                # duplicate ignored
    db = db_of(app)
    assert db.execute("SELECT COUNT(*) FROM followed_locations").fetchone()[0] == 2
    prof = me.c.get("/profile").get_data(as_text=True)
    assert "Kochi, Kerala" in prof
    me.form(f"/settings/unfollow/{kc}")
    assert db.execute("SELECT COUNT(*) FROM followed_locations").fetchone()[0] == 1


def test_invalid_location_selections_rejected(app, make_user):
    me = make_user()
    s, c, a = location_ids(app, "Tamil Nadu", "Chennai", "Adyar")
    ks, _, _ = location_ids(app, "Kerala", "Kochi")
    before = user_row(app, me)["current_location_id"]
    for data in ({"state_id": ks, "city_id": c, "area_id": a},    # city not in that state
                 {"state_id": s, "city_id": c},                   # city has areas -> area required
                 {"state_id": "999999"}, {"state_id": "abc"}):
        me.form("/settings/location", data)
    assert user_row(app, me)["current_location_id"] == before


def test_location_import_is_idempotent(app, tmp_path):
    from services import locations
    db = db_of(app)
    db.isolation_level = None
    csv_file = tmp_path / "locs.csv"
    csv_file.write_text("state,city,area\nGoa,Panaji,Miramar\nGoa,Vasco da Gama,\nTestland,Testville,Test Area\n")
    before = db.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
    first = locations.import_locations_csv(db, str(csv_file))
    second = locations.import_locations_csv(db, str(csv_file))
    assert first == {"state": 1, "city": 2, "area": 1} or sum(first.values()) >= 4
    assert sum(second.values()) == 0
    assert db.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == before + sum(first.values())


# ---------------------------------------------------------------- theme
def test_theme_persists_across_logout_and_login(app, make_user):
    me = make_user()
    assert 'data-theme="light"' in me.c.get("/settings").get_data(as_text=True)      # default
    assert me.json("/settings/theme", {"theme": "night"}).get_json() == {"theme": "night"}
    assert 'data-theme="night"' in me.c.get("/").get_data(as_text=True)
    me.logout()
    assert 'data-theme="light"' in me.c.get("/login").get_data(as_text=True)         # logged out -> default
    me.login()
    assert 'data-theme="night"' in me.c.get("/").get_data(as_text=True)              # restored from DB
    assert db_of(app).execute("SELECT theme FROM user_settings").fetchone()["theme"] == "night"
    assert me.json("/settings/theme", {"theme": "purple"}).status_code == 400


def test_responsive_markup_present(app, make_user):
    me = make_user()
    html = me.c.get("/").get_data(as_text=True)
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html and 'id="navToggle"' in html
    css = open(os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")).read()
    assert "@media (max-width: 820px)" in css and "@media (max-width: 480px)" in css


def test_restricted_user_cannot_publish_but_can_read(app, make_user):
    me = make_user()
    db = db_of(app)
    db.execute("UPDATE users SET status='restricted' WHERE id=?", (user_row(app, me)["id"],))
    db.commit()
    assert me.c.get("/").status_code == 200
    assert me.c.get("/news/create").status_code == 302
    assert me.publish().status_code in (302, 403)
    assert db.execute("SELECT COUNT(*) FROM news_posts").fetchone()[0] == 0
