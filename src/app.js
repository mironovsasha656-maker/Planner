/* ================= helpers ================= */
const $ = (s, el = document) => el.querySelector(s);
const NBSP = ' ', MINUS = '−';
const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const fmt = n => n == null ? '—' : nf0.format(Math.round(n)).replace('-', MINUS);
const rub = n => n == null ? '—' : fmt(n) + NBSP + '₽';
const signed = n => n == null ? '—' : (n > 0 ? '+' : n < 0 ? MINUS : '') + nf0.format(Math.abs(Math.round(n)));
const compact = n => {
  const a = Math.abs(n);
  if (a >= 1e6) return nf2.format(+(n / 1e6).toFixed(a >= 1e7 ? 1 : 2)) + NBSP + 'млн';
  if (a >= 1e4) return nf0.format(Math.round(n / 1e3)) + NBSP + 'тыс';
  return nf0.format(Math.round(n));
};
const GEN = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
const SHORT = ['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'];
const WD = ['Вс','Пн','Вт','Ср','Чт','Пт','Сб'];
const pd = iso => { const [y, m, d] = iso.split('-').map(Number); return { y, m, d, wd: new Date(Date.UTC(y, m - 1, d)).getUTCDay() }; };
const dayLong = iso => { const p = pd(iso); return `${p.d} ${GEN[p.m - 1]}`; };
const dateRu = iso => { if (!iso) return '—'; const p = pd(iso); return `${String(p.d).padStart(2, '0')}.${String(p.m).padStart(2, '0')}.${p.y}`; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const todayISO = () => { const t = new Date(); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`; };
const CAT_VARS = ['--c1','--c2','--c3','--c4','--c5','--c6','--c7','--c8','--c9'];
function catColor(name, idx) { return /^прочее$/i.test(name) ? 'var(--c9)' : `var(${CAT_VARS[Math.min(idx, 7)]})`; }

/* ================= storage ================= */
const KEY = 'planner.model.v1', UI_KEY = 'planner.ui.v1';
const store = {
  get(k) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};

/* ================= demo data (clearly marked) ================= */
function demoModel() {
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const settings = {
    start: '2026-09-01', end: '2031-07-23', dailySave: 570, rate: 0.1521, dailyNorm: 1333, subsDaily: 62, obligatory: 632, free: 701, goal: 760000,
    cats: [['Еда',1],['Транспорт',1],['Развлечения',1],['Одежда',0],['Покупки',0],['Здоровье',0],['Образование',0],['Подписки',0],['Прочее',1]].map(([name, f]) => ({ name, inLimit: !!f })),
  };
  const t = new Date();
  let y = t.getFullYear(), mo = t.getMonth() + 1;
  if (`${y}-${String(mo).padStart(2, '0')}` < '2026-10') { y = 2026; mo = 10; }
  const keys = [];
  for (let k = 1; k >= 0; k--) { let mm = mo - k, yy = y; if (mm < 1) { mm += 12; yy--; } keys.push([yy, mm]); }
  const months = keys.map(([yy, mm], idx) => {
    const n = new Date(Date.UTC(yy, mm, 0)).getUTCDate();
    const upto = idx === 0 ? n : Math.max(3, Math.min(n, t.getDate() - 1));
    const days = [];
    for (let d = 1; d <= n; d++) {
      const iso = `${yy}-${String(mm).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      let cats = null;
      if (d <= upto) {
        cats = [Math.round(180 + rnd() * 620), rnd() < .5 ? [62, 124, 150][Math.floor(rnd() * 3)] : null, rnd() < .18 ? Math.round(150 + rnd() * 450) : null,
          rnd() < .04 ? Math.round(1500 + rnd() * 2500) : null, rnd() < .1 ? Math.round(400 + rnd() * 2200) : null, rnd() < .06 ? Math.round(300 + rnd() * 1500) : null,
          null, d === 10 ? 1890 : null, rnd() < .08 ? Math.round(50 + rnd() * 300) : null];
      }
      const all = cats ? cats.reduce((a, v) => a + (v || 0), 0) : null;
      const limit = cats ? cats.reduce((a, v, i) => a + (settings.cats[i].inLimit ? (v || 0) : 0), 0) : null;
      days.push({ date: iso, wd: null, planSave: 570, factSave: 570, income: rnd() < .15 ? Math.round(900 + rnd() * 700) : null, all, limit, status: null, cats });
    }
    const spentAll = days.reduce((a, d) => a + (d.all || 0), 0);
    return {
      name: `${MONTHS[mm - 1]} ${yy}`, key: `${yy}-${String(mm).padStart(2, '0')}`, archive: false, days,
      panel: { freePerDay: 701, normPerDay: 1333, onHand: idx === 1 ? 24500 : null, enoughUntil: null, needMore: idx === 1 ? 6100 : null,
        planSaveMonth: 570 * n, factSaveMonth: 570 * n, incomeMonth: days.reduce((a, d) => a + (d.income || 0), 0), spentAll },
      catNames: settings.cats.map(c => c.name), catFlags: settings.cats.map(c => c.inLimit), staleDays: 0,
    };
  });
  const savings = [];
  let bal = 0, cc = 0, ic = 0;
  for (let yy = 2026, mm = 9; `${yy}-${String(mm).padStart(2, '0')}` <= '2031-07'; mm++) {
    if (mm > 12) { mm = 1; yy++; }
    const n = yy === 2031 && mm === 7 ? 23 : new Date(Date.UTC(yy, mm, 0)).getUTCDate();
    const contrib = n * 570; const before = bal + contrib; const interest = before * 0.1521 / 12; bal = before + interest; cc += contrib; ic += interest;
    savings.push({ name: `${MONTHS[mm - 1]} ${yy}`, key: `${yy}-${String(mm).padStart(2, '0')}`, days: n, contrib, interest, balance: bal, contribCum: cc, interestCum: ic });
  }
  return { v: 1, demo: true, fileName: 'пример', loadedAt: new Date().toISOString(), settings, savings, months, quality: { uncachedShare: 0, staleDays: 0 } };
}

