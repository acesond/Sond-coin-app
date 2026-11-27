/**
 * 코인 매매기록 동기화 — Google Apps Script (V8)
 * ──────────────────────────────────────────────────────────────
 * 대상 스프레드시트: "코인 매매기록 동기화"
 *   https://docs.google.com/spreadsheets/d/13U4opKJqUnW06BWhEyeWb7MxHXLt6KvYwQcveew2euI/edit
 *
 * 쓰는 법 (딱 한 번)
 *   1. 시트를 열고  확장 프로그램 → Apps Script   (PC 크롬 권장 — 폰 시트 앱에는 이 메뉴가 없습니다)
 *      · 폰만 있으면 script.google.com → 새 프로젝트에서도 됩니다(아래 SPREADSHEET_ID로 시트를 엽니다)
 *   2. 기본 Code.gs 내용을 모두 지우고 이 파일 전체를 붙여넣기 → 저장(Ctrl+S)
 *   3. 배포 → 새 배포 → 유형 '웹 앱'
 *        · 설명: 매매기록 동기화
 *        · 다음 사용자로 실행: 나
 *        · 액세스 권한: 모든 사용자(Anyone)   ← 폰 브라우저에서 부르려면 필요
 *   4. 배포 후 나오는 '웹 앱 URL'(…/exec)을 복사해 피클에게 전달
 *      → 피클이 웹앱(index.html)의 SYNC_URL 에 넣고 배포합니다.
 *
 * 통신 규칙 (GitHub Pages에서 CORS 프리플라이트 없이 부르기 위한 규칙)
 *   · 읽기(GET)  : <웹앱URL>            → JSON 문자열 그대로 응답
 *                  <웹앱URL>?callback=cb  → JSONP(cb({…})) 로도 응답 (CORS가 막힐 때 보조)
 *   · 쓰기(POST) : <웹앱URL>  Content-Type: text/plain;charset=utf-8
 *                  본문 = JSON 문자열 (application/json 으로 보내면 프리플라이트가 떠서 실패할 수 있음)
 *
 * 시트 구성
 *   · 매매기록   : 사람이 보는 표 (진입일시·종목·방향·진입가·청산가·레버리지·증거금·손익·ROE·결과·메모)
 *   · 요약       : 자산현황 · 매매 요약 · 마지막 동기화 시각
 *   · 출금내역   : 출금 기록 표
 *   · _JournalJSON : (숨김) 매매 1건 = 1행, 앱이 쓰는 원본 JSON
 *   · 예약주문     : (보임) 앱의 미체결 예약주문 표 (지정가·증거금·SL·TP·상태)
 *   · _OrdersJSON  : (숨김) 예약주문 1건 = 1행, 앱이 쓰는 원본 JSON
 *   · _Sync        : (숨김) 자산 설정·수정시각 등 메타 정보
 *   원본은 _JournalJSON + _OrdersJSON + _Sync 이고, 나머지 시트는 매번 원본에서 다시 그려집니다.
 *   (시트에서 직접 고친 표 내용은 다음 동기화 때 원본 값으로 되돌아갑니다.)
 *
 * v2 (2026-11-27 추가): 예약주문(지정가 대기) 동기화
 *   · doGet  pull 응답에 orders(예약주문 배열)·ordersUpdatedAt·orderCount 를 더했습니다. (기존 필드는 그대로)
 *   · doPost save 본문에 orders 배열이 있으면 그것을 예약주문 원본으로 저장합니다.
 *     orders 를 보내지 않는 예전 앱의 저장은 지금 시트에 있는 예약주문을 지우지 않습니다.
 *   · 예약주문은 매매기록(journal)과 완전히 분리돼 있어 승률·자산·매매기록 표에 영향이 없습니다.
 *
 * v3 (2026-11-27 추가): 예약주문 '감시 기준' 보관
 *   · 주문마다 source 필드(manual = 가설 / auto1 = 🤖 자동 1 / custom = 직접 입력)를 같이 저장합니다.
 *     관점 감시(ntfy_alert.py)가 수동 가설선과 자동 1 후보를 섞지 않고 각자 기준으로 판정하려면 필요합니다.
 *   · 값이 없는 예전 주문은 빈 문자열로 두고, 감시 쪽이 지정가·손절가를 가설과 비교해 추정합니다.
 *     (이 코드를 다시 배포하지 않아도 감시는 그대로 동작하고, 배포하면 '감시 기준' 칸이 채워집니다.)
 */

