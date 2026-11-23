"""LOCAL NEWS - Flask application factory.

Run:  python app.py        (or:  flask --app app run)
"""
import hmac
import secrets
from datetime import timedelta

from flask import Flask, abort, g, jsonify, render_template, request, session, send_from_directory

import database
from config import build_config
from database import close_db, get_db, init_db, parse_ts, utcnow


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(build_config())
    if test_config:
        app.config.update(test_config)

    from pathlib import Path
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    init_db(app)
    app.teardown_appcontext(close_db)

    from routes import auth, locations, news, profile, settings
    for bp in (auth.bp, locations.bp, news.bp, profile.bp, settings.bp):
        app.register_blueprint(bp)

    import cli
    cli.register(app)

    @app.route("/healthz")
    def healthz():
        return jsonify(status="ok"), 200

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename, max_age=3600)

    @app.route("/welcome")
    def welcome():
        from services import locations
        return render_template("register.html", states=locations.children(get_db()), form={})

    # ---- per-request user -----------------------------------------------------
    @app.before_request
    def load_user():
        g.user = None
        g.theme = "light"
        uid = session.get("user_id")
        if uid:
            row = get_db().execute(
                "SELECT u.*, s.theme FROM users u LEFT JOIN user_settings s ON s.user_id=u.id "
                "WHERE u.id=?", (uid,)).fetchone()
            if row is None:
                session.clear()
            else:
                g.user = row
                g.theme = row["theme"] or "light"

    # ---- CSRF protection (token in session; form field or X-CSRF-Token header)
    @app.before_request
    def csrf_protect():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            if not hmac.compare_digest(sent, session["csrf_token"]):
                if request.accept_mimetypes.best == "application/json" or request.is_json \
                        or request.headers.get("X-Requested-With") == "fetch":
                    return jsonify(error="Security check failed. Please reload the page."), 400
                abort(400, "Security check failed (CSRF). Please go back, reload the page and try again.")

    @app.context_processor
    def inject_globals():
        return {"csrf_token": session.get("csrf_token", ""), "current_user": g.get("user"),
                "theme": g.get("theme", "light"), "cfg": app.config}

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        if g.get("user") is not None:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---- template helpers --------------------------------------------------------
    @app.template_filter("timeago")
    def timeago(value):
        dt = parse_ts(value)
        if not dt:
            return ""
        seconds = int((utcnow() - dt).total_seconds())
        if seconds < 60:
            return "just now"
        for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
            if seconds >= size:
                n = seconds // size
                return f"{n} {unit}{'s' if n != 1 else ''} ago"
        return ""

    @app.template_filter("ist")
    def ist(value):
        dt = parse_ts(value)
        return (dt + timedelta(hours=5, minutes=30)).strftime("%d %b %Y, %I:%M %p IST") if dt else ""

    @app.template_filter("window_left")
    def window_left(value):
        dt = parse_ts(value)
        if not dt:
            return 0
        return max(0, int((dt - utcnow()).total_seconds()))

    # ---- errors ---------------------------------------------------------------------
    def wants_json():
        return request.path.startswith("/api/") or request.is_json or \
            request.headers.get("X-Requested-With") == "fetch"

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(429)
    @app.errorhandler(500)
    def handle_error(err):
        code = getattr(err, "code", 500)
        messages = {400: "Bad request.", 403: "You are not allowed to do that.",
                    404: "We couldn't find that page.", 413: "Upload is too large.",
                    429: "Too many requests.", 500: "Something went wrong on our side."}
        message = getattr(err, "description", None) if code in (400, 413) else None
        message = message or messages.get(code, "Error")
        if wants_json():
            return jsonify(error=message), code
        return render_template("error.html", code=code, message=message), code

    return app


if __name__ == "__main__":
    # debug is off by default; enable only for local development: LOCAL_NEWS_DEBUG=1
    import os
    create_app().run(host="127.0.0.1", port=5000, debug=os.environ.get("LOCAL_NEWS_DEBUG") == "1")
