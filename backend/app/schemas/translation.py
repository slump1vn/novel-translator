from pydantic import BaseModel, Field


class TranslationPreviewRequest(BaseModel):
    text: str = Field(min_length=1)
    provider_config_id: str | None = None


class TranslationPreviewResponse(BaseModel):
    translated_text: str
    provider_config_id: str
    provider: str
    model_name: str
    source_characters: int
    cleaned_characters: int
    chunk_count: int
    removed_noise_lines: int
    elapsed_ms: int
