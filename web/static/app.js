/* SMC Bot — single-page app */
"use strict";

const API = {
  symbols:  () => fetch("/api/symbols").then(r => r.json()),
  defaults: () => fetch("/api/defaults").then(r => r.json()),
  runBacktest: (req) => fetch("/api/backtest", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(req),
  }).then(r => r.json()),
  jobStatus:  (id) => fetch(`/api/backtest/${id}/status`).then(r => r.json()),
  jobResult:  (id) => fetch(`/api/backtest/${id}/result`).then(r => r.json()),
  history:    (limit = 100) => fetch(`/api/history?limit=${limit}`).then(r => r.json()),
  historyGet: (id) => fetch(`/api/history/${id}`).then(r => r.json()),
  historyDel: (id) => fetch(`/api/history/${id}`, { method: "DELETE" }).then(r => r.json()),
};

const STATE = {
  defaults:    null,
  symbols:     [],
  formValues:  null,
  lastResult:  null,    // most recent finished backtest result
  currentJob:  null,    // {id, eventSource}
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const el = (tag, props = {}, ...children) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "checked" || k === "disabled" || k === "selected") { if (v) e.setAttribute(k, ""); }
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    if (typeof c === "string") e.appendChild(document.createTextNode(c));
    else e.appendChild(c);
  }
  return e;
};

