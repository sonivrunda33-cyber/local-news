"""News queries and operations: create, delete, home sections, featured, saved."""
from database import now_str, parse_ts, transaction, utcnow
from services import images, locations, moderation

CARD_SELECT = """
SELECT p.id, p.title, p.description, p.status, p.relevant_count, p.fake_count, p.created_at,
       p.area_id, p.city_id, p.state_id, p.user_id, p.window_expires_at, u.name AS author_name,
       a.name AS area_name, c.name AS city_name, s.name AS state_name,
       (SELECT filename FROM news_images WHERE post_id = p.id ORDER BY position LIMIT 1) AS cover,
       (SELECT COUNT(*) FROM news_images WHERE post_id = p.id) AS image_count,
       v.vote AS my_vote, (sv.post_id IS NOT NULL) AS saved
FROM news_posts p
JOIN users u ON u.id = p.user_id
JOIN locations s ON s.id = p.state_id
LEFT JOIN locations c ON c.id = p.city_id
LEFT JOIN locations a ON a.id = p.area_id
LEFT JOIN news_votes v ON v.post_id = p.id AND v.user_id = :uid
LEFT JOIN saved_news sv ON sv.post_id = p.id AND sv.user_id = :uid
"""


class NewsError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def location_label(row) -> str:
    return ", ".join(x for x in (row["area_name"], row["city_name"], row["state_name"]) if x)


# ---- create / delete ----------------------------------------------------------
def create_post(db, cfg, user, title, description, files):
    """Validate + store images first, then insert everything in one transaction."""
    if user["status"] != "active":
        raise NewsError("Your account is read-only and cannot publish news.", 403)
    if user["current_location_id"] is None:
        raise NewsError("Set your current location before publishing.")
    files = [f for f in files if f and f.filename]
    if len(files) > cfg["MAX_IMAGES_PER_POST"]:
        raise NewsError(f"You can upload at most {cfg['MAX_IMAGES_PER_POST']} images.")
    dup = db.execute("SELECT 1 FROM news_posts WHERE user_id=? AND lower(title)=lower(?) "
                     "AND status!='deleted' AND created_at >= datetime('now','-1 day')",
                     (user["id"], title)).fetchone()
    if dup:
        raise NewsError("You already published news with this title in the last 24 hours.")

    saved_files = []
    try:
        for f in files:
            try:
                saved_files.append(images.save_image(f, cfg["UPLOAD_FOLDER"], cfg["MAX_IMAGE_BYTES"],
                                                     cfg["MAX_IMAGE_PIXELS"]))
            except images.ImageError as exc:
                raise NewsError(str(exc))
        chain = locations.chain(db, user["current_location_id"])
        with transaction(db):
            cur = db.execute(
                "INSERT INTO news_posts (user_id, title, description, location_id, state_id, city_id, area_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (user["id"], title, description, user["current_location_id"],
                 chain["state_id"], chain["city_id"], chain["area_id"]))
            post_id = cur.lastrowid
            for pos, fn in enumerate(saved_files, start=1):
                db.execute("INSERT INTO news_images (post_id, filename, position) VALUES (?,?,?)",
                           (post_id, fn, pos))
            # Reward successful publishing once per created post; reputation is capped.
            reward = int(cfg.get("NEWS_PUBLISH_REWARD", 3))
            maximum = int(cfg.get("MAX_REPUTATION", 100))
            db.execute(
                "UPDATE users SET reputation_points = MIN(?, reputation_points + ?) WHERE id=?",
                (maximum, reward, user["id"]))
        return post_id
    except BaseException:
        images.remove_files(cfg["UPLOAD_FOLDER"], saved_files)
        raise


def delete_post(db, cfg, user_id, post_id) -> dict:
    """Creators may delete their own posts at any time. Deletion never reverses an RP penalty."""
    with transaction(db):
        post = db.execute("SELECT * FROM news_posts WHERE id=?", (post_id,)).fetchone()
        if post is None or post["status"] == "deleted":
            raise NewsError("News not found.", 404)
        if post["user_id"] != user_id:
            raise NewsError("You can only delete your own news.", 403)
        restored = False
        files = [r["filename"] for r in db.execute(
            "SELECT filename FROM news_images WHERE post_id=?", (post_id,))]
        db.execute("DELETE FROM news_images WHERE post_id=?", (post_id,))
        db.execute("UPDATE news_posts SET status='deleted', deleted_at=? WHERE id=?",
                   (now_str(), post_id))
    images.remove_files(cfg["UPLOAD_FOLDER"], files)
    return {"chance_restored": restored}


# ---- reading --------------------------------------------------------------------
def get_post(db, user, post_id):
    """Returns (row, images). Hidden posts are visible only to their creator;
    deleted posts are never visible."""
    row = db.execute(CARD_SELECT + " WHERE p.id = :pid", {"uid": user["id"], "pid": post_id}).fetchone()
    if row is None or row["status"] == "deleted":
        return None, []
    if row["status"] == "hidden" and row["user_id"] != user["id"]:
        return None, []
    imgs = [r["filename"] for r in db.execute(
        "SELECT filename FROM news_images WHERE post_id=? ORDER BY position", (post_id,))]
    return row, imgs


