import asyncio
import re
import uuid
from io import BytesIO
from pathlib import Path

import chardet
from ebooklib import ITEM_DOCUMENT, epub
from openai import AsyncOpenAI
from pypdf import PdfReader
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import decrypt_secret
from app.core.storage import download_file, upload_file
from app.models.job import Job, JobStep, utcnow
from app.models.provider import ProviderConfig
from app.workers.celery_app import celery_app

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
}

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional Chinese-to-Vietnamese novel translator. "
    "Preserve paragraph structure, names, sect names, places, and cultivation terms. "
    "Return only the translated Vietnamese text."
)


def _strip_html(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _extract_text(filename: str, data: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension == ".txt":
        detected = chardet.detect(data)
        encoding = detected.get("encoding") or "utf-8"
        return data.decode(encoding, errors="replace")

    if extension == ".pdf":
        reader = PdfReader(BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

    if extension == ".epub":
        book = epub.read_epub(BytesIO(data))
        parts: list[str] = []
        for item in book.get_items():
            if item.get_type() == ITEM_DOCUMENT:
                parts.append(_strip_html(item.get_content().decode("utf-8", errors="replace")))
        return "\n\n".join(part for part in parts if part)

    raise ValueError("Unsupported source file type")


def _chunk_text(text: str, chunk_size: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    cursor = 0
    while cursor < len(normalized):
        end = min(cursor + chunk_size, len(normalized))
        newline = normalized.rfind("\n\n", cursor, end)
        if newline > cursor + chunk_size // 2:
            end = newline
        chunks.append(normalized[cursor:end].strip())
        cursor = end
    return [chunk for chunk in chunks if chunk]


def _build_txt(text: str) -> tuple[bytes, str]:
    return text.encode("utf-8"), "text/plain; charset=utf-8"


def _build_epub(title: str, text: str) -> tuple[bytes, str]:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("vi")

    chapter = epub.EpubHtml(title=title, file_name="content.xhtml", lang="vi")
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs) or "<p></p>"
    chapter.content = f"<h1>{title}</h1>{body}"

    book.add_item(chapter)
    book.toc = (epub.Link("content.xhtml", title, "content"),)
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    buffer = BytesIO()
    epub.write_epub(buffer, book)
    return buffer.getvalue(), "application/epub+zip"


async def _load_provider(db, job: Job) -> ProviderConfig:
    if job.provider_config_id:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == job.provider_config_id))
    else:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.is_default.is_(True)).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        raise ValueError("No default provider configured")
    return config


async def _translate_chunks(config: ProviderConfig, chunks: list[str]) -> list[str]:
    api_key = decrypt_secret(config.encrypted_api_key)
    if config.provider in {"openai", "deepseek"} and not api_key:
        raise ValueError(f"Missing API key for provider {config.provider}")

    client = AsyncOpenAI(
        api_key=api_key or "ollama",
        base_url=(config.base_url or DEFAULT_BASE_URLS[config.provider]).rstrip("/"),
        timeout=config.timeout_seconds,
        max_retries=0,
    )
    semaphore = asyncio.Semaphore(config.parallelism)
    system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT

    async def translate_one(chunk: str) -> str:
        async with semaphore:
            last_error: Exception | None = None
            for attempt in range(config.retry_limit + 1):
                try:
                    response = await client.chat.completions.create(
                        model=config.model_name,
                        temperature=config.temperature,
                        max_tokens=config.max_tokens,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": chunk},
                        ],
                    )
                    content = response.choices[0].message.content
                    if content:
                        return content.strip()
                    raise ValueError("Provider returned an empty translation")
                except Exception as exc:
                    last_error = exc
                    if attempt < config.retry_limit:
                        await asyncio.sleep(min(2**attempt, 10))
            raise RuntimeError(str(last_error) if last_error else "Translation failed")

    return await asyncio.gather(*(translate_one(chunk) for chunk in chunks))


async def _set_step(db, job: Job, step_name: str, status: str, progress: int | None = None, error: str | None = None):
    result = await db.execute(select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == step_name))
    step = result.scalar_one_or_none()
    now = utcnow()
    if step:
        step.status = status
        if status == "processing" and not step.started_at:
            step.started_at = now
        if status in {"completed", "failed"}:
            step.ended_at = now
        step.error_message = error

    job.current_step = step_name
    if progress is not None:
        job.progress_percent = progress
    job.updated_at = now
    await db.commit()


async def _fail_job(job_id: str, message: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        job.status = "failed"
        job.error_message = message
        job.updated_at = utcnow()
        if job.current_step:
            await _set_step(db, job, job.current_step, "failed", job.progress_percent, message)
        await db.commit()


async def _process_translation_job(job_id: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job or job.status == "cancelled":
            return
        if not job.source_file:
            raise ValueError("Job does not have a source file")

        job.status = "processing"
        await _set_step(db, job, "text_extracted", "processing", 20)

        source = download_file(job.source_file["bucket"], job.source_file["key"])
        text = _extract_text(job.source_file["filename"], source)
        if not text.strip():
            raise ValueError("Could not extract text from source file")
        await _set_step(db, job, "text_extracted", "completed", 35)

        await _set_step(db, job, "chunked", "processing", 40)
        chunks = _chunk_text(text, settings.CHUNK_SIZE_CHARS)
        if not chunks:
            raise ValueError("Source text is empty after chunking")
        job.total_chunks = len(chunks)
        await _set_step(db, job, "chunked", "completed", 50)

        await _set_step(db, job, "translating", "processing", 55)
        provider = await _load_provider(db, job)
        job.provider_config_id = provider.id
        await db.commit()
        translated_chunks = await _translate_chunks(provider, chunks)
        job.translated_chunks = len(translated_chunks)
        job.failed_chunks = 0
        await _set_step(db, job, "translating", "completed", 80)

        await _set_step(db, job, "merged", "processing", 85)
        translated_text = "\n\n".join(translated_chunks)
        await _set_step(db, job, "merged", "completed", 88)

        await _set_step(db, job, "output_built", "processing", 92)
        base_name = Path(job.source_file["filename"]).stem or job.job_name
        if job.output_format == "txt":
            output_bytes, content_type = _build_txt(translated_text)
            output_filename = f"{base_name}.translated.txt"
        else:
            output_bytes, content_type = _build_epub(base_name, translated_text)
            output_filename = f"{base_name}.translated.epub"

        output_key = f"jobs/{job.id}/output/{output_filename}"
        upload_file(settings.STORAGE_BUCKET_OUTPUT, output_key, output_bytes, content_type)
        job.output_file = {
            "filename": output_filename,
            "content_type": content_type,
            "size_bytes": len(output_bytes),
            "bucket": settings.STORAGE_BUCKET_OUTPUT,
            "key": output_key,
        }
        await _set_step(db, job, "output_built", "completed", 96)

        await _set_step(db, job, "download_ready", "processing", 98)
        job.status = "completed"
        job.progress_percent = 100
        job.completed_at = utcnow()
        await _set_step(db, job, "download_ready", "completed", 100)


@celery_app.task(name="app.workers.tasks.process_translation_job")
def process_translation_job(job_id: str):
    try:
        asyncio.run(_process_translation_job(job_id))
    except Exception as exc:
        asyncio.run(_fail_job(job_id, str(exc)))
        raise