const SCHEMA_VERSION = 2;
const SPREADSHEET_ID = '13U4opKJqUnW06BWhEyeWb7MxHXLt6KvYwQcveew2euI';
const TZ = 'Asia/Seoul';
const DEFAULT_INITIAL = 730;          // 앱의 ASSET_DEFAULT 와 동일

const SHEET_JOURNAL  = '매매기록';
const SHEET_SUMMARY  = '요약';
const SHEET_WITHDRAW = '출금내역';
const SHEET_ORDERS   = '예약주문';
const SHEET_JSON     = '_JournalJSON';
const SHEET_ORDERS_JSON = '_OrdersJSON';
const SHEET_STATE    = '_Sync';

const JOURNAL_HEADERS = [
  '번호', '진입일시(KST)', '청산일시(KST)', '종목', '방향', '레버리지',
  '진입가', '청산가', '증거금(USDT)', '손익(USDT)', 'ROE(%)',
  '결과', '청산사유', '메모', '기록ID'
];

const ORDER_HEADERS = [
  '번호', '상태', '등록일시(KST)', '종목', '방향', '종류', '지정가', '증거금(USDT)',
  '레버리지', '주문금액(USDT)', '손절(SL)', 'TP1', 'TP2', '메모', '감시 기준', '주문ID'
];

/* ───────────────────────── HTTP 진입점 ───────────────────────── */

