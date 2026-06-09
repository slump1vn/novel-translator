import mimetypes
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import quote

import redis.asyncio as redis
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from openai import AsyncOpenAI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.epub_chapters import chapter_heading_candidates, epub_text, extract_epub_chapters, split_text_by_heading_candidates
from app.core.security import decrypt_secret
from app.core.storage import download_file, upload_file
from app.models.glossary import StoryGlossaryEntry
from app.models.job import Job, JobChunkResult, JobLog, JobStep, utcnow
from app.models.provider import ProviderConfig, default_model_options
from app.schemas.jobs import (
    DownloadInfo,
    EpubAiSplitProgressResponse,
    EpubAiSplitTaskCreated,
    EpubChaptersResponse,
    GlossaryEntriesResponse,
    GlossaryEntriesUpdate,
    JobGlossaryProviderUpdate,
    JobChunkResultsResponse,
    JobCreated,
    JobDetail,
    JobListItem,
    JobLogsResponse,
    JobProviderUpdate,
    JobStepsResponse,
)

router = APIRouter()

ALLOWED_EXTENSIONS = {".txt", ".epub", ".pdf"}
EPUB_CHAPTERIZED_THRESHOLD = 10
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
}
AI_CHAPTER_SPLIT_PROMPT = """Bạn đang nhận danh sách các dòng có thể là tiêu đề chương trong một truyện EPUB chưa được tách chương đúng cách.

Chọn các dòng thật sự là mốc bắt đầu chương, bỏ mục lục, lời giới thiệu, quảng cáo, tiêu đề phụ, số trang và dòng nhiễu.
Giữ đúng thứ tự xuất hiện. Chuẩn hóa tên chương ngắn gọn nếu cần.

Chỉ trả về JSON hợp lệ, không markdown, không giải thích:
[
  {{"line_number": 123, "title": "Tên chương chuẩn"}}
]

Danh sách ứng viên:
__CANDIDATES__
"""
STEP_ORDER = [
    "upload_received",
    "file_validated",
    "text_extracted",
    "chunked",
    "glossary_generated",
    "glossary_review",
    "translating",
    "merged",
    "output_built",
    "download_ready",
]
AI_SPLIT_TASK_PREFIX = "novel-translator:ai-split:"
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "upload.txt").name.strip()
    return name or "upload.txt"


def _content_type(filename: str, provided: str | None) -> str:
    return provided or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _parse_selected_chapter_indexes(value: str | None) -> list[int] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="selected_chapter_indexes must be a JSON array") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="selected_chapter_indexes must be a JSON array")

    indexes: list[int] = []
    seen: set[int] = set()
    for item in parsed:
        if not isinstance(item, int) or item < 0:
            raise HTTPException(status_code=400, detail="selected_chapter_indexes must contain non-negative integers")
        if item not in seen:
            seen.add(item)
            indexes.append(item)
    if not indexes:
        raise HTTPException(status_code=400, detail="Select at least one chapter")
    return indexes


def _parse_chapter_segments(value: str | None) -> list[dict] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="chapter_segments must be a JSON array") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="chapter_segments must be a JSON array")

    segments: list[dict] = []
    for position, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="chapter_segments items must be objects")
        raw_index = item.get("index")
        segment_index = raw_index if isinstance(raw_index, int) and raw_index >= 0 else position
        start_offset = item.get("start_offset")
        end_offset = item.get("end_offset")
        if not isinstance(start_offset, int) or not isinstance(end_offset, int) or start_offset < 0 or end_offset <= start_offset:
            raise HTTPException(status_code=400, detail="chapter_segments must contain valid start_offset/end_offset")
        title = str(item.get("title") or f"Chapter {position + 1}").strip()[:200]
        segments.append(
            {
                "index": segment_index,
                "title": title or f"Chapter {position + 1}",
                "path": str(item.get("path") or f"ai-line-{position + 1}")[:512],
                "character_count": max(0, int(item.get("character_count") or (end_offset - start_offset))),
                "source": "ai",
                "start_offset": start_offset,
                "end_offset": end_offset,
            }
        )
    return segments


