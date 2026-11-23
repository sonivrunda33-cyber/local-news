"""Profile page: citizen name, safe Citizen ID, locations, saved news, status."""
from flask import Blueprint, g, render_template

from database import get_db
from routes.common import login_required
from services import citizen_verification as cv
from services import locations, news_service

bp = Blueprint("profile", __name__)


def followed_with_labels(db, user_id):
    rows = db.execute("SELECT location_id FROM followed_locations WHERE user_id=? "
                      "ORDER BY created_at, location_id", (user_id,)).fetchall()
    return [{"id": r["location_id"], "label": locations.label(db, r["location_id"])} for r in rows]


@bp.route("/profile")
@login_required
def profile():
    db = get_db()
    user = g.user
    restriction = db.execute("SELECT reason, created_at FROM account_restrictions WHERE user_id=?",
                             (user["id"],)).fetchone()
    banned = bool(db.execute("SELECT 1 FROM moderation_events WHERE user_id=? AND event_type='reputation_ban' LIMIT 1", (user["id"],)).fetchone())
    return render_template(
        "profile.html",
        masked_id=cv.mask_citizen_id(user["citizen_id"]),
        current_location=locations.label(db, user["current_location_id"]) if user["current_location_id"] else None,
        followed=followed_with_labels(db, user["id"]),
        saved=news_service.saved_list(db, user["id"]),
        my_posts=news_service.my_posts(db, user["id"]),
        restriction=restriction, banned=banned)
