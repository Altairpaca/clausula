from __future__ import annotations


PANEL = r'''
<section class="panel" id="equity-monitor-panel" style="margin-top:12px">
  <div class="panel-head">
    <div>
      <h2>Public-equity coverage</h2>
      <div class="panel-caption">Company thesis, security readiness and action posture stay separate. No composite conviction score.</div>
    </div>
    <span class="badge" id="equity-monitor-status">unconfigured</span>
  </div>
  <div id="equity-monitor-summary" class="list-copy">No monitored listed-equity cases for this portfolio.</div>
  <div id="equity-monitor-cases" style="margin-top:12px"></div>
</section>
'''

SCRIPT = r'''
<script>
(() => {
  const originalFetch = window.fetch.bind(window);
  const renderEquityMonitor = (snapshot) => {
    const monitor = snapshot && snapshot.equity_monitor ? snapshot.equity_monitor : {};
    const cases = Array.isArray(monitor.cases) ? monitor.cases : [];
    const badge = document.getElementById("equity-monitor-status");
    const summary = document.getElementById("equity-monitor-summary");
    const container = document.getElementById("equity-monitor-cases");
    if (!badge || !summary || !container) return;
    container.replaceChildren();
    if (!cases.length) {
      badge.textContent = "unconfigured";
      badge.className = "badge warn";
      summary.textContent = "No monitored listed-equity cases for this portfolio.";
      return;
    }
    const blocked = Number(monitor.not_decision_grade || 0);
    const reunderwrite = Number(monitor.re_underwrite || 0);
    badge.textContent = blocked ? `${blocked} not decision-grade` : reunderwrite ? `${reunderwrite} re-underwrite` : `${cases.length} active`;
    badge.className = blocked ? "badge bad" : reunderwrite ? "badge warn" : "badge good";
    summary.textContent = `${cases.length} cases · ${blocked} not decision-grade · ${reunderwrite} re-underwrite`;
    for (const item of cases.slice(0, 8)) {
      const view = item.summary || {};
      const row = document.createElement("div");
      row.className = "list-item";
      const left = document.createElement("div");
      const title = document.createElement("div");
      title.className = "list-title";
      title.textContent = view.name || "Unnamed case";
      const copy = document.createElement("div");
      copy.className = "list-copy";
      const proof = view.next_proof_point ? ` · next proof: ${view.next_proof_point}` : "";
      const missing = Array.isArray(view.missing_inputs) && view.missing_inputs.length ? ` · ${view.missing_inputs.length} blockers` : "";
      copy.textContent = `${view.company_status || "untested"} company · ${view.security_readiness || "not decision-grade"} security · ${view.action || "wait"}${missing}${proof}`;
      left.append(title, copy);
      const action = document.createElement("span");
      action.className = ["exit", "trim"].includes(view.action) ? "badge bad" : ["wait_for_proof", "re_underwrite", "hedge"].includes(view.action) ? "badge warn" : "badge";
      action.textContent = String(view.action || "wait").replaceAll("_", " ");
      row.append(left, action);
      container.appendChild(row);
    }
  };
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (String(args[0] || "").includes("/workspace/snapshot")) {
      response.clone().json().then(renderEquityMonitor).catch(() => {});
    }
    return response;
  };
})();
</script>
'''


def augment_equity_monitor(document: str) -> str:
    if 'id="equity-monitor-panel"' in document:
        return document
    if "</main>" in document:
        document = document.replace("</main>", PANEL + "</main>", 1)
    else:
        document = document.replace("</body>", PANEL + "</body>", 1)
    return document.replace("</body>", SCRIPT + "</body>", 1)
