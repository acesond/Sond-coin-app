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
