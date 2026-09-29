/* ================= XLSX reader (no dependencies) =================
   .xlsx = zip + XML. We read the values Excel cached for every formula,
   so the app shows exactly what Excel showed when the file was saved. */
class AppError extends Error { constructor(code, msg) { super(msg || code); this.code = code; } }

function readZipIndex(buf) {
  const u8 = new Uint8Array(buf), dv = new DataView(buf);
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 70000); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new AppError('not-zip', 'Это не файл Excel (.xlsx).');
  const count = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const td = new TextDecoder();
  const entries = new Map();
  for (let k = 0; k < count; k++) {
    if (dv.getUint32(p, true) !== 0x02014b50) break;
    const method = dv.getUint16(p + 10, true);
    const csize = dv.getUint32(p + 20, true);
    const nlen = dv.getUint16(p + 28, true), xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
    const lho = dv.getUint32(p + 42, true);
    entries.set(td.decode(u8.subarray(p + 46, p + 46 + nlen)), { method, csize, lho });
    p += 46 + nlen + xlen + clen;
  }
  return { u8, dv, entries };
}

async function zipText(z, name) {
  const e = z.entries.get(name);
  if (!e) return null;
  const nlen = z.dv.getUint16(e.lho + 26, true), xlen = z.dv.getUint16(e.lho + 28, true);
  const start = e.lho + 30 + nlen + xlen;
  const data = z.u8.subarray(start, start + e.csize);
  let out;
  if (e.method === 0) out = data;
  else if (e.method === 8) {
    if (typeof DecompressionStream === 'undefined') throw new AppError('old-browser', 'Браузер слишком старый: обновите Chrome или Samsung Internet.');
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    out = new Uint8Array(await new Response(stream).arrayBuffer());
  } else throw new AppError('zip-method', 'Файл сжат необычным способом. Пересохраните его в Excel.');
  return new TextDecoder().decode(out);
}

const RNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
function xml(text) { return new DOMParser().parseFromString(text, 'application/xml'); }
function kids(el, name) { return Array.from(el.childNodes).filter(n => n.nodeType === 1 && n.localName === name); }
function kid(el, name) { return kids(el, name)[0] || null; }

function siText(si) {
  let s = '';
  for (const n of si.childNodes) {
    if (n.nodeType !== 1) continue;
    if (n.localName === 't') s += n.textContent;
    else if (n.localName === 'r') { const t = kid(n, 't'); if (t) s += t.textContent; }
  }
  return s;
}

