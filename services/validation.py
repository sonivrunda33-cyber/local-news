"""Backend input validation and basic malicious-content / spam checks.

These checks are heuristics. They reduce abuse; they cannot decide whether a
news item is true.
"""
import re

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SUSPICIOUS = re.compile(r"(<\s*/?\s*(script|iframe|object|embed|style|link|meta)\b|javascript\s*:|"
                        r"data\s*:\s*text/html|on\w+\s*=\s*[\"'])", re.IGNORECASE)
URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)
REPEATED_CHAR = re.compile(r"(.)\1{14,}")
MAX_LINKS = 3


def clean_text(value: str) -> str:
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    return CONTROL_CHARS.sub("", value).strip()


def validate_news_text(title: str, description: str, cfg) -> tuple[str, str, str | None]:
    title, description = clean_text(title), clean_text(description)
    title = re.sub(r"\s+", " ", title)
    if not (cfg["TITLE_MIN"] <= len(title) <= cfg["TITLE_MAX"]):
        return title, description, (f"Title must be {cfg['TITLE_MIN']}-{cfg['TITLE_MAX']} characters.")
    if not description:
        return title, description, "Description is required."
    if len(description) > cfg["DESCRIPTION_MAX"]:
        return title, description, f"Description can be at most {cfg['DESCRIPTION_MAX']} characters."
    for text in (title, description):
        if SUSPICIOUS.search(text):
            return title, description, "Your text contains content that is not allowed (scripts or HTML)."
        if REPEATED_CHAR.search(text):
            return title, description, "Your text looks like spam (repeated characters)."
    if len(URL_RE.findall(title + " " + description)) > MAX_LINKS:
        return title, description, f"Please include at most {MAX_LINKS} links."
    return title, description, None
