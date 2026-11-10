# macOS 로컬 수집기 정기 실행안

`com.seominji.biteforecast.collector.plist.example`은 검토용 예시이며 자동 설치하지 않는다.

- launchd가 매시간 **1회 실행**을 시작하므로 `--loop`를 넣지 않는다.
- 수집기 자체의 `runtime/collector.lock` 비차단 잠금이 수동 실행·기존 `--loop`와의 중복 실행을 막는다.
- 한 주기가 1시간을 넘으면 다음 실행은 잠금 확인 후 종료한다.
- 작업 디렉터리를 backend로 고정해 `.env`와 SQLite 상대 경로를 그대로 사용한다.
- 상태는 `python -m app.jobs.collect --status`, 로그는 `runtime/collector.*.log`에서 확인한다.
- 적용 전 기존 `--loop` 프로세스를 종료하고, 예시 파일을 `~/Library/LaunchAgents/`에 복사한 뒤 `launchctl bootstrap`해야 한다.
- 해제 시 `launchctl bootout` 후 복사한 plist를 제거한다. DB나 수집 데이터는 삭제하지 않는다.