function doGet(e) {
  const cb = e && e.parameter && e.parameter.callback;
  try {
    const action = (e && e.parameter && e.parameter.action) || 'pull';
    const st = readState_();

    let payload;
    if (action === 'ping') {
      payload = { ok: true, schema: SCHEMA_VERSION, updatedAt: st.updatedAt, count: st.journal.length };
    } else if (action === 'pull') {
      payload = {
        ok: true,
        schema: SCHEMA_VERSION,
        updatedAt: st.updatedAt,
        count: st.journal.length,
        journal: st.journal,
        asset: st.asset,
        ordersUpdatedAt: st.ordersUpdatedAt,
        orderCount: st.orders.length,
        orders: st.orders
      };
    } else if (action === 'orders') {
      payload = {
        ok: true,
        schema: SCHEMA_VERSION,
        ordersUpdatedAt: st.ordersUpdatedAt,
        orderCount: st.orders.length,
        orders: st.orders
      };
    } else {
      payload = { ok: false, error: 'unknown action: ' + action };
    }

    // JSONP 보조 경로 — 어떤 브라우저에서 CORS가 막혀도 읽기만은 되게
    if (cb && /^[A-Za-z_$][A-Za-z0-9_$.]*$/.test(String(cb))) return jsonp_(String(cb), payload);
    return json_(payload);
  } catch (err) {
    const payload = { ok: false, error: errText_(err) };
    if (cb && /^[A-Za-z_$][A-Za-z0-9_$.]*$/.test(String(cb))) return jsonp_(String(cb), payload);
    return json_(payload);
  }
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    if (!lock.tryLock(25000)) return json_({ ok: false, error: 'busy', retry: true });

    const body = readBody_(e);
    if (!body) return json_({ ok: false, error: 'JSON 본문을 읽지 못했습니다.' });

    const action = body.action || 'save';
    const st = readState_();

    if (action === 'pull' || action === 'get') {
      return json_({ ok: true, schema: SCHEMA_VERSION, updatedAt: st.updatedAt,
                     count: st.journal.length, journal: st.journal, asset: st.asset,
                     ordersUpdatedAt: st.ordersUpdatedAt, orderCount: st.orders.length, orders: st.orders });
    }

    if (action === 'save' || action === 'replace') {
      if (!Array.isArray(body.journal)) return json_({ ok: false, error: 'journal 배열이 필요합니다.' });

      const base = numOr_(body.baseUpdatedAt, NaN);
      const stale = !body.force && isFinite(base) && st.updatedAt > 0 && st.updatedAt > base + 1500;
      if (stale) {
        // 다른 기기가 먼저 저장했습니다. 덮어쓰지 않고 최신 상태를 돌려줍니다.
        return json_({ ok: false, error: 'stale', reason: 'stale',
                       updatedAt: st.updatedAt, count: st.journal.length,
                       journal: st.journal, asset: st.asset });
      }

      // 예약주문: 이번 저장 본문에 orders 가 있으면 통째로 교체, 없으면(예전 앱) 지금 것을 그대로 둡니다.
      const hasOrders = Array.isArray(body.orders);
      const next = {
        schema: SCHEMA_VERSION,
        updatedAt: Date.now(),
        asset: normalizeAsset_(body.asset),
        journal: sortJournal_(body.journal.map(cleanEntry_).filter(Boolean)),
        orders: hasOrders ? sortOrders_(body.orders.map(cleanOrder_).filter(Boolean)) : st.orders,
        ordersUpdatedAt: hasOrders ? Date.now() : st.ordersUpdatedAt
      };
      writeState_(next);
      return json_({ ok: true, updatedAt: next.updatedAt, count: next.journal.length,
                     journal: next.journal, asset: next.asset,
                     ordersUpdatedAt: next.ordersUpdatedAt, orderCount: next.orders.length, orders: next.orders });
    }

    if (action === 'upsert') {
      const entry = cleanEntry_(body.entry);
      if (!entry) return json_({ ok: false, error: 'entry 객체가 필요합니다.' });

      const journal = st.journal.slice();
      const i = journal.findIndex(x => x.id === entry.id);
      if (i >= 0) journal[i] = entry; else journal.push(entry);

      const next = {
        schema: SCHEMA_VERSION,
        updatedAt: Date.now(),
        asset: body.asset ? normalizeAsset_(body.asset) : st.asset,
        journal: sortJournal_(journal),
        orders: Array.isArray(body.orders) ? sortOrders_(body.orders.map(cleanOrder_).filter(Boolean)) : st.orders,
        ordersUpdatedAt: Array.isArray(body.orders) ? Date.now() : st.ordersUpdatedAt
      };
      writeState_(next);
      return json_({ ok: true, updatedAt: next.updatedAt, count: next.journal.length,
                     journal: next.journal, asset: next.asset,
                     ordersUpdatedAt: next.ordersUpdatedAt, orderCount: next.orders.length, orders: next.orders });
    }

    if (action === 'delete') {
      const ids = (Array.isArray(body.ids) ? body.ids : (body.id ? [body.id] : [])).map(String);
      if (!ids.length) return json_({ ok: false, error: 'ids 배열이 필요합니다.' });

      const next = {
        schema: SCHEMA_VERSION,
        updatedAt: Date.now(),
        asset: body.asset ? normalizeAsset_(body.asset) : st.asset,
        journal: st.journal.filter(x => ids.indexOf(String(x.id)) < 0),
        orders: st.orders,
        ordersUpdatedAt: st.ordersUpdatedAt
      };
      writeState_(next);
      return json_({ ok: true, updatedAt: next.updatedAt, count: next.journal.length,
                     journal: next.journal, asset: next.asset,
                     ordersUpdatedAt: next.ordersUpdatedAt, orderCount: next.orders.length, orders: next.orders });
    }

    if (action === 'asset') {
      const next = {
        schema: SCHEMA_VERSION,
        updatedAt: Date.now(),
        asset: normalizeAsset_(body.asset),
        journal: st.journal,
        orders: st.orders,
        ordersUpdatedAt: st.ordersUpdatedAt
      };
      writeState_(next);
      return json_({ ok: true, updatedAt: next.updatedAt, count: next.journal.length,
                     journal: next.journal, asset: next.asset,
                     ordersUpdatedAt: next.ordersUpdatedAt, orderCount: next.orders.length, orders: next.orders });
    }

    return json_({ ok: false, error: 'unknown action: ' + action });
  } catch (err) {
    return json_({ ok: false, error: errText_(err) });
  } finally {
    try { lock.releaseLock(); } catch (_) {}
  }
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function jsonp_(cb, obj) {
  return ContentService.createTextOutput(cb + '(' + JSON.stringify(obj) + ');')
    .setMimeType(ContentService.MimeType.JAVASCRIPT);
}

function readBody_(e) {
  let text = '';
  try {
    if (e && e.postData && e.postData.contents) text = e.postData.contents;
  } catch (_) {}
  if (!text && e && e.parameter && e.parameter.payload) text = e.parameter.payload;
  if (!text) return null;
  try { return JSON.parse(text); } catch (_) { return null; }
}

function errText_(err) {
  return String((err && err.message) || err || 'unknown error');
}

