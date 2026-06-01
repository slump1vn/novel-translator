import html
import inspect
import posixpath
import re
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class EpubChapter:
    index: int
    title: str
    path: str
    character_count: int
    text: str
    start_offset: int | None = None
    end_offset: int | None = None
    source: str = "epub"


@dataclass(frozen=True)
class ChapterHeadingCandidate:
    line_number: int
    title: str
    start_offset: int


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


def _path_without_fragment(path: str) -> str:
    return posixpath.normpath(path.split("#", 1)[0]).lstrip("/")


def _unique_paths(paths: list[str], available: set[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        normalized = _path_without_fragment(path)
        if normalized in available and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _strip_html(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(
        r"</?(?:h[1-6]|p|div|section|article|nav|header|footer|li|tr|table|blockquote|pre)\b[^>]*>",
        "\n",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"(?<!\n)(第[0-9一二三四五六七八九十百千万零〇两]+[章节卷回部集])", r"\n\1", value)
    value = re.sub(r"(?<!\n)((?:Chương|Chuong|Chapter|Chap)\s+[0-9IVXLCDMivxlcdm]+)", r"\n\1", value)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line)).strip()


def _title_from_html(value: str, fallback: str) -> str:
    for pattern in [
        r"<h[1-3]\b[^>]*>([\s\S]*?)</h[1-3]>",
        r"<title\b[^>]*>([\s\S]*?)</title>",
    ]:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            title = _strip_html(match.group(1))
            if title:
                return title[:200]
    return fallback


def _find_opf_path(archive: zipfile.ZipFile, names: set[str]) -> str | None:
    container_path = "META-INF/container.xml"
    if container_path not in names:
        return None

    container_root = ElementTree.fromstring(archive.read(container_path))
    for element in container_root.iter():
        if _xml_name(element.tag) == "rootfile":
            full_path = element.attrib.get("full-path")
            if full_path:
                opf_path = _path_without_fragment(full_path)
                return opf_path if opf_path in names else None
    return None


def _find_epub_documents(archive: zipfile.ZipFile, names: set[str], opf_path: str | None) -> list[str]:
    html_candidates = sorted(path for path in names if _is_html_document(path))
    if not opf_path:
        return html_candidates

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
                full_path = _path_without_fragment(posixpath.join(opf_dir, href))
                manifest[item_id] = (full_path, element.attrib.get("media-type"))
        elif local_name == "itemref":
            idref = element.attrib.get("idref")
            if idref:
                spine_ids.append(idref)

    ordered = [manifest[idref][0] for idref in spine_ids if idref in manifest and _is_html_document(*manifest[idref])]
    if not ordered:
        ordered = [path for path, media_type in manifest.values() if _is_html_document(path, media_type)]
    return _unique_paths(ordered or html_candidates, names)


def _manifest_items(archive: zipfile.ZipFile, opf_path: str | None) -> tuple[str, list[dict[str, str]]]:
    if not opf_path:
        return "", []

    opf_root = ElementTree.fromstring(archive.read(opf_path))
    opf_dir = posixpath.dirname(opf_path)
    items: list[dict[str, str]] = []
    for element in opf_root.iter():
        if _xml_name(element.tag) != "item":
            continue
        href = element.attrib.get("href")
        if not href:
            continue
        items.append(
            {
                "path": _path_without_fragment(posixpath.join(opf_dir, href)),
                "media_type": element.attrib.get("media-type", ""),
                "properties": element.attrib.get("properties", ""),
            }
        )
    return opf_dir, items


def _toc_titles_from_ncx(archive: zipfile.ZipFile, ncx_path: str, opf_dir: str) -> dict[str, str]:
    root = ElementTree.fromstring(archive.read(ncx_path))
    titles: dict[str, str] = {}
    for nav_point in root.iter():
        if _xml_name(nav_point.tag) != "navPoint":
            continue
        label = ""
        src = ""
        for child in nav_point.iter():
            local_name = _xml_name(child.tag)
            if local_name == "text" and child.text and not label:
                label = child.text.strip()
            elif local_name == "content" and not src:
                src = child.attrib.get("src", "").strip()
        if label and src:
            titles[_path_without_fragment(posixpath.join(opf_dir, src))] = html.unescape(label)[:200]
    return titles


def _toc_titles_from_nav(archive: zipfile.ZipFile, nav_path: str, opf_dir: str) -> dict[str, str]:
    root = ElementTree.fromstring(archive.read(nav_path))
    titles: dict[str, str] = {}
    for element in root.iter():
        if _xml_name(element.tag) != "a":
            continue
        href = element.attrib.get("href", "").strip()
        label = " ".join(text.strip() for text in element.itertext() if text.strip())
        if href and label:
            titles[_path_without_fragment(posixpath.join(opf_dir, href))] = html.unescape(label)[:200]
    return titles


def _find_toc_titles(archive: zipfile.ZipFile, opf_path: str | None) -> dict[str, str]:
    opf_dir, items = _manifest_items(archive, opf_path)
    titles: dict[str, str] = {}
    for item in items:
        try:
            if item["media_type"] == "application/x-dtbncx+xml":
                titles.update(_toc_titles_from_ncx(archive, item["path"], opf_dir))
            elif "nav" in item["properties"].split() and _is_html_document(item["path"], item["media_type"]):
                titles.update(_toc_titles_from_nav(archive, item["path"], opf_dir))
        except ElementTree.ParseError:
            continue
    return titles


def extract_epub_chapters(data: bytes) -> list[EpubChapter]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = {entry.filename for entry in archive.infolist()}
        opf_path = _find_opf_path(archive, names)
        documents = _find_epub_documents(archive, names, opf_path)
        toc_titles = _find_toc_titles(archive, opf_path)

        chapters: list[EpubChapter] = []
        for document_path in documents:
            raw = archive.read(document_path)
            html_text = raw.decode("utf-8", errors="replace")
            text = _strip_html(html_text)
            if not text:
                continue
            fallback_title = Path(document_path).stem.replace("_", " ").replace("-", " ").strip() or f"Chapter {len(chapters) + 1}"
            title = toc_titles.get(document_path) or _title_from_html(html_text, fallback_title)
            chapters.append(
                EpubChapter(
                    index=len(chapters),
                    title=title,
                    path=document_path,
                    character_count=len(text),
                    text=text,
                )
            )
        return chapters


def selected_epub_text(chapters: list[EpubChapter], selected_indexes: list[int] | None = None) -> str:
    selected = set(selected_indexes or [])
    parts: list[str] = []
    for chapter in chapters:
        if selected and chapter.index not in selected:
            continue
        title = chapter.title.strip() or f"Chapter {chapter.index + 1}"
        parts.append(f"{title}\n\n{chapter.text}")
    return "\n\n".join(parts)


CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"第[0-9一二三四五六七八九十百千万零〇两]+[章节卷回部集][^\n]{0,80}"
    r"|(?:chương|chuong|chapter|chap)\s+[0-9ivxlcdm一二三四五六七八九十百千万零〇两]+[^\n]{0,80}"
    r"|[0-9]{1,4}\s*[.、:-]\s*[^\n]{1,80}"
    r")\s*$",
    re.IGNORECASE,
)
LOOSE_CHAPTER_HINT_RE = re.compile(
    r"(第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节卷回部集]"
    r"|(?:chương|chuong|chapter|chap|quyển|quyen|hồi|hoi)\s+[0-9ivxlcdm一二三四五六七八九十百千万零〇两]+"
    r"|[0-9一二三四五六七八九十百千万零〇两]+\s*[章节卷回部集])",
    re.IGNORECASE,
)
SENTENCE_END_RE = re.compile(r"[。.!?！？…]$")