def _chapter_payload(chapter) -> dict:
    return {
        "index": chapter.index,
        "title": chapter.title,
        "path": chapter.path,
        "character_count": chapter.character_count,
        "source": chapter.source,
        "start_offset": chapter.start_offset,
        "end_offset": chapter.end_offset,
    }


def _ai_split_task_key(task_id: str) -> str:
    return f"{AI_SPLIT_TASK_PREFIX}{task_id}"


async def _save_ai_split_task(task_id: str, task: dict[str, object]) -> None:
    await redis_client.setex(_ai_split_task_key(task_id), settings.AI_SPLIT_TASK_TTL_SECONDS, json.dumps(task, ensure_ascii=False))


async def _load_ai_split_task(task_id: str) -> dict[str, object] | None:
    raw = await redis_client.get(_ai_split_task_key(task_id))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def _create_ai_split_task() -> str:
    task_id = str(uuid.uuid4())
    await _save_ai_split_task(task_id, {
        "task_id": task_id,
        "status": "queued",
        "progress_percent": 0,
        "message": "Queued AI chapter splitting",
        "detected_candidates": 0,
        "selected_headings": 0,
        "chapter_count": 0,
        "chapters": [],
        "can_ai_split": True,
        "chapterized": False,
        "error": None,
    })
    return task_id


async def _update_ai_split_task(task_id: str, **fields: object) -> None:
    task = await _load_ai_split_task(task_id)
    if not task:
        return
    if "progress_percent" in fields:
        try:
            fields["progress_percent"] = max(0, min(100, int(fields["progress_percent"] or 0)))
        except (TypeError, ValueError):
            fields.pop("progress_percent", None)
    task.update(fields)
    await _save_ai_split_task(task_id, task)


def _ai_split_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc) or exc.__class__.__name__


def _json_array_from_model_output(content: str) -> list[dict]:
    first = content.find("[")
    last = content.rfind("]")
    if first == -1 or last == -1 or last <= first:
        return []
    try:
        parsed = json.loads(content[first : last + 1])
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _provider_options(config: ProviderConfig) -> dict:
    return {**default_model_options(), **(config.options or {})}


def _create_provider_client(config: ProviderConfig) -> AsyncOpenAI:
    api_key = decrypt_secret(config.encrypted_api_key)
    if config.provider in {"openai", "deepseek"} and not api_key:
        raise HTTPException(status_code=400, detail=f"Missing API key for provider {config.provider}")
    options = _provider_options(config)
    timeout_ms = options.get("timeout", 28800000)
    return AsyncOpenAI(
        api_key=api_key or "ollama",
        base_url=(config.base_url or DEFAULT_BASE_URLS[config.provider]).rstrip("/"),
        timeout=max(float(timeout_ms) / 1000, 1),
        max_retries=0,
    )


async def _chat_completion_content(client: AsyncOpenAI, **kwargs) -> str:
    response = await client.chat.completions.create(**kwargs)
    if hasattr(response, "__aiter__"):
        parts: list[str] = []
        async for event in response:
            if not event.choices:
                continue
            content = getattr(event.choices[0].delta, "content", None)
            if content:
                parts.append(content)
        return "".join(parts)
    return response.choices[0].message.content or ""


