"""RP category rules, duplicate-deduction safeguards and the 'Choose news location' filter."""
import pytest

from conftest import db_of, last_post_id, location_ids, sections, user_row
from test_voting import events, vote


def run_votes(app, make_user, relevant, fakes):
    """fakes: list of reasons. Returns (author, post_id). Every vote is a real API call."""
    author = make_user()
    author.publish()
    pid = last_post_id(app)
    for _ in range(relevant):
        assert vote(make_user(), pid, "relevant").status_code == 200
    for reason in fakes:
        r = vote(make_user(), pid, "fake", reason)
        assert r.status_code in (200, 404)       # 404 only if the post got hidden meanwhile
    return author, pid


def rp(app, author):
    return user_row(app, author)["reputation_points"]


# ---- minimum-vote condition applies only when Relevant == 0
@pytest.mark.parametrize("relevant,fake,deducted", [
    (0, 4, False), (0, 5, True), (1, 2, True), (2, 4, True), (2, 3, False), (3, 6, True),
])
def test_prompt_examples_end_to_end(app, make_user, relevant, fake, deducted):
    author, pid = run_votes(app, make_user, relevant, ["False"] * fake)
    assert (len(events(app, pid, "threshold_2x")) == 1) is deducted
    assert (rp(app, author) < 100) is deducted      # author starts at the 100 cap


# ---- category winner
def test_clear_winner_false_category(app, make_user):
    author, pid = run_votes(app, make_user, 0, ["False", "False", "False", "Misleading", "Inaccurate"])
    ev = events(app, pid, "threshold_2x")[0]
    assert (ev["penalty_category"], ev["points_deducted"]) == ("False", 5)
    assert rp(app, author) == 95


def test_clear_winner_inaccurate_category(app, make_user):
    author, pid = run_votes(app, make_user, 0, ["Inaccurate", "Inaccurate", "Inaccurate", "Misleading", "False"])
    ev = events(app, pid, "threshold_2x")[0]
    assert (ev["penalty_category"], ev["points_deducted"]) == ("Inaccurate", 2)
    assert rp(app, author) == 98


def test_clear_winner_misleading_category(app, make_user):
    author, pid = run_votes(app, make_user, 0, ["Misleading"] * 3 + ["False", "Inaccurate"])
    ev = events(app, pid, "threshold_2x")[0]
    assert (ev["penalty_category"], ev["points_deducted"]) == ("Misleading", 3)


@pytest.mark.parametrize("reasons", [
    ["Inaccurate", "Inaccurate", "Misleading", "Misleading", "False"],          # 40/40/20 two-way tie
    ["Inaccurate", "Inaccurate", "False", "False", "Misleading"],               # tie that includes the 5-RP one
    ["Inaccurate", "Misleading", "False", "Inaccurate", "Misleading", "False"],  # all three tied
])
def test_ties_always_default_5_rp(app, make_user, reasons):
    author, pid = run_votes(app, make_user, 0, reasons)
    ev = events(app, pid, "threshold_2x")[0]
    assert ev["points_deducted"] == 5 and ev["penalty_category"] is None
    assert rp(app, author) == 95


def test_category_is_not_the_fake_vs_relevant_ratio(app, make_user):
    # 2 Relevant, 4 Fake (exactly 2x) -> category chosen from the 4 fake votes only.
    author, pid = run_votes(app, make_user, 2, ["Inaccurate", "Inaccurate", "Inaccurate", "False"])
    ev = events(app, pid, "threshold_2x")[0]
    assert (ev["penalty_category"], ev["points_deducted"]) == ("Inaccurate", 2)


# ---- safeguards
def test_repeated_requests_cannot_double_deduct(app, make_user):
    author, pid = run_votes(app, make_user, 0, ["False"] * 5)
    assert rp(app, author) == 95
    voter = make_user()
    for _ in range(3):
        vote(voter, pid, "fake", "False")          # hidden post / duplicate vote -> refused
    assert rp(app, author) == 95 and len(events(app, pid, "threshold_2x")) == 1


def test_only_the_author_is_charged(app, make_user):
    bystander = make_user()
    author, pid = run_votes(app, make_user, 0, ["False"] * 5)
    assert rp(app, bystander) == 100 and rp(app, author) == 95


def test_deduction_persists_across_logout_login(app, make_user):
    author, pid = run_votes(app, make_user, 0, ["False"] * 5)
    author.logout()
    assert author.login().status_code == 302
    assert rp(app, author) == 95
    assert b"95" in author.c.get("/profile").data