def epub_text(data: bytes) -> str:
    return selected_epub_text(extract_epub_chapters(data))


def chapter_heading_candidates(text: str, max_candidates: int = 800) -> list[ChapterHeadingCandidate]:
    strict_candidates: list[ChapterHeadingCandidate] = []
    loose_candidates: list[ChapterHeadingCandidate] = []
    offset = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        if 2 <= len(stripped) <= 100 and CHAPTER_HEADING_RE.match(stripped):
            strict_candidates.append(ChapterHeadingCandidate(line_number=line_number, title=stripped[:200], start_offset=offset))
            if len(strict_candidates) >= max_candidates:
                break
        elif _looks_like_loose_heading(stripped):
            loose_candidates.append(ChapterHeadingCandidate(line_number=line_number, title=stripped[:200], start_offset=offset))
        offset += len(line)
    if len(strict_candidates) >= 2:
        return strict_candidates[:max_candidates]
    return (strict_candidates + loose_candidates)[:max_candidates]


def _looks_like_loose_heading(value: str) -> bool:
    if not 2 <= len(value) <= 120:
        return False
    if LOOSE_CHAPTER_HINT_RE.search(value):
        return True
    if len(value) <= 60 and any(char.isdigit() for char in value) and not SENTENCE_END_RE.search(value):
        return True
    return False


async def split_text_by_heading_candidates(
    text: str,
    selected_headings: list[tuple[int, str]],
    progress_callback: Callable[[int, int], Awaitable[None] | None] | None = None,
) -> list[EpubChapter]:
    candidate_by_line = {candidate.line_number: candidate for candidate in chapter_heading_candidates(text)}
    starts: list[tuple[int, str, int]] = []
    seen: set[int] = set()
    for line_number, title in selected_headings:
        if line_number in seen:
            continue
        candidate = candidate_by_line.get(line_number)
        if not candidate:
            continue
        starts.append((candidate.start_offset, title.strip()[:200] or candidate.title, line_number))
        seen.add(line_number)

    starts.sort(key=lambda item: item[0])
    chapters: list[EpubChapter] = []
    total = len(starts)
    for index, (start_offset, title, line_number) in enumerate(starts):
        end_offset = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        chapter_text = text[start_offset:end_offset].strip()
        if not chapter_text:
            continue
        chapters.append(
            EpubChapter(
                index=len(chapters),
                title=title,
                path=f"ai-line-{line_number}",
                character_count=len(chapter_text),
                text=chapter_text,
                start_offset=start_offset,
                end_offset=end_offset,
                source="ai",
            )
        )
        if progress_callback:
            result = progress_callback(len(chapters), total)
            if inspect.isawaitable(result):
                await result
    return chapters
