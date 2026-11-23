"""Shared route helpers."""
from functools import wraps

from flask import flash, g, jsonify, redirect, request, url_for


def wants_json() -> bool:
    return (request.path.startswith("/api/") or request.is_json
            or request.headers.get("X-Requested-With") == "fetch")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if wants_json():
                return jsonify(error="Please log in first."), 401
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth.register", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def client_ip() -> str:
    return request.remote_addr or "unknown"


def safe_next(target: str | None) -> str:
    """Only allow local, relative redirects (prevents open redirects)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("news.home")
