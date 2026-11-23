import threading

import pytest

from conftest import CITIZENS, Client, db_of, last_post_id, user_row
from services.moderation import thresholds


def vote(cl, pid, kind, reason=None):
    payload = {"vote": kind}
    if reason:
        payload["reason"] = reason
    return cl.json(f"/api/news/{pid}/vote", payload)


def events(app, pid, event_type=None):
    db = db_of(app)
    q, args = "SELECT * FROM moderation_events WHERE post_id=?", [pid]
    if event_type:
        q += " AND event_type=?"
        args.append(event_type)
    return db.execute(q, args).fetchall()


@pytest.fixture
def cfg(app):
    return app.config


# ------------------------------------------------------------------ pure threshold maths
@pytest.mark.parametrize("relevant,fake,deduct,hide", [
    (0, 0, False, False),
    (0, 4, False, False),      # Relevant = 0 -> needs 5 total votes
    (0, 5, True, False),       # RP at 5 votes, but hiding needs 7 when Relevant = 0
    (0, 6, True, False),
    (0, 7, True, True),
    (1, 3, True, True),        # Relevant >= 1 -> no minimum for hiding either; 3 >= 3*1
    (1, 2, True, False),
    (2, 5, True, False),
    (2, 6, True, True),
    (1, 2, True, False),       # Relevant >= 1 -> NO minimum-vote condition; 2 >= 2*1
    (1, 1, False, False),
    (2, 4, True, False),
    (2, 3, False, False),      # 3 < 2*2
    (3, 6, True, False),
    (3, 5, False, False),
    (5, 9, False, False),
    (5, 10, True, False),
    (5, 15, True, True),
])
def test_threshold_rule(cfg, relevant, fake, deduct, hide):
    assert thresholds(relevant, fake, cfg) == (deduct, hide)


# ------------------------------------------------------------------ voting rules
def test_vote_and_counts_and_reason_stored(app, make_user):
    author, v1, v2 = make_user(), make_user(), make_user()
    author.publish()
    pid = last_post_id(app)
    r = vote(v1, pid, "relevant")
    assert r.status_code == 200 and r.get_json()["relevant"] == 1
    r = vote(v2, pid, "fake", "Misleading")
    assert r.get_json()["fake"] == 1
    db = db_of(app)
    row = db.execute("SELECT vote, fake_reason FROM news_votes WHERE user_id=?", (user_row(app, v2)["id"],)).fetchone()
    assert (row["vote"], row["fake_reason"]) == ("fake", "Misleading")
    assert "Relevant" in v1.c.get(f"/news/{pid}").get_data(as_text=True)


def test_fake_vote_requires_valid_reason(app, make_user):
    author, v = make_user(), make_user()
    author.publish()
    pid = last_post_id(app)
    assert vote(v, pid, "fake").status_code == 400
    assert vote(v, pid, "fake", "Boring").status_code == 400
    assert vote(v, pid, "banana").status_code == 400
    for reason in ("False", "Misleading", "Inaccurate"):
        assert reason in ("False", "Misleading", "Inaccurate")
    assert db_of(app).execute("SELECT COUNT(*) FROM news_votes").fetchone()[0] == 0


def test_one_vote_per_user_per_post(app, make_user):
    author, v = make_user(), make_user()
    author.publish()
    pid = last_post_id(app)
    assert vote(v, pid, "relevant").status_code == 200
    assert vote(v, pid, "relevant").status_code == 409
    assert vote(v, pid, "fake", "False").status_code == 409
    post = db_of(app).execute("SELECT relevant_count, fake_count FROM news_posts WHERE id=?", (pid,)).fetchone()
    assert (post["relevant_count"], post["fake_count"]) == (1, 0)


def test_database_blocks_duplicate_votes(app, make_user):
    import sqlite3
    author, v = make_user(), make_user()
    author.publish()
    pid = last_post_id(app)
    vote(v, pid, "relevant")
    db = db_of(app)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO news_votes (post_id, user_id, vote) VALUES (?,?, 'relevant')",
                   (pid, user_row(app, v)["id"]))


def test_only_logged_in_users_can_vote(app, make_user):
    author = make_user()
    author.publish()
    anon = Client(app)
    assert vote(anon, last_post_id(app), "relevant").status_code == 401


def test_cannot_vote_on_own_post(app, make_user):
    author = make_user()
    author.publish()
    assert vote(author, last_post_id(app), "fake", "False").status_code == 403


def test_vote_on_missing_post_404(app, make_user):
    assert vote(make_user(), 9999, "relevant").status_code == 404


# ------------------------------------------------------------------ Rule A / B: 2x threshold
def drive_to_2x(app, voters, pid, fakes=5):
    for v in voters[:fakes]:
        assert vote(v, pid, "fake", "False").status_code == 200


def test_2x_deducts_rp_exactly_once(app, make_user):
    author = make_user()
    voters = [make_user() for _ in range(7)]
    author.publish()
    pid = last_post_id(app)
    start = user_row(app, author)["reputation_points"]
    for v in voters[:2]:
        vote(v, pid, "relevant")
    for v in voters[2:5]:
        vote(v, pid, "fake", "Inaccurate")
    assert events(app, pid, "threshold_2x") == []              # 3 fakes < 2*2
    assert user_row(app, author)["reputation_points"] == start
    vote(voters[5], pid, "fake", "Inaccurate")                 # 4 fakes == 2*2 -> trigger
    assert len(events(app, pid, "threshold_2x")) == 1
    assert user_row(app, author)["reputation_points"] == start - 2    # Inaccurate = 2 RP
    vote(voters[6], pid, "fake", "Inaccurate")                 # more fakes: still ONE deduction
    assert len(events(app, pid, "threshold_2x")) == 1
    assert user_row(app, author)["reputation_points"] == start - 2


