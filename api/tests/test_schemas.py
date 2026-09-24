"""Input validation for POST /shorten (what gets a 422 before reaching the database)."""

import pytest
from pydantic import ValidationError

from app.schemas import MAX_URL_LENGTH, ShortenRequest


def url_of_length(length: int) -> str:
    prefix = "https://example.com/"
    return prefix + "a" * (length - len(prefix))


@pytest.mark.parametrize(
    "url",
    [
        "https://www.google.com",
        "http://example.com/path?q=1&x=2",
        "https://docs.google.com/spreadsheets/u/0/",
    ],
)
def test_valid_urls_are_accepted(url):
    assert ShortenRequest(url=url).url is not None


@pytest.mark.parametrize(
    "url",
    [
        "www.google.com",  # no scheme
        "not-a-url",
        "ftp://example.com/file",  # only http/https
        "",
    ],
)
def test_invalid_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        ShortenRequest(url=url)


def test_url_at_max_length_is_accepted():
    url = url_of_length(MAX_URL_LENGTH)
    assert len(str(ShortenRequest(url=url).url)) == MAX_URL_LENGTH


def test_url_over_max_length_is_rejected():
    # Regression: a 2049-2083 char URL used to pass validation and crash the DB insert with a 500
    # (column is VARCHAR(2048)). It must be rejected up front with a 422 instead.
    with pytest.raises(ValidationError, match=f"at most {MAX_URL_LENGTH} characters"):
        ShortenRequest(url=url_of_length(MAX_URL_LENGTH + 1))
