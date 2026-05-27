# ConvertVN - Dịch Truyện Tiên Hiệp

Ứng dụng dịch truyện tiên hiệp Trung Quốc sang tiếng Việt, hỗ trợ TXT, EPUB và PDF.

Stack: **Next.js 16** · **FastAPI** · **Celery** · **PostgreSQL** · **Redis** · **MinIO**

## Cấu Trúc

```text
novel-translator/
├── backend/                  # FastAPI + Celery
│   ├── alembic/              # DB migrations
│   ├── app/
│   │   ├── api/              # REST endpoints
│   │   ├── core/             # Config, DB, storage, security
│   │   ├── models/           # SQLAlchemy ORM
│   │   ├── schemas/          # Pydantic schemas
│   │   └── workers/          # Celery app + translation task
│   └── requirements.txt
├── frontend/                 # Next.js + Tailwind
│   ├── app/                  # Pages: /, /jobs/[id], /settings
│   ├── components/
│   └── lib/                  # API client + types
├── docker/
├── docker-compose.yml
└── .env.example
```

## Chạy Nhanh Bằng Docker Compose

```bash
cp .env.example .env
# Sửa SECRET_KEY, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD trong .env

docker compose up --build -d
docker compose logs -f backend worker
```

Truy cập:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- MinIO UI: `http://localhost:9001`

## Chạy Local Development

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Worker:

```bash
cd backend
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

Frontend:

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Triển Khai Ubuntu On-Premise

Các bước dưới đây giả định server Ubuntu 22.04/24.04, domain trỏ về server, và triển khai bằng Docker Compose.

### 1. Cài Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Lấy source và tạo env

```bash
sudo mkdir -p /opt/convertvn
sudo chown -R $USER:$USER /opt/convertvn
cd /opt/convertvn
git clone <GITHUB_REPO_URL> .
cp .env.example .env
```

Sửa `.env`:

```bash
nano .env
```

Các biến tối thiểu cần đổi:

```env
POSTGRES_PASSWORD=<mat-khau-db-manh>
MINIO_ROOT_PASSWORD=<mat-khau-minio-manh>
SECRET_KEY=<chuoi-ngau-nhien-it-nhat-32-ky-tu>
NEXT_PUBLIC_API_URL=https://your-domain.com
ALLOWED_ORIGINS=["https://your-domain.com"]
```

Nếu chỉ dùng trong LAN, có thể đặt:

```env
NEXT_PUBLIC_API_URL=http://<server-ip>:8000
ALLOWED_ORIGINS=["http://<server-ip>:3000"]
```

### 3. Build và chạy dịch vụ

```bash
docker compose pull
docker compose up --build -d
docker compose ps
docker compose logs -f backend worker
```

Migration DB tự chạy trong container `backend` bằng `alembic upgrade head`.

### 4. Cấu hình firewall

Nếu chạy trực tiếp không qua Nginx:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 3000/tcp
sudo ufw allow 8000/tcp
sudo ufw enable
```

Nếu chạy qua Nginx/HTTPS, chỉ mở 80/443:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 5. Reverse proxy Nginx với HTTPS

Cài Nginx và Certbot:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

Tạo file `/etc/nginx/sites-available/convertvn`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 60m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8000/docs;
        proxy_set_header Host $host;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:8000/openapi.json;
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Kích hoạt site và cấp SSL:

```bash
sudo ln -s /etc/nginx/sites-available/convertvn /etc/nginx/sites-enabled/convertvn
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d your-domain.com
```

Sau khi dùng domain HTTPS, cập nhật `.env`:

```env
NEXT_PUBLIC_API_URL=https://your-domain.com
ALLOWED_ORIGINS=["https://your-domain.com"]
```

Build lại frontend vì `NEXT_PUBLIC_API_URL` được đóng gói lúc build:

```bash
docker compose up --build -d frontend
docker compose up -d backend worker
```

### 6. Tự khởi động sau reboot

Docker Compose đã dùng `restart: always`. Sau reboot, kiểm tra:

```bash
docker compose ps
```

Nếu muốn systemd quản lý rõ ràng hơn, tạo `/etc/systemd/system/convertvn.service`:

```ini
[Unit]
Description=ConvertVN Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/convertvn
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Kích hoạt:

```bash
sudo systemctl daemon-reload
sudo systemctl enable convertvn
sudo systemctl start convertvn
```

### 7. Cập nhật phiên bản mới

```bash
cd /opt/convertvn
git pull
docker compose up --build -d
docker compose logs -f backend worker
```

### 8. Backup dữ liệu

Các volume quan trọng:

- `pgdata`: PostgreSQL
- `miniodata`: file nguồn và file output
- `redisdata`: hàng đợi và trạng thái Celery

Backup PostgreSQL:

```bash
docker compose exec postgres pg_dump -U app novel_translator > backup.sql
```

Backup MinIO volume tùy hạ tầng lưu trữ; tối thiểu nên snapshot thư mục Docker volumes định kỳ hoặc dùng MinIO client để mirror bucket ra NAS.

## Providers Hỗ Trợ

| Provider | Model gợi ý | Ghi chú |
|---|---|---|
| OpenAI | `gpt-4.1-mini` | Cân bằng giá và chất lượng |
| DeepSeek | `deepseek-chat` | Rẻ, tốt cho tiếng Trung |
| Ollama | `qwen3:8b` | Chạy local |

Thêm provider tại `/settings`, test kết nối, rồi đặt làm mặc định trước khi tạo job dịch.

## Luồng Dịch

```text
Upload file (.txt/.epub/.pdf)
  -> trích xuất nội dung
  -> chia chunk
  -> dịch song song qua provider
  -> ghép bản dịch
  -> xuất EPUB/TXT
  -> tải file kết quả
```

## Biến Môi Trường

| Biến | Ý nghĩa |
|---|---|
| `POSTGRES_DB` | Tên database PostgreSQL |
| `POSTGRES_USER` | User PostgreSQL |
| `POSTGRES_PASSWORD` | Mật khẩu PostgreSQL |
| `REDIS_URL` | Redis URL |
| `SECRET_KEY` | Khóa mã hóa API key provider |
| `MINIO_ROOT_USER` | User root MinIO |
| `MINIO_ROOT_PASSWORD` | Mật khẩu root MinIO |
| `STORAGE_ENDPOINT` | Endpoint S3/MinIO |
| `STORAGE_ACCESS_KEY` | Access key S3/MinIO |
| `STORAGE_SECRET_KEY` | Secret key S3/MinIO |
| `MAX_FILE_SIZE_MB` | Giới hạn upload |
| `CHUNK_SIZE_CHARS` | Kích thước chunk dịch |
| `ALLOWED_ORIGINS` | Danh sách origin được CORS cho phép |
| `NEXT_PUBLIC_API_URL` | URL API public mà trình duyệt gọi |
