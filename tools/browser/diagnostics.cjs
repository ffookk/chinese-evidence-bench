"use strict";

const TARGETS = Object.freeze({
  20: ["model-input", "#meta-model"], 21: ["reset-filters", "#reset-filters"],
  22: ["first-case", "#case-list button"], 23: ["parameters-input", "#meta-parameters"],
  24: ["model-input", "#meta-model"],
  90: ["first-case", "#case-list button"], 91: ["first-case", "#case-list button"],
  92: ["response", "#response"], 93: ["response", "#response"],
  94: ["next-case", "#next-case"], 95: ["next-case", "#next-case"],
  96: ["previous-case", "#previous-case"], 97: ["previous-case", "#previous-case"]
});

async function captureState(page, checkpoint) {
  let timer;
  try {
    if (!page || page.isClosed()) return null;
    const target = TARGETS[checkpoint] || ["none", null];
    const capture = page.evaluate(([code, selector]) => {
      const byId = id => document.getElementById(id);
      const buttons = document.querySelectorAll("#case-list button");
      const element = selector ? document.querySelector(selector) : null;
      const rect = element?.getBoundingClientRect();
      const style = element ? getComputedStyle(element) : null;
      const visible = Boolean(rect && rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none");
      const inView = Boolean(visible && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth);
      const hit = inView ? document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2) : null;
      const filters = ["case-search", "answerability-filter", "synthetic-filter", "outcome-filter", "case-sort", "evidence-filter", "review-filter", "judgment-filter", "draft-filter"];
      return {
        target: code,
        case_buttons: Math.min(buttons.length, 63),
        filters_clear: filters.every(id => byId(id)?.value === ""),
        reset_enabled: Boolean(byId("reset-filters") && !byId("reset-filters").disabled),
        first_selected: buttons[0]?.getAttribute("aria-pressed") === "true",
        preview_pending: Boolean(byId("metric-state")?.classList.contains("dirty") && !byId("metrics")?.querySelector(".metric-grid, .notice.error")),
        target_present: Boolean(element),
        target_enabled: Boolean(element && !element.disabled),
        target_visible: visible,
        target_in_view: inView,
        target_hit: Boolean(hit && element.contains(hit))
      };
    }, target);
    return await Promise.race([capture, new Promise(resolve => { timer = setTimeout(() => resolve(null), 1000); })]);
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

module.exports = {captureState};