async def _ai_selected_headings(
    db: AsyncSession,
    text: str,
    candidates: list | None = None,
    progress_callback: Callable[..., Awaitable[None]] | None = None,
    provider_config_id: str | None = None,
) -> list[tuple[int, str]]:
    candidates = candidates if candidates is not None else chapter_heading_candidates(text)
    if len(candidates) < 2:
        raise HTTPException(status_code=409, detail="Not enough chapter heading candidates for AI splitting")
    if progress_callback:
        await progress_callback(
            progress_percent=25,
            message=f"Detected {len(candidates)} chapter heading candidates",
            detected_candidates=len(candidates),
        )

    if provider_config_id:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_config_id).limit(1))
    else:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.is_default.is_(True)).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(
            status_code=400,
            detail="Selected provider was not found for AI chapter splitting" if provider_config_id else "No default provider configured for AI chapter splitting",
        )

    candidate_text = "\n".join(f"{candidate.line_number}: {candidate.title}" for candidate in candidates)
    options = _provider_options(config)
    client = _create_provider_client(config)
    extra_body = {"options": options} if config.provider == "ollama" else None
    if progress_callback:
        await progress_callback(
            progress_percent=35,
            message=f"Sending {len(candidates)} candidates to {config.provider}/{config.model_name}",
            detected_candidates=len(candidates),
        )
    content = await _chat_completion_content(
        client,
        model=config.model_name,
        temperature=min(float(options["temperature"]), 0.1),
        stream=bool(config.stream),
        extra_body=extra_body,
        messages=[
            {"role": "system", "content": "Bạn chỉ trả về JSON hợp lệ theo schema người dùng yêu cầu."},
            {"role": "user", "content": AI_CHAPTER_SPLIT_PROMPT.replace("__CANDIDATES__", candidate_text)},
        ],
    )
    if progress_callback:
        await progress_callback(progress_percent=65, message="Reading AI chapter split result", detected_candidates=len(candidates))

    valid_lines = {candidate.line_number: candidate.title for candidate in candidates}
    headings: list[tuple[int, str]] = []
    seen: set[int] = set()
    for item in _json_array_from_model_output(content):
        if not isinstance(item, dict):
            continue
        line_number = item.get("line_number")
        if not isinstance(line_number, int) or line_number in seen or line_number not in valid_lines:
            continue
        title = str(item.get("title") or valid_lines[line_number]).strip()
        headings.append((line_number, title or valid_lines[line_number]))
        seen.add(line_number)

    if len(headings) < 2:
        headings = [(candidate.line_number, candidate.title) for candidate in candidates]
    if progress_callback:
        await progress_callback(
            progress_percent=72,
            message=f"AI selected {len(headings)} chapter starts",
            detected_candidates=len(candidates),
            selected_headings=len(headings),
        )
    return headings