/* ================= derived numbers ================= */
function monthStats(m, settings) {
  const free = num(m.panel.freePerDay) ?? settings.free ?? 0;
  let last = -1;
  m.days.forEach((d, i) => { if (d.all != null) last = i; });
  const upto = m.days.slice(0, last + 1);
  const sum = (arr, f) => arr.reduce((a, d) => a + (f(d) || 0), 0);
  const spentAll = sum(m.days, d => d.all), spentLimit = sum(m.days, d => d.limit);
  const emptyDays = upto.filter(d => d.all == null).length;
  const budget = free * upto.length;
  const cats = m.catNames.map((name, i) => ({
    name, idx: i, inLimit: m.catFlags[i] !== false,
    total: m.days.reduce((a, d) => a + ((d.cats && d.cats[i]) || 0), 0),
  }));
  return {
    free, lastIdx: last, lastDate: last >= 0 ? m.days[last].date : null, elapsed: upto.length, emptyDays,
    spentAll, spentLimit, spentOut: spentAll - spentLimit, budget, dev: budget - spentLimit,
    income: sum(m.days, d => d.income), planSave: sum(m.days, d => d.planSave), factSave: sum(m.days, d => d.factSave),
    avgLimit: upto.length ? spentLimit / upto.length : 0,
    overDays: upto.filter(d => d.limit != null && d.limit > free).length,
    cats,
  };
}
const hasData = m => m.days.some(d => d.all != null);

/* ================= state ================= */
const state = { model: null, tab: 'obzor', monthKey: null, catMode: 'cum', catOff: {}, openDay: null };

function defaultMonthKey(model) {
  const cur = todayISO().slice(0, 7);
  const curM = model.months.find(m => m.key === cur);
  if (curM && hasData(curM)) return cur;
  const withData = model.months.filter(hasData);
  if (withData.length) return withData[withData.length - 1].key;
  return curM ? cur : model.months[0].key;
}
const curMonth = () => state.model.months.find(m => m.key === state.monthKey) || state.model.months[0];