# ------------------------------------------------------------------ Rule C: 3x hides globally
def test_3x_hides_post_globally_but_not_the_account(app, make_user):
    author = make_user()
    voters = [make_user() for _ in range(7)]
    bystander = make_user()
    author.publish(title="Questionable claim news")
    pid = last_post_id(app)
    drive_to_2x(app, voters, pid, fakes=7)         # 0 Relevant, 7 Fake -> RP cut at 5, hidden at 7
    assert len(events(app, pid, "hidden_3x")) == 1
    assert db_of(app).execute("SELECT status FROM news_posts WHERE id=?", (pid,)).fetchone()["status"] == "hidden"
    assert bystander.c.get(f"/news/{pid}").status_code == 404                 # hidden for everyone else
    assert "Questionable claim news" not in bystander.c.get("/").get_data(as_text=True)
    assert author.c.get(f"/news/{pid}").status_code == 200                    # creator can still see + delete it
    assert vote(bystander, pid, "relevant").status_code == 404                # no more voting on hidden posts
    assert user_row(app, author)["status"] == "active"                        # hiding != banning
    assert db_of(app).execute("SELECT COUNT(*) FROM account_restrictions").fetchone()[0] == 0


def test_below_minimum_votes_nothing_happens(app, make_user):
    author = make_user()
    voters = [make_user() for _ in range(4)]
    author.publish()
    pid = last_post_id(app)
    drive_to_2x(app, voters, pid, fakes=4)
    assert events(app, pid) == []
    assert user_row(app, author)["reputation_points"] == 100


# ------------------------------------------------------------------ deletion never reverses RP
def test_deleting_post_never_reverses_deduction(app, make_user):
    author = make_user()
    voters = [make_user() for _ in range(5)]
    author.publish()
    pid = last_post_id(app)
    start = user_row(app, author)["reputation_points"]
    # 0 Relevant, 5 "False" -> 5 RP; the post is also hidden by the 3x rule.
    drive_to_2x(app, voters, pid)
    assert user_row(app, author)["reputation_points"] == start - 5
    assert author.form(f"/news/{pid}/delete").status_code in (200, 302)
    assert user_row(app, author)["reputation_points"] == start - 5
    assert len(events(app, pid, "threshold_2x")) == 1


def test_rp_zero_restricts_account(app, make_user):
    author = make_user()
    voters = [make_user() for _ in range(5)]
    author.publish()
    pid = last_post_id(app)
    db = db_of(app)
    db.execute("UPDATE users SET reputation_points=5 WHERE id=?", (user_row(app, author)["id"],))
    db.commit()
    drive_to_2x(app, voters, pid)                       # -5 RP -> 0
    row = user_row(app, author)
    assert row["reputation_points"] == 0 and row["status"] == "restricted"
    assert len(events(app, pid, "reputation_ban")) == 1
    assert author.publish(title="Another news item").status_code == 302   # redirected away: read-only
    assert db_of(app).execute("SELECT COUNT(*) FROM news_posts").fetchone()[0] == 1


def test_concurrent_votes_keep_counts_consistent_and_trigger_once(app, make_user):
    author = make_user()
    voters = [make_user() for _ in range(9)]
    author.publish()
    pid = last_post_id(app)
    # Pre-fetch CSRF tokens so threads only perform the vote itself.
    tokens = [v.csrf() for v in voters]
    results = []

    def worker(v, tok, kind, reason):
        resp = v.c.post(f"/api/news/{pid}/vote", json={"vote": kind, "reason": reason},
                        headers={"X-CSRF-Token": tok, "X-Requested-With": "fetch"})
        results.append(resp.status_code)

    threads = [threading.Thread(target=worker, args=(v, t, "fake", "False")) for v, t in zip(voters, tokens)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Votes are serialised: the 7th Fake vote (0 Relevant) hides the post,
    # so exactly 7 succeed and the other 2 are refused, whatever the thread order.
    assert results.count(200) == 7 and results.count(404) == 2
    db = db_of(app)
    post = db.execute("SELECT * FROM news_posts WHERE id=?", (pid,)).fetchone()
    assert post["fake_count"] == 7 and post["relevant_count"] == 0 and post["status"] == "hidden"
    assert db.execute("SELECT COUNT(*) FROM news_votes WHERE post_id=?", (pid,)).fetchone()[0] == 7
    assert len(events(app, pid, "threshold_2x")) == 1                         # exactly one deduction
    assert len(events(app, pid, "hidden_3x")) == 1
    assert user_row(app, author)["reputation_points"] == 95


def test_concurrent_duplicate_votes_from_same_user_count_once(app, make_user):
    author, v = make_user(), make_user()
    author.publish()
    pid = last_post_id(app)
    tok = v.csrf()
    results = []

    # A shared test client is not thread-safe, so give each thread its own client carrying v's session.
    clients = []
    for _ in range(6):
        c = app.test_client()
        with c.session_transaction() as s:
            with v.c.session_transaction() as orig:
                s.update(dict(orig))
        clients.append(c)

    def worker2(c):
        r = c.post(f"/api/news/{pid}/vote", json={"vote": "relevant"},
                   headers={"X-CSRF-Token": tok, "X-Requested-With": "fetch"})
        results.append(r.status_code)

    ts = [threading.Thread(target=worker2, args=(c,)) for c in clients]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count(200) == 1 and results.count(409) == 5
    assert db_of(app).execute("SELECT relevant_count FROM news_posts WHERE id=?", (pid,)).fetchone()[0] == 1
