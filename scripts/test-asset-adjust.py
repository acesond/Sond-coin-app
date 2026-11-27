#!/usr/bin/env python3
"""자산현황 «잔액 맞추기(현재 자산 보정)» 계산·저장·렌더 테스트.
   실행: python3 scripts/test-asset-adjust.py
   · index.html 의 자산현황 블록만 떼어 내, localStorage/토스트/매매기록을 흉내 낸 환경에서 돌립니다.
   · 보정 뒤 현재 자산 = 입력한 값, 실현 손익·출금은 그대로, 초기 금액(시드)은 보존되는지 확인합니다.
   · 시트 왕복(동기화)에서의 유지 여부는 test-sync-harness.py 18~19번이 봅니다.
"""
import sys, json, quickjs

HTML = open('index.html', encoding='utf-8').read()
START = '/* ---------- 자산현황 (초기 금액'
END = '/* ---------- 새벽 BTC 숏 시드'
i = HTML.find(START)
j = HTML.find(END, i)
assert i > 0 and j > i, '자산현황 블록을 찾지 못했습니다'
MODULE = HTML[i:j]

PRELUDE = r"""
globalThis.window = globalThis;
if (!globalThis.console) globalThis.console = { warn(){}, log(){} };
const LS = {};
function store(key, val){
  if (val === undefined){ const v = LS[key]; return v === undefined ? null : JSON.parse(v); }
  LS[key] = JSON.stringify(val);
  return null;
}
function isNum(v){ return typeof v === 'number' && isFinite(v); }
let __toasts = [];
function toast(title, body){ __toasts.push(String(title) + ' | ' + String(body || '')); }
function syncSchedule(){ __syncSchedules++; }
let __syncSchedules = 0;
let syncApplying = false;
function syncEnabled(){ return true; }
function renderJournal(){ __renders++; }
function refreshAutoMargin(){}
let __renders = 0;
const __els = {};
function El(id){ this.id = id; this.innerHTML = ''; this.listeners = {}; }
El.prototype.addEventListener = function(t, f){ (this.listeners[t] = this.listeners[t] || []).push(f); };
['#jAsset','#assInit','#assSave','#assFixed','#assWd','#assWdMemo','#assWdAdd'].forEach(s => { __els[s] = new El(s); });
function $(s){ return __els[s] || null; }
function kst(at, short){ return '2026-11-27 17:30'; }
function escHtml(s){ return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function hasFeeRecord(e){ return false; }          /* 수수료 정보 없는 기록 = 기존 손익 그대로 */
function roundTripFee(e){ return NaN; }
function roeOf(entry, px, side, lev){ return NaN; }
function livePriceOf(){ return NaN; }
let tradeLog = [
  { id:'a', sym:'BTCUSDT', status:'closed', margin:500, roe:16, pnl:80 },
  { id:'b', sym:'ETHUSDT', status:'closed', margin:400, roe:-5, pnl:-20 }
];
"""

