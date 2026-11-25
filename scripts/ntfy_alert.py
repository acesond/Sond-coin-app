#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""손디 코인 웹앱 — 3중 점검 3/3 ntfy 자동 알림 (15분 감시)

웹앱(https://acesond.github.io/Sond-coin-app/)의 진입 근거 3중 점검을 파이썬으로 그대로 옮겨,
**3/3 타점 도달**(주의 포함)이 뜰 때만 ntfy 토픽으로 푸시를 보냅니다.

  · ① 자리   — 4H 마지막 레그 0.45~0.68 되돌림 안, 또는 현재가가 가설의 숏/눌림 존 안(±0.09%)
  · ② 라인   — 가장 가까운 가설·4H 스윙 라인 0.6% 이내 (①과 같은 숫자면 1개로 셈)
  · ③ 다이버전스 — 1H·4H RSI 다이버전스(고점/저점이 무효화되지 않은 것만)
  판정 라벨은 웹앱과 동일하게 「타점 도달 / 주의 / 폐기 / 이탈」까지 계산하고,
  타점 도달·주의일 때만 알림을 보냅니다.

데이터: 바이낸스 선물 fapi.binance.com 우선(1D 200봉 · 4H 200봉 · 1H 200봉),
        HTTP 451 등으로 막히면 OKX 퍼블릭 API(BTC-USDT-SWAP …)로 자동 폴백.

가설값: HYP_VERSION 2026-11-25-1015 (index.html의 LEVELS · HYP · ZONE_DEF와 같은 값).
        가설을 새로 배포하면 아래 HYP_DATA를 같은 값으로 바꿔 커밋하면 됩니다.

사용법:
    python3 scripts/ntfy_alert.py                 # 1회 스캔 → 3/3만 발송 (60분 쿨다운)
    python3 scripts/ntfy_alert.py --dry-run       # 발송 없이 판정만 (상태 파일도 안 씀)
    python3 scripts/ntfy_alert.py --test          # 테스트 알림 1건 발송 후 종료
    python3 scripts/ntfy_alert.py --json out.json # 판정 결과를 JSON으로 남김
    python3 scripts/ntfy_alert.py --state .alert-state/state.json
"""
import argparse
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
  "HYP_VERSION": "2026-11-25-1015",
  "LEVELS": {
    "BTCUSDT": [
      {"p": 63750, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 4H 0.786 되돌림 63,746 위 라운드 (1D EMA20 66,517 아래)"},
      {"p": 62540, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 1H 64,572.8→59,251의 0.382 되돌림 62,539.9"},
      {"p": 61300, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 1H 0.618 되돌림 61,283.9 위 · 1H 종가면 폐기"},
      {"p": 60750, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 11/24 14시 고점 60,746.1·4H EMA20 60,588 위 라운드"},
      {"p": 60250, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 1H 0.786 되돌림 60,389.9 아래·60,085.1 고점 위"},
      {"p": 59850, "side": "long", "role": "break", "tag": "눌림 롱 1차 목표", "label": "눌림 롱 1차 · 상승 레그 0.5 되돌림 59,849.8"},
      {"p": 59250, "side": "long", "role": "break", "tag": "눌림 롱 감시선", "label": "눌림 롱 감시선 겸 숏 1차 · 11/25 02시 저점 59,251·라운드"},
      {"p": 58780, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 0.618 되돌림 58,738.1·11/22 4H 저점 58,746.1"},
      {"p": 58200, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 0.618 클러스터 아래 (1H 종가면 폐기)"},
      {"p": 57700, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 1H 종가 57,700 이하 (11/20 저점 57,700.1)"},
    ],
    "ETHUSDT": [
      {"p": 1866, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 11/16 4H 고점 1,866.21 (1D EMA20 1,886 아래)"},
      {"p": 1805, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 1,800 라운드 (11/21 4H 고점 1,816.95 아래)"},
      {"p": 1762, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 1H 0.5 되돌림 1,754.1·4H EMA50 1,748.7 위 · 1H 종가면 폐기"},
      {"p": 1732, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 1H 1,845→1,663.17의 0.618 되돌림 1,732.6"},
      {"p": 1700, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 4H EMA20 1,702.6·0.786 되돌림 1,702.1 (숏존 시작)"},
      {"p": 1680, "side": "long", "role": "break", "tag": "눌림 롱 1차 목표", "label": "눌림 롱 1차 · 11/24 4H 종가 1,679.4·1H EMA20 1,687 아래"},
      {"p": 1658, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 상승 레그 0.618 되돌림 1,654.0·11/22 저점 1,647.5 위"},
      {"p": 1640, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 11/22 4H 저점 1,647.5 클러스터 아래"},
      {"p": 1620, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 1H 종가 1,620 이하 (11/20 종가 1,622)"},
    ],
    "SOLUSDT": [
      {"p": 74.68, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 1H 78.49→68.52의 0.382 되돌림 74.68"},
      {"p": 72.65, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 11/24 1D 고점 72.65"},
      {"p": 71.2, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 1H EMA50 70.77·11/21 4H 고점 71.08 위 · 1H 종가면 폐기"},
      {"p": 70.4, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 상승 레그 0.618 70.05·1H EMA20 70.10·70.04 고점 선"},
      {"p": 69.9, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 70 라운드 아래·11/25 08시 고점 70.08 (숏존 시작)"},
      {"p": 69.6, "side": "long", "role": "break", "tag": "눌림 롱 1차 목표", "label": "눌림 롱 1차 · 1H EMA20 70.10·EMA50 70.77 아래 라운드"},
      {"p": 68.55, "side": "long", "role": "break", "tag": "눌림 롱 감시선", "label": "눌림 롱 감시선 겸 숏 1차 · 11/25 저점 68.52·11/22 저점 68.67"},
      {"p": 68.05, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 상승 레그 0.786 되돌림 67.75 바로 위 68 라운드"},
      {"p": 67.25, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 0.786 되돌림 67.75 아래 (1H 종가면 폐기)"},
      {"p": 66.5, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 1H 종가 66.50 이하 — 11/21 저점 64.83 재시험"},
    ],
    "XRPUSDT": [
      {"p": 1.026, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 11/23 야간 스파이크 고점 1.0259"},
      {"p": 1, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 1.00 라운드 겸 하락 0.786 되돌림 1.0009"},
      {"p": 0.964, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 11/24 14시 고점 0.9609·0.618 되돌림 0.9536 위 · 1H 종가면 폐기"},
      {"p": 0.945, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 상승 레그 0.5 되돌림 0.9425·4H EMA50 0.9514 아래"},
      {"p": 0.933, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 4H EMA20 0.9339·1H EMA50 0.9325 (숏존 시작)"},
      {"p": 0.918, "side": "long", "role": "break", "tag": "눌림 롱 감시선", "label": "눌림 롱 감시선 · 0.618 되돌림 0.9229 아래 라운드"},
      {"p": 0.912, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 11/22 저점 0.9112·11/25 저점 0.9089 위 (이중바닥)"},
      {"p": 0.9, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 이중바닥 0.9089 아래·0.786 되돌림 0.8949 위"},
      {"p": 0.883, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 1H 종가 0.883 이하 (11/20 저점 0.8835)"},
    ],
    "BNBUSDT": [
      {"p": 600, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 11/15 4H 고점 599.92 (1D EMA20 609.1 아래)"},
      {"p": 587.5, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 11/23 21시 스파이크 고점 587.49"},
      {"p": 562.5, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 11/24 10시 고점 562.18 위 · 1H 종가면 폐기"},
      {"p": 556, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 11/24 14시 고점 556.18·4H EMA20 553.9 위"},
      {"p": 548, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 상승 레그 0.5 되돌림 545.46 위 548 라운드 (숏존 시작)"},
      {"p": 552.5, "side": "long", "role": "break", "tag": "눌림 롱 1차 목표", "label": "눌림 롱 1차 · 1H EMA50 552.7·4H EMA20 553.9 아래"},
      {"p": 536, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 상승 레그 0.618 되돌림 535.56·11/22 저점 536.75"},
      {"p": 528, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 11/20 저점 530.81 아래 (1H 종가면 폐기)"},
      {"p": 520, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 1H 종가 520 이하 — 0.786 되돌림 521.43·11/21 저점 503.43 재시험"},
    ],
    "DOGEUSDT": [
      {"p": 0.063, "side": "long", "role": "break", "tag": "롱 2차 목표", "label": "돌파 롱 2차 · 0.063 라운드 (1D EMA20 0.062011 위)"},
      {"p": 0.06045, "side": "long", "role": "break", "tag": "롱 1차 목표", "label": "돌파 롱 1차 · 11/18 4H 고점 0.06045·11/23 고점 0.06022"},
      {"p": 0.0586, "side": "short", "role": "stop", "tag": "숏 손절", "label": "숏 손절 · 1H 0.618 되돌림 0.05796·11/24 10시 고점 0.05716 위 · 1H 종가면 폐기"},
      {"p": 0.0573, "side": "short", "role": "entry", "tag": "숏 진입", "label": "숏 진입 · 1H 0.5 되돌림 0.05727·4H EMA50 0.05724"},
      {"p": 0.0556, "side": "short", "role": "entry", "tag": "숏 감시선", "label": "숏 감시선 · 상승 레그 0.5 0.05549·4H EMA20 0.05574 (숏존 시작)"},
      {"p": 0.055, "side": "long", "role": "break", "tag": "눌림 롱 감시선", "label": "눌림 롱 감시선 · 상승 레그 0.5 되돌림 0.05549 아래 (지금 자리)"},
      {"p": 0.0544, "side": "long", "role": "entry", "tag": "눌림 롱 진입", "label": "눌림 롱 진입 · 상승 레그 0.618 0.05437·11/23 4H 저점 0.05431"},
      {"p": 0.0532, "side": "long", "role": "stop", "tag": "눌림 롱 손절", "label": "눌림 롱 손절 · 11/22 저점 0.05373 아래 (1H 종가면 폐기)"},
      {"p": 0.0508, "side": "short", "role": "break", "tag": "이탈 경계", "label": "하방 이탈 · 1H 종가 0.0508 이하 (11/21 저점 0.05075)"},
    ],
  },
  "HYP": {
    "BTCUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 60750, "stop": 61300, "t1": 59250, "t2": 58750},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 하단 눌림목 롱", "tag": "서브", "entry": 58780, "stop": 58200, "t1": 59850, "t2": 60750},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 돌파 롱", "tag": "추세", "entry": 61300, "stop": 60750, "t1": 62540, "t2": 63750},
    },
    "ETHUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 1732, "stop": 1762, "t1": 1680, "t2": 1638},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 하단 눌림목 롱", "tag": "서브", "entry": 1658, "stop": 1640, "t1": 1701, "t2": 1732},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 돌파 롱", "tag": "추세", "entry": 1762, "stop": 1732, "t1": 1805, "t2": 1866},
    },
    "SOLUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 70.4, "stop": 71.2, "t1": 68.55, "t2": 67.75},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 하단 눌림목 롱", "tag": "서브", "entry": 68.05, "stop": 67.25, "t1": 69.6, "t2": 70.9},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 돌파 롱", "tag": "추세", "entry": 71.2, "stop": 70.4, "t1": 72.65, "t2": 74.68},
    },
    "XRPUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 0.945, "stop": 0.964, "t1": 0.911, "t2": 0.8835},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 눌림목 롱", "tag": "서브", "entry": 0.912, "stop": 0.9, "t1": 0.933, "t2": 0.951},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 돌파 롱", "tag": "추세", "entry": 0.964, "stop": 0.945, "t1": 1, "t2": 1.026},
    },
    "BNBUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 556, "stop": 562.5, "t1": 543.8, "t2": 535},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 눌림목 롱", "tag": "서브", "entry": 536, "stop": 528, "t1": 552.5, "t2": 562},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 돌파 롱", "tag": "추세", "entry": 562.5, "stop": 556, "t1": 587.5, "t2": 600},
    },
    "DOGEUSDT": {
      "h1": {"id": "h1", "cls": "short", "kind": "short", "title": "가설 1 · 반등 저항 숏", "tag": "메인", "entry": 0.0573, "stop": 0.0586, "t1": 0.0544, "t2": 0.0528},
      "h2": {"id": "h2", "cls": "long", "kind": "long", "title": "가설 2 · 눌림목 롱", "tag": "서브", "entry": 0.0544, "stop": 0.0532, "t1": 0.0572, "t2": 0.0602},
      "br": {"id": "br", "cls": "break", "kind": "long", "title": "가설 3 · 돌파 롱", "tag": "추세", "entry": 0.0586, "stop": 0.0573, "t1": 0.06045, "t2": 0.063},
    },
  },
  "ZONE_DEF": {
    "BTCUSDT": {"stop": 61300, "brkup": 61300, "brkupTop": 62540, "ext": 63750, "short": 60250, "shortTop": 60750, "mid": 59250, "long": 58780, "warnL": 58200, "brk1": 57700, "midLabel": "눌림 롱 대기 · 반등 숏 대기 · 58,780 지지 감시"},
    "ETHUSDT": {"stop": 1762, "brkup": 1762, "brkupTop": 1805, "ext": 1866, "short": 1700, "shortTop": 1732, "mid": 1680, "long": 1658, "warnL": 1640, "brk1": 1620, "midLabel": "눌림 롱 대기 · 반등 숏 대기 · 1,658 지지 감시"},
    "SOLUSDT": {"stop": 71.2, "brkup": 71.2, "brkupTop": 72.65, "ext": 74.68, "short": 69.9, "shortTop": 70.4, "mid": 68.55, "long": 68.05, "warnL": 67.25, "brk1": 66.5, "midLabel": "눌림 롱 대기 · 반등 숏 대기 · 68.05 지지 감시"},
    "XRPUSDT": {"stop": 0.964, "brkup": 0.964, "brkupTop": 1, "ext": 1.026, "short": 0.933, "shortTop": 0.945, "mid": 0.918, "long": 0.912, "warnL": 0.9, "brk1": 0.883, "midLabel": "눌림 롱 대기 · 반등 숏 대기 · 0.9120 지지 감시"},
    "BNBUSDT": {"stop": 562.5, "brkup": 562.5, "brkupTop": 587.5, "ext": 600, "short": 548, "shortTop": 556, "mid": 543.5, "long": 536, "warnL": 528, "brk1": 520, "midLabel": "눌림 롱 대기 · 반등 숏 대기 · 536 지지 감시"},
    "DOGEUSDT": {"stop": 0.0586, "brkup": 0.0586, "brkupTop": 0.06045, "ext": 0.063, "short": 0.0556, "shortTop": 0.0573, "mid": 0.055, "long": 0.0544, "warnL": 0.0532, "brk1": 0.0508, "midLabel": "눌림 롱 대기 · 반등 숏 대기 · 0.0544 지지 감시"},
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


# ---------------------------------------------------------------- NEoWave 참고(주의 문구용, 판정에는 미반영)
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
        waves.append({"len": ln, "bars": bars, "slope": ln / bars,
                      "dir": 1 if p2["price"] >= p1["price"] else -1,
                      "endPrice": p2["price"]})
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


# ---------------------------------------------------------------- 3중 점검


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
    if n_s > n_l:
        side = "short"
    elif n_l > n_s:
        side = "long"
    else:
        side = "long" if tfs["4H"]["trend"] == "up" else "short"

    best = max(n_s, n_l)
    caution = None
    if best >= 3:
        reasons = []
        try:
            cs1 = tfs["1H"]["cs"]
            atr = calc_atr(cs1, 14)[-1]
            if not is_num(atr) or atr <= 0:
                atr = cs1[-1]["c"] * 0.005
            hint = neowave_reduce_hint(extract_monowaves(cs1, atr))
            if hint:
                reasons.append("NEoWave(1H) 파동 겹침/조정 구간 — " + hint)
        except Exception:  # noqa: BLE001 — 참고 문구라 실패해도 알림은 보냅니다
            pass
        d1 = tfs["1Dutc"]["trend"]
        if (side == "long" and d1 == "down") or (side == "short" and d1 == "up"):
            reasons.append("1D " + ("하락" if d1 == "down" else "상승") + " 배열 — 역추세 " + ("롱" if side == "long" else "숏"))
        if reasons:
            caution = reasons

    if best >= 3 and caution:
        label, cls = "주의", "warn"
    elif best >= 3:
        label, cls = "타점 도달", ("bad" if side == "short" else "long")
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
        "caution": caution,
        "alertable": best >= 3 and label in ("타점 도달", "주의"),
    }


# ---------------------------------------------------------------- ntfy
def send_ntfy(title, body, click=APP_URL, priority="high", tags="chart_with_upwards_trend,bell",
              dry_run=False):
    headers = {
        "Title": title,
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
    if a["caution"]:
        lines.append("⚠ 주의 — " + " / ".join(a["caution"]))
    lines.append("")
    lines.append("⏳ 1H 봉 마감(정각) 확인 후 진입 판단 — 이 알림은 분석 참고용이고 주문은 실행하지 않습니다.")
    return "\n".join(lines)


def alert_title(a, sym_meta):
    """ntfy Title은 ASCII로만 — 한글 본문과 섞이지 않게 헤더는 영문으로 보냅니다."""
    side = "SHORT" if a["side"] == "short" else "LONG"
    return f"{sym_meta['code']} {side} {a['best']}/3 - Sond coin"


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
def write_summary(results, sent, source, feed):
    """GitHub Actions 실행 요약(GITHUB_STEP_SUMMARY)에 한 줄씩 남깁니다."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["### 코인 3중 점검 스캔", "",
             f"- {now_kst():%Y-%m-%d %H:%M} KST · 데이터 {source}" +
             (f" (바이낸스 차단: {feed.binance_why})" if feed.binance_why else ""), "",
             "| 종목 | 현재가 | 숏 | 롱 | 판정 |", "|---|---|---|---|---|"]
    for a in results:
        meta = SYM_BY_ID.get(a.get("sym"), {"dp": 2})
        if a.get("error"):
            lines.append(f"| {a.get('sym')} | — | — | — | 조회 실패: {a['error']} |")
        else:
            lines.append(f"| {a['sym']} | {fmt_px(a['price'], meta['dp'])} | {a['nS']}/3 | {a['nL']}/3 | {a['label']} |")
    lines += ["", "- 발송: " + (", ".join(s["key"] for s in sent) or "없음")]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


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
            a["ticker"] = tk
            a["source"] = feed.name()
            out.append(a)
            if verbose:
                print(f"· {sym:<9} {fmt_px(price, meta['dp']):>12}  숏 {a['nS']}/3 · 롱 {a['nL']}/3 → {a['label']}"
                      f" ({a['zone']['code']})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"!! {sym} 조회 실패: {e}", flush=True)
            out.append({"sym": sym, "error": str(e), "alertable": False})
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

    if args.json_out:
        payload = {
            "generated": now_kst().isoformat(timespec="seconds"),
            "source": source,
            "binanceBlocked": (None if feed.binance_ok else feed.binance_why),
            "cooldownMin": args.cooldown,
            "sent": [s["key"] for s in sent],
            "skipped": skipped,
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
    }
    if not args.dry_run:
        save_state(args.state, st)

    write_summary(results, sent, source, feed)

    ok = [a for a in results if "error" not in a]
    print(f"· 3/3 알림 {len(sent)}건 · 판정 {len(ok)}/{len(results)}종목 · 쿨다운 생략 {len(skipped)}건", flush=True)
    if not ok:
        print("!! 모든 종목 조회 실패 — 데이터 소스 확인 필요", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
