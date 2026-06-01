import asyncio
import html
import json
import posixpath
import signal
import threading
import time
import re
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import chardet
from ebooklib import epub
from openai import AsyncOpenAI
from pypdf import PdfReader
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.epub_chapters import extract_epub_chapters, selected_epub_text
from app.core.security import decrypt_secret
from app.core.storage import download_file, upload_file
from app.core.translation_prompt import build_effective_system_prompt
from app.core.translation_settings import get_translation_system_prompt
from app.models.glossary import StoryGlossaryEntry
from app.models.job import Job, JobLog, JobStep, utcnow
from app.models.provider import ProviderConfig, default_model_options
from app.workers.celery_app import celery_app

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
}


def _model_options(config: ProviderConfig) -> dict:
    return {**default_model_options(), **(getattr(config, "options", None) or {})}


def _model_timeout_seconds(config: ProviderConfig) -> float:
    timeout_ms = _model_options(config).get("timeout")
    try:
        return max(float(timeout_ms) / 1000, 1)
    except (TypeError, ValueError):
        return float(config.timeout_seconds)


def _model_extra_body(config: ProviderConfig, options: dict) -> dict | None:
    if config.provider != "ollama":
        return None
    return {"options": options}

TRANSLATION_USER_PROMPT = """Dịch đoạn nguồn sau sang tiếng Việt theo đúng quy tắc. Không lặp lại marker, không giải thích.

<<<SOURCE>>>
{chunk}
<<<END_SOURCE>>>"""

REPAIR_USER_PROMPT = """Bản dịch trước có dấu hiệu lỗi: {issues}.
Hãy dịch lại đoạn nguồn sau sang tiếng Việt tự nhiên hơn. Chỉ trả về bản dịch đã sửa.

<<<SOURCE>>>
{chunk}
<<<END_SOURCE>>>"""

GLOSSARY_USER_PROMPT = """Đọc mẫu nội dung truyện dưới đây và tạo từ điển tên riêng để dịch thống nhất toàn truyện.

Chỉ lấy các mục thật sự là tên riêng hoặc thuật ngữ cần nhất quán: nhân vật, địa danh, môn phái/tổ chức, chức vị/danh xưng, công pháp, pháp bảo/vật phẩm, cảnh giới.
Ưu tiên cách dịch Hán-Việt hoặc cách gọi tự nhiên trong truyện tiên hiệp/võ hiệp. Không lấy từ phổ thông, không lấy cả câu, không lấy watermark/link.

Trả về JSON hợp lệ duy nhất, không markdown, không giải thích. Định dạng:
[
  {{
    "source_term": "source text",
    "translated_term": "Tên tiếng Việt chuẩn",
    "category": "person|place|organization|title|technique|item|realm|other",
    "note": "ghi chú ngắn nếu cần"
  }}
]

<<<SOURCE_SAMPLE>>>
{text}
<<<END_SOURCE_SAMPLE>>>"""

GLOSSARY_TRANSLATION_INSTRUCTION = """Từ điển tên riêng bắt buộc dùng thống nhất trong đoạn này:
{glossary}

Khi gặp source_term trong nguồn, phải dùng đúng translated_term tương ứng. Không tự đổi cách gọi tên nhân vật, địa danh, môn phái, công pháp, vật phẩm hoặc cảnh giới."""

NOISE_LINE_PATTERNS = [
    re.compile(r"\b(download|tai|tải)\s+(prc|ebook|truyen|truyện)\b", re.IGNORECASE),
    re.compile(r"\btruyen\.thichcode\.net\b", re.IGNORECASE),
    re.compile(r"\btruyenfull\b|\bmetruyencv\b|\btangthuvien\b|\bbachngocsach\b", re.IGNORECASE),
    re.compile(r"^\s*(nguon|nguồn|source)\s*:\s*\S+", re.IGNORECASE),
]
THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)
THINK_TOKEN_RE = re.compile(r"</?think\b[^>]*>|/?think\b", re.IGNORECASE)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
CHUNK_SENTENCE_BREAK_RE = re.compile(r"[。！？!?；;…]+[\"'”’』」》）)]*")


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


