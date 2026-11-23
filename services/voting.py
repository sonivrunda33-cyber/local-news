"""Relevant / Fake voting. One transaction per vote (race-condition safe)."""
import sqlite3

from database import transaction
from services import moderation

FAKE_REASONS = ("False", "Misleading", "Inaccurate")


class VoteError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def cast_vote(db, cfg, user_id: int, post_id: int, vote: str, reason: str | None) -> dict:
    if vote not in ("relevant", "fake"):
        raise VoteError("Invalid vote.")
    if vote == "fake" and reason not in FAKE_REASONS:
        raise VoteError("Please choose a reason: False, Misleading or Inaccurate.")
    if vote == "relevant":
        reason = None

    with transaction(db):
        user = db.execute("SELECT status FROM users WHERE id=?", (user_id,)).fetchone()
        if user is None or user["status"] != "active":
            raise VoteError("Your account is read-only and cannot vote.", 403)
        post = db.execute("SELECT * FROM news_posts WHERE id=?", (post_id,)).fetchone()
        if post is None or post["status"] != "active":
            raise VoteError("This news is no longer available.", 404)
        if post["user_id"] == user_id:
            raise VoteError("You cannot vote on your own news.", 403)
        try:
            db.execute("INSERT INTO news_votes (post_id, user_id, vote, fake_reason) VALUES (?,?,?,?)",
                       (post_id, user_id, vote, reason))
        except sqlite3.IntegrityError:
            raise VoteError("You have already voted on this news.", 409)
        column = "relevant_count" if vote == "relevant" else "fake_count"
        db.execute(f"UPDATE news_posts SET {column} = {column} + 1 WHERE id = ?", (post_id,))
        events = moderation.evaluate_post(db, post_id, cfg)
        fresh = db.execute("SELECT relevant_count, fake_count, status FROM news_posts WHERE id=?",
                           (post_id,)).fetchone()
    return {"relevant": fresh["relevant_count"], "fake": fresh["fake_count"],
            "status": fresh["status"], "my_vote": vote, "events": events}