/* ================= charts (hand-drawn SVG) ================= */
function niceMax(v, ticks = 4) {
  if (v <= 0) return { max: ticks, step: 1 };
  const raw = v / ticks, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(k => k * p).find(s => s >= raw);
  return { max: step * Math.ceil(v / step), step };
}
function roundTopRect(x, y, w, h, r) {
  if (h <= 0) return '';
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function attachTip(host, n, xAt, html) {
  const tip = document.createElement('div');
  tip.className = 'tip'; tip.hidden = true; host.appendChild(tip);
  const cross = host.querySelector('.xhair');
  let active = -1;
  const show = (clientX) => {
    const rect = host.getBoundingClientRect();
    const x = clientX - rect.left;
    let best = 0, bd = Infinity;
    for (let i = 0; i < n; i++) { const dx = Math.abs(xAt(i) - x); if (dx < bd) { bd = dx; best = i; } }
    const content = html(best);
    if (!content) { tip.hidden = true; if (cross) cross.style.opacity = 0; return; }
    active = best;
    tip.innerHTML = content; tip.hidden = false;
    const tw = tip.offsetWidth, px = xAt(best);
    tip.style.left = Math.max(0, Math.min(rect.width - tw, px - tw / 2)) + 'px';
    tip.style.top = (-tip.offsetHeight - 8) + 'px';
    if (cross) { cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.style.opacity = 1; }
    host.dispatchEvent(new CustomEvent('tipindex', { detail: best }));
  };
  const hide = () => { tip.hidden = true; active = -1; if (cross) cross.style.opacity = 0; host.dispatchEvent(new CustomEvent('tipindex', { detail: -1 })); };
  host.addEventListener('pointerdown', e => show(e.clientX));
  host.addEventListener('pointermove', e => { if (e.pointerType === 'mouse' || e.buttons) show(e.clientX); });
  host.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') hide(); });
  document.addEventListener('pointerdown', e => { if (!host.contains(e.target) && active >= 0) hide(); });
}

/* Daily spending: in-limit part (green / red vs limit) + outside-limit part stacked on top */
function dailyChart(host, m, st) {
  const W = host.clientWidth || 340, H = 190, L = 38, R = 6, T = 10, B = 24;
  const n = m.days.length, pw = W - L - R, ph = H - T - B;
  const vals = m.days.map(d => [d.limit || 0, Math.max(0, (d.all || 0) - (d.limit || 0))]);
  const { max, step } = niceMax(Math.max(st.free * 1.25, ...vals.map(v => v[0] + v[1])));
  const y = v => T + ph - (v / max) * ph;
  const band = pw / n, bw = Math.min(14, band * 0.66);
  const xc = i => L + band * i + band / 2;
  let g = '';
  for (let v = 0; v <= max + 1e-9; v += step) {
    g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" style="stroke:var(--line)" stroke-width="1"/>`;
    g += `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="10.5" style="fill:var(--muted)">${compact(v)}</text>`;
  }
  let bars = '';
  m.days.forEach((d, i) => {
    if (d.all == null) return;
    const [a, b] = vals[i], x = xc(i) - bw / 2;
    const over = a > st.free;
    const hA = Math.max(a > 0 ? 2 : 0, (a / max) * ph), hB = (b / max) * ph;
    if (b > 0) {
      bars += `<path d="${roundTopRect(x, y(0) - hA - hB, bw, Math.max(0, hB - 2), 3)}" style="fill:var(--out)"/>`;
      if (a > 0) bars += `<rect x="${x}" y="${y(0) - hA}" width="${bw}" height="${hA}" style="fill:var(${over ? '--bad' : '--good'})"/>`;
    } else if (a > 0) {
      bars += `<path d="${roundTopRect(x, y(0) - hA, bw, hA, 3)}" style="fill:var(${over ? '--bad' : '--good'})"/>`;
    }
  });
  const ticks = [1, 5, 10, 15, 20, 25, n].filter((v, i, a) => v <= n && a.indexOf(v) === i && !(v === 25 && n - 25 < 3));
  const xl = ticks.map(t => `<text x="${xc(t - 1)}" y="${H - 6}" text-anchor="middle" font-size="10.5" style="fill:var(--muted)">${t}</text>`).join('');
  const ly = y(st.free);
  const limitLine = `<line x1="${L}" x2="${W - R}" y1="${ly}" y2="${ly}" style="stroke:var(--gold)" stroke-width="1.5"/>`;
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Расходы по дням за ${esc(m.name)}">
    ${g}${bars}${limitLine}${xl}
    <line class="xhair" x1="0" x2="0" y1="${T}" y2="${T + ph}" style="stroke:var(--ink-2);opacity:0" stroke-width="1"/>
  </svg>`;
  attachTip(host, n, xc, i => {
    const d = m.days[i];
    if (d.all == null) return `<b>${dayLong(d.date)}</b><div class="muted">нет записей</div>`;
    const dev = st.free - (d.limit || 0);
    return `<b>${dayLong(d.date)}</b>
      <div class="tr"><span><i class="sw" style="background:var(${(d.limit || 0) > st.free ? '--bad' : '--good'})"></i>из лимита</span><span>${rub(d.limit)}</span></div>
      ${d.all - d.limit > 0 ? `<div class="tr"><span><i class="sw" style="background:var(--out)"></i>вне лимита</span><span>${rub(d.all - d.limit)}</span></div>` : ''}
      <div class="tr"><span>к лимиту</span><span>${signed(dev)}</span></div>`;
  });
}

/* Generic multi-line chart with crosshair tooltip */
function lineChart(host, { labels, series, H = 200, yFmt = compact, xTicks, tipTitle, marker = null, area = null }) {
  const W = host.clientWidth || 340, L = 44, R = 8, T = 12, B = 24;
  const n = labels.length, pw = W - L - R, ph = H - T - B;
  const all = series.flatMap(s => s.values.filter(v => v != null));
  const { max, step } = niceMax(Math.max(1, ...all));
  const x = i => L + (n === 1 ? pw / 2 : (pw * i) / (n - 1));
  const y = v => T + ph - (v / max) * ph;
  let g = '';
  for (let v = 0; v <= max + 1e-9; v += step) {
    g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" style="stroke:var(--line)" stroke-width="1"/>`;
    g += `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="10.5" style="fill:var(--muted)">${yFmt(v)}</text>`;
  }
  const xl = (xTicks || []).map(([i, t]) => `<text x="${x(i)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}" font-size="10.5" style="fill:var(--muted)">${t}</text>`).join('');
  let paths = '';
  if (area) {
    const s = series[area.index];
    let d = '', started = false, first = 0, lastI = 0;
    s.values.forEach((v, i) => { if (v == null) return; if (!started) { d += `M${x(i)},${y(0)}L${x(i)},${y(v)}`; started = true; first = i; } else d += `L${x(i)},${y(v)}`; lastI = i; });
    if (started) paths += `<path d="${d}L${x(lastI)},${y(0)}Z" style="fill:${s.color};opacity:.1"/>`;
  }
  if (marker != null && marker >= 0 && marker < n) {
    paths += `<line x1="${x(marker)}" x2="${x(marker)}" y1="${T}" y2="${T + ph}" style="stroke:var(--gold)" stroke-width="1.5"/>
      <text x="${x(marker) + (marker > n * 0.7 ? -5 : 5)}" y="${T + 10}" font-size="10.5" font-weight="600" text-anchor="${marker > n * 0.7 ? 'end' : 'start'}" style="fill:var(--ink-2)">сейчас</text>`;
  }
  for (const s of series) {
    let d = '', pen = false;
    s.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + x(i) + ',' + y(v); pen = true; });
    paths += `<path d="${d}" fill="none" style="stroke:${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ` stroke-dasharray="${s.dash}"` : ''}/>`;
    let li = -1; s.values.forEach((v, i) => { if (v != null) li = i; });
    if (li >= 0 && s.endDot !== false) paths += `<circle cx="${x(li)}" cy="${y(s.values[li])}" r="4" style="fill:${s.color};stroke:var(--surface)" stroke-width="2"/>`;
  }
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img">${g}${paths}${xl}
    <line class="xhair" x1="0" x2="0" y1="${T}" y2="${T + ph}" style="stroke:var(--ink-2);opacity:0" stroke-width="1"/></svg>`;
  attachTip(host, n, x, i => {
    const rows = series.filter(s => s.values[i] != null && !s.noTip).map(s => `<div class="tr"><span><i class="sw" style="background:${s.color}"></i>${esc(s.name)}</span><span>${rub(s.values[i])}</span></div>`).join('');
    if (!rows) return '';
    return `<b>${esc(tipTitle(i))}</b>${rows}`;
  });
}

/* ================= screens ================= */
function freshLine(model) {
  if (model.demo) return `<div class="banner"><span><b>Это пример данных.</b> Загрузите свой файл планировщика, чтобы увидеть свои цифры.</span><button class="btn btn-primary" data-act="upload" type="button">Загрузить</button></div>`;
  const withData = model.months.filter(hasData);
  const lastM = withData[withData.length - 1];
  const lastDate = lastM ? monthStats(lastM, model.settings).lastDate : null;
  const la = new Date(model.loadedAt);
  const loaded = `${String(la.getDate()).padStart(2, '0')}.${String(la.getMonth() + 1).padStart(2, '0')} в ${String(la.getHours()).padStart(2, '0')}:${String(la.getMinutes()).padStart(2, '0')}`;
  let warn = '';
  if (model.quality.uncachedShare > 0.3) warn = `<div class="warnbox"><b>Файл не пересчитан.</b> В нём нет значений формул — так бывает, если файл собран программой и ни разу не сохранялся в Excel. Откройте его в Excel, нажмите «Сохранить» и загрузите снова.</div>`;
  else if (model.quality.staleDays) warn = `<div class="warnbox">В ${model.quality.staleDays} дн. суммы дня в Excel не пересчитались — посчитал их сам из таблицы категорий. Сохраните файл в Excel ещё раз, чтобы цифры совпали полностью.</div>`;
  return `<div class="fresh"><span class="dot" style="background:var(--good)"></span>Данные по ${lastDate ? dayLong(lastDate) : '—'} · загружено ${loaded}</div>${warn}`;
}

function monthSwitch() {
  const ms = state.model.months, i = ms.findIndex(m => m.key === state.monthKey);
  const m = ms[i];
  return `<div class="mswitch">
    <button type="button" data-act="mprev" ${i <= 0 ? 'disabled' : ''} aria-label="Предыдущий месяц"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg></button>
    <div class="mname"><h1 class="screen-title">${esc(m.name)}</h1><div class="screen-sub">${m.archive ? 'архив, вне плана' : hasData(m) ? `записи по ${dayLong(monthStats(m, state.model.settings).lastDate)}` : 'пока без записей'}</div></div>
    <button type="button" data-act="mnext" ${i >= ms.length - 1 ? 'disabled' : ''} aria-label="Следующий месяц"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg></button>
  </div>`;
}

function heroCard(m, st) {
  if (!hasData(m)) {
    return `<section class="hero"><div class="hero-k">Дневной лимит · ${esc(m.name.toLowerCase())}</div>
      <div class="hero-v">${fmt(st.free)}<span class="cur">₽</span></div>
      <div class="hero-cap">в день на еду, транспорт и развлечения. Записей за этот месяц пока нет.</div></section>`;
  }
  const ok = st.dev >= 0;
  const share = st.budget ? Math.min(1, st.spentLimit / st.budget) : 0;
  const overShare = st.budget && st.spentLimit > st.budget ? Math.min(1, (st.spentLimit - st.budget) / st.spentLimit) : 0;
  return `<section class="hero" aria-label="Дневной лимит">
    <div class="row"><div class="hero-k">Лимит с начала месяца</div><span class="pill ${ok ? 'pill-good' : 'pill-bad'}">${ok ? 'в запасе' : 'перерасход'}</span></div>
    <div class="hero-v">${signed(st.dev)}<span class="cur">₽</span></div>
    <div class="hero-cap">за ${st.elapsed} ${plural(st.elapsed, 'день', 'дня', 'дней')}: потрачено <b>${rub(st.spentLimit)}</b> из <b>${rub(st.budget)}</b> · в среднем <b>${fmt(st.avgLimit)}</b> в день при лимите ${fmt(st.free)}</div>
    <div class="meter" role="img" aria-label="Потрачено ${Math.round(share * 100)}% лимита">
      <i style="width:${(ok ? share : 1) * 100}%;background:${ok ? 'var(--good)' : 'var(--bad)'}"></i>
      ${!ok ? `<i style="width:${(1 - overShare) * 100}%;background:rgba(255,255,255,.55)"></i>` : ''}
    </div>
    <div class="meter-legend"><span>${ok ? `осталось ${rub(st.dev)} до лимита` : `лимит ${rub(st.budget)} превышен на ${rub(-st.dev)}`}</span><span>${st.overDays} ${plural(st.overDays, 'день', 'дня', 'дней')} сверх</span></div>
  </section>`;
}
function plural(n, a, b, c) { n = Math.abs(n) % 100; const k = n % 10; if (n > 10 && n < 20) return c; if (k > 1 && k < 5) return b; if (k === 1) return a; return c; }

function screenObzor() {
  const model = state.model, m = curMonth(), st = monthStats(m, model.settings);
  const s = model.settings;
  const sv = model.savings;
  const nowKey = todayISO().slice(0, 7);
  const svNow = sv.find(r => r.key === nowKey) || sv.find(r => r.key === m.key) || sv[0];
  const svEnd = sv[sv.length - 1];
  const goal = s.goal;
  // last recorded day
  const lastDay = st.lastIdx >= 0 ? m.days[st.lastIdx] : null;
  const months = model.months.filter(x => hasData(x) && !x.archive);
  const monthsAll = model.months.filter(hasData);
  const p = m.panel;
  const names = f => { const l = m.catNames.filter((_, i) => (m.catFlags[i] !== false) === f).map(x => x.toLowerCase()); return l.length > 3 ? l.slice(0, 3).join(', ') + '…' : l.join(', '); };
  return `
    ${freshLine(model)}
    <div><h1 class="screen-title">${esc(m.name)}</h1></div>
    ${heroCard(m, st)}
    <div class="tiles">
      <div class="tile"><div class="tile-k">Потрачено всего</div><div class="tile-v">${rub(st.spentAll)}</div><div class="tile-s">все траты месяца</div></div>
      <div class="tile"><div class="tile-k"><span class="dot" style="background:var(--good)"></span>Из лимита</div><div class="tile-v">${rub(st.spentLimit)}</div><div class="tile-s">${esc(names(true))}</div></div>
      <div class="tile"><div class="tile-k"><span class="dot" style="background:var(--out)"></span>Из отложенных</div><div class="tile-v">${rub(st.spentOut)}</div><div class="tile-s">${esc(names(false))}</div></div>
      <div class="tile"><div class="tile-k">Доходы</div><div class="tile-v">${rub(st.income)}</div><div class="tile-s">записано за месяц</div></div>
    </div>
    ${lastDay ? `<div class="card">
      <div class="card-h"><span class="card-t">Последний день в файле</span><span class="card-note">${WD[pd(lastDay.date).wd]}, ${dayLong(lastDay.date)}</span></div>
      <div class="row"><div><div style="font-size:26px;font-weight:650" class="tnum">${rub(lastDay.limit)}</div><div class="muted small">из лимита ${fmt(st.free)} ₽${lastDay.all - lastDay.limit > 0 ? ` · ещё ${rub(lastDay.all - lastDay.limit)} из отложенных` : ''}</div></div>
      <span class="pill ${lastDay.limit <= st.free ? 'pill-good' : 'pill-bad'}">${signed(st.free - lastDay.limit)} ₽</span></div>
    </div>` : ''}
    ${p.onHand != null ? `<div class="card"><div class="card-h"><span class="card-t">Деньги на руках</span><span class="card-note">по данным панели месяца</span></div>
      <div class="kv">
        <div class="kv-row"><span class="k">На руках</span><span class="v">${rub(num(p.onHand))}</span></div>
        <div class="kv-row"><span class="k">Хватает по</span><span class="v">${p.enoughUntil ? dayLong(p.enoughUntil) : '—'}</span></div>
        <div class="kv-row"><span class="k">Доложить до конца месяца</span><span class="v">${typeof p.needMore === 'number' ? rub(p.needMore) : '—'}</span></div>
      </div></div>` : ''}
    ${monthsAll.length > 1 ? `<div class="card"><div class="card-h"><span class="card-t">Траты по месяцам</span></div><div class="chart" id="chMonths"></div>
      <div class="legend"><span><i style="background:var(--navy)"></i>из лимита</span><span><i style="background:var(--out)"></i>из отложенных</span></div></div>` : ''}
    <button class="card" type="button" data-act="tab" data-tab="nakopleniya" style="text-align:left;cursor:pointer;font:inherit;color:inherit;width:100%">
      <div class="card-h"><span class="card-t">Накопительный счёт</span><span class="card-note">по плану ›</span></div>
      <div class="kv">
        <div class="kv-row"><span class="k">На конец ${svNow ? esc(monthGen(svNow.name)) : '—'}</span><span class="v">${rub(svNow?.balance)}</span></div>
        <div class="kv-row"><span class="k">Прогноз на ${s.end ? dateRu(s.end) : 'конец'}</span><span class="v">${rub(svEnd?.balance)}</span></div>
        <div class="kv-row"><span class="k">Цель</span><span class="v">${rub(goal)}</span></div>
      </div>
    </button>`;
}
function monthGen(name) { const m = MONTH_RE.exec(name); return m ? `${GEN[MONTHS.indexOf(m[1])]} ${m[2]}` : name; }

function afterObzor() {
  const host = $('#chMonths');
  if (!host) return;
  const ms = state.model.months.filter(hasData);
  const W = host.clientWidth || 340, H = 170, L = 44, R = 6, T = 12, B = 24, pw = W - L - R, ph = H - T - B;
  const data = ms.map(m => { const s = monthStats(m, state.model.settings); return { m, a: s.spentLimit, b: s.spentOut }; });
  const { max, step } = niceMax(Math.max(...data.map(d => d.a + d.b)));
  const y = v => T + ph - (v / max) * ph;
  const band = pw / data.length, bw = Math.min(24, band * 0.55), xc = i => L + band * i + band / 2;
  let g = '';
  for (let v = 0; v <= max + 1e-9; v += step) g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" style="stroke:var(--line)"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="10.5" style="fill:var(--muted)">${compact(v)}</text>`;
  let bars = '';
  data.forEach((d, i) => {
    const x = xc(i) - bw / 2, hA = (d.a / max) * ph, hB = (d.b / max) * ph;
    if (d.b > 0) { bars += `<path d="${roundTopRect(x, y(0) - hA - hB, bw, Math.max(0, hB - 2), 4)}" style="fill:var(--out)"/><rect x="${x}" y="${y(0) - hA}" width="${bw}" height="${hA}" style="fill:var(--navy)"/>`; }
    else bars += `<path d="${roundTopRect(x, y(0) - hA, bw, hA, 4)}" style="fill:var(--navy)"/>`;
    bars += `<text x="${xc(i)}" y="${y(d.a + d.b) - 6}" text-anchor="middle" font-size="11" font-weight="600" style="fill:var(--ink)">${compact(d.a + d.b)}</text>`;
    bars += `<text x="${xc(i)}" y="${H - 6}" text-anchor="middle" font-size="10.5" style="fill:var(--muted)">${SHORT[+d.m.key.slice(5) - 1]} ${d.m.key.slice(2, 4)}</text>`;
  });
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Траты по месяцам">${g}${bars}<line class="xhair" x1="0" x2="0" y1="${T}" y2="${T + ph}" style="stroke:var(--ink-2);opacity:0"/></svg>`;
  attachTip(host, data.length, xc, i => `<b>${esc(data[i].m.name)}</b><div class="tr"><span><i class="sw" style="background:var(--navy)"></i>из лимита</span><span>${rub(data[i].a)}</span></div><div class="tr"><span><i class="sw" style="background:var(--out)"></i>из отложенных</span><span>${rub(data[i].b)}</span></div>`);
}

