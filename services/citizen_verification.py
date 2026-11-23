"""Citizen ID verification, secure code hashing, and citizen seeding/import.

Citizen ID Codes are hashed as:  scrypt( HMAC-SHA256(pepper, "<citizen_id>:<code>") )
The pepper lives outside the database (instance/pepper.key or an env var), so a
stolen database file alone cannot be brute-forced offline (an 8-digit code is
otherwise very easy to guess).
"""
import csv
import hashlib
import hmac
import json
import re
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

CITIZEN_ID_RE = re.compile(r"^\d{15}$")
CODE_RE = re.compile(r"^\d{8}$")


def valid_citizen_id(value: str) -> bool:
    return bool(CITIZEN_ID_RE.fullmatch(value or ""))


def valid_code(value: str) -> bool:
    return bool(CODE_RE.fullmatch(value or ""))


def _digest(pepper: str, citizen_id: str, code: str) -> str:
    return hmac.new(pepper.encode(), f"{citizen_id}:{code}".encode(), hashlib.sha256).hexdigest()


def hash_code(citizen_id: str, code: str, pepper: str, method: str = "scrypt") -> str:
    return generate_password_hash(_digest(pepper, citizen_id, code), method=method)


def verify_code(stored_hash: str, citizen_id: str, code: str, pepper: str) -> bool:
    return check_password_hash(stored_hash, _digest(pepper, citizen_id, code))


# A throw-away hash so unknown Citizen IDs cost the same time as known ones.
_DECOY_CACHE: dict = {}


def decoy_verify(pepper: str, method: str, citizen_id: str, code: str) -> None:
    if method not in _DECOY_CACHE:
        _DECOY_CACHE[method] = hash_code("0" * 15, "00000000", pepper, method)
    verify_code(_DECOY_CACHE[method], citizen_id, code, pepper)


def find_citizen(db, citizen_id: str):
    return db.execute("SELECT * FROM citizens WHERE citizen_id = ?", (citizen_id,)).fetchone()


def verify_citizen(db, citizen_id: str, code: str, pepper: str, method: str):
    """Return the citizen row if the ID + code match the trusted Citizen Database."""
    if not (valid_citizen_id(citizen_id) and valid_code(code)):
        return None
    citizen = find_citizen(db, citizen_id)
    if citizen is None:
        decoy_verify(pepper, method, citizen_id, code)
        return None
    return citizen if verify_code(citizen["code_hash"], citizen_id, code, pepper) else None


def _insert_citizen(db, cid, name, code, pepper, method, is_dummy) -> bool:
    if not valid_citizen_id(cid) or not valid_code(code) or not name.strip():
        raise ValueError(f"Invalid citizen record for ID {cid!r}")
    cur = db.execute(
        "INSERT OR IGNORE INTO citizens (citizen_id, code_hash, citizen_name, is_dummy) "
        "VALUES (?, ?, ?, ?)",
        (cid, hash_code(cid, code, pepper, method), name.strip(), 1 if is_dummy else 0))
    return cur.rowcount == 1


def seed_dummy_citizens(db, json_path: str, pepper: str, method: str) -> int:
    """Idempotent: existing Citizen IDs are skipped, so restarts never duplicate rows."""
    path = Path(json_path)
    if not path.exists():
        return 0
    records = json.loads(path.read_text(encoding="utf-8"))["citizens"]
    added = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        for r in records:
            if db.execute("SELECT 1 FROM citizens WHERE citizen_id = ?", (r["Citizen_ID"],)).fetchone():
                continue
            added += _insert_citizen(db, r["Citizen_ID"], r["Citizen_Name"],
                                     r["Citizen_ID_Code"], pepper, method, True)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return added


def import_citizens_csv(db, csv_path: str, pepper: str, method: str) -> tuple[int, int]:
    """Import real citizen records from a CSV with columns:
    Citizen_ID,Citizen_ID_Code,Citizen_Name.  Returns (added, skipped_existing)."""
    added = skipped = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ok = _insert_citizen(db, row["Citizen_ID"].strip(), row["Citizen_Name"],
                                     row["Citizen_ID_Code"].strip(), pepper, method, False)
                added += ok
                skipped += not ok
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return added, skipped


def mask_citizen_id(citizen_id: str) -> str:
    """Display safely: show only the first 3 and last 3 digits."""
    return f"{citizen_id[:3]}{'•' * 9}{citizen_id[-3:]}"
