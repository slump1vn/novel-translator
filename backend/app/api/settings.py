from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.translation_prompt import DEFAULT_TRANSLATION_SYSTEM_PROMPT
from app.core.translation_settings import get_translation_system_prompt, set_translation_system_prompt
from app.schemas.settings import TranslationSettingsRead, TranslationSettingsUpdate

router = APIRouter()


@router.get("/translation", response_model=TranslationSettingsRead)
async def get_translation_settings(db: AsyncSession = Depends(get_db)):
    return TranslationSettingsRead(
        system_prompt=await get_translation_system_prompt(db),
        default_system_prompt=DEFAULT_TRANSLATION_SYSTEM_PROMPT,
    )


@router.put("/translation", response_model=TranslationSettingsRead)
async def update_translation_settings(payload: TranslationSettingsUpdate, db: AsyncSession = Depends(get_db)):
    system_prompt = await set_translation_system_prompt(db, payload.system_prompt)
    return TranslationSettingsRead(
        system_prompt=system_prompt,
        default_system_prompt=DEFAULT_TRANSLATION_SYSTEM_PROMPT,
    )
