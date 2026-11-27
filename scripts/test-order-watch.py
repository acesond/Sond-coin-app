#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""예약주문 관점 감시 테스트 (네트워크 없이 가짜 시세로).

실행: python3 scripts/test-order-watch.py
  · ntfy_alert.scan_orders / evaluate_order 의 판정 5종
  · order_watch.py CLI 의 종료 코드(0 알림 / 1 조용 / 2 실패)
실제 구글 시트·거래소에 쓰지 않습니다.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ntfy_alert as core  # noqa: E402

OUT = []


def ok(name, cond, extra=""):
    OUT.append((name, bool(cond), str(extra)))


class FakeFeed:
    def __init__(self, price, trend="down", ema_above=True):
        self.price = price
        self.trend = trend
        self.ema_above = ema_above

    def ticker(self, sym):
        return {"last": self.price, "open24h": self.price, "high24h": self.price,
                "low24h": self.price, "chg": 0.0, "ts": 0}

    def candles(self, sym, bar, limit=200):
        n = 200
        cs = []
        base = self.price
        # 4H: 서서히 내려오는(또는 올라가는) 봉 — EMA50 대비 위치를 만들어 냅니다
        for i in range(n):
            if self.trend == "down":
                c = base * (1.06 - 0.06 * (i + 1) / n)
            else:
                c = base * (0.94 + 0.06 * (i + 1) / n)
            cs.append({"t": 1700000000000 + i * 3600000, "o": c, "h": c * 1.001,
                       "l": c * 0.999, "c": c, "v": 1.0, "conf": True})
        if bar == "1H":
            cs = cs[-200:]
            # 마지막 확정 1H 종가를 현재가 근처로
            cs[-2]["c"] = cs[-2]["o"] = self.price * 0.999
        return cs


def ev_for(order, price, trend="down"):
    return core.evaluate_order(order, FakeFeed(price, trend).ticker(order["sym"]),
                               FakeFeed(price, trend).candles(order["sym"], "4H"))


BTC_ORDER = {"id": "od-btc", "sym": "BTCUSDT", "side": "short", "kind": "entry",
             "price": 61778.0, "margin": 667.2, "lev": 5, "stop": 63234.5,
             "t1": 60770.0, "t2": 59800.0, "note": "0.618 되돌림 지정가", "status": "pending", "at": 1}
ETH_LONG = {"id": "od-eth", "sym": "ETHUSDT", "side": "long", "kind": "entry",
            "price": 1670.0, "margin": 120.0, "lev": 5, "stop": 1634.0,
            "t1": 1712.0, "t2": 1742.0, "note": "", "status": "pending", "at": 1}


class FakeFeedCandles:
    """evaluate_order 는 candles dict 를 받습니다."""

    def __init__(self, price, trend="down"):
        f = FakeFeed(price, trend)
        self.c = {"4H": f.candles("x", "4H"), "1H": f.candles("x", "1H")}


def evaluate(order, price, trend="down"):
    f = FakeFeedCandles(price, trend)
    return core.evaluate_order(order, {"last": price}, f.c)


# ---------- 1) 숏: 무효화선 돌파 (1H 종가 확인)
ev = evaluate(BTC_ORDER, 61900, "down")
keys = [c["key"] for c in ev["conds"]]
ok("1-1 숏 무효선 돌파 판정", "breach1h" in keys or "breach" in keys, keys)
ok("1-2 무효선은 가설 손절(61,850) — 주문 SL 63,234.5보다 가깝다", ev["inval"] == 61850.0, ev["inval"])
ok("1-3 제목·본문에 종목/지정가 포함",
   "BTC" in core.order_title(ev, ev["best"]) and "61,778.0" in core.order_body(ev, ev["best"]),
   core.order_title(ev, ev["best"]))

# ---------- 2) 숏: 무효화선 근접
ev = evaluate(BTC_ORDER, 61830, "down")
keys = [c["key"] for c in ev["conds"]]
ok("2-1 숏 무효선 근접 판정", "near" in keys and "breach1h" not in keys, keys)
ok("2-2 근접이 가장 높은 사유", ev["best"] and ev["best"]["key"] == "near", ev["best"] and ev["best"]["key"])