function screenMesyac() {
  const m = curMonth(), st = monthStats(m, state.model.settings), p = m.panel;
  const today = todayISO();
  const rows = m.days.map((d, i) => {
    const p0 = pd(d.date);
    const future = d.date > today && d.all == null;
    if (d.all == null) {
      return `<div class="day-row ${future ? 'future' : 'empty'}"><div class="day-d"><b>${p0.d}</b><span>${WD[p0.wd]}</span></div><div class="day-mid"><div class="day-meta">${future ? '' : 'нет записей'}</div></div><div class="day-r"></div></div>`;
    }
    const over = d.limit > st.free, dev = st.free - d.limit;
    const w = Math.min(100, (d.limit / (st.free * 2)) * 100);
    const catsTxt = d.cats ? d.cats.map((v, k) => v ? m.catNames[k] : null).filter(Boolean).join(', ') : '';
    const open = state.openDay === d.date;
    const detail = open && d.cats ? `<div class="day-detail">${d.cats.map((v, k) => v ? `<span><i class="dot" style="background:${catColor(m.catNames[k], k)}"></i>${esc(m.catNames[k])} ${rub(v)}</span>` : '').join('')}</div>` : '';
    return `<button type="button" class="day-row" data-day="${d.date}" aria-expanded="${open}">
      <div class="day-d"><b>${p0.d}</b><span>${WD[p0.wd]}</span></div>
      <div class="day-mid"><div class="day-bar"><i style="width:${w}%;background:var(${over ? '--bad' : '--good'})"></i><span class="lim" style="left:50%"></span></div>
        <div class="day-meta">${esc(catsTxt) || '—'}${d.all - d.limit > 0 ? ` · всего ${rub(d.all)}` : ''}</div></div>
      <div class="day-r"><b>${rub(d.limit)}</b><span class="pill ${over ? 'pill-bad' : 'pill-good'}">${signed(dev)}</span></div>
      ${detail}
    </button>`;
  }).join('');
  return `
    ${monthSwitch()}
    <div class="tiles">
      <div class="tile"><div class="tile-k">Из лимита</div><div class="tile-v">${rub(st.spentLimit)}</div><div class="tile-s">лимит ${fmt(st.free)} ₽ в день</div></div>
      <div class="tile"><div class="tile-k">К лимиту</div><div class="tile-v" style="color:var(${st.dev >= 0 ? '--good' : '--bad'})">${signed(st.dev)} ₽</div><div class="tile-s">за ${st.elapsed} ${plural(st.elapsed, 'день', 'дня', 'дней')}</div></div>
    </div>
    <div class="card">
      <div class="card-h"><span class="card-t">Расходы по дням</span><span class="card-note">нажмите на столбик</span></div>
      <div class="chart" id="chDaily"></div>
      <div class="legend"><span><i style="background:var(--good)"></i>в лимите</span><span><i style="background:var(--bad)"></i>сверх лимита</span><span><i style="background:var(--out)"></i>из отложенных</span><span><i class="ln" style="background:var(--gold)"></i>лимит ${fmt(st.free)}</span></div>
    </div>
    <div class="card">
      <div class="card-h"><span class="card-t">Итоги месяца</span></div>
      <div class="kv">
        <div class="kv-row"><span class="k">Потрачено всего</span><span class="v">${rub(st.spentAll)}</span></div>
        <div class="kv-row"><span class="k">— из дневного лимита</span><span class="v">${rub(st.spentLimit)}</span></div>
        <div class="kv-row"><span class="k">— из отложенных</span><span class="v">${rub(st.spentOut)}</span></div>
        <div class="kv-row"><span class="k">Дней сверх лимита</span><span class="v">${st.overDays} из ${st.elapsed}</span></div>
        <div class="kv-row"><span class="k">Доходы</span><span class="v">${rub(st.income)}</span></div>
        <div class="kv-row"><span class="k">Отложено на счёт (факт / план)</span><span class="v">${fmt(st.factSave)} / ${fmt(st.planSave)} ₽</span></div>
        ${p.onHand != null ? `<div class="kv-row"><span class="k">На руках · хватает по</span><span class="v">${rub(num(p.onHand))} · ${p.enoughUntil ? dateRu(p.enoughUntil).slice(0, 5) : '—'}</span></div>` : ''}
        ${st.emptyDays ? `<div class="kv-row"><span class="k">Дней без записей</span><span class="v" style="color:var(--gold)">${st.emptyDays}</span></div>` : ''}
      </div>
    </div>
    <div class="card">
      <div class="card-h"><span class="card-t">По дням</span><span class="card-note">нажмите, чтобы раскрыть</span></div>
      <div class="days">${rows}</div>
    </div>`;
}
function afterMesyac() { const h = $('#chDaily'); if (h) dailyChart(h, curMonth(), monthStats(curMonth(), state.model.settings)); }