/* ───────────────────────── 원본 읽기/쓰기 ───────────────────────── */

function readState_() {
  const ss = spreadsheet_();
  const st = { schema: SCHEMA_VERSION, updatedAt: 0, ordersUpdatedAt: 0,
               asset: normalizeAsset_(null), journal: [], orders: [] };

  const sync = ss.getSheetByName(SHEET_STATE);
  if (sync && sync.getLastRow() > 1) {
    const vals = sync.getRange(2, 1, sync.getLastRow() - 1, 2).getValues();
    const kv = {};
    vals.forEach(r => { if (r[0] !== '' && r[0] != null) kv[String(r[0])] = r[1]; });
    if (kv.updatedAt) st.updatedAt = Number(kv.updatedAt) || 0;
    if (kv.ordersUpdatedAt) st.ordersUpdatedAt = Number(kv.ordersUpdatedAt) || 0;
    if (kv.asset) { try { st.asset = normalizeAsset_(JSON.parse(String(kv.asset))); } catch (_) {} }
  }

  const js = ss.getSheetByName(SHEET_JSON);
  if (js && js.getLastRow() > 1) {
    const vals = js.getRange(2, 1, js.getLastRow() - 1, 2).getValues();
    for (let i = 0; i < vals.length; i++) {
      const raw = vals[i][1];
      if (!raw) continue;
      try {
        const o = JSON.parse(String(raw));
        if (o && o.id) st.journal.push(o);
      } catch (_) { /* 깨진 행은 건너뜀 */ }
    }
  }

  const oj = ss.getSheetByName(SHEET_ORDERS_JSON);
  if (oj && oj.getLastRow() > 1) {
    const vals = oj.getRange(2, 1, oj.getLastRow() - 1, 2).getValues();
    for (let i = 0; i < vals.length; i++) {
      const raw = vals[i][1];
      if (!raw) continue;
      try {
        const o = JSON.parse(String(raw));
        if (o && o.id) st.orders.push(o);
      } catch (_) { /* 깨진 행은 건너뜀 */ }
    }
  }

  st.journal = sortJournal_(st.journal.map(cleanEntry_).filter(Boolean));
  st.orders = sortOrders_(st.orders.map(cleanOrder_).filter(Boolean));
  return st;
}

function writeState_(st) {
  const ss = spreadsheet_();

  // 1) 원본 메타 (_Sync)
  const sync = ensureSheet_(ss, SHEET_STATE, { hidden: true });
  sync.clearContents();
  sync.getRange(1, 1, 1, 2).setValues([['key', 'value']]);
  const orders = Array.isArray(st.orders) ? st.orders : [];
  const meta = [
    ['schema', SCHEMA_VERSION],
    ['updatedAt', st.updatedAt],
    ['ordersUpdatedAt', st.ordersUpdatedAt || 0],
    ['asset', JSON.stringify(st.asset)],
    ['count', st.journal.length],
    ['orderCount', orders.length],
    ['syncedAtKst', fmtTs_(st.updatedAt)]
  ];
  sync.getRange(2, 1, meta.length, 2).setValues(meta);

  // 2) 원본 매매 JSON (_JournalJSON) — 1건 = 1행
  const js = ensureSheet_(ss, SHEET_JSON, { hidden: true });
  const rows = [['id', 'json']];
  st.journal.forEach(e => rows.push([String(e.id), JSON.stringify(e)]));
  js.clearContents();
  js.getRange(1, 1, rows.length, 2).setValues(rows);

  // 3) 예약주문 원본 (_OrdersJSON) — 1건 = 1행
  const oj = ensureSheet_(ss, SHEET_ORDERS_JSON, { hidden: true });
  const orows = [['id', 'json']];
  orders.forEach(o => orows.push([String(o.id), JSON.stringify(o)]));
  oj.clearContents();
  oj.getRange(1, 1, orows.length, 2).setValues(orows);

  // 4) 사람이 보는 시트 다시 그리기
  renderJournal_(ss, st);
  renderWithdrawals_(ss, st);
  renderOrders_(ss, st);
  renderSummary_(ss, st);
}

/* ───────────────────────── 예약주문 표 ───────────────────────── */