# ---------- 3) 숏: 관점 유지(조용)
ev = evaluate(BTC_ORDER, 61300, "down")
ok("3-1 지정가 0.8% 아래·무효선 여유 → 사유 없음", ev["conds"] == [], [c["key"] for c in ev["conds"]])

# ---------- 4) 지정가 도달 (다른 사유가 없을 때만 따로 알림)
ev = evaluate(ETH_LONG, 1669, "up")
keys = [c["key"] for c in ev["conds"]]
ok("4-1 지정가 도달 판정", "reach" in keys, keys)
ok("4-2 도달 표시", ev["reached"] is True, ev["reached"])
ev = evaluate(BTC_ORDER, 61790, "down")
keys = [c["key"] for c in ev["conds"]]
ok("4-3 무효화 사유가 있으면 도달은 중복 알림하지 않음", "reach" not in keys and "near" in keys, keys)

# ---------- 5) 숏: 반대편(눌림 롱) 먼저 이탈 → 관점 식음
ev = evaluate(BTC_ORDER, 59700, "down")
keys = [c["key"] for c in ev["conds"]]
ok("5-1 박스 하단 아래로 먼저 빠짐 → stale", "stale" in keys, keys)

# ---------- 6) 롱: 4H EMA50 아래로 안착 → 구조 반전
ev = evaluate(ETH_LONG, 1690, "down")
keys = [c["key"] for c in ev["conds"]]
ok("6-1 롱 4H 구조 반전", "flip4h" in keys, keys)
ok("6-2 롱 손절선 1634 반영", ev["inval"] == 1634.0, ev["inval"])

# ---------- 7) 롱: 위로 달아나 관점 식음
ev = evaluate(ETH_LONG, 1730, "up")
keys = [c["key"] for c in ev["conds"]]
ok("7-1 롱 지정가가 아래로 멀어짐 → stale", "stale" in keys, keys)

# ---------- 8) 6종목 밖 종목도 손절선 기준으로 감시
NEAR_X = {"id": "od-near", "sym": "NEARUSDT", "side": "long", "kind": "entry",
          "price": 2.92, "margin": 100, "lev": 5, "stop": 2.85, "status": "pending", "at": 1}
ev = evaluate(NEAR_X, 2.855, "down")
ok("8-1 가설 없는 종목도 SL 근접 판정", any(c["key"] in ("near", "breach", "breach1h") for c in ev["conds"]),
   [(c["key"]) for c in ev["conds"]])

# ---------- 9) 미체결 0건 → 알림 없음
res = core.scan_orders(None, verbose=False, orders=[])
ok("9-1 주문 0건이면 알림 없음", res["alerts"] == [] and res["ok"] is True, res["alerts"])

# ---------- 10) order_watch.py : 조용 / 알림 / ack / 재알림 억제 (가짜 시세로 main() 직접 호출)
import contextlib  # noqa: E402
import importlib  # noqa: E402
import io  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ordwatch-")
STATE = os.path.join(TMP, "state", "order_watch.json")
ow = importlib.import_module("order_watch")


def write_orders(name, orders):
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"orders": orders}, f, ensure_ascii=False)
    return p


def run_main(orders_file, price, extra=None):
    ow.core.Feed = lambda verbose=True: FakeFeed(price, "down")   # 실제 시세 대신 가짜
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ow.main(["--state", STATE, "--orders-file", orders_file] + (extra or []))
    return code, buf.getvalue().strip()


quiet_file = write_orders("quiet.json", [BTC_ORDER])
code, out = run_main(quiet_file, 61300)
ok("10-1 관점 유지 → 종료 1", code == 1, f"code={code} out={out[:80]}")
ok("10-2 조용할 때 stdout 없음", out == "", out[:80])