# ---- location filter
def pick(app, state, city=None, area=None):
    db = db_of(app)
    s = db.execute("SELECT id FROM locations WHERE level='state' AND name=?", (state,)).fetchone()["id"]
    out = {"state_id": s, "city_id": "", "area_id": ""}
    if city:
        s_, c, a = location_ids(app, state, city, area)
        out["city_id"], out["area_id"] = c, a or ""
    return out


@pytest.fixture
def world(app, make_user):
    me = make_user("Karnataka", "Bengaluru", "Indiranagar")
    for who, loc, title in [
        (make_user("Karnataka", "Bengaluru", "Indiranagar"), ("Karnataka", "Bengaluru", "Indiranagar"), "Indiranagar story"),
        (make_user("Karnataka", "Bengaluru", "Koramangala"), ("Karnataka", "Bengaluru", "Koramangala"), "Koramangala story"),
        (make_user("Karnataka", "Mysuru", "Vijayanagar"), ("Karnataka", "Mysuru", "Vijayanagar"), "Mysuru story"),
        (make_user("Maharashtra", "Mumbai", "Andheri"), ("Maharashtra", "Mumbai", "Andheri"), "Mumbai Andheri story"),
    ]:
        assert who.publish(title=title).status_code == 302
    return me


def page(cl):
    return "".join(sections(cl.c.get("/").get_data(as_text=True)).values())


def test_dropdown_scripts_are_loaded_on_home(world):
    html = world.c.get("/").get_data(as_text=True)
    assert "js/locations.js" in html and "js/news.js" in html


def test_filter_by_area_city_state_and_persist(app, world):
    me = world
    assert "Mumbai Andheri story" not in page(me)                       # default = my location
    assert me.form("/news/location", pick(app, "Maharashtra", "Mumbai", "Andheri")).status_code == 302
    p = page(me)
    assert "Mumbai Andheri story" in p and "Indiranagar story" not in p
    # persisted in the database, survives logout/login
    assert user_row(app, me)["news_filter_location_id"] is not None
    me.logout(); me.login()
    assert "Mumbai Andheri story" in page(me) and "Indiranagar story" not in page(me)
    # city level
    me.form("/news/location", pick(app, "Karnataka", "Bengaluru"))
    p = page(me)
    assert "Indiranagar story" in p and "Koramangala story" in p and "Mysuru story" not in p
    # state level
    me.form("/news/location", pick(app, "Karnataka"))
    p = page(me)
    assert all(t in p for t in ("Indiranagar story", "Koramangala story", "Mysuru story")) and "Mumbai" not in p
    # clear -> back to own location
    me.form("/news/location/clear")
    assert user_row(app, me)["news_filter_location_id"] is None
    assert "Mumbai Andheri story" not in page(me)


def test_filter_validates_dependent_selection(app, world):
    me = world
    mum = pick(app, "Maharashtra", "Mumbai", "Andheri")
    bad = dict(mum, state_id=pick(app, "Karnataka")["state_id"])        # Mumbai city under Karnataka
    me.form("/news/location", bad)
    assert user_row(app, me)["news_filter_location_id"] is None
    me.form("/news/location", {"state_id": "", "city_id": "", "area_id": ""})
    assert user_row(app, me)["news_filter_location_id"] is None
    me.form("/news/location", {"state_id": "abc"})
    assert user_row(app, me)["news_filter_location_id"] is None


def test_selected_values_prefilled_for_dropdowns(app, world):
    me = world
    sel = pick(app, "Maharashtra", "Mumbai", "Andheri")
    me.form("/news/location", sel)
    html = me.c.get("/").get_data(as_text=True)
    assert f'data-initial-state="{sel["state_id"]}"' in html
    assert f'data-initial-city="{sel["city_id"]}"' in html
    assert f'data-initial-area="{sel["area_id"]}"' in html


def test_filter_requires_csrf(app, world):
    r = world.c.post("/news/location", data={"state_id": 1})
    assert r.status_code == 400


# ---- hide rule: Relevant = 0 -> min 7 votes; Relevant >= 1 -> no minimum, Fake >= 3x
@pytest.mark.parametrize("relevant,fake,hidden", [
    (0, 5, False), (0, 6, False), (0, 7, True), (1, 2, False), (1, 3, True), (2, 5, False), (2, 6, True),
])
def test_hide_rule_end_to_end(app, make_user, relevant, fake, hidden):
    author, pid = run_votes(app, make_user, relevant, ["False"] * fake)
    status = db_of(app).execute("SELECT status FROM news_posts WHERE id=?", (pid,)).fetchone()["status"]
    assert (status == "hidden") is hidden