function renderOrders_(ss, st) {
  const sh = ensureSheet_(ss, SHEET_ORDERS);
  const list = Array.isArray(st.orders) ? st.orders : [];
  const rows = [ORDER_HEADERS];
  list.forEach((o, i) => {
    rows.push([
      i + 1,
      orderStatusLabel_(o),
      numOr_(o.at, 0) ? fmtTs_(o.at) : '',
      String(o.sym || o.code || ''),
      o.side === 'short' ? '숏' : '롱',
      o.kind === 'add' ? '물타기' : '진입',
      numOr_(o.price, ''),
      numOr_(o.margin, ''),
      numOr_(o.lev, ''),
      numOr_((Number(o.margin) || 0) * (Number(o.lev) || 0), ''),
      numOr_(o.stop, ''),
      numOr_(o.t1, ''),
      numOr_(o.t2, ''),
      String(o.note || ''),
      orderSourceLabel_(o.source),
      String(o.id || '')
    ]);
  });

  sh.clearContents();
  sh.getRange(1, 1, rows.length, ORDER_HEADERS.length).setValues(rows);
  sh.getRange(1, 1, 1, ORDER_HEADERS.length)
    .setFontWeight('bold').setFontColor('#ffffff').setBackground('#0f172a')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sh.setFrozenRows(1);
  [44, 96, 132, 84, 54, 64, 104, 106, 72, 118, 104, 104, 104, 300, 88, 200].forEach((w, i) => sh.setColumnWidth(i + 1, w));
  sh.getRange(2, 1, Math.max(rows.length - 1, 1), 1).setHorizontalAlignment('center');
  sh.getRange(2, 2, Math.max(rows.length - 1, 1), 1).setHorizontalAlignment('center');
  sh.getRange(2, 5, Math.max(rows.length - 1, 1), 2).setHorizontalAlignment('center');
  sh.getRange('A2:A1000').setNumberFormat('0');
  sh.getRange('I2:I1000').setNumberFormat('0');
  sh.getRange('G2:H1000').setNumberFormat('#,##0.00####');
  sh.getRange('J2:J1000').setNumberFormat('#,##0.00');
  sh.getRange('K2:M1000').setNumberFormat('#,##0.00####');
  if (list.length) sh.getRange(2, 1, list.length, ORDER_HEADERS.length).setVerticalAlignment('middle');
}

/* ───────────────────────── 화면용 시트 ───────────────────────── */

function renderJournal_(ss, st) {
  const sh = ensureSheet_(ss, SHEET_JOURNAL);
  const rows = [JOURNAL_HEADERS];
  st.journal.forEach((e, i) => {
    rows.push([
      i + 1,
      numOr_(e.at, 0) ? fmtTs_(e.at) : '',
      e.exitAt ? fmtTs_(e.exitAt) : '',
      String(e.sym || e.code || ''),
      e.side === 'short' ? '숏' : '롱',
      numOr_(e.lev, ''),
      numOr_(e.entry, ''),
      numOr_(e.exitPrice, ''),
      numOr_(e.margin, ''),
      numOr_(pnlOf_(e), ''),
      numOr_(e.roe, ''),
      resultLabel_(e),
      reasonLabel_(e),
      String(e.memo || ''),
      String(e.id || '')
    ]);
  });

  sh.clearContents();
  sh.getRange(1, 1, rows.length, JOURNAL_HEADERS.length).setValues(rows);

  // 서식 (매 동기화 때 다시 입혀 시트가 스스로 복구되게)
  sh.getRange(1, 1, 1, JOURNAL_HEADERS.length)
    .setFontWeight('bold').setFontColor('#ffffff').setBackground('#1f2937')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sh.setFrozenRows(1);
  const widths = [44, 132, 132, 84, 54, 72, 104, 104, 106, 104, 78, 78, 210, 330, 200];
  widths.forEach((w, i) => sh.setColumnWidth(i + 1, w));
  sh.getRange(2, 1, Math.max(rows.length - 1, 1), 1).setHorizontalAlignment('center');
  sh.getRange(2, 5, Math.max(rows.length - 1, 1), 2).setHorizontalAlignment('center');
  sh.getRange(2, 12, Math.max(rows.length - 1, 1), 1).setHorizontalAlignment('center');
  sh.getRange('A2:A1000').setNumberFormat('0');
  sh.getRange('F2:F1000').setNumberFormat('0');
  sh.getRange('G2:H1000').setNumberFormat('#,##0.00####');
  sh.getRange('I2:J1000').setNumberFormat('#,##0.00');
  sh.getRange('K2:K1000').setNumberFormat('0.00"%"');
}

