"""경기데이터드림(openapi.gg.go.kr) OpenAPI 공통 호출.

요청: GET https://openapi.gg.go.kr/{서비스명}?KEY=인증키&Type=json&pIndex=쪽&pSize=건수(최대 1000)
응답(정상): {"서비스명": [{"head": [{"list_total_count": N}, {"RESULT": {"CODE": "INFO-000", ...}}]},
                        {"row": [...]}]}
응답(오류·자료 없음): {"RESULT": {"CODE": "ERROR-310"|"INFO-200"|..., "MESSAGE": "..."}}
  (2026-11-12 실제 호출로 확인: 없는 서비스명 → ERROR-310)

- 인증키는 서버 설정(GYEONGGI_DATA_API_KEY)에서만 읽고, 오류 메시지에서 가린다
- 자료가 없으면 빈 목록 (0 이나 가짜 행을 만들지 않음)
"""

import httpx

from app.core.config import get_settings

BASE = "https://openapi.gg.go.kr"
MAX_PAGE_SIZE = 1000
MAX_PAGES = 50  # 안전장치 (최대 5만 건)


class GyeonggiError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


# 오류 코드 → 사람이 읽는 설명 (공통 코드, 확인된 것만 의미를 적는다)
_KNOWN = {
    "ERROR-310": "해당 서비스를 찾을 수 없습니다 (서비스명 확인)",  # 2026-11-12 실제 응답으로 확인
}


class GyeonggiClient:
    def __init__(self, api_key: str | None = None, http: httpx.Client | None = None):
        s = get_settings()
        self.api_key = (api_key if api_key is not None else s.gyeonggi_data_api_key).strip()
        if not self.api_key:
            raise GyeonggiError(
                "경기데이터드림 인증키(GYEONGGI_DATA_API_KEY)가 설정되지 않았습니다", "NO_KEY"
            )
        self.http = http or httpx.Client(timeout=s.external_timeout_seconds)

    def _hide(self, text: str) -> str:
        return text.replace(self.api_key, "***")

    def page(
        self, service: str, p_index: int = 1, p_size: int = MAX_PAGE_SIZE, **filters
    ) -> tuple[int, list[dict]]:
        """한 쪽. (전체 건수, 행 목록). 자료 없음은 (0, [])"""
        params = {
            "KEY": self.api_key,
            "Type": "json",
            "pIndex": p_index,
            "pSize": min(p_size, MAX_PAGE_SIZE),
            **filters,
        }
        try:
            r = self.http.get(f"{BASE}/{service}", params=params)
        except httpx.HTTPError as e:
            raise GyeonggiError(f"경기데이터드림 호출 실패: {type(e).__name__}", "NETWORK") from None
        if r.status_code != 200:
            raise GyeonggiError(f"경기데이터드림 HTTP {r.status_code}", f"HTTP_{r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise GyeonggiError(
                "경기데이터드림 응답이 JSON 이 아닙니다: " + self._hide(r.text[:120]), "BAD_RESPONSE"
            ) from None

        if "RESULT" in data:  # 오류 또는 자료 없음
            code = data["RESULT"].get("CODE", "")
            if code == "INFO-200":
                return 0, []
            msg = _KNOWN.get(code) or self._hide(str(data["RESULT"].get("MESSAGE", "")))
            raise GyeonggiError(f"경기데이터드림 {code}: {msg}", code)

        body = data.get(service)
        if not isinstance(body, list) or not body:
            raise GyeonggiError("경기데이터드림 응답 형식이 예상과 다릅니다", "BAD_RESPONSE")
        head = next((b["head"] for b in body if "head" in b), [])
        total = next((h["list_total_count"] for h in head if "list_total_count" in h), 0)
        result = next((h["RESULT"] for h in head if "RESULT" in h), {})
        if result.get("CODE") not in (None, "INFO-000"):
            raise GyeonggiError(
                f"경기데이터드림 {result.get('CODE')}: {self._hide(str(result.get('MESSAGE', '')))}"
            )
        rows = next((b["row"] for b in body if "row" in b), [])
        return int(total), rows

    def all(self, service: str, **filters) -> list[dict]:
        """모든 쪽을 받아 합친다 (최대 MAX_PAGES 쪽)"""
        out: list[dict] = []
        for p in range(1, MAX_PAGES + 1):
            total, rows = self.page(service, p, MAX_PAGE_SIZE, **filters)
            out.extend(rows)
            if not rows or len(out) >= total:
                break
        return out
