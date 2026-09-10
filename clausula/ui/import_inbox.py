from __future__ import annotations


PANEL = r'''
<section class="panel" id="import-inbox-panel" style="margin-top:12px">
  <div class="panel-head">
    <div>
      <h2>Import inbox</h2>
      <div class="caption">Reconcile a browser-selected CSV against one account before granting any ledger write authority.</div>
    </div>
    <span class="badge" id="import-preview-status">PREVIEW ONLY</span>
  </div>
  <div style="display:grid;grid-template-columns:minmax(250px,.8fr) minmax(0,1.2fr) auto;gap:10px;align-items:end">
    <div class="field">
      <label for="import-account">Account UUID</label>
      <input id="import-account" autocomplete="off" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
    </div>
    <div class="field">
      <label for="import-file">Ledger CSV</label>
      <input id="import-file" type="file" accept=".csv,text/csv" style="padding:9px 12px">
    </div>
    <button class="primary" id="import-preview-button" type="button">Reconcile CSV</button>
  </div>
  <div class="caption" id="import-preview-note" style="margin-top:10px">The browser sends only the selected file bytes plus the account UUID. Clausula reads no caller-supplied server path, performs no import, and exposes no write credential.</div>
  <div class="error" id="import-preview-error" style="margin-top:12px;margin-bottom:0"></div>
  <div id="import-preview-result" style="margin-top:14px"><div class="empty">Choose an account and CSV to classify rows as new, already imported, or conflicting.</div></div>
</section>
'''

SCRIPT = r'''
<script>
(() => {
  "use strict";
  const MAX_BYTES = 2 * 1024 * 1024;
  const accountInput = document.getElementById("import-account");
  const fileInput = document.getElementById("import-file");
  const button = document.getElementById("import-preview-button");
  const status = document.getElementById("import-preview-status");
  const error = document.getElementById("import-preview-error");
  const result = document.getElementById("import-preview-result");
  if (!accountInput || !fileInput || !button || !status || !error || !result) return;

  const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); };
  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = String(value);
    return node;
  };
  const showError = (message) => {
    error.textContent = message;
    error.classList.add("show");
    status.textContent = "INVALID";
    status.className = "badge bad";
  };
  const clearError = () => {
    error.textContent = "";
    error.classList.remove("show");
  };
  const base64 = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Failed to read file"));
    reader.onload = () => {
      const value = String(reader.result || "");
      const comma = value.indexOf(",");
      if (comma < 0) reject(new Error("Browser did not produce a data URL"));
      else resolve(value.slice(comma + 1));
    };
    reader.readAsDataURL(file);
  });
  const importTone = (value) => value === "new" ? "good" : value === "conflict_external_id" ? "bad" : "warn";
  const importLabel = (value) => value === "new" ? "NEW" : value === "duplicate_exact" ? "ALREADY IMPORTED" : value === "conflict_external_id" ? "CONFLICT" : "UNCLASSIFIED";

  const renderCounts = (preview) => {
    const reconciliation = preview.reconciliation || {};
    const block = document.createElement("div");
    block.style.cssText = "display:flex;flex-wrap:wrap;gap:7px;margin:12px 0 4px";
    block.append(
      text("span", `${reconciliation.new || 0} NEW`, "badge good"),
      text("span", `${reconciliation.duplicate_exact || 0} ALREADY IMPORTED`, "badge warn"),
      text("span", `${reconciliation.conflict_external_id || 0} CONFLICT`, "badge bad"),
    );
    return block;
  };

  const render = (preview) => {
    clear(result);
    const reconciliation = preview.reconciliation || {};
    const conflicts = Number(reconciliation.conflict_external_id || 0);
    status.textContent = conflicts ? "CONFLICT" : preview.ok ? "RECONCILED" : "NEEDS FIXES";
    status.className = conflicts || !preview.ok ? "badge bad" : "badge good";

    const summary = document.createElement("div");
    summary.className = "list";
    const main = document.createElement("div");
    main.className = "main";
    main.append(
      text("div", `${preview.filename || "upload.csv"} · ${preview.row_count} rows`, "title"),
      text("div", `SHA-256 ${String(preview.source_sha256 || "").slice(0, 16)}… · ${preview.upload_bytes || preview.source_bytes || 0} bytes`, "copy"),
    );
    summary.append(main, text("span", preview.ok ? `${preview.valid_rows} parsed` : `${(preview.errors || []).length} errors`, preview.ok ? "badge good" : "badge bad"));
    result.append(summary, renderCounts(preview));

    for (const issue of preview.errors || []) {
      const row = document.createElement("div");
      row.className = "list";
      const left = document.createElement("div");
      left.className = "main";
      left.append(
        text("div", `Row ${issue.row} · ${issue.field}`, "title"),
        text("div", issue.message, "copy"),
      );
      row.append(left, text("span", issue.code, "badge bad"));
      result.appendChild(row);
    }

    for (const transaction of (preview.transactions || []).slice(0, 20)) {
      const row = document.createElement("div");
      row.className = "list";
      const left = document.createElement("div");
      left.className = "main";
      const instrumentLeg = (transaction.legs || []).find((leg) => leg.instrument);
      const instrument = instrumentLeg && instrumentLeg.instrument ? instrumentLeg.instrument.identifier : "CASH";
      const defaults = transaction.defaulted_fields || [];
      left.append(
        text("div", `Row ${transaction.row} · ${transaction.type} · ${instrument}`, "title"),
        text("div", defaults.length ? `Defaults: ${defaults.join(", ")}` : "No implicit defaults", "copy"),
      );
      const right = document.createElement("div");
      right.style.cssText = "display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end";
      right.append(
        text("span", importLabel(transaction.import_status), `badge ${importTone(transaction.import_status)}`),
        text("span", String(transaction.effective_at || "").slice(0, 10), "badge"),
      );
      row.append(left, right);
      result.appendChild(row);
    }
    if ((preview.transactions || []).length > 20) {
      result.appendChild(text("div", `Showing first 20 of ${preview.transactions.length} normalized rows.`, "empty"));
    }
  };

  fileInput.addEventListener("change", () => {
    clearError();
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      status.textContent = "PREVIEW ONLY";
      status.className = "badge";
      return;
    }
    status.textContent = file.size > MAX_BYTES ? "TOO LARGE" : "READY";
    status.className = file.size > MAX_BYTES ? "badge bad" : "badge";
  });

  button.addEventListener("click", async () => {
    clearError();
    const accountId = accountInput.value.trim();
    const file = fileInput.files && fileInput.files[0];
    if (!accountId) {
      showError("Enter the account UUID to reconcile this CSV.");
      return;
    }
    if (!file) {
      showError("Select a CSV first.");
      return;
    }
    if (file.size > MAX_BYTES) {
      showError(`CSV preview is limited to ${MAX_BYTES} bytes.`);
      return;
    }
    button.disabled = true;
    status.textContent = "RECONCILING";
    status.className = "badge warn";
    try {
      const content = await base64(file);
      const response = await fetch("/workspace/import-preview", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({account_id: accountId, filename: file.name, content_base64: content}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || `Preview failed (${response.status})`);
      render(payload);
    } catch (problem) {
      showError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      button.disabled = false;
    }
  });
})();
</script>
'''


def augment_import_inbox(document: str) -> str:
    """Add an account-aware, content-only CSV reconciliation surface."""

    if 'id="import-inbox-panel"' in document:
        return document
    if "<footer" in document:
        document = document.replace("<footer", PANEL + "<footer", 1)
    else:
        document = document.replace("</body>", PANEL + "</body>", 1)
    return document.replace("</body>", SCRIPT + "</body>", 1)