function renderWithdrawals_(ss, st) {
  const sh = ensureSheet_(ss, SHEET_WITHDRAW);
  const ws = st.asset.withdrawals.slice().sort((a, b) => (b.at || 0) - (a.at || 0));
  const rows = [['출금일시(KST)', '금액(USDT)', '메모', 'ID']];
  ws.forEach(w => rows.push([fmtTs_(w.at), numOr_(w.usd, 0), String(w.memo || ''), String(w.id || '')]));
  sh.clearContents();
  sh.getRange(1, 1, rows.length, 4).setValues(rows);
  sh.getRange(1, 1, 1, 4)
    .setFontWeight('bold').setFontColor('#ffffff').setBackground('#1f2937')
    .setHorizontalAlignment('center');
  sh.setFrozenRows(1);
  [148, 110, 300, 150].forEach((w, i) => sh.setColumnWidth(i + 1, w));
  sh.getRange('B2:B1000').setNumberFormat('#,##0.00');
}

function renderSummary_(ss, st) {
  const sh = ensureSheet_(ss, SHEET_SUMMARY);
  const closed = st.journal.filter(e => e.status === 'closed');
  const open = st.journal.filter(e => e.status !== 'closed');
  const roes = closed.map(e => Number(e.roe)).filter(v => isFinite(v));
  const wins = roes.filter(v => v > 0).length;
  const losses = roes.filter(v => v < 0).length;
  const evens = roes.filter(v => v === 0).length;
  const decided = wins + losses;
  const rate = decided ? (wins / decided * 100) : NaN;
  const avg = roes.length ? roes.reduce((a, b) => a + b, 0) / roes.length : NaN;

  const realized = closed.reduce((a, e) => {
    const v = pnlOf_(e);
    return a + (isFinite(v) ? v : 0);
  }, 0);
  const wd = st.asset.withdrawals.reduce((a, w) => a + (Number(w.usd) || 0), 0);
  const current = st.asset.initial + realized - wd;

  const usd = v => (v > 0 ? '+' : '') + v.toFixed(2) + ' USDT';
  const pct = v => (isFinite(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—');

  const rows = [
    ['코인 매매기록 동기화', ''],
    ['폰 · PC 실시간 동기화', ''],
    ['', ''],
    ['마지막 동기화', st.updatedAt ? fmtTs_(st.updatedAt) + ' KST' : '아직 없음'],
    ['기록 건수', st.journal.length + '건'],
    ['', ''],
    ['💰 자산 현황', ''],
    ['초기 금액', st.asset.initial.toFixed(2) + ' USDT'],
    ['실현 손익(누적)', usd(realized)],
    ['총 출금', (wd > 0 ? '-' + wd.toFixed(2) : '0.00') + ' USDT'],
    ['현재 자산', current.toFixed(2) + ' USDT'],
    ['', ''],
    ['📒 매매 요약', ''],
    ['총 매매', st.journal.length + '건'],
    ['진행 중', open.length + '건'],
    ['종료', closed.length + '건'],
    ['승 / 패 / 본전', wins + '승 · ' + losses + '패' + (evens ? ' · 본전 ' + evens : '')],
    ['승률', isFinite(rate) ? rate.toFixed(1) + '%' : '—'],
    ['평균 ROE(종료 기준)', pct(avg)],
    ['누적 손익', usd(realized)],
    ['', ''],
    ['ℹ️ 이 시트는 웹앱 기록에서 자동으로 다시 그려집니다. (직접 고쳐도 다음 동기화 때 원본 기준으로 되돌아갑니다)', '']
  ];

  sh.clearContents();
  sh.getRange(1, 1, rows.length, 2).setValues(rows);
  [220, 240].forEach((w, i) => sh.setColumnWidth(i + 1, w));

  sh.getRange('A1:B1').merge().setFontSize(16).setFontWeight('bold').setFontColor('#1f2937');
  sh.getRange('A2:B2').merge().setFontColor('#6b7280');
  ['A7:B7', 'A13:B13'].forEach(a1 => sh.getRange(a1).merge()
    .setFontWeight('bold').setBackground('#e8eaed').setFontColor('#1f2937'));
  ['A4:A5', 'A8:A11', 'A14:A20'].forEach(a1 => sh.getRange(a1).setFontWeight('bold'));
  sh.getRange('B4:B5').setHorizontalAlignment('right');
  sh.getRange('B8:B11').setHorizontalAlignment('right');
  sh.getRange('B14:B20').setHorizontalAlignment('right');
  sh.getRange('A22').setFontColor('#9aa0a6').setFontSize(9);
}

/* ───────────────────────── 값 가공 ───────────────────────── */

function normalizeAsset_(a) {
  a = a || {};
  let initial = numOr_(a.initial, numOr_(a.initialCapital, DEFAULT_INITIAL));
  if (!(initial > 0)) initial = DEFAULT_INITIAL;

  let ws = Array.isArray(a.withdrawals) ? a.withdrawals : [];
  ws = ws.map(w => ({
    id: String((w && w.id) || ('wd' + Math.random().toString(36).slice(2, 8))),
    at: numOr_(w && w.at, Date.now()),
    usd: round2_(numOr_(w && w.usd, numOr_(w && w.amount, 0))),
    memo: String((w && w.memo) || '').slice(0, 40)
  })).filter(w => w.usd > 0);

  // 예전 형식(합계만 있는 경우)도 받아 줍니다.
  const total = numOr_(a.totalWithdrawn, 0);
  if (!ws.length && total > 0) {
    ws = [{ id: 'wd-legacy', at: Date.now(), usd: round2_(total), memo: '(합계로만 기록된 출금)' }];
  }
  return { initial: round2_(initial), withdrawals: ws };
}

function cleanEntry_(e) {
  if (!e || typeof e !== 'object') return null;
  const o = {};
  Object.keys(e).forEach(k => { o[k] = e[k]; });
  if (!o.id) o.id = 'tl' + numOr_(o.at, Date.now()) + Math.random().toString(36).slice(2, 6);
  o.id = String(o.id);
  if (o.side !== 'short') o.side = 'long';
  if (o.status !== 'closed') o.status = 'open';
  return o;
}

/* 예약주문 1건 정리 — 앱(localStorage)과 같은 필드만 남깁니다. */
function cleanOrder_(o) {
  if (!o || typeof o !== 'object' || !o.id) return null;
  const price = numOr_(o.price, NaN);
  const margin = numOr_(o.margin, NaN);
  if (!isFinite(price) || price <= 0) return null;
  if (!isFinite(margin) || margin <= 0) return null;
  const status = (o.status === 'cancelled' || o.status === 'filled') ? o.status : 'pending';
  const out = {
    id: String(o.id),
    sym: String(o.sym || ''),
    code: String(o.code || ''),
    side: o.side === 'long' ? 'long' : 'short',
    kind: o.kind === 'add' ? 'add' : 'entry',
    price: price,
    margin: round2_(margin),
    lev: numOr_(o.lev, 5),
    stop: isFinite(numOr_(o.stop, NaN)) ? numOr_(o.stop, 0) : null,
    t1: isFinite(numOr_(o.t1, NaN)) ? numOr_(o.t1, 0) : null,
    t2: isFinite(numOr_(o.t2, NaN)) ? numOr_(o.t2, 0) : null,
    feeMode: String(o.feeMode || 'maker'),
    at: numOr_(o.at, Date.now()),
    note: String(o.note || '').slice(0, 80),
    /* 값의 출처 — 관점 감시가 수동 가설 주문과 자동 1 주문을 섞지 않게 함께 보관합니다.
       값이 없는 예전 주문은 빈 문자열로 두고, 감시 쪽이 숫자로 추정합니다. */
    source: (o.source === 'auto1' || o.source === 'manual' || o.source === 'custom') ? o.source : '',
    baseEntry: isFinite(numOr_(o.baseEntry, NaN)) ? numOr_(o.baseEntry, 0) : null,
    hitAt: numOr_(o.hitAt, 0),
    status: status,
    st: numOr_(o.st, numOr_(o.at, 0))
  };
  if (status === 'filled') out.filledAt = numOr_(o.filledAt, out.st);
  if (status === 'cancelled') out.cancelAt = numOr_(o.cancelAt, out.st);
  return out;
}

function sortOrders_(list) {
  return list.slice().sort((a, b) => {
    const ap = a.status === 'pending' ? 0 : 1, bp = b.status === 'pending' ? 0 : 1;
    if (ap !== bp) return ap - bp;
    return numOr_(b.st, 0) - numOr_(a.st, 0);
  });
}

function orderStatusLabel_(o) {
  if (!o) return '';
  if (o.status === 'filled') return '✅ 체결됨';
  if (o.status === 'cancelled') return '❌ 취소';
  return '⏳ 대기';
}

/* 예약주문이 어느 기준으로 만들어진 주문인지 — 예약주문 시트 '감시 기준' 칸 */
function orderSourceLabel_(src) {
  if (src === 'auto1') return '🤖 자동 1';
  if (src === 'manual') return '가설';
  if (src === 'custom') return '직접 입력';
  return '';
}

function sortJournal_(list) {
  return list.slice().sort((a, b) => numOr_(b.at, 0) - numOr_(a.at, 0));
}

function pnlOf_(e) {
  if (!e) return NaN;
  if (isFinite(Number(e.pnl))) return Number(e.pnl);
  const m = Number(e.margin);
  const r = Number(e.roe);
  if (isFinite(m) && isFinite(r) && m > 0) return round2_(m * r / 100);
  return NaN;
}

function resultLabel_(e) {
  if (!e || e.status !== 'closed') return '진행 중';
  return ({
    tp2: '익절(2차)',
    tp1be: '익절(1차·본절)',
    stop: '손절',
    manual: '수동 청산'
  })[e.exitReason] || '청산';
}

function reasonLabel_(e) {
  if (e && e.exitNote) return String(e.exitNote);
  if (!e || e.status !== 'closed') return '';
  return ({
    tp2: '2차 익절 (1차 50% + 2차 50%)',
    tp1be: '1차 익절 · 남은 절반 본절',
    stop: '손절가 전량 정리',
    manual: '현재가 수동 청산'
  })[e.exitReason] || '청산';
}

/* 시트는 보통 '시트에 붙은(bound) 스크립트'로 열지만,
   script.google.com 에서 따로 만든 프로젝트에서도 돌 수 있게 시트 ID로도 엽니다. */
function spreadsheet_() {
  let ss = null;
  try { ss = SpreadsheetApp.getActive(); } catch (_) {}
  if (ss) return ss;
  return SpreadsheetApp.openById(SPREADSHEET_ID);
}

function ensureSheet_(ss, name, opt) {
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    if (opt && opt.hidden) { try { sh.hideSheet(); } catch (_) {} }
  }
  return sh;
}

function fmtTs_(ms) {
  const n = Number(ms);
  if (!isFinite(n) || n <= 0) return '';
  return Utilities.formatDate(new Date(n), TZ, 'yyyy-MM-dd HH:mm');
}

function numOr_(v, dflt) {
  const n = Number(v);
  return (v !== '' && v != null && isFinite(n)) ? n : dflt;
}

function round2_(v) {
  return Math.round(Number(v) * 100) / 100;
}

/* ───────────────────────── 편의 함수 (에디터에서 수동 실행) ─────────────────────────
 * 처음 한 번 setupSheets() 를 실행하면 빈 시트에 머리글·서식을 잡아 둡니다.
 * (웹앱으로 저장이 한 번이라도 들어오면 자동으로 같은 상태가 됩니다.) */
function setupSheets() {
  const ss = spreadsheet_();
  ensureSheet_(ss, SHEET_JOURNAL);
  ensureSheet_(ss, SHEET_SUMMARY);
  ensureSheet_(ss, SHEET_WITHDRAW);
  ensureSheet_(ss, SHEET_ORDERS);
  ensureSheet_(ss, SHEET_JSON, { hidden: true });
  ensureSheet_(ss, SHEET_ORDERS_JSON, { hidden: true });
  ensureSheet_(ss, SHEET_STATE, { hidden: true });
  const st = readState_();
  writeState_(st);
  return 'setup 완료 · 기록 ' + st.journal.length + '건';
}

/** 배포 후 브라우저 주소창에 ?action=ping 을 붙여 확인할 수 있습니다. */
function debugPing() {
  const st = readState_();
  Logger.log(JSON.stringify({ ok: true, schema: SCHEMA_VERSION, updatedAt: st.updatedAt,
                              count: st.journal.length, asset: st.asset,
                              orderCount: st.orders.length, ordersUpdatedAt: st.ordersUpdatedAt }, null, 2));
  return st.updatedAt;
}
