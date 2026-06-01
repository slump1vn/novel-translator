from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.translation_prompt import DEFAULT_TRANSLATION_SYSTEM_PROMPT
from app.models.setting import AppSetting, utcnow

TRANSLATION_SYSTEM_PROMPT_KEY = "translation_system_prompt"


async def get_translation_system_prompt(db: AsyncSession) -> str:
    result = await db.execute(select(AppSetting.value).where(AppSetting.key == TRANSLATION_SYSTEM_PROMPT_KEY))
    value = result.scalar_one_or_none()
    return value.strip() if value and value.strip() else DEFAULT_TRANSLATION_SYSTEM_PROMPT


async def set_translation_system_prompt(db: AsyncSession, system_prompt: str) -> str:
    value = system_prompt.strip()
    result = await db.execute(select(AppSetting).where(AppSetting.key == TRANSLATION_SYSTEM_PROMPT_KEY))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        setting.updated_at = utcnow()
    else:
        db.add(AppSetting(key=TRANSLATION_SYSTEM_PROMPT_KEY, value=value, updated_at=utcnow()))
    await db.commit()
    return value
