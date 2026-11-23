"""Settings: theme, current location, followed locations, logout."""
from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from database import get_db, transaction
from routes.common import login_required
from routes.profile import followed_with_labels
from services import locations, rate_limit

bp = Blueprint("settings", __name__)

THEMES = ("light", "night")


@bp.route("/settings")
@login_required
def settings():
    db = get_db()
    return render_template(
        "settings.html", states=locations.children(db),
        current_location=locations.label(db, g.user["current_location_id"]) if g.user["current_location_id"] else None,
        followed=followed_with_labels(db, g.user["id"]), reputation=g.user["reputation_points"])


@bp.route("/settings/theme", methods=["POST"])
@login_required
def set_theme():
    theme = (request.get_json(silent=True) or {}).get("theme") or request.form.get("theme")
    if theme not in THEMES:
        if request.is_json:
            return jsonify(error="Invalid theme."), 400
        flash("Invalid theme.", "error")
        return redirect(url_for("settings.settings"))
    db = get_db()
    with transaction(db):
        db.execute("INSERT INTO user_settings (user_id, theme, updated_at) VALUES (?, ?, datetime('now')) "
                   "ON CONFLICT(user_id) DO UPDATE SET theme=excluded.theme, updated_at=excluded.updated_at",
                   (g.user["id"], theme))
    if request.is_json:
        return jsonify(theme=theme)
    return redirect(url_for("settings.settings"))


def _resolve_from_form(require_city):
    return locations.resolve_selection(get_db(), request.form.get("state_id"), request.form.get("city_id"),
                                       request.form.get("area_id"), require_city=require_city)


@bp.route("/settings/location", methods=["POST"])
@login_required
def change_location():
    db = get_db()
    try:
        rate_limit.check_and_record(db, f"user:{g.user['id']}", "location")
    except rate_limit.RateLimited as exc:
        flash(str(exc), "error")
        return redirect(url_for("settings.settings"))
    location_id, error = _resolve_from_form(require_city=True)
    if error:
        flash(error, "error")
        return redirect(url_for("settings.settings"))
    with transaction(db):
        db.execute("UPDATE users SET current_location_id=? WHERE id=?", (location_id, g.user["id"]))
    flash("Current location updated.", "success")
    return redirect(url_for("settings.settings"))


@bp.route("/settings/follow", methods=["POST"])
@login_required
def follow():
    db = get_db()
    try:
        rate_limit.check_and_record(db, f"user:{g.user['id']}", "location")
    except rate_limit.RateLimited as exc:
        flash(str(exc), "error")
        return redirect(url_for("settings.settings"))
    location_id, error = _resolve_from_form(require_city=False)
    if error:
        flash(error, "error")
        return redirect(url_for("settings.settings"))
    with transaction(db):
        cur = db.execute("INSERT OR IGNORE INTO followed_locations (user_id, location_id) VALUES (?,?)",
                         (g.user["id"], location_id))
    flash("Location followed." if cur.rowcount else "You already follow this location.",
          "success" if cur.rowcount else "info")
    return redirect(url_for("settings.settings"))


@bp.route("/settings/unfollow/<int:location_id>", methods=["POST"])
@login_required
def unfollow(location_id):
    db = get_db()
    with transaction(db):
        db.execute("DELETE FROM followed_locations WHERE user_id=? AND location_id=?",
                   (g.user["id"], location_id))
    flash("Location removed from followed locations.", "success")
    return redirect(url_for("settings.settings"))
