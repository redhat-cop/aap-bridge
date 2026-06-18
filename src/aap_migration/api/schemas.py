from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_connection_url(url: str) -> str:
    normalized = url.strip()
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    if not normalized.startswith("https://"):
        raise ValueError("URL should use HTTPS for security")
    return normalized


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["awx", "aap"]
    role: Literal["source", "destination"]
    url: str = Field(..., min_length=1, max_length=512)
    token: str | None = None
    verify_ssl: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_connection_url(value)

    @model_validator(mode="after")
    def validate_type_role(self) -> "ConnectionCreate":
        if self.type == "awx" and self.role != "source":
            raise ValueError("AWX connections can only use the source role")
        return self


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: Literal["awx", "aap"] | None = None
    role: Literal["source", "destination"] | None = None
    url: str | None = Field(default=None, min_length=1, max_length=512)
    token: str | None = None
    verify_ssl: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_connection_url(value)

    @model_validator(mode="after")
    def validate_type_role(self) -> "ConnectionUpdate":
        if self.type == "awx" and self.role == "destination":
            raise ValueError("AWX connections can only use the source role")
        return self


class ConnectionResponse(BaseModel):
    id: str
    name: str
    type: str
    role: str
    url: str
    token: str | None = None
    verify_ssl: bool
    version: str | None = None
    api_prefix: str | None = None
    ping_status: str = "unknown"
    ping_error: str | None = None
    auth_status: str = "unknown"
    auth_error: str | None = None
    last_checked: datetime | None = None

    model_config = {"from_attributes": True}


class TestResult(BaseModel):
    ok: bool
    ping_status: str
    auth_status: str
    version: str | None = None
    api_prefix: str | None = None
    error: str | None = None


class JobResponse(BaseModel):
    id: str
    type: str
    connection_id: str | None = None
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


class JobDetailResponse(JobResponse):
    output: list[str] = []
    job_metadata: dict | None = None


class MigratePreviewRequest(BaseModel):
    source_id: str
    destination_id: str


class MigrateRunRequest(BaseModel):
    source_id: str
    destination_id: str
    job_id: str


class MigrationResource(BaseModel):
    source_id: int
    name: str
    type: str
    action: str
    dest_id: int | None = None


class MigrationPreviewSummary(BaseModel):
    total: int
    create: int
    skip_exists: int
    displayed: int
    truncated: bool = False


class MigrationPreviewResponse(BaseModel):
    source_id: str
    destination_id: str
    resources: dict[str, list[MigrationResource]] = {}
    resource_summaries: dict[str, MigrationPreviewSummary] = {}
    warnings: list[str] = []
    host_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}


class JobCreatedResponse(BaseModel):
    job_id: str
