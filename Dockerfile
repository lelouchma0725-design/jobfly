# JobFly 後端 Dockerfile（倉庫根，context 為根目錄，路徑無歧義）
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./

RUN pip install --no-cache-dir .

# 使用鏡像內置瀏覽器，無需下載
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 綁定 Render 注入的 $PORT（Docker 服務默認 10000）
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