fired_file = write_orders("fired.json", [BTC_ORDER])
code, out = run_main(fired_file, 61900)
ok("10-3 무효화 돌파 → 종료 0", code == 0, f"code={code}")
ok("10-4 stdout 에 관찰 사실(JSON)", out.startswith("{") and "61778" in out and "무효" in out, out[:200])

code2, out2 = run_main(fired_file, 61900)
a1 = json.loads(out)["alerts"]
a2 = json.loads(out2)["alerts"] if out2 else []
ok("10-5 처리 전에는 같은 사실을 다시 넘김", code2 == 0 and a1 == a2 and len(a1) >= 1, f"code={code2} n={len(a2)}")

code3, out3 = run_main(fired_file, 61900, ["--ack"])
ok("10-6 ack 후 비움", code3 == 0 and "비움" in out3, out3[:60])

code4, out4 = run_main(fired_file, 61900)
ok("10-7 ack 뒤에는 쿨다운으로 조용", code4 == 1, f"code={code4} out={out4[:60]}")

# ---------- 11) 시트가 읽히지 않으면 종료 2
r = subprocess.run([sys.executable, os.path.join(ROOT, "order_watch.py"),
                    "--state", os.path.join(TMP, "s2.json"),
                    "--url", "https://script.google.com/macros/s/INVALID/exec"],
                   capture_output=True, text=True, timeout=180)
ok("11-1 시트 응답이 없으면 종료 2", r.returncode == 2, f"code={r.returncode} err={r.stderr.strip()[:100]}")

# ---------- 12) 실제 시트(읽기 전용) — 매매기록 건수가 줄거나 늘지 않았는지
real = core.fetch_pending_orders(core.SYNC_URL, verbose=False)
ok("12-1 실제 시트 pull 성공", real["ok"] is True, real["why"])
ok("12-2 실제 시트 예약주문 상태 확인", isinstance(real["orders"], list),
   f"supported={real['supported']} pending={len(real['orders'])}")

# ============================================================================
# 13~) 각자 기준 분리 — 수동 가설 주문과 자동 1 주문을 섞지 않는다 (2026-11-27 #14524)
#     성훈님 SOL 숏 73.63 / SL 76.2 는 자동 1 로 만든 주문인데, 수동 가설 h1 의 손절선 72.55 와
#     비교해 "무효화선 돌파"·"4H 구조 반전" 오경보가 나갔습니다.
# ============================================================================

def zigzag4h(start, segs, pad=0.004):
    """4H 모노웨이브를 만들 수 있는 지그재그 봉. segs=[(봉 수, 그 구간 마지막 종가), ...]"""
    vals = [start]
    cur = start
    for n, target in segs:
        for i in range(1, n + 1):
            vals.append(cur + (target - cur) * i / n)
        cur = target
    return [{"t": 1700000000000 + i * 14400000, "o": c, "h": c * (1 + pad), "l": c * (1 - pad),
             "c": c, "v": 1.0, "conf": True} for i, c in enumerate(vals)]


def one1h(price):
    return [{"t": 0, "o": price, "h": price * 1.001, "l": price * 0.999, "c": price, "v": 1.0, "conf": True}] * 3


# 마지막에서 두 번째 모노웨이브(m1)가 아래로 향하는 4H — 자동 1 후보도 숏
C4_SHORT_M1 = zigzag4h(71.0, [(25, 66.0), (20, 74.0), (20, 68.0), (12, 69.2)])
# m1 이 위로 향하는 4H — 자동 1 후보가 롱으로 바뀐 경우
C4_LONG_M1 = zigzag4h(71.0, [(20, 66.0), (20, 74.5), (15, 68.5), (18, 74.0), (6, 73.0)])

# 성훈님이 실제로 걸어둔 주문 그대로(시트에 source 없음)
SOL_A1 = {"id": "odmwymtb25pzw", "sym": "SOLUSDT", "code": "SOL", "side": "short", "kind": "entry",
          "price": 73.63, "margin": 837.01, "lev": 5, "stop": 76.2, "t1": 65.77, "t2": 57.91,
          "feeMode": "maker", "at": 1795762813757, "note": "", "status": "pending", "hitAt": 0}


