from datetime import datetime, timezone

from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_model_options() -> dict[str, Any]:
    return {
        "temperature": 0.2,
        "num_predict": 2048,
        "repeat_penalty": 1.2,
        "timeout": 28800000,
    }


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    temperature: Mapped[float] = mapped_column(Float, default=0.3)
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    model_options: Mapped[dict[str, Any]] = mapped_column("options", JSON, default=default_model_options)
    parallelism: Mapped[int] = mapped_column(Integer, default=2)
    retry_limit: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def options(self) -> dict[str, Any]:
        return {**default_model_options(), **(self.model_options or {})}

    @options.setter
    def options(self, value: dict[str, Any] | None) -> None:
        self.model_options = {**default_model_options(), **(value or {})}
