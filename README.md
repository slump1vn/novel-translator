# ConvertVN — Dịch Truyện Tiên Hiệp

Ứng dụng dịch truyện tiên hiệp Trung Quốc sang tiếng Việt, hỗ trợ TXT, EPUB, PDF.  
Stack: **Next.js 14** · **FastAPI** · **Celery** · **PostgreSQL** · **MinIO**

---

## Cấu trúc thư mục

```
novel-translator/
├── backend/                  # FastAPI + Celery
│   ├── app/
│   │   ├── api/              # REST endpoints (jobs, providers)
│   │   ├── core/             # Config, DB, Storage
│   │   ├── models/           # SQLAlchemy ORM
│   │   ├── providers/        # Adapters: OpenAI / DeepSeek / Ollama
│   │   ├── schemas/          # Pydantic request/response
│   │   ├── services/         # file_processor, chunker, translator, output_builder
│   │   └── workers/          # Celery app + translation_task
│   ├── alembic/              # DB migrations
│   └── requirements.txt
├── frontend/                 # Next.js 14 + Tailwind
│   ├── app/                  # Pages: /, /jobs/[id], /settings
│   ├── components/           # UploadZone, JobCard, ProviderForm, …
│   └── lib/                  # api.ts, types.ts
├── docker/
│   ├── Dockerfile.backend
│   └── Dockerfile.frontend
├── docker-compose.yml
├── .env.example
└── .github/workflows/ci.yml
```

---

## Chạy với Docker Compose

```bash
# 1. Sao chép env
cp .env.example .env
# Sửa SECRET_KEY và thêm OpenAI/DeepSeek key nếu có

# 2. Khởi động toàn bộ stack
docker compose up --build

# 3. Truy cập
#   Frontend:  http://localhost:3000
#   API docs:  http://localhost:8000/docs
#   MinIO UI:  http://localhost:9001  (minioadmin / minioadmin)
```

---

## Chạy local (development)

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Tạo DB
alembic upgrade head

# API
uvicorn app.main:app --reload --port 8000

# Worker (terminal khác)
celery -A app.workers.celery_app worker --loglevel=info
```

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

---

## Providers hỗ trợ

| Provider | Model gợi ý | Ghi chú |
|---|---|---|
| OpenAI | gpt-4.1-mini | Cân bằng giá/chất lượng |
| DeepSeek | deepseek-chat | Rẻ, tốt cho tiếng Trung |
| Ollama | qwen3:8b | Chạy local, miễn phí |

Thêm provider tại trang **/settings** → điền API key → test kết nối → đặt mặc định.

---

## Luồng dịch

```
Upload file (.txt/.epub/.pdf)
      ↓
Trích xuất chương (chardet + ebooklib/pypdf)
      ↓
Chia chunk 2000 ký tự (overlap 100)
      ↓
Dịch song song qua AI provider (semaphore + retry)
      ↓
Ghép bản dịch → xuất EPUB / TXT
      ↓
Presigned URL tải về
```

---

## Môi trường biến

| Biến | Ý nghĩa | Bắt buộc |
|---|---|---|
| `DATABASE_URL` | PostgreSQL async URL | ✅ |
| `REDIS_URL` | Redis URL | ✅ |
| `SECRET_KEY` | Khóa mã hóa API key | ✅ |
| `STORAGE_ENDPOINT` | MinIO/S3 endpoint | ✅ |
| `MAX_FILE_SIZE_MB` | Giới hạn file upload | ❌ (50) |
| `CHUNK_SIZE_CHARS` | Kích thước chunk dịch | ❌ (2000) |

---

## Roadmap

- [ ] Auth (JWT / OAuth2)
- [ ] Glossary manager (khóa thuật ngữ tiên hiệp)
- [ ] Dịch song ngữ song song (reader view)
- [ ] Webhook / SSE progress real-time
- [ ] Xuất DOCX
- [ ] Thống kê chi phí token
