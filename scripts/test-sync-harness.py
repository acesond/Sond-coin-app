#!/usr/bin/env python3
"""구글 시트 동기화 클라이언트(index.html 안 sync 모듈)를 가짜 서버로 돌려 보는 테스트.
   실행: python3 scripts/test-sync-harness.py
   · index.html 에서 sync 모듈 블록만 떼어 내, DOM/localStorage/fetch를 흉내 낸 환경에서 돌립니다."""
import re, sys, json, quickjs

HTML = open('index.html', encoding='utf-8').read()
START = '/* ========================= 구글 시트 자동 동기화'
END = '/* 진입 시점 근거 스냅샷 */'
i = HTML.find(START)
j = HTML.find(END, i)
assert i > 0 and j > i, 'sync 모듈 블록을 찾지 못했습니다'
MODULE = HTML[i:j]

PRELUDE = r"""
globalThis.window = globalThis;
globalThis.addEventListener = function(){};
if (!globalThis.console) globalThis.console = { warn(){}, log(){} };
const __timers = []; let __tid = 1;
globalThis.setTimeout = function(fn, ms){ const id = __tid++; __timers.push({id, fn, ms: ms||0}); return id; };
globalThis.clearTimeout = function(id){ const k = __timers.findIndex(t => t.id === id); if (k >= 0) __timers.splice(k,1); };
function flushTimers(){
  let n = 0;
  while (__timers.length && n < 50){ const t = __timers.shift(); n++; try { t.fn(); } catch(e){ __log.push('timer error: ' + e.message); } }
  return n;
}
const __log = [];
function El(id){ this.id = id; this.innerHTML = ''; this.className = ''; this.title = ''; this.textContent = '';
  this.classList = { contains(){ return false; }, add(){}, remove(){}, toggle(){} };
  this.listeners = {}; }
El.prototype.addEventListener = function(t, f){ (this.listeners[t] = this.listeners[t] || []).push(f); };
El.prototype.setAttribute = function(){};
El.prototype.appendChild = function(){};
El.prototype.closest = function(){ return null; };
El.prototype.focus = function(){};
const __els = {};
['#syncPillTop','#syncPillJournal','#jSyncNote','#pgJournalN','#jHint','#jList','#jAsset'].forEach(s => { __els[s] = new El(s); });
globalThis.document = {
  head: { appendChild(script){
    const src = String(script.src || '');
    const m = /callback=([A-Za-z0-9_$]+)/.exec(src);
    Promise.resolve().then(function(){
      if (!m) { script.onerror && script.onerror(); return; }
      const fn = globalThis[m[1]];
      if (typeof fn === 'function') fn(srvGet());
    });
  } },
  body: { classList: { add(){}, remove(){} }, contains(){ return true; } },
  activeElement: null,
  createElement(tag){ return { tagName: String(tag).toUpperCase(), src: '', onerror: null, parentNode: null }; },
  querySelector(s){ return __els[s] || null; },
  addEventListener(){}
};
const $ = s => __els[s] || null;
function store(key, val){
  if (val === undefined){ const raw = localStorage[key]; return raw ? JSON.parse(raw) : undefined; }
  localStorage[key] = JSON.stringify(val); return val;
}
const localStorage = {};
function isNum(v){ return typeof v === 'number' && isFinite(v); }

/* 가짜 Apps Script 서버 */
const SRV = { updatedAt: 0, journal: [], asset: { initial: 730, withdrawals: [] }, mode: 'ok', jsonp: 'ok', saves: [], pulls: 0 };
const clone = o => JSON.parse(JSON.stringify(o));
function srvGet(){ SRV.pulls++; return { ok:true, schema:1, updatedAt: SRV.updatedAt || 1, count: SRV.journal.length, journal: clone(SRV.journal), asset: clone(SRV.asset) }; }
function srvPost(body){
  SRV.saves.push(clone(body));
  const base = Number(body.baseUpdatedAt);
  const stale = !body.force && isFinite(base) && SRV.updatedAt > 0 && SRV.updatedAt > base + 1500;
  if (stale) return { ok:false, error:'stale', reason:'stale', updatedAt: SRV.updatedAt, count: SRV.journal.length, journal: clone(SRV.journal), asset: clone(SRV.asset) };
  SRV.journal = clone(body.journal || []); SRV.asset = clone(body.asset || SRV.asset);
  SRV.updatedAt = Date.now();
  return { ok:true, updatedAt: SRV.updatedAt, count: SRV.journal.length, journal: clone(SRV.journal), asset: clone(SRV.asset) };
}
function mkRes(data){ return { ok:true, status:200, text(){ return Promise.resolve(JSON.stringify(data)); } }; }
globalThis.fetch = function(url, opt){
  opt = opt || {};
  if (SRV.mode === 'down') return Promise.reject(new TypeError('Failed to fetch'));
  if (!opt.method || opt.method === 'GET'){
    if (String(url).indexOf('callback=') >= 0) return Promise.reject(new TypeError('CORS'));
    if (SRV.mode === 'corsget') return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve(mkRes(srvGet()));
  }
  if (opt.mode === 'no-cors'){ srvPost(JSON.parse(opt.body)); return Promise.resolve({ ok:true, status:0, type:'opaque', text(){ return Promise.resolve(''); } }); }
  if (SRV.mode === 'corspost') return Promise.reject(new TypeError('Failed to fetch'));
  return Promise.resolve(mkRes(srvPost(JSON.parse(opt.body))));
};

/* 앱 쪽 스텁 */
const LOG_KEY = 'maeyo.tradeLog.v1', ASSET_KEY = 'maeyo.assetState.v1', SEED_DEL_KEY = 'maeyo.seedDeleted.v1';
const __render = { journal:0, auto:0, badge:0 };
function renderJournal(){ __render.journal++; }
function refreshAutoMargin(){ __render.auto++; }
function updateJournalBadges(){ __render.badge++; }
let tradeLog = [];
let assetState = { initial: 730, withdrawals: [] };
function saveTradeLog(){ store(LOG_KEY, tradeLog); updateJournalBadges(); syncSchedule(); }
function saveAssetState(){ store(ASSET_KEY, assetState); if (!syncApplying) syncSchedule(); }
const SEED = { id:'seed-btc-20261124-62000', sym:'BTCUSDT', code:'BTC', side:'short', lev:5, margin:730,
  entry:62000, stop:63700, t1:60770, t2:59800, at:1795449600000, status:'closed', exitReason:'tp2',
  exitAt:1795489200000, exitPrice:59800, roe:13.83, pnl:100.96, seed:true, memo:'시드' };
const ENTRY2 = { id:'tl-test-1', sym:'ETHUSDT', code:'ETH', side:'long', lev:5, margin:100,
  entry:3000, stop:2900, t1:3200, t2:3300, at:1795600000000, status:'open', memo:'' };
function badge(){ const e = __els['#syncPillTop']; return { cls: e.className, txt: e.innerHTML.replace(/<[^>]+>/g,'') }; }
function reset(opt){
  Object.keys(localStorage).forEach(k => delete localStorage[k]);
  SRV.updatedAt = 0; SRV.journal = []; SRV.asset = { initial: 730, withdrawals: [] };
  SRV.mode = 'ok'; SRV.jsonp = 'ok'; SRV.saves = []; SRV.pulls = 0;
  __timers.length = 0; __log.length = 0;
  tradeLog = [clone(SEED)]; assetState = { initial: 730, withdrawals: [] };
  syncBusy = false; syncApplying = false; clearTimeout(syncTimer); syncTimer = null;
  syncState = { kind:'idle', at:0, msg:'' };
  if (opt && opt.serverHasSeed){ SRV.journal = [clone(SEED)]; SRV.updatedAt = 1795500000000; }
  if (opt && opt.serverBumps && SRV.updatedAt > 0) SRV.updatedAt += 60000;
}
const __out = [];
function ok(name, cond, extra){ __out.push({ name, pass: !!cond, extra: extra === undefined ? '' : extra }); }
async function pump(n){ for (let i = 0; i < (n || 12); i++){ await Promise.resolve(); } }
"""

