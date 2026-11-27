#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""예약주문 관점 감시 — 피클 예약 작업(check.sh)용 얇은 CLI.

ntfy_alert.py 의 감시 로직을 그대로 씁니다(같은 가설값·같은 판정).
다만 여기서는 ntfy 푸시를 보내지 않고, **피클 채팅으로 알릴 게 있는지만** 종료 코드로 알립니다.
  · 0 : 알릴 관점 변화가 있음 → stdout 에 관찰 사실(JSON) 출력
  · 1 : 미체결 예약주문이 없거나, 있어도 관점 변화가 없음 (조용)
  · 2 : 관찰 실패 (시트·시세)

시트(Apps Script)에 미체결 예약주문이 0건이면 아무 것도 하지 않습니다.

  python3 order_watch.py --state state/order_watch.json     # 판정(조용한 검사)
  python3 order_watch.py --state state/order_watch.json --show   # 사람이 보는 요약
  python3 order_watch.py --ack --state state/order_watch.json    # 알린 사실 비우기
  python3 order_watch.py --orders-file test-orders.json     # 시트 대신 테스트 주문으로
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ntfy_alert as core  # noqa: E402

MAX_PENDING = 20


def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict):
            raise ValueError("state is not an object")
    except FileNotFoundError:
        st = {}
    except Exception:  # noqa: BLE001
        st = {}
    st.setdefault("keys", {})
    st.setdefault("pending", {})
    st.setdefault("setupNotified", False)
    if not isinstance(st["keys"], dict):
        st["keys"] = {}
    if not isinstance(st["pending"], dict):
        st["pending"] = {}
    return st


def save_state(path, st):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def emit(pending):
    facts = list(pending.values())
    print(json.dumps({"observed_at": core.now_kst().isoformat(timespec="seconds"),
                      "alerts": facts}, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="예약주문 관점 감시 (check.sh용)")
    ap.add_argument("--state", default=os.environ.get("ORDER_WATCH_STATE", "state/order_watch.json"))
    ap.add_argument("--url", default=core.SYNC_URL)
    ap.add_argument("--orders-file", default="", help="시트 대신 읽을 테스트 주문 JSON")
    ap.add_argument("--cooldown", type=int, default=core.ORDER_COOLDOWN_MIN)
    ap.add_argument("--timeout", type=float, default=12.0, help="HTTP 타임아웃(초)")
    ap.add_argument("--ack", action="store_true", help="알린 사실(pending)을 비웁니다")
    ap.add_argument("--show", action="store_true", help="사람이 보는 요약 출력")
    ap.add_argument("--dry-run", action="store_true", help="상태 파일을 쓰지 않고 판정만")
    args = ap.parse_args(argv)

    st = load_state(args.state)

    if args.ack:
        n = len(st.get("pending") or {})
        st["pending"] = {}
        if not args.dry_run:
            save_state(args.state, st)
        print(f"ack: 알림 {n}건 비움")
        return 0

    # 아직 처리하지 않은 알림이 있으면 같은 사실을 다시 넘깁니다(처리될 때까지).
    if st.get("pending"):
        return emit(st["pending"])

    core.HTTP_TIMEOUT = args.timeout

    orders = None
    if args.orders_file:
        try:
            with open(args.orders_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            orders = data.get("orders") if isinstance(data, dict) else data
            if not isinstance(orders, list):
                raise ValueError("orders 배열이 아닙니다")
            got = {"ok": True, "supported": True, "orders": orders, "why": ""}
        except Exception as e:  # noqa: BLE001
            print(f"테스트 주문 파일을 읽지 못했습니다: {e}", file=sys.stderr)
            return 2
    else:
        got = core.fetch_pending_orders(args.url, verbose=False)

    if not got["ok"]:
        print(got.get("why") or "시트를 읽지 못했습니다", file=sys.stderr)
        return 2

    if not got["supported"]:
        # 시트가 아직 예약주문을 돌려주지 않는 상태(Apps Script 붙여넣기 전).
        # 한 번만 알려서 감시가 안 돌아가는 걸 모르고 지나치지 않게 합니다.
        if st.get("setupNotified"):
            if args.show:
                print("· 시트가 예약주문을 아직 지원하지 않습니다(이미 한 번 알림) — 조용")
            return 1
        fact = {
            "kind": "setup",
            "label": "예약주문 감시 준비 안 됨",
            "text": ("구글 시트의 Apps Script 가 아직 예약주문을 돌려주지 않습니다(v2 붙여넣기 전) — "
                     "지금은 예약주문이 폰 브라우저에만 저장되고, 시트·관점 감시에는 반영되지 않습니다."),
            "ordersUpdatedAt": got.get("ordersUpdatedAt"),
        }
        if not args.dry_run:
            st["setupNotified"] = True
            st["pending"]["setup"] = fact
            save_state(args.state, st)
        print(json.dumps({"observed_at": core.now_kst().isoformat(timespec="seconds"),
                          "alerts": [fact]}, ensure_ascii=False))
        return 0

    if not got["orders"]:
        if args.show:
            print("· 미체결 예약주문 0건 — 알림 없음")
        return 1

    feed = core.Feed(verbose=False)
    res = core.scan_orders(feed, verbose=False, orders=got["orders"], deadline=time.time() + 40)
    failed = {e["sym"] for e in (res.get("errors") or [])}
    seen = {o["sym"] for o in got["orders"]}
    if seen and failed >= seen:
        for e in res.get("errors") or []:
            print(f"{e['sym']}: {e['error']}", file=sys.stderr)
        return 2

    now = time.time()
    new = {}
    for al in res.get("alerts") or []:
        key = al["key"]
        last = float(st["keys"].get(key, 0) or 0)
        if args.show:
            print(f"· {al['title']} ({now - last:.0f}s 전 알림)" if last else f"· {al['title']}")
        if now - last < args.cooldown * 60:
            continue
        if len(new) >= MAX_PENDING:
            continue
        st["keys"][key] = now
        new[key] = {
            "kind": "order",
            "orderId": al.get("orderId"), "sym": al.get("sym"), "side": al.get("side"),
            "limit": al.get("limit"), "price": al.get("price"), "cond": al.get("cond"),
            "label": al.get("label"), "text": al.get("text"),
            "observed_at": core.now_kst().isoformat(timespec="seconds"),
        }
    # 오래된 쿨다운 키 정리(7일)
    for k in [k for k, v in st["keys"].items() if isinstance(v, (int, float)) and now - float(v) > 7 * 86400]:
        st["keys"].pop(k, None)

    if new:
        st["pending"] = new
        if not args.dry_run:
            save_state(args.state, st)
        return emit(new)

    if not args.dry_run:
        save_state(args.state, st)
    if args.show:
        print("· 관점 변화 없음 — 조용")
    return 1


if __name__ == "__main__":
    sys.exit(main())
