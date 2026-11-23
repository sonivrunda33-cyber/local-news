"""Registration, login and logout using Citizen ID + Citizen ID Code."""
import sqlite3

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

from database import get_db, transaction
from routes.common import client_ip, safe_next
from services import citizen_verification as cv
from services import locations, rate_limit

bp = Blueprint("auth", __name__)

GENERIC_LOGIN_ERROR = "Invalid Citizen ID or Citizen ID Code."


def _start_session(user_id: int) -> None:
    session.clear()                       # prevents session fixation
    session["user_id"] = user_id
    session.permanent = True


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("news.home"))
    db, cfg = get_db(), current_app.config
    states = locations.children(db)
    if request.method == "POST":
        citizen_id = request.form.get("citizen_id", "").strip()
        code = request.form.get("citizen_id_code", "").strip()
        form = {"citizen_id": citizen_id, "state_id": request.form.get("state_id", ""),
                "city_id": request.form.get("city_id", ""), "area_id": request.form.get("area_id", "")}
        try:
            rate_limit.check_and_record(db, f"ip:{client_ip()}", "register")
        except rate_limit.RateLimited as exc:
            flash(str(exc), "error")
            return render_template("register.html", states=states, form=form), 429

        error = None
        if not cv.valid_citizen_id(citizen_id):
            error = "Citizen ID must be exactly 15 digits."
        elif not cv.valid_code(code):
            error = "Citizen ID Code must be exactly 8 digits."
        location_id = None
        if not error:
            location_id, error = locations.resolve_selection(
                db, form["state_id"], form["city_id"], form["area_id"])
        if not error and rate_limit.login_locked(db, citizen_id, client_ip()):
            error = "Too many failed attempts. Please try again later."
        citizen = None
        if not error:
            citizen = cv.verify_citizen(db, citizen_id, code, cfg["CITIZEN_PEPPER"], cfg["HASH_METHOD"])
            if citizen is None:
                rate_limit.record_login_failure(db, citizen_id, client_ip())
                error = "Citizen ID and Citizen ID Code do not match our Citizen Database."
        if error:
            flash(error, "error")
            return render_template("register.html", states=states, form=form), 400

        try:
            with transaction(db):
                cur = db.execute(
                    "INSERT INTO users (citizen_id, name, current_location_id, reputation_points) "
                    "VALUES (?,?,?,?)",
                    (citizen["citizen_id"], citizen["citizen_name"], location_id, cfg["INITIAL_REPUTATION"]))
                db.execute("INSERT INTO user_settings (user_id) VALUES (?)", (cur.lastrowid,))
        except sqlite3.IntegrityError:        # UNIQUE(users.citizen_id)
            flash("This Citizen ID is already registered. Please log in.", "error")
            return render_template("register.html", states=states, form=form), 409

        rate_limit.clear_login_failures(db, citizen_id)
        _start_session(cur.lastrowid)
        flash(f"Welcome, {citizen['citizen_name']}!", "success")
        return redirect(url_for("news.home"))
    return render_template("register.html", states=states, form={})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("news.home"))
    db, cfg = get_db(), current_app.config
    if request.method == "POST":
        citizen_id = request.form.get("citizen_id", "").strip()
        code = request.form.get("citizen_id_code", "").strip()
        ip = client_ip()
        if rate_limit.login_locked(db, citizen_id, ip):
            flash(f"Too many failed attempts. Try again in {cfg['LOGIN_LOCK_MINUTES']} minutes.", "error")
            return render_template("login.html", citizen_id=citizen_id), 429
        citizen = cv.verify_citizen(db, citizen_id, code, cfg["CITIZEN_PEPPER"], cfg["HASH_METHOD"])
        user = None
        if citizen:
            user = db.execute("SELECT id, status FROM users WHERE citizen_id=?", (citizen_id,)).fetchone()
        if citizen is None:
            rate_limit.record_login_failure(db, citizen_id, ip)
            flash(GENERIC_LOGIN_ERROR, "error")
            return render_template("login.html", citizen_id=citizen_id), 401
        if user is not None and (user["status"] == "banned" or db.execute("SELECT 1 FROM moderation_events WHERE user_id=? AND event_type='reputation_ban' LIMIT 1", (user["id"],)).fetchone()):
            flash("This Citizen ID is permanently banned.", "error")
            return render_template("login.html", citizen_id=citizen_id), 403
        if user is None:
            flash("This Citizen ID is valid but not registered yet. Please register first.", "info")
            return redirect(url_for("auth.register"))
        rate_limit.clear_login_failures(db, citizen_id)
        _start_session(user["id"])
        return redirect(safe_next(request.args.get("next")))
    return render_template("login.html", citizen_id="")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
