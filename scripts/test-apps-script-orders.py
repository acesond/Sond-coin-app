#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apps Script(v2) 를 가짜 스프레드시트에서 돌려 보는 테스트.

실행: python3 scripts/test-apps-script-orders.py

확인하는 것
  · 예약주문이 없던 v1 시트(매매기록 6건)를 열어도 매매기록 6건이 그대로다.
  · doPost save 에 orders 를 실으면 _OrdersJSON·예약주문 시트에 저장되고, doGet pull 이 orders 를 돌려준다.
  · orders 를 보내지 않는 예전 앱의 저장은 시트에 있는 예약주문을 지우지 않는다.
  · 취소( status:'cancelled' ) 상태가 그대로 왕복한다.
  · doGet ?callback= 은 JSONP 문자열로 응답한다.
실제 구글 시트에는 아무것도 쓰지 않습니다(모두 메모리 안 가짜 시트).
"""
import json
import sys

import quickjs

GS = open('scripts/apps-script-sync.gs', encoding='utf-8').read()

PRELUDE = r"""
globalThis.Logger = { log(){} };

globalThis.Utilities = {
  formatDate(d, tz, f) {
    const p = n => (n < 10 ? '0' : '') + n;
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
      ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }
};

function DummyRange(sheet){ this.sheet = sheet; }
['setFontWeight','setFontColor','setBackground','setHorizontalAlignment','setVerticalAlignment',
 'setNumberFormat','setFontSize','merge','clearContents'].forEach(function(m){
  DummyRange.prototype[m] = function(){ return this; };
});

function Sheet(name){ this.name = name; this.data = []; this.hidden = false; }
Sheet.prototype.getLastRow = function(){ return this.data.length; };
Sheet.prototype.clearContents = function(){ this.data = []; return this; };
Sheet.prototype.hideSheet = function(){ this.hidden = true; };
Sheet.prototype.setFrozenRows = function(){ return this; };
Sheet.prototype.setColumnWidth = function(){ return this; };
Sheet.prototype.getRange = function(r, c, nr, nc){
  const self = this;
  if (typeof r === 'string') return new DummyRange(self);
  nr = nr || 1; nc = nc || 1;
  return {
    getValues(){
      const out = [];
      for (let i = 0; i < nr; i++){
        const row = self.data[r - 1 + i] || [];
        const rr = [];
        for (let j = 0; j < nc; j++){ const v = row[c - 1 + j]; rr.push(v === undefined ? '' : v); }
        out.push(rr);
      }
      return out;
    },
    setValues(m){
      for (let i = 0; i < m.length; i++){
        const ri = r - 1 + i;
        while (self.data.length <= ri) self.data.push([]);
        const row = self.data[ri];
        for (let j = 0; j < m[i].length; j++){
          while (row.length < c - 1 + j + 1) row.push('');
          row[c - 1 + j] = m[i][j];
        }
      }
      return this;
    },
    setFontWeight(){ return this; }, setFontColor(){ return this; }, setBackground(){ return this; },
    setHorizontalAlignment(){ return this; }, setVerticalAlignment(){ return this; },
    setNumberFormat(){ return this; }, setFontSize(){ return this; }, merge(){ return this; },
    clearContents(){ return this; }
  };
};

function FakeSS(){ this.sheets = {}; this.order = []; }
FakeSS.prototype.getSheetByName = function(name){ return this.sheets[name] || null; };
FakeSS.prototype.insertSheet = function(name){ const s = new Sheet(name); this.sheets[name] = s; this.order.push(name); return s; };
FakeSS.prototype.nameList = function(){ return Object.keys(this.sheets); };

globalThis.SS = new FakeSS();
globalThis.SpreadsheetApp = {
  getActive(){ return SS; },
  openById(){ return SS; }
};
globalThis.LockService = { getScriptLock(){ return { tryLock(){ return true; }, releaseLock(){} }; } };

function Out(text){ this.text = String(text); this.mime = ''; }
Out.prototype.setMimeType = function(m){ this.mime = m; return this; };
Out.prototype.getContent = function(){ return this.text; };
globalThis.ContentService = {
  MimeType: { JSON: 'application/json', JAVASCRIPT: 'application/javascript' },
  createTextOutput(t){ return new Out(t); }
};

