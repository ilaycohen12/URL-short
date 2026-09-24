from pydantic import BaseModel, Field, HttpUrl, field_validator

MAX_URL_LENGTH = 2048


class ShortenRequest(BaseModel):
    url: HttpUrl = Field(
        description=f"The full URL to shorten, including http:// or https:// (max {MAX_URL_LENGTH} chars).",
        examples=["https://docs.google.com/spreadsheets/u/0/"],
    )

    @field_validator("url")
    @classmethod
    def validate_url_length(cls, value: HttpUrl) -> HttpUrl:
        if len(str(value)) > MAX_URL_LENGTH:
            raise ValueError(f"URL must be at most {MAX_URL_LENGTH} characters")
        return value


class ShortenResponse(BaseModel):
    short_code: str = Field(description="The generated code.", examples=["5"])
    short_url: str = Field(
        description="Open this to be redirected to the original URL.",
        examples=["http://localhost:8000/5"],
    )


class Metrics(BaseModel):
    shorten_requests: int
    redirects: int
    cache_hits: int
    cache_misses: int
    not_found: int
    validation_errors: int
    errors: int
    db_unavailable: int


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    redis: bool
    version: str
    uptime_seconds: float
    # From Postgres - survives restarts. None when Postgres is unreachable.
    links_stored: int | None
    # In-memory, since this API process started - reset to 0 on every restart.
    metrics: Metrics
