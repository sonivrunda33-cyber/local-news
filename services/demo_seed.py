"""Idempotent, clearly labelled sample-news seeding for a demo deployment.

These entries are NOT real reports. They exist only to demonstrate the UI and
must be replaced with verified reporting before the site is presented as live news.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from database import now_str
from services.citizen_verification import hash_code

SAMPLE_TOPICS = [
    ("Neighbourhood cleanliness information", "A sample community-information post showing how a cleanliness update can appear in the LOCAL NEWS feed."),
    ("Public-space accessibility note", "A demonstration entry for sharing accessibility information about public spaces. This is placeholder content, not a verified local report."),
    ("Water conservation reminder", "A sample awareness post about responsible water use. It does not describe a confirmed local incident or announcement."),
    ("Community library information", "A placeholder showing how a community resource update could be presented. Confirm all details with an official source before publishing real information."),
    ("Waste segregation awareness", "A sample educational post about separating household waste. This is general demonstration content, not an announcement from a local authority."),
    ("Road-safety awareness note", "A demonstration post for general road-safety awareness. It does not report a road closure, accident, or traffic change."),
    ("Local green-space feature", "A sample feature card demonstrating a positive neighbourhood topic. The text is illustrative and is not a factual claim about a specific park."),
    ("Community noticeboard example", "A placeholder community notice showing the layout of a local update. Replace this sample with verified information before public use."),
]


def _make_demo_image(path: Path, area: str, variant: int) -> None:
    """Create a lightweight illustrative image; deliberately not a news photograph."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    palettes = [((232, 241, 250), (77, 119, 157), (242, 177, 92)),
                ((235, 245, 237), (72, 133, 104), (238, 184, 112)),
                ((246, 239, 231), (147, 105, 78), (104, 151, 166))]
    bg, main, accent = palettes[variant % len(palettes)]
    im = Image.new("RGB", (960, 540), bg)
    d = ImageDraw.Draw(im)
    # Soft horizon and simple abstract neighbourhood skyline.
    d.ellipse((650, 55, 850, 255), fill=(255, 224, 155))
    d.rectangle((0, 390, 960, 540), fill=(main[0] // 2 + 80, main[1] // 2 + 80, main[2] // 2 + 80))
    heights = [130, 205, 160, 250, 180, 220, 145]
    x = 70
    for i, h in enumerate(heights):
        w = 82
        col = tuple(max(0, min(255, c + (i % 3) * 9)) for c in main)
        d.rounded_rectangle((x, 390-h, x+w, 390), radius=8, fill=col)
        for wy in range(390-h+22, 370, 34):
            for wx in (x+18, x+49):
                d.rectangle((wx, wy, wx+12, wy+16), fill=(242, 239, 215))
        x += 112
    d.rounded_rectangle((38, 34, 922, 506), radius=28, outline=(255, 255, 255), width=5)
    try:
        font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()
    d.rounded_rectangle((66, 58, 440, 142), radius=18, fill=(255, 255, 255))
    d.text((88, 78), "SAMPLE ILLUSTRATION", fill=(35, 48, 58), font=font_big)
    d.rounded_rectangle((66, 430, 510, 484), radius=14, fill=(255, 255, 255))
    d.text((88, 445), f"{area}  •  NOT A NEWS PHOTO", fill=(35, 48, 58), font=font_small)
    im.save(path, format="PNG", optimize=True)


def _system_author(db, pepper: str, hash_method: str, location_id: int) -> int:
    row = db.execute(
        "SELECT u.id FROM users u JOIN citizens c ON c.citizen_id=u.citizen_id "
        "WHERE c.citizen_name='LOCAL NEWS Demo Desk' AND c.is_dummy=1 LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    while True:
        citizen_id = str(secrets.randbelow(9 * 10**14) + 10**14)
        if not db.execute("SELECT 1 FROM citizens WHERE citizen_id=?", (citizen_id,)).fetchone():
            break
    private_code = str(secrets.randbelow(9 * 10**7) + 10**7)
    code_hash = hash_code(citizen_id, private_code, pepper, hash_method)
    db.execute(
        "INSERT INTO citizens (citizen_id, code_hash, citizen_name, is_dummy) VALUES (?,?,?,1)",
        (citizen_id, code_hash, "LOCAL NEWS Demo Desk"),
    )
    cur = db.execute(
        "INSERT INTO users (citizen_id, name, current_location_id, reputation_points) VALUES (?,?,?,100)",
        (citizen_id, "LOCAL NEWS Demo Desk", location_id),
    )
    user_id = cur.lastrowid
    db.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
    return user_id


def seed_ahmedabad_demo_news(db, cfg) -> int:
    """Fill each of the three configured Ahmedabad areas up to 8 active posts."""
    area_rows = db.execute(
        "SELECT a.id AS area_id, a.name AS area, c.id AS city_id, s.id AS state_id "
        "FROM locations a JOIN locations c ON c.id=a.parent_id "
        "JOIN locations s ON s.id=c.parent_id "
        "WHERE s.name='Gujarat' AND c.name='Ahmedabad' AND a.name IN ('Navrangpura','Satellite','Maninagar') "
        "ORDER BY a.name"
    ).fetchall()
    if not area_rows:
        return 0

    # Create a non-login service author only if a sample entry is actually needed.
    needs_seed = any(db.execute(
        "SELECT COUNT(*) FROM news_posts WHERE area_id=? AND status='active'", (r["area_id"],)
    ).fetchone()[0] < 8 for r in area_rows)
    if not needs_seed:
        return 0

    first_area = next((r for r in area_rows if r["area"] == "Navrangpura"), area_rows[0])
    author_id = _system_author(db, cfg["CITIZEN_PEPPER"], cfg["HASH_METHOD"], first_area["area_id"])
    upload_dir = Path(cfg["UPLOAD_FOLDER"])
    added = 0
    for area in area_rows:
        active_count = db.execute(
            "SELECT COUNT(*) FROM news_posts WHERE area_id=? AND status='active'", (area["area_id"],)
        ).fetchone()[0]
        needed = max(0, 8 - active_count)
        if not needed:
            continue
        for index, (topic, body) in enumerate(SAMPLE_TOPICS):
            if needed <= 0:
                break
            title = f"[SAMPLE] {area['area']} — {topic}"
            if db.execute("SELECT 1 FROM news_posts WHERE area_id=? AND title=?", (area["area_id"], title)).fetchone():
                continue
            description = (
                f"DEMO CONTENT — NOT A VERIFIED NEWS REPORT. This is placeholder material for testing the "
                f"LOCAL NEWS website in {area['area']}, Ahmedabad. {body} Replace it with independently "
                f"verified local reporting before treating this as live news."
            )
            cur = db.execute(
                "INSERT INTO news_posts (user_id,title,description,location_id,state_id,city_id,area_id,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (author_id, title, description, area["area_id"], area["state_id"], area["city_id"],
                 area["area_id"], now_str()),
            )
            post_id = cur.lastrowid
            # Only two posts per area receive an illustrative (not photographic) image.
            if index in (0, 4):
                filename = f"demo_{area['area'].lower()}_{index+1}.png"
                _make_demo_image(upload_dir / filename, area["area"], index)
                db.execute(
                    "INSERT OR IGNORE INTO news_images (post_id,filename,position) VALUES (?,?,1)",
                    (post_id, filename),
                )
            added += 1
            needed -= 1
    return added
