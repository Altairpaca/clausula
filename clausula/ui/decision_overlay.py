from __future__ import annotations


PANELS = r'''
<section class="panel" id="decision-workspace-panel" style="margin-top:12px">
  <div class="panel-head">
    <div>
      <h2>Decision workspace</h2>
      <div class="panel-caption">Material changes, recommendations, evidence pressure and scheduled review — derived from append-only local facts.</div>
    </div>
    <span class="badge" id="workspace-status">quiet</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px">
    <div>
      <div class="eyebrow">Attention</div>
      <div id="attention-list" style="margin-top:10px"></div>
    </div>
    <div>
      <div class="eyebrow">Recommendation inbox</div>
      <div id="recommendation-list" style="margin-top:10px"></div>
    </div>
    <div>
      <div class="eyebrow">Evidence pressure</div>
      <div id="evidence-summary" style="margin-top:10px"></div>
    </div>
    <div>
      <div class="eyebrow">Review queue</div>
      <div id="review-list" style="margin-top:10px"></div>
    </div>
  </div>
</section>

<section class="panel" id="lineage-panel" style="margin-top:12px">
  <div class="panel-head">
    <div>
      <h2>Decision lineage</h2>
      <div class="panel-caption">Explicit recommendation → decision → plan/execution → transaction → review continuity.</div>
    </div>
    <span class="badge" id="lineage-count">0 decisions</span>
  </div>
  <div id="lineage-list"></div>
</section>
'''


