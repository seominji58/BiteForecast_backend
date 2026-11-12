# BiteForecast_backend

입질예보 API 서버 (FastAPI + SQLAlchemy 2 · DB: Supabase PostgreSQL, 로컬 개발·테스트는 SQLite)

- 배포 서버: https://biteforecast-api.fly.dev/api/v1

- 기획 의도(개발 배경): [이 앱을 만드는 이유](https://github.com/seominji58/BiteForecast_docs/blob/main/01_기획/2026-11-12_개발배경_및_외부API.md#1-이-앱을-만드는-이유)
- 외부 API 정리: [사용 중인 외부 API·서비스](https://github.com/seominji58/BiteForecast_docs/blob/main/01_기획/2026-11-12_개발배경_및_외부API.md#2-사용-중인-외부-api서비스)
- 기능명세서: [BiteForecast_docs / 02_명세](https://github.com/seominji58/BiteForecast_docs/tree/main/02_명세)
- 앱: [BiteForecast_frontend](https://github.com/seominji58/BiteForecast_frontend)

## 실행

> 매일 켜는 순서, 휴대폰 연결(터널), 자주 나는 문제는 **[실행 가이드](https://github.com/seominji58/BiteForecast_docs/blob/main/06_개발환경/실행_가이드.md)** 참고

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # DATA_GO_KR_API_KEY, KMA_API_KEY 입력

# 지원 장소·관측소 적재 (219곳: 신고 바다 낚시터 + 바다낚시지수 지점 + 수동 지정)
python -m seeds.load

# 공공 데이터 수집 (처음 1회는 수 분 소요, 이후에는 받은 자료를 건너뜀)
python -m app.jobs.collect

# 로컬에서 1시간 주기로 계속 수집. 예상 밖 오류는 1분·5분 뒤 재시도하고 다음 주기도 계속 실행
python -m app.jobs.collect --loop

# 마지막 완전 성공·일부 실패·최종 실패와 DB 자료별 신선도 확인
python -m app.jobs.collect --status

# 0.0.0.0 으로 열어야 같은 Wi-Fi 의 휴대폰(Expo Go)에서 접속 가능
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

- API 문서: http://localhost:8001/docs
- 헬스체크: `GET /api/v1/health`
- 사진 인증 관리자 화면: http://localhost:8001/api/v1/admin (`ADMIN_TOKEN` 필요)
- DB 스키마가 바뀌어도 지울 필요 없다. 서버가 켜질 때 새 테이블·컬럼만 추가한다 (운영 전환 시 Alembic)
- 수집기 상태는 `runtime/collector-status.json`에 원자적으로 기록되며 git에 포함하지 않는다. `--loop`는 로컬 터미널이
  실행 중인 동안 유지되므로 재부팅 뒤에는 다시 시작해야 한다.

| 환경변수 | 내용 |
|---|---|
| `DATA_GO_KR_API_KEY` | 공공데이터포털 인증키 (국립해양조사원 물때·부이·바다낚시지수, 기상청 단기예보·특보) |
| `KMA_API_KEY` | 기상청 API허브 인증키 (현재 사용 안 함) |
| `ADMIN_TOKEN` | 사진 인증 관리자 검토 비밀값 (비우면 관리자 기능 차단) |
| `MEDIA_DIR` | 업로드 사진 저장 폴더 (기본 `./media`, git 제외) |

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
