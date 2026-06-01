import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.models.provider import ProviderConfig, utcnow
from app.schemas.providers import (
    ProviderConfigCreate,
    ProviderConfigRead,
    ProviderConfigUpdate,
    ProviderConnectionResult,
    ProviderConnectionTest,
)

router = APIRouter()

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
}


@router.get("", response_model=list[ProviderConfigRead])
async def list_provider_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).order_by(ProviderConfig.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ProviderConfigRead, status_code=status.HTTP_201_CREATED)
async def create_provider_config(payload: ProviderConfigCreate, db: AsyncSession = Depends(get_db)):
    if payload.provider in {"openai", "deepseek"} and not payload.api_key:
        raise HTTPException(status_code=400, detail="api_key is required for this provider")
    if payload.provider == "ollama" and not payload.base_url:
        payload.base_url = DEFAULT_BASE_URLS["ollama"]

    if payload.is_default:
        await db.execute(update(ProviderConfig).values(is_default=False))

    config = ProviderConfig(
        id=str(uuid.uuid4()),
        config_name=payload.config_name,
        provider=payload.provider,
        encrypted_api_key=encrypt_secret(payload.api_key),
        base_url=payload.base_url,
        model_name=payload.model_name,
        is_default=payload.is_default,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        parallelism=payload.parallelism,
        retry_limit=payload.retry_limit,
        timeout_seconds=payload.timeout_seconds,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.put("/{config_id}", response_model=ProviderConfigRead)
async def update_provider_config(config_id: str, payload: ProviderConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Provider config not found")

    if payload.provider == "ollama" and not payload.base_url:
        payload.base_url = DEFAULT_BASE_URLS["ollama"]
    if payload.provider in {"openai", "deepseek"} and not payload.api_key and not config.encrypted_api_key:
        raise HTTPException(status_code=400, detail="api_key is required for this provider")

    now = utcnow()
    if payload.is_default:
        await db.execute(update(ProviderConfig).where(ProviderConfig.id != config.id).values(is_default=False, updated_at=now))

    config.config_name = payload.config_name
    config.provider = payload.provider
    config.base_url = payload.base_url
    config.model_name = payload.model_name
    config.is_default = payload.is_default or config.is_default
    config.temperature = payload.temperature
    config.max_tokens = payload.max_tokens
    config.parallelism = payload.parallelism
    config.retry_limit = payload.retry_limit
    config.timeout_seconds = payload.timeout_seconds
    config.updated_at = now
    if payload.provider == "ollama":
        config.encrypted_api_key = None
    elif payload.api_key:
        config.encrypted_api_key = encrypt_secret(payload.api_key)

    await db.commit()
    await db.refresh(config)
    return config


@router.post("/{config_id}/default", response_model=ProviderConfigRead)
async def set_default_provider_config(config_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Provider config not found")

    now = utcnow()
    await db.execute(update(ProviderConfig).values(is_default=False, updated_at=now))
    config.is_default = True
    config.updated_at = now
    await db.commit()
    await db.refresh(config)
    return config


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_config(config_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Provider config not found")
    await db.delete(config)
    await db.commit()
    return None


@router.post("/test", response_model=ProviderConnectionResult)
async def test_provider_connection(payload: ProviderConnectionTest, db: AsyncSession = Depends(get_db)):
    provider = payload.provider
    base_url = payload.base_url
    api_key = payload.api_key
    model_name = payload.model_name

    if payload.config_id:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == payload.config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail="Provider config not found")
        provider = config.provider
        base_url = config.base_url
        api_key = decrypt_secret(config.encrypted_api_key)
        model_name = config.model_name

    if not provider:
        raise HTTPException(status_code=400, detail="provider or config_id is required")

    base = (base_url or DEFAULT_BASE_URLS[provider]).rstrip("/")
    headers: dict[str, str] = {}
    if provider in {"openai", "deepseek"}:
        if not api_key:
            return ProviderConnectionResult(ok=False, message="Missing API key")
        headers["Authorization"] = f"Bearer {api_key}"

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base}/models", headers=headers)
            response.raise_for_status()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ProviderConnectionResult(ok=True, latency_ms=latency_ms, message=model_name)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ProviderConnectionResult(ok=False, latency_ms=latency_ms, message=str(exc))