def _first_header_value(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(",", 1)[0].strip() or None


def _download_url(request: Request, job_id: str) -> str:
    url = request.url_for("download_job_file", job_id=job_id)
    scheme = _first_header_value(request.headers.get("x-forwarded-proto")) or url.scheme
    host = (
        _first_header_value(request.headers.get("x-forwarded-host"))
        or _first_header_value(request.headers.get("host"))
        or url.netloc
    )
    return f"{scheme}://{host}{url.path}"


def _attachment_content_disposition(filename: str) -> str:
    name = Path(filename or "download").name or "download"
    fallback = name.encode("ascii", "ignore").decode("ascii")
    fallback = re.sub(r'[\r\n"\\;]+', "_", fallback).strip(" .")
    if not fallback:
        suffix = Path(name).suffix
        fallback = f"download{suffix if suffix.isascii() else ''}"

    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def _step_rows(job_id: str) -> list[JobStep]:
    now = utcnow()
    rows: list[JobStep] = []
    for position, step_name in enumerate(STEP_ORDER):
        rows.append(
            JobStep(
                id=str(uuid.uuid4()),
                job_id=job_id,
                step_name=step_name,
                position=position,
                status="completed" if step_name in {"upload_received", "file_validated"} else "pending",
                progress_percent=100 if step_name in {"upload_received", "file_validated"} else 0,
                started_at=now if step_name in {"upload_received", "file_validated"} else None,
                ended_at=now if step_name in {"upload_received", "file_validated"} else None,
            )
        )
    return rows


async def _replace_job_glossary_entries(
    db: AsyncSession, job: Job, payload: GlossaryEntriesUpdate
) -> list[StoryGlossaryEntry]:
    await db.execute(delete(StoryGlossaryEntry).where(StoryGlossaryEntry.job_id == job.id))
    now = utcnow()
    rows: list[StoryGlossaryEntry] = []
    seen: set[str] = set()
    for position, entry in enumerate(payload.entries):
        source_term = entry.source_term.strip()
        translated_term = entry.translated_term.strip()
        if not source_term or not translated_term or source_term in seen:
            continue
        seen.add(source_term)
        rows.append(
            StoryGlossaryEntry(
                id=entry.id or str(uuid.uuid4()),
                job_id=job.id,
                source_term=source_term,
                translated_term=translated_term,
                category=(entry.category or "other").strip()[:64] or "other",
                note=entry.note.strip() if entry.note and entry.note.strip() else None,
                occurrence_count=max(0, entry.occurrence_count),
                position=position,
                created_at=now,
                updated_at=now,
            )
        )
    db.add_all(rows)
    job.updated_at = now
    await db.commit()

    result = await db.execute(
        select(StoryGlossaryEntry).where(StoryGlossaryEntry.job_id == job.id).order_by(StoryGlossaryEntry.position.asc())
    )
    return list(result.scalars().all())


async def _job_detail(db: AsyncSession, job_id: str) -> Job:
    result = await db.execute(select(Job).options(selectinload(Job.provider), selectinload(Job.glossary_provider)).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _append_job_log(db: AsyncSession, job: Job, step_name: str | None, message: str, level: str = "info") -> None:
    db.add(
        JobLog(
            id=str(uuid.uuid4()),
            job_id=job.id,
            step_name=step_name,
            level=level,
            message=message,
            progress_percent=job.progress_percent,
            created_at=utcnow(),
        )
    )


@router.get("", response_model=list[JobListItem])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(100))
    return result.scalars().all()


@router.post("", response_model=JobCreated, status_code=status.HTTP_201_CREATED)
async def create_job(
    file: UploadFile = File(...),
    output_format: str = Form("epub"),
    selected_chapter_indexes: str | None = Form(None),
    chapter_segments: str | None = Form(None),
    glossary_provider_config_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    output_format = output_format.lower()
    if output_format not in {"epub", "txt"}:
        raise HTTPException(status_code=400, detail="output_format must be epub or txt")

    filename = _safe_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .txt, .epub and .pdf files are supported")
    chapter_indexes = _parse_selected_chapter_indexes(selected_chapter_indexes)
    segments = _parse_chapter_segments(chapter_segments)
    if chapter_indexes is not None and extension != ".epub":
        raise HTTPException(status_code=400, detail="Chapter selection is only supported for EPUB files")
    if segments is not None and extension != ".epub":
        raise HTTPException(status_code=400, detail="AI chapter segments are only supported for EPUB files")

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.MAX_FILE_SIZE_MB} MB")

    job_id = str(uuid.uuid4())
    storage_key = f"jobs/{job_id}/source/{filename}"
    upload_file(settings.STORAGE_BUCKET_SOURCE, storage_key, data, _content_type(filename, file.content_type))
    default_provider = (
        await db.execute(select(ProviderConfig).where(ProviderConfig.is_default.is_(True)).limit(1))
    ).scalar_one_or_none()
    glossary_provider = None
    if glossary_provider_config_id:
        glossary_provider = (
            await db.execute(select(ProviderConfig).where(ProviderConfig.id == glossary_provider_config_id).limit(1))
        ).scalar_one_or_none()
        if not glossary_provider:
            raise HTTPException(status_code=404, detail="Glossary provider config not found")

    source_file = {
        "filename": filename,
        "content_type": _content_type(filename, file.content_type),
        "size_bytes": len(data),
        "bucket": settings.STORAGE_BUCKET_SOURCE,
        "key": storage_key,
    }
    if chapter_indexes is not None:
        source_file["selected_chapter_indexes"] = chapter_indexes
    if segments is not None:
        source_file["chapter_segments"] = segments
    chapter_scope_message = ""
    if extension == ".epub":
        selected_count = len(chapter_indexes or [])
        segment_count = len(segments or [])
        chapter_scope_message = (
            f"; selected_chapter_indexes={selected_count if chapter_indexes is not None else 'all'}"
            f"; chapter_segments={segment_count if segments is not None else 0}"
        )

    job = Job(
        id=job_id,
        job_name=Path(filename).stem or filename,
        status="queued",
        current_step="upload_received",
        progress_percent=10,
        output_format=output_format,
        source_file=source_file,
        provider_config_id=default_provider.id if default_provider else None,
        glossary_provider_config_id=glossary_provider.id if glossary_provider else None,
    )
    db.add(job)
    db.add_all(_step_rows(job_id))
    db.add(
        JobLog(
            id=str(uuid.uuid4()),
            job_id=job_id,
            step_name="upload_received",
            level="info",
            message=f"Uploaded {filename} ({len(data) / 1024 / 1024:.2f} MB){chapter_scope_message}",
            progress_percent=10,
            created_at=utcnow(),
        )
    )
    await db.commit()

    try:
        from app.workers.tasks import process_translation_job

        process_translation_job.delay(job_id)
    except Exception:
        # API creation should still succeed in local development without a running broker.
        pass

    return JobCreated(job_id=job_id)


@router.post("/epub-chapters", response_model=EpubChaptersResponse)
async def inspect_epub_chapters(file: UploadFile = File(...)):
    filename = _safe_filename(file.filename)
    if Path(filename).suffix.lower() != ".epub":
        raise HTTPException(status_code=400, detail="Only .epub files can be inspected for chapters")

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.MAX_FILE_SIZE_MB} MB")

    try:
        chapters = extract_epub_chapters(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not inspect EPUB chapters: {exc}") from exc

    chapterized = len(chapters) >= EPUB_CHAPTERIZED_THRESHOLD
    return EpubChaptersResponse(
        chapters=[_chapter_payload(chapter) for chapter in chapters],
        can_ai_split=not chapterized,
        chapterized=chapterized,
        message=None if chapterized else "EPUB has fewer than 10 detected chapters; AI splitting is available",
    )


async def _run_ai_split_task(task_id: str, data: bytes, provider_config_id: str | None = None) -> None:
    try:
        await _update_ai_split_task(task_id, status="processing", progress_percent=5, message="Reading EPUB text")
        text = epub_text(data)
        await _update_ai_split_task(task_id, progress_percent=15, message="Finding chapter heading candidates")
        candidates = chapter_heading_candidates(text)
        await _update_ai_split_task(
            task_id,
            progress_percent=20,
            message=f"Detected {len(candidates)} chapter heading candidates",
            detected_candidates=len(candidates),
        )

        async def progress(**fields: object) -> None:
            await _update_ai_split_task(task_id, status="processing", **fields)

        async with AsyncSessionLocal() as db:
            headings = await _ai_selected_headings(
                db,
                text,
                candidates=candidates,
                progress_callback=progress,
                provider_config_id=provider_config_id,
            )

        async def split_progress(chapter_count: int, total: int) -> None:
            step_progress = int(chapter_count / max(total, 1) * 20)
            await _update_ai_split_task(
                task_id,
                status="processing",
                progress_percent=75 + min(20, step_progress),
                message=f"Split {chapter_count}/{total} chapters",
                selected_headings=len(headings),
                chapter_count=chapter_count,
            )

        chapters = await split_text_by_heading_candidates(text, headings, progress_callback=split_progress)
        if len(chapters) < 2:
            raise HTTPException(status_code=409, detail="AI could not split this EPUB into chapters")

        payload = [_chapter_payload(chapter) for chapter in chapters]
        await _update_ai_split_task(
            task_id,
            status="completed",
            progress_percent=100,
            message=f"AI split EPUB into {len(chapters)} chapters",
            selected_headings=len(headings),
            chapter_count=len(chapters),
            chapters=payload,
            can_ai_split=False,
            chapterized=True,
            error=None,
        )
    except Exception as exc:
        await _update_ai_split_task(
            task_id,
            status="failed",
            progress_percent=100,
            message="AI chapter splitting failed",
            error=_ai_split_error_message(exc),
        )


@router.post("/epub-chapters/ai-split", response_model=EpubAiSplitTaskCreated, status_code=status.HTTP_202_ACCEPTED)
async def ai_split_epub_chapters(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    provider_config_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    filename = _safe_filename(file.filename)
    if Path(filename).suffix.lower() != ".epub":
        raise HTTPException(status_code=400, detail="Only .epub files can be split into chapters")

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.MAX_FILE_SIZE_MB} MB")

    if provider_config_id:
        provider = (await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_config_id).limit(1))).scalar_one_or_none()
        if not provider:
            raise HTTPException(status_code=404, detail="AI chapter split provider config not found")

    task_id = await _create_ai_split_task()
    background_tasks.add_task(_run_ai_split_task, task_id, data, provider_config_id)
    return EpubAiSplitTaskCreated(task_id=task_id)


