(() => {
  "use strict";
  const capabilityElement = document.querySelector('meta[name="workbench-capability"]');
  const capability = capabilityElement.content;
  capabilityElement.remove();
  const byId = id => document.getElementById(id);
  const axes = ["factual", "citation", "refusal_decision"];
  const axisNames = {factual: "Factual", citation: "Citation", refusal_decision: "Refusal decision"};
  const judgments = ["unscored", "correct", "incorrect", "not_applicable"];
  const label = value => value.replaceAll("_", " ");
  let cases = [], runs = [], view = null, selectedCase = null, page = 0, busy = false;
  let records = new Map(), drafts = new Map(), metadata = {}, previewGeneration = 0, previewTimer = null, comparisonSelection = null;
  let pageSize = 20;
  const filterIds = ["case-search", "answerability-filter", "synthetic-filter", "outcome-filter", "case-sort", "evidence-filter", "review-filter", "judgment-filter", "draft-filter"];
  const dirty = () => drafts.size > 0 || Object.keys(metadata).length > 0;
  const clone = value => structuredClone(value);
  const currentRecord = () => drafts.get(selectedCase) || records.get(selectedCase);

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function message(text, error = false) {
    const element = byId("message");
    element.replaceChildren(node("div", text, error ? "notice error" : "notice"));
  }
  async function api(route, payload, download = false) {
    let response;
    try {
      response = await fetch(route, {method: "POST", mode: "same-origin", credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "same-origin",
        headers: {"Content-Type": "application/json", "X-Workbench-Capability": capability}, body: JSON.stringify(payload)});
    } catch (_) { throw new Error("The local session is unavailable. Check that its terminal server is still running."); }
    if (!response.ok) {
      let detail;
      try { detail = await response.json(); } catch (_) { detail = {}; }
      throw new Error(typeof detail.error === "string" ? detail.error : "The local operation was rejected.");
    }
    return download ? response.blob() : response.json();
  }
  async function act(action) {
    if (busy) return;
    busy = true; controls();
    try { await action(); } catch (error) {
      const select = byId("run-select");
      if (view && ![...select.options].some(option => option.value === view.key)) {
        const option = node("option", view.run.run_id + " · loaded state unavailable in saved list");
        option.value = view.key; option.disabled = true; select.append(option);
      }
      select.value = view?.key || "";
      message(error.message || "The local operation failed.", true);
    }
    finally { busy = false; controls(); }
  }
  function options(select, values, previous) {
    select.replaceChildren();
    if (!values.length) select.append(node("option", "No saved runs"));
    for (const item of values) {
      const option = node("option", item.run_id + " · " + item.model_label);
      option.value = item.key; select.append(option);
    }
    if (values.some(item => item.key === previous)) select.value = previous;
  }
  function renderRuns() {
    const left = byId("left-run").value, right = byId("right-run").value;
    options(byId("run-select"), runs, view?.key);
    options(byId("left-run"), runs, left);
    options(byId("right-run"), runs, right || runs.at(-1)?.key);
    byId("run-count").textContent = runs.length + " / 8 runs saved in memory. Server restart clears all runs.";
    controls();
  }
  async function refreshRuns() {
    const state = await api("/api/runs", {});
    runs = state.runs; renderRuns();
  }
  function controls() {
    const changed = dirty(), hasRun = Boolean(view), record = currentRecord();
    for (const id of ["create-run", "new-run-id", "new-model", "import-run", "run-select"]) byId(id).disabled = busy || changed;
    byId("reload-run").disabled = busy || !hasRun;
    byId("remove-run").disabled = busy || changed || !hasRun;
    for (const id of ["save-run", "discard-run"]) byId(id).disabled = busy || !changed || !hasRun;
    for (const id of ["export-run", "export-score"]) byId(id).disabled = busy || changed || !hasRun;
    for (const id of ["left-run", "right-run", "compare-runs", "swap-runs"]) byId(id).disabled = busy || changed || !runs.length;
    byId("export-comparison").disabled = busy || changed || !comparisonSelection;
    for (const element of document.querySelectorAll("[data-meta]")) element.disabled = busy || !hasRun;
    for (const id of [...filterIds, "reset-filters", "page-size"]) byId(id).disabled = busy || !hasRun;
    for (const element of byId("case-list").querySelectorAll("button")) element.disabled = busy;
    byId("outcome").disabled = busy || !record;
    byId("restore-case").disabled = busy || !drafts.has(selectedCase);
    byId("prompt-default").disabled = busy || !record;
    byId("prompt").disabled = busy || !record || record.prompt_override === null;
    byId("response-count").textContent = "Response characters: " + Array.from(record?.response_text || "").length + " (Unicode code points).";
    byId("response").disabled = busy || !record || record.outcome === "missing";
    for (const element of document.querySelectorAll("[data-axis]")) {
      element.disabled = busy || !record || record.outcome === "missing" || (element.dataset.axis !== "refusal_decision" && record.outcome !== "answered");
    }
    byId("save-state").textContent = hasRun ? (changed ? "Unsaved draft in this tab · not included in exports or comparisons" : "Saved in server memory · revision " + view.revision) : "No run selected";
    byId("save-state").className = changed ? "changed" : "muted";
    const pages = Math.max(1, Math.ceil((hasRun ? filteredCases().length : 0) / pageSize));
    byId("previous-page").disabled = busy || page <= 0;
    byId("next-page").disabled = busy || page + 1 >= pages;
    caseNavigation();
  }
  function baseMetadata() {
    return {run_id: view.run.run_id, created_at: view.run.created_at, model_label: view.run.generation.model_label,
      review_method: view.run.review.method, reviewer_label: view.run.review.reviewer_label, parameters_text: view.parameters_text};
  }
  function loadView(value) {
    previewGeneration++; clearTimeout(previewTimer);
    view = value; drafts = new Map(); metadata = {};
    records = new Map(value.run.records.map(record => [record.case_id, record]));
    if (!records.has(selectedCase)) selectedCase = cases[0]?.id || null;
    byId("empty-state").hidden = true; byId("run-workspace").hidden = false;
    byId("run-title").textContent = value.run.run_id;
    const values = baseMetadata();
    for (const element of document.querySelectorAll("[data-meta]")) element.value = values[element.dataset.meta];
    renderMetrics(value.metrics, "Saved run"); renderCases(); renderEditor(); controls();
    clearComparison();
  }
  function clearSelection() {
    view = null; drafts.clear(); records.clear(); metadata = {}; selectedCase = null; previewGeneration++;
    byId("run-workspace").hidden = true; byId("empty-state").hidden = false; clearComparison(); controls();
  }
  function fraction(value) {
    return value.denominator ? value.numerator + " / " + value.denominator + " (" + (value.rate * 100).toFixed(1) + "%)" : "Undefined · 0 scored denominator";
  }
  function table(headers, rows) {
    const wrap = node("div", undefined, "table-scroll"), result = node("table"), head = node("thead"), heading = node("tr"), body = node("tbody");
    wrap.tabIndex = 0; wrap.setAttribute("role", "region"); wrap.setAttribute("aria-label", "Scrollable data table");
    for (const title of headers) { const cell = node("th", title); cell.scope = "col"; heading.append(cell); }
    head.append(heading);
    for (const row of rows) { const item = node("tr"); for (const value of row) item.append(node("td", String(value))); body.append(item); }
    result.append(head, body); wrap.append(result); return wrap;
  }
  function renderMetrics(metrics, state) {
    const target = byId("metrics"), cards = node("div", undefined, "metric-grid");
    for (const [name, key] of [["Answer coverage", "answer_coverage"], ["Response coverage", "response_coverage"]]) {
      const card = node("div", undefined, "metric-card"); card.append(node("span", name), node("strong", fraction(metrics[key]))); cards.append(card);
    }
    target.replaceChildren(cards, table(["Quality axis", "Correct / scored", "Judgment coverage", "Unscored", "Not applicable"], axes.map(axis => [axisNames[axis], fraction(metrics[axis].score), fraction(metrics[axis].judgment_coverage), metrics[axis].counts.unscored, metrics[axis].counts.not_applicable])));
    target.append(node("p", Object.entries(metrics.outcome_counts).map(([key, value]) => label(key) + ": " + value).join(" · "), "muted small"));
    byId("metric-state").textContent = state; byId("metric-state").className = state === "Saved run" ? "tag" : "tag dirty";
  }
  function draftPayload() { return {key: view.key, revision: view.revision, metadata, records: [...drafts.values()]}; }
  function changed() {
    previewGeneration++; clearTimeout(previewTimer); controls(); clearComparison(); renderCases();
    if (!dirty()) { renderMetrics(view.metrics, "Saved run"); return; }
    byId("metric-state").textContent = "Unsaved draft"; byId("metric-state").className = "tag dirty";
    byId("metrics").replaceChildren(node("p", "Draft changed. Waiting for authoritative Python validation…", "muted"));
    const generation = previewGeneration;
    previewTimer = setTimeout(async () => {
      try {
        const preview = await api("/api/preview", draftPayload());
        if (generation === previewGeneration && dirty()) renderMetrics(preview.metrics, "Validated draft · not saved");
      } catch (error) {
        if (generation === previewGeneration && dirty()) byId("metrics").replaceChildren(node("p", error.message + " Saved results remain unchanged; correct the draft before saving.", "notice error"));
      }
    }, 400);
  }
  function setDraft(record) {
    if (JSON.stringify(record) === JSON.stringify(records.get(record.case_id))) drafts.delete(record.case_id);
    else drafts.set(record.case_id, record);
    changed();
  }
  function resetJudgments(record) {
    for (const axis of axes) record.judgments[axis] = record.outcome !== "missing" && record.outcome !== "answered" && axis !== "refusal_decision" ? "not_applicable" : "unscored";
    for (const element of document.querySelectorAll("[data-axis]")) element.value = record.judgments[element.dataset.axis];
  }
  function filteredCases() {
    const search = byId("case-search").value.trim().toLowerCase(), answerability = byId("answerability-filter").value, synthetic = byId("synthetic-filter").value, outcome = byId("outcome-filter").value;
    const evidence = byId("evidence-filter").value, review = byId("review-filter").value;
    const judgment = byId("judgment-filter").value, draft = byId("draft-filter").value;
    const matchesJudgment = item => { const values = Object.values((drafts.get(item.id) || records.get(item.id)).judgments); return !judgment || (judgment === "complete" ? !values.includes("unscored") : values.includes(judgment)); };
    const filtered = cases.filter(item => (!draft || drafts.has(item.id) === (draft === "changed")) && matchesJudgment(item) && (!review || item.review_status === review) && (!evidence || Boolean(item.evidence.length) === (evidence === "present")) && (!search || (item.id + " " + item.question).toLowerCase().includes(search)) && (!answerability || item.answerability === answerability) && (!synthetic || item.synthetic === (synthetic === "synthetic")) && (!outcome || (drafts.get(item.id) || records.get(item.id))?.outcome === outcome));
    const order = byId("case-sort").value;
    return filtered.sort((a, b) => order === "question" ? a.question.localeCompare(b.question, "en") || a.id.localeCompare(b.id, "en") : (order === "descending" ? -1 : 1) * a.id.localeCompare(b.id, "en"));
  }
  function caseNavigation() {
    const filtered = view ? filteredCases() : [], index = filtered.findIndex(item => item.id === selectedCase);
    byId("previous-case").disabled = busy || index <= 0; byId("next-case").disabled = busy || index + 1 >= filtered.length;
    byId("case-position").textContent = index < 0 ? "Selected case is outside the filters" : "Match " + (index + 1) + " of " + filtered.length;
  }
  function renderCases() {
    if (!view) return;
    const filtered = filteredCases(), pages = Math.max(1, Math.ceil(filtered.length / pageSize));
    page = Math.min(page, pages - 1);
    byId("case-count").textContent = filtered.length + " of " + cases.length + " cases match. Draft changes persist while switching cases.";
    const list = byId("case-list"); list.replaceChildren();
    for (const item of filtered.slice(page * pageSize, (page + 1) * pageSize)) {
      const button = node("button"); button.type = "button"; button.setAttribute("aria-pressed", String(item.id === selectedCase));
      button.append(node("strong", item.id + (drafts.has(item.id) ? " · unsaved" : "")), node("span", item.question.length > 95 ? item.question.slice(0, 95) + "…" : item.question), node("span", label(item.answerability) + " · " + label((drafts.get(item.id) || records.get(item.id)).outcome), "case-state"));
      button.addEventListener("click", () => { selectedCase = item.id; renderCases(); renderEditor(); }); list.append(button);
    }
    if (!filtered.length) list.append(node("p", "No cases match these filters. Clear a filter to see more cases.", "muted"));
    caseNavigation();
    byId("page-number").textContent = (page + 1) + " / " + pages;
    byId("previous-page").disabled = busy || page === 0; byId("next-page").disabled = busy || page + 1 >= pages;
  }
  function renderEditor() {
    const item = cases.find(value => value.id === selectedCase), record = currentRecord();
    byId("case-editor").hidden = !item || !record;
    if (!item || !record) return;
    byId("case-id").textContent = item.id;
    byId("case-tags").textContent = (item.synthetic ? "Synthetic" : "Real label") + " · " + label(item.answerability);
    byId("case-question").textContent = item.question;
    byId("case-reference").textContent = item.reference_answer === null ? "No reference answer for this answerability state." : item.reference_answer;
    byId("case-review").textContent = "Recorded status: " + item.review_status + ". Reviewed date: " + (item.verified_at || "none") + ". Applicable date: " + (item.valid_as_of || "not time dependent") + ". These labels do not establish independent human certification.";
    const evidence = byId("case-evidence"); evidence.replaceChildren();
    for (const source of item.evidence) { const entry = node("li"); entry.append(node("strong", source.source_title), node("span", source.source_url), node("span", label(source.evidence_locator.type) + ": " + source.evidence_locator.value)); evidence.append(entry); }
    if (!item.evidence.length) evidence.append(node("li", "No evidence entries recorded."));
    byId("outcome").value = record.outcome;
    byId("prompt-default").checked = record.prompt_override === null; byId("prompt").value = record.prompt_override || "";
    byId("response").value = record.response_text;
    for (const element of document.querySelectorAll("[data-axis]")) element.value = record.judgments[element.dataset.axis];
    controls();
  }
  async function download(route, payload, filename) {
    const blob = await api(route, payload, true), url = URL.createObjectURL(blob), anchor = node("a");
    anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message("Export requested. The file contains supplied data; browser download location and permissions apply.");
  }
  function clearComparison() { comparisonSelection = null; byId("comparison-panel").hidden = true; byId("export-comparison").disabled = true; }
  function delta(value) { return value === null ? "Undefined" : (value > 0 ? "+" : "") + (value * 100).toFixed(1) + " percentage points"; }
  function comparisonBlock(title, group) {
    const block = node("section", undefined, "comparison-block"); block.append(node("h3", title + " · " + group.sample_size + " cases"));
    block.append(table(["Paired quality", "Baseline", "Candidate", "Delta", "Improved", "Regressed", "Unchanged", "Excluded"], axes.map(axis => { const pair = group.paired_quality[axis]; return [axisNames[axis], fraction(pair.left_score), fraction(pair.right_score), delta(pair.rate_delta), pair.improved, pair.regressed, pair.unchanged, pair.not_comparable]; })));
    block.append(table(["All-case rates", "Baseline denominator", "Candidate denominator", "Aggregate delta"], [...axes.map(axis => [axisNames[axis], fraction(group.left_metrics[axis].score), fraction(group.right_metrics[axis].score), delta(group.aggregate_deltas[axis].score.rate_delta)]), ...["answer_coverage", "response_coverage"].map(key => [label(key), fraction(group.left_metrics[key]), fraction(group.right_metrics[key]), delta(group.aggregate_deltas[key].rate_delta)])]));
    block.append(node("p", "Excluded quality pairs by axis (baseline only / candidate only / neither scored): " + axes.map(axis => { const pair = group.paired_quality[axis]; return axisNames[axis] + " " + pair.left_only_scored + " / " + pair.right_only_scored + " / " + pair.neither_scored; }).join("; "), "muted"));
    block.append(node("p", "Response availability: " + Object.entries(group.response_availability).map(([key, value]) => label(key) + " " + value).join(" · "), "muted"));
    return block;
  }
  function renderComparison(report) {
    const result = byId("comparison-result"); result.replaceChildren();
    byId("comparison-label").textContent = report.left_run_id + " → " + report.right_run_id + " · " + report.sample_scope.synthetic + " synthetic / " + report.sample_scope.real + " real-labelled cases. Descriptive comparison; no statistical significance or controlled-experiment claim.";
    const setup = node("div", undefined, "setup-flags");
    for (const [key, value] of Object.entries(report.declared_setup_changes)) setup.append(node("span", label(key) + ": " + (typeof value === "boolean" ? (value ? "yes" : "no") : value), value ? "tag dirty" : "tag"));
    result.append(setup, comparisonBlock("All cases", report.aggregate));
    const applicability = axes.map(axis => axisNames[axis] + ": from not applicable " + report.applicability_label_changes[axis].moved_from_not_applicable + ", to not applicable " + report.applicability_label_changes[axis].moved_to_not_applicable).join("; ");
    result.append(node("p", "Applicability label transitions (including unknown/unscored states): " + applicability + ". These transitions do not establish actual applicability.", "muted small"));
    const outcomeDetails = node("details"), outcomes = report.aggregate.outcome_transitions;
    outcomeDetails.append(node("summary", "All-case outcome transitions"), table(["Baseline → candidate", ...Object.keys(outcomes).map(label)], Object.entries(outcomes).map(([key, values]) => [label(key), ...Object.values(values)]))); result.append(outcomeDetails);
    for (const [dimension, groups] of Object.entries(report.strata)) {
      const details = node("details"); details.append(node("summary", "Stratification: " + label(dimension)));
      for (const [name, group] of Object.entries(groups)) details.append(comparisonBlock(label(name), group)); result.append(details);
    }
    byId("comparison-cases").replaceChildren(table(["Case", "Outcome", "Factual", "Citation", "Refusal decision"], report.case_changes.map(item => [item.case_id, label(item.left_outcome) + " → " + label(item.right_outcome), ...axes.map(axis => label(item.judgments[axis].left) + " → " + label(item.judgments[axis].right) + " (" + label(item.judgments[axis].transition) + ")")])));
    byId("comparison-limits").replaceChildren(...report.limitations.map(text => node("li", text)));
    byId("comparison-panel").hidden = false; byId("comparison-panel").scrollIntoView({block: "start"}); controls();
  }

  for (const element of document.querySelectorAll("[data-axis]")) {
    for (const state of judgments.filter(value => element.dataset.axis !== "refusal_decision" || value !== "not_applicable")) { const option = node("option", label(state)); option.value = state; element.append(option); }
    element.addEventListener("change", () => { const record = clone(currentRecord()); record.judgments[element.dataset.axis] = element.value; setDraft(record); });
  }
  for (const element of document.querySelectorAll("[data-meta]")) element.addEventListener("input", () => {
    const field = element.dataset.meta;
    if (element.value === baseMetadata()[field]) delete metadata[field]; else metadata[field] = element.value;
    changed();
  });
  byId("response").addEventListener("input", () => { const record = clone(currentRecord()); record.response_text = byId("response").value; resetJudgments(record); setDraft(record); });
  byId("prompt").addEventListener("input", () => { const record = clone(currentRecord()); record.prompt_override = byId("prompt").value; resetJudgments(record); setDraft(record); });
  byId("prompt-default").addEventListener("change", () => { const record = clone(currentRecord()); record.prompt_override = byId("prompt-default").checked ? null : byId("prompt").value; resetJudgments(record); setDraft(record); renderEditor(); });
  byId("outcome").addEventListener("change", () => {
    const record = clone(currentRecord()), outcome = byId("outcome").value;
    if (outcome === "missing" && record.response_text && !window.confirm("Set this response to missing and clear its response text and judgments in the draft?")) { byId("outcome").value = record.outcome; return; }
    record.outcome = outcome; if (outcome === "missing") record.response_text = "";
    resetJudgments(record); setDraft(record); renderEditor();
  });
  for (const id of filterIds) byId(id).addEventListener("input", () => { page = 0; renderCases(); });
  byId("reset-filters").addEventListener("click", () => { for (const id of filterIds) byId(id).value = ""; page = 0; renderCases(); });
  byId("page-size").addEventListener("change", () => { pageSize = Number(byId("page-size").value); page = 0; renderCases(); });
  for (const [id, direction] of [["previous-case", -1], ["next-case", 1]]) byId(id).addEventListener("click", () => {
    const filtered = filteredCases(), index = filtered.findIndex(item => item.id === selectedCase) + direction, item = filtered[index];
    if (!item) return; selectedCase = item.id; page = Math.floor(index / pageSize); renderCases(); renderEditor();
  });
  byId("restore-case").addEventListener("click", () => { if (!drafts.has(selectedCase) || !window.confirm("Discard only this case's unsaved edits and restore its last loaded saved state?")) return; drafts.delete(selectedCase); changed(); renderEditor(); });
  byId("previous-page").addEventListener("click", () => { page--; renderCases(); });
  byId("next-page").addEventListener("click", () => { page++; renderCases(); });
  byId("create-run").addEventListener("click", () => act(async () => { const result = await api("/api/create", {run_id: byId("new-run-id").value, model_label: byId("new-model").value}); loadView(result); await refreshRuns(); byId("right-run").value = view.key; message("Created a complete unscored run in memory. No model was called."); }));
  byId("import-run").addEventListener("change", () => act(async () => {
    const file = byId("import-run").files[0]; if (!file) return;
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error("The selected document exceeds the 8 MiB import limit.");
      let text;
      try { text = new TextDecoder("utf-8", {fatal: true, ignoreBOM: true}).decode(await file.arrayBuffer()); } catch (_) { throw new Error("The selected file is not valid UTF-8."); }
      const result = await api("/api/import", {document: text}); loadView(result); await refreshRuns(); byId("right-run").value = view.key; message("Imported and validated the run in memory. Its declared provenance is not independently authenticated.");
    } finally { byId("import-run").value = ""; }
  }));
  byId("run-select").addEventListener("change", () => act(async () => { loadView(await api("/api/select", {key: byId("run-select").value})); }));
  byId("reload-run").addEventListener("click", () => { if (dirty() && !window.confirm("Discard this tab's unsaved draft and load the latest saved revision?")) return; act(async () => {
    const previousKey = view.key; await refreshRuns();
    const key = runs.some(item => item.key === previousKey) ? previousKey : runs[0]?.key;
    if (key) loadView(await api("/api/select", {key})); else clearSelection();
    message("Loaded the current saved state. Other tabs keep their own drafts.");
  }); });
  byId("save-run").addEventListener("click", () => act(async () => { const result = await api("/api/save", draftPayload()); loadView(result); await refreshRuns(); message("Validated changes saved to server memory. Export explicitly to keep a file."); }));
  byId("discard-run").addEventListener("click", () => { if (window.confirm("Discard this tab's unsaved changes?")) { loadView(view); message("Draft discarded; the last loaded saved run is unchanged."); } });
  byId("remove-run").addEventListener("click", () => { if (!window.confirm("Remove this saved run from server memory? Existing downloaded files will remain unchanged.")) return; act(async () => { await api("/api/remove", {key: view.key, revision: view.revision}); clearSelection(); await refreshRuns(); if (runs.length) loadView(await api("/api/select", {key: runs[0].key})); message("Removed the run from session memory."); }); });
  for (const [id, kind, filename] of [["export-run", "run", "evidence-bench-run.json"], ["export-score", "scored", "evidence-bench-scored.json"]]) byId(id).addEventListener("click", () => act(() => download("/api/export", {key: view.key, revision: view.revision, kind}, filename)));
  for (const id of ["left-run", "right-run"]) byId(id).addEventListener("change", clearComparison);
  byId("swap-runs").addEventListener("click", () => { const left = byId("left-run").value; byId("left-run").value = byId("right-run").value; byId("right-run").value = left; clearComparison(); });
  byId("compare-runs").addEventListener("click", () => act(async () => {
    const left = runs.find(item => item.key === byId("left-run").value), right = runs.find(item => item.key === byId("right-run").value);
    const selection = {left_key: left.key, left_revision: left.revision, right_key: right.key, right_revision: right.revision};
    const report = await api("/api/compare", {...selection, mode: "preview"}); comparisonSelection = selection; renderComparison(report);
  }));
  byId("export-comparison").addEventListener("click", () => act(() => download("/api/compare", {...comparisonSelection, mode: "export"}, "evidence-bench-comparison.json")));
  window.addEventListener("beforeunload", event => { if (dirty()) { event.preventDefault(); event.returnValue = ""; } });
  act(async () => {
    const state = await api("/api/bootstrap", {}); cases = state.dataset.cases; runs = state.runs;
    byId("dataset-status").textContent = cases.length + " startup cases · " + cases.filter(item => item.synthetic).length + " synthetic · validation date " + state.dataset.validation_as_of;
    for (const state of [...new Set(cases.map(item => item.review_status))].sort()) { const option = node("option", label(state)); option.value = state; byId("review-filter").append(option); }
    renderRuns(); if (runs.length) loadView(await api("/api/select", {key: runs[0].key}));
    message("Session ready. Supplied data stays in local memory unless you explicitly export it.");
  });
})();
