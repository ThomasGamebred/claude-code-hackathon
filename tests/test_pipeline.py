"""Unit tests for the deterministic guts: normalizers + matcher scoring.

These are the parts that MUST be exact (ADR-0005), so they get unit tests. The
probabilistic matcher's quality is measured separately by eval/score_matcher.py.

Run: .venv/bin/python -m pytest -q   (or: make test)
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import common, resolve


# --------------------------------------------------------------- normalizers
def test_phone_strips_extension_and_country_code():
    assert common.normalize_phone("(312) 555-0188 x4") == "3125550188"
    assert common.normalize_phone("+1-973-555-0142") == "9735550142"
    assert common.normalize_phone("000-000-0000") == ""          # sentinel -> absent


def test_email_gmail_dots_and_junk():
    assert common.normalize_email("J.Smith+promo@gmail.com") == "jsmith@gmail.com"
    assert common.normalize_email("test@test") == ""             # not a real address
    assert common.normalize_email("NULL") == ""


def test_name_normalization_collapses_order_and_punct():
    assert common.normalize_name("Hernandez, Maria Jose") == common.normalize_name("Maria Jose Hernandez")
    assert common.normalize_name("O'BRIEN, SEAN") == common.normalize_name("Sean O Brien")


def test_mojibake_repair_and_lossy_detection():
    assert common.repair_mojibake("JÃ¼rgen MÃ¼ller") == "Jürgen Müller"
    assert common.has_lossy_encoding("Bj�rn") is True       # U+FFFD unrecoverable


def test_date_zoo():
    assert common.parse_date("19851201") == dt.date(1985, 12, 1)        # YYYYMMDD
    assert common.parse_date("02.09.1975", dayfirst=True) == dt.date(1975, 9, 2)  # German
    assert common.parse_date("44197") == dt.date(2021, 1, 1)           # Excel serial
    assert common.parse_date("00000000") is None                       # null sentinel


def test_money_us_and_german():
    assert common.parse_money("1,234.56") == 1234.56
    assert common.parse_money("1.234,55") == 1234.55
    assert common.parse_money("NULL") is None


def test_zip_pads_leading_zero():
    assert common.normalize_zip("7102") == "07102"                     # POS drops the 0
    assert common.normalize_zip("02108-1234") == "02108"


def test_timezone_shift_to_utc():
    # naive Chicago store time -> UTC (the loyalty bug being fixed)
    utc = common.parse_timestamp_utc("2021-05-30 16:45:00", assume_tz="America/Chicago")
    assert utc.hour == 22 and utc.tzinfo is not None


# --------------------------------------------------------------- matcher rules
def _rec(**kw):
    base = dict(name_norm="", email_norm="", phone_norm="", dob=None,
                city=None, zip=None, state=None)
    base.update(kw)
    return base


def test_name_agreement_handles_reorder_and_extra_tokens():
    assert resolve.name_agreement("hernandez maria", "garcia hernandez j maria") >= 0.99


def test_dob_conflict_is_hard_negative():
    a = _rec(name_norm="jones michael", phone_norm="111", dob=dt.date(1952, 7, 16))
    b = _rec(name_norm="jones michael", phone_norm="111", dob=dt.date(1988, 11, 1))
    score, _ = resolve.score_pair(a, b)
    assert score < resolve.REVIEW


def test_shared_strong_id_merges():
    a = _rec(name_norm="maria hernandez", phone_norm="9735550142", dob=dt.date(1985, 7, 22))
    b = _rec(name_norm="garcia maria j", phone_norm="9735550142", dob=dt.date(1985, 7, 22))
    score, _ = resolve.score_pair(a, b)
    assert score >= resolve.AUTO_MERGE


def test_templated_email_with_conflicts_goes_to_review_not_merge():
    a = _rec(name_norm="hans weber", email_norm="hans.weber@sunsetcatalog.example",
             phone_norm="4425550003", city="Austin")
    b = _rec(name_norm="hans weber", email_norm="hans.weber@sunsetcatalog.example",
             phone_norm="6615550011", city="Seattle")
    score, _ = resolve.score_pair(a, b)
    assert resolve.REVIEW <= score < resolve.AUTO_MERGE          # unclear, not auto-merged


def test_co_location_is_not_identity():
    a = _rec(name_norm="greta wilson", zip="60601", city="Chicago", phone_norm="7105550000")
    b = _rec(name_norm="karen jones", zip="60601", city="Chicago", phone_norm="9625550000")
    score, _ = resolve.score_pair(a, b)
    assert score < resolve.REVIEW
