from fastapi import FastAPI
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.auth import get_current_user
from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.providers import router as providers_router
from app.api.settings import router as settings_router
from app.api.translation import router as translation_router

app = FastAPI(title="Novel Translator API", version="1.0.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["jobs"], dependencies=[Depends(get_current_user)])
app.include_router(providers_router, prefix="/api/v1/provider-configs", tags=["providers"], dependencies=[Depends(get_current_user)])
app.include_router(settings_router, prefix="/api/v1/settings", tags=["settings"], dependencies=[Depends(get_current_user)])
app.include_router(translation_router, prefix="/api/v1/translation-preview", tags=["translation"], dependencies=[Depends(get_current_user)])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "novel-translator-api"}
