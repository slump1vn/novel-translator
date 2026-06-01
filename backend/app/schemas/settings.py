from pydantic import BaseModel, Field


class TranslationSettingsRead(BaseModel):
    system_prompt: str
    default_system_prompt: str


class TranslationSettingsUpdate(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=20000)