@router.get("/epub-chapters/ai-split/{task_id}", response_model=EpubAiSplitProgressResponse)
async def get_ai_split_epub_chapters(task_id: str):
    task = await _load_ai_split_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="AI split task not found")
    return task


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    return await _job_detail(db, job_id)


@router.get("/{job_id}/steps", response_model=JobStepsResponse)
async def get_job_steps(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.position.asc()))
    return JobStepsResponse(steps=result.scalars().all())


@router.get("/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(job_id: str, db: AsyncSession = Depends(get_db)):
    exists = await db.execute(select(Job.id).where(Job.id == job_id))
    if not exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")
    result = await db.execute(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.created_at.desc()).limit(5000))
    logs = list(result.scalars().all())
    logs.reverse()
    return JobLogsResponse(logs=logs)


@router.get("/{job_id}/chunks", response_model=JobChunkResultsResponse)
async def get_job_chunk_results(job_id: str, db: AsyncSession = Depends(get_db)):
    exists = await db.execute(select(Job.id).where(Job.id == job_id))
    if not exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")
    result = await db.execute(
        select(JobChunkResult)
        .where(JobChunkResult.job_id == job_id)
        .order_by(JobChunkResult.chunk_index.asc(), JobChunkResult.created_at.asc())
    )
    return JobChunkResultsResponse(chunks=result.scalars().all())