function screenKategorii() {
  const m = curMonth(), st = monthStats(m, state.model.settings);
  const cats = st.cats.slice().sort((a, b) => b.total - a.total);
  const top = Math.max(1, ...cats.map(c => c.total));
  const inSum = st.cats.filter(c => c.inLimit).reduce((a, c) => a + c.total, 0);
  const outSum = st.spentAll - inSum;
  const zero = cats.filter(c => !c.total).map(c => c.name);
  const list = cats.filter(c => c.total).map(c => `
    <div class="cat-row">
      <div class="cat-name"><span class="dot" style="background:${catColor(c.name, c.idx)}"></span><span>${esc(c.name)}</span><span class="tag ${c.inLimit ? 'tag-in' : 'tag-out'}">${c.inLimit ? 'в лимите' : 'отдельно'}</span></div>
      <div class="cat-val">${rub(c.total)}<small>${st.spentAll ? Math.round((c.total / st.spentAll) * 100) : 0}%</small></div>
      <div class="cat-bar"><i style="width:${(c.total / top) * 100}%;background:${catColor(c.name, c.idx)}"></i></div>
    </div>`).join('');
  const active = st.cats.filter(c => c.total > 0);
  const chips = active.map(c => `<button type="button" class="chip" data-cat="${esc(c.name)}" aria-pressed="${!state.catOff[c.name]}"><span class="dot" style="background:${catColor(c.name, c.idx)}"></span>${esc(c.name)}</button>`).join('');
  return `
    ${monthSwitch()}
    <div class="card">
      <div class="card-h"><span class="card-t">Куда ушли деньги</span><span class="card-note">${rub(st.spentAll)}</span></div>
      ${st.spentAll ? `<div class="split" role="img" aria-label="В лимите ${Math.round(inSum / st.spentAll * 100)}%">
        <i style="width:${inSum / st.spentAll * 100}%;background:var(--good)"></i><i style="width:${outSum / st.spentAll * 100}%;background:var(--gold)"></i></div>
      <div class="row small" style="margin-bottom:14px"><span><span class="dot" style="background:var(--good)"></span> в лимите <b class="tnum">${rub(inSum)}</b></span><span><span class="dot" style="background:var(--gold)"></span> отдельно <b class="tnum">${rub(outSum)}</b></span></div>` : ''}
      <div class="cats">${st.spentAll ? list : '<div class="muted">В этом месяце трат пока нет.</div>'}</div>
      ${st.spentAll && zero.length ? `<div class="card-note" style="margin-top:12px">Без трат: ${esc(zero.join(', ').toLowerCase())}</div>` : ''}
    </div>
    ${active.length ? `<div class="card">
      <div class="card-h"><span class="card-t">Категории по дням</span>
        <div class="seg" role="group" aria-label="Режим графика"><button type="button" data-mode="cum" aria-pressed="${state.catMode === 'cum'}">Итогом</button><button type="button" data-mode="day" aria-pressed="${state.catMode === 'day'}">По дням</button></div>
      </div>
      <div class="chart" id="chCats"></div>
      <div class="chips" style="margin-top:12px">${chips}</div>
      <div class="card-note" style="margin-top:8px">${state.catMode === 'cum' ? 'Нарастающий итог: сколько накопилось по каждой категории к этому дню.' : 'Сколько потрачено в каждый день. Нажмите на категорию, чтобы скрыть или показать линию.'}</div>
    </div>` : ''}`;
}
function afterKategorii() {
  const host = $('#chCats'); if (!host) return;
  const m = curMonth(), st = monthStats(m, state.model.settings);
  const last = st.lastIdx;
  const series = st.cats.filter(c => c.total > 0 && !state.catOff[c.name]).map(c => {
    let acc = 0;
    const values = m.days.map((d, i) => {
      if (i > last) return null;
      const v = (d.cats && d.cats[c.idx]) || 0;
      acc += v;
      return state.catMode === 'cum' ? acc : v;
    });
    return { name: c.name, color: catColor(c.name, c.idx), values };
  });
  const n = m.days.length;
  lineChart(host, {
    labels: m.days.map(d => d.date), series, H: 220,
    xTicks: [[0, '1'], [9, '10'], [19, '20'], [n - 1, String(n)]],
    tipTitle: i => dayLong(m.days[i].date),
  });
}

