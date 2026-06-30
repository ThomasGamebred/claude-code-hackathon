"""Shared helpers: paths, DuckDB connection, lineage, and value normalizers.

The normalizers here are deliberately deterministic and unit-testable. The fuzzy,
probabilistic work (entity matching) lives in resolve.py. The rule from the ADRs:
deterministic guardrails in code, probabilistic judgement clearly separated.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path

import duckdb

# --------------------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "warehouse.duckdb"
SOURCES = ROOT  # source dirs (pos/, crm/, ...) live at repo root


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE), read_only=read_only)


# --------------------------------------------------------------------------- lineage
def row_lineage_id(source_system: str, source_record_id: str, payload: str) -> str:
    """Stable per-row lineage id. Same source + key + bytes -> same id, so re-running
    ingestion is idempotent and a value in a report can be walked back to its origin."""
    h = hashlib.sha1(f"{source_system}|{source_record_id}|{payload}".encode("utf-8")).hexdigest()
    return f"{source_system}:{h[:16]}"


# --------------------------------------------------------------------------- encoding
def repair_mojibake(s: str | None) -> str | None:
    """Repair the classic UTF-8-decoded-as-Latin-1 corruption (Ã¼ -> ü, Ã¶ -> ö).

    Reversible mojibake is repaired. Lossy corruption (the U+FFFD replacement char,
    e.g. Bj�rn) cannot be recovered and is left as-is for a DQ flag to catch."""
    if s is None:
        return None
    if "�" in s:  # already lossy — nothing to recover
        return s
    if not re.search(r"Ã|Â|â€|Ã\x9f", s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def has_lossy_encoding(s: str | None) -> bool:
    return bool(s) and "�" in s


# --------------------------------------------------------------------------- names
_NAME_NOISE = re.compile(r"[.,'’\-]")   # punctuation that splits/joins names inconsistently
_WS = re.compile(r"\s+")
# tokens that are not name content
_NAME_DROP = {"jr", "sr", "ii", "iii", "iv", "mr", "mrs", "ms", "dr"}


def normalize_name(name: str | None) -> str:
    """Lowercase, de-accent, strip punctuation/suffixes, sort tokens.

    'Hernandez, Maria Jose' and 'Maria Hernandez' both -> 'hernandez maria'-ish.
    Token-sorted so 'last, first' and 'first last' collapse together."""
    if not name:
        return ""
    s = strip_accents(name.lower())
    s = _NAME_NOISE.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    toks = [t for t in s.split(" ") if t and t not in _NAME_DROP and len(t) > 1]
    return " ".join(sorted(toks))


_ACCENTS = str.maketrans(
    "áàâäãåçéèêëíìîïñóòôöõúùûüýÿ", "aaaaaaceeeeiiiinooooouuuuyy"
)


def strip_accents(s: str) -> str:
    # handle ß explicitly (no single-char mapping)
    return s.translate(_ACCENTS).replace("ß", "ss")


# --------------------------------------------------------------------------- email
def normalize_email(email: str | None) -> str:
    if not email:
        return ""
    e = email.strip().lower()
    if "@" not in e or e in {"null", "n/a", "test@test"}:
        return ""
    local, _, domain = e.partition("@")
    if "." not in domain:  # e.g. test@test — not a real address
        return ""
    # gmail ignores dots in the local part; normalize so j.smith == jsmith
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+")[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


# --------------------------------------------------------------------------- phone
def normalize_phone(phone: str | None) -> str:
    """Return the national significant number (last 10 digits for US, or the
    digits after a country code). Good enough to use as a blocking/match key."""
    if not phone:
        return ""
    # cut extensions ('x4', 'ext. 12') before stripping, or the ext digits corrupt
    # the number (e.g. '(312) 555-0188 x4' -> 31255501884).
    phone = re.split(r"\s*(?:x|ext\.?|#)\s*\d+", phone, flags=re.IGNORECASE)[0]
    digits = re.sub(r"\D", "", phone)
    # strip obvious extensions handled by the 'x' split upstream isn't done here;
    # drop a leading US country code
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    # German +49 ... keep last 10 as the comparable tail
    if len(digits) > 10:
        digits = digits[-10:]
    if digits in {"", "0000000000", "0" * len(digits)}:
        return ""
    return digits


# --------------------------------------------------------------------------- dates
def parse_date(value, *, dayfirst: bool = False) -> dt.date | None:
    """Parse the zoo of date formats across the seven sources:
    ISO, US M/D/Y, German D.M.Y, YYYYMMDD, and Excel serial numbers."""
    if value is None:
        return None
    s = str(value).strip()
    if s in {"", "0", "00000000", "NULL", "N/A", "null"}:
        return None
    # Excel serial date (e.g. Sunset's 44197). Origin 1899-12-30 (Excel's leap bug).
    if re.fullmatch(r"\d{4,5}", s) and not re.fullmatch(r"\d{8}", s):
        try:
            n = int(s)
            if 10000 <= n <= 60000:  # ~1927..2064, a sane window
                return dt.date(1899, 12, 30) + dt.timedelta(days=n)
        except ValueError:
            pass
    fmts = ["%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"]
    if dayfirst:
        fmts = ["%d.%m.%Y", "%d/%m/%Y"] + fmts
    for f in fmts:
        try:
            d = dt.datetime.strptime(s[:len(f) + 4], f).date()
            if dt.date(1900, 1, 2) <= d <= dt.date.today():
                return d
        except ValueError:
            continue
    return None


def parse_timestamp_utc(value, *, assume_tz: str | None = None) -> dt.datetime | None:
    """Parse a timestamp to UTC. `assume_tz` documents the source's wall-clock zone
    for naive timestamps — this is where the loyalty timezone bug gets fixed."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {"NULL", "null"}:
        return None
    try:
        if s.endswith("Z"):
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        # Naive wall-clock. Document the assumed source zone; we shift to UTC.
        offset = {"America/Chicago": -6, "America/New_York": -5, "Europe/Berlin": 1}.get(assume_tz, 0)
        d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=offset)))
    return d.astimezone(dt.timezone.utc)


# --------------------------------------------------------------------------- numbers
def parse_money(value) -> float | None:
    """Parse money across US (1,234.56) and German (1.234,56) conventions."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.upper() in {"NULL", "N/A"}:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # German: . thousands, , decimal
            s = s.replace(".", "").replace(",", ".")
        else:  # US: , thousands, . decimal
            s = s.replace(",", "")
    elif "," in s:  # lone comma -> decimal (German) unless it looks like thousands
        s = s.replace(".", "").replace(",", ".") if re.search(r",\d{2}$", s) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_zip(z: str | None) -> str:
    """US 5-digit zip, left-padded (POS drops the leading 0: 7102 -> 07102)."""
    if not z:
        return ""
    digits = re.sub(r"\D", "", str(z))
    if not digits:
        return ""
    if len(digits) <= 5:
        return digits.zfill(5)
    return digits[:5]  # drop +4