@router.get("/{job_id}/glossary", response_model=GlossaryEntriesResponse)
async def get_job_glossary(job_id: str, db: AsyncSession = Depends(get_db)):
    exists = await db.execute(select(Job.id).where(Job.id == job_id))
    if not exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")
    result = await db.execute(
        select(StoryGlossaryEntry).where(StoryGlossaryEntry.job_id == job_id).order_by(StoryGlossaryEntry.position.asc())
    )
    return GlossaryEntriesResponse(entries=result.scalars().all())


@router.put("/{job_id}/glossary", response_model=GlossaryEntriesResponse)
async def update_job_glossary(job_id: str, payload: GlossaryEntriesUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"queued", "processing", "paused", "awaiting_glossary_review"}:
        raise HTTPException(status_code=409, detail="Glossary can no longer be edited for this job")

    return GlossaryEntriesResponse(entries=await _replace_job_glossary_entries(db, job, payload))


@router.post("/{job_id}/glossary/approve", response_model=JobDetail)
async def approve_job_glossary(job_id: str, payload: GlossaryEntriesUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).options(selectinload(Job.provider), selectinload(Job.glossary_provider)).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "awaiting_glossary_review":
        raise HTTPException(status_code=409, detail="Job is not waiting for glossary review")

    await _replace_job_glossary_entries(db, job, payload)
    job.status = "queued"
    job.current_step = "glossary_review"
    job.progress_percent = max(job.progress_percent, 56)
    job.updated_at = utcnow()
    db.add(
        JobLog(
            id=str(uuid.uuid4()),
            job_id=job_id,
            step_name="glossary_review",
            level="info",
            message="Glossary approved; translation queued",
            progress_percent=job.progress_percent,
            created_at=utcnow(),
        )
    )
    await db.commit()
    await _set_job_step_review_completed(db, job_id)

    try:
        from app.workers.tasks import process_translation_job

        process_translation_job.delay(job_id)
    except Exception:
        pass

    await db.refresh(job)
    return job


async def _set_job_step_review_completed(db: AsyncSession, job_id: str):
    result = await db.execute(select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "glossary_review"))
    step = result.scalar_one_or_none()
    if step:
        now = utcnow()
        step.status = "completed"
        step.progress_percent = 100
        step.started_at = step.started_at or now
        step.ended_at = now
        await db.commit()


