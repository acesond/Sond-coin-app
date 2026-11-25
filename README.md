# 매억남 코인 분석 웹앱

매억남·박경철 실전 1장 기준으로 BTC·ETH·XRP·SOL 무기한 선물을 분석하는 모바일 웹앱입니다.
멀티 타임프레임 RSI·거래량·다이버전스 자동 판정, 가설 타점, 손익비 계산기, 매매 전 체크리스트를 제공합니다.
시세는 OKX 공개 API(`https://www.okx.com`)에서 브라우저가 직접 받아옵니다.

## 사용

- 웹: https://acesond.github.io/Sond-coin-app/
- 모바일 브라우저에서 열고 "홈 화면에 추가"하면 앱처럼 전체 화면으로 실행됩니다.

## 구성

- `index.html` — 단일 파일 앱 (외부 빌드·서버 불필요)
- `crypto-events.json` — 코인·거시 주요 일정 원본(시장 자극 요약 `stimulus_summary`, 자세히 보기 풀이 `detail`)
- `scripts/ntfy_alert.py` — 6종목 3중 점검을 파이썬으로 다시 계산해 3/3(주의 포함)일 때만 ntfy 푸시를 보내는 감시 스크립트
- `.github/workflows/coin-alert.yml` — 15분마다 위 스크립트를 실행하는 GitHub Actions 워크플로 (`actions/cache`에 60분 쿨다운 상태 저장)

## 자동 알림 (ntfy)

- 토픽: `https://ntfy.sh/sond-coin-9842k` (ntfy 앱에서 이 토픽을 구독하면 폰으로 푸시가 옵니다)
- 알림 조건: ① 자리 · ② 라인 · ③ 다이버전스가 모두 충족된 **3/3**(웹앱의 `타점 도달`·`주의`)일 때만. 같은 종목·같은 방향은 60분 쿨다운.
- 데이터: 바이낸스 선물(`fapi.binance.com`) 우선, HTTP 451 등으로 막히면 OKX 퍼블릭 API로 자동 폴백.
- 수동 실행: `python3 scripts/ntfy_alert.py --dry-run` (발송 없이 판정만) · `--test` (테스트 알림 1건) · `--json out.json`
- 가설을 새로 배포하면 `scripts/ntfy_alert.py`의 `HYP_DATA`(LEVELS·HYP·ZONE_DEF)를 같은 값으로 바꿔 커밋해야 알림 기준이 맞습니다.