async function openWorkbook(buf) {
  const z = readZipIndex(buf);
  const wbText = await zipText(z, 'xl/workbook.xml');
  if (!wbText) throw new AppError('not-xlsx', 'В файле нет книги Excel. Нужен .xlsx, сохранённый в Excel.');
  const wb = xml(wbText);
  const relsDoc = xml(await zipText(z, 'xl/_rels/workbook.xml.rels') || '<Relationships/>');
  const rel = {};
  for (const r of relsDoc.getElementsByTagNameNS('*', 'Relationship')) {
    let t = r.getAttribute('Target') || '';
    t = t.startsWith('/') ? t.slice(1) : 'xl/' + t.replace(/^\.\//, '');
    rel[r.getAttribute('Id')] = t;
  }
  const sheets = Array.from(wb.getElementsByTagNameNS('*', 'sheet')).map(s => ({
    name: s.getAttribute('name'),
    path: rel[s.getAttributeNS(RNS, 'id') || s.getAttribute('r:id')]
  }));
  const sstText = await zipText(z, 'xl/sharedStrings.xml');
  const sst = sstText ? Array.from(xml(sstText).getElementsByTagNameNS('*', 'si')).map(siText) : [];
  const stats = { formulas: 0, uncached: 0 };

  async function sheet(name) {
    const s = sheets.find(x => x.name === name);
    if (!s || !s.path) return null;
    const doc = xml(await zipText(z, s.path));
    const cells = new Map();
    for (const c of doc.getElementsByTagNameNS('*', 'c')) {
      const r = c.getAttribute('r');
      const t = c.getAttribute('t');
      const vEl = kid(c, 'v');
      if (kid(c, 'f')) { stats.formulas++; if (!vEl) stats.uncached++; }
      let v = null;
      if (t === 's') v = vEl ? (sst[+vEl.textContent] ?? null) : null;
      else if (t === 'str') v = vEl ? vEl.textContent : null;
      else if (t === 'inlineStr') { const is = kid(c, 'is'); v = is ? siText(is) : null; }
      else if (t === 'b') v = vEl ? vEl.textContent === '1' : null;
      else if (t === 'e') v = null;
      else if (vEl) { const n = parseFloat(vEl.textContent); v = Number.isFinite(n) ? n : null; }
      if (r) cells.set(r, v);
    }
    return cells;
  }
  return { sheetNames: sheets.map(s => s.name), sheet, stats };
}

/* ================= Planner model ================= */
const MONTHS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const MONTH_RE = new RegExp('^(' + MONTHS.join('|') + ')\\s+(\\d{4})$');

function colL(i) { let s = ''; while (i > 0) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; }
function norm(v) { return v == null ? '' : String(v).replace(/\s+/g, ' ').trim().toLowerCase(); }
function num(v) { return typeof v === 'number' && Number.isFinite(v) ? v : null; }
function serialToISO(n) {
  if (typeof n !== 'number') return null;
  const d = new Date(Date.UTC(1899, 11, 30) + Math.round(n) * 86400000);
  return d.toISOString().slice(0, 10);
}
function isDateSerial(v) { return typeof v === 'number' && v > 30000 && v < 80000; }

function findLabel(cells, col, re, rows = 60) {
  for (let r = 1; r <= rows; r++) {
    const v = cells.get(col + r);
    if (typeof v === 'string' && re.test(norm(v))) return r;
  }
  return 0;
}

function extractSettings(cells) {
  const s = {};
  const pick = (re) => { const r = findLabel(cells, 'A', re, 40); return r ? cells.get('B' + r) : null; };
  s.start = serialToISO(pick(/^дата начала/));
  s.end = serialToISO(pick(/^дата окончания/));
  s.dailySave = num(pick(/^ежедневное пополнение/));
  s.rate = num(pick(/^годовая процентная ставка/));
  s.dailyNorm = num(pick(/^дневной норматив/));
  s.subsDaily = num(pick(/^ежедневный платёж за подписки|^ежедневный платеж за подписки/));
  s.obligatory = num(pick(/^обязательные списания/));
  s.free = num(pick(/^свободно на день/));
  s.goal = num(pick(/^цель/));
  s.cats = [];
  // category list: header «Категории расходов», optional flag column next to it
  for (let ci = 1; ci <= 12; ci++) {
    const L = colL(ci);
    const r = findLabel(cells, L, /^категории расходов/, 10);
    if (!r) continue;
    const FL = colL(ci + 1);
    const hasFlag = /лимит/.test(norm(cells.get(FL + r)));
    for (let rr = r + 1; rr < r + 30; rr++) {
      const name = cells.get(L + rr);
      if (typeof name !== 'string' || !name.trim()) break;
      const flag = hasFlag ? norm(cells.get(FL + rr)) : 'да';
      s.cats.push({ name: name.trim(), inLimit: flag !== 'нет' });
    }
    break;
  }
  return s;
}

function extractSavings(cells) {
  if (!cells) return [];
  const hr = findLabel(cells, 'A', /^месяц$/, 10);
  if (!hr) return [];
  const map = {};
  for (let ci = 1; ci <= 12; ci++) {
    const h = norm(cells.get(colL(ci) + hr));
    if (h === 'дней') map.days = colL(ci);
    else if (h.startsWith('пополнение')) map.contrib = colL(ci);
    else if (h.startsWith('проценты за')) map.interest = colL(ci);
    else if (h.startsWith('баланс после')) map.balance = colL(ci);
    else if (h.startsWith('всего внесено')) map.contribCum = colL(ci);
    else if (h.startsWith('всего заработано')) map.interestCum = colL(ci);
  }
  const rows = [];
  for (let r = hr + 1; r < hr + 200; r++) {
    const name = cells.get('A' + r);
    if (typeof name !== 'string' || !name.trim()) break;
    const m = MONTH_RE.exec(name.trim());
    rows.push({
      name: name.trim(),
      key: m ? `${m[2]}-${String(MONTHS.indexOf(m[1]) + 1).padStart(2, '0')}` : null,
      days: num(cells.get(map.days + r)),
      contrib: num(cells.get(map.contrib + r)),
      interest: num(cells.get(map.interest + r)),
      balance: num(cells.get(map.balance + r)),
      contribCum: num(cells.get(map.contribCum + r)),
      interestCum: num(cells.get(map.interestCum + r)),
    });
  }
  return rows.filter(r => r.key);
}

const PANEL_KEYS = [
  ['normPerDay', /^норматив на день/], ['obligPerDay', /^обязательные в день/], ['freePerDay', /^свободно на день/],
  ['onHand', /на руках сейчас/], ['fromDate', /считать остаток с даты/], ['useIncome', /учитывать доходы/],
  ['enoughUntil', /^денег хватает по дату/], ['coveredDays', /^дней покрыто/], ['needMore', /^нужно доложить/],
  ['planSaveMonth', /^план накоплений за месяц/], ['factSaveMonth', /^фактически накоплено/], ['incomeMonth', /^доходы за месяц/],
  ['spentAll', /^потрачено всего|^фактически потрачено/], ['avgLimit', /^средний расход/], ['savedTotal', /^накоплено с начала периода/],
  ['interestMonth', /^проценты за месяц/], ['balanceEnd', /^баланс счёта на конец|^баланс счета на конец/], ['spentLimit', /^из них в дневном лимите/],
];

function extractMonth(name, cells, settings) {
  const g = a => cells.get(a);
  const m = MONTH_RE.exec(name);
  const key = `${m[2]}-${String(MONTHS.indexOf(m[1]) + 1).padStart(2, '0')}`;
  let hr = 0;
  for (let r = 1; r <= 8; r++) if (norm(g('A' + r)) === 'дата') { hr = r; break; }
  if (!hr) return null;
  const cols = {};
  for (let ci = 1; ci <= 24; ci++) {
    const L = colL(ci), h = norm(g(L + hr));
    if (!h) continue;
    if (h === 'дата') cols.date = L;
    else if (h.startsWith('день недели')) cols.wd = L;
    else if (h.startsWith('план накоплен')) cols.planSave = L;
    else if (h.startsWith('факт накоплен')) cols.factSave = L;
    else if (h.startsWith('доходы')) cols.income = L;
    else if (h.startsWith('факт расходов')) {
      if (h.includes('авто') && !h.includes('весь')) cols.limit = L;
      else if (h.includes('весь')) cols.all = L;
      else cols.single = L;
    }
    else if (h.startsWith('статус')) cols.status = L;
  }
  if (!cols.all) cols.all = cols.single || cols.limit;
  if (!cols.limit) cols.limit = cols.single || cols.all;
  const days = [];
  for (let r = hr + 1; r < hr + 40; r++) {
    const d = g(cols.date + r);
    if (!isDateSerial(d)) break;
    const val = (L) => L ? num(g(L + r)) : null;
    days.push({
      serial: d, date: serialToISO(d), wd: cols.wd ? g(cols.wd + r) : null,
      planSave: val(cols.planSave), factSave: val(cols.factSave), income: val(cols.income),
      all: val(cols.all), limit: val(cols.limit), status: cols.status ? g(cols.status + r) : null, cats: null,
    });
  }
  // panel (label in P, value in R)
  const panel = {};
  for (let r = 1; r <= 45; r++) {
    const lab = norm(g('P' + r));
    if (!lab) continue;
    for (const [k, re] of PANEL_KEYS) if (panel[k] === undefined && re.test(lab)) { panel[k] = g('R' + r); break; }
  }
  for (const k of ['fromDate', 'enoughUntil']) panel[k] = isDateSerial(panel[k]) ? serialToISO(panel[k]) : null;
  // category table
  let catNames = [], catFlags = [];
  let tr = 0;
  for (let r = hr + days.length; r < hr + days.length + 30; r++) {
    const v = g('A' + r);
    if (typeof v === 'string' && /^расходы по категориям/i.test(v.trim())) { tr = r; break; }
  }
  if (tr) {
    const h = tr + 1;
    const catCols = [];
    for (let ci = 3; ci <= 20; ci++) {
      const L = colL(ci), t = g(L + h);
      if (typeof t !== 'string' || !t.trim() || /лимите|всего|итого/i.test(t)) break;
      catCols.push(L); catNames.push(t.trim());
    }
    let d0 = h + 1;
    const hasFlags = /^учёт|^учет/.test(norm(g('A' + d0)));
    if (hasFlags) { catFlags = catCols.map(L => norm(g(L + d0)) !== 'отдельно'); d0++; }
    else catFlags = catNames.map(n => { const c = settings.cats.find(x => x.name === n); return c ? c.inLimit : true; });
    const bySerial = new Map(days.map(d => [d.serial, d]));
    for (let r = d0; r < d0 + 40; r++) {
      const d = g('A' + r);
      if (!isDateSerial(d)) break;
      const day = bySerial.get(d);
      if (!day) continue;
      const vals = catCols.map(L => num(g(L + r)));
      day.cats = vals.some(v => v != null) ? vals : null;
    }
  }
  // stale-cache guard: category entries exist but the day total is empty
  let staleDays = 0;
  for (const d of days) {
    if (d.cats && d.all == null) {
      staleDays++;
      d.all = d.cats.reduce((a, v) => a + (v || 0), 0);
      d.limit = d.cats.reduce((a, v, i) => a + (catFlags[i] ? (v || 0) : 0), 0);
    }
  }
  const banner = g('A2');
  return {
    name, key, archive: typeof banner === 'string' && /архив/i.test(banner),
    days, panel, catNames, catFlags, staleDays,
  };
}

async function parsePlanner(buf, fileName) {
  const wb = await openWorkbook(buf);
  if (!wb.sheetNames.includes('Настройки')) throw new AppError('not-planner', 'В файле нет листа «Настройки». Это точно финансовый планировщик?');
  const settings = extractSettings(await wb.sheet('Настройки'));
  const savings = extractSavings(await wb.sheet('Накопления'));
  const months = [];
  for (const n of wb.sheetNames) {
    if (!MONTH_RE.test(n)) continue;
    const mo = extractMonth(n, await wb.sheet(n), settings);
    if (mo) months.push(mo);
  }
  if (!months.length) throw new AppError('no-months', 'Не нашёл месячных листов вида «Сентябрь 2026».');
  months.sort((a, b) => a.key.localeCompare(b.key));
  const staleDays = months.reduce((a, m) => a + m.staleDays, 0);
  const uncachedShare = wb.stats.formulas ? wb.stats.uncached / wb.stats.formulas : 0;
  return {
    v: 1, fileName, loadedAt: new Date().toISOString(),
    settings, savings, months,
    quality: { uncachedShare, staleDays },
  };
}

