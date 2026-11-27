#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""손디 코인 웹앱 — 3중 점검 3/3 ntfy 자동 알림 (15분 감시)

웹앱(https://acesond.github.io/Sond-coin-app/)의 진입 근거 3중 점검을 파이썬으로 그대로 옮겨,
**3/3 타점 도달**이 뜰 때만 ntfy 토픽으로 푸시를 보냅니다.

  · ① 자리   — 4H 마지막 레그 0.45~0.68 되돌림 안, 또는 현재가가 가설의 숏/눌림 존 안(±0.09%)
  · ② 라인   — 가장 가까운 가설·4H 스윙 라인 0.6% 이내 (①과 같은 숫자면 1개로 셈)
  · ③ 다이버전스 — 1H·4H RSI 다이버전스(고점/저점이 무효화되지 않은 것만)
  판정 라벨은 웹앱과 동일하게 「타점 도달 / 숏·롱 대기 / 관망 / 폐기 / 이탈」로 계산합니다.
  **매억남 기본 원칙이 메인 판정**이라 3/3이면 폐기·이탈이 아닌 한 ‘타점 도달’이고,
  NEoWave 파동 상태(1·4파 겹침·터미널·깊은 조정)·1D 역추세는 판정을 깎지 않고 본문 ‘참고’ 줄로만 남깁니다.
  타점 도달일 때만 알림을 보냅니다.

추가: **자동 1 (4H 모노웨이브 추세 재개)** 감시 — 웹앱 «자동 후보»의 후보 1을 그대로 옮겨,
  4H ATR(14)×2.5 모노웨이브 직전 파동(m1)의 0.5·0.618·0.786 되돌림 자리에 현재가가
  **±0.8% 이내**로 들어오면(파동 무효선 100% 되돌림을 넘지 않은 경우만) 별도 알림을 보냅니다.
  수작업 가설 3중 점검과는 다른 종류라 본문에 그 사실을 적고, 쿨다운도 따로 셉니다.

데이터: 바이낸스 선물 fapi.binance.com 우선(1D 200봉 · 4H 200봉 · 1H 200봉),
        HTTP 451 등으로 막히면 OKX 퍼블릭 API(BTC-USDT-SWAP …)로 자동 폴백.

가설값: HYP_VERSION 2026-11-26-1015 (index.html의 LEVELS · HYP · ZONE_DEF와 같은 값).
        가설을 새로 배포하면 아래 HYP_DATA를 같은 값으로 바꿔 커밋하면 됩니다.

사용법:
    python3 scripts/ntfy_alert.py                 # 1회 스캔 → 3/3만 발송 (60분 쿨다운)
    python3 scripts/ntfy_alert.py --dry-run       # 발송 없이 판정만 (상태 파일도 안 씀)
    python3 scripts/ntfy_alert.py --test          # 테스트 알림 1건 발송 후 종료
    python3 scripts/ntfy_alert.py --json out.json # 판정 결과를 JSON으로 남김
    python3 scripts/ntfy_alert.py --state .alert-state/state.json
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TOPIC_URL = "https://ntfy.sh/sond-coin-9842k"
APP_URL = "https://acesond.github.io/Sond-coin-app/"
KST = timezone(timedelta(hours=9))
USER_AGENT = "sond-coin-alert/1.0 (+https://github.com/acesond/Sond-coin-app)"
COOLDOWN_MIN = 60
AUTO1_NEAR_PCT = 0.8   # 자동 1 진입가 ±0.8% 이내면 타점 도달 (수작업 가설의 ±1.0%와 별개)

BN = "https://fapi.binance.com"
OKX = "https://www.okx.com"
BN_IV = {"1Dutc": "1d", "4H": "4h", "1H": "1h"}
OKX_BAR = {"1Dutc": "1Dutc", "4H": "4H", "1H": "1H"}
TF_LABEL = {"1Dutc": "1D", "4H": "4H", "1H": "1H"}

SYMS = [
    {"id": "BTCUSDT", "code": "BTC", "name": "비트코인", "dp": 1},
    {"id": "ETHUSDT", "code": "ETH", "name": "이더리움", "dp": 2},
    {"id": "SOLUSDT", "code": "SOL", "name": "솔라나", "dp": 2},
    {"id": "XRPUSDT", "code": "XRP", "name": "리플", "dp": 4},
    {"id": "BNBUSDT", "code": "BNB", "name": "바이낸스코인", "dp": 2},
    {"id": "DOGEUSDT", "code": "DOGE", "name": "도지코인", "dp": 5},
]
SYM_BY_ID = {s["id"]: s for s in SYMS}

HYP_DATA = {
  "HYP_VERSION": "2026-11-27-1000",
  "LEVELS": {
    "BTCUSDT": [
      {"p": 64570, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 11/23 4H 고점 64,572.8 (레그 시작점·1D EMA20 65,423.7 아래)"},
      {"p": 63000, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 하락 레그 0.786 되돌림 63,007.1"},
      {"p": 61850, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 0.618 되돌림 61,778.0 위 · 1H 종가면 폐기"},
      {"p": 61600, "side": "short", "role": "entry", "tag": "숏존 상단", "label": "숏존 상단 · 61,122 고점 위 0.8% (리테스트 상단)"},
      {"p": 61120, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 24시간 박스 상단 61,121.7 (0.5 되돌림 60,914.7 위·0.618 아래)"},
      {"p": 60500, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 박스 중간(24시간 횡보 중심)"},
      {"p": 59950, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 박스 하단 59,877.6·0.382 되돌림 60,051.3·4H EMA20 60,285.1 아래"},
      {"p": 59890, "side": "long", "role": "break", "tag": "숏 1차 목표", "label": "숏 1차 목표 · 박스 하단 59,877.6 (1H 종가 이탈 확인)"},
      {"p": 59250, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 박스 하단 아래 1.05%(1.5 ATR 1H) · 1H 종가면 폐기"},
      {"p": 58650, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 박스 높이(1,244) 투영 58,634 · 0.236 되돌림 58,983 아래"},
    ],
    "ETHUSDT": [
      {"p": 1845, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 11/23 4H 고점 1,845 (레그 시작점·1D EMA20 1,850.5 바로 아래)"},
      {"p": 1794, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 하락 레그 0.786 되돌림 1,794.3"},
      {"p": 1742, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 0.5 되돌림 1,726.5 위 · 1H 종가면 폐기"},
      {"p": 1730, "side": "short", "role": "entry", "tag": "숏존 상단", "label": "숏존 상단 · 박스 상단 위 1.1%"},
      {"p": 1712, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 24시간 박스 상단 1,711.89 (0.382 되돌림 1,698.5 위·4H EMA50 1,722.7 아래)"},
      {"p": 1700, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 0.382 되돌림 1,698.5 (숏존 시작)"},
      {"p": 1670, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 박스 하단 1,667.0·0.236 되돌림 1,663.9 위"},
      {"p": 1668, "side": "long", "role": "break", "tag": "숏 1차 목표", "label": "숏 1차 목표 · 박스 하단 1,667.0 (1H 종가 이탈 확인)"},
      {"p": 1634, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 0.236 되돌림 1,663.9 아래·박스 하단 -2.0% · 1H 종가면 폐기"},
      {"p": 1600, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · PCE 저점 1,608.0 아래 (1H 종가 확인)"},
    ],
    "SOLUSDT": [
      {"p": 76.5, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 1D EMA20 76.52 (11/23 고점 78.49 아래)"},
      {"p": 73.63, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 하락 레그 0.618 되돌림 73.63"},
      {"p": 72.55, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 0.5 되돌림 72.13 위 · 1H 종가면 폐기"},
      {"p": 72.3, "side": "short", "role": "entry", "tag": "숏존 상단", "label": "숏존 상단 · 박스 상단 위 0.7%"},
      {"p": 71.8, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 24시간 박스 상단 71.80 (4H EMA50 71.44 위·0.5 되돌림 72.13 아래)"},
      {"p": 70.76, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 박스 중간 (4H EMA20 70.46 위)"},
      {"p": 69.78, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 박스 하단 69.73·1H EMA20 70.93 아래"},
      {"p": 69.75, "side": "long", "role": "break", "tag": "숏 1차 목표", "label": "숏 1차 목표 · 박스 하단 69.73 (1H 종가 이탈 확인)"},
      {"p": 68.95, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 0.236 되돌림 68.77 위·박스 하단 -1.1% · 1H 종가면 폐기"},
      {"p": 67.9, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 박스 높이(2.07) 투영 67.66 (1H 종가 확인)"},
    ],
    "XRPUSDT": [
      {"p": 1.0259, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 11/23 고점 1.0259 (레그 시작점·1D EMA20 1.0044 위)"},
      {"p": 0.9964, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 하락 레그 0.786 되돌림 0.9964"},
      {"p": 0.9755, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 0.618 되돌림 0.9733 위 · 1H 종가면 폐기"},
      {"p": 0.97, "side": "short", "role": "entry", "tag": "숏존 상단", "label": "숏존 상단 · 박스 상단 위 0.7%"},
      {"p": 0.963, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 24시간 박스 상단 0.9634 (0.5 되돌림 0.9571 위·0.618 아래)"},
      {"p": 0.948, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 박스 중간 (4H EMA50 0.9461 부근)"},
      {"p": 0.9335, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "숏 1차 겸 눌림 롱 진입 · 박스 하단 0.9332 (4H EMA20 0.9383 아래)"},
      {"p": 0.9175, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 0.236 되돌림 0.9207 아래 · 1H 종가면 폐기"},
      {"p": 0.903, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 박스 높이(0.0302) 투영 0.9030 · 11/25 저점 0.8882 위"},
    ],
    "BNBUSDT": [
      {"p": 599.0, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 1D EMA20 599.19 (11/23 고점 587.49 위)"},
      {"p": 587.5, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 11/23 고점 587.49 (레그 시작점)"},
      {"p": 567.5, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 0.618 되돌림 564.25 위 · 1H 종가면 폐기"},
      {"p": 565.0, "side": "short", "role": "entry", "tag": "숏존 상단", "label": "숏존 상단 · 박스 상단 위 0.6%"},
      {"p": 561.5, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 24시간 박스 상단 561.57 (4H EMA50 561.93·0.5 되돌림 557.08 위)"},
      {"p": 553.0, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 박스 중간 (4H EMA20 551.93 위)"},
      {"p": 544.8, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "숏 1차 겸 눌림 롱 진입 · 박스 하단 544.51 (4H EMA20·0.382 549.9 아래)"},
      {"p": 537.5, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 0.236 되돌림 541.02 아래·박스 하단 -1.3% · 1H 종가면 폐기"},
      {"p": 526.5, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 11/25 저점 526.66 (1H 종가 확인)"},
    ],
    "DOGEUSDT": [
      {"p": 0.0602, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 11/23 고점 0.06022 (레그 시작점·1D EMA20 0.06096 아래)"},
      {"p": 0.0585, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 하락 레그 0.786 되돌림 0.05850"},
      {"p": 0.0575, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 0.618 되돌림 0.05714·박스 상단 0.05727 위 · 1H 종가면 폐기"},
      {"p": 0.05727, "side": "short", "role": "entry", "tag": "숏존 상단", "label": "숏존 상단 · 24시간 박스 상단 0.05727"},
      {"p": 0.0567, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 4H EMA50 0.05669·0.5 되돌림 0.05619 위 (숏존 하단)"},
      {"p": 0.05619, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 0.5 되돌림 0.05619 (숏존 시작)"},
      {"p": 0.0558, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 박스 하단 0.05576·4H EMA20 0.05592 아래"},
      {"p": 0.055, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 0.236 되돌림 0.05406 위·박스 하단 -1.4% · 1H 종가면 폐기"},
      {"p": 0.0543, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 박스 높이(0.00151) 투영 0.05425 (1H 종가 확인)"},
    ],
  },
  "HYP": {
    "BTCUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 61120, "stop": 61850, "t1": 59890, "t2": 57900},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 박스 하단 지지 롱", "tag": "서브", "entry": 59950, "stop": 59250, "t1": 61120, "t2": 63000},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 박스 상단 돌파 롱", "tag": "추세", "entry": 61850, "stop": 61120, "t1": 63000, "t2": 64570},
    },
    "ETHUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 1712, "stop": 1742, "t1": 1668, "t2": 1600},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 박스 하단 지지 롱", "tag": "서브", "entry": 1670, "stop": 1634, "t1": 1754, "t2": 1794},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 박스 상단 돌파 롱", "tag": "추세", "entry": 1742, "stop": 1712, "t1": 1794, "t2": 1845},
    },
    "SOLUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 71.8, "stop": 72.55, "t1": 69.75, "t2": 68.3},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 박스 하단 지지 롱", "tag": "서브", "entry": 69.78, "stop": 68.95, "t1": 71.8, "t2": 73.63},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 박스 상단 돌파 롱", "tag": "추세", "entry": 72.55, "stop": 71.8, "t1": 73.63, "t2": 76.5},
    },
    "XRPUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 0.963, "stop": 0.9755, "t1": 0.9335, "t2": 0.91},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 박스 하단 지지 롱", "tag": "서브", "entry": 0.9335, "stop": 0.9175, "t1": 0.963, "t2": 0.982},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 박스 상단 돌파 롱", "tag": "추세", "entry": 0.9755, "stop": 0.963, "t1": 0.9964, "t2": 1.0259},
    },
    "BNBUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 561.5, "stop": 567.5, "t1": 544.8, "t2": 532.0},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 박스 하단 지지 롱", "tag": "서브", "entry": 544.8, "stop": 537.5, "t1": 561.5, "t2": 574.5},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 박스 상단 돌파 롱", "tag": "추세", "entry": 567.5, "stop": 561.5, "t1": 587.5, "t2": 599.0},
    },
    "DOGEUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 0.0567, "stop": 0.0575, "t1": 0.0545, "t2": 0.0523},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 박스 하단 지지 롱", "tag": "서브", "entry": 0.0558, "stop": 0.055, "t1": 0.0572, "t2": 0.0595},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 박스 상단 돌파 롱", "tag": "추세", "entry": 0.0575, "stop": 0.0567, "t1": 0.0585, "t2": 0.0602},
    },
  },
  "ZONE_DEF": {
    "BTCUSDT": {"stop": 61850, "brkup": 61850, "brkupTop": 63000, "ext": 64570, "short": 61120, "shortTop": 61600, "mid": 60500, "long": 59950, "warnL": 59250, "brk1": 58650, "midLabel": "눌림 롱 대기 · 박스 상단 숏 대기 · 59,950 지지 감시"},
    "ETHUSDT": {"stop": 1742, "brkup": 1742, "brkupTop": 1794, "ext": 1845, "short": 1712, "shortTop": 1730, "mid": 1700, "long": 1670, "warnL": 1634, "brk1": 1600, "midLabel": "눌림 롱 대기 · 박스 상단 숏 대기 · 1,670 지지 감시"},
    "SOLUSDT": {"stop": 72.55, "brkup": 72.55, "brkupTop": 73.63, "ext": 76.5, "short": 71.8, "shortTop": 72.3, "mid": 70.76, "long": 69.78, "warnL": 68.95, "brk1": 67.9, "midLabel": "눌림 롱 대기 · 박스 상단 숏 대기 · 69.78 지지 감시"},
    "XRPUSDT": {"stop": 0.9755, "brkup": 0.9755, "brkupTop": 0.9964, "ext": 1.0259, "short": 0.963, "shortTop": 0.97, "mid": 0.948, "long": 0.9335, "warnL": 0.9175, "brk1": 0.903, "midLabel": "눌림 롱 대기 · 박스 상단 숏 대기 · 0.9335 지지 감시"},
    "BNBUSDT": {"stop": 567.5, "brkup": 567.5, "brkupTop": 587.5, "ext": 599.0, "short": 561.5, "shortTop": 565.0, "mid": 553.0, "long": 544.8, "warnL": 537.5, "brk1": 526.5, "midLabel": "눌림 롱 대기 · 박스 상단 숏 대기 · 544.8 지지 감시"},
    "DOGEUSDT": {"stop": 0.0575, "brkup": 0.0575, "brkupTop": 0.0585, "ext": 0.0602, "short": 0.0567, "shortTop": 0.05727, "mid": 0.05619, "long": 0.0558, "warnL": 0.055, "brk1": 0.0543, "midLabel": "눌림 롱 대기 · 박스 상단 숏 대기 · 0.0558 지지 감시"},
  },
}


# ---------------------------------------------------------------- 유틸
def is_num(v):
    return isinstance(v, (int, float)) and v == v and v not in (float("inf"), float("-inf"))


def now_kst():
    return datetime.now(KST)


def fmt_px(v, dp):
    if not is_num(v):
        return "—"
    return f"{v:,.{dp}f}"


def fmt_lv(v, dp):
    """가설·감시선 문구용 — 종목 소수점 안에서 자연스러운 자릿수만 남깁니다."""
    if not is_num(v):
        return "—"
    s = f"{v:.{dp}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    # 1,710 / 74.2 / 0.0573 처럼 천 단위 쉼표만 붙입니다
    ip, _, fp = s.partition(".")
    neg = ip.startswith("-")
    ip = ip.lstrip("-")
    ip = f"{int(ip):,}" if ip.isdigit() else ip
    return ("-" if neg else "") + ip + ("." + fp if fp else "")


def fmt_pct(v, d=2):
    if not is_num(v):
        return "—"
    return f"{v:+.{d}f}%"


def http_json(url, timeout=25, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 — 재시도 후 마지막 오류를 올립니다
            last = e
            time.sleep(0.8 + i * 1.2)
    raise last


# ---------------------------------------------------------------- 데이터
class Feed:
    """바이낸스 선물 우선, 451/차단/오류면 OKX로 폴백. 한 번 실패한 소스는 그 실행 동안 다시 쓰지 않습니다."""

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.binance_ok = True
        self.binance_why = ""
        self.used = set()

    def log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    # -- 바이낸스
    def _bn_candles(self, sym, bar, limit):
        iv = BN_IV[bar]
        d = http_json(f"{BN}/fapi/v1/klines?symbol={sym}&interval={iv}&limit={limit}")
        now_ms = int(time.time() * 1000)
        out = []
        for a in d:
            close_ms = int(a[6])
            out.append({"t": int(a[0]), "o": float(a[1]), "h": float(a[2]), "l": float(a[3]),
                        "c": float(a[4]), "v": float(a[5]), "conf": close_ms < now_ms})
        out.sort(key=lambda c: c["t"])
        return out

    def _bn_ticker(self, sym):
        d = http_json(f"{BN}/fapi/v1/ticker/24hr?symbol={sym}")
        o = d[0] if isinstance(d, list) else d
        return {"last": float(o["lastPrice"]), "open24h": float(o["openPrice"]),
                "high24h": float(o["highPrice"]), "low24h": float(o["lowPrice"]),
                "chg": float(o["priceChangePercent"]), "ts": int(o.get("closeTime") or 0)}

    # -- OKX
    def _okx_inst(self, sym):
        return sym.replace("USDT", "-USDT-SWAP")

    def _okx_candles(self, sym, bar, limit):
        inst = self._okx_inst(sym)
        d = http_json(f"{OKX}/api/v5/market/candles?instId={inst}&bar={OKX_BAR[bar]}&limit={min(limit, 300)}")
        if d.get("code") != "0":
            raise RuntimeError("OKX 오류 " + str(d.get("code")) + " " + str(d.get("msg")))
        out = []
        for a in reversed(d["data"]):  # OKX는 최신봉이 앞
            out.append({"t": int(a[0]), "o": float(a[1]), "h": float(a[2]), "l": float(a[3]),
                        "c": float(a[4]), "v": float(a[5]), "conf": str(a[8]) == "1"})
        return out

    def _okx_ticker(self, sym):
        inst = self._okx_inst(sym)
        d = http_json(f"{OKX}/api/v5/market/ticker?instId={inst}")
        if d.get("code") != "0" or not d.get("data"):
            raise RuntimeError("OKX 시세 오류 " + str(d.get("code")))
        o = d["data"][0]
        last, op = float(o["last"]), float(o["open24h"])
        return {"last": last, "open24h": op, "high24h": float(o["high24h"]), "low24h": float(o["low24h"]),
                "chg": (last - op) / op * 100 if op else 0.0, "ts": int(o["ts"])}

    # -- 공통 진입점
    def _binance_off(self, why):
        if self.binance_ok:
            self.binance_ok = False
            self.binance_why = why
            self.log(f"· 바이낸스 사용 불가({why}) → OKX 폴백")

    def candles(self, sym, bar, limit=200):
        if self.binance_ok:
            try:
                cs = self._bn_candles(sym, bar, limit)
                if len(cs) >= 60:
                    self.used.add("binance")
                    return cs
                raise RuntimeError(f"봉 부족 {len(cs)}")
            except Exception as e:  # noqa: BLE001
                self._binance_off(f"{sym} {bar}: {e}")
        self.used.add("okx")
        return self._okx_candles(sym, bar, limit)

    def ticker(self, sym):
        if self.binance_ok:
            try:
                t = self._bn_ticker(sym)
                self.used.add("binance")
                return t
            except Exception as e:  # noqa: BLE001
                self._binance_off(f"{sym} ticker: {e}")
        self.used.add("okx")
        return self._okx_ticker(sym)

    def name(self):
        if "binance" in self.used and "okx" in self.used:
            return "binance+okx"
        return "binance" if "binance" in self.used else "okx"


# ---------------------------------------------------------------- 지표 (index.html과 동일)
def rsi_series(closes, period=14):
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    g = l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            g += d
        else:
            l -= d
    g /= period
    l /= period
    out[period] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = (g * (period - 1) + max(d, 0)) / period
        l = (l * (period - 1) + max(-d, 0)) / period
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def ema_series(vals, period):
    out = [None] * len(vals)
    if len(vals) < period:
        return out
    k = 2 / (period + 1)
    s = sum(vals[:period]) / period
    out[period - 1] = s
    for i in range(period, len(vals)):
        s = vals[i] * k + s * (1 - k)
        out[i] = s
    return out


def swings(cs, lb=2, rb=2):
    highs, lows = [], []
    for i in range(lb, len(cs) - rb):
        is_h = is_l = True
        for j in range(i - lb, i + rb + 1):
            if j == i:
                continue
            if cs[j]["h"] >= cs[i]["h"]:
                is_h = False
            if cs[j]["l"] <= cs[i]["l"]:
                is_l = False
        if is_h:
            highs.append({"i": i, "p": cs[i]["h"]})
        if is_l:
            lows.append({"i": i, "p": cs[i]["l"]})
    return {"highs": highs, "lows": lows}


def last_leg(cs):
    sw = swings(cs, 2, 2)
    if not sw["highs"] or not sw["lows"]:
        return None
    h = sw["highs"][-1]
    l = sw["lows"][-1]
    up = l["i"] < h["i"]
    start = l if up else h
    end = h if up else l
    if end["i"] - start["i"] < 2 or end["p"] == start["p"]:
        return None
    span = abs(end["p"] - start["p"])

    def retr(v):
        return (end["p"] - v) / span if up else (v - end["p"]) / span

    def level(x):
        return end["p"] - span * x if up else end["p"] + span * x

    return {"up": up, "startP": start["p"], "endP": end["p"], "startI": start["i"], "endI": end["i"],
            "span": span, "retr": retr, "level": level}


def divergence(cs, rsi):
    sw = swings(cs, 2, 2)
    n = len(cs)
    close = cs[-1]["c"]
    bear = bull = stale_bear = stale_bull = None
    hs, ls = sw["highs"], sw["lows"]
    for k in range(len(hs) - 1, 0, -1):
        if bear:
            break
        b, a = hs[k], hs[k - 1]
        rb_, ra_ = rsi[b["i"]], rsi[a["i"]]
        if rb_ is None or ra_ is None:
            continue
        ago = n - 1 - b["i"]
        if ago > 30:
            continue
        if b["p"] > a["p"] * 1.0005 and rb_ < ra_ - 0.3 and rb_ >= 48:
            o = {"barsAgo": ago, "pa": a["p"], "pb": b["p"], "ra": ra_, "rb": rb_}
            if close <= b["p"] * 1.003:
                bear = o
            else:
                stale_bear = o
    for k in range(len(ls) - 1, 0, -1):
        if bull:
            break
        b, a = ls[k], ls[k - 1]
        rb_, ra_ = rsi[b["i"]], rsi[a["i"]]
        if rb_ is None or ra_ is None:
            continue
        ago = n - 1 - b["i"]
        if ago > 30:
            continue
        if b["p"] < a["p"] * 0.9995 and rb_ > ra_ + 0.3 and rb_ <= 52:
            o = {"barsAgo": ago, "pa": a["p"], "pb": b["p"], "ra": ra_, "rb": rb_}
            if close >= b["p"] * 0.997:
                bull = o
            else:
                stale_bull = o
    return {"bear": bear, "bull": bull, "staleBear": stale_bear, "staleBull": stale_bull}


def tf_analysis(bar, candles, price):
    cs = candles.get(bar) or []
    o = {"bar": bar, "label": TF_LABEL[bar], "ok": False}
    if len(cs) < 60:
        return o
    closes = [c["c"] for c in cs]
    rsi = rsi_series(closes, 14)
    e20 = ema_series(closes, 20)
    e50 = ema_series(closes, 50)
    o["rsi"] = rsi
    o["rsiNow"] = rsi[-1]
    o["ema20"] = e20[-1]
    o["ema50"] = e50[-1]
    o["trend"] = "mixed"
    if is_num(price) and is_num(o["ema20"]) and is_num(o["ema50"]):
        if price < o["ema20"] < o["ema50"]:
            o["trend"] = "down"
        elif price > o["ema20"] > o["ema50"]:
            o["trend"] = "up"
    o["div"] = divergence(cs, rsi)
    o["leg"] = last_leg(cs)
    o["cs"] = cs
    o["ok"] = True
    return o


def swing_levels(price, max_each, candles_4h):
    cs = (candles_4h or [])[-160:]
    if len(cs) < 30 or not is_num(price):
        return []
    sw = swings(cs, 2, 2)
    raw = sorted([x["p"] for x in sw["highs"]] + [x["p"] for x in sw["lows"]], reverse=True)
    uniq = []
    for v in raw:
        if not any(abs(u - v) / v < 0.0025 for u in uniq):
            uniq.append(v)
    n = max_each or 4
    above = list(reversed([v for v in uniq if v > price][-n:]))
    below = [v for v in uniq if v < price][:n]
    return ([{"p": v, "side": "short", "role": "swing", "label": "4H 스윙 저항"} for v in above]
            + [{"p": v, "side": "long", "role": "swing", "label": "4H 스윙 지지"} for v in below])


def levels_for(sym, price, candles_4h):
    fixed = HYP_DATA["LEVELS"].get(sym)
    sw = swing_levels(price, 4, candles_4h)
    if fixed:
        return [dict(l) for l in fixed] + sw
    return sw


def zone_state(price, sym):
    z = HYP_DATA["ZONE_DEF"].get(sym)
    dp = SYM_BY_ID[sym]["dp"]
    if not is_num(price) or price <= 0:
        return {"code": "none", "text": "데이터 대기 중"}
    if not z:
        return {"code": "other", "text": "가설 미적용 — 4H 스윙 라인 기준으로 판단"}
    f = lambda n: fmt_lv(n, dp)  # noqa: E731
    if price >= z["stop"]:
        return {"code": "void", "text": "가설 1 폐기 구간 — 숏 손절 " + f(z["stop"]) + " 상회"}
    if price >= z["brkup"]:
        return {"code": "brkup", "text": "돌파 롱 감시 구간 (" + f(z["brkup"]) + " ~ " + f(z["brkupTop"]) + ") — 1H 확정 종가 · " + f(z["ext"]) + " 확장"}
    if price >= z["short"]:
        return {"code": "short", "text": "가설 1 숏 진입 구간 (" + f(z["short"]) + " ~ " + f(z["shortTop"]) + ")"}
    if price > z["mid"]:
        return {"code": "mid", "text": (z.get("midLabel") or "숏 진입 대기 · 눌림목 롱 대기") + " (" + f(z["mid"]) + " ~ " + f(z["short"]) + ")"}
    if price > z["long"]:
        return {"code": "long", "text": "가설 2 눌림목 롱 구간 (" + f(z["long"]) + " ~ " + f(z["mid"]) + ")"}
    if price > z["warnL"]:
        return {"code": "warnL", "text": "롱 손절 바로 위 (" + f(z["warnL"]) + " ~ " + f(z["long"]) + ") — 신규 진입 금지"}
    if price > z["brk1"]:
        return {"code": "brk1", "text": "하방 이탈 경계 위 (" + f(z["brk1"]) + " ~ " + f(z["warnL"]) + ") — 종가 확인 대기"}
    return {"code": "brk2", "text": "하방 이탈 진행 (" + f(z["brk1"]) + " 이하) — 반등 확인 전 추격 금지"}


# ---------------------------------------------------------------- NEoWave 참고(판정에는 미반영)
def calc_atr(cs, period=14):
    out = [None] * len(cs)
    if len(cs) <= period:
        return out
    tr = [None]
    for i in range(1, len(cs)):
        pc = cs[i - 1]["c"]
        tr.append(max(cs[i]["h"] - cs[i]["l"], abs(cs[i]["h"] - pc), abs(cs[i]["l"] - pc)))
    atr = sum(tr[1:period + 1]) / period
    out[period] = atr
    for i in range(period + 1, len(cs)):
        atr = (atr * (period - 1) + tr[i]) / period
        out[i] = atr
    return out


def extract_monowaves(cs, atr):
    n = len(cs)
    if n < 20 or not (is_num(atr) and atr > 0):
        return []
    thr = atr * 2.5
    pivots = [{"idx": 0, "price": cs[0]["c"]}]
    direction, ext, ext_i = 0, cs[0]["c"], 0
    for i in range(1, n):
        hi, lo = cs[i]["h"], cs[i]["l"]
        if direction == 0:
            if hi - cs[0]["c"] >= thr:
                direction, ext, ext_i = 1, hi, i
            elif cs[0]["c"] - lo >= thr:
                direction, ext, ext_i = -1, lo, i
        elif direction == 1:
            if hi > ext:
                ext, ext_i = hi, i
            elif ext - lo >= thr:
                pivots.append({"idx": ext_i, "price": ext})
                direction, ext, ext_i = -1, lo, i
        else:
            if lo < ext:
                ext, ext_i = lo, i
            elif hi - ext >= thr:
                pivots.append({"idx": ext_i, "price": ext})
                direction, ext, ext_i = 1, hi, i
    if direction != 0 and ext_i > pivots[-1]["idx"]:
        pivots.append({"idx": ext_i, "price": ext})
    if pivots[-1]["idx"] < n - 1:
        pivots.append({"idx": n - 1, "price": cs[n - 1]["c"]})
    waves = []
    for i in range(1, len(pivots)):
        p1, p2 = pivots[i - 1], pivots[i]
        ln = abs(p2["price"] - p1["price"])
        bars = max(1, p2["idx"] - p1["idx"])
        waves.append({"id": f"m{i}", "len": ln, "bars": bars, "slope": ln / bars,
                      "dir": 1 if p2["price"] >= p1["price"] else -1,
                      "startPrice": p1["price"], "endPrice": p2["price"],
                      "startIdx": p1["idx"], "endIdx": p2["idx"]})
    return waves


def neowave_reduce_hint(waves):
    """웹앱 neowaveHint가 level='reduce'인 경우의 사유만 뽑습니다."""
    if not waves or len(waves) < 2:
        return None
    last, prev = waves[-1], waves[-2]
    retr = (last["len"] / prev["len"] * 100) if prev["len"] > 0 else 0.0
    ratio = (last["bars"] / prev["bars"] * 100) if prev["bars"] > 0 else 0.0
    if retr < 38.2:
        group = "impulse"
    elif retr <= 61.8:
        group = "standard"
    elif retr <= 100:
        group = "complex"
    else:
        group = "reversal"
    time_long = ratio > 150
    overlap = violated = False
    integ = ""
    if len(waves) >= 5:
        w1, w2, w3, w4, w5 = waves[-5], waves[-4], waves[-3], waves[-2], waves[-1]
        overlap = (w4["endPrice"] < w1["endPrice"]) if w1["dir"] == 1 else (w4["endPrice"] > w1["endPrice"])
        if w2["len"] > w1["len"]:
            violated, integ = True, "2파 규칙 위반"
        elif overlap:
            integ = "1·4파 겹침"
        elif w3["len"] < w1["len"] and w3["len"] < w5["len"]:
            violated, integ = True, "3파 최단 위반"
    complex_adj = group in ("complex", "reversal")
    if not (overlap or violated or complex_adj or time_long):
        return None
    why = []
    if overlap:
        why.append("1·4파 겹침")
    if violated:
        why.append(integ)
    if complex_adj:
        why.append(f"되돌림 {retr:.1f}% 깊은 조정")
    if time_long:
        why.append(f"시간 {ratio:.0f}% 연장")
    return " · ".join(why)


# ---------------------------------------------------------------- 자동 1 · 4H 모노웨이브 추세 재개
# 웹앱 index.html의 autoHypotheses() 후보 1(a1)을 그대로 옮겼습니다.
#   직전에 완성된 4H 모노웨이브 m1의 방향으로 재개를 노리는 자리 — 0.5 → 0.618 → 0.786
#   되돌림 중 아직 닿지 않은 가장 얕은 자리가 진입가입니다. 파동 무효선은 m1 시작점(100% 되돌림).
#   판정(3중 점검)에는 반영되지 않는 참고 후보라, 알림 본문에도 그 사실을 적습니다.
def auto1_candidate(sym, price, candles):
    cs = (candles or {}).get("4H") or []
    if len(cs) < 60:
        return {"ok": False, "why": "4H 캔들 부족"}
    if not is_num(price) or price <= 0:
        return {"ok": False, "why": "현재가 없음"}
    atr = calc_atr(cs, 14)[-1]
    if not is_num(atr) or atr <= 0:
        atr = cs[-1]["c"] * 0.005
    waves = extract_monowaves(cs, atr)
    if len(waves) < 3:
        return {"ok": False, "why": f"4H 모노웨이브 {len(waves)}개 — 3개 미만", "atr": atr}
    m1 = waves[-2]                       # 직전에 완성된 모노웨이브
    d1 = m1["dir"]
    side = "long" if d1 > 0 else "short"

    def lvl(r):                          # m1을 r만큼 되돌린 가격
        return m1["endPrice"] - d1 * m1["len"] * r

    margin = 0.15 * atr
    pick = next((r for r in (0.5, 0.618, 0.786) if (price - lvl(r)) * d1 > margin), None)
    r = 0.786 if pick is None else pick
    entry = lvl(r)
    stop = (m1["startPrice"] if r == 0.786 else lvl(0.786)) - d1 * 0.2 * atr
    voided = (price - m1["startPrice"]) * d1 <= 0     # 100% 되돌림 넘으면 파동 무효
    t1 = m1["endPrice"]                                  # 1차 = 직전 극값
    t2 = m1["startPrice"] + d1 * m1["len"] * 1.618     # 2차 = m1 길이 1.618배 확장
    gap = (price - entry) / entry * 100 if entry else None
    near = bool(is_num(gap) and abs(gap) <= AUTO1_NEAR_PCT and not voided)
    risk = abs(entry - stop)
    return {
        "ok": True, "sym": sym, "side": side, "dir": d1, "r": r,
        "entry": entry, "stop": stop, "t1": t1, "t2": t2,
        "rr1": (abs(t1 - entry) / risk if risk else None),
        "rr2": (abs(t2 - entry) / risk if risk else None),
        "atr": atr, "voided": bool(voided), "weak": pick is None,
        "gapPct": gap, "near": near, "price": price, "waves": len(waves),
        "m1": {"id": m1["id"], "len": m1["len"], "bars": m1["bars"], "dir": d1,
               "startPrice": m1["startPrice"], "endPrice": m1["endPrice"]},
    }


def auto1_refs(candles, price):
    """자동 1 알림 본문의 참고 메모 — 1D·4H·1H 배열/RSI와 1H NEoWave 경고."""
    out = {"rsi": {}, "trend": {}, "nwRef": None}
    for bar in ("1Dutc", "4H", "1H"):
        cs = (candles or {}).get(bar) or []
        if len(cs) < 60:
            continue
        closes = [c["c"] for c in cs]
        rsi = rsi_series(closes, 14)
        e20 = ema_series(closes, 20)[-1]
        e50 = ema_series(closes, 50)[-1]
        p_ = price if is_num(price) else closes[-1]
        trend = "mixed"
        if is_num(e20) and is_num(e50):
            if p_ < e20 < e50:
                trend = "down"
            elif p_ > e20 > e50:
                trend = "up"
        out["rsi"][TF_LABEL[bar]] = rsi[-1]
        out["trend"][TF_LABEL[bar]] = trend
        if bar == "1H":
            try:
                atr = calc_atr(cs, 14)[-1]
                if not is_num(atr) or atr <= 0:
                    atr = cs[-1]["c"] * 0.005
                hint = neowave_reduce_hint(extract_monowaves(cs, atr))
                if hint:
                    out["nwRef"] = hint
            except Exception:  # noqa: BLE001 — 참고 문구라 실패해도 알림은 그대로
                pass
    return out


# ---------------------------------------------------------------- 3중 점검

# 가설 진입 구간 실제 일치 — 현재가가 그 방향 가설의 진입 구간 안인가.
# 요청(2026-11-26): 「타점 도달(3/3)」은 근거가 겹쳐도 현재가가 그 가설의 진입 구간에
# 실제로 들어와 있을 때만 성립합니다. 진입가에서 1.0% 넘게 떨어져 있으면 3/3이어도
# 타점 도달로 승격하지 않고 「대기(진입가와 X% 차이)」로 남깁니다.
# 진입 구간 = 가설 진입가 기준 ±1.0% (숏·롱·돌파 모두).
ZONE_MATCH_TOL = 1.0   # 진입가 기준 허용 갭 (%)


def hyp_zone_match(side, price, sym):
    h = HYP_DATA["HYP"].get(sym) or {}
    if not is_num(price) or price <= 0:
        return {"inZone": False, "entry": None, "slot": None, "gapPct": None}
    pick = None
    for slot in ("h1", "h2", "br"):
        hy = h.get(slot)
        if not hy or hy.get("kind") != side:
            continue
        entry = hy.get("entry")
        if not is_num(entry) or entry <= 0:
            continue
        gap_pct = (price - entry) / entry * 100
        in_zone = abs(gap_pct) <= ZONE_MATCH_TOL
        cand = {"inZone": in_zone, "entry": entry, "slot": slot, "gapPct": gap_pct}
        if pick is None:
            pick = cand
        elif ((cand["inZone"] and not pick["inZone"])
              or (cand["inZone"] == pick["inZone"] and abs(gap_pct) < abs(pick["gapPct"]))):
            pick = cand
    return pick or {"inZone": False, "entry": None, "slot": None, "gapPct": None}


def build_analysis(sym, price, candles):
    tfs = {bar: tf_analysis(bar, candles, price) for bar in ("1Dutc", "4H", "1H")}
    if not all(tfs[b]["ok"] for b in tfs):
        return None
    levels = levels_for(sym, price, candles.get("4H"))
    zone = zone_state(price, sym)
    leg4 = tfs["4H"]["leg"]

    with_dist = [dict(l, d=(l["p"] - price) / price * 100) for l in levels if is_num(l["p"])]
    shorts = sorted([x for x in with_dist if x["side"] == "short"], key=lambda x: abs(x["d"]))
    longs = sorted([x for x in with_dist if x["side"] == "long"], key=lambda x: abs(x["d"]))
    near_short = shorts[0] if shorts else None
    near_long = longs[0] if longs else None

    zz0 = HYP_DATA["ZONE_DEF"].get(sym)
    z_tol = price * 0.0009
    zs_lo = min(zz0["short"], zz0["shortTop"]) if zz0 else None
    zs_hi = max(zz0["short"], zz0["shortTop"]) if zz0 else None
    zl_lo = min(zz0["long"], zz0["mid"]) if zz0 else None
    zl_hi = max(zz0["long"], zz0["mid"]) if zz0 else None
    fib_short = bool(leg4 and not leg4["up"] and 0.45 <= leg4["retr"](price) <= 0.68)
    fib_long = bool(leg4 and leg4["up"] and 0.45 <= leg4["retr"](price) <= 0.68)
    in_z_short = bool(is_num(zs_lo) and zs_hi > zs_lo and zs_lo - z_tol <= price <= zs_hi + z_tol)
    in_z_long = bool(is_num(zl_lo) and zl_hi > zl_lo and zl_lo - z_tol <= price <= zl_hi + z_tol)
    wave_short = fib_short or in_z_short
    wave_long = fib_long or in_z_long

    line_short = bool(near_short and abs(near_short["d"]) <= 0.6)
    line_long = bool(near_long and abs(near_long["d"]) <= 0.6)

    div_short = bool(tfs["4H"]["div"]["bear"] or tfs["1H"]["div"]["bear"])
    div_long = bool(tfs["4H"]["div"]["bull"] or tfs["1H"]["div"]["bull"])

    def same_lvl(wave, line, near, in_z, fib):
        return bool(wave and line and near and near.get("role") == "entry"
                    and (in_z or (fib and "되돌림" in (near.get("label") or ""))))

    dup_short = same_lvl(wave_short, line_short, near_short, in_z_short, fib_short)
    dup_long = same_lvl(wave_long, line_long, near_long, in_z_long, fib_long)
    line_short_ind = line_short and not dup_short
    line_long_ind = line_long and not dup_long
    n_s = sum(1 for x in (wave_short, line_short_ind, div_short) if x)
    n_l = sum(1 for x in (wave_long, line_long_ind, div_long) if x)
    # 판정 방향 — 현재가가 실제로 들어와 있는 가설을 먼저 봅니다
    #   (숏 구간 안에서 ‘롱 타점 도달’ 제목 + ‘숏 진입 구간’ 부제가 겹치지 않도록)
    zone_s = hyp_zone_match("short", price, sym)
    zone_l = hyp_zone_match("long", price, sym)
    ev_of = lambda s: n_s if s == "short" else n_l  # noqa: E731
    if n_s > n_l:
        side = "short"
    elif n_l > n_s:
        side = "long"
    else:
        side = "long" if tfs["4H"]["trend"] == "up" else "short"
    if zone_s["inZone"] and not zone_l["inZone"]:
        z_side = "short"
    elif zone_l["inZone"] and not zone_s["inZone"]:
        z_side = "long"
    else:
        z_side = None
    if z_side and z_side != side and ev_of(z_side) >= 1:
        side = z_side

    best = ev_of(side)                       # 판정 방향의 근거 개수 (반대 방향은 참고)
    z_side_m = zone_s if side == "short" else zone_l
    zone_hit = best >= 3 and z_side_m["inZone"]   # 실제 진입 구간 일치가 확인된 3/3만 타점
    # 참고 정보 — 판정을 깎지 않습니다.
    # 3/3이면 폐기·이탈이 아닌 한 ‘타점 도달’(매억남 기본)이고, NEoWave·1D 역추세는 본문 참고 줄로만.
    nw_ref = None
    trend_ref = None
    if best >= 3:
        try:
            cs1 = tfs["1H"]["cs"]
            atr = calc_atr(cs1, 14)[-1]
            if not is_num(atr) or atr <= 0:
                atr = cs1[-1]["c"] * 0.005
            hint = neowave_reduce_hint(extract_monowaves(cs1, atr))
            if hint:
                nw_ref = "파동 겹침/조정 구간 — " + hint
        except Exception:  # noqa: BLE001 — 참고 문구라 실패해도 판정은 그대로
            pass
        d1 = tfs["1Dutc"]["trend"]
        if (side == "long" and d1 == "down") or (side == "short" and d1 == "up"):
            trend_ref = ("1D " + ("하락" if d1 == "down" else "상승") + " 배열 — 역추세 "
                         + ("롱" if side == "long" else "숏") + ", 비중만 조절")

    if zone_hit:
        label, cls = "타점 도달", ("bad" if side == "short" else "long")
    elif best >= 3:
        # 근거 3/3이어도 현재가가 진입 구간 밖 — 타점 도달로 승격하지 않습니다
        gap_txt = (f" (진입가 {abs(z_side_m['gapPct']):.2f}% 차이)"
                   if z_side_m.get("gapPct") is not None else "")
        label, cls = ("숏 대기" if side == "short" else "롱 대기") + " — 3/3 구간 밖" + gap_txt, ("bad" if side == "short" else "long")
    elif best == 2:
        label, cls = ("숏 대기" if side == "short" else "롱 대기"), ("bad" if side == "short" else "long")
    elif best == 1:
        label, cls = "관망", "warn"
    else:
        label, cls = "관망", "neutral"
    if zone["code"] == "void":
        label, cls = "폐기", "warn"
    if zone["code"] == "brk2" and n_s >= 2:
        label, cls = "이탈", "bad"

    return {
        "sym": sym,
        "price": price,
        "side": side,
        "nS": n_s,
        "nL": n_l,
        "checks": {
            "short": {"wave": wave_short, "line": line_short_ind, "div": div_short,
                      "fib": fib_short, "inZone": in_z_short, "dup": dup_short},
            "long": {"wave": wave_long, "line": line_long_ind, "div": div_long,
                     "fib": fib_long, "inZone": in_z_long, "dup": dup_long},
        },
        "nearShort": near_short,
        "nearLong": near_long,
        "zShort": [zs_lo, zs_hi],
        "zLong": [zl_lo, zl_hi],
        "zone": zone,
        "leg4": {"up": leg4["up"], "startP": leg4["startP"], "endP": leg4["endP"],
                 "retr": leg4["retr"](price) if leg4 else None,
                 "l50": leg4["level"](0.5) if leg4 else None,
                 "l618": leg4["level"](0.618) if leg4 else None} if leg4 else None,
        "rsi": {"1D": tfs["1Dutc"]["rsiNow"], "4H": tfs["4H"]["rsiNow"], "1H": tfs["1H"]["rsiNow"]},
        "trend": {"1D": tfs["1Dutc"]["trend"], "4H": tfs["4H"]["trend"], "1H": tfs["1H"]["trend"]},
        "label": label,
        "cls": cls,
        "best": best,
        "zoneHit": zone_hit,
        "zoneEntry": z_side_m.get("entry"),
        "zoneGap": z_side_m.get("gapPct"),
        "nwRef": nw_ref,
        "trendRef": trend_ref,
        "alertable": best >= 3 and zone_hit and label == "타점 도달",
    }


# ---------------------------------------------------------------- ntfy
def rfc2047(s):
    """ntfy는 HTTP 헤더 UTF-8을 지원하지만 urllib은 헤더를 latin-1로 인코딩합니다.
    한글 제목은 RFC 2047 base64 인코딩 단어로 보내야 전송되고, 앱에서는 한글로 풀려 보입니다."""
    if s.isascii():
        return s
    return "=?UTF-8?B?" + base64.b64encode(s.encode("utf-8")).decode("ascii") + "?="


def send_ntfy(title, body, click=APP_URL, priority="high", tags="chart_with_upwards_trend,bell",
              dry_run=False):
    headers = {
        "Title": rfc2047(title),
        "Priority": priority,
        "Tags": tags,
        "Click": click,
        "User-Agent": USER_AGENT,
        "Content-Type": "text/plain; charset=utf-8",
    }
    token = os.environ.get("NTFY_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    data = body.encode("utf-8")
    if dry_run:
        print("[dry-run] POST " + TOPIC_URL)
        print("[dry-run] headers: " + json.dumps({k: v for k, v in headers.items() if k != "Authorization"}, ensure_ascii=False))
        print("[dry-run] body:\n" + body)
        return {"dry_run": True}
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(TOPIC_URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                txt = r.read().decode("utf-8", "replace")
                return {"status": r.status, "body": txt[:400]}
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1 + i * 2)
    raise RuntimeError(f"ntfy 발송 실패: {last}")


def alert_body(a, sym_meta, tk):
    dp = sym_meta["dp"]
    p = lambda n: fmt_lv(n, dp)  # noqa: E731
    side_kr = "숏" if a["side"] == "short" else "롱"
    chk = a["checks"][a["side"]]
    h = HYP_DATA["HYP"][a["sym"]]
    hyp = None
    # 점검 기준 가설 — 같은 방향 가설 중 진입가가 가장 가까운 것
    for k in ("h1", "h2", "br"):
        if h[k]["kind"] == a["side"]:
            if hyp is None or abs(h[k]["entry"] - a["price"]) < abs(hyp["entry"] - a["price"]):
                hyp = h[k]
    rr = ""
    if hyp:
        risk = abs(hyp["entry"] - hyp["stop"])
        rr = f" · 손익비 {abs(hyp['t1'] - hyp['entry']) / risk:.2f}:1" if risk else ""

    lines = []
    lines.append(f"{sym_meta['code']} {sym_meta['name']} · {side_kr} 근거 {a['best']}/3 — {a['label']}")
    if tk:
        lines.append(f"현재가 {fmt_px(a['price'], dp)} (24h {fmt_pct(tk['chg'])})  ·  {now_kst():%m/%d %H:%M} KST")
    else:
        lines.append(f"현재가 {fmt_px(a['price'], dp)}  ·  {now_kst():%m/%d %H:%M} KST")
    lines.append("")
    mark = lambda b: "✓" if b else "✗"  # noqa: E731
    zlo, zhi = (a["zShort"] if a["side"] == "short" else a["zLong"]) or (None, None)
    zone_name = "숏 핵심 존" if a["side"] == "short" else "눌림 롱 핵심 존"
    fib_txt = ""
    if a["leg4"]:
        fib_txt = (f"4H 레그 {p(a['leg4']['startP'])}→{p(a['leg4']['endP'])} "
                   f"되돌림 {a['leg4']['retr'] * 100:.0f}%")
    if chk["wave"]:
        if chk["fib"] and chk["inZone"]:
            desc = f"{fib_txt} · {zone_name} {p(zlo)}~{p(zhi)} 안"
        elif chk["fib"]:
            desc = fib_txt + " (45~68% 되돌림 구간)"
        else:
            desc = f"{zone_name} {p(zlo)}~{p(zhi)} 안 — 리테스트 자리"
    else:
        if a["leg4"]:
            desc = f"4H 되돌림 {a['leg4']['retr'] * 100:.0f}% — 45~68% 밖 · {zone_name} {p(zlo)}~{p(zhi)} 밖"
        else:
            desc = "4H 레그 없음"
    lines.append(f"① 자리 {mark(chk['wave'])} — {desc}")
    near = a["nearShort"] if a["side"] == "short" else a["nearLong"]
    if chk["line"] and near:
        lines.append(f"② 라인 {mark(True)} — {near['label']} {p(near['p'])} 까지 {fmt_pct(near['d'])}")
    elif chk["dup"]:
        lines.append(f"② 라인 ✗ — ①과 같은 숫자({p(near['p']) if near else '—'})라 1개로 셈")
    elif near:
        lines.append(f"② 라인 {mark(False)} — 가장 가까운 라인 {near['label']} {p(near['p'])} {fmt_pct(near['d'])} (0.6% 밖)")
    else:
        lines.append("② 라인 ✗ — 근처 라인 없음")
    lines.append(f"③ 다이버전스 {mark(chk['div'])} — " + ("1H·4H " + ("하락" if a["side"] == "short" else "상승") + " 다이버전스" if chk["div"] else "1H·4H 다이버전스 없음"))
    lines.append("")
    if hyp:
        lines.append(f"기준 가설 · {hyp['title']} ({hyp['tag']})")
        lines.append(f"진입 {p(hyp['entry'])} · 손절 {p(hyp['stop'])} · 1차 {p(hyp['t1'])} · 2차 {p(hyp['t2'])}{rr}")
    rsi = a["rsi"]
    lines.append("RSI 1D {0:.1f} · 4H {1:.1f} · 1H {2:.1f}".format(rsi["1D"], rsi["4H"], rsi["1H"]))
    lines.append("자리 — " + a["zone"]["text"])
    if a.get("trendRef"):
        lines.append("📅 " + a["trendRef"] + " — 판정은 그대로, 비중만 조절")
    if a.get("nwRef"):
        lines.append("🌊 NEoWave 참고: " + a["nwRef"] + " — 판정은 3중 점검 기준")
    lines.append("")
    lines.append("⏳ 1H 봉 마감(정각) 확인 후 진입 판단 — 이 알림은 분석 참고용이고 주문은 실행하지 않습니다.")
    return "\n".join(lines)


def alert_title(a, sym_meta):
    """ntfy Title은 ASCII로만 — 한글 본문과 섞이지 않게 헤더는 영문으로 보냅니다."""
    side = "SHORT" if a["side"] == "short" else "LONG"
    return f"{sym_meta['code']} {side} {a['best']}/3 - Sond coin"


def auto1_title(a, sym_meta):
    """자동 1 알림 제목 — 수작업 3중 점검 알림과 한눈에 구분되도록 [자동 1]을 붙입니다.
    한글 제목은 send_ntfy가 RFC 2047로 인코딩해 보냅니다."""
    side = "SHORT" if a["side"] == "short" else "LONG"
    return f"[자동 1] {sym_meta['code']} {side} 타점 도달"


def auto1_body(a, sym_meta, tk, refs):
    dp = sym_meta["dp"]
    p = lambda n: fmt_lv(n, dp)  # noqa: E731
    px = lambda n: fmt_px(n, dp)  # noqa: E731
    side_kr = "숏" if a["side"] == "short" else "롱"
    side_en = "SHORT" if a["side"] == "short" else "LONG"
    m1 = a["m1"]
    refs = refs or {}
    r_pct = f"{a['r'] * 100:.1f}%"

    lines = []
    lines.append(f"[자동 1] {sym_meta['code']} {side_en} 타점 도달 — 4H {m1['id']} 추세 재개 ({side_kr})")
    if tk:
        lines.append(f"{sym_meta['code']} {sym_meta['name']} · 현재가 {px(a['price'])} (24h {fmt_pct(tk['chg'])})  ·  {now_kst():%m/%d %H:%M} KST")
    else:
        lines.append(f"{sym_meta['code']} {sym_meta['name']} · 현재가 {px(a['price'])}  ·  {now_kst():%m/%d %H:%M} KST")
    lines.append("")
    lines.append(f"진입 {p(a['entry'])} ({r_pct} 되돌림) — 현재가 {a['gapPct']:+.2f}% 차이")
    rr = ""
    if is_num(a.get("rr1")):
        rr += f" · 손익비 1차 {a['rr1']:.2f}:1"
    if is_num(a.get("rr2")):
        rr += f" · 2차 {a['rr2']:.2f}:1"
    lines.append(f"손절 {p(a['stop'])} · 1차 목표 {p(a['t1'])} · 2차 {p(a['t2'])}{rr}")
    lines.append("")
    lines.append(f"파동 — 4H {m1['id']} {side_kr} {p(m1['startPrice'])} → {p(m1['endPrice'])} "
                 f"(길이 {p(m1['len'])}, {m1['bars']}봉) 를 {r_pct} 되돌린 자리 · 무효선 {p(m1['startPrice'])}")

    # 단기 반등·추세 참고 메모
    trend = refs.get("trend") or {}
    rsi = refs.get("rsi") or {}
    t1h = trend.get("1H")
    want = "up" if a["side"] == "long" else "down"
    memo = {"up": "1H 상승 배열", "down": "1H 하락 배열"}.get(t1h, "1H 혼조")
    if t1h == want:
        memo += " · 단기 추세 같은 방향"
    elif t1h in ("up", "down"):
        memo += " · 단기 역방향이라 되돌림 더 깊을 수 있음"
    rsi_txt = " · ".join(f"{k} {rsi[k]:.1f}" for k in ("1D", "4H", "1H") if is_num(rsi.get(k)))
    lines.append("참고 — " + memo + ((" · RSI " + rsi_txt) if rsi_txt else ""))
    d1t = trend.get("1D")
    if (a["side"] == "long" and d1t == "down") or (a["side"] == "short" and d1t == "up"):
        lines.append("📅 1D " + ("하락" if d1t == "down" else "상승") + " 배열 — 역추세 " + side_kr + ", 비중만 조절")
    if refs.get("nwRef"):
        lines.append("🌊 NEoWave 참고: " + refs["nwRef"] + " — 자동 후보 계산은 그대로")
    if a.get("weak"):
        lines.append("⚠️ 되돌림 78.6% 초과 — 재개 근거 약함(웹앱과 같은 태그)")

    lines.append("")
    lines.append("⏳ 자동 1은 수작업 가설·3중 점검 판정과 별개로, 지금 4H 캔들에서 다시 계산한 참고 후보입니다.")
    lines.append("   1H 봉 마감(정각) 확인 후 진입 판단 — 이 알림은 분석 참고용이고 주문은 실행하지 않습니다.")
    return "\n".join(lines)


# ---------------------------------------------------------------- 상태(쿨다운)
def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict):
            st.setdefault("alerts", {})
            return st
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"· 상태 파일을 읽지 못했습니다({e}) — 새로 시작")
    return {"version": 1, "alerts": {}}


def save_state(path, st):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def in_cooldown(st, key, now_ts, minutes):
    rec = st.get("alerts", {}).get(key)
    if not rec:
        return 0.0
    try:
        left = minutes - (now_ts - float(rec.get("ts", 0))) / 60.0
    except Exception:  # noqa: BLE001
        return 0.0
    return max(0.0, left)


# ---------------------------------------------------------------- 실행
def write_summary(results, sent, source, feed, sent_auto=None):
    """GitHub Actions 실행 요약(GITHUB_STEP_SUMMARY)에 한 줄씩 남깁니다."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["### 코인 3중 점검 스캔", "",
             f"- {now_kst():%Y-%m-%d %H:%M} KST · 데이터 {source}" +
             (f" (바이낸스 차단: {feed.binance_why})" if feed.binance_why else ""), "",
             "| 종목 | 현재가 | 숏 | 롱 | 판정 | 자동 1 |", "|---|---|---|---|---|---|"]
    for a in results:
        meta = SYM_BY_ID.get(a.get("sym"), {"dp": 2})
        if a.get("error"):
            lines.append(f"| {a.get('sym')} | — | — | — | 조회 실패: {a['error']} | — |")
        else:
            lines.append(f"| {a['sym']} | {fmt_px(a['price'], meta['dp'])} | {a['nS']}/3 | {a['nL']}/3 | {a['label']} | {auto_cell(a, meta['dp'])} |")
    lines += ["", "- 발송(3중 점검): " + (", ".join(s["key"] for s in sent) or "없음"),
             "- 발송(자동 1): " + (", ".join(s["key"] for s in (sent_auto or [])) or "없음")]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def auto_cell(a, dp):
    """실행 요약 표의 자동 1 칸."""
    au = a.get("auto1") or {}
    if not au.get("ok"):
        return "—"
    side = "롱" if au["side"] == "long" else "숏"
    if au["voided"]:
        return f"{side} 폐기(무효선 넘음)"
    gap = au.get("gapPct")
    txt = f"{side} 진입 {fmt_px(au['entry'], dp)} ({fmt_pct(gap)})"
    return txt + (" 🔔" if au.get("alertable") else "")


def scan(feed, verbose=True):
    out = []
    for meta in SYMS:
        sym = meta["id"]
        try:
            tk = feed.ticker(sym)
            price = float(tk["last"])
            candles = {bar: feed.candles(sym, bar, 200) for bar in ("1Dutc", "4H", "1H")}
            a = build_analysis(sym, price, candles)
            if a is None:
                raise RuntimeError("봉이 60개 미만 — 분석 불가")
            auto = auto1_candidate(sym, price, candles)
            if auto.get("ok"):
                auto["refs"] = auto1_refs(candles, price)
                auto["alertable"] = bool(auto.get("near") and not auto.get("voided"))
            a["auto1"] = auto
            a["ticker"] = tk
            a["source"] = feed.name()
            out.append(a)
            if verbose:
                print(f"· {sym:<9} {fmt_px(price, meta['dp']):>12}  숏 {a['nS']}/3 · 롱 {a['nL']}/3 → {a['label']}"
                      f" ({a['zone']['code']})", flush=True)
                if auto.get("ok"):
                    print(f"   · 자동 1 {('롱' if auto['side'] == 'long' else '숏')}"
                          f" 진입 {fmt_px(auto['entry'], meta['dp'])}"
                          f" · 현재가 차이 {fmt_pct(auto['gapPct'])}"
                          + (" · 폐기(되돌림 100% 초과)" if auto["voided"] else "")
                          + (" · 🔔 타점 도달" if auto["alertable"] else ""), flush=True)
                else:
                    print(f"   · 자동 1 — {auto.get('why', '계산 불가')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"!! {sym} 조회 실패: {e}", flush=True)
            out.append({"sym": sym, "error": str(e), "alertable": False, "auto1": {"ok": False}})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="손디 코인 웹앱 3중 점검 3/3 ntfy 알림")
    ap.add_argument("--test", action="store_true", help="ntfy 테스트 알림 1건 발송 후 종료")
    ap.add_argument("--dry-run", action="store_true", help="발송·상태 저장 없이 판정만 출력")
    ap.add_argument("--state", default=os.environ.get("ALERT_STATE", ".alert-state/state.json"),
                    help="쿨다운 상태 파일 경로 (기본 .alert-state/state.json)")
    ap.add_argument("--cooldown", type=int, default=COOLDOWN_MIN, help="같은 종목·방향 재알림 최소 간격(분)")
    ap.add_argument("--json", dest="json_out", default="", help="판정 결과 JSON 저장 경로")
    ap.add_argument("--quiet", action="store_true", help="스캔 표를 출력하지 않음")
    args = ap.parse_args(argv)

    meta = SYM_BY_ID

    if args.test:
        body = (f"🔔 테스트 알림 — 코인 웹앱 자동 감시 연결 확인\n\n"
                f"{now_kst():%Y-%m-%d %H:%M} KST\n"
                f"이 알림이 보이면 ntfy 구독이 정상입니다. 앞으로 3중 점검 3/3 타점이 뜰 때만 이 토픽으로 알림이 옵니다.\n"
                f"{APP_URL}")
        r = send_ntfy("Sond coin alert TEST", body, dry_run=args.dry_run)
        print("테스트 알림 발송:", json.dumps(r, ensure_ascii=False)[:300])
        return 0

    feed = Feed(verbose=not args.quiet)
    results = scan(feed, verbose=not args.quiet)
    source = feed.name()
    print(f"· 데이터 소스: {source}" + (f" (바이낸스 차단 사유: {feed.binance_why})" if feed.binance_why else ""), flush=True)

    st = load_state(args.state)
    now_ts = time.time()
    sent, skipped = [], []
    for a in results:
        if not a.get("alertable"):
            continue
        key = f"{a['sym']}:{a['side']}"
        left = in_cooldown(st, key, now_ts, args.cooldown)
        if left > 0:
            skipped.append((key, round(left, 1)))
            print(f"· 쿨다운 {key} — {left:.0f}분 남음, 발송 생략", flush=True)
            continue
        body = alert_body(a, meta[a["sym"]], a.get("ticker"))
        title = alert_title(a, meta[a["sym"]])
        try:
            r = send_ntfy(title, body, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001
            print(f"!! 알림 발송 실패 {key}: {e}", flush=True)
            continue
        sent.append({"key": key, "title": title, "res": r})
        print(f"🔔 알림 발송 {key} — {title}", flush=True)
        st.setdefault("alerts", {})[key] = {
            "ts": now_ts,
            "iso": now_kst().isoformat(timespec="seconds"),
            "count": a["best"],
            "price": a["price"],
            "label": a["label"],
        }

    # ---- 자동 1 (4H 모노웨이브 추세 재개) — 수작업 3중 점검과 별도 키로 쿨다운
    sent_auto, skipped_auto = [], []
    for a in results:
        if a.get("error"):
            continue
        au = a.get("auto1") or {}
        if not au.get("alertable"):
            continue
        key = f"auto1:{a['sym']}:{au['side']}"
        left = in_cooldown(st, key, now_ts, args.cooldown)
        if left > 0:
            skipped_auto.append((key, round(left, 1)))
            print(f"· 자동 1 쿨다운 {key} — {left:.0f}분 남음, 발송 생략", flush=True)
            continue
        body = auto1_body(au, meta[a["sym"]], a.get("ticker"), au.get("refs"))
        title = auto1_title(au, meta[a["sym"]])
        try:
            r = send_ntfy(title, body, dry_run=args.dry_run, tags="zap,bell")
        except Exception as e:  # noqa: BLE001
            print(f"!! 자동 1 알림 발송 실패 {key}: {e}", flush=True)
            continue
        sent_auto.append({"key": key, "title": title, "res": r})
        print(f"🔔 자동 1 알림 발송 {key} — {title}", flush=True)
        st.setdefault("alerts", {})[key] = {
            "ts": now_ts,
            "iso": now_kst().isoformat(timespec="seconds"),
            "kind": "auto1",
            "entry": au["entry"],
            "price": au["price"],
            "gapPct": au["gapPct"],
            "label": "자동 1 타점 도달",
        }

    if args.json_out:
        payload = {
            "generated": now_kst().isoformat(timespec="seconds"),
            "source": source,
            "binanceBlocked": (None if feed.binance_ok else feed.binance_why),
            "cooldownMin": args.cooldown,
            "sent": [s["key"] for s in sent],
            "sentAuto": [s["key"] for s in sent_auto],
            "skipped": skipped + skipped_auto,
            "symbols": [
                {k: v for k, v in a.items() if k not in ("ticker",)}
                for a in results
            ][:20],
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        print("· 판정 JSON 저장: " + args.json_out, flush=True)

    st["lastRun"] = {
        "iso": now_kst().isoformat(timespec="seconds"),
        "source": source,
        "scanned": [{"sym": a.get("sym"), "nS": a.get("nS"), "nL": a.get("nL"),
                     "label": a.get("label"), "error": a.get("error")} for a in results],
        "sent": [s["key"] for s in sent],
        "sentAuto": [s["key"] for s in sent_auto],
    }
    if not args.dry_run:
        save_state(args.state, st)

    write_summary(results, sent, source, feed, sent_auto)

    ok = [a for a in results if "error" not in a]
    print(f"· 3/3 알림 {len(sent)}건 · 자동 1 알림 {len(sent_auto)}건 · 판정 {len(ok)}/{len(results)}종목"
          f" · 쿨다운 생략 {len(skipped) + len(skipped_auto)}건", flush=True)
    if not ok:
        print("!! 모든 종목 조회 실패 — 데이터 소스 확인 필요", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
