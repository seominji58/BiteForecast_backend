from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import init_db
from app.routers import health, me, places

API_PREFIX = "/api/v1"

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="입질예보 API", version="0.1.0", lifespan=lifespan)

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
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "요청 값이 올바르지 않습니다",
                "details": exc.errors(),
            }
        },
    )


app.include_router(health.router, prefix=API_PREFIX)
app.include_router(places.router, prefix=API_PREFIX)
app.include_router(me.router, prefix=API_PREFIX)
