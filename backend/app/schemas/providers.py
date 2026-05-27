from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["openai", "deepseek", "ollama"]


class ProviderConfigBase(BaseModel):
    config_name: str = Field(min_length=1, max_length=255)
    provider: ProviderName
    base_url: str | None = None
    model_name: str = Field(min_length=1, max_length=255)
    is_default: bool = False
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1, le=200000)
    parallelism: int = Field(default=2, ge=1, le=20)
    retry_limit: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    system_prompt: str | None = None


class ProviderConfigCreate(ProviderConfigBase):
    api_key: str | None = None


class ProviderConfigRead(ProviderConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class ProviderConnectionTest(BaseModel):
    config_id: str | None = None
    provider: ProviderName | None = None
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None


class ProviderConnectionResult(BaseModel):
    ok: bool
    latency_ms: int | None = None
    message: str | None = None