DRIVER = r"""
globalThis.__run = async function(){
 try {
  /* 1) 첫 진입 — 서버에 시드 1건, 이 기기에도 같은 시드 → pull+merge 후 push */
  reset({ serverHasSeed: true });
  syncInit();
  flushTimers();
  await pump(30);
  ok('1-1 첫 동기화 성공 배지', badge().cls.indexOf('ok') >= 0, badge().txt);
  ok('1-2 서버 기록 1건 유지', SRV.journal.length === 1, SRV.journal.map(e => e.id).join(','));
  ok('1-3 자산 730 유지', SRV.asset.initial === 730, SRV.asset.initial);
  ok('1-4 기록 화면 다시 그려짐', __render.journal > 0, __render.journal);
  ok('1-5 updatedAt 저장', syncLastTs() > 0, syncLastTs());

  /* 2) 이 기기에서 새 진입 → 저장 후 자동 push */
  reset({ serverHasSeed: true });
  store(SYNC_TS_KEY, 1795500000000);          /* 1단계에서 맞춘 상태로 가정 */
  tradeLog = [clone(SEED), clone(ENTRY2)];
  saveTradeLog();
  flushTimers();
  await pump(30);
  ok('2-1 서버에 2건 저장', SRV.journal.length === 2, SRV.journal.map(e => e.id).join(','));
  ok('2-2 새 기록 id 포함', SRV.journal.some(e => e.id === 'tl-test-1'), '');
  ok('2-3 동기화됨 배지', badge().cls.indexOf('ok') >= 0, badge().txt);

  /* 3) 다른 기기가 먼저 저장(stale) → 합친 뒤 강제 저장 */
  reset({ serverHasSeed: true });
  store(SYNC_TS_KEY, 1795500000000);
  const closedRemote = Object.assign(clone(ENTRY2), { status:'closed', exitReason:'tp2', exitAt:1795700000000, exitPrice:3300, roe:50, pnl:50 });
  SRV.journal = [clone(SEED), closedRemote];
  SRV.updatedAt = 1795500000000 + 60000;      /* 내가 아는 시각보다 앞서 있음 */
  tradeLog = [clone(SEED), clone(ENTRY2)];    /* 이 기기엔 아직 진행 중 */
  saveTradeLog();
  flushTimers();
  await pump(40);
  const e2 = SRV.journal.find(e => e.id === 'tl-test-1');
  ok('3-1 stale 뒤 청산본으로 합쳐짐', e2 && e2.status === 'closed', e2 && e2.status);
  ok('3-2 서버 기록 2건 유지', SRV.journal.length === 2, SRV.journal.length);
  ok('3-3 동기화됨 배지', badge().cls.indexOf('ok') >= 0, badge().txt);

  /* 4) GET이 CORS로 막힘 → JSONP로 pull */
  reset({ serverHasSeed: true });
  SRV.mode = 'corsget';
  syncInit();
  flushTimers();
  await pump(40);
  ok('4-1 JSONP 우회로 pull 성공', SRV.pulls > 0 && SRV.journal.length === 1, 'pulls=' + SRV.pulls);
  ok('4-2 동기화됨 배지', badge().cls.indexOf('ok') >= 0, badge().txt);

  /* 5) 서버 완전 다운 → 실패 배지, 로컬 기록 유지 */
  reset({ serverHasSeed: true });
  SRV.mode = 'down';
  tradeLog = [clone(SEED), clone(ENTRY2)];
  syncInit();
  flushTimers();
  await pump(40);
  ok('5-1 실패 배지', badge().cls.indexOf('err') >= 0, badge().txt);
  ok('5-2 로컬 기록 2건 그대로', tradeLog.length === 2, tradeLog.length);
  ok('5-3 시트 쓰기 없음', SRV.saves.length === 0, SRV.saves.length);

  /* 6) 시드를 지운 기기 → 지운 시드는 다시 올리지 않음 */
  reset({ serverHasSeed: true });
  store(SEED_DEL_KEY, ['seed-btc-20261124-62000']);
  store(SYNC_TS_KEY, 1795500000000);
  tradeLog = [clone(ENTRY2)];
  saveTradeLog();
  flushTimers();
  await pump(30);
  ok('6-1 서버에 시드 없음', !SRV.journal.some(e => e.id === 'seed-btc-20261124-62000'), SRV.journal.map(e => e.id).join(','));
  ok('6-2 내 기록은 올라감', SRV.journal.some(e => e.id === 'tl-test-1'), '');

  /* 7) 자산 수정 → 자동 push */
  reset({ serverHasSeed: true });
  store(SYNC_TS_KEY, 1795500000000);
  assetState = { initial: 1000, withdrawals: [{ id:'wd1', at:1795600000000, usd: 50, memo:'출금' }] };
  saveAssetState();
  flushTimers();
  await pump(30);
  ok('7-1 서버 자산 반영', SRV.asset && SRV.asset.initial === 1000 && SRV.asset.withdrawals.length === 1,
     JSON.stringify(SRV.asset));

  /* 8) POST 응답이 CORS로 막힘 — no-cors로 보내고 pull로 확인 */
  reset({ serverHasSeed: true });
  store(SYNC_TS_KEY, 1795500000000);
  SRV.mode = 'corspost';
  tradeLog = [clone(SEED), clone(ENTRY2)];
  saveTradeLog();
  flushTimers();
  await pump(50);
  ok('8-1 no-cors 전송으로 서버 저장', SRV.journal.length === 2, SRV.journal.map(e => e.id).join(','));
  ok('8-2 동기화됨 배지', badge().cls.indexOf('ok') >= 0, badge().txt);

  /* 9) 가짜 테스트 기록 숙청 — 폰이 새 버전을 여는 순간 localStorage·시트에서 함께 사라지고 다시 안 올라감 */
  reset({});
  store(SYNC_TS_KEY, 1795500000000);
  const T_WIN  = { id:'t-win', sym:'BTCUSDT', code:'BTC', side:'short', lev:5, margin:100, entry:62000,
    stop:63000, t1:60000, t2:59800, at:1795500000000, status:'closed', exitReason:'tp2', roe:88.7, memo:'테스트 승' };
  const T_LOSS = { id:'t-loss', sym:'ETHUSDT', code:'ETH', side:'long', lev:5, margin:100, entry:1700,
    stop:1600, t1:1800, t2:1900, at:1795500000000, status:'closed', exitReason:'stop', roe:-8.82, memo:'테스트 패' };
  const T_OPEN = { id:'t-open', sym:'SOLUSDT', code:'SOL', side:'short', lev:5, margin:50, entry:72,
    stop:76, t1:68, t2:64, at:1795600000000, status:'open', memo:'테스트 진행' };
  const T_BTC  = { id:'tl17955490867980uya', sym:'BTCUSDT', code:'BTC', side:'long', lev:5, margin:200,
    entry:60200, stop:59700, t1:61200, t2:61700, at:1795549086798, status:'closed', exitReason:'stop', roe:-4.15, memo:'' };
  const T_MEMO = { id:'tl-old-fake-77', sym:'XRPUSDT', code:'XRP', side:'long', lev:5, margin:10,
    entry:0.9, stop:0.88, t1:0.95, t2:1, at:1795300000000, status:'closed', exitReason:'stop', roe:-2, memo:'테스트' };
  const fakes = [T_WIN, T_LOSS, T_OPEN, T_BTC, T_MEMO];
  SRV.journal = [clone(SEED)].concat(fakes.map(clone));
  SRV.updatedAt = 1795500000000;
  tradeLog = [clone(SEED)].concat(fakes.map(clone));
  syncInit();
  flushTimers();
  await pump(50);
  ok('9-1 이 기기에서 가짜 5건 삭제', tradeLog.length === 1 && tradeLog[0].id === SEED.id,
     tradeLog.map(e => e.id).join(','));
  ok('9-2 시트에서도 가짜 5건 삭제', SRV.journal.length === 1 && SRV.journal[0].id === SEED.id,
     SRV.journal.map(e => e.id).join(','));
  const dset9 = Array.from(deletedIdSet());
  ok('9-3 지운 목록에 5건 기록', fakes.every(f => dset9.indexOf(f.id) >= 0), dset9.join(','));

  /* 10) 다른 기기에서 지운 기록은 이 기기에서도 사라지고 되살아나지 않음 */
  reset({});
  const T0 = 1795500000000;
  store(SYNC_TS_KEY, T0);
  store(SYNC_SEEN_KEY, [SEED.id, ENTRY2.id]);     /* 지난번엔 둘 다 시트에 있었음 */
  SRV.journal = [clone(SEED)];                   /* 그 사이 다른 기기가 tl-test-1을 삭제·저장 */
  SRV.updatedAt = T0 + 60000;
  tradeLog = [clone(SEED), clone(ENTRY2)];
  syncInit();
  flushTimers();
  await pump(50);
  ok('10-1 다른 기기 삭제가 이 기기에 반영', !tradeLog.some(e => e.id === ENTRY2.id), tradeLog.map(e => e.id).join(','));
  ok('10-2 다시 올라가지 않음', !SRV.journal.some(e => e.id === ENTRY2.id), SRV.journal.map(e => e.id).join(','));
  ok('10-3 지운 목록에 기록', deletedIdSet().has(ENTRY2.id), Array.from(deletedIdSet()).join(','));

  /* 11) 서버에 아직 남아 있어도 지운 기록은 pull 때 걸러짐(옛 복사본 부활 방지) */
  reset({});
  store(SYNC_TS_KEY, 1795500000000);
  store(DEL_KEY, [ENTRY2.id]);
  SRV.journal = [clone(SEED), clone(ENTRY2)];
  SRV.updatedAt = 1795500000000;
  tradeLog = [clone(SEED)];
  syncNow();
  await pump(50);
  ok('11-1 이 기기에 되살아나지 않음', !tradeLog.some(e => e.id === ENTRY2.id), tradeLog.map(e => e.id).join(','));
  ok('11-2 시트에서도 정리됨', !SRV.journal.some(e => e.id === ENTRY2.id), SRV.journal.map(e => e.id).join(','));

  globalThis.__result = JSON.stringify({ results: __out, log: __log });
  return 1;
 } catch (e){ globalThis.__result = JSON.stringify({ results: __out, log: __log, fatal: String(e && (e.message || e)) + ' || ' + String(e && e.stack) }); }
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
    print('RAW: no result; log=', ctx.get('__log'))
    sys.exit(1)
if data.get('fatal'): print('FATAL:', data['fatal'][:1500])
fails = [r for r in data['results'] if not r['pass']]
for r in data['results']:
    print(('PASS ' if r['pass'] else 'FAIL ') + r['name'] + (('  → ' + str(r['extra'])) if r['extra'] != '' else ''))
if data['log']:
    print('log:', data['log'])
print(f"\n{len(data['results']) - len(fails)}/{len(data['results'])} passed")
sys.exit(1 if fails else 0)