SCRIPT = r'''
<script>
(() => {
  const originalFetch = window.fetch.bind(window);
  const text = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
  const dateOnly = (value) => text(value).slice(0, 10);
  const empty = (message) => {
    const node = document.createElement("div");
    node.className = "empty";
    node.textContent = message;
    return node;
  };
  const row = (title, copy, badgeText = null, badgeClass = "badge") => {
    const item = document.createElement("div");
    item.className = "list-item";
    const main = document.createElement("div");
    main.className = "list-main";
    const heading = document.createElement("div");
    heading.className = "list-title";
    heading.textContent = title;
    const detail = document.createElement("div");
    detail.className = "list-copy";
    detail.textContent = copy;
    main.append(heading, detail);
    item.appendChild(main);
    if (badgeText !== null) {
      const badge = document.createElement("div");
      badge.className = badgeClass;
      badge.textContent = String(badgeText);
      item.appendChild(badge);
    }
    return item;
  };
  const badgeFor = (status) => {
    if (["clear", "completed", "accepted", "executable", "reviewed"].includes(status)) return "badge good";
    if (["pressure", "due", "rejected", "blocked"].includes(status)) return "badge bad";
    return "badge warn";
  };

  const render = (snapshot) => {
    const workspace = snapshot && snapshot.decision_workspace ? snapshot.decision_workspace : {};
    const attentions = workspace.attention || [];
    const inbox = workspace.recommendation_inbox || [];
    const evidence = workspace.evidence || {};
    const reviews = workspace.review_queue || [];
    const lineage = workspace.lineage || [];

    const status = document.getElementById("workspace-status");
    if (status) {
      const due = reviews.filter((item) => item.status === "due").length;
      const pressure = evidence.status === "pressure";
      const active = attentions.length + inbox.length + due + (pressure ? 1 : 0);
      status.textContent = active ? `${active} active signals` : "quiet";
      status.className = pressure || due ? "badge bad" : active ? "badge warn" : "badge good";
    }

    const attentionRoot = document.getElementById("attention-list");
    if (attentionRoot) {
      attentionRoot.replaceChildren();
      if (!attentions.length) attentionRoot.appendChild(empty("No material attention events at this cutoff."));
      for (const item of attentions.slice(0, 5)) {
        attentionRoot.appendChild(row(
          text(item.summary, text(item.event_type, "Material change")),
          `${text(item.event_type, "event")} · ${dateOnly(item.occurred_at || item.recorded_at)} · ${text(item.scope, "local")}`,
          text(item.severity, "material"),
          item.severity === "critical" || item.severity === "high" ? "badge bad" : "badge warn",
        ));
      }
    }

    const recommendationRoot = document.getElementById("recommendation-list");
    if (recommendationRoot) {
      recommendationRoot.replaceChildren();
      if (!inbox.length) recommendationRoot.appendChild(empty("No draft or reviewed recommendations."));
      for (const item of inbox.slice(0, 5)) {
        recommendationRoot.appendChild(row(
          text(item.subject, "Recommendation"),
          `${text(item.recommendation_type, "action")} · ${text(item.origin, "unknown origin")} · as of ${dateOnly(item.as_of)}`,
          text(item.status, "draft"),
          badgeFor(item.status),
        ));
      }
    }

    const evidenceRoot = document.getElementById("evidence-summary");
    if (evidenceRoot) {
      evidenceRoot.replaceChildren();
      const statusText = text(evidence.status, "unlinked");
      evidenceRoot.appendChild(row(
        `${evidence.linked_evidence || 0} linked items`,
        `${evidence.contradicting_links || 0} contradicting links · ${evidence.explicit_contradictions || 0} explicit contradictions`,
        statusText,
        badgeFor(statusText),
      ));
      if (evidence.oldest_age_days !== null && evidence.oldest_age_days !== undefined) {
        evidenceRoot.appendChild(row(
          "Evidence age",
          `Newest ${text(evidence.newest_age_days, "?")}d · oldest ${text(evidence.oldest_age_days, "?")}d at the selected knowledge cutoff`,
        ));
      }
      for (const item of (evidence.items || []).slice(0, 3)) {
        evidenceRoot.appendChild(row(
          text(item.decision_title, "Decision evidence"),
          `${text(item.relation, "context")} · ${text(item.age_days, "?")}d old · ${text(item.evidence_kind, "research")}`,
          text(item.relation, "context"),
          item.relation === "contradicts" ? "badge bad" : "badge",
        ));
      }
    }

    const reviewRoot = document.getElementById("review-list");
    if (reviewRoot) {
      reviewRoot.replaceChildren();
      const actionable = reviews.filter((item) => item.status !== "completed");
      if (!actionable.length) reviewRoot.appendChild(empty("No pending scheduled reviews."));
      for (const item of actionable.slice(0, 5)) {
        reviewRoot.appendChild(row(
          text(item.decision_title, "Decision review"),
          `${text(item.review_type, "review")} · due ${dateOnly(item.due_at)}`,
          text(item.status),
          badgeFor(item.status),
        ));
      }
    }

    const lineageRoot = document.getElementById("lineage-list");
    const lineageCount = document.getElementById("lineage-count");
    if (lineageCount) lineageCount.textContent = `${lineage.length} decisions`;
    if (lineageRoot) {
      lineageRoot.replaceChildren();
      if (!lineage.length) lineageRoot.appendChild(empty("No decision lineage has been recorded."));
      for (const item of lineage.slice(0, 6)) {
        const decision = item.decision || {};
        const recs = item.recommendations || [];
        const transactions = item.transactions || [];
        const reviewsForDecision = item.reviews || [];
        lineageRoot.appendChild(row(
          text(decision.title, "Decision"),
          `${recs.length} recommendation links · ${item.plan_id ? "plan linked" : "no plan"} · ${transactions.length} transactions · ${reviewsForDecision.length} reviews`,
          text(item.stage, "decided"),
          badgeFor(item.stage),
        ));
      }
    }
  };

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const target = String(args[0] || "");
    if (target.includes("/workspace/snapshot")) {
      response.clone().json().then(render).catch(() => {});
    }
    return response;
  };
})();
</script>
'''


def augment_decision_workspace(document: str) -> str:
    if "id=\"decision-workspace-panel\"" in document:
        return document
    if "</main>" in document:
        document = document.replace("</main>", PANELS + "</main>", 1)
    else:
        document = document.replace("</body>", PANELS + "</body>", 1)
    return document.replace("</body>", SCRIPT + "</body>", 1)
