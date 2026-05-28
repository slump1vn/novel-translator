import asyncio
import html
import posixpath
import signal
import threading
import time
import re
import uuid
import zipfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import chardet
from ebooklib import epub
from openai import AsyncOpenAI
from pypdf import PdfReader
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import decrypt_secret
from app.core.storage import download_file, upload_file
from app.models.job import Job, JobLog, JobStep, utcnow
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


class ExtractionTimeoutError(TimeoutError):
    pass


@contextmanager
def _timeout_guard(seconds: int, label: str):
    if seconds <= 0 or not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def raise_timeout(signum, frame):
        raise ExtractionTimeoutError(f"{label} exceeded {seconds} seconds")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _strip_html(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def _xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_html_document(path: str, media_type: str | None = None) -> bool:
    lowered = path.lower()
    return (
        media_type in {"application/xhtml+xml", "text/html"}
        or lowered.endswith(".xhtml")
        or lowered.endswith(".html")
        or lowered.endswith(".htm")
    )


def _unique_paths(paths: list[str], available: set[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        normalized = posixpath.normpath(path).lstrip("/")
        if normalized in available and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _find_epub_documents(archive: zipfile.ZipFile, names: set[str]) -> tuple[list[str], str | None]:
    html_candidates = sorted(path for path in names if _is_html_document(path))
    container_path = "META-INF/container.xml"
    if container_path not in names:
        return html_candidates, None

    container_root = ElementTree.fromstring(archive.read(container_path))
    opf_path: str | None = None
    for element in container_root.iter():
        if _xml_name(element.tag) == "rootfile":
            full_path = element.attrib.get("full-path")
            if full_path:
                opf_path = posixpath.normpath(full_path).lstrip("/")
                break
    if not opf_path or opf_path not in names:
        return html_candidates, opf_path

    opf_root = ElementTree.fromstring(archive.read(opf_path))
    opf_dir = posixpath.dirname(opf_path)
    manifest: dict[str, tuple[str, str | None]] = {}
    spine_ids: list[str] = []
    for element in opf_root.iter():
        local_name = _xml_name(element.tag)
        if local_name == "item":
            item_id = element.attrib.get("id")
            href = element.attrib.get("href")
            if item_id and href:
                full_path = posixpath.normpath(posixpath.join(opf_dir, href)).lstrip("/")
                manifest[item_id] = (full_path, element.attrib.get("media-type"))
        elif local_name == "itemref":
            idref = element.attrib.get("idref")
            if idref:
                spine_ids.append(idref)

    ordered = [manifest[idref][0] for idref in spine_ids if idref in manifest and _is_html_document(*manifest[idref])]
    if not ordered:
        ordered = [path for path, media_type in manifest.values() if _is_html_document(path, media_type)]
    return _unique_paths(ordered or html_candidates, names), opf_path


async def _add_log(
    db,
    job: Job,
    step_name: str | None,
    message: str,
    level: str = "info",
    progress: int | None = None,
):
    db.add(
        JobLog(
            id=str(uuid.uuid4()),
            job_id=job.id,
            step_name=step_name,
            level=level,
            message=message,
            progress_percent=progress,
            created_at=utcnow(),
        )
    )
    if progress is not None:
        job.progress_percent = progress
    job.updated_at = utcnow()
    await db.commit()


async def _extract_text(db, job: Job, filename: str, data: bytes) -> str:
    extension = Path(filename).suffix.lower()
    started = time.monotonic()
    deadline = started + settings.EXTRACTION_TIMEOUT_SECONDS

    def remaining_timeout(label: str) -> int:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            raise ExtractionTimeoutError(f"{label} exceeded {settings.EXTRACTION_TIMEOUT_SECONDS} seconds")
        return max(1, remaining)

    await _add_log(
        db,
        job,
        "text_extracted",
        f"Starting text extraction for {extension or 'unknown'} file ({len(data) / 1024 / 1024:.2f} MB)",
        progress=21,
    )

    if extension == ".txt":
        with _timeout_guard(remaining_timeout("TXT encoding detection"), "TXT encoding detection"):
            detected = chardet.detect(data)
        encoding = detected.get("encoding") or "utf-8"
        await _add_log(db, job, "text_extracted", f"Detected text encoding: {encoding}", progress=25)
        with _timeout_guard(remaining_timeout("TXT decode"), "TXT decode"):
            text = data.decode(encoding, errors="replace")
        await _add_log(db, job, "text_extracted", f"Decoded TXT file in {time.monotonic() - started:.1f}s", progress=34)
        return text

    if extension == ".pdf":
        with _timeout_guard(remaining_timeout("PDF parser initialization"), "PDF parser initialization"):
            reader = PdfReader(BytesIO(data))
        with _timeout_guard(remaining_timeout("PDF page count"), "PDF page count"):
            page_count = len(reader.pages)
        await _add_log(db, job, "text_extracted", f"PDF has {page_count} pages", progress=23)
        parts: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            with _timeout_guard(remaining_timeout(f"PDF page {index}/{page_count} extraction"), f"PDF page {index}/{page_count} extraction"):
                parts.append(page.extract_text() or "")
            if index == 1 or index == page_count or index % 5 == 0:
                step_progress = int(index / max(page_count, 1) * 100)
                await _set_step(db, job, "text_extracted", "processing", 20 + min(14, int(step_progress * 0.14)), step_progress)
                await _add_log(
                    db,
                    job,
                    "text_extracted",
                    f"Extracted PDF page {index}/{page_count}",
                    progress=20 + min(14, int(step_progress * 0.14)),
                )
        await _add_log(db, job, "text_extracted", f"Extracted PDF text in {time.monotonic() - started:.1f}s", progress=34)
        return "\n\n".join(parts)

    if extension == ".epub":
        await _add_log(db, job, "text_extracted", "Opening EPUB ZIP archive", progress=22)
        with _timeout_guard(remaining_timeout("EPUB ZIP open"), "EPUB ZIP open"):
            archive = zipfile.ZipFile(BytesIO(data))
        with archive:
            with _timeout_guard(remaining_timeout("EPUB ZIP entry listing"), "EPUB ZIP entry listing"):
                entries = archive.infolist()
            names = {entry.filename for entry in entries}
            html_candidates = [name for name in names if _is_html_document(name)]
            uncompressed_mb = sum(entry.file_size for entry in entries) / 1024 / 1024
            await _add_log(
                db,
                job,
                "text_extracted",
                f"EPUB archive has {len(entries)} entries, {uncompressed_mb:.2f} MB uncompressed, {len(html_candidates)} HTML candidates",
                progress=23,
            )

            with _timeout_guard(remaining_timeout("EPUB OPF manifest parsing"), "EPUB OPF manifest parsing"):
                documents, opf_path = _find_epub_documents(archive, names)
            if opf_path:
                await _add_log(db, job, "text_extracted", f"EPUB package file: {opf_path}", progress=24)
            else:
                await _add_log(db, job, "text_extracted", "EPUB package file not found; using HTML file fallback", level="warning", progress=24)
            await _add_log(db, job, "text_extracted", f"EPUB reading order contains {len(documents)} document files", progress=25)
            if not documents:
                raise ValueError("EPUB does not contain readable HTML/XHTML documents")

            parts: list[str] = []
            for index, document_path in enumerate(documents, start=1):
                with _timeout_guard(
                    remaining_timeout(f"EPUB document {index}/{len(documents)} read"),
                    f"EPUB document {index}/{len(documents)} read",
                ):
                    raw = archive.read(document_path)
                with _timeout_guard(
                    remaining_timeout(f"EPUB document {index}/{len(documents)} HTML cleanup"),
                    f"EPUB document {index}/{len(documents)} HTML cleanup",
                ):
                    extracted = _strip_html(raw.decode("utf-8", errors="replace"))
                if extracted:
                    parts.append(extracted)

                step_progress = int(index / max(len(documents), 1) * 100)
                progress = 25 + min(9, int(step_progress * 0.09))
                await _set_step(db, job, "text_extracted", "processing", progress, step_progress)
                if index <= 20 or index == len(documents) or index % 10 == 0:
                    await _add_log(
                        db,
                        job,
                        "text_extracted",
                        f"Extracted EPUB document {index}/{len(documents)}: {document_path} ({len(extracted):,} chars)",
                        progress=progress,
                    )
        await _add_log(db, job, "text_extracted", f"Extracted EPUB text in {time.monotonic() - started:.1f}s", progress=34)
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


async def _translate_chunks(db, job: Job, config: ProviderConfig, chunks: list[str]) -> list[str]:
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
    await _add_log(
        db,
        job,
        "translating",
        f"Using {config.provider}/{config.model_name} with parallelism {config.parallelism}",
        progress=55,
    )

    async def translate_one(index: int, chunk: str) -> tuple[int, str]:
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
                        return index, content.strip()
                    raise ValueError("Provider returned an empty translation")
                except Exception as exc:
                    last_error = exc
                    if attempt < config.retry_limit:
                        await asyncio.sleep(min(2**attempt, 10))
            raise RuntimeError(str(last_error) if last_error else "Translation failed")

    translated: list[str] = [""] * len(chunks)
    completed = 0
    tasks = [asyncio.create_task(translate_one(index, chunk)) for index, chunk in enumerate(chunks)]
    log_every = max(1, len(chunks) // 20)

    try:
        for task in asyncio.as_completed(tasks):
            index, text = await task
            translated[index] = text
            completed += 1
            step_progress = int(completed / max(len(chunks), 1) * 100)
            progress = 55 + min(25, int(step_progress * 0.25))
            job.translated_chunks = completed
            await _set_step(db, job, "translating", "processing", progress, step_progress)
            if completed == 1 or completed == len(chunks) or completed % log_every == 0:
                await _add_log(
                    db,
                    job,
                    "translating",
                    f"Translated chunk {completed}/{len(chunks)}",
                    progress=progress,
                )
    except Exception:
        for task in tasks:
            task.cancel()
        raise

    return translated


async def _set_step(
    db,
    job: Job,
    step_name: str,
    status: str,
    progress: int | None = None,
    step_progress: int | None = None,
    error: str | None = None,
):
    result = await db.execute(select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == step_name))
    step = result.scalar_one_or_none()
    now = utcnow()
    if step:
        step.status = status
        if step_progress is not None:
            step.progress_percent = max(0, min(100, step_progress))
        elif status == "completed":
            step.progress_percent = 100
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
        await _add_log(db, job, job.current_step, message, level="error", progress=job.progress_percent)
        if job.current_step:
            await _set_step(db, job, job.current_step, "failed", job.progress_percent, error=message)
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
        await _add_log(db, job, "text_extracted", "Job picked up by worker", progress=20)
        await _set_step(db, job, "text_extracted", "processing", 20, 0)

        await _add_log(db, job, "text_extracted", "Downloading source file from object storage", progress=20)
        source = download_file(job.source_file["bucket"], job.source_file["key"])
        await _add_log(db, job, "text_extracted", "Source file downloaded", progress=21)
        text = await _extract_text(db, job, job.source_file["filename"], source)
        if not text.strip():
            raise ValueError("Could not extract text from source file")
        await _set_step(db, job, "text_extracted", "completed", 35, 100)

        await _add_log(db, job, "chunked", f"Extracted {len(text):,} characters", progress=36)
        await _set_step(db, job, "chunked", "processing", 40, 0)
        chunks = _chunk_text(text, settings.CHUNK_SIZE_CHARS)
        if not chunks:
            raise ValueError("Source text is empty after chunking")
        job.total_chunks = len(chunks)
        await _add_log(db, job, "chunked", f"Created {len(chunks)} chunks with target size {settings.CHUNK_SIZE_CHARS}", progress=49)
        await _set_step(db, job, "chunked", "completed", 50, 100)

        await _set_step(db, job, "translating", "processing", 55, 0)
        provider = await _load_provider(db, job)
        job.provider_config_id = provider.id
        await db.commit()
        translated_chunks = await _translate_chunks(db, job, provider, chunks)
        job.translated_chunks = len(translated_chunks)
        job.failed_chunks = 0
        await _set_step(db, job, "translating", "completed", 80, 100)

        await _set_step(db, job, "merged", "processing", 85, 0)
        await _add_log(db, job, "merged", "Merging translated chunks", progress=85)
        translated_text = "\n\n".join(translated_chunks)
        await _set_step(db, job, "merged", "completed", 88, 100)

        await _set_step(db, job, "output_built", "processing", 92, 0)
        await _add_log(db, job, "output_built", f"Building {job.output_format.upper()} output", progress=92)
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
        await _add_log(db, job, "output_built", f"Uploaded output file {output_filename}", progress=96)
        await _set_step(db, job, "output_built", "completed", 96, 100)

        await _set_step(db, job, "download_ready", "processing", 98, 0)
        job.status = "completed"
        job.progress_percent = 100
        job.completed_at = utcnow()
        await _add_log(db, job, "download_ready", "Conversion completed", progress=100)
        await _set_step(db, job, "download_ready", "completed", 100, 100)


@celery_app.task(name="app.workers.tasks.process_translation_job")
def process_translation_job(job_id: str):
    try:
        asyncio.run(_process_translation_job(job_id))
    except Exception as exc:
        asyncio.run(_fail_job(job_id, str(exc)))
        raise
