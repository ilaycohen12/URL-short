"""Base62 short codes: a short code is the Postgres row id written in base 62."""

import pytest

from app.shortcode import ALPHABET, decode, encode

POSTGRES_INT_MAX = 2_147_483_647  # largest id the url_mappings.id column can hold


@pytest.mark.parametrize(
    ("number", "code"),
    [(0, "0"), (9, "9"), (10, "a"), (35, "z"), (36, "A"), (61, "Z"), (62, "10"), (3843, "ZZ")],
)
def test_known_values(number, code):
    assert encode(number) == code
    assert decode(code) == number


def test_round_trip():
    for number in [*range(1000), 123_456_789, POSTGRES_INT_MAX]:
        assert decode(encode(number)) == number, number


def test_codes_use_only_the_alphabet():
    for number in (1, 62, 999_999, POSTGRES_INT_MAX):
        assert set(encode(number)) <= set(ALPHABET)


def test_largest_id_fits_in_six_characters():
    assert len(encode(POSTGRES_INT_MAX)) == 6


@pytest.mark.parametrize("bad_code", ["favicon.ico", "ab-c", "hello!", "a b"])
def test_invalid_characters_are_rejected(bad_code):
    # The redirect endpoint turns this ValueError into a 404.
    with pytest.raises(ValueError, match="invalid short code"):
        decode(bad_code)