function screenNakopleniya() {
  const s = state.model.settings, sv = state.model.savings;
  if (!sv.length) return `<h1 class="screen-title">Накопления</h1><div class="card muted">В файле нет листа «Накопления».</div>`;
  const end = sv[sv.length - 1];
  const nowKey = todayISO().slice(0, 7);
  const nowIdx = sv.findIndex(r => r.key === nowKey);
  const now = sv[nowIdx] || sv[0];
  const goal = s.goal || 0;
  const over = end.balance - goal;
  const thresholds = [100000, 250000, 500000, goal, 1000000, 1500000].filter((v, i, a) => v && a.indexOf(v) === i && v <= end.balance * 1.001).sort((a, b) => a - b);
  const ms = thresholds.map(t => { const r = sv.find(x => x.balance >= t); return { t, r, goal: t === goal }; });
  const years = sv.filter(r => /^Декабрь/.test(r.name) || r === end);
  const facts = state.model.months.filter(m => hasData(m) && !m.archive).map(m => ({ m, st: monthStats(m, s) }));
  return `
    <div><h1 class="screen-title">Накопления</h1><div class="screen-sub">${s.start ? dateRu(s.start) : ''} — ${s.end ? dateRu(s.end) : ''} · ${sv.length} мес.</div></div>
    <section class="hero">
      <div class="hero-k">Прогноз на ${s.end ? dateRu(s.end) : 'конец плана'}</div>
      <div class="hero-v">${fmt(end.balance)}<span class="cur">₽</span></div>
      <div class="hero-cap">цель <b>${rub(goal)}</b> · ${over >= 0 ? `сверх цели <b>${rub(over)}</b>` : `не хватает <b>${rub(-over)}</b>`}</div>
      <div class="meter"><i style="width:${Math.min(100, (now.balance / (end.balance || 1)) * 100)}%;background:var(--gold)"></i></div>
      <div class="meter-legend"><span>сейчас по плану ${rub(now.balance)}</span><span>${Math.round((now.balance / (end.balance || 1)) * 100)}% пути</span></div>
    </section>
    <div class="card">
      <div class="card-h"><span class="card-t">Рост счёта</span><span class="card-note">нажмите на график</span></div>
      <div class="chart" id="chSave"></div>
      <div class="legend"><span><i class="ln" style="background:var(--navy)"></i>баланс счёта</span><span><i class="ln" style="background:var(--muted)"></i>внесено мной</span><span><i class="ln" style="background:var(--gold)"></i>сейчас</span></div>
    </div>
    <div class="tiles">
      <div class="tile"><div class="tile-k">Внесу за весь срок</div><div class="tile-v">${compact(end.contribCum)}${NBSP}₽</div><div class="tile-s">${fmt(s.dailySave)} ₽ в день</div></div>
      <div class="tile"><div class="tile-k">Проценты за срок</div><div class="tile-v">${compact(end.interestCum)}${NBSP}₽</div><div class="tile-s">ставка ${s.rate != null ? nf2.format(s.rate * 100) : '—'}% годовых</div></div>
    </div>
    <div class="card">
      <div class="card-h"><span class="card-t">Рубежи</span></div>
      <div class="ms">${ms.map(x => `<div class="ms-row ${x.r && x.r.key <= nowKey ? 'done' : ''} ${x.goal ? 'goal' : ''}"><span class="ms-mark"></span><span>${x.goal ? '<b>Цель</b> ' : ''}${rub(x.t)}</span><span class="muted tnum">${x.r ? esc(x.r.name.toLowerCase()) : '—'}</span></div>`).join('')}</div>
    </div>
    ${facts.length ? `<div class="card">
      <div class="card-h"><span class="card-t">Отложено: факт и план</span></div>
      <div class="kv">${facts.map(f => `<div class="kv-row"><span class="k">${esc(f.m.name)}</span><span class="v" style="color:var(${f.st.factSave >= f.st.planSave ? '--good' : '--bad'})">${fmt(f.st.factSave)} <span class="muted" style="font-weight:500">/ ${fmt(f.st.planSave)} ₽</span></span></div>`).join('')}</div>
    </div>` : ''}
    <div class="card">
      <div class="card-h"><span class="card-t">Баланс на конец года</span></div>
      <div class="kv">${years.map(r => `<div class="kv-row"><span class="k">${esc(r.name)}</span><span class="v">${rub(r.balance)}</span></div>`).join('')}</div>
    </div>
    <div class="card-note" style="padding:0 4px">Прогноз считается по плану из листа «Накопления»: ${fmt(s.dailySave)} ₽ в день и ${s.rate != null ? nf2.format(s.rate * 100) : '—'}% годовых на весь срок. Фактические пополнения в прогноз не входят, а ставка за пять лет почти наверняка изменится, так что это ориентир, а не обещание.</div>`;
}
function afterNakopleniya() {
  const host = $('#chSave'); if (!host) return;
  const sv = state.model.savings, n = sv.length;
  const nowIdx = sv.findIndex(r => r.key === todayISO().slice(0, 7));
  const yearTicks = [];
  sv.forEach((r, i) => { if (/^Январь/.test(r.name)) yearTicks.push([i, r.key.slice(0, 4)]); });
  lineChart(host, {
    labels: sv.map(r => r.name), H: 210,
    series: [
      { name: 'Баланс', color: 'var(--navy)', values: sv.map(r => r.balance) },
      { name: 'Внесено', color: 'var(--muted)', values: sv.map(r => r.contribCum), width: 1.5, endDot: false },
    ],
    area: { index: 0 }, marker: nowIdx, xTicks: yearTicks,
    tipTitle: i => sv[i].name,
  });
}