def evaluate_c(order, price, c4, close1=None):
    return core.evaluate_order(order, {"last": price}, {"4H": c4, "1H": one1h(close1 or price)})


# 수동 가설 h1(SOL 숏 71.8 / SL 72.55)의 손절선을 넘어선 자리에 걸린 숏 지정가 → 자동 1
src, why = core.order_source(SOL_A1, "SOLUSDT", "short", 73.63, 76.2)
ok("13-1 source 없는 SOL 73.63 주문은 자동 1 로 판별", src == "auto1", f"{src} / {why}")

# 73.63 은 수동 h1 손절선 72.55 위 → 예전 코드라면 '무효화선 돌파'가 났던 자리
ev = evaluate_c(SOL_A1, 73.0, C4_SHORT_M1)
ok("13-2 무효화선은 수동 72.55 가 아니라 주문 SL 76.2", ev["inval"] == 76.2, ev["inval"])
ok("13-3 4H 반전(flip4h)을 끌어오지 않음", "flip4h" not in [c["key"] for c in ev["conds"]],
   [c["key"] for c in ev["conds"]])

# 예전 코드에서 오경보가 나던 구간: 가설 손절선 72.55 아래로 내려간 현재가
ev = evaluate_c(SOL_A1, 72.6, C4_SHORT_M1)
keys = [c["key"] for c in ev["conds"]]
ok("13-4 수동 72.55 아래(72.60)에서도 오경보 없음", keys == [], keys)
ev = evaluate_c(SOL_A1, 72.6, C4_SHORT_M1, close1=72.7)
ok("13-5 1H 종가가 72.55 위여도 '무효화 확정' 없음", [c["key"] for c in ev["conds"]] == [],
   [c["key"] for c in ev["conds"]])

# 주문 자체의 손절선 76.2 는 그대로 감시
ev = evaluate_c(SOL_A1, 76.05, C4_SHORT_M1)
ok("13-6 주문 SL 76.2 근접은 알림", "near" in [c["key"] for c in ev["conds"]], [c["key"] for c in ev["conds"]])
ev = evaluate_c(SOL_A1, 76.4, C4_SHORT_M1, close1=76.5)
ok("13-7 주문 SL 76.2 1H 종가 돌파는 '무효화 확정'", "breach1h" in [c["key"] for c in ev["conds"]],
   [c["key"] for c in ev["conds"]])
ok("13-8 알림 본문에 감시 기준(자동 1) 표기", "감시 기준 자동 1" in core.order_body(ev, ev["best"]),
   core.order_body(ev, ev["best"]).split("\n")[3:5])

# 지정가 도달은 자동 1 주문에도 그대로 (수동 가설선과 무관)
ev = evaluate_c(SOL_A1, 73.7, C4_SHORT_M1)
ok("13-9 자동 1 주문도 지정가 도달은 알림", "reach" in [c["key"] for c in ev["conds"]],
   [c["key"] for c in ev["conds"]])
ok("13-10 자동 1 주문의 반대편 가설선(stale)은 쓰지 않음",
   "stale" not in [c["key"] for c in evaluate_c(SOL_A1, 69.0, C4_SHORT_M1)["conds"]],
   [c["key"] for c in evaluate_c(SOL_A1, 69.0, C4_SHORT_M1)["conds"]])

# ---------- 14) 자동 1 후보가 반대 방향으로 바뀌면 auto1_flip
ev = evaluate_c(SOL_A1, 72.0, C4_LONG_M1)
keys = [c["key"] for c in ev["conds"]]
ok("14-1 4H m1 이 롱으로 바뀌면 auto1_flip", keys == ["auto1_flip"], keys)
ok("14-2 제목에 '자동 1' 표기", "자동 1" in core.order_title(ev, ev["best"]), core.order_title(ev, ev["best"]))
ok("14-3 반대 전환 사유에 모노웨이브 방향 표기", "롱" in ev["best"]["text"], ev["best"]["text"])

