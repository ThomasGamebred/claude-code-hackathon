"""Pure normalization functions used by the conform layer.

Every function is side-effect-free, deterministic, and easy to unit-test.
The conform layer composes these into per-source pipelines; the matcher
uses the normalized outputs as features.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import phonenumbers
from dateutil import parser as du_parser


# Demo-only pepper baked into the repo. Real deployments would pull from KMS.
_PII_PEPPER = b"FABRIKAM_DEMO_PEPPER_DO_NOT_SHIP"


# Sentinels seen across the seven sources that should normalize to None.
_NULL_SENTINELS: frozenset[str] = frozenset({
    "", "null", "none", "n/a", "na", "-", "--",
    "00000000", "0000-00-00", "00.00.0000", "0/0/0", "1900-01-01",
})


# Surnames observed in ALL-CAPS sources where the first token is the surname.
_KNOWN_SURNAMES: frozenset[str] = frozenset({
    "OBRIEN", "O'BRIEN", "HERNANDEZ", "GARCIA", "HERNANDEZ-GARCIA",
    "MUELLER", "MULLER", "MÜLLER", "SCHMIDT", "SCHONFELD", "SCHÖNFELD",
    "NGUYEN", "LEE", "SMITH", "WILLIAMS", "RODRIGUEZ", "MARTINEZ",
    "JOHNSON", "BROWN", "DAVIS", "WILSON", "ANDERSON", "TAYLOR",
    "WAGNER", "GRESS", "GREß", "DANGELO", "D'ANGELO", "MUNOZ", "MUÑOZ",
    "WIERZBICKI-KOWALCZYK", "HALPERT", "CARTER",
})


# Excel epoch — Excel mistakenly treats 1900 as a leap year, so we use the
# "1899-12-30" base which lines up with what Excel emits for serial dates.
_EXCEL_EPOCH = datetime(1899, 12, 30)


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp, used everywhere we record ingestion time."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in _NULL_SENTINELS:
        return None
    return s or None


def nfkd_strip_accents(s: str) -> str:
    """Decompose, drop combining marks, recompose under NFKC."""
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return unicodedata.normalize("NFKC", stripped)


def normalize_name(s: str | None) -> str | None:
    if not s:
        return None
    cleaned = nfkd_strip_accents(s)
    cleaned = re.sub(r"[\.\,]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    return cleaned.lower()


def split_full_name(full: str | None) -> tuple[str | None, str | None]:
    """Return (first_name, last_name) titled-cased.

    Handles three shapes seen in the data:
    - "Last, First Middle"            (CRM, POS)
    - "First Last"                    (loyalty, sunset)
    - "FIRST LAST" all-caps           (northwind, POS) — uses surname dictionary
    """
    raw = _coerce_str(full)
    if not raw:
        return None, None

    if "," in raw:
        last, _, rest = raw.partition(",")
        first = rest.strip()
        return _titlecase(first) or None, _titlecase(last) or None

    tokens = [t for t in re.split(r"\s+", raw) if t]
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return None, _titlecase(tokens[0])

    is_all_caps = raw == raw.upper() and any(c.isalpha() for c in raw)
    if is_all_caps:
        # Compound surnames like HERNANDEZ-GARCIA can be the first token.
        first_token = tokens[0].upper()
        first_no_accent = nfkd_strip_accents(first_token).upper()
        if first_token in _KNOWN_SURNAMES or first_no_accent in _KNOWN_SURNAMES:
            last = tokens[0]
            first = " ".join(tokens[1:])
            return _titlecase(first) or None, _titlecase(last) or None

    # Default Western "First [Middle...] Last".
    first = " ".join(tokens[:-1])
    last = tokens[-1]
    return _titlecase(first) or None, _titlecase(last) or None


def _titlecase(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    out: list[str] = []
    for word in s.split():
        if "'" in word and len(word) > 1:
            # Preserve O'Brien-style apostrophes.
            head, _, tail = word.partition("'")
            out.append(head.capitalize() + "'" + tail.capitalize())
        elif "-" in word:
            out.append("-".join(p.capitalize() for p in word.split("-")))
        else:
            out.append(word.capitalize())
    return " ".join(out)


def normalize_email(value: str | None) -> str | None:
    raw = _coerce_str(value)
    if not raw:
        return None
    raw = raw.lower()
    if "@" not in raw:
        return None
    local, _, domain = raw.partition("@")
    domain = domain.strip()
    local = local.strip()
    if not local or not domain or "." not in domain:
        return None
    # Drop +tag for all providers.
    if "+" in local:
        local = local.split("+", 1)[0]
    # Gmail dot-aliases collapse.
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.replace(".", "")
        domain = "gmail.com"
    if not local:
        return None
    return f"{local}@{domain}"


_PHONE_EXT_RE = re.compile(
    r"\s*(?:x|ext|extension|#)\.?\s*(\d{1,6})\s*$",
    flags=re.IGNORECASE,
)


def normalize_phone(value: str | None, default_region: str = "US") -> tuple[str | None, str | None]:
    raw = _coerce_str(value)
    if not raw:
        return None, None

    ext: str | None = None
    m = _PHONE_EXT_RE.search(raw)
    if m:
        ext = m.group(1)
        raw = raw[: m.start()].strip()

    # Some sources (sunset) write a date into the phone column; reject if no digits.
    digits = sum(1 for c in raw if c.isdigit())
    if digits < 7:
        return None, ext

    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return None, ext
    if not phonenumbers.is_valid_number(parsed):
        return None, ext
    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    if parsed.extension and not ext:
        ext = parsed.extension
    return e164, ext


def parse_date(
    value: object,
    formats: Iterable[str] = (
        "%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d",
    ),
) -> date | None:
    """Validation-retry: strict formats first, then dateutil, else None.

    Handles Excel serial dates (5-digit ints), sentinels, and ISO timestamps.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in _NULL_SENTINELS:
        return None

    # Excel serial: a 4-6 digit pure integer in a plausible date range.
    if s.isdigit() and 5 <= len(s) <= 6:
        try:
            n = int(s)
            if 1 <= n <= 90000:
                dt = _EXCEL_EPOCH + timedelta(days=n)
                return dt.date()
        except (ValueError, OverflowError):
            pass

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    try:
        return du_parser.parse(s, dayfirst=False, yearfirst=False).date()
    except (ValueError, OverflowError, du_parser.ParserError):
        return None


def parse_birth_year_strict(value: object) -> int | None:
    d = parse_date(value)
    if d is None:
        return None
    today = date.today()
    if d.year < 1900 or d.year > today.year:
        return None
    return d.year


def pad_us_zip(value: str | None) -> tuple[str | None, bool]:
    """Return (zip, padded_flag). 4-digit US zips get a leading zero."""
    raw = _coerce_str(value)
    if not raw:
        return None, False
    # ZIP+4 form.
    base = raw.split("-")[0].strip()
    if base.isdigit() and len(base) == 4:
        return "0" + raw, True
    return raw, False


def parse_de_decimal(value: str | None) -> float | None:
    """German-format decimal: '12.840,55' -> 12840.55. Tolerates plain numbers."""
    raw = _coerce_str(value)
    if raw is None:
        return None
    cleaned = raw.replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def hash_pii(value: str | None) -> str | None:
    """SHA-256 with peppered salt; returns None for None."""
    if value is None:
        return None
    h = hashlib.sha256()
    h.update(_PII_PEPPER)
    h.update(value.encode("utf-8"))
    return h.hexdigest()
