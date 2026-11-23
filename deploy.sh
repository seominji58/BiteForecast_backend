#!/usr/bin/env bash
# 백엔드 배포 한 번에 (2026-11-23): DB 구조 맞추기 → 서버 배포 → 수집기 이미지 맞추기 → 확인.
# 수집기(예약 머신)는 fly deploy 로 바뀌지 않는다. 서버만 새 코드가 되면 수집기가 DB 버전 검사에서 멈춘다
# (2026-11-23 19:13 배포 뒤 예보 수집 중단). 그래서 배포 직후 서버와 같은 이미지로 맞춘다.
# 사용: ./deploy.sh   (backend 폴더에서, main 브랜치에서)
set -euo pipefail
cd "$(dirname "$0")"

APP=biteforecast-api
COLLECTOR=891eee5f0969d8
APP_MACHINE=080ee5debe74d8

DB_URL=$(grep '^SUPABASE_DATABASE_URL=' .env | cut -d= -f2-)
[ -n "$DB_URL" ] || { echo "backend/.env 에 SUPABASE_DATABASE_URL 이 없어요"; exit 1; }

echo "① DB 구조 맞추기 (alembic upgrade head)"
DATABASE_URL="$DB_URL" .venv/bin/alembic upgrade head

echo "② 서버 배포 (fly deploy)"
fly deploy -a "$APP"

echo "③ 수집기를 서버와 같은 이미지로"
IMG=$(fly machine status "$APP_MACHINE" -a "$APP" -d | grep -m1 '"image"' | sed 's/.*"image": "\(.*\)".*/\1/')
fly machine update "$COLLECTOR" -a "$APP" --image "$IMG" --schedule hourly --restart no -y
fly machine start "$COLLECTOR" -a "$APP" || true

echo "④ 확인"
curl -fsS "https://$APP.fly.dev/api/v1/health" && echo
echo "완료 — 수집기가 지금 한 번 돌고 있어요 (약 5분). 이후 매시간 + 오래되면 서버가 깨움"