const __out = [];
function ok(name, cond, extra){ __out.push({ name: name, pass: !!cond, extra: extra === undefined ? '' : String(extra) }); }
function pull(){
  const r = doGet({ parameter: { action: 'pull' } });
  return JSON.parse(r.getContent());
}
function savePost(body){
  const r = doPost({ postData: { contents: JSON.stringify(body) } });
  return JSON.parse(r.getContent());
}
function sheetRows(name){ const s = SS.getSheetByName(name); return s ? s.data : null; }
"""

DRIVER = r"""
globalThis.__run = function(){
 try {
  const T0 = 1795750071222;
  /* ---------- v1 시트 재현: 매매기록 6건, 예약주문 원본 없음 ---------- */
  const j = SS.insertSheet('_JournalJSON');
  const six = [
    { id:'tl17957203800005jba', sym:'DOGEUSDT', code:'DOGE', side:'short', lev:5, margin:100, entry:0.05705, stop:0.059, t1:0.055, t2:0.053, at:T0-3600000, status:'closed', exitReason:'stop', exitAt:T0-1800000, exitPrice:0.059, roe:-17.1 },
    { id:'tl1795720380000x91u', sym:'DOGEUSDT', code:'DOGE', side:'short', lev:5, margin:100, entry:0.05705, stop:0.059, t1:0.055, t2:0.053, at:T0-3000000, status:'open' },
    { id:'tl17956563000004j2a', sym:'XRPUSDT', code:'XRP', side:'short', lev:5, margin:100, entry:0.957, stop:0.98, t1:0.93, t2:0.90, at:T0-90000000, status:'closed', exitReason:'tp2', exitAt:T0-80000000, exitPrice:0.93, roe:14.1 },
    { id:'tl1795604220000smd3', sym:'XRPUSDT', code:'XRP', side:'long', lev:5, margin:100, entry:0.91, stop:0.89, t1:0.94, t2:0.96, at:T0-140000000, status:'closed', exitReason:'tp2', exitAt:T0-130000000, exitPrice:0.94, roe:16.4 },
    { id:'tl1795517064340vdif', sym:'NEARUSDT', code:'NEAR', side:'long', lev:5, margin:100, entry:2.92, stop:2.85, t1:3.0, t2:3.06, at:T0-230000000, status:'closed', exitReason:'tp1be', exitAt:T0-220000000, exitPrice:3.0, roe:13.7 },
    { id:'seed-btc-20261124-62000', sym:'BTCUSDT', code:'BTC', side:'short', lev:5, margin:730, entry:62000, stop:63700, t1:60770, t2:59800, at:T0-300000000, status:'closed', exitReason:'tp2', exitAt:T0-290000000, exitPrice:59800, roe:13.83, seed:true, memo:'시드' }
  ];
  j.data = [['id','json']].concat(six.map(e => [e.id, JSON.stringify(e)]));
  const sy = SS.insertSheet('_Sync');
  sy.data = [['key','value'], ['schema', 1], ['updatedAt', T0], ['asset', JSON.stringify({initial:712, withdrawals:[]})], ['count', 6]];

  let p = pull();
  ok('1-1 v1 시트 매매기록 6건 그대로', p.count === 6 && p.journal.length === 6, p.count);
  ok('1-2 예약주문 0건', p.orderCount === 0 && Array.isArray(p.orders) && p.orders.length === 0, JSON.stringify(p.orders));
  ok('1-3 schema 2', p.schema === 2, p.schema);
  ok('1-4 자산 712 유지', p.asset && p.asset.initial === 712, JSON.stringify(p.asset));

  /* ---------- 예약주문 1건 저장 (미체결 대기) ---------- */
  const order = { id:'odtest1', sym:'ETHUSDT', code:'ETH', side:'long', kind:'entry',
    price:1670, margin:120, lev:5, stop:1634, t1:1712, t2:1742, feeMode:'maker',
    at:T0 + 1000, note:'박스 하단 지정가', status:'pending', hitAt:0, st:T0 + 1000 };
  let res = savePost({ action:'save', journal: six, asset:{initial:712, withdrawals:[]},
                       baseUpdatedAt: T0, orders:[order] });
  ok('2-1 저장 응답 ok', res.ok === true, JSON.stringify(res).slice(0, 120));
  ok('2-2 응답에 예약주문 1건', res.orderCount === 1 && res.orders[0].id === 'odtest1', res.orderCount);
  ok('2-3 매매기록 6건 그대로', res.count === 6, res.count);

  p = pull();
  ok('2-4 pull 예약주문 1건', p.orderCount === 1 && p.orders[0].price === 1670, JSON.stringify(p.orders));
  ok('2-5 pull 매매기록 6건 유지', p.count === 6, p.count);
  const ojRows = sheetRows('_OrdersJSON');
  ok('2-6 _OrdersJSON 1행 저장', ojRows && ojRows.length === 2 && ojRows[1][0] === 'odtest1', ojRows && ojRows.length);
  const ordRows = sheetRows('예약주문');
  ok('2-7 예약주문 시트 머리글 + 1행', ordRows && ordRows.length === 2 && ordRows[0][0] === '번호', ordRows && ordRows.length);
  ok('2-8 예약주문 시트 상태=대기', ordRows && String(ordRows[1][1]).indexOf('대기') >= 0, ordRows && ordRows[1][1]);

  /* ---------- 예전 앱(orders 없이) 저장 → 예약주문 보존 ---------- */
  res = savePost({ action:'save', journal: six, asset:{initial:712, withdrawals:[]}, baseUpdatedAt: Date.now() - 5000, force:true });
  ok('3-1 orders 없이 저장해도 예약주문 유지', res.orderCount === 1 && res.orders[0].id === 'odtest1', res.orderCount);
  ok('3-2 매매기록 6건 유지', res.count === 6, res.count);

  /* ---------- 취소 상태 왕복 ---------- */
  const cancelled = Object.assign({}, order, { status:'cancelled', st: T0 + 900000, cancelAt: T0 + 900000 });
  res = savePost({ action:'save', journal: six, asset:{initial:712, withdrawals:[]},
                   baseUpdatedAt: Date.now() - 1000, force:true, orders:[cancelled] });
  ok('4-1 취소 상태 저장', res.orders.length === 1 && res.orders[0].status === 'cancelled', JSON.stringify(res.orders[0]).slice(0, 120));
  ok('4-2 취소일시 보존', res.orders[0].cancelAt === T0 + 900000, res.orders[0].cancelAt);
  const ordRows2 = sheetRows('예약주문');
  ok('4-3 시트에 취소로 표시', ordRows2 && String(ordRows2[1][1]).indexOf('취소') >= 0, ordRows2 && ordRows2[1][1]);

  /* ---------- 체결 상태 ---------- */
  const filled = Object.assign({}, order, { status:'filled', st: T0 + 1200000, filledAt: T0 + 1200000 });
  res = savePost({ action:'save', journal: six, asset:{initial:712, withdrawals:[]},
                   baseUpdatedAt: Date.now() - 1000, force:true, orders:[filled] });
  ok('5-1 체결 상태 저장', res.orders[0].status === 'filled' && res.orders[0].filledAt === T0 + 1200000, JSON.stringify(res.orders[0]).slice(0, 120));

  /* ---------- 이상값 방어 ---------- */
  res = savePost({ action:'save', journal: six, asset:{initial:712, withdrawals:[]},
                   baseUpdatedAt: Date.now() - 1000, force:true,
                   orders:[{ id:'bad', price:0, margin:10 }, { id:'bad2', price:100, margin:0 }] });
  ok('6-1 값이 없는 예약주문은 버림', res.orderCount === 0, res.orderCount);

  /* ---------- JSONP 경로 ---------- */
  const jr = doGet({ parameter: { action:'orders', callback:'__cb' } });
  const txt = jr.getContent();
  ok('7-1 JSONP 로 예약주문 읽기', /^__cb\(/.test(txt) && txt.indexOf('"orders"') > 0, txt.slice(0, 60));

  /* ---------- 상태별 정렬/표시 ---------- */
  res = savePost({ action:'save', journal: six, asset:{initial:712, withdrawals:[]},
                   baseUpdatedAt: Date.now() - 1000, force:true,
                   orders:[{ id:'od2', sym:'BTCUSDT', code:'BTC', side:'short', price:61000, margin:100, lev:5, at:T0 + 5000, status:'pending', st:T0 + 5000 },
                           { id:'od1', sym:'BTCUSDT', code:'BTC', side:'short', price:62000, margin:100, lev:5, at:T0 + 4000, status:'pending', st:T0 + 4000 },
                           cancelled] });
  ok('8-1 대기 주문이 먼저, 최신 등록 순', res.orders[0].id === 'od2' && res.orders[1].id === 'od1', res.orders.map(o => o.id).join(','));
  ok('8-2 매매기록은 끝까지 6건', res.count === 6, res.count);

  globalThis.__result = JSON.stringify({ results: __out });
  return 1;
 } catch (e){ globalThis.__result = JSON.stringify({ results: __out, fatal: String(e && (e.message || e)) + ' || ' + String(e && e.stack) }); }
};
"""

ctx = quickjs.Context()
ctx.eval(PRELUDE + GS + DRIVER)
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
    print('FATAL:', data['fatal'][:2000])
fails = [r for r in data['results'] if not r['pass']]
for r in data['results']:
    print(('PASS ' if r['pass'] else 'FAIL ') + r['name'] + (('  → ' + r['extra']) if r['extra'] != '' else ''))
print(f"\n{len(data['results']) - len(fails)}/{len(data['results'])} passed")
sys.exit(1 if fails or data.get('fatal') else 0)
