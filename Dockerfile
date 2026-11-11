# Fly.io 배포용 (2026-11-11). DB 는 Supabase(DATABASE_URL 비밀값), 사진은 볼륨 /data/media
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080
# Fly 프록시 뒤: 실제 접속 주소·https 를 X-Forwarded-* 헤더로 받는다
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
