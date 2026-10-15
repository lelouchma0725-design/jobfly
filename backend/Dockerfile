# JobFly 後端 Dockerfile（基於 Playwright 官方 Python 鏡像，瀏覽器已預裝）
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir .

# 使用鏡像內置瀏覽器，無需下載
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