const fmt = {
  money:   (n) => "$" + Math.round(n).toLocaleString(),
  moneySigned: (n) => (n >= 0 ? "+" : "") + "$" + Math.round(n).toLocaleString(),
  pct:     (n) => Math.round(n * 100) / 100 + "%",
  num:     (n, d = 2) => n.toFixed(d),
  shortDt: (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("he-IL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  },
  hms: (sec) => {
    if (!sec || sec <= 0) return "0s";
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  },
};

// ── Router ────────────────────────────────────────────────────────────────
function getRoute() {
  const h = window.location.hash || "#/backtest";
  return h.replace(/^#/, "");
}

function setActiveNav(tab) {
  $$(".nav-item").forEach(a => {
    a.classList.toggle("active", a.dataset.tab === tab);
  });
}

async function render() {
  const route = getRoute();
  const main = $("#main-content");
  main.innerHTML = "";
  if (route === "/backtest") {
    setActiveNav("backtest");
    $("#page-title").textContent = "בקטסט";
    await renderBacktest(main);
  } else if (route === "/history") {
    setActiveNav("history");
    $("#page-title").textContent = "היסטוריה";
    await renderHistory(main);
  } else if (route === "/results") {
    setActiveNav("results");
    $("#page-title").textContent = "תוצאות";
    renderResults(main, STATE.lastResult);
  } else {
    window.location.hash = "#/backtest";
  }
}

window.addEventListener("hashchange", render);

// ── Backtest form ─────────────────────────────────────────────────────────
async function renderBacktest(main) {
  if (!STATE.defaults) {
    const [defs, syms] = await Promise.all([API.defaults(), API.symbols()]);
    STATE.defaults  = defs;
    STATE.symbols   = syms.symbols;
  }
  if (!STATE.formValues) {
    // Default 2 years back
    const today = new Date();
    const twoYearsAgo = new Date();
    twoYearsAgo.setFullYear(today.getFullYear() - 2);
    STATE.formValues = {
      ...STATE.defaults,
      date_from: twoYearsAgo.toISOString().slice(0, 10),
      date_to:   today.toISOString().slice(0, 10),
    };
  }
  const v = STATE.formValues;

  const card = el("div", { class: "card" },
    el("p", { class: "card-title" }, "הגדרות בקטסט"),

    // Symbol + capital
    el("div", { class: "field-row" },
      el("div", { class: "field" },
        el("label", {}, "סימבול"),
        symbolSelect(v.symbol),
      ),
      el("div", { class: "field" },
        el("label", {}, "הון התחלתי ($)"),
        el("input", { type: "number", id: "f-capital", value: v.initial_capital, step: "1000" }),
      ),
    ),

    // Dates
    el("div", { class: "field-row" },
      el("div", { class: "field" },
        el("label", {}, "מתאריך"),
        el("input", { type: "date", id: "f-from", value: v.date_from }),
      ),
      el("div", { class: "field" },
        el("label", {}, "עד תאריך"),
        el("input", { type: "date", id: "f-to", value: v.date_to }),
      ),
    ),

    // Risk
    el("div", { class: "field" },
      el("label", { class: "toggle-row" },
        el("input", { type: "checkbox", id: "f-compound", checked: v.compound, onchange: () => { v.compound = $("#f-compound").checked; render(); } }),
        el("span", {}, "📈 ריבית דריבית (compound)"),
      ),
    ),
    v.compound
      ? el("div", { class: "field" },
          el("label", {}, "סיכון לעסקה (% מההון)"),
          el("input", { type: "number", id: "f-risk-pct", value: v.risk_pct, step: "0.1", min: "0.1" }),
        )
      : el("div", { class: "field" },
          el("label", {}, "סיכון לעסקה ($)"),
          el("input", { type: "number", id: "f-risk-usd", value: v.risk_per_trade, step: "50", min: "1" }),
        ),

    // RR
    el("div", { class: "field" },
      el("label", {}, "Risk : Reward"),
      el("select", { id: "f-rr" },
        ...[1, 1.5, 2, 2.5, 3, 3.5, 4, 5].map(rr =>
          el("option", { value: String(rr), selected: rr === v.rr }, `1 : ${rr}`)
        ),
      ),
    ),

    // Commission
    el("div", { class: "field" },
      el("label", {}, "עמלה לוט ($, round-trip)"),
      el("input", { type: "number", id: "f-commission", value: v.commission_per_lot, step: "0.5", min: "0" }),
    ),

    // Hours filter
    el("div", { class: "field" },
      el("label", {}, "מסנן שעות (זמן ישראל)"),
      el("div", { class: "hours-range" },
        el("input", { type: "number", id: "f-h-start", value: v.hours_filter_start, min: "0", max: "23" }),
        el("span", {}, "עד"),
        el("input", { type: "number", id: "f-h-end", value: v.hours_filter_end, min: "0", max: "23" }),
        el("span", { class: "muted" }, ":00"),
      ),
    ),

    // Weekday filter
    el("div", { class: "field" },
      el("label", {}, "ימים מותרים"),
      weekdayPills(v.weekday_mask),
    ),

    // Max trades / day
    el("div", { class: "field" },
      el("label", {}, "מקס׳ עסקאות ביום (0 = ללא הגבלה)"),
      el("input", { type: "number", id: "f-maxtrades", value: v.max_trades_per_day, min: "0", step: "1" }),
    ),

    // FVG toggle
    el("div", { class: "field" },
      el("label", { class: "toggle-row" },
        el("input", { type: "checkbox", id: "f-fvg", checked: v.require_fvg }),
        el("span", {}, "🟨 דרוש FVG ליד הכניסה"),
      ),
    ),
  );
  main.appendChild(card);

  // Run button
  const runBtn = el("button", {
    class: "btn btn-primary",
    id: "run-btn",
    onclick: () => onRunClicked(),
  }, "▶ הרץ בקטסט");
  main.appendChild(runBtn);

  // Progress slot (hidden until running)
  const progSlot = el("div", { id: "progress-slot", class: "" });
  main.appendChild(progSlot);
}

function symbolSelect(current) {
  const sel = el("select", { id: "f-symbol" });
  for (const s of STATE.symbols) {
    sel.appendChild(el("option", { value: s, selected: s === current }, s));
  }
  return sel;
}

const WEEKDAY_LABELS = ["א'", "ב'", "ג'", "ד'", "ה'", "ו'", "ש'"];

function weekdayPills(mask) {
  const wrap = el("div", { class: "day-pills" });
  for (let i = 0; i < 7; i++) {
    const isOn = (mask & (1 << i)) !== 0;
    const pill = el("div", { class: `day-pill ${isOn ? "active" : ""}`, "data-day": String(i) }, WEEKDAY_LABELS[i]);
    pill.addEventListener("click", () => {
      pill.classList.toggle("active");
    });
    wrap.appendChild(pill);
  }
  return wrap;
}

function collectForm() {
  const v = STATE.formValues;
  v.symbol             = $("#f-symbol").value;
  v.initial_capital    = parseFloat($("#f-capital").value);
  v.date_from          = $("#f-from").value;
  v.date_to            = $("#f-to").value;
  v.compound           = $("#f-compound").checked;
  v.rr                 = parseFloat($("#f-rr").value);
  v.commission_per_lot = parseFloat($("#f-commission").value || 0);
  v.hours_filter_start = parseInt($("#f-h-start").value, 10);
  v.hours_filter_end   = parseInt($("#f-h-end").value, 10);
  v.max_trades_per_day = parseInt($("#f-maxtrades").value, 10) || 0;
  v.require_fvg        = $("#f-fvg").checked;

  if (v.compound) {
    v.risk_pct       = parseFloat($("#f-risk-pct").value);
  } else {
    v.risk_per_trade = parseFloat($("#f-risk-usd").value);
  }

  // Build weekday mask from pill states
  let mask = 0;
  $$(".day-pill").forEach(p => {
    if (p.classList.contains("active")) {
      mask |= 1 << parseInt(p.dataset.day, 10);
    }
  });
  v.weekday_mask = mask;
  return v;
}

// ── Run + SSE progress ────────────────────────────────────────────────────
async function onRunClicked() {
  const v = collectForm();
  $("#run-btn").setAttribute("disabled", "");
  $("#run-btn").textContent = "⏳ רץ…";
  $("#progress-slot").innerHTML = "";

  try {
    const { job_id, error } = await API.runBacktest(v);
    if (error) throw new Error(error);
    STATE.currentJob = { id: job_id };
    startProgressStream(job_id);
  } catch (e) {
    showError(e.message || String(e));
    $("#run-btn").removeAttribute("disabled");
    $("#run-btn").textContent = "▶ הרץ בקטסט";
  }
}

function startProgressStream(jobId) {
  const slot = $("#progress-slot");
  slot.innerHTML = `
    <div class="progress-card">
      <div class="progress-text">
        <span id="prog-phase">מאתחל…</span>
        <span class="pct" id="prog-pct">0%</span>
      </div>
      <div class="progress-bar"><div id="prog-bar" style="width:0%"></div></div>
      <div class="progress-eta" id="prog-eta">—</div>
    </div>`;

  const phaseLabel = (p) => ({
    "queued":         "ממתין…",
    "results-cache":  "בודק cache תוצאות…",
    "data":           "טוען נתונים…",
    "signals":        "מעבד אינדיקטורים…",
    "engine":         "מריץ בקטסט…",
    "done":           "הסתיים ✓",
    "error":          "שגיאה",
  }[p] || p);

  // Use SSE
  const es = new EventSource(`/api/backtest/${jobId}/stream`);
  STATE.currentJob.eventSource = es;

  es.addEventListener("progress", (ev) => {
    const d = JSON.parse(ev.data);
    $("#prog-phase").textContent = phaseLabel(d.phase);
    $("#prog-pct").textContent   = Math.round((d.progress || 0) * 100) + "%";
    $("#prog-bar").style.width   = Math.round((d.progress || 0) * 100) + "%";
    if (d.phase === "engine") {
      $("#prog-eta").textContent = `${d.n_trades} עסקאות · נותרו ~${fmt.hms(d.eta_sec)}`;
    } else {
      $("#prog-eta").textContent = "מעבד…";
    }
  });
  es.addEventListener("done", (ev) => {
    const result = JSON.parse(ev.data);
    es.close();
    STATE.lastResult = result;
    $("#run-btn").removeAttribute("disabled");
    $("#run-btn").textContent = "▶ הרץ בקטסט";
    window.location.hash = "#/results";
  });
  es.addEventListener("error", (ev) => {
    let msg = "שגיאה לא ידועה";
    try { msg = JSON.parse(ev.data).error || msg; } catch {}
    es.close();
    showError(msg);
    $("#run-btn").removeAttribute("disabled");
    $("#run-btn").textContent = "▶ הרץ בקטסט";
  });
}

function showError(msg) {
  const slot = $("#progress-slot");
  if (slot) {
    slot.innerHTML = `<div class="error-banner">⚠ ${msg}</div>`;
  }
}

// ── Results ──────────────────────────────────────────────────────────────
function renderResults(main, result) {
  if (!result) {
    main.appendChild(el("div", { class: "empty-state" },
      "אין תוצאות להצגה. עבור לעמוד הבקטסט והרץ ריצה."));
    return;
  }
  const s = result.stats || {};
  const isOk = (s.total_trades || 0) > 0;

  // Summary header
  const headerCard = el("div", { class: "card" },
    el("p", { class: "card-title" }, `${result.symbol} · ${result.date_from} → ${result.date_to}${result.cached ? " · ⚡ מ-cache" : ""}`),
    el("div", { class: "stats-grid" },
      stat("עסקאות", s.total_trades || 0),
      stat("Win Rate", (s.win_rate_pct ?? 0) + "%", `${s.wins || 0}W / ${s.losses || 0}L`),
      stat("Net P&L", fmt.moneySigned(s.net_pnl_usd || 0), null, (s.net_pnl_usd || 0) >= 0 ? "green" : "red"),
      stat("Profit Factor", (s.profit_factor ?? 0).toFixed(2)),
      stat("Max DD", (s.max_dd_pct ?? 0).toFixed(2) + "%", null, "red"),
      stat("Avg R:R", (s.avg_rr ?? 0).toFixed(2)),
    )
  );
  main.appendChild(headerCard);

  if (!isOk) {
    main.appendChild(el("div", { class: "empty-state" }, "לא נמצאו עסקאות"));
    return;
  }

  // Holding times
  const holdCard = el("div", { class: "card" },
    el("p", { class: "card-title" }, "זמני החזקה ממוצעים"),
    el("div", { class: "stats-grid" },
      stat("Long", `${s.long_trades || 0} עסקאות`, fmt.hms(s.avg_hold_long_sec || 0), "green"),
      stat("Short", `${s.short_trades || 0} עסקאות`, fmt.hms(s.avg_hold_short_sec || 0), "red"),
    )
  );
  main.appendChild(holdCard);

  // Equity curve
  const eqCard = el("div", { class: "card" },
    el("p", { class: "card-title" }, "Equity Curve"),
    el("div", { id: "equity-chart" }),
  );
  main.appendChild(eqCard);

  // Trade list
  const tradesCard = el("div", { class: "card" },
    el("p", { class: "card-title" }, `כל ${result.trades.length} העסקאות`),
    tradeList(result.trades, result),
  );
  main.appendChild(tradesCard);

  // Render the equity chart
  setTimeout(() => renderEquityChart(result.equity_curve), 50);
}

function stat(label, value, sub = null, color = null) {
  return el("div", { class: "stat" },
    el("div", { class: "lbl" }, label),
    el("div", { class: `val ${color || ""}` }, String(value)),
    sub ? el("div", { class: "sub" }, sub) : null,
  );
}

function tradeList(trades, result) {
  const wrap = el("div", { class: "trade-list" });
  trades.forEach((t, idx) => {
    const isWin = t.result === "win";
    const isLong = t.direction === "bull";
    const row = el("div", { class: "trade-row" },
      el("div", { class: `dir ${isLong ? "long" : "short"}` }, isLong ? "▲" : "▼"),
      el("div", { class: "meta" },
        el("div", {}, `${isLong ? "LONG" : "SHORT"} #${idx + 1}`),
        el("div", { class: "time" }, fmt.shortDt(t.entry_time)),
      ),
      el("div", { class: `pnl ${isWin ? "win" : "loss"}` },
        (t.pnl_usd >= 0 ? "+" : "") + Math.round(t.pnl_usd) + "$"),
    );
    row.addEventListener("click", () => openTradeModal(t, idx, result));
    wrap.appendChild(row);
  });
  return wrap;
}

function renderEquityChart(eqPoints) {
  const container = $("#equity-chart");
  if (!container || !eqPoints || !eqPoints.length) return;
  container.innerHTML = "";
  const chart = LightweightCharts.createChart(container, {
    autoSize: true,
    layout: { background: { color: "#0e1118" }, textColor: "#8a92a6" },
    grid: { vertLines: { color: "rgba(38,45,61,0.5)" }, horzLines: { color: "rgba(38,45,61,0.5)" } },
    rightPriceScale: { borderColor: "#262d3d" },
    timeScale: { borderColor: "#262d3d", timeVisible: false },
  });
  const series = chart.addAreaSeries({
    lineColor: "#26a69a",
    topColor: "rgba(38,166,154,0.4)",
    bottomColor: "rgba(38,166,154,0.05)",
    lineWidth: 2,
  });
  const data = eqPoints.map(p => ({
    time: Math.floor(new Date(p.time).getTime() / 1000),
    value: p.equity,
  }));
  // Lightweight-charts requires unique sorted timestamps
  const seen = new Set();
  const dedup = [];
  for (const d of data) {
    if (seen.has(d.time)) continue;
    seen.add(d.time);
    dedup.push(d);
  }
  series.setData(dedup);
  chart.timeScale().fitContent();
}

// ── Trade detail modal ───────────────────────────────────────────────────
function openTradeModal(trade, idx, result) {
  const isWin = trade.result === "win";
  const isLong = trade.direction === "bull";
  const backdrop = el("div", { class: "modal-backdrop", onclick: (e) => { if (e.target === backdrop) backdrop.remove(); } });
  const modal = el("div", { class: "modal" },
    el("div", { class: "modal-header" },
      el("h2", {}, `${isLong ? "LONG ▲" : "SHORT ▼"} · ${isWin ? "✅ WIN" : "❌ LOSS"}`),
      el("button", { class: "modal-close", onclick: () => backdrop.remove() }, "×"),
    ),
    el("div", { class: "card" },
      el("div", { class: "stats-grid" },
        stat("P&L", fmt.moneySigned(trade.pnl_usd), null, isWin ? "green" : "red"),
        stat("Risk", "$" + Math.round(trade.risk_usd)),
        stat("Lot", trade.lot_size.toFixed(2)),
      ),
      el("div", { style: "margin-top:12px;font-size:13px;line-height:1.7" },
        el("div", {}, `Entry: ${trade.entry_price.toFixed(5)}`),
        el("div", {}, `SL: ${trade.sl_price.toFixed(5)}`),
        el("div", {}, `TP: ${trade.tp_price.toFixed(5)}`),
        el("div", { class: "muted", style: "margin-top:6px" }, `כניסה: ${fmt.shortDt(trade.entry_time)}`),
        el("div", { class: "muted" }, `יציאה: ${fmt.shortDt(trade.exit_time)}`),
      ),
    ),
    el("div", { class: "card" },
      el("p", { class: "card-title" }, "גרף ויזואלי"),
      el("div", { id: "trade-chart", class: "trade-chart-container" }),
    ),
  );
  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);

  setTimeout(() => renderTradeChart(trade), 100);
}

function renderTradeChart(trade) {
  // Without per-trade OHLC data, render a minimal price-line chart between key levels.
  // (A full candlestick view would require an extra endpoint with the surrounding bars.)
  const container = $("#trade-chart");
  if (!container) return;
  container.innerHTML = "";
  const chart = LightweightCharts.createChart(container, {
    autoSize: true,
    layout: { background: { color: "#0e1118" }, textColor: "#8a92a6" },
    grid: { vertLines: { color: "rgba(38,45,61,0.4)" }, horzLines: { color: "rgba(38,45,61,0.4)" } },
    rightPriceScale: { borderColor: "#262d3d" },
    timeScale: { borderColor: "#262d3d", timeVisible: true },
  });
  const series = chart.addLineSeries({ lineColor: "#00c2d6", lineWidth: 2 });
  const t1 = Math.floor(new Date(trade.entry_time).getTime() / 1000);
  const t2 = trade.exit_time ? Math.floor(new Date(trade.exit_time).getTime() / 1000) : t1 + 3600;
  series.setData([
    { time: t1, value: trade.entry_price },
    { time: t2, value: trade.exit_price ?? trade.tp_price },
  ]);
  series.createPriceLine({ price: trade.entry_price, color: "#f0b429", lineWidth: 2, axisLabelVisible: true, title: "Entry" });
  series.createPriceLine({ price: trade.sl_price,    color: "#ef5350", lineWidth: 2, axisLabelVisible: true, title: "SL" });
  series.createPriceLine({ price: trade.tp_price,    color: "#26a69a", lineWidth: 2, axisLabelVisible: true, title: "TP" });
  chart.timeScale().fitContent();
}

// ── History ──────────────────────────────────────────────────────────────
async function renderHistory(main) {
  main.appendChild(el("div", { class: "empty-state" }, "טוען היסטוריה…"));
  const data = await API.history(200);
  main.innerHTML = "";
  if (!data.runs || !data.runs.length) {
    main.appendChild(el("div", { class: "empty-state" }, "אין עדיין ריצות שמורות."));
    return;
  }
  for (const r of data.runs) {
    const stats = r.stats || {};
    const row = el("div", { class: "history-row" },
      el("div", { class: "top" },
        el("div", { class: "symbol" }, r.symbol),
        el("div", { class: "when" }, new Date(r.timestamp).toLocaleString("he-IL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })),
      ),
      el("div", { class: "muted", style: "font-size:12px;margin-bottom:6px" },
        `${r.date_from} → ${r.date_to}`),
      el("div", { class: "stats-line" },
        el("div", {}, "עסקאות: ", el("strong", {}, String(stats.total_trades || 0))),
        el("div", {}, "WR: ", el("strong", {}, (stats.win_rate_pct || 0) + "%")),
        el("div", {}, "PF: ", el("strong", {}, (stats.profit_factor || 0).toFixed(2))),
        el("div", {}, "P&L: ", el("strong", {}, fmt.moneySigned(stats.net_pnl_usd || 0))),
      ),
    );
    row.addEventListener("click", async () => {
      const result = await API.historyGet(r.run_id);
      STATE.lastResult = result;
      window.location.hash = "#/results";
    });
    main.appendChild(row);
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  // Open Settings header button → toggles visibility of "advanced" knobs (future)
  $("#open-settings")?.addEventListener("click", () => {
    alert("הגדרות מתקדמות יבואו בעתיד");
  });

  // Register service worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  render();
});
