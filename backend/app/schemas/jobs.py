from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.providers import ProviderConfigRead

JobStatus = Literal["queued", "processing", "completed", "failed", "cancelled", "partial_success"]


class JobCreated(BaseModel):
    job_id: str


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_name: str
    status: JobStatus
    progress_percent: int
    output_format: str
    created_at: datetime


class JobDetail(JobListItem):
    current_step: str
    source_file: dict[str, Any] | None = None
    output_file: dict[str, Any] | None = None
    total_chunks: int | None = None
    translated_chunks: int
    failed_chunks: int
    error_message: str | None = None
    completed_at: datetime | None = None
    provider: ProviderConfigRead | None = None


class JobStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_name: str
    status: str
    progress_percent: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_message: str | None = None


class JobStepsResponse(BaseModel):
    steps: list[JobStepRead]


class JobLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    step_name: str | None = None
    level: str
    message: str
    progress_percent: int | None = None
    created_at: datetime


class JobLogsResponse(BaseModel):
    logs: list[JobLogRead]


class DownloadInfo(BaseModel):
    filename: str
    download_url: str
    content_type: str
