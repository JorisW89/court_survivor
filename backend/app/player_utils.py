import re
import unicodedata

FIRST_NAME_ALIASES = {
    "samuel": "sam",
}


def normalize_player_name(name: str) -> str:
    name = re.sub(r"\s*[\(\[]\d+[\)\]]", "", name or "")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = re.sub(r"[-–—]", " ", name)
    normalized = " ".join(name.split()).strip().lower()
    parts = normalized.split(" ", 1)
    if parts and parts[0] in FIRST_NAME_ALIASES:
        parts[0] = FIRST_NAME_ALIASES[parts[0]]
        normalized = " ".join(parts)
    return normalized
