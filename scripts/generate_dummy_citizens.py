"""Generate DUMMY / TEST citizen records (development only).

Usage:  python scripts/generate_dummy_citizens.py [count]

Writes data/dummy_citizens.json containing plain-text test credentials.
This file is for LOCAL TESTING ONLY. It is never served by the website and the
application never loads it when LOCAL_NEWS_ENV=production.

All values are fictional and are NOT real government-issued identity numbers.
"""
import json
import secrets
import sys
from pathlib import Path

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karthik", "Siddharth", "Rahul",
         "Ananya", "Diya", "Isha", "Meera", "Priya", "Kavya", "Neha", "Sneha", "Lakshmi",
         "Farhan", "Zoya", "Gurpreet", "Harleen", "Ishaan", "Tanvi", "Manoj", "Deepa",
         "Suresh", "Anjali", "Vikram", "Pooja", "Nikhil"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Gupta", "Singh", "Kulkarni",
        "Das", "Banerjee", "Chatterjee", "Mehta", "Joshi", "Menon", "Pillai", "Khan",
        "Naidu", "Bhatt", "Rao", "Chauhan", "Mishra", "Yadav", "Shetty", "Kaur"]


def generate(count: int = 22):
    names, ids, codes, records = set(), set(), set(), []
    while len(records) < count:
        name = f"{secrets.choice(FIRST)} {secrets.choice(LAST)}"
        cid = str(secrets.randbelow(9 * 10**14) + 10**14)      # 15 digits, no leading 0
        code = str(secrets.randbelow(9 * 10**7) + 10**7)       # 8 digits, no leading 0
        if name in names or cid in ids or code in codes:
            continue
        names.add(name), ids.add(cid), codes.add(code)
        records.append({"Citizen_Name": name, "Citizen_ID": cid, "Citizen_ID_Code": code})
    return records


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 22
    out = Path(__file__).resolve().parent.parent / "data" / "dummy_citizens.json"
    payload = {
        "_notice": "DUMMY / TEST DATA - fictional development credentials. Not real identity numbers.",
        "citizens": generate(count),
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {count} dummy citizens to {out}")
