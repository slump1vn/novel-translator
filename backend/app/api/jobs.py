import mimetypes
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.storage import download_file, upload_file
from app.models.job import Job, JobLog, JobStep, utcnow
from app.models.provider import ProviderConfig
from app.schemas.jobs import DownloadInfo, JobCreated, JobDetail, JobListItem, JobLogsResponse, JobStepsResponse

router = APIRouter()

ALLOWED_EXTENSIONS = {".txt", ".epub", ".pdf"}
STEP_ORDER = [
    "upload_received",
    "file_validated",
    "text_extracted",
    "chunked",
    "translating",
    "merged",
    "output_built",
    "download_ready",
]


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "upload.txt").name.strip()
    return name or "upload.txt"


def _content_type(filename: str, provided: str | None) -> str:
    return provided or mimetypes.guess_type(filename)[0] or "application/octet-stream"


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


@router.get("", response_model=list[JobListItem])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(100))
    return result.scalars().all()


@router.post("", response_model=JobCreated, status_code=status.HTTP_201_CREATED)
async def create_job(
    file: UploadFile = File(...),
    output_format: str = Form("epub"),
    db: AsyncSession = Depends(get_db),
):
    output_format = output_format.lower()
    if output_format not in {"epub", "txt"}:
        raise HTTPException(status_code=400, detail="output_format must be epub or txt")

    filename = _safe_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .txt, .epub and .pdf files are supported")

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

    job = Job(
        id=job_id,
        job_name=Path(filename).stem or filename,
        status="queued",
        current_step="upload_received",
        progress_percent=10,
        output_format=output_format,
        source_file={
            "filename": filename,
            "content_type": _content_type(filename, file.content_type),
            "size_bytes": len(data),
            "bucket": settings.STORAGE_BUCKET_SOURCE,
            "key": storage_key,
        },
        provider_config_id=default_provider.id if default_provider else None,
    )
    db.add(job)
    db.add_all(_step_rows(job_id))
    db.add(
        JobLog(
            id=str(uuid.uuid4()),
            job_id=job_id,
            step_name="upload_received",
            level="info",
            message=f"Uploaded {filename} ({len(data) / 1024 / 1024:.2f} MB)",
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


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).options(selectinload(Job.provider)).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/steps", response_model=JobStepsResponse)
async def get_job_steps(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.position.asc()))
    return JobStepsResponse(steps=result.scalars().all())


@router.get("/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(job_id: str, db: AsyncSession = Depends(get_db)):
    exists = await db.execute(select(Job.id).where(Job.id == job_id))
    if not exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")
    result = await db.execute(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.created_at.asc()).limit(500))
    return JobLogsResponse(logs=result.scalars().all())


@router.post("/{job_id}/cancel", response_model=JobDetail)
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).options(selectinload(Job.provider)).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"queued", "processing"}:
        job.status = "cancelled"
        job.current_step = "cancelled"
        job.progress_percent = min(job.progress_percent, 99)
        job.updated_at = utcnow()
        await db.commit()
        await db.refresh(job)
    return job


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
