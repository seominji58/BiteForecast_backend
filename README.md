# BiteForecast_backend

입질예보 API 서버 (FastAPI + SQLAlchemy 2 + SQLite)

- 기능명세서: [BiteForecast_docs / 02_명세](https://github.com/seominji58/BiteForecast_docs/tree/main/02_명세)
- 앱: [BiteForecast_frontend](https://github.com/seominji58/BiteForecast_frontend)

## 실행

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

# 0.0.0.0 으로 열어야 같은 Wi-Fi 의 휴대폰(Expo Go)에서 접속 가능
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API 문서: http://localhost:8000/docs
- 헬스체크: `GET /api/v1/health`

## 테스트

```bash
pytest
ruff check .
```

## 구조

```
app/
  main.py        앱 생성, 공통 오류 형식, 라우터 등록
  core/          설정(.env), DB 엔진·세션, 초기 시드
  api/deps.py    DB 세션, X-Device-Id 사용자 식별
  models/        SQLAlchemy 모델 (명세 6장)
  schemas/       요청/응답 Pydantic 모델
  routers/       API 엔드포인트
  services/      비즈니스 로직 (비교, 포인트, 규제 판정 등)
  clients/       공공 API 클라이언트 (국립해양조사원, 기상청)
  jobs/          배치 수집기
seeds/           해역·장소·관측소·규제 시드 데이터
tests/
```

## 규칙

- 공공 API 키는 `.env`에만 둔다. 앱 코드나 git 에 올리지 않는다 (NFR-03)
- 값이 없으면 `null`. 0 으로 채우지 않는다 (TC-02)
- 예보(`forecast`)와 실측(`observed`)은 응답에서 별도 계열로 분리한다 (TC-03)
- 사용자 식별은 `X-Device-Id: <UUID>` 헤더 (로그인 없음, 명세 D-2)
