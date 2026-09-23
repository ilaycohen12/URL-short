from pydantic import BaseModel, HttpUrl, field_validator

MAX_URL_LENGTH = 2048


class ShortenRequest(BaseModel):
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def validate_url_length(cls, value: HttpUrl) -> HttpUrl:
        if len(str(value)) > MAX_URL_LENGTH:
            raise ValueError(f"URL must be at most {MAX_URL_LENGTH} characters")
        return value


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str


class Metrics(BaseModel):
    shorten_requests: int
    redirects: int
    cache_hits: int
    cache_misses: int
    not_found: int
    validation_errors: int
    errors: int


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    redis: bool
    version: str
    uptime_seconds: float
    metrics: Metrics
