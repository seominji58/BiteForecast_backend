"""로컬 수집기 실행 상태를 DB와 분리해 기록한다.

DB 스키마를 바꾸지 않고도 프로세스 재시작 뒤 마지막 성공·실패를 확인할 수 있게
작은 JSON 파일을 원자적으로 교체한다. 오류 문자열은 저장 전에 인증정보를 가린다.
"""

import json
from pathlib import Path
from typing import Any

from app.core import logsafe

STATUS_PATH = Path("runtime/collector-status.json")


def read_status(path: Path = STATUS_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"state": "never_run"}
    return value if isinstance(value, dict) else {"state": "invalid"}


def write_status(value: dict[str, Any], path: Path = STATUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(value)
    if clean.get("last_error"):
        clean["last_error"] = logsafe.redact(str(clean["last_error"]))[:1000]
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
