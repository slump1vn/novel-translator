from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.providers import ProviderConfigRead

JobStatus = Literal["queued", "processing", "awaiting_glossary_review", "completed", "failed", "cancelled", "partial_success"]


class JobCreated(BaseModel):
    job_id: str


class EpubChapterRead(BaseModel):
    index: int
    title: str
    path: str
    character_count: int


class EpubChaptersResponse(BaseModel):
    chapters: list[EpubChapterRead]


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


class GlossaryEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_term: str
    translated_term: str
    category: str
    note: str | None = None
    occurrence_count: int
    position: int


class GlossaryEntryInput(BaseModel):
    id: str | None = None
    source_term: str = Field(min_length=1, max_length=255)
    translated_term: str = Field(min_length=1, max_length=255)
    category: str = Field(default="other", max_length=64)
    note: str | None = None
    occurrence_count: int = 0
    position: int = 0


class GlossaryEntriesResponse(BaseModel):
    entries: list[GlossaryEntryRead]


class GlossaryEntriesUpdate(BaseModel):
    entries: list[GlossaryEntryInput]
