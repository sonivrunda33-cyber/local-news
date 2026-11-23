"""Public JSON API used by the cascading State -> City -> Area selectors."""
from flask import Blueprint, jsonify, request

from database import get_db
from services import locations

bp = Blueprint("locations", __name__, url_prefix="/api/locations")


@bp.route("/children")
def children():
    parent = request.args.get("parent_id", "")
    if parent == "":
        return jsonify(locations.children(get_db(), None))
    try:
        parent_id = int(parent)
    except ValueError:
        return jsonify(error="Invalid parent_id"), 400
    return jsonify(locations.children(get_db(), parent_id))
