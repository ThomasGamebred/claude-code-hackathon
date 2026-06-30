"""Unit tests for pure normalizers."""
from __future__ import annotations

from datetime import date

import pytest

from pipeline.normalize import (
    normalize_email,
    normalize_phone,
    pad_us_zip,
    parse_birth_year_strict,
    parse_date,
    parse_de_decimal,
    split_full_name,
)


class TestNormalizeEmail:
    def test_gmail_dot_alias_collapses(self) -> None:
        assert normalize_email("First.Last@gmail.com") == "firstlast@gmail.com"

    def test_gmail_plus_tag_stripped(self) -> None:
        assert normalize_email("david.lee+amazon@gmail.com") == "davidlee@gmail.com"

    def test_googlemail_normalized_to_gmail(self) -> None:
        assert normalize_email("a.b@googlemail.com") == "ab@gmail.com"

    def test_plus_tag_stripped_non_gmail(self) -> None:
        assert normalize_email("user+work@yahoo.com") == "user@yahoo.com"

    def test_null_sentinel_returns_none(self) -> None:
        assert normalize_email("NULL") is None
        assert normalize_email("") is None
        assert normalize_email(None) is None

    def test_no_at_sign_returns_none(self) -> None:
        assert normalize_email("not-an-email") is None

    def test_lowercase(self) -> None:
        assert normalize_email("FOO@BAR.COM") == "foo@bar.com"


class TestNormalizePhone:
    def test_us_formatted(self) -> None:
        e164, ext = normalize_phone("(973) 555-0142", default_region="US")
        assert e164 == "+19735550142"
        assert ext is None

    def test_us_plain_digits(self) -> None:
        e164, _ = normalize_phone("6175550211", default_region="US")
        assert e164 == "+16175550211"

    def test_de_format(self) -> None:
        e164, _ = normalize_phone("+49 30 1234567", default_region="DE")
        assert e164 is not None and e164.startswith("+49")

    def test_extension_extracted(self) -> None:
        e164, ext = normalize_phone("(312) 555-0188 x4", default_region="US")
        assert e164 == "+13125550188"
        assert ext == "4"

    def test_invalid_returns_none(self) -> None:
        assert normalize_phone("03/15/2021", default_region="US") == (None, None)

    def test_null_sentinel(self) -> None:
        assert normalize_phone("NULL") == (None, None)
        assert normalize_phone("") == (None, None)


class TestParseDate:
    def test_excel_serial(self) -> None:
        assert parse_date(44197) == date(2021, 1, 1)
        assert parse_date("44197") == date(2021, 1, 1)

    def test_german_format(self) -> None:
        assert parse_date("02.09.1975") == date(1975, 9, 2)

    def test_us_two_digit_year(self) -> None:
        # dateutil handles 7/22/85; we accept anywhere it lands as long as month/day match.
        d = parse_date("7/22/85")
        assert d is not None and d.month == 7 and d.day == 22

    def test_sentinel_zeros(self) -> None:
        assert parse_date("00000000") is None
        assert parse_date("0000-00-00") is None
        assert parse_date("") is None
        assert parse_date("N/A") is None
        assert parse_date("NULL") is None


class TestPadZip:
    def test_four_digit_padded(self) -> None:
        out, padded = pad_us_zip("7102")
        assert out == "07102"
        assert padded is True

    def test_five_digit_untouched(self) -> None:
        out, padded = pad_us_zip("60601")
        assert out == "60601"
        assert padded is False

    def test_zip_plus_four_padded(self) -> None:
        out, padded = pad_us_zip("7102-1234")
        assert out == "07102-1234"
        assert padded is True


class TestDeDecimal:
    def test_thousands_and_decimal(self) -> None:
        assert parse_de_decimal("12.840,55") == 12840.55

    def test_zero(self) -> None:
        assert parse_de_decimal("0,00") == 0.0

    def test_garbage_returns_none(self) -> None:
        assert parse_de_decimal("abc") is None
        assert parse_de_decimal("") is None


class TestSplitName:
    def test_comma_form(self) -> None:
        first, last = split_full_name("Hernandez-Garcia, Maria Jose")
        assert first == "Maria Jose"
        assert last == "Hernandez-Garcia"

    def test_first_last(self) -> None:
        first, last = split_full_name("Maria Hernandez")
        assert first == "Maria"
        assert last == "Hernandez"

    def test_all_caps_known_surname_first(self) -> None:
        first, last = split_full_name("OBRIEN SEAN PATRICK")
        assert last == "Obrien"
        assert first == "Sean Patrick"

    def test_all_caps_smith_robert_known_surname(self) -> None:
        first, last = split_full_name("SMITH ROBERT")
        assert last == "Smith"
        assert first == "Robert"

    def test_single_token(self) -> None:
        first, last = split_full_name("Madonna")
        assert first is None
        assert last == "Madonna"


class TestBirthYearStrict:
    def test_in_range(self) -> None:
        assert parse_birth_year_strict("1985-07-22") == 1985

    def test_too_old(self) -> None:
        assert parse_birth_year_strict("1899-12-31") is None

    def test_future(self) -> None:
        assert parse_birth_year_strict("2999-01-01") is None

    def test_none_input(self) -> None:
        assert parse_birth_year_strict(None) is None
        assert parse_birth_year_strict("NULL") is None
