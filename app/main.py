import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.core import logsafe
from app.core.config import get_settings
from app.core.db import init_db
from app.routers import (
    admin,
    amenities,
    auth,
    boat_ports,
    community,
    compare,
    fishing_rules,
    geo,
    health,
    journals,
    marine_issues,
    me,
    nearby,
    photos,
    place_kakao,
    place_map,
    place_photos,
    places,
    rock_points,
    trips,
)

API_PREFIX = "/api/v1"

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    429: "TOO_MANY_REQUESTS",
    503: "UNAVAILABLE",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 우리 로그(요청 시간·특보 갱신)가 Fly 로그에 보이게. 가림 필터는 이 핸들러에도 붙는다
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logsafe.install()  # 서버 로그에도 인증키·관리자 토큰이 남지 않게
    init_db()
    yield


app = FastAPI(title="입질예보 API", version="0.1.0", lifespan=lifespan)
# 큰 JSON(전체 요약·참고 포인트 1,070곳)을 휴대폰 데이터로 받을 때 크기를 줄인다 (2026-11-19)
app.add_middleware(GZipMiddleware, minimum_size=2048)

_req_log = logging.getLogger("req")
SLOW_MS = 2000


@app.middleware("http")
async def timing(request: Request, call_next):
    """요청마다 걸린 시간을 남긴다 (2026-11-20). 서버가 느려질 때 어느 요청이 원인인지 Fly 로그로 찾기.
    주소의 ? 뒤(검색어 등)는 남기지 않는다. 30초마다 오는 상태 확인은 뺀다"""
    began = time.perf_counter()
    status = 500
    try:
        res = await call_next(request)
        status = res.status_code
        return res
    finally:
        ms = (time.perf_counter() - began) * 1000
        path = request.url.path
        if path != f"{API_PREFIX}/health":
            level = logging.WARNING if ms >= SLOW_MS else logging.INFO
            _req_log.log(
                level, "%s %s %s %.0fms%s", request.method, path, status, ms, " SLOW" if ms >= SLOW_MS else ""
            )


if get_settings().app_env == "dev":
    # 네이티브 앱은 CORS 와 무관. Expo 웹 미리보기용으로 개발 환경에서만 허용
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# 공통 오류 형식: {"error": {"code", "message"}} (명세 5장)
@app.exception_handler(HTTPException)
async def http_exception_handler(_req: Request, exc: HTTPException):
    code = _HTTP_CODES.get(exc.status_code, "ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": str(exc.detail)}},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_req: Request, exc: RequestValidationError):
    # errors() 의 ctx 에는 JSON 직렬화가 안 되는 예외 객체가 들어 있을 수 있어 필요한 필드만 내보낸다
    details = [
        {"loc": list(e.get("loc", ())), "msg": _clean_msg(e.get("msg", "")), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": details[0]["msg"] if details else "요청 값이 올바르지 않습니다",
                "details": details,
            }
        },
    )


def _clean_msg(msg: str) -> str:
    # pydantic 이 붙이는 "Value error, " 접두어 제거 → 앱에 그대로 표시 가능한 한국어 메시지
    return msg.removeprefix("Value error, ")


app.include_router(health.router, prefix=API_PREFIX)
app.include_router(amenities.router, prefix=API_PREFIX)
app.include_router(boat_ports.router, prefix=API_PREFIX)
app.include_router(fishing_rules.router, prefix=API_PREFIX)
app.include_router(places.router, prefix=API_PREFIX)
app.include_router(me.router, prefix=API_PREFIX)
app.include_router(trips.router, prefix=API_PREFIX)
app.include_router(trips.invites, prefix=API_PREFIX)

app.include_router(journals.router, prefix=API_PREFIX)
app.include_router(compare.router, prefix=API_PREFIX)
app.include_router(community.router, prefix=API_PREFIX)
app.include_router(photos.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(geo.router, prefix=API_PREFIX)
app.include_router(nearby.router, prefix=API_PREFIX)
app.include_router(place_map.router, prefix=API_PREFIX)
app.include_router(place_photos.router, prefix=API_PREFIX)
app.include_router(place_kakao.router, prefix=API_PREFIX)
app.include_router(rock_points.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(marine_issues.router, prefix=API_PREFIX)
