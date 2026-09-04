from __future__ import annotations


def workspace_document() -> str:
    """Return the dependency-free local Capital Cockpit shell."""

    return r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clausula · Capital Cockpit</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #f4f5f2;
  --surface: rgba(255,255,255,.84);
  --surface-strong: #fff;
  --surface-soft: #eceee9;
  --ink: #171a17;
  --muted: #687068;
  --line: rgba(26,34,27,.12);
  --accent: #315b49;
  --accent-soft: #dfeae4;
  --good: #2d6a4f;
  --warn: #8a5a17;
  --bad: #9f3a38;
  --shadow: 0 18px 50px rgba(40,48,41,.08);
  --radius: 18px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111411;
    --surface: rgba(26,30,26,.9);
    --surface-strong: #1c211d;
    --surface-soft: #222823;
    --ink: #eef1ed;
    --muted: #a1aaa1;
    --line: rgba(235,242,235,.11);
    --accent: #8db8a2;
    --accent-soft: #23372d;
    --good: #83c5a4;
    --warn: #dfb36e;
    --bad: #e78e8a;
    --shadow: 0 22px 60px rgba(0,0,0,.26);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background:
    radial-gradient(circle at 16% -10%, color-mix(in srgb, var(--accent) 10%, transparent), transparent 34rem),
    var(--bg);
  color: var(--ink);
  font: 14px/1.45 Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  letter-spacing: -.006em;
}
button,input { font: inherit; }
button { color: inherit; }
.shell { max-width: 1480px; margin: 0 auto; padding: 26px 30px 56px; }
.topbar { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:30px; }
.brand { display:flex; align-items:center; gap:11px; font-weight:760; letter-spacing:-.035em; font-size:18px; }
.mark { width:28px; height:28px; border:1px solid var(--line); border-radius:9px; display:grid; place-items:center; background:var(--surface-strong); box-shadow:var(--shadow); }
.mark:before { content:"C"; font-family:Georgia,serif; font-weight:700; color:var(--accent); }
.meta-actions { display:flex; align-items:center; gap:8px; }
.pill,.icon-button { border:1px solid var(--line); background:var(--surface); backdrop-filter:blur(10px); }
.pill { border-radius:999px; padding:7px 10px; font-size:11px; font-weight:720; color:var(--muted); letter-spacing:.06em; }
.icon-button { width:36px; height:36px; border-radius:11px; cursor:pointer; display:grid; place-items:center; }
.icon-button:hover { background:var(--surface-strong); }
.hero { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:end; gap:28px; margin-bottom:22px; }
h1 { margin:0; font-size:clamp(34px,4vw,58px); line-height:.98; letter-spacing:-.065em; font-weight:770; }
.hero-copy { margin:12px 0 0; max-width:720px; color:var(--muted); font-size:15px; }
.flow { display:flex; flex-wrap:wrap; gap:6px; justify-content:flex-end; max-width:470px; }
.flow span { padding:6px 9px; border-radius:999px; background:var(--surface-soft); color:var(--muted); font-size:11px; font-weight:650; }
.flow b { color:var(--accent); }
.controls { display:grid; grid-template-columns:minmax(260px,1.5fr) minmax(160px,.7fr) minmax(160px,.7fr) auto; gap:10px; padding:12px; background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow); margin-bottom:18px; }
.field { min-width:0; }
.field label { display:block; font-size:10px; text-transform:uppercase; letter-spacing:.1em; font-weight:750; color:var(--muted); margin:0 0 5px 3px; }
.field input { width:100%; height:42px; border:1px solid var(--line); border-radius:11px; padding:0 12px; background:var(--surface-strong); color:var(--ink); outline:none; }
.field input:focus { border-color:color-mix(in srgb,var(--accent) 55%,var(--line)); box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 10%,transparent); }
.primary { align-self:end; height:42px; border:0; border-radius:11px; padding:0 18px; background:var(--accent); color:#fff; font-weight:740; cursor:pointer; }
.primary:hover { filter:brightness(1.06); }
.primary:disabled { opacity:.55; cursor:wait; }
.context-line { min-height:25px; display:flex; align-items:center; justify-content:space-between; gap:16px; color:var(--muted); font-size:12px; margin:0 4px 12px; }
.status { display:inline-flex; align-items:center; gap:6px; }
.dot { width:7px; height:7px; border-radius:999px; background:var(--muted); }
.dot.good { background:var(--good); box-shadow:0 0 0 4px color-mix(in srgb,var(--good) 12%,transparent); }
.dot.bad { background:var(--bad); box-shadow:0 0 0 4px color-mix(in srgb,var(--bad) 12%,transparent); }
.kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:12px; }
.card,.panel { background:var(--surface); border:1px solid var(--line); box-shadow:var(--shadow); backdrop-filter:blur(14px); }
.card { border-radius:16px; padding:17px 18px 16px; min-height:118px; }
.eyebrow { color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-size:10px; font-weight:760; }
.metric { font-size:27px; letter-spacing:-.045em; font-weight:750; margin-top:16px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.metric.small { font-size:21px; }
.submetric { margin-top:4px; color:var(--muted); font-size:11px; }
.private .sensitive { color:transparent!important; text-shadow:0 0 8px var(--ink); user-select:none; }
.grid { display:grid; grid-template-columns:minmax(0,1.65fr) minmax(330px,.8fr); gap:12px; align-items:start; }
.stack { display:grid; gap:12px; }
.panel { border-radius:var(--radius); padding:19px; overflow:hidden; }
.panel-head { display:flex; justify-content:space-between; align-items:flex-start; gap:14px; margin-bottom:16px; }
.panel h2 { margin:0; font-size:16px; letter-spacing:-.025em; }
.panel-caption { color:var(--muted); font-size:11px; margin-top:3px; }
.badge { border-radius:999px; padding:5px 8px; font-size:10px; font-weight:760; letter-spacing:.04em; background:var(--surface-soft); color:var(--muted); white-space:nowrap; }
.badge.good { color:var(--good); background:color-mix(in srgb,var(--good) 12%,transparent); }
.badge.warn { color:var(--warn); background:color-mix(in srgb,var(--warn) 13%,transparent); }
.badge.bad { color:var(--bad); background:color-mix(in srgb,var(--bad) 12%,transparent); }
.alloc-row { display:grid; grid-template-columns:140px minmax(0,1fr) 88px; gap:12px; align-items:center; padding:7px 0; }
.alloc-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:610; }
.bar { height:7px; border-radius:999px; background:var(--surface-soft); overflow:hidden; }
.bar > span { display:block; height:100%; border-radius:999px; background:var(--accent); min-width:2px; }
.alloc-value { text-align:right; font-variant-numeric:tabular-nums; color:var(--muted); }
.rule { display:grid; grid-template-columns:10px minmax(0,1fr) auto; gap:10px; align-items:start; padding:11px 0; border-top:1px solid var(--line); }
.rule:first-child { border-top:0; padding-top:0; }
.rule-dot { width:8px; height:8px; border-radius:999px; margin-top:5px; background:var(--muted); }
.rule-dot.compliant { background:var(--good); }
.rule-dot.violation { background:var(--bad); }
.rule-dot.unavailable { background:var(--warn); }
.rule-title { font-weight:650; }
.rule-copy { color:var(--muted); font-size:11px; margin-top:2px; }
.rail-item { position:relative; padding:0 0 17px 19px; border-left:1px solid var(--line); margin-left:4px; }
.rail-item:last-child { padding-bottom:0; }
.rail-item:before { content:""; position:absolute; left:-4px; top:5px; width:7px; height:7px; border-radius:999px; background:var(--accent); box-shadow:0 0 0 4px var(--surface-strong); }
.rail-title { font-weight:660; }
.rail-meta { color:var(--muted); font-size:11px; margin-top:3px; }
.list-item { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; padding:10px 0; border-top:1px solid var(--line); }
.list-item:first-child { border-top:0; padding-top:0; }
.list-main { min-width:0; }
.list-title { font-weight:650; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.list-copy { color:var(--muted); font-size:11px; margin-top:3px; }
.empty { color:var(--muted); padding:20px 0 8px; text-align:center; font-size:12px; }
.gap-row { display:grid; grid-template-columns:78px 1fr; gap:10px; padding:9px 0; border-top:1px solid var(--line); }
.gap-row:first-child { border-top:0; padding-top:0; }
.gap-kind { font-size:10px; font-weight:760; text-transform:uppercase; color:var(--warn); }
.gap-copy { color:var(--muted); font-size:11px; }
.error-box { display:none; margin-bottom:12px; border:1px solid color-mix(in srgb,var(--bad) 35%,var(--line)); background:color-mix(in srgb,var(--bad) 8%,var(--surface)); color:var(--bad); padding:11px 13px; border-radius:12px; font-size:12px; white-space:pre-wrap; }
.error-box.show { display:block; }
footer { color:var(--muted); font-size:10px; margin-top:18px; padding:0 4px; display:flex; justify-content:space-between; gap:20px; }
@media (max-width: 980px) {
  .shell { padding:20px 16px 42px; }
  .hero { grid-template-columns:1fr; }
  .flow { justify-content:flex-start; }
  .controls { grid-template-columns:1fr 1fr; }
  .field:first-child { grid-column:1/-1; }
  .kpis { grid-template-columns:1fr 1fr; }
  .grid { grid-template-columns:1fr; }
}
@media (max-width: 590px) {
  .topbar { margin-bottom:22px; }
  .pill { display:none; }
  .controls { grid-template-columns:1fr; }
  .field:first-child { grid-column:auto; }
  .primary { width:100%; }
  .kpis { grid-template-columns:1fr; }
  .alloc-row { grid-template-columns:95px minmax(0,1fr) 70px; }
  footer { display:block; }
}
</style>
</head>
<body>
<div class="shell">
  <div class="topbar">
    <div class="brand"><span class="mark"></span>Clausula</div>
    <div class="meta-actions">
      <span class="pill">LOCAL · READ ONLY</span>
      <button class="icon-button" id="privacy" title="Mask monetary values" aria-label="Toggle privacy">◉</button>
    </div>
  </div>

  <section class="hero">
    <div>
      <h1>Capital Cockpit</h1>
      <p class="hero-copy">A decision-first view of capital state, policy boundaries, feasible plans and the memory of what you actually decided.</p>
    </div>
    <div class="flow" aria-label="Clausula decision loop">
      <span><b>State</b></span><span>Boundary</span><span>Attention</span><span>Evidence</span><span>Plan</span><span>Decision</span><span>Review</span>
    </div>
  </section>

  <section class="controls">
    <div class="field"><label for="portfolio">Portfolio UUID</label><input id="portfolio" autocomplete="off" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"></div>
    <div class="field"><label for="asof">As of</label><input id="asof" type="date"></div>
    <div class="field"><label for="known">Known as of</label><input id="known" type="date"></div>
    <button class="primary" id="load">Load snapshot</button>
  </section>

  <div class="error-box" id="error"></div>
  <div class="context-line">
    <span class="status"><span class="dot" id="state-dot"></span><span id="context">Enter a portfolio and load a point-in-time snapshot.</span></span>
    <span id="stamp"></span>
  </div>

  <section class="kpis">
    <div class="card"><div class="eyebrow">Capital</div><div class="metric sensitive" id="capital">—</div><div class="submetric" id="capital-sub">Canonical portfolio valuation</div></div>
    <div class="card"><div class="eyebrow">Cash</div><div class="metric sensitive" id="cash">—</div><div class="submetric" id="cash-sub">Liquidity inside this portfolio</div></div>
    <div class="card"><div class="eyebrow">Largest position</div><div class="metric small" id="largest">—</div><div class="submetric sensitive" id="largest-sub">Concentration</div></div>
    <div class="card"><div class="eyebrow">Data freshness</div><div class="metric small" id="freshness">—</div><div class="submetric" id="freshness-sub">Oldest accepted position price</div></div>
  </section>

  <main class="grid">
    <div class="stack">
      <section class="panel">
        <div class="panel-head"><div><h2>Capital state</h2><div class="panel-caption">Allocation is descriptive; policy determines whether it is acceptable.</div></div><span class="badge" id="complete-badge">Not loaded</span></div>
        <div id="allocation"><div class="empty">Load a snapshot to inspect allocation.</div></div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h2>Policy boundary</h2><div class="panel-caption">Effective and knowledge-dated constraints evaluated against the same snapshot.</div></div><span class="badge" id="policy-badge">—</span></div>
        <div id="policies"><div class="empty">No policy evaluation loaded.</div></div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h2>Data gaps</h2><div class="panel-caption">Clausula fails closed instead of inventing missing market truth.</div></div><span class="badge" id="gap-badge">—</span></div>
        <div id="gaps"><div class="empty">No snapshot loaded.</div></div>
      </section>
    </div>

    <aside class="stack">
      <section class="panel">
        <div class="panel-head"><div><h2>Decision memory</h2><div class="panel-caption">What you chose remains separate from what later happened.</div></div><span class="badge" id="decision-badge">—</span></div>
        <div id="decisions"><div class="empty">No decisions loaded.</div></div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h2>Plans</h2><div class="panel-caption">Persisted deterministic scenarios, not live brokerage intent.</div></div><span class="badge" id="plan-badge">—</span></div>
        <div id="plans"><div class="empty">No plans loaded.</div></div>
      </section>
    </aside>
  </main>

  <footer><span>Canonical facts remain in the local ledger. This workspace is a projection.</span><span>0.x · no autonomous brokerage execution</span></footer>
</div>
<script>
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const READ_PERMISSIONS = ["portfolio:read","market:read","policy:read","planning:read","decision:read","recommendation:read","research:read","system:read"];
  const state = { valuation: null, privacy: false };

  function isoDate(value) {
    if (!value) return null;
    return value.length === 10 ? value + "T23:59:59+00:00" : value;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function div(className, text) {
    const node = document.createElement("div");
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function badge(text, tone) {
    const node = document.createElement("span");
    node.className = "badge" + (tone ? " " + tone : "");
    node.textContent = text;
    return node;
  }
  function setBadge(id, text, tone) {
    const node = $(id); node.className = "badge" + (tone ? " " + tone : ""); node.textContent = text;
  }
  function toneFor(status) {
    if (status === "compliant" || status === "complete") return "good";
    if (status === "violation" || status === "incomplete") return "bad";
    return "warn";
  }
  function formatMoney(value, currency) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value) + (currency ? " " + currency : "");
    try { return new Intl.NumberFormat(undefined,{style:"currency",currency:currency || "USD",maximumFractionDigits:2}).format(n); }
    catch (_) { return n.toLocaleString(undefined,{maximumFractionDigits:2}) + (currency ? " " + currency : ""); }
  }
  function formatPct(value) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value); return Number.isFinite(n) ? (n * 100).toFixed(n >= .1 ? 1 : 2) + "%" : "—";
  }
  function shortDate(value) { return value ? String(value).slice(0,10) : "—"; }
  function showError(message) { const node=$("error"); node.textContent=message; node.classList.add("show"); }
  function hideError() { const node=$("error"); node.textContent=""; node.classList.remove("show"); }

  async function capability(name, payload) {
    const response = await fetch("/capabilities/" + encodeURIComponent(name), {
      method: "POST",
      cache: "no-store",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Clausula-Permissions": READ_PERMISSIONS.join(",")
      },
      body: JSON.stringify(payload || {})
    });
    const body = await response.json();
    if (!response.ok) throw new Error(name + ": " + (body.message || body.error || response.status));
    return body;
  }

  function renderAllocation(v) {
    const root=$("allocation"); clear(root);
    const rows=(v.allocation || []).slice().sort((a,b)=>Number(b.base_value)-Number(a.base_value));
    if (!rows.length) { root.appendChild(div("empty","No valued allocation lines.")); return; }
    rows.forEach((row) => {
      const line=div("alloc-row");
      line.appendChild(div("alloc-name", row.asset_type));
      const bar=div("bar"); const fill=document.createElement("span");
      const pct=Math.max(0,Math.min(100,Number(row.weight || 0)*100)); fill.style.width=pct+"%"; bar.appendChild(fill); line.appendChild(bar);
      const value=div("alloc-value sensitive", formatPct(row.weight)); value.title=formatMoney(row.base_value,v.base_currency); line.appendChild(value);
      root.appendChild(line);
    });
  }

  function renderGaps(v) {
    const root=$("gaps"); clear(root); const gaps=v.gaps || [];
    setBadge("gap-badge", gaps.length ? gaps.length + " unresolved" : "No gaps", gaps.length ? "warn" : "good");
    if (!gaps.length) { root.appendChild(div("empty","Valuation has no unresolved data gaps.")); return; }
    gaps.slice(0,12).forEach((gap) => {
      const row=div("gap-row"); row.appendChild(div("gap-kind",gap.kind || "gap"));
      row.appendChild(div("gap-copy",[gap.message,gap.instrument_id,gap.currency].filter(Boolean).join(" · ")));
      root.appendChild(row);
    });
  }

  function renderPolicies(results) {
    const root=$("policies"); clear(root);
    if (!results.length) { setBadge("policy-badge","No policy",""); root.appendChild(div("empty","No policy is attached to this portfolio.")); return; }
    const overall=results.some(x=>x.status==="violation") ? "violation" : results.some(x=>x.status==="unavailable") ? "unavailable" : "compliant";
    setBadge("policy-badge",overall, toneFor(overall));
    results.forEach((evaluation) => {
      const heading=div("list-item"); const main=div("list-main");
      main.appendChild(div("list-title", evaluation.policy_name || evaluation.policy_id));
      main.appendChild(div("list-copy","Policy v" + evaluation.version_number + " · " + (evaluation.results || []).length + " rules"));
      heading.appendChild(main); heading.appendChild(badge(evaluation.status,toneFor(evaluation.status))); root.appendChild(heading);
      (evaluation.results || []).filter(r=>r.status!=="compliant").slice(0,8).forEach((rule) => {
        const row=div("rule"); const dot=div("rule-dot " + rule.status); row.appendChild(dot);
        const copy=div(""); copy.appendChild(div("rule-title",rule.rule_key));
        const bounds=[rule.lower_bound!==null&&rule.lower_bound!==undefined ? "min "+rule.lower_bound : null, rule.upper_bound!==null&&rule.upper_bound!==undefined ? "max "+rule.upper_bound : null].filter(Boolean).join(" · ");
        copy.appendChild(div("rule-copy",[rule.rule_type,rule.current_value!==null&&rule.current_value!==undefined ? "current "+rule.current_value : "unavailable",bounds].filter(Boolean).join(" · ")));
        row.appendChild(copy); row.appendChild(badge(rule.severity || rule.status, toneFor(rule.status))); root.appendChild(row);
      });
    });
  }

  function renderDecisions(items) {
    const root=$("decisions"); clear(root); const sorted=(items || []).slice().sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at))).slice(0,8);
    setBadge("decision-badge",String((items || []).length),"");
    if (!sorted.length) { root.appendChild(div("empty","No decision memory for this portfolio yet.")); return; }
    sorted.forEach((item) => {
      const row=div("rail-item"); row.appendChild(div("rail-title",item.title || item.intent || "Decision"));
      row.appendChild(div("rail-meta",[item.intent,shortDate(item.as_of),item.plan_id ? "planned" : null].filter(Boolean).join(" · "))); root.appendChild(row);
    });
  }

  function renderPlans(items) {
    const root=$("plans"); clear(root); const sorted=(items || []).slice().sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at))).slice(0,6);
    setBadge("plan-badge",String((items || []).length),"");
    if (!sorted.length) { root.appendChild(div("empty","No persisted plans for this portfolio.")); return; }
    sorted.forEach((item) => {
      const row=div("list-item"); const main=div("list-main"); main.appendChild(div("list-title",item.name || "Plan"));
      main.appendChild(div("list-copy",[shortDate(item.as_of),item.policy_version_id ? "policy-bound" : null].filter(Boolean).join(" · "))); row.appendChild(main); root.appendChild(row);
    });
  }

  function renderValuation(v) {
    state.valuation=v; const currency=v.base_currency || "USD";
    $("capital").textContent=formatMoney(v.complete ? v.total_value : v.partial_value,currency);
    $("capital-sub").textContent=v.complete ? "Complete canonical valuation" : "Partial value · unresolved inputs excluded";
    const cash=(v.allocation || []).find(x=>x.asset_type==="cash");
    $("cash").textContent=formatMoney(cash ? cash.base_value : "0",currency);
    $("cash-sub").textContent=cash ? formatPct(cash.weight)+" of valued capital" : "No valued cash line";
    const largest=(v.concentration || [])[0];
    $("largest").textContent=largest ? largest.identifier : "—";
    $("largest-sub").textContent=largest ? formatPct(largest.weight)+" · "+formatMoney(largest.base_value,currency) : "No valued position";
    const priceDates=(v.positions || []).map(x=>x.price_observed_at).filter(Boolean).sort();
    $("freshness").textContent=priceDates.length ? shortDate(priceDates[0]) : "—";
    $("freshness-sub").textContent=priceDates.length ? "Oldest accepted position price · "+priceDates.length+" lines" : "No position price observations";
    setBadge("complete-badge",v.complete ? "Complete" : "Incomplete",v.complete ? "good" : "bad");
    $("state-dot").className="dot "+(v.complete?"good":"bad");
    $("context").textContent=(v.name || "Portfolio")+" · "+currency+" · as of "+shortDate(v.as_of)+" · known "+shortDate(v.known_as_of);
    renderAllocation(v); renderGaps(v);
  }

  async function load() {
    hideError(); const portfolio=$("portfolio").value.trim(); const asOf=isoDate($("asof").value); const known=isoDate($("known").value || $("asof").value);
    if (!portfolio || !asOf) { showError("Portfolio UUID and as-of date are required."); return; }
    const button=$("load"); button.disabled=true; button.textContent="Loading…"; $("stamp").textContent="";
    try {
      const [valuation, policies, plans, decisions] = await Promise.all([
        capability("portfolio.get_valuation",{portfolio_id:portfolio,as_of:asOf,known_as_of:known}),
        capability("policy.list",{portfolio_id:portfolio}),
        capability("planning.list",{portfolio_id:portfolio}),
        capability("decision.list",{portfolio_id:portfolio})
      ]);
      renderValuation(valuation); renderPlans(plans); renderDecisions(decisions);
      const evaluations=await Promise.all((policies || []).map(p=>capability("policy.evaluate",{policy_id:p.id,as_of:asOf,known_as_of:known})));
      renderPolicies(evaluations);
      $("stamp").textContent="Snapshot loaded locally";
      try { localStorage.setItem("clausula.cockpit.portfolio",portfolio); } catch (_) {}
    } catch (error) {
      $("state-dot").className="dot bad"; $("context").textContent="Snapshot unavailable"; showError(error instanceof Error ? error.message : String(error));
    } finally { button.disabled=false; button.textContent="Load snapshot"; }
  }

  $("load").addEventListener("click",load);
  $("privacy").addEventListener("click",()=>{ state.privacy=!state.privacy; document.body.classList.toggle("private",state.privacy); $("privacy").textContent=state.privacy?"○":"◉"; $("privacy").title=state.privacy?"Reveal monetary values":"Mask monetary values"; });
  [$("portfolio"),$("asof"),$("known")].forEach(node=>node.addEventListener("keydown",e=>{if(e.key==="Enter")load();}));
  const today=new Date().toISOString().slice(0,10); $("asof").value=today; $("known").value=today;
  try { const saved=localStorage.getItem("clausula.cockpit.portfolio"); if(saved) $("portfolio").value=saved; } catch (_) {}
})();
</script>
</body>
</html>'''