DRIVER = r"""
globalThis.__run = function(){
 const out = [];
 const ok = (name, cond, extra) => out.push({ name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
 try {
  /* 1) 기본 상태 — 초기 730 + 실현 60 = 790, 보정 없음 */
  loadAssetState();
  ok('1-1 손대지 않은 상태 현재 자산 790', Math.abs(currentAsset() - 790) < 0.005, currentAsset());
  ok('1-2 화면상 초기 금액 730', Math.abs(baseAsset() - 730) < 0.005, baseAsset());
  renderAssetCard();
  const h0 = __els['#jAsset'].innerHTML;
  ok('1-3 잔액 맞추기 줄이 보임', h0.indexOf('잔액 맞추기') >= 0 && h0.indexOf('id="assFixGo"') >= 0, '');
  ok('1-4 맞추기 입력창 기본값 = 현재 자산', h0.indexOf('id="assFix"') >= 0 && h0.indexOf('value="790.00"') >= 0, '');

  /* 2) 바이낸스 잔액 785.50 으로 맞추기 — 차액 -4.50 */
  fixCurrentAsset({ value: '785.50' });
  ok('2-1 현재 자산이 입력값으로', Math.abs(currentAsset() - 785.5) < 0.005, currentAsset());
  ok('2-2 보정 1건 -4.50', assetState.corr.length === 1 && Math.abs(assetState.corr[0].delta + 4.5) < 0.005, JSON.stringify(assetState.corr));
  ok('2-3 실현 손익 그대로 60', Math.abs(realizedPnlUsd() - 60) < 0.005, realizedPnlUsd());
  ok('2-4 화면상 초기 금액(시드) 보존 730', Math.abs(baseAsset() - 730) < 0.005, baseAsset());
  ok('2-5 기준값은 725.50 으로 옮겨짐', Math.abs(assetState.initial - 725.5) < 0.005, assetState.initial);
  renderAssetCard();
  const h1 = __els['#jAsset'].innerHTML;
  ok('2-6 보정 줄이 카드에 보임', h1.indexOf('잔액 보정 1건') >= 0 && h1.indexOf('−4.50') >= 0, '');
  ok('2-7 계산식에 보정 항', h1.indexOf('보정') >= 0 && h1.indexOf('초기 <b class="num">730.00</b>') >= 0, '');
  ok('2-8 초기 금액 입력칸은 시드 730', h1.indexOf('id="assInit"') >= 0 && h1.indexOf('value="730"') >= 0, '');

  /* 3) 새로고침(다시 불러오기) 뒤에도 유지 */
  loadAssetState();
  ok('3-1 새로고침 뒤 현재 자산 785.50', Math.abs(currentAsset() - 785.5) < 0.005, currentAsset());
  ok('3-2 새로고침 뒤 보정 내역 유지', assetState.corr.length === 1, JSON.stringify(assetState.corr));

  /* 4) 위로 맞추기(+) — 800 */
  fixCurrentAsset('800');
  ok('4-1 현재 자산 800', Math.abs(currentAsset() - 800) < 0.005, currentAsset());
  ok('4-2 보정 2건 합 +10.00', assetState.corr.length === 2 && Math.abs(totalCorrections() - 10) < 0.005, totalCorrections());
  ok('4-3 시드 그대로 730', Math.abs(baseAsset() - 730) < 0.005, baseAsset());

  /* 5) 마지막 보정 삭제 → 785.50 으로 되돌아감 */
  const lastId = assetState.corr[assetState.corr.length - 1].id;
  delCorrection(lastId);
  ok('5-1 삭제 뒤 785.50', Math.abs(currentAsset() - 785.5) < 0.005, currentAsset());
  ok('5-2 보정 1건 남음', assetState.corr.length === 1, assetState.corr.length);

  /* 6) 같은 금액으로 맞추기 → 아무것도 안 바뀜 */
  const beforeCorr = assetState.corr.length, beforeInit = assetState.initial;
  fixCurrentAsset('785.50');
  ok('6-1 보정이 늘지 않음', assetState.corr.length === beforeCorr, assetState.corr.length);
  ok('6-2 기준값 그대로', assetState.initial === beforeInit, assetState.initial);
  ok('6-3 이미 맞습니다 안내', (__toasts[__toasts.length - 1] || '').indexOf('이미 맞습니다') >= 0, __toasts[__toasts.length - 1]);

  /* 7) 초기 금액 수정 — 시드는 새 값, 보정은 유지 */
  setInitialAmount('700');
  ok('7-1 화면상 초기 금액 700', Math.abs(baseAsset() - 700) < 0.005, baseAsset());
  ok('7-2 현재 자산 700 + 60 − 4.50 = 755.50', Math.abs(currentAsset() - 755.5) < 0.005, currentAsset());
  ok('7-3 보정 내역 유지', assetState.corr.length === 1, assetState.corr.length);

  /* 8) 출금을 넣어도 맞추기는 그때 계산으로 동작 */
  addWithdrawal({ value: '50' }, { value: '생활비' });
  ok('8-1 출금 반영 705.50', Math.abs(currentAsset() - 705.5) < 0.005, currentAsset());
  fixCurrentAsset('650');
  ok('8-2 출금 뒤 맞추기 650', Math.abs(currentAsset() - 650) < 0.005, currentAsset());
  ok('8-3 보정 2건', assetState.corr.length === 2, assetState.corr.length);
  ok('8-4 총 출금은 50 그대로', Math.abs(totalWithdrawals() - 50) < 0.005, totalWithdrawals());

  /* 9) 잘못된 입력은 거부 */
  const nCorr = assetState.corr.length;
  fixCurrentAsset('abc');
  ok('9-1 문자 입력 거부', assetState.corr.length === nCorr, assetState.corr.length);
  fixCurrentAsset('-5');
  ok('9-2 음수 입력 거부', assetState.corr.length === nCorr, assetState.corr.length);

  /* 10) 동기화에 올라가는 값 = 보정 반영 기준값 */
  ok('10-1 시트로 갈 initial = 시드 + 보정합', Math.abs(assetState.initial - (baseAsset() + totalCorrections())) < 0.005,
     assetState.initial + ' vs ' + (baseAsset() + totalCorrections()));
  ok('10-2 보정도 저장 요청을 부름', __syncSchedules > 0, __syncSchedules);

  globalThis.__result = JSON.stringify({ results: out });
  return 1;
 } catch (e){ globalThis.__result = JSON.stringify({ results: out, fatal: String(e && (e.message || e)) + ' || ' + String(e && e.stack) }); }
};
"""

ctx = quickjs.Context()
ctx.eval(PRELUDE + MODULE + DRIVER)
ctx.eval('__run()')
for _ in range(20000):
    if not ctx.execute_pending_job():
        break
raw = ctx.get('__result')
data = json.loads(raw) if raw else None
if data is None:
    print('RAW: no result')
    sys.exit(1)
if data.get('fatal'):
    print('FATAL:', data['fatal'][:1500])
fails = [r for r in data['results'] if not r['pass']]
for r in data['results']:
    print(('PASS ' if r['pass'] else 'FAIL ') + r['name'] + (('  → ' + str(r['extra'])) if r['extra'] != '' else ''))
print(f"\n{len(data['results']) - len(fails)}/{len(data['results'])} passed")
sys.exit(1 if fails else 0)
