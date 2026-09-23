from pydantic import BaseModel, HttpUrl


class ShortenRequest(BaseModel):
    url: HttpUrl


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    redis: bool