async def _get_job_step(db: AsyncSession, job_id: str, step_name: str) -> JobStep | None:
    result = await db.execute(select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == step_name).limit(1))
    return result.scalar_one_or_none()


@router.post("/{job_id}/pause", response_model=JobDetail)
async def pause_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _job_detail(db, job_id)
    if job.status not in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Only queued or processing jobs can be paused")

    job.status = "paused"
    job.updated_at = utcnow()
    _append_job_log(db, job, job.current_step, "Pause requested; worker will stop before starting the next chunk")
    await db.commit()
    return await _job_detail(db, job_id)


@router.post("/{job_id}/resume", response_model=JobDetail)
async def resume_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _job_detail(db, job_id)
    if job.status != "paused":
        raise HTTPException(status_code=409, detail="Job is not paused")

    job.status = "processing"
    job.updated_at = utcnow()
    _append_job_log(db, job, job.current_step, "Resume requested; worker can continue with pending chunks")
    await db.commit()
    return await _job_detail(db, job_id)


@router.post("/{job_id}/provider", response_model=JobDetail)
async def update_job_provider(job_id: str, payload: JobProviderUpdate, db: AsyncSession = Depends(get_db)):
    job = await _job_detail(db, job_id)
    if job.status not in {"queued", "processing", "paused"}:
        raise HTTPException(status_code=409, detail="Provider can only be changed before the job finishes")

    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == payload.provider_config_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider config not found")

    job.provider_config_id = provider.id
    job.updated_at = utcnow()
    _append_job_log(db, job, job.current_step, f"Provider changed to {provider.provider}/{provider.model_name}")
    await db.commit()
    return await _job_detail(db, job_id)


@router.post("/{job_id}/glossary-provider", response_model=JobDetail)
async def update_job_glossary_provider(job_id: str, payload: JobGlossaryProviderUpdate, db: AsyncSession = Depends(get_db)):
    job = await _job_detail(db, job_id)
    if job.status not in {"queued", "processing", "paused"}:
        raise HTTPException(status_code=409, detail="Glossary provider can only be changed before the job finishes")

    glossary_step = await _get_job_step(db, job_id, "glossary_generated")
    if glossary_step and glossary_step.status != "pending":
        raise HTTPException(status_code=409, detail="Glossary model can only be changed before glossary generation starts")

    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == payload.provider_config_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider config not found")

    job.glossary_provider_config_id = provider.id
    job.updated_at = utcnow()
    _append_job_log(db, job, "glossary_generated", f"Glossary provider changed to {provider.provider}/{provider.model_name}")
    await db.commit()
    return await _job_detail(db, job_id)


@router.post("/{job_id}/cancel", response_model=JobDetail)
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _job_detail(db, job_id)
    if job.status in {"queued", "processing", "paused", "awaiting_glossary_review"}:
        job.status = "cancelled"
        job.current_step = "cancelled"
        job.progress_percent = min(job.progress_percent, 99)
        job.updated_at = utcnow()
        _append_job_log(db, job, job.current_step, "Job cancellation requested", level="warning")
        await db.commit()
    return await _job_detail(db, job_id)


@router.get("/{job_id}/download", response_model=DownloadInfo)
async def get_download(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_file:
        raise HTTPException(status_code=409, detail="Output is not ready")

    return DownloadInfo(
        filename=job.output_file["filename"],
        download_url=_download_url(request, job_id),
        content_type=job.output_file.get("content_type", "application/octet-stream"),
    )


@router.get("/{job_id}/download-file", name="download_job_file")
async def download_job_file(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_file:
        raise HTTPException(status_code=409, detail="Output is not ready")

    data = download_file(job.output_file["bucket"], job.output_file["key"])
    headers = {"Content-Disposition": _attachment_content_disposition(job.output_file["filename"])}
    return Response(content=data, media_type=job.output_file.get("content_type", "application/octet-stream"), headers=headers)
