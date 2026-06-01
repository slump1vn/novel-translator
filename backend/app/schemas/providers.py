from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["openai", "deepseek", "ollama"]


class ModelOptions(BaseModel):
    temperature: float = Field(default=0.2, ge=0, le=2)
    num_predict: int = Field(default=2048, ge=1, le=200000)
    repeat_penalty: float = Field(default=1.2, ge=0.1, le=10)
    timeout: int = Field(default=28800000, ge=1000)


class ProviderConfigBase(BaseModel):
    config_name: str = Field(min_length=1, max_length=255)
    provider: ProviderName
    base_url: str | None = None
    model_name: str = Field(min_length=1, max_length=255)
    is_default: bool = False
    stream: bool = False
    options: ModelOptions = Field(default_factory=ModelOptions)
    parallelism: int = Field(default=2, ge=1, le=20)
    retry_limit: int = Field(default=3, ge=0, le=10)


class ProviderConfigCreate(ProviderConfigBase):
    api_key: str | None = None


class ProviderConfigUpdate(ProviderConfigBase):
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


class ProviderModelsResult(BaseModel):
    models: list[str]
