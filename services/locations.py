"""Location tree helpers and importer (State/UT -> City/District -> Area)."""
import csv

from database import transaction


def import_locations_csv(db, csv_path: str) -> dict:
    """Idempotent import. CSV columns: state,city,area (city/area may be blank).
    Existing rows are kept; only missing ones are inserted."""
    added = {"state": 0, "city": 0, "area": 0}

    def get_or_create(parent_id, level, name):
        row = db.execute(
            "SELECT id FROM locations WHERE COALESCE(parent_id,0)=? AND level=? "
            "AND name = ? COLLATE NOCASE", (parent_id or 0, level, name)).fetchone()
        if row:
            return row["id"]
        cur = db.execute("INSERT INTO locations (parent_id, level, name) VALUES (?,?,?)",
                         (parent_id, level, name))
        added[level] += 1
        return cur.lastrowid

    with transaction(db):
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                state = (row.get("state") or "").strip()
                if not state:
                    continue
                sid = get_or_create(None, "state", state)
                city = (row.get("city") or "").strip()
                if not city:
                    continue
                cid = get_or_create(sid, "city", city)
                area = (row.get("area") or "").strip()
                if area:
                    get_or_create(cid, "area", area)
    return added


def seed_if_empty(db, csv_path: str) -> None:
    if db.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0:
        import_locations_csv(db, csv_path)


def children(db, parent_id=None):
    if parent_id is None:
        rows = db.execute("SELECT id, name, level FROM locations WHERE parent_id IS NULL "
                          "ORDER BY name").fetchall()
    else:
        rows = db.execute("SELECT id, name, level FROM locations WHERE parent_id = ? "
                          "ORDER BY name", (parent_id,)).fetchall()
    return [dict(r) for r in rows]


def get(db, location_id):
    return db.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()


def chain(db, location_id):
    """Return dict(state_id, city_id, area_id, state, city, area) for any location."""
    loc = get(db, location_id)
    out = {"state_id": None, "city_id": None, "area_id": None,
           "state": None, "city": None, "area": None}
    while loc is not None:
        out[f"{loc['level']}_id"] = loc["id"]
        out[loc["level"]] = loc["name"]
        loc = get(db, loc["parent_id"]) if loc["parent_id"] else None
    return out


def label(db, location_id) -> str:
    c = chain(db, location_id)
    return ", ".join(p for p in (c["area"], c["city"], c["state"]) if p)


def resolve_selection(db, state_id, city_id, area_id, require_city=True):
    """Validate a cascading selection and return (location_id, error).
    The most specific selected level becomes the location."""
    def to_int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return -1

    state_id, city_id, area_id = to_int(state_id), to_int(city_id), to_int(area_id)
    if state_id is None or state_id == -1:
        return None, "Please select a state or union territory."
    state = get(db, state_id)
    if not state or state["level"] != "state":
        return None, "Invalid state selected."
    if city_id is None:
        if require_city:
            return None, "Please select a city or district."
        return state_id, None
    city = get(db, city_id) if city_id != -1 else None
    if not city or city["level"] != "city" or city["parent_id"] != state_id:
        return None, "Invalid city selected."
    has_areas = db.execute("SELECT 1 FROM locations WHERE parent_id = ? LIMIT 1", (city_id,)).fetchone()
    if area_id is None:
        if has_areas and require_city:
            return None, "Please select a locality or area."
        return city_id, None
    area = get(db, area_id) if area_id != -1 else None
    if not area or area["level"] != "area" or area["parent_id"] != city_id:
        return None, "Invalid area selected."
    return area_id, None
