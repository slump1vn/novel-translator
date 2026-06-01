import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.translation_settings import get_translation_system_prompt
from app.models.provider import ProviderConfig
from app.schemas.translation import TranslationPreviewRequest, TranslationPreviewResponse
from app.workers.tasks import translate_preview_text

router = APIRouter()


async def _load_preview_provider(db: AsyncSession, provider_config_id: str | None) -> ProviderConfig:
    if provider_config_id:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_config_id))
    else:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.is_default.is_(True)).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Provider config not found")
    return config


@router.post("", response_model=TranslationPreviewResponse)
async def translate_preview(payload: TranslationPreviewRequest, db: AsyncSession = Depends(get_db)):
    source_text = payload.text.strip()
    if not source_text:
        raise HTTPException(status_code=400, detail="Text is required")
    if len(source_text) > settings.TRANSLATION_PREVIEW_MAX_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text is longer than {settings.TRANSLATION_PREVIEW_MAX_CHARS} characters",
        )

    config = await _load_preview_provider(db, payload.provider_config_id)
    system_prompt = await get_translation_system_prompt(db)
    started = time.perf_counter()
    try:
        translated_text, chunk_count, cleaned_characters, removed_noise_lines = await translate_preview_text(
            config,
            source_text,
            system_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return TranslationPreviewResponse(
        translated_text=translated_text,
        provider_config_id=config.id,
        provider=config.provider,
        model_name=config.model_name,
        source_characters=len(source_text),
        cleaned_characters=cleaned_characters,
        chunk_count=chunk_count,
        removed_noise_lines=removed_noise_lines,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
