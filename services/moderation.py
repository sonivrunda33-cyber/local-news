"""Community-vote moderation and capped Citizen Reputation Points (RP)."""
PENALTIES = {"False": 5, "Misleading": 3, "Inaccurate": 2}
DEFAULT_PENALTY = 5   # used when the top category is tied

def thresholds(relevant: int, fake: int, cfg) -> tuple[bool, bool]:
    """Return (deduct_rp, hide) for the given stored vote counts.

    RP deduction (2x rule):
      * Relevant == 0  -> at least MIN_TOTAL_VOTES (5) total votes are required.
      * Relevant >= 1  -> the minimum-vote condition does NOT apply.
      * In both cases Fake must be >= WARN_MULTIPLIER (2) x Relevant (0 Relevant counts as 1).
    Hiding (3x rule):
      * Relevant == 0  -> at least HIDE_MIN_TOTAL_VOTES (7) total votes are required.
      * Relevant >= 1  -> no minimum; Fake must be >= HIDE_MULTIPLIER (3) x Relevant.
    """
    base = max(relevant, cfg["ZERO_RELEVANT_BASE"])
    enough_for_rp = relevant > 0 or (relevant + fake) >= cfg["MIN_TOTAL_VOTES"]
    deduct = enough_for_rp and fake >= cfg["WARN_MULTIPLIER"] * base
    enough_for_hide = relevant > 0 or (relevant + fake) >= cfg.get("HIDE_MIN_TOTAL_VOTES", 7)
    hide = enough_for_hide and fake >= cfg["HIDE_MULTIPLIER"] * base
    return deduct, hide


def category_percentages(db, post_id) -> dict:
    """Share (0-100) of the Fake votes of a post that chose each category, computed from
    the stored votes. This is NOT the Fake-vs-Relevant ratio."""
    rows = db.execute("SELECT fake_reason, COUNT(*) AS n FROM news_votes "
                      "WHERE post_id=? AND vote='fake' AND fake_reason IS NOT NULL "
                      "GROUP BY fake_reason", (post_id,)).fetchall()
    counts = {c: 0 for c in PENALTIES}
    for r in rows:
        if r["fake_reason"] in counts:
            counts[r["fake_reason"]] = r["n"]
    total = sum(counts.values())
    return {c: (n * 100.0 / total if total else 0.0) for c, n in counts.items()}, counts


def decide_penalty(db, post_id, cfg) -> tuple[str | None, int]:
    """Returns (winning_category | None, rp_to_deduct).
    A strictly highest category -> its configured deduction. Any tie for the highest
    (two-way or three-way) -> DEFAULT_PENALTY (5 RP) and no category."""
    pct, counts = category_percentages(db, post_id)
    default = int(cfg.get("DEFAULT_PENALTY", DEFAULT_PENALTY))
    if not any(counts.values()):
        return None, default
    top = max(counts.values())
    leaders = [c for c, n in counts.items() if n == top]
    if len(leaders) != 1:
        return None, default
    return leaders[0], PENALTIES[leaders[0]]


def evaluate_post(db, post_id: int, cfg) -> list[str]:
    post = db.execute("SELECT * FROM news_posts WHERE id=?", (post_id,)).fetchone()
    if post is None or post["status"] == "deleted": return []
    votes = db.execute("SELECT COALESCE(SUM(vote='relevant'),0) AS r, COALESCE(SUM(vote='fake'),0) AS f "
                       "FROM news_votes WHERE post_id=?", (post_id,)).fetchone()
    reached_2x, reached_3x = thresholds(votes["r"], votes["f"], cfg)
    events = []
    prior = db.execute("SELECT 1 FROM moderation_events WHERE post_id=? AND event_type='threshold_2x'", (post_id,)).fetchone()
    if reached_2x and not prior:
        category, deduction = decide_penalty(db, post_id, cfg)
        user = db.execute("SELECT reputation_points FROM users WHERE id=?", (post["user_id"],)).fetchone()
        after = max(0, user["reputation_points"] - deduction)
        db.execute("UPDATE users SET reputation_points=? WHERE id=?", (after, post["user_id"]))
        db.execute("INSERT INTO moderation_events (post_id,user_id,event_type,points_deducted,penalty_category,details) VALUES (?,?,'threshold_2x',?,?,?)", (post_id, post["user_id"], deduction, category, f"2x threshold; relevant={votes['r']} fake={votes['f']}; category={category or 'tie/default'}; deducted={deduction} RP"))
        events.append("threshold_2x")
        if after == 0:
            db.execute("UPDATE users SET status='restricted' WHERE id=?", (post["user_id"],))
            db.execute("INSERT INTO moderation_events (post_id,user_id,event_type,details) VALUES (?,?,'reputation_ban','Reputation reached zero; Citizen ID banned')", (post_id, post["user_id"]))
            events.append("reputation_ban")
    prior_hidden = db.execute("SELECT 1 FROM moderation_events WHERE post_id=? AND event_type='hidden_3x'", (post_id,)).fetchone()
    if reached_3x and post["status"] == "active" and not prior_hidden:
        db.execute("UPDATE news_posts SET status='hidden' WHERE id=?", (post_id,))
        db.execute("INSERT INTO moderation_events (post_id,user_id,event_type,details) VALUES (?,?,'hidden_3x',?)", (post_id, post["user_id"], f"relevant={votes['r']} fake={votes['f']}"))
        events.append("hidden_3x")
    return events

def restore_chance_if_in_window(db, post, cfg) -> bool:
    """Legacy compatibility; penalties are never restored after post deletion."""
    return False