def _remove_noise_lines(text: str) -> tuple[str, int]:
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and any(pattern.search(stripped) for pattern in NOISE_LINE_PATTERNS):
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept), removed


def _strip_thinking_artifacts(text: str) -> str:
    text = THINK_BLOCK_RE.sub("", text)
    return THINK_TOKEN_RE.sub("", text)


def _normalize_text_common(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "").replace("\u200b", "")
    text = _strip_thinking_artifacts(text)
    text = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = re.sub(r"^\s*<<<(?:SOURCE|END_SOURCE)>>>\s*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    return text


def _normalize_translation_text(text: str) -> str:
    text = _normalize_text_common(text)
    text, _ = _remove_noise_lines(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_source_text(text: str) -> tuple[str, int]:
    text = _normalize_text_common(text)
    text, removed_lines = _remove_noise_lines(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip(), removed_lines


def _sample_text_for_glossary(text: str, max_chars: int = 30000) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized

    part_size = max_chars // 3
    midpoint = max(0, (len(normalized) - part_size) // 2)
    samples = [
        normalized[:part_size],
        normalized[midpoint : midpoint + part_size],
        normalized[-part_size:],
    ]
    return "\n\n".join(part.strip() for part in samples if part.strip())


def _json_array_from_model_output(content: str) -> list[dict]:
    text = _normalize_text_common(content).strip()
    first = text.find("[")
    last = text.rfind("]")
    if first == -1 or last == -1 or last <= first:
        return []
    try:
        parsed = json.loads(text[first : last + 1])
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_glossary_category(value: object) -> str:
    category = str(value or "other").strip().lower()
    aliases = {
        "character": "person",
        "name": "person",
        "sect": "organization",
        "clan": "organization",
        "group": "organization",
        "skill": "technique",
        "spell": "technique",
        "artifact": "item",
        "treasure": "item",
        "level": "realm",
        "cultivation": "realm",
    }
    category = aliases.get(category, category)
    return category if category in {"person", "place", "organization", "title", "technique", "item", "realm", "other"} else "other"


def _parse_glossary_entries(content: str, source_text: str) -> list[dict[str, object]]:
    raw_entries = _json_array_from_model_output(content)
    rows: list[dict[str, object]] = []
    seen_sources: set[str] = set()

    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        source_term = str(item.get("source_term") or item.get("source") or item.get("term") or "").strip()
        translated_term = str(item.get("translated_term") or item.get("translation") or item.get("target_term") or "").strip()
        if not source_term or not translated_term or source_term in seen_sources:
            continue
        if len(source_term) > 255 or len(translated_term) > 255:
            continue
        if len(source_term) < 2 and CJK_RE.search(source_term):
            continue

        occurrence_count = source_text.count(source_term)
        first_index = source_text.find(source_term)
        if occurrence_count == 0:
            continue

        note = str(item.get("note") or "").strip()
        rows.append(
            {
                "source_term": source_term,
                "translated_term": translated_term,
                "category": _normalize_glossary_category(item.get("category")),
                "note": note[:500] or None,
                "occurrence_count": occurrence_count,
                "_first_index": first_index if first_index >= 0 else 10**12,
            }
        )
        seen_sources.add(source_term)

    rows.sort(key=lambda row: (int(row["_first_index"]), -int(row["occurrence_count"]), str(row["source_term"])))
    cleaned: list[dict[str, object]] = []
    for position, row in enumerate(rows[:200]):
        row.pop("_first_index", None)
        row["position"] = position
        cleaned.append(row)
    return cleaned


async def _generate_glossary_entries(config: ProviderConfig, text: str, system_prompt: str) -> list[dict[str, object]]:
    client = _create_translation_client(config)
    options = _model_options(config)
    prompt = GLOSSARY_USER_PROMPT.format(text=_sample_text_for_glossary(text))
    if config.provider == "ollama" and "qwen3" in config.model_name.lower():
        prompt = f"{prompt}\n\n/no_think"

    content = await _chat_completion_content(
        client,
        model=config.model_name,
        temperature=min(float(options["temperature"]), 0.2),
        stream=bool(config.stream),
        extra_body=_model_extra_body(config, options),
        messages=[
            {
                "role": "system",
                "content": (
                    f"{system_prompt.strip()}\n\n"
                    "Nhiệm vụ hiện tại là tạo từ điển tên riêng cho truyện. "
                    "Chỉ trả về JSON hợp lệ đúng schema đã yêu cầu."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    return _parse_glossary_entries(content, text)


async def _save_glossary_entries(db, job: Job, entries: list[dict[str, object]]) -> None:
    await db.execute(delete(StoryGlossaryEntry).where(StoryGlossaryEntry.job_id == job.id))
    now = utcnow()
    rows = [
        StoryGlossaryEntry(
            id=str(uuid.uuid4()),
            job_id=job.id,
            source_term=str(entry["source_term"]),
            translated_term=str(entry["translated_term"]),
            category=str(entry.get("category") or "other")[:64],
            note=str(entry["note"]) if entry.get("note") else None,
            occurrence_count=int(entry.get("occurrence_count") or 0),
            position=index,
            created_at=now,
            updated_at=now,
        )
        for index, entry in enumerate(entries)
    ]
    db.add_all(rows)
    job.updated_at = now
    await db.commit()


async def _load_glossary_entries(db, job_id: str) -> list[StoryGlossaryEntry]:
    result = await db.execute(
        select(StoryGlossaryEntry).where(StoryGlossaryEntry.job_id == job_id).order_by(StoryGlossaryEntry.position.asc())
    )
    return list(result.scalars().all())


def _format_glossary_for_chunk(chunk: str, entries: list[StoryGlossaryEntry], max_entries: int = 80) -> str:
    lines: list[str] = []
    for entry in entries:
        if entry.source_term not in chunk:
            continue
        detail = f"{entry.source_term} => {entry.translated_term}"
        extras = [entry.category]
        if entry.note:
            extras.append(entry.note)
        if extras:
            detail = f"{detail} ({'; '.join(extras)})"
        lines.append(detail)
        if len(lines) >= max_entries:
            break
    return "\n".join(lines)


def _translation_quality_issues(text: str, source: str) -> list[str]:
    issues: list[str] = []
    if not text.strip():
        issues.append("empty output")
    source_cjk_count = len(CJK_RE.findall(source))
    output_cjk_count = len(CJK_RE.findall(text))
    if output_cjk_count > 3 and source_cjk_count > 20 and output_cjk_count / max(len(text), 1) > 0.01:
        issues.append("raw Chinese characters remain")
    if any(pattern.search(line.strip()) for line in text.splitlines() for pattern in NOISE_LINE_PATTERNS):
        issues.append("source watermark remains")
    return issues


def _build_user_prompt(
    chunk: str,
    *,
    repair_issues: list[str] | None = None,
    no_think: bool = False,
    glossary: str | None = None,
) -> str:
    if repair_issues:
        prompt = REPAIR_USER_PROMPT.format(issues=", ".join(repair_issues), chunk=chunk)
    else:
        prompt = TRANSLATION_USER_PROMPT.format(chunk=chunk)
    if glossary:
        prompt = f"{GLOSSARY_TRANSLATION_INSTRUCTION.format(glossary=glossary)}\n\n{prompt}"
    if no_think:
        prompt = f"{prompt}\n\n/no_think"
    return prompt


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
        await _add_log(db, job, "text_extracted", "Inspecting EPUB chapters", progress=22)
        with _timeout_guard(remaining_timeout("EPUB chapter detection"), "EPUB chapter detection"):
            chapters = extract_epub_chapters(data)
        if not chapters:
            raise ValueError("EPUB does not contain readable chapters")

        selected_indexes = None
        if isinstance(job.source_file, dict) and isinstance(job.source_file.get("selected_chapter_indexes"), list):
            selected_indexes = [int(index) for index in job.source_file["selected_chapter_indexes"]]
        selected_set = set(selected_indexes or [])
        selected_chapters = [chapter for chapter in chapters if not selected_set or chapter.index in selected_set]
        if not selected_chapters:
            raise ValueError("Selected EPUB chapters are empty or invalid")

        await _add_log(
            db,
            job,
            "text_extracted",
            f"Detected {len(chapters)} EPUB chapters; selected {len(selected_chapters)}",
            progress=25,
        )
        for position, chapter in enumerate(selected_chapters, start=1):
            step_progress = int(position / max(len(selected_chapters), 1) * 100)
            progress = 25 + min(9, int(step_progress * 0.09))
            await _set_step(db, job, "text_extracted", "processing", progress, step_progress)
            if position <= 20 or position == len(selected_chapters) or position % 10 == 0:
                await _add_log(
                    db,
                    job,
                    "text_extracted",
                    f"Prepared EPUB chapter {position}/{len(selected_chapters)}: {chapter.title} ({chapter.character_count:,} chars)",
                    progress=progress,
                )
        await _add_log(db, job, "text_extracted", f"Extracted EPUB text in {time.monotonic() - started:.1f}s", progress=34)
        return selected_epub_text(chapters, selected_indexes)

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
        else:
            sentence_end = None
            for match in CHUNK_SENTENCE_BREAK_RE.finditer(normalized, cursor, end):
                if match.end() > cursor + int(chunk_size * 0.6):
                    sentence_end = match.end()
            if sentence_end:
                end = sentence_end
        chunks.append(normalized[cursor:end].strip())
        cursor = end
        while cursor < len(normalized) and normalized[cursor].isspace():
            cursor += 1
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


def _create_translation_client(config: ProviderConfig) -> AsyncOpenAI:
    api_key = decrypt_secret(config.encrypted_api_key)
    if config.provider in {"openai", "deepseek"} and not api_key:
        raise ValueError(f"Missing API key for provider {config.provider}")

    return AsyncOpenAI(
        api_key=api_key or "ollama",
        base_url=(config.base_url or DEFAULT_BASE_URLS[config.provider]).rstrip("/"),
        timeout=_model_timeout_seconds(config),
        max_retries=0,
    )


async def _chat_completion_content(client: AsyncOpenAI, **kwargs) -> str:
    response = await client.chat.completions.create(**kwargs)
    if hasattr(response, "__aiter__"):
        parts: list[str] = []
        async for event in response:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                parts.append(content)
        return "".join(parts)
    return response.choices[0].message.content or ""


async def _translate_chunk_batch(
    config: ProviderConfig,
    chunks: list[str],
    system_prompt: str,
    progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    glossary_entries: list[StoryGlossaryEntry] | None = None,
) -> list[str]:
    client = _create_translation_client(config)
    semaphore = asyncio.Semaphore(config.parallelism)
    effective_system_prompt = build_effective_system_prompt(system_prompt)
    options = _model_options(config)
    no_think = config.provider == "ollama" and "qwen3" in config.model_name.lower()

    async def translate_one(index: int, chunk: str) -> tuple[int, str]:
        async with semaphore:
            last_error: Exception | None = None
            for attempt in range(config.retry_limit + 1):
                try:
                    glossary = _format_glossary_for_chunk(chunk, glossary_entries or [])
                    user_prompt = _build_user_prompt(chunk, no_think=no_think, glossary=glossary)
                    cleaned_text = ""
                    issues: list[str] = []
                    for quality_attempt in range(settings.TRANSLATION_QUALITY_RETRY_LIMIT + 1):
                        content = await _chat_completion_content(
                            client,
                            model=config.model_name,
                            temperature=float(options["temperature"]),
                            stream=bool(config.stream),
                            extra_body=_model_extra_body(config, options),
                            messages=[
                                {"role": "system", "content": effective_system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                        )
                        if not content:
                            raise ValueError("Provider returned an empty translation")
                        has_thinking_artifact = bool(THINK_BLOCK_RE.search(content) or THINK_TOKEN_RE.search(content))
                        cleaned_text = _normalize_translation_text(content)
                        issues = _translation_quality_issues(cleaned_text, chunk)
                        if has_thinking_artifact:
                            issues.append("thinking artifact")
                        if not issues:
                            return index, cleaned_text
                        if quality_attempt < settings.TRANSLATION_QUALITY_RETRY_LIMIT:
                            user_prompt = _build_user_prompt(chunk, repair_issues=issues, no_think=no_think, glossary=glossary)
                    if cleaned_text:
                        return index, cleaned_text
                    raise ValueError(f"Provider returned an invalid translation: {', '.join(issues)}")
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
            if progress_callback and (completed == 1 or completed == len(chunks) or completed % log_every == 0):
                await progress_callback(completed, len(chunks))
    except Exception:
        for task in tasks:
            task.cancel()
        raise

    return translated


async def _translate_chunks(db, job: Job, config: ProviderConfig, chunks: list[str]) -> list[str]:
    system_prompt = await get_translation_system_prompt(db)
    glossary_entries = await _load_glossary_entries(db, job.id)
    await _add_log(
        db,
        job,
        "translating",
        f"Using {config.provider}/{config.model_name} with parallelism {config.parallelism}",
        progress=57,
    )
    if glossary_entries:
        await _add_log(db, job, "translating", f"Applying {len(glossary_entries)} approved glossary entries", progress=57)

    async def update_progress(completed: int, total: int) -> None:
        step_progress = int(completed / max(total, 1) * 100)
        progress = 57 + min(23, int(step_progress * 0.23))
        job.translated_chunks = completed
        await _set_step(db, job, "translating", "processing", progress, step_progress)
        await _add_log(db, job, "translating", f"Translated chunk {completed}/{total}", progress=progress)

    return await _translate_chunk_batch(config, chunks, system_prompt, update_progress, glossary_entries)


async def translate_preview_text(config: ProviderConfig, text: str, system_prompt: str) -> tuple[str, int, int, int]:
    cleaned_text, removed_noise_lines = _clean_source_text(text)
    if not cleaned_text:
        raise ValueError("Source text is empty after cleanup")
    chunks = _chunk_text(cleaned_text, settings.CHUNK_SIZE_CHARS)
    if not chunks:
        raise ValueError("Source text is empty after chunking")
    translated_chunks = await _translate_chunk_batch(config, chunks, system_prompt)
    return "\n\n".join(translated_chunks), len(chunks), len(cleaned_text), removed_noise_lines


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


async def _is_step_completed(db, job_id: str, step_name: str) -> bool:
    result = await db.execute(
        select(JobStep.status).where(JobStep.job_id == job_id, JobStep.step_name == step_name).limit(1)
    )
    return result.scalar_one_or_none() == "completed"


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
        if not job or job.status in {"cancelled", "awaiting_glossary_review", "completed"}:
            return
        if not job.source_file:
            raise ValueError("Job does not have a source file")

        job.status = "processing"
        job.error_message = None
        await _add_log(db, job, "text_extracted", "Job picked up by worker", progress=20)
        await _set_step(db, job, "text_extracted", "processing", 20, 0)

        await _add_log(db, job, "text_extracted", "Downloading source file from object storage", progress=20)
        source = download_file(job.source_file["bucket"], job.source_file["key"])
        await _add_log(db, job, "text_extracted", "Source file downloaded", progress=21)
        raw_text = await _extract_text(db, job, job.source_file["filename"], source)
        text, removed_noise_lines = _clean_source_text(raw_text)
        if removed_noise_lines:
            await _add_log(
                db,
                job,
                "text_extracted",
                f"Removed {removed_noise_lines} source noise/watermark lines before translation",
                progress=34,
            )
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

        provider = await _load_provider(db, job)
        job.provider_config_id = provider.id
        await db.commit()

        if not await _is_step_completed(db, job.id, "glossary_review"):
            await _set_step(db, job, "glossary_generated", "processing", 51, 0)
            system_prompt = await get_translation_system_prompt(db)
            glossary_entries = await _generate_glossary_entries(provider, text, system_prompt)
            await _save_glossary_entries(db, job, glossary_entries)
            await _set_step(db, job, "glossary_generated", "completed", 54, 100)
            await _set_step(db, job, "glossary_review", "processing", 55, 0)
            job.status = "awaiting_glossary_review"
            job.current_step = "glossary_review"
            job.progress_percent = 55
            await _add_log(
                db,
                job,
                "glossary_review",
                f"Generated {len(glossary_entries)} glossary entries; waiting for review",
                progress=55,
            )
            return

        await _set_step(db, job, "glossary_review", "completed", 56, 100)
        await _set_step(db, job, "translating", "processing", 57, 0)
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
