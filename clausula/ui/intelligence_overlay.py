from __future__ import annotations


PANEL = r'''
<section class="panel" id="intelligence-panel" style="margin-top:12px">
  <div class="panel-head">
    <div>
      <h2>Decision intelligence</h2>
      <div class="panel-caption">Material attention, open recommendations, evidence pressure, review queue and decision lineage at the selected knowledge cutoff.</div>
    </div>
    <span class="badge" id="intelligence-status">quiet</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px">
    <div class="card" style="min-height:92px"><div class="eyebrow">Attention</div><div class="metric small" id="attention-count">0</div><div class="submetric" id="attention-copy">material events</div></div>
    <div class="card" style="min-height:92px"><div class="eyebrow">Recommendation inbox</div><div class="metric small" id="recommendation-count">0</div><div class="submetric">draft or reviewed</div></div>
    <div class="card" style="min-height:92px"><div class="eyebrow">Contradiction pressure</div><div class="metric small" id="contradiction-pressure">—</div><div class="submetric" id="evidence-freshness">no research evidence</div></div>
    <div class="card" style="min-height:92px"><div class="eyebrow">Review queue</div><div class="metric small" id="review-count">0</div><div class="submetric" id="review-copy">no reviews due</div></div>
  </div>
  <div id="intelligence-details" style="margin-top:14px"></div>
</section>
'''

SCRIPT = r'''
<script>
(() => {
  const inheritedFetch = window.fetch.bind(window);
  const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  const render = (snapshot) => {
    const attention = snapshot.attention || [];
    const recommendations = snapshot.recommendations || {open:[],open_count:0};
    const evidence = snapshot.evidence_pressure || {};
    const reviews = snapshot.review_queue || [];
    const lineage = snapshot.decision_lineage || [];
    const due = reviews.filter((item) => item.status === "due");
    text("attention-count", String(attention.length));
    text("attention-copy", attention.length ? `${attention.filter((x) => x.severity === "high").length} high severity` : "material events");
    text("recommendation-count", String(recommendations.open_count || 0));
    text("contradiction-pressure", evidence.contradiction_ratio == null ? "—" : `${(Number(evidence.contradiction_ratio) * 100).toFixed(1)}%`);
    text("evidence-freshness", evidence.freshness_age_days == null ? "no research evidence" : `latest evidence ${evidence.freshness_age_days}d old`);
    text("review-count", String(reviews.length));
    text("review-copy", due.length ? `${due.length} due now` : (reviews.length ? "upcoming reviews" : "no reviews due"));
    const incomplete = lineage.filter((item) => !item.complete).length;
    const status = document.getElementById("intelligence-status");
    if (status) {
      const pressured = due.length > 0 || (recommendations.open_count || 0) > 0 || attention.length > 0;
      status.textContent = pressured ? "needs attention" : "quiet";
      status.className = pressured ? "badge warn" : "badge good";
    }
    const details = document.getElementById("intelligence-details");
    if (!details) return;
    details.replaceChildren();
    const rows = [];
    for (const item of (recommendations.open || []).slice(-3).reverse()) {
      rows.push([`Recommendation · ${item.status}`, item.subject || item.recommendation_type || item.id]);
    }
    for (const item of due.slice(0,3)) {
      rows.push([`Review due · ${item.review_type}`, item.title || item.decision_id]);
    }
    for (const item of attention.slice(0,3)) {
      rows.push([`Attention · ${item.severity || "material"}`, item.summary || item.event_key]);
    }
    if (incomplete) rows.push(["Decision lineage", `${incomplete} decision(s) have missing plan/policy/evidence/execution/review stages`]);
    if (!rows.length) {
      const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "No material decision-workflow items at this snapshot."; details.appendChild(empty); return;
    }
    for (const [label, value] of rows.slice(0,7)) {
      const row = document.createElement("div"); row.className = "list-item";
      const left = document.createElement("div"); left.className = "list-main";
      const title = document.createElement("div"); title.className = "list-title"; title.textContent = label;
      const copy = document.createElement("div"); copy.className = "list-copy"; copy.textContent = value;
      left.append(title, copy); row.appendChild(left); details.appendChild(row);
    }
  };
  window.fetch = async (...args) => {
    const response = await inheritedFetch(...args);
    if (String(args[0] || "").includes("/workspace/snapshot")) response.clone().json().then(render).catch(() => {});
    return response;
  };
})();
</script>
'''


def augment_workspace(document: str) -> str:
    if "id=\"intelligence-panel\"" in document:
        return document
    if "</main>" in document:
        document = document.replace("</main>", PANEL + "</main>", 1)
    else:
        document = document.replace("</body>", PANEL + "</body>", 1)
    return document.replace("</body>", SCRIPT + "</body>", 1)
