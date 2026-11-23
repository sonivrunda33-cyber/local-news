"""Home page, publishing, viewing, deleting, voting and saving news."""
from flask import (Blueprint, current_app, flash, g, jsonify, redirect, render_template,
                   request, url_for)

from database import get_db, transaction
from routes.common import login_required
from services import news_service, rate_limit, validation, voting
from services.news_service import NewsError

bp = Blueprint("news", __name__)


@bp.route("/")
@login_required
def home():
    db = get_db()
    from services import locations
    states = locations.children(db)
    state_id, city_id, area_id = request.args.get('state_id'), request.args.get('city_id'), request.args.get('area_id')
    selected_location = None
    if state_id or city_id or area_id:
        # Explicit (URL) selection: validated and applied, but only the POST below persists it.
        selected_location, error = news_service.resolve_home_location(db, state_id, city_id, area_id)
        if error:
            flash(error, "error")
            state_id = city_id = area_id = None
            selected_location = None
    elif g.user["news_filter_location_id"]:
        # Persisted selection (survives refresh and logout/login).
        selected_location = g.user["news_filter_location_id"]
        if locations.get(db, selected_location) is None:
            selected_location = None
    filter_label = None
    if selected_location:
        chain = locations.chain(db, selected_location)
        state_id, city_id, area_id = chain["state_id"], chain["city_id"], chain["area_id"]
        filter_label = locations.label(db, selected_location)
    sections = news_service.home_sections(db, g.user, selected_location=selected_location)
    return render_template("home.html", featured=news_service.featured(db, g.user), sections=sections,
                         news_service=news_service, states=states, filter_label=filter_label,
                         location_form={"state_id": state_id or "", "city_id": city_id or "", "area_id": area_id or ""})


@bp.route("/news/location", methods=["POST"])
@login_required
def set_news_location():
    """Validate and persist the 'Choose news location' selection, then show the filtered news."""
    db = get_db()
    try:
        rate_limit.check_and_record(db, f"user:{g.user['id']}", "location")
    except rate_limit.RateLimited as exc:
        flash(str(exc), "error")
        return redirect(url_for("news.home"))
    location_id, error = news_service.resolve_home_location(
        db, request.form.get("state_id"), request.form.get("city_id"), request.form.get("area_id"))
    if error:
        flash(error, "error")
        return redirect(url_for("news.home"))
    with transaction(db):
        db.execute("UPDATE users SET news_filter_location_id=? WHERE id=?", (location_id, g.user["id"]))
    flash("News location saved: " + locations_label(db, location_id), "success")
    return redirect(url_for("news.home"))


@bp.route("/news/location/clear", methods=["POST"])
@login_required
def clear_news_location():
    """Back to the default: news for the user's own (and followed) locations."""
    db = get_db()
    with transaction(db):
        db.execute("UPDATE users SET news_filter_location_id=NULL WHERE id=?", (g.user["id"],))
    flash("Showing news for your location.", "success")
    return redirect(url_for("news.home"))


def locations_label(db, location_id):
    from services import locations
    return locations.label(db, location_id)


@bp.route("/news/create", methods=["GET", "POST"])
@login_required
def create():
    db, cfg = get_db(), current_app.config
    if g.user["status"] != "active":
        flash("Your account is read-only. You can read news but not publish.", "error")
        return redirect(url_for("news.home"))
    if request.method == "POST":
        title, description, error = validation.validate_news_text(
            request.form.get("title", ""), request.form.get("description", ""), cfg)
        if not error:
            try:
                rate_limit.check_and_record(db, f"user:{g.user['id']}", "post")
                post_id = news_service.create_post(db, cfg, g.user, title, description,
                                                   request.files.getlist("images"))
                flash("Your news has been published. Published news cannot be edited.", "success")
                return redirect(url_for("news.detail", post_id=post_id))
            except rate_limit.RateLimited as exc:
                error = str(exc)
            except NewsError as exc:
                error = str(exc)
        flash(error, "error")
        return render_template("create_news.html", form_title=title, form_description=description), 400
    return render_template("create_news.html", form_title="", form_description="")


@bp.route("/news/<int:post_id>")
@login_required
def detail(post_id):
    post, imgs = news_service.get_post(get_db(), g.user, post_id)
    if post is None:
        return render_template("error.html", code=404, message="This news is not available."), 404
    return render_template("news_detail.html", post=post, images=imgs, news_service=news_service)


@bp.route("/news/<int:post_id>/delete", methods=["POST"])
@login_required
def delete(post_id):
    try:
        result = news_service.delete_post(get_db(), current_app.config, g.user["id"], post_id)
    except NewsError as exc:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(error=str(exc)), exc.status
        flash(str(exc), "error")
        return redirect(url_for("news.home"))
    msg = "News deleted. Any reputation penalty already applied remains."
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, message=msg)
    flash(msg, "success")
    return redirect(url_for("profile.profile"))


@bp.route("/api/news/<int:post_id>/vote", methods=["POST"])
@login_required
def vote(post_id):
    data = request.get_json(silent=True) or {}
    try:
        rate_limit.check_and_record(get_db(), f"user:{g.user['id']}", "vote")
        result = voting.cast_vote(get_db(), current_app.config, g.user["id"], post_id,
                                  data.get("vote"), data.get("reason"))
    except rate_limit.RateLimited as exc:
        return jsonify(error=str(exc)), 429
    except voting.VoteError as exc:
        return jsonify(error=str(exc)), exc.status
    return jsonify(result)


@bp.route("/api/news/<int:post_id>/save", methods=["POST"])
@login_required
def save(post_id):
    try:
        rate_limit.check_and_record(get_db(), f"user:{g.user['id']}", "save")
        saved = news_service.toggle_save(get_db(), g.user["id"], post_id)
    except rate_limit.RateLimited as exc:
        return jsonify(error=str(exc)), 429
    except NewsError as exc:
        return jsonify(error=str(exc)), exc.status
    return jsonify(saved=saved)
