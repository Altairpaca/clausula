from __future__ import annotations


PANEL = r'''
<section class="panel" id="execution-panel" style="margin-top:12px">
  <div class="panel-head">
    <div>
      <h2>Execution contract</h2>
      <div class="panel-caption">Deterministic market/account feasibility. Missing execution facts remain conditional.</div>
    </div>
    <span class="badge" id="execution-status">unconfigured</span>
  </div>
  <div class="list-title" id="execution-title">No active execution contract</div>
  <div class="list-copy" id="execution-copy">Versioned constraints will appear here when configured.</div>
  <div id="execution-details" style="margin-top:12px"></div>
</section>
'''

SCRIPT = r'''
<script>
(() => {
  const originalFetch = window.fetch.bind(window);
  const badgeClass = (status) => {
    if (["executable", "has_executable_scenario", "configured"].includes(status)) return "badge good";
    if (["blocked"].includes(status)) return "badge bad";
    return "badge warn";
  };
  const renderExecution = (snapshot) => {
    const execution = snapshot && snapshot.execution ? snapshot.execution : {};
    const contract = execution.contract || null;
    const plan = execution.latest_plan || null;
    const status = execution.status || "unconfigured";
    const badge = document.getElementById("execution-status");
    const title = document.getElementById("execution-title");
    const copy = document.getElementById("execution-copy");
    const details = document.getElementById("execution-details");
    if (!badge || !title || !copy || !details) return;
    badge.textContent = String(status).replaceAll("_", " ");
    badge.className = badgeClass(status);
    if (!contract) {
      title.textContent = "No active execution contract";
      copy.textContent = "Action feasibility is intentionally unavailable until a versioned contract is active at this cutoff.";
      details.replaceChildren();
      return;
    }
    title.textContent = `${contract.name} · v${contract.version_number}`;
    copy.textContent = `${contract.constraints.length} typed constraints · effective ${String(contract.effective_from).slice(0, 10)}`;
    details.replaceChildren();
    if (!plan) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No persisted Plan to evaluate against this contract.";
      details.appendChild(empty);
      return;
    }
    const counts = { executable: 0, conditional: 0, blocked: 0 };
    let missing = 0;
    for (const scenario of plan.scenarios || []) {
      const value = scenario.execution || {};
      if (counts[value.status] !== undefined) counts[value.status] += 1;
      missing += (value.missing_facts || []).length;
    }
    const rows = [
      ["Executable", counts.executable],
      ["Conditional", counts.conditional],
      ["Blocked", counts.blocked],
      ["Missing facts", missing],
    ];
    for (const [label, value] of rows) {
      const row = document.createElement("div");
      row.className = "list-item";
      const left = document.createElement("div");
      left.className = "list-title";
      left.textContent = label;
      const right = document.createElement("div");
      right.className = "badge";
      right.textContent = String(value);
      row.append(left, right);
      details.appendChild(row);
    }
  };
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const target = String(args[0] || "");
    if (target.includes("/workspace/snapshot")) {
      response.clone().json().then(renderExecution).catch(() => {});
    }
    return response;
  };
})();
</script>
'''


def augment_workspace(document: str) -> str:
    """Add execution feasibility without coupling to the base workspace renderer."""

    if "id=\"execution-panel\"" in document:
        return document
    if "</main>" in document:
        document = document.replace("</main>", PANEL + "</main>", 1)
    elif "<footer" in document:
        document = document.replace("<footer", PANEL + "<footer", 1)
    else:
        document = document.replace("</body>", PANEL + "</body>", 1)
    return document.replace("</body>", SCRIPT + "</body>", 1)