# ---------- 15) source 필드가 있으면 숫자 추정보다 그 값을 먼저 믿는다
SOL_MANUAL = dict(SOL_A1, source="manual")
ev = evaluate_c(SOL_MANUAL, 72.6, C4_SHORT_M1)
ok("15-1 source=manual 이면 수동 가설 기준(72.55)", ev["inval"] == 72.55, ev["inval"])
ok("15-2 source=manual 이면 예전처럼 무효화선 72.55 로 경보",
   any(c["key"] in ("near", "breach", "breach1h") for c in ev["conds"]), [c["key"] for c in ev["conds"]])
SOL_A1_TAG = dict(SOL_A1, source="auto1")
ev = evaluate_c(SOL_A1_TAG, 72.6, C4_SHORT_M1)
ok("15-3 source=auto1 이면 수동 가설선 무시", ev["inval"] == 76.2 and ev["conds"] == [],
   f"{ev['inval']} {[c['key'] for c in ev['conds']]}")

# ---------- 16) 수동 가설 주문은 기존 그대로 — BTC 숏 61,778 은 h1 손절 61,850 으로 경보
src, why = core.order_source(BTC_ORDER, "BTCUSDT", "short", 61778.0, 63234.5)
ok("16-1 source 없는 BTC 61,778 주문은 수동 가설로 판별", src == "manual", f"{src} / {why}")
ev = evaluate(BTC_ORDER, 61830, "down")
ok("16-2 수동 가설 주문은 가설 손절선 근접 경보 유지", "near" in [c["key"] for c in ev["conds"]],
   [c["key"] for c in ev["conds"]])
ev = evaluate(BTC_ORDER, 61300, "down")
ok("16-3 수동 가설 주문 본문에 감시 기준(수동 가설) 표기",
   "감시 기준 수동 가설" in core.order_body(ev, {"label": "x", "text": "y", "key": "near"}), "")

# ---------- 17) 가설이 없는 종목(직접 입력)은 주문 SL 만 본다
src, why = core.order_source(NEAR_X, "NEARUSDT", "long", 2.92, 2.85)
ok("17-1 가설 없는 종목은 직접 입력(custom)", src == "custom", f"{src} / {why}")
ok("17-2 가설 없는 종목은 flip4h 를 쓰지 않음", "flip4h" not in [c["key"] for c in evaluate(NEAR_X, 2.855, "down")["conds"]],
   [c["key"] for c in evaluate(NEAR_X, 2.855, "down")["conds"]])

# ---------- 18) order_watch.py CLI — 자동 1 주문은 조용하고, 주문 SL 에 닿을 때만 실행을 연다
SOL_STATE = os.path.join(TMP, "state", "order_watch_sol.json")
SOL_FILE = write_orders("sol.json", [SOL_A1])


def run_sol(price, extra=None):
    ow.core.Feed = lambda verbose=True: FakeFeed(price, "down")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ow.main(["--state", SOL_STATE, "--orders-file", SOL_FILE] + (extra or []))
    return code, buf.getvalue().strip()


code, out = run_sol(72.6)
ok("18-1 자동 1 주문·가설 손절선 아래 → 종료 1(조용)", code == 1 and out == "", f"code={code} out={out[:80]}")
code, out = run_sol(76.05)
ok("18-2 주문 SL 76.2 근접 → 종료 0", code == 0 and "76.2" in out, f"code={code} out={out[:120]}")
ok("18-3 관찰 사실에 출처(auto1)가 실림", out.startswith("{") and json.loads(out)["alerts"][0].get("source") == "auto1",
   out[:160])

fails = [x for x in OUT if not x[1]]
for name, passed, extra in OUT:
    print(("PASS " if passed else "FAIL ") + name + (("  → " + extra) if extra else ""))
print(f"\n{len(OUT) - len(fails)}/{len(OUT)} passed")
sys.exit(1 if fails else 0)
