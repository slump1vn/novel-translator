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
from dataclasses import dataclass
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
from app.models.job import Job, JobChunkResult, JobLog, JobStep, utcnow
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

GLOSSARY_USER_PROMPT = """Đọc kỹ các mẫu nội dung truyện dưới đây và tạo từ điển tên riêng/thuật ngữ để dịch thống nhất toàn truyện.

Yêu cầu chất lượng:
- Rà soát kỹ, ưu tiên đủ hơn là ít. Nếu mẫu có nhiều tên/thuật ngữ, hãy trả về khoảng 60-180 mục.
- Chỉ lấy mục thật sự cần nhất quán: nhân vật, biệt danh, địa danh, môn phái/tổ chức, chức vị/danh xưng, công pháp, pháp bảo/vật phẩm, cảnh giới, chủng tộc, sự kiện quan trọng.
- Với tên Hán/Trung, ưu tiên cách dịch Hán-Việt hoặc cách gọi tự nhiên trong truyện tiên hiệp/võ hiệp.
- Nếu cùng một nhân vật/địa danh có biệt danh hoặc tên rút gọn, thêm thành mục riêng và ghi chú liên hệ.
- Không lấy từ phổ thông, không lấy cả câu, không lấy watermark/link, không bịa mục không xuất hiện trong mẫu.

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


class JobCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceChapter:
    index: int
    title: str
    text: str


@dataclass(frozen=True)
class ExtractedContent:
    text: str
    chapters: list[SourceChapter] | None = None


@dataclass(frozen=True)
class ChunkMetadata:
    chapter_index: int
    chapter_title: str
    chapter_chunk_index: int
    chapter_total_chunks: int


@dataclass(frozen=True)
class TranslatedChapter:
    index: int
    title: str
    text: str


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


def _strip_leading_chapter_title(chapter_text: str, chapter_title: str) -> str:
    normalized_title = _normalize_text_common(chapter_title).strip()
    normalized_text = _normalize_text_common(chapter_text).strip()
    if not normalized_title or not normalized_text:
        return normalized_text
    if normalized_text == normalized_title:
        return ""
    if normalized_text.startswith(normalized_title):
        remainder = normalized_text[len(normalized_title) :].lstrip()
        return remainder
    return normalized_text


def _sample_text_for_glossary(text: str, max_chars: int = 80000, slices: int = 8) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized

    slice_count = max(3, slices)
    part_size = max(1000, max_chars // slice_count)
    max_start = max(0, len(normalized) - part_size)
    starts = [round(index * max_start / max(slice_count - 1, 1)) for index in range(slice_count)]
    samples: list[str] = []
    seen: set[tuple[int, int]] = set()
    for position, start in enumerate(starts, start=1):
        end = min(len(normalized), start + part_size)
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        part = normalized[start:end].strip()
        if part:
            samples.append(f"--- MẪU {position}/{slice_count} ---\n{part}")
    return "\n\n".join(samples)


def _content_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_content_to_text(item) for item in value]
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "value", "content"):
            text = _content_to_text(value.get(key))
            if text:
                return text
        return ""
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    value_attr = getattr(value, "value", None)
    if isinstance(value_attr, str):
        return value_attr
    return ""


def _json_array_from_model_output(content: str) -> list[dict]:
    text = _normalize_text_common(content).strip()
    first = text.find("[")
    last = text.rfind("]")
    if first == -1 or last == -1 or last <= first:
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return []
        try:
            parsed = json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, dict):
            for key in ("entries", "glossary", "items", "data", "results"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return value
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


def _sanitize_glossary_term(value: object) -> str:
    term = str(value or "").strip()
    term = term.strip("`\"'[](){}<>|")
    term = term.strip("“”‘’「」『』【】《》")
    return re.sub(r"\s+", " ", term).strip()


def _glossary_occurrence_details(source_text: str, source_term: str) -> tuple[int, int]:
    variants = [source_term]
    squashed = source_term.replace(" ", "")
    if squashed != source_term:
        variants.append(squashed)
    best_count = 0
    best_index = -1
    for variant in variants:
        count = source_text.count(variant)
        index = source_text.find(variant)
        if count > best_count or (count == best_count and best_index < 0 <= index):
            best_count = count
            best_index = index
    return best_count, best_index


def _line_glossary_candidates(content: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw_line in _normalize_text_common(content).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("|---", "---|")):
            continue
        line = re.sub(r"^\s*[-*]\s*", "", line)
        line = re.sub(r"^\s*\d+\s*[\).\:-]\s*", "", line)
        if not line:
            continue

        source_term = ""
        translated_term = ""
        category = "other"
        note = ""

        if any(separator in line for separator in ("=>", "->", "→")):
            parts = re.split(r"\s*(?:=>|->|→)\s*", line, maxsplit=1)
            if len(parts) == 2:
                source_term, remainder = parts
                columns = [column.strip() for column in re.split(r"\s*[|;]\s*", remainder) if column.strip()]
                if columns:
                    translated_term = columns[0]
                if len(columns) >= 2:
                    category = columns[1]
                if len(columns) >= 3:
                    note = columns[2]
        else:
            columns = [column.strip() for column in raw_line.split("|")]
            columns = [column for column in columns if column]
            if len(columns) >= 2:
                lower_columns = {column.lower() for column in columns[:3]}
                if {"source_term", "translated_term"} & lower_columns:
                    continue
                source_term = columns[0]
                translated_term = columns[1]
                if len(columns) >= 3:
                    category = columns[2]
                if len(columns) >= 4:
                    note = columns[3]

        source_term = _sanitize_glossary_term(source_term)
        translated_term = _sanitize_glossary_term(translated_term)
        if not source_term or not translated_term:
            continue

        rows.append(
            {
                "source_term": source_term,
                "translated_term": translated_term,
                "category": category,
                "note": note,
            }
        )
    return rows


def _parse_glossary_entries(content: str, source_text: str) -> list[dict[str, object]]:
    raw_entries = _json_array_from_model_output(content)
    if not raw_entries:
        raw_entries = _line_glossary_candidates(content)
    rows: list[dict[str, object]] = []
    seen_sources: set[str] = set()

    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        source_term = _sanitize_glossary_term(item.get("source_term") or item.get("source") or item.get("term") or "")
        translated_term = _sanitize_glossary_term(item.get("translated_term") or item.get("translation") or item.get("target_term") or "")
        if not source_term or not translated_term or source_term in seen_sources:
            continue
        if len(source_term) > 255 or len(translated_term) > 255:
            continue
        if len(source_term) < 2 and CJK_RE.search(source_term):
            continue

        occurrence_count, first_index = _glossary_occurrence_details(source_text, source_term)
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

    try:
        content = await _chat_completion_content(
            client,
            model=config.model_name,
            temperature=min(float(options["temperature"]), 0.15),
            stream=bool(config.stream),
            extra_body=_model_extra_body(config, options),
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt.strip()}\n\n"
                        "Nhiệm vụ hiện tại là tạo từ điển tên riêng/thuật ngữ cho truyện. "
                        "Hãy rà kỹ nhiều mẫu, ưu tiên đủ các tên quan trọng, chỉ trả về JSON hợp lệ đúng schema."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        entries = _parse_glossary_entries(content, text)
        if len(entries) >= 20:
            return entries

        fallback_prompt = (
            "Tạo lại từ điển tên riêng/thuật ngữ chi tiết hơn từ các mẫu truyện sau. "
            "Không giải thích. Mỗi dòng một mục theo đúng định dạng:\n"
            "source_term => translated_term | category | note\n\n"
            f"{_sample_text_for_glossary(text, max_chars=50000, slices=6)}"
        )
        fallback_content = await _chat_completion_content(
            client,
            model=config.model_name,
            temperature=min(float(options["temperature"]), 0.1),
            stream=False,
            extra_body=_model_extra_body(config, options),
            messages=[
                {"role": "system", "content": "Only return glossary entries. No explanation. No markdown code fences."},
                {"role": "user", "content": fallback_prompt},
            ],
        )
        fallback_entries = _parse_glossary_entries(fallback_content, text)
        return fallback_entries if len(fallback_entries) > len(entries) else entries
    finally:
        try:
            await client.close()
        except Exception:
            pass


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


def _format_glossary_for_chunk(chunk: str, entries: list[StoryGlossaryEntry], max_entries: int = 120) -> str:
    lines: list[str] = []
    compact_chunk = re.sub(r"\s+", "", chunk)
    for entry in entries:
        source_term = entry.source_term.strip()
        compact_term = re.sub(r"\s+", "", source_term)
        if source_term not in chunk and (not compact_term or compact_term not in compact_chunk):
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
    force_non_empty: bool = False,
) -> str:
    if repair_issues:
        prompt = REPAIR_USER_PROMPT.format(issues=", ".join(repair_issues), chunk=chunk)
    else:
        prompt = TRANSLATION_USER_PROMPT.format(chunk=chunk)
    if glossary:
        prompt = f"{GLOSSARY_TRANSLATION_INSTRUCTION.format(glossary=glossary)}\n\n{prompt}"
    if force_non_empty:
        prompt = (
            f"{prompt}\n\n"
            "Bat buoc tra ve ban dich thuan van ban bang tieng Viet. "
            "Khong duoc de trong. Neu doan rat ngan, chi la tieu de, ten rieng hoac mot cau ngan, van phai tra ve mot dong ban dich."
        )
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


async def _add_job_log_by_id(
    job_id: str,
    step_name: str | None,
    message: str,
    level: str = "info",
    progress: int | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        await _add_log(db, job, step_name, message, level=level, progress=progress)


async def _upsert_chunk_result(
    job_id: str,
    chunk_index: int,
    source_text: str,
    *,
    status: str,
    metadata: ChunkMetadata | None = None,
    translated_text: str | None = None,
    provider_name: str | None = None,
    model_name: str | None = None,
    error_message: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(JobChunkResult).where(JobChunkResult.job_id == job_id, JobChunkResult.chunk_index == chunk_index).limit(1)
        )
        row = result.scalar_one_or_none()
        now = utcnow()
        if not row:
            row = JobChunkResult(
                id=str(uuid.uuid4()),
                job_id=job_id,
                chunk_index=chunk_index,
                chapter_index=metadata.chapter_index if metadata else None,
                chapter_title=metadata.chapter_title if metadata else None,
                chapter_chunk_index=metadata.chapter_chunk_index if metadata else None,
                chapter_total_chunks=metadata.chapter_total_chunks if metadata else None,
                source_text=source_text,
                status=status,
                translated_text=translated_text,
                provider_name=provider_name,
                model_name=model_name,
                error_message=error_message,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            row.source_text = source_text
            row.chapter_index = metadata.chapter_index if metadata else None
            row.chapter_title = metadata.chapter_title if metadata else None
            row.chapter_chunk_index = metadata.chapter_chunk_index if metadata else None
            row.chapter_total_chunks = metadata.chapter_total_chunks if metadata else None
            row.status = status
            row.translated_text = translated_text
            row.provider_name = provider_name
            row.model_name = model_name
            row.error_message = error_message
            row.updated_at = now
        await db.commit()


async def _preload_chunk_results(job_id: str, chunks: list[str], chunk_metadata: list[ChunkMetadata] | None = None) -> None:
    if not chunks:
        return
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(JobChunkResult.chunk_index).where(JobChunkResult.job_id == job_id))
        existing_indexes = set(existing.scalars().all())
        now = utcnow()
        rows: list[JobChunkResult] = []
        for index, chunk in enumerate(chunks):
            if index in existing_indexes:
                continue
            metadata = chunk_metadata[index] if chunk_metadata and index < len(chunk_metadata) else None
            rows.append(
                JobChunkResult(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    chunk_index=index,
                    chapter_index=metadata.chapter_index if metadata else None,
                    chapter_title=metadata.chapter_title if metadata else None,
                    chapter_chunk_index=metadata.chapter_chunk_index if metadata else None,
                    chapter_total_chunks=metadata.chapter_total_chunks if metadata else None,
                    status="queued",
                    source_text=chunk,
                    created_at=now,
                    updated_at=now,
                )
            )
        if rows:
            db.add_all(rows)
            await db.commit()


async def _wait_for_resume_or_cancel(db, job: Job, step_name: str | None, detail: str | None = None) -> None:
    logged_pause = False
    while True:
        await db.refresh(job)
        if job.status == "cancelled":
            raise JobCancelledError("Job was cancelled")
        if job.status != "paused":
            if logged_pause:
                await _add_log(db, job, step_name, "Job resumed; continuing work", progress=job.progress_percent)
            return
        if not logged_pause:
            await _add_log(db, job, step_name, detail or "Job paused; waiting for resume", progress=job.progress_percent)
            logged_pause = True
        await asyncio.sleep(2)


async def _wait_for_live_job(job_id: str, chunk_number: int, total_chunks: int) -> None:
    logged_pause = False
    while True:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                raise JobCancelledError("Job no longer exists")
            if job.status == "cancelled":
                raise JobCancelledError("Job was cancelled")
            if job.status != "paused":
                if logged_pause:
                    await _add_log(db, job, "translating", f"Chunk {chunk_number}/{total_chunks} resumed after pause")
                return
            if not logged_pause:
                await _add_log(db, job, "translating", f"Chunk {chunk_number}/{total_chunks} waiting because job is paused")
                logged_pause = True
        await asyncio.sleep(2)


async def _load_live_provider(job_id: str) -> ProviderConfig:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise JobCancelledError("Job no longer exists")
        return await _load_provider(db, job)


async def _extract_text(db, job: Job, filename: str, data: bytes) -> ExtractedContent:
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

    async def extract_ai_segmented_chapters(base_text: str, source_label: str) -> ExtractedContent | None:
        if not isinstance(job.source_file, dict) or not isinstance(job.source_file.get("chapter_segments"), list):
            return None

        selected_indexes: set[int] | None = None
        if isinstance(job.source_file.get("selected_chapter_indexes"), list):
            try:
                selected_indexes = {int(index) for index in job.source_file["selected_chapter_indexes"]}
            except (TypeError, ValueError):
                raise ValueError("Selected chapter indexes are invalid")
        if selected_indexes is None:
            await _add_log(db, job, "text_extracted", f"No chapter selection provided; using all AI-split {source_label} chapters", progress=24)

        def segment_matches(segment: dict) -> bool:
            if not selected_indexes:
                return True
            try:
                return int(segment.get("index", -1)) in selected_indexes
            except (TypeError, ValueError):
                return False

        selected_segments = [
            segment
            for segment in job.source_file["chapter_segments"]
            if isinstance(segment, dict) and segment_matches(segment)
        ]
        if not selected_segments:
            raise ValueError("Selected AI chapter segments are empty or invalid")

        parts: list[str] = []
        source_chapters: list[SourceChapter] = []
        for position, segment in enumerate(selected_segments, start=1):
            start_offset = int(segment["start_offset"])
            end_offset = int(segment["end_offset"])
            title = str(segment.get("title") or f"Chapter {position}").strip()
            chapter_text = _strip_leading_chapter_title(base_text[start_offset:end_offset], title)
            if chapter_text:
                parts.append(f"{title}\n\n{chapter_text}")
                source_chapters.append(SourceChapter(index=len(source_chapters), title=title, text=chapter_text))
            step_progress = int(position / max(len(selected_segments), 1) * 100)
            progress = 25 + min(9, int(step_progress * 0.09))
            await _set_step(db, job, "text_extracted", "processing", progress, step_progress)
        await _add_log(
            db,
            job,
            "text_extracted",
            f"Using {len(selected_segments)} AI-split {source_label} chapters",
            progress=34,
        )
        return ExtractedContent(text="\n\n".join(parts), chapters=source_chapters)

    if extension == ".txt":
        with _timeout_guard(remaining_timeout("TXT encoding detection"), "TXT encoding detection"):
            detected = chardet.detect(data)
        encoding = detected.get("encoding") or "utf-8"
        await _add_log(db, job, "text_extracted", f"Detected text encoding: {encoding}", progress=25)
        with _timeout_guard(remaining_timeout("TXT decode"), "TXT decode"):
            text = data.decode(encoding, errors="replace")
        await _add_log(db, job, "text_extracted", f"Decoded TXT file in {time.monotonic() - started:.1f}s", progress=34)
        segmented = await extract_ai_segmented_chapters(text, "TXT")
        if segmented is not None:
            return segmented
        return ExtractedContent(text=text)

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
        return ExtractedContent(text="\n\n".join(parts))

    if extension == ".epub":
        await _add_log(db, job, "text_extracted", "Inspecting EPUB chapters", progress=22)
        with _timeout_guard(remaining_timeout("EPUB chapter detection"), "EPUB chapter detection"):
            chapters = extract_epub_chapters(data)
        if not chapters:
            raise ValueError("EPUB does not contain readable chapters")

        segmented = await extract_ai_segmented_chapters(selected_epub_text(chapters), "EPUB")
        if segmented is not None:
            return segmented

        selected_indexes: list[int] | None = None
        if isinstance(job.source_file, dict) and isinstance(job.source_file.get("selected_chapter_indexes"), list):
            try:
                selected_indexes = [int(index) for index in job.source_file["selected_chapter_indexes"]]
            except (TypeError, ValueError):
                raise ValueError("Selected chapter indexes are invalid")
        if not selected_indexes:
            await _add_log(db, job, "text_extracted", "No chapter selection provided; using all EPUB chapters", progress=24)
        selected_set = set(selected_indexes or [])
        selected_chapters = [chapter for chapter in chapters if not selected_set or chapter.index in selected_set]
        if not selected_chapters:
            raise ValueError("Selected EPUB chapters are empty or invalid")
        source_chapters = [
            SourceChapter(index=position, title=chapter.title.strip() or f"Chapter {chapter.index + 1}", text=chapter.text)
            for position, chapter in enumerate(selected_chapters)
        ]

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
        return ExtractedContent(
            text="\n\n".join(f"{chapter.title}\n\n{chapter.text}" for chapter in source_chapters),
            chapters=source_chapters,
        )

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
    raw_chunks = [chunk for chunk in chunks if chunk]
    if len(raw_chunks) <= 1:
        return raw_chunks

    min_chunk_size = max(200, chunk_size // 5)
    merged: list[str] = []
    carry: str | None = None
    for chunk in raw_chunks:
        current = chunk if carry is None else f"{carry}\n\n{chunk}".strip()
        carry = None
        if len(current) < min_chunk_size:
            if merged:
                merged[-1] = f"{merged[-1].rstrip()}\n\n{current.lstrip()}".strip()
            else:
                carry = current
            continue
        merged.append(current)

    if carry:
        if merged:
            merged[-1] = f"{merged[-1].rstrip()}\n\n{carry.lstrip()}".strip()
        else:
            merged.append(carry)
    return merged


def _clean_extracted_content(extracted: ExtractedContent) -> tuple[str, int, list[SourceChapter] | None]:
    if not extracted.chapters:
        text, removed_noise_lines = _clean_source_text(extracted.text)
        return text, removed_noise_lines, None

    cleaned_chapters: list[SourceChapter] = []
    total_removed_noise_lines = 0
    for chapter in extracted.chapters:
        chapter_text, removed_noise_lines = _clean_source_text(chapter.text)
        total_removed_noise_lines += removed_noise_lines
        if not chapter_text.strip():
            continue
        title = _normalize_text_common(chapter.title).strip()[:200] or f"Chapter {chapter.index + 1}"
        cleaned_chapters.append(SourceChapter(index=len(cleaned_chapters), title=title, text=chapter_text))

    text = "\n\n".join(f"{chapter.title}\n\n{chapter.text}" for chapter in cleaned_chapters)
    return text, total_removed_noise_lines, cleaned_chapters


def _chunk_chapters(chapters: list[SourceChapter]) -> tuple[list[str], list[ChunkMetadata]]:
    chunks: list[str] = []
    metadata: list[ChunkMetadata] = []
    for chapter in chapters:
        chapter_chunks = _chunk_text(chapter.text, settings.CHUNK_SIZE_CHARS)
        chapter_total_chunks = len(chapter_chunks)
        for chapter_chunk_index, chunk in enumerate(chapter_chunks):
            chunks.append(chunk)
            metadata.append(
                ChunkMetadata(
                    chapter_index=chapter.index,
                    chapter_title=chapter.title,
                    chapter_chunk_index=chapter_chunk_index,
                    chapter_total_chunks=chapter_total_chunks,
                )
            )
    return chunks, metadata


def _translated_chapters(
    source_chapters: list[SourceChapter],
    chunk_metadata: list[ChunkMetadata],
    translated_chunks: list[str],
) -> list[TranslatedChapter]:
    chapter_texts: dict[int, list[str]] = {chapter.index: [] for chapter in source_chapters}
    chapter_titles = {chapter.index: chapter.title for chapter in source_chapters}
    for metadata, translated_chunk in zip(chunk_metadata, translated_chunks):
        if translated_chunk.strip():
            chapter_texts.setdefault(metadata.chapter_index, []).append(translated_chunk.strip())

    return [
        TranslatedChapter(index=chapter.index, title=chapter_titles.get(chapter.index, chapter.title), text="\n\n".join(chapter_texts.get(chapter.index, [])))
        for chapter in source_chapters
        if chapter_texts.get(chapter.index)
    ]


def _build_txt(text: str) -> tuple[bytes, str]:
    return text.encode("utf-8"), "text/plain; charset=utf-8"


def _paragraph_html(text: str) -> str:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
    return "\n".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs) or "<p></p>"


def _chapter_file_name(index: int) -> str:
    return f"chapters/chapter-{index + 1:04d}.xhtml"


def _build_epub(title: str, text: str, chapters: list[TranslatedChapter] | None = None) -> tuple[bytes, str]:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("vi")

    style = epub.EpubItem(
        uid="style",
        file_name="styles/novel.css",
        media_type="text/css",
        content="""