/* ================= app shell ================= */
const SCREENS = {
  obzor: [screenObzor, afterObzor], mesyac: [screenMesyac, afterMesyac],
  kategorii: [screenKategorii, afterKategorii], nakopleniya: [screenNakopleniya, afterNakopleniya],
};
let enterTimer, countRaf = [];
const REDUCED = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
function clearEnter(main) {
  clearTimeout(enterTimer);
  countRaf.forEach(cancelAnimationFrame); countRaf = [];
  main.classList.remove('enter', 'dir-next', 'dir-prev');
}
/* stagger: --n on top-level blocks and rows; chart marks get --i and animation hooks */
function stagger(main) {
  [...main.children].forEach((el, i) => el.style.setProperty('--n', i));
  main.querySelectorAll('.tile, .cat-row, .day-row, .kv-row, .ms-row').forEach((el, i) => el.style.setProperty('--n', i % 9));
  main.querySelectorAll('svg').forEach(svg => {
    let bi = 0, fi = 0;
    svg.querySelectorAll('rect[style*="fill:var"], path[style*="fill:var"]:not([opacity])').forEach(el => {
      if (el.closest('.tip') || /fill:var\(--(surface|line)\)/.test(el.getAttribute('style') || '')) return;
      el.classList.add('bar'); el.style.setProperty('--i', bi++);
    });
    svg.querySelectorAll('path[fill="none"][stroke-width]').forEach(el => { el.setAttribute('pathLength', '1'); el.classList.add('ln-draw'); });
    svg.querySelectorAll('circle[r]').forEach(el => el.classList.add('dot-pop'));
    svg.querySelectorAll('text').forEach(el => { if (el.getAttribute('text-anchor') === 'middle' && el.getAttribute('font-weight')) { el.classList.add('fade'); el.style.setProperty('--i', fi++); } });
  });
}
/* count-up for pure numbers ("12 345 ₽", "+1 200"); text with dates/words is left alone */
function countUp(main) {
  main.querySelectorAll('.hero-v, .tile-v, .kv-row .v').forEach(el => {
    const node = [...el.childNodes].find(n => n.nodeType === 3 && /\d/.test(n.nodeValue));
    if (!node) return;
    const m = node.nodeValue.match(/^([^\d]{0,2})(\d[\d\s\u00a0]*\d|\d)([\s\u00a0]*[^\d\s]{0,3})?$/);
    if (!m) return;
    const end = parseInt(m[2].replace(/[\s\u00a0]/g, ''), 10);
    if (!(end > 0) || end > 1e12) return;
    const text = node.nodeValue, t0 = performance.now(), dur = 900;
    const step = now => {
      const p = Math.min((now - t0) / dur, 1);
      const e = p < .5 ? 4 * p ** 3 : 1 - (-2 * p + 2) ** 3 / 2;
      node.nodeValue = p >= 1 ? text : m[1] + nf0.format(Math.round(end * e)) + (m[3] || '');
      if (p < 1) countRaf.push(requestAnimationFrame(step));
    };
    countRaf.push(requestAnimationFrame(step));
  });
}
function render(anim = false, dir = 0) {
  const main = $('#main');
  clearEnter(main);
  document.querySelectorAll('.tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.tab === state.tab)));
  if (!state.model) { main.innerHTML = welcome(); if (anim && !REDUCED()) { stagger(main); main.classList.add('enter'); enterTimer = setTimeout(() => main.classList.remove('enter'), 2200); } return; }
  const [scr, after] = SCREENS[state.tab];
  main.innerHTML = scr();
  after();
  if (anim && !REDUCED()) {
    stagger(main);
    main.classList.add('enter');
    if (dir < 0) main.classList.add('dir-prev'); else if (dir > 0) main.classList.add('dir-next');
    countUp(main);
    enterTimer = setTimeout(() => main.classList.remove('enter', 'dir-next', 'dir-prev'), 2200);
  }
  const sub = $('#brandSub');
  if (sub) sub.textContent = state.model.demo ? 'Пример данных' : (state.model.fileName || 'Накопительный счёт 2026–2031');
}
function welcome() {
  return `<div class="welcome">
    <h1 class="screen-title">Финансы из Excel — на экране телефона</h1>
    <ol class="steps"><li>Сохраните планировщик в Excel после правок.</li><li>Перешлите файл на телефон: в «Избранное» Телеграма, на Яндекс Диск или в Google Диск.</li><li>Нажмите «Загрузить файл» и выберите его. Данные останутся в памяти телефона и откроются без интернета.</li></ol>
    <button class="btn btn-primary" data-act="upload" type="button">Загрузить файл</button>
    <button class="btn" data-act="demo" type="button">Посмотреть на примере</button></div>`;
}
let toastTimer;
function toast(msg) {
  let t = $('.toast');
  if (!t) { t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3600);
}
function saveUI() { store.set(UI_KEY, { tab: state.tab, catMode: state.catMode, catOff: state.catOff }); }
function setModel(model, fromFile) {
  state.model = model;
  state.monthKey = defaultMonthKey(model);
  state.openDay = null;
  if (fromFile) {
    const ok = store.set(KEY, model);
    const withData = model.months.filter(hasData);
    const last = withData.length ? monthStats(withData[withData.length - 1], model.settings).lastDate : null;
    toast(ok ? `Загружено. Данные по ${last ? dayLong(last) : '—'}.` : 'Загружено, но память браузера недоступна: после закрытия файл придётся загрузить снова.');
  }
  render(true);
}

async function handleFile(file) {
  if (!file) return;
  const ov = document.createElement('div');
  ov.className = 'loading'; ov.innerHTML = '<div><div class="spin"></div>Читаю файл…</div>';
  document.body.appendChild(ov);
  try {
    const buf = await file.arrayBuffer();
    const model = await parsePlanner(buf, file.name);
    setModel(model, true);
  } catch (e) {
    console.error(e);
    toast(e instanceof AppError ? e.message : 'Не получилось прочитать файл. Проверьте, что это .xlsx из Excel.');
  } finally { ov.remove(); }
}

function init() {
  const ui = store.get(UI_KEY) || {};
  const hash = (location.hash || '').slice(1);
  state.tab = SCREENS[hash] ? hash : (SCREENS[ui.tab] ? ui.tab : 'obzor');
  state.catMode = ui.catMode === 'day' ? 'day' : 'cum';
  state.catOff = ui.catOff || {};
  const saved = store.get(KEY);
  setModel(saved && saved.v === 1 ? saved : demoModel(), false);

  $('#btnUpload').addEventListener('click', () => $('#fileInput').click());
  $('#fileInput').addEventListener('change', e => { handleFile(e.target.files[0]); e.target.value = ''; });
  document.querySelector('.tabbar').addEventListener('click', e => {
    const b = e.target.closest('.tab'); if (!b) return;
    state.tab = b.dataset.tab; saveUI(); render(true); window.scrollTo(0, 0);
    b.classList.remove('pop'); void b.offsetWidth; b.classList.add('pop');
  });
  $('#main').addEventListener('click', e => {
    const a = e.target.closest('[data-act],[data-day],[data-cat],[data-mode]');
    if (!a) return;
    const ms = state.model?.months || [];
    const i = ms.findIndex(m => m.key === state.monthKey);
    if (a.dataset.act === 'upload') $('#fileInput').click();
    else if (a.dataset.act === 'demo') setModel(demoModel(), false);
    else if (a.dataset.act === 'mprev' && i > 0) { state.monthKey = ms[i - 1].key; state.openDay = null; render(true, -1); }
    else if (a.dataset.act === 'mnext' && i < ms.length - 1) { state.monthKey = ms[i + 1].key; state.openDay = null; render(true, 1); }
    else if (a.dataset.act === 'tab') { state.tab = a.dataset.tab; saveUI(); render(true); window.scrollTo(0, 0); }
    else if (a.dataset.day) { state.openDay = state.openDay === a.dataset.day ? null : a.dataset.day; const y = window.scrollY; render(); window.scrollTo(0, y); }
    else if (a.dataset.cat) { state.catOff[a.dataset.cat] = !state.catOff[a.dataset.cat]; saveUI(); afterKategorii(); a.setAttribute('aria-pressed', String(!state.catOff[a.dataset.cat])); }
    else if (a.dataset.mode) { state.catMode = a.dataset.mode; saveUI(); const y = window.scrollY; render(); window.scrollTo(0, y); }
  });
  let rw = window.innerWidth;
  window.addEventListener('resize', () => { if (Math.abs(window.innerWidth - rw) > 20) { rw = window.innerWidth; render(); } });
}
init();


if ('serviceWorker' in navigator && location.protocol === 'https:') {
  window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}