def _user_scope(db, user):
    """IDs of the areas / cities / states the user cares about (current + followed)."""
    areas, cities, states = set(), set(), set()
    loc_ids = []
    if user["current_location_id"]:
        loc_ids.append(user["current_location_id"])
    loc_ids += [r["location_id"] for r in db.execute(
        "SELECT location_id FROM followed_locations WHERE user_id=?", (user["id"],))]
    for lid in loc_ids:
        ch = locations.chain(db, lid)
        if ch["area_id"]:
            areas.add(ch["area_id"])
        if ch["city_id"]:
            cities.add(ch["city_id"])
        if ch["state_id"]:
            states.add(ch["state_id"])
    return areas, cities, states


def _in_clause(ids):
    ids = sorted(ids) or [-1]
    return ",".join("?" * len(ids)), ids


def resolve_home_location(db, state_id, city_id, area_id):
    location_id, error = locations.resolve_selection(db, state_id, city_id, area_id, require_city=False)
    if error: return None, error
    return location_id, None


def home_sections(db, user, limit=10, selected_location=None):
    """Four tiers, most local first. A post appears in only one tier."""
    areas, cities, states = _user_scope(db, user)
    if selected_location:
        chain = locations.chain(db, selected_location)
        areas = {chain["area_id"]} if chain["area_id"] else set()
        cities = {chain["city_id"]} if chain["city_id"] else set()
        states = {chain["state_id"]} if chain["state_id"] else set()
        if chain["state_id"] and not chain["city_id"]:
            cities = {r["id"] for r in db.execute("SELECT id FROM locations WHERE parent_id=? AND level='city'", (chain["state_id"],))}
        if not chain["area_id"]:
            # City (or whole state) selected: every area inside it is shown in the Area section.
            areas = {r["id"] for city_id in cities for r in db.execute("SELECT id FROM locations WHERE parent_id=? AND level='area'", (city_id,))}
    base = CARD_SELECT + " WHERE p.status = 'active' "

    def run(extra, params):
        q = base + extra + " ORDER BY p.created_at DESC, p.id DESC LIMIT ?"
        # sqlite named + positional can't mix; use positional for the IN lists
        return db.execute(q.replace(":uid", "?"), [user["id"], user["id"]] + params + [limit]).fetchall()

    a_sql, a_ids = _in_clause(areas)
    c_sql, c_ids = _in_clause(cities)
    s_sql, s_ids = _in_clause(states)
    area = run(f"AND p.area_id IN ({a_sql})", a_ids)
    city = run(f"AND p.city_id IN ({c_sql}) AND COALESCE(p.area_id,-1) NOT IN ({a_sql})", c_ids + a_ids)
    return {"area": area, "city": city}


def featured(db, user, limit=6):
    """Featured slideshow: recent posts WITH images from the last 7 days, ranked by
         location tier (area 4, followed/city 3, state 2, rest 0) * 10
         + (Relevant - Fake) - age_in_days
    Ties are broken by newest first."""
    areas, cities, states = _user_scope(db, user)
    rows = db.execute(
        CARD_SELECT.replace(":uid", "?") +
        " WHERE p.status='active' AND p.created_at >= datetime('now','-7 days') "
        " AND EXISTS (SELECT 1 FROM news_images i WHERE i.post_id = p.id)",
        [user["id"], user["id"]]).fetchall()
    now = utcnow()

    def score(r):
        tier = (4 if r["area_id"] in areas else 3 if r["city_id"] in cities
                else 2 if r["state_id"] in states else 0)
        age_days = (now - parse_ts(r["created_at"])).total_seconds() / 86400
        return tier * 10 + (r["relevant_count"] - r["fake_count"]) - age_days

    return sorted(rows, key=score, reverse=True)[:limit]


def saved_list(db, user_id):
    return db.execute(
        "SELECT sv.saved_at, p.id, p.title, p.status, "
        "       (SELECT filename FROM news_images WHERE post_id=p.id ORDER BY position LIMIT 1) AS cover, "
        "       p.user_id "
        "FROM saved_news sv JOIN news_posts p ON p.id = sv.post_id "
        "WHERE sv.user_id=? ORDER BY sv.saved_at DESC, p.id DESC", (user_id,)).fetchall()


def my_posts(db, user_id):
    return db.execute(
        "SELECT id, title, status, relevant_count, fake_count, created_at, window_expires_at "
        "FROM news_posts WHERE user_id=? AND status!='deleted' ORDER BY created_at DESC, id DESC",
        (user_id,)).fetchall()


def toggle_save(db, user_id, post_id) -> bool:
    """Save/unsave. Returns True when the post is saved afterwards."""
    with transaction(db):
        post = db.execute("SELECT status, user_id FROM news_posts WHERE id=?", (post_id,)).fetchone()
        exists = db.execute("SELECT 1 FROM saved_news WHERE user_id=? AND post_id=?",
                            (user_id, post_id)).fetchone()
        if exists:
            db.execute("DELETE FROM saved_news WHERE user_id=? AND post_id=?", (user_id, post_id))
            return False
        visible = post and (post["status"] == "active" or
                            (post["status"] == "hidden" and post["user_id"] == user_id))
        if not visible:
            raise NewsError("This news is no longer available.", 404)
        db.execute("INSERT INTO saved_news (user_id, post_id) VALUES (?,?)", (user_id, post_id))
        return True
