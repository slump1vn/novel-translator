from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.jobs import router as jobs_router
from app.api.providers import router as providers_router
from app.api.translation import router as translation_router

app = FastAPI(title="Novel Translator API", version="1.0.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(providers_router, prefix="/api/v1/provider-configs", tags=["providers"])
app.include_router(translation_router, prefix="/api/v1/translation-preview", tags=["translation"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "novel-translator-api"}