body {
  font-family: serif;
  line-height: 1.65;
}
h1 {
  margin: 0 0 1.5em;
  text-align: center;
}
p {
  margin: 0 0 0.85em;
  text-align: justify;
  text-indent: 1.5em;
}
""".strip(),
    )
    book.add_item(style)

    epub_chapters: list[epub.EpubHtml] = []
    if chapters:
        for chapter in chapters:
            item = epub.EpubHtml(title=chapter.title, file_name=_chapter_file_name(chapter.index), lang="vi")
            item.content = f"<h1>{html.escape(chapter.title)}</h1>{_paragraph_html(chapter.text)}"
            item.add_item(style)
            book.add_item(item)
            epub_chapters.append(item)
    else:
        item = epub.EpubHtml(title=title, file_name="content.xhtml", lang="vi")
        item.content = f"<h1>{html.escape(title)}</h1>{_paragraph_html(text)}"
        item.add_item(style)
        book.add_item(item)
        epub_chapters.append(item)

    book.toc = tuple(epub_chapters)
    book.spine = ["nav", *epub_chapters]
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


async def _load_glossary_provider(db, job: Job) -> ProviderConfig:
    if job.glossary_provider_config_id:
        result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == job.glossary_provider_config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("Selected glossary provider no longer exists")
        return config
    return await _load_provider(db, job)


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
            content = _content_to_text(getattr(delta, "content", None))
            if content:
                parts.append(content)
        return "".join(parts)
    return _content_to_text(response.choices[0].message.content)


async def _translate_chunk_batch(
    config: ProviderConfig,
    chunks: list[str],
    system_prompt: str,
    progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    glossary_entries: list[StoryGlossaryEntry] | None = None,
    glossary_loader: Callable[[str], Awaitable[str]] | None = None,
    provider_loader: Callable[[], Awaitable[ProviderConfig]] | None = None,
    job_id: str | None = None,
    chunk_metadata: list[ChunkMetadata] | None = None,
) -> list[str]:
    semaphore = asyncio.Semaphore(config.parallelism)
    effective_system_prompt = build_effective_system_prompt(system_prompt)
    clients: dict[str, AsyncOpenAI] = {}

    def client_key(active_config: ProviderConfig) -> str:
        options = _model_options(active_config)
        return "|".join(
            [
                active_config.id,
                active_config.provider,
                active_config.base_url or DEFAULT_BASE_URLS[active_config.provider],
                active_config.model_name,
                str(options.get("timeout")),
            ]
        )

    def client_for(active_config: ProviderConfig) -> AsyncOpenAI:
        key = client_key(active_config)
        if key not in clients:
            clients[key] = _create_translation_client(active_config)
        return clients[key]

    async def log_chunk(message: str, level: str = "info") -> None:
        if job_id:
            await _add_job_log_by_id(job_id, "translating", message, level=level)

    async def translate_one(index: int, chunk: str) -> tuple[int, str]:
        async with semaphore:
            metadata = chunk_metadata[index] if chunk_metadata and index < len(chunk_metadata) else None
            chunk_number = index + 1
            total_chunks = len(chunks)
            if job_id:
                await _wait_for_live_job(job_id, chunk_number, total_chunks)
            active_config = await provider_loader() if provider_loader else config
            client = client_for(active_config)
            options = _model_options(active_config)
            no_think = active_config.provider == "ollama" and "qwen3" in active_config.model_name.lower()
            started = time.monotonic()
            await log_chunk(
                f"Chunk {chunk_number}/{total_chunks} started: {len(chunk):,} chars using {active_config.provider}/{active_config.model_name}"
            )
            if job_id:
                await _upsert_chunk_result(
                    job_id,
                    index,
                    chunk,
                    status="processing",
                    metadata=metadata,
                    provider_name=active_config.provider,
                    model_name=active_config.model_name,
                )
            last_error: Exception | None = None
            for attempt in range(active_config.retry_limit + 1):
                try:
                    glossary = await glossary_loader(chunk) if glossary_loader else _format_glossary_for_chunk(chunk, glossary_entries or [])
                    user_prompt = _build_user_prompt(chunk, no_think=no_think, glossary=glossary)
                    cleaned_text = ""
                    issues: list[str] = []
                    for quality_attempt in range(settings.TRANSLATION_QUALITY_RETRY_LIMIT + 1):
                        if attempt > 0 or quality_attempt > 0:
                            await log_chunk(
                                f"Chunk {chunk_number}/{total_chunks} retrying provider call "
                                f"(attempt {attempt + 1}/{active_config.retry_limit + 1}, quality {quality_attempt + 1}/{settings.TRANSLATION_QUALITY_RETRY_LIMIT + 1})",
                                level="warning",
                            )
                        content = await _chat_completion_content(
                            client,
                            model=active_config.model_name,
                            temperature=float(options["temperature"]),
                            stream=bool(active_config.stream),
                            extra_body=_model_extra_body(active_config, options),
                            messages=[
                                {"role": "system", "content": effective_system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                        )
                        has_thinking_artifact = bool(THINK_BLOCK_RE.search(content) or THINK_TOKEN_RE.search(content))
                        cleaned_text = _normalize_translation_text(content)
                        issues = _translation_quality_issues(cleaned_text, chunk)
                        if not content.strip():
                            issues.append("empty raw output")
                        elif not cleaned_text:
                            issues.append("empty output after cleanup")
                        if has_thinking_artifact:
                            issues.append("thinking artifact")
                        if not issues:
                            elapsed_ms = int((time.monotonic() - started) * 1000)
                            await log_chunk(
                                f"Chunk {chunk_number}/{total_chunks} completed in {elapsed_ms}ms: "
                                f"{len(cleaned_text):,} output chars, glossary entries applied: {len(glossary.splitlines()) if glossary else 0}"
                            )
                            if job_id:
                                await _upsert_chunk_result(
                                    job_id,
                                    index,
                                    chunk,
                                    status="completed",
                                    metadata=metadata,
                                    translated_text=cleaned_text,
                                    provider_name=active_config.provider,
                                    model_name=active_config.model_name,
                                )
                            return index, cleaned_text
                        if quality_attempt < settings.TRANSLATION_QUALITY_RETRY_LIMIT:
                            await log_chunk(
                                f"Chunk {chunk_number}/{total_chunks} quality check found: {', '.join(issues)}; repairing",
                                level="warning",
                            )
                            user_prompt = _build_user_prompt(
                                chunk,
                                repair_issues=issues,
                                no_think=no_think,
                                glossary=glossary,
                                force_non_empty="empty raw output" in issues or "empty output after cleanup" in issues,
                            )
                    if cleaned_text:
                        elapsed_ms = int((time.monotonic() - started) * 1000)
                        await log_chunk(
                            f"Chunk {chunk_number}/{total_chunks} completed with remaining quality warnings in {elapsed_ms}ms: {', '.join(issues)}",
                            level="warning",
                        )
                        if job_id:
                            await _upsert_chunk_result(
                                job_id,
                                index,
                                chunk,
                                status="completed",
                                metadata=metadata,
                                translated_text=cleaned_text,
                                provider_name=active_config.provider,
                                model_name=active_config.model_name,
                                error_message=", ".join(issues) if issues else None,
                            )
                        return index, cleaned_text
                    if "empty raw output" in issues or "empty output after cleanup" in issues:
                        raise ValueError("Provider returned an empty translation")
                    raise ValueError(f"Provider returned an invalid translation: {', '.join(issues)}")
                except Exception as exc:
                    last_error = exc
                    if attempt < active_config.retry_limit:
                        await log_chunk(
                            f"Chunk {chunk_number}/{total_chunks} failed attempt {attempt + 1}/{active_config.retry_limit + 1}: {exc}",
                            level="warning",
                        )
                        await asyncio.sleep(min(2**attempt, 10))
            await log_chunk(f"Chunk {chunk_number}/{total_chunks} failed: {last_error}", level="error")
            if job_id:
                await _upsert_chunk_result(
                    job_id,
                    index,
                    chunk,
                    status="failed",
                    metadata=metadata,
                    provider_name=active_config.provider,
                    model_name=active_config.model_name,
                    error_message=str(last_error) if last_error else "Translation failed",
                )
            raise RuntimeError(str(last_error) if last_error else "Translation failed")

    translated: list[str] = [""] * len(chunks)
    completed = 0
    tasks = [asyncio.create_task(translate_one(index, chunk)) for index, chunk in enumerate(chunks)]

    try:
        for task in asyncio.as_completed(tasks):
            index, text = await task
            translated[index] = text
            completed += 1
            if progress_callback:
                await progress_callback(completed, len(chunks))
    except Exception:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        for client in clients.values():
            try:
                await client.close()
            except Exception:
                pass

    return translated


async def _translate_chunks(
    db,
    job: Job,
    config: ProviderConfig,
    chunks: list[str],
    chunk_metadata: list[ChunkMetadata] | None = None,
) -> list[str]:
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
        await _add_log(db, job, "translating", f"Applying {len(glossary_entries)} glossary entries", progress=57)
    progress_log_every = max(1, len(chunks) // 20)

    async def load_live_provider() -> ProviderConfig:
        return await _load_live_provider(job.id)

    async def load_live_glossary(chunk: str) -> str:
        async with AsyncSessionLocal() as glossary_db:
            entries = await _load_glossary_entries(glossary_db, job.id)
        return _format_glossary_for_chunk(chunk, entries)

    async def update_progress(completed: int, total: int) -> None:
        step_progress = int(completed / max(total, 1) * 100)
        progress = 57 + min(23, int(step_progress * 0.23))
        job.translated_chunks = completed
        await _set_step(db, job, "translating", "processing", progress, step_progress)
        if completed == 1 or completed == total or completed % progress_log_every == 0:
            await _add_log(db, job, "translating", f"Translation progress {completed}/{total} chunks", progress=progress)

    return await _translate_chunk_batch(
        config,
        chunks,
        system_prompt,
        update_progress,
        glossary_entries,
        load_live_glossary,
        load_live_provider,
        job.id,
        chunk_metadata,
    )


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

        await _wait_for_resume_or_cancel(db, job, job.current_step, "Job paused before worker processing")
        job.status = "processing"
        job.error_message = None
        await _add_log(db, job, "text_extracted", "Job picked up by worker", progress=20)
        await _set_step(db, job, "text_extracted", "processing", 20, 0)

        await _wait_for_resume_or_cancel(db, job, "text_extracted")
        await _add_log(db, job, "text_extracted", "Downloading source file from object storage", progress=20)
        source = download_file(job.source_file["bucket"], job.source_file["key"])
        await _add_log(db, job, "text_extracted", "Source file downloaded", progress=21)
        extracted = await _extract_text(db, job, job.source_file["filename"], source)
        text, removed_noise_lines, source_chapters = _clean_extracted_content(extracted)
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

        await _wait_for_resume_or_cancel(db, job, "chunked")
        await _add_log(db, job, "chunked", f"Extracted {len(text):,} characters", progress=36)
        await _set_step(db, job, "chunked", "processing", 40, 0)
        chunk_metadata: list[ChunkMetadata] | None = None
        if source_chapters:
            chunks, chunk_metadata = _chunk_chapters(source_chapters)
        else:
            chunks = _chunk_text(text, settings.CHUNK_SIZE_CHARS)
        if not chunks:
            raise ValueError("Source text is empty after chunking")
        job.total_chunks = len(chunks)
        if source_chapters:
            await _add_log(
                db,
                job,
                "chunked",
                f"Created {len(chunks)} chunks across {len(source_chapters)} chapters with target size {settings.CHUNK_SIZE_CHARS}",
                progress=49,
            )
        else:
            await _add_log(db, job, "chunked", f"Created {len(chunks)} chunks with target size {settings.CHUNK_SIZE_CHARS}", progress=49)
        await _preload_chunk_results(job.id, chunks, chunk_metadata)
        await _set_step(db, job, "chunked", "completed", 50, 100)

        provider = await _load_provider(db, job)
        job.provider_config_id = provider.id
        glossary_provider = await _load_glossary_provider(db, job)
        await db.commit()

        await _wait_for_resume_or_cancel(db, job, "glossary_generated")
        if not await _is_step_completed(db, job.id, "glossary_review"):
            await _set_step(db, job, "glossary_generated", "processing", 51, 0)
            system_prompt = await get_translation_system_prompt(db)
            await _add_log(
                db,
                job,
                "glossary_generated",
                f"Generating glossary with {glossary_provider.provider}/{glossary_provider.model_name}",
                progress=51,
            )
            glossary_entries = await _generate_glossary_entries(glossary_provider, text, system_prompt)
            await _save_glossary_entries(db, job, glossary_entries)
            await _set_step(db, job, "glossary_generated", "completed", 54, 100)
            await _set_step(db, job, "glossary_review", "completed", 56, 100)
            await _add_log(
                db,
                job,
                "glossary_review",
                (
                    f"Generated {len(glossary_entries)} glossary entries; continuing translation"
                    if glossary_entries
                    else "Generated 0 glossary entries after fallback parsing; continuing translation without glossary"
                ),
                level="info" if glossary_entries else "warning",
                progress=56,
            )
        else:
            await _set_step(db, job, "glossary_review", "completed", 56, 100)

        await _wait_for_resume_or_cancel(db, job, "translating")
        await _set_step(db, job, "translating", "processing", 57, 0)
        translated_chunks = await _translate_chunks(db, job, provider, chunks, chunk_metadata)
        await _wait_for_resume_or_cancel(db, job, "translating")
        job.translated_chunks = len(translated_chunks)
        job.failed_chunks = 0
        await _set_step(db, job, "translating", "completed", 80, 100)

        await _wait_for_resume_or_cancel(db, job, "merged")
        await _set_step(db, job, "merged", "processing", 85, 0)
        await _add_log(db, job, "merged", "Merging translated chunks", progress=85)
        translated_text = "\n\n".join(translated_chunks)
        translated_chapters = (
            _translated_chapters(source_chapters, chunk_metadata, translated_chunks)
            if source_chapters and chunk_metadata
            else None
        )
        await _set_step(db, job, "merged", "completed", 88, 100)

        await _wait_for_resume_or_cancel(db, job, "output_built")
        await _set_step(db, job, "output_built", "processing", 92, 0)
        await _add_log(db, job, "output_built", f"Building {job.output_format.upper()} output", progress=92)
        base_name = Path(job.source_file["filename"]).stem or job.job_name
        if job.output_format == "txt":
            text_output = (
                "\n\n".join(f"{chapter.title}\n\n{chapter.text}" for chapter in translated_chapters)
                if translated_chapters
                else translated_text
            )
            output_bytes, content_type = _build_txt(text_output)
            output_filename = f"{base_name}.translated.txt"
        else:
            output_bytes, content_type = _build_epub(base_name, translated_text, translated_chapters)
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
    except JobCancelledError:
        return
    except Exception as exc:
        asyncio.run(_fail_job(job_id, str(exc)))
        raise
