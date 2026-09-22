"use strict";
const assert = require("node:assert/strict");
const {chromium, firefox} = require("playwright");
const [origin, engine, scenario] = process.argv.slice(2);
let checkpoint = 0; // Browser startup.

async function ready(page, id = "reload-run") {
  await page.waitForFunction(id => !document.getElementById(id).disabled, id);
}
async function openPage(context) {
  const page = await context.newPage();
  await page.goto(origin);
  await ready(page);
  return page;
}
async function remove(page) {
  page.once("dialog", dialog => dialog.accept());
  await page.locator("#remove-run").click();
}
async function readDownload(page, id) {
  const event = page.waitForEvent("download");
  await page.locator("#" + id).click();
  const download = await event;
  const stream = await download.createReadStream();
  assert(stream);
  const chunks = [];
  let size = 0;
  for await (const chunk of stream) {
    size += chunk.length;
    assert(size <= 1024 * 1024);
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function reviewControls(context) {
  checkpoint = 1; // Initial state and filter reset.
  const page = await context.newPage();
  const checks = [];
  const el=id=>page.locator('#'+id), text=id=>el(id).textContent();
  const count=()=>page.locator('#case-list button').count();
  const first=()=>page.locator('#case-list button strong').first().textContent();
  const choose=async(id,value)=>{await el(id).selectOption(value);};
  const waitReady=()=>el('create-run').waitFor({state:'visible'});
  async function enabled(id) { await page.waitForFunction(id=>!document.getElementById(id).disabled,id); }
  await page.goto(origin); await waitReady(); await enabled('reset-filters');
  assert.equal(await count(),20); assert.equal(await text('page-number'),'1 / 4');
  assert.equal(await text('case-id'),'fictional-001');
  await el('response').fill('Fictional pending note.');
  await el('case-search').fill('fictional-060'); await choose('outcome-filter','missing'); assert.equal(await count(),1);
  await el('reset-filters').click(); assert.equal(await count(),20); assert.equal(await el('response').inputValue(),'Fictional pending note.'); assert.match(await text('save-state'),/Unsaved/);
  checks.push('reset clears all active filters and preserves the case draft');
  checkpoint = 2; // Page sizes.
  await choose('page-size','10'); assert.equal(await count(),10); assert.equal(await text('page-number'),'1 / 7');
  await el('next-page').click(); assert.equal(await text('page-number'),'2 / 7');
  await choose('page-size','50'); assert.equal(await count(),50); assert.equal(await text('page-number'),'1 / 2');
  await choose('page-size','20'); assert.equal(await count(),20); assert.equal(await el('response').inputValue(),'Fictional pending note.');
  checks.push('10/20/50 page sizes and page reset preserve drafts');
  checkpoint = 3; // Case ordering.
  await choose('case-sort','descending'); assert.equal(await first(),'fictional-063');
  await choose('case-sort','question'); assert.equal(await first(),'fictional-055');
  await el('reset-filters').click(); assert.match(await first(),/^fictional-001/);
  checks.push('distinct descending ID and question sorts reset to ascending ID');
  checkpoint = 4; // Evidence filter.
  await choose('evidence-filter','present'); assert.match(await text('case-count'),/^42 of 63/);
  await choose('evidence-filter','absent'); assert.match(await text('case-count'),/^21 of 63/);
  const absentIDs=await page.locator('#case-list button strong').allTextContents(); assert(absentIDs.every(id=>Number(id.match(/\d+/)[0])%3===0));
  await el('reset-filters').click(); checks.push('evidence presence and absence filters match recorded entries');
  checkpoint = 5; // Review status filter.
  await choose('review-filter','pending'); assert.match(await text('case-count'),/^21 of 63/);
  await choose('review-filter','reviewed'); assert.match(await text('case-count'),/^42 of 63/);
  await el('reset-filters').click(); checks.push('dataset-derived review status options filter exact supplied labels');
  checkpoint = 6; // Judgment filter.
  await choose('judgment-filter','incorrect'); assert.equal(await count(),1); assert.equal(await first(),'fictional-002');
  await page.locator('#case-list button').first().click(); await choose('judge-refusal','correct');
  assert.equal(await count(),1); await choose('judgment-filter','complete'); assert.equal(await count(),1); // Case 1 was reset to unscored by text edit.
  await choose('judgment-filter','unscored'); assert.match(await text('case-count'),/^62 of 63/);
  await el('reset-filters').click(); checks.push('judgment filters reflect current unsaved labels including unscored state');
  checkpoint = 7; // Draft filter.
  await page.locator('.metadata summary').click(); await el('meta-model').fill('Fictional changed declaration');
  await choose('draft-filter','changed'); assert.equal(await count(),2);
  await choose('draft-filter','unchanged'); assert.match(await text('case-count'),/^61 of 63/);
  await el('reset-filters').click(); checks.push('draft filter counts case edits independently of metadata edits');
  checkpoint = 8; // Matching case navigation.
  await choose('page-size','10'); await page.locator('#case-list button').nth(9).click();
  assert.equal(await text('case-id'),'fictional-010'); await el('next-case').click();
  assert.equal(await text('case-id'),'fictional-011'); assert.equal(await text('page-number'),'2 / 7'); assert.equal(await text('case-position'),'Match 11 of 63');
  await el('previous-case').click(); assert.equal(await text('case-id'),'fictional-010'); assert.equal(await text('page-number'),'1 / 7');
  await el('case-search').fill('fictional-030'); assert.match(await text('case-position'),/outside/); assert.equal(await el('previous-case').isDisabled(),true);
  await el('next-case').click(); assert.equal(await text('case-id'),'fictional-030'); assert.equal(await el('next-case').isDisabled(),true);
  await el('case-search').fill('no-fictional-case'); assert.equal(await el('previous-case').isDisabled(),true); assert.equal(await el('next-case').isDisabled(),true);
  await el('reset-filters').click(); checks.push('matching-case navigation crosses pages, handles filtered-out selection and empty results');
  checkpoint = 9; // Unicode response count.
  await page.locator('#case-list button').first().click(); await el('response').fill('A' + String.fromCodePoint(0x1F642) + '\n');
  assert.equal(await text('response-count'),'Response characters: 3 (Unicode code points).'); assert.equal(await el('response').inputValue(),'A' + String.fromCodePoint(0x1F642) + '\n');
  await el('next-case').click(); assert.equal(await text('response-count'),'Response characters: 23 (Unicode code points).');
  await el('previous-case').click(); assert.equal(await text('response-count'),'Response characters: 3 (Unicode code points).');
  checks.push('live response counter counts Unicode code points and updates across cases');
  checkpoint = 10; // Selected case restoration.
  page.once('dialog',d=>d.dismiss()); await el('restore-case').click(); assert.equal(await el('response').inputValue(),'A' + String.fromCodePoint(0x1F642) + '\n');
  page.once('dialog',d=>d.accept()); await el('restore-case').click(); assert.equal(await el('response').inputValue(),'Fictional first answer.');
  assert.equal(await el('meta-model').inputValue(),'Fictional changed declaration');
  await choose('draft-filter','changed'); assert.equal(await count(),1); assert.match(await first(),/^fictional-002/);
  assert.equal(await el('restore-case').isDisabled(),true); assert.match(await text('save-state'),/Unsaved/);
  await el('reset-filters').click(); checks.push('selected-case restore supports cancellation and preserves other case and metadata drafts');
  checkpoint = 11; // Save and comparison controls.
  assert.equal(await el('swap-runs').isDisabled(),true); await el('save-run').click(); await enabled('swap-runs');
  const left=await el('left-run').inputValue(),right=await el('right-run').inputValue(); assert.notEqual(left,right);
  await el('compare-runs').click(); await enabled('swap-runs'); assert.equal(await el('comparison-panel').isVisible(),true);
  const before=await text('comparison-label'); await el('swap-runs').click();
  assert.equal(await el('left-run').inputValue(),right); assert.equal(await el('right-run').inputValue(),left); assert.equal(await el('comparison-panel').isVisible(),false);
  assert.equal(await el('export-comparison').isDisabled(),true); await el('compare-runs').click(); await enabled('swap-runs');
  assert.equal(await el('comparison-panel').isVisible(),true); assert.notEqual(await text('comparison-label'),before);
  checks.push('swap reverses comparison selectors, clears stale report and recalculates explicitly');
  assert.equal(checks.length, 11);
  checkpoint = 12; // Authoritative scored export and import.
  const scored = await readDownload(page, "export-score");
  const textValue = scored.toString("utf8");
  assert.match(textValue, /"large_integer": 9007199254740993/);
  assert.match(textValue, /"whole_float": 1\.0/);
  const document = JSON.parse(textValue);
  assert.equal(document.artifact_type, "scored_run");
  assert.equal(document.run.run_id, "fictional-a");
  assert.equal(document.metrics.sample_size, 63);
  await ready(page, "import-run");
  await page.locator("#import-run").setInputFiles({name:"fictional-scored.json", mimeType:"application/json", buffer:scored});
  await page.waitForFunction(() => document.getElementById("message").textContent.includes("Imported and validated"));
  await ready(page);
  assert.match(await page.locator("#run-count").textContent(), /^3 \/ 8/);
  assert.equal(await page.locator("#meta-model").inputValue(), "Fictional changed declaration");
  checkpoint = 13; // Responsive layout and browser storage.
  await page.setViewportSize({width:390, height:844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(await page.evaluate(() => ({local:localStorage.length, session:sessionStorage.length, cookies:document.cookie})), {local:0, session:0, cookies:""});
}

async function deletedRun(context) {
  checkpoint = 14; // Reload after another tab removes the selected run.
  const first = await openPage(context), second = await openPage(context);
  await remove(second);
  await second.waitForFunction(() => document.getElementById("run-title").textContent === "fictional-b");
  await ready(second);
  await first.locator("#reload-run").click();
  await first.waitForFunction(() => document.getElementById("run-title").textContent === "fictional-b");
  await ready(first);
  assert.equal(await first.locator("#run-select").inputValue(), "run-2");
  assert.equal(await first.locator("#run-workspace").isVisible(), true);
  const exported = JSON.parse((await readDownload(first, "export-run")).toString("utf8"));
  assert.equal(exported.run_id, "fictional-b");
  checkpoint = 15; // Recovery after the final run is removed.
  await remove(second);
  await second.waitForFunction(() => document.getElementById("run-workspace").hidden);
  await ready(first);
  await first.locator("#reload-run").click();
  await first.waitForFunction(() => document.getElementById("run-workspace").hidden);
  assert.equal(await first.locator("#export-run").isDisabled(), true);
}

async function failedSelection(context) {
  checkpoint = 16; // Failed selection keeps the displayed run identity.
  const first = await openPage(context), second = await openPage(context);
  await second.locator("#run-select").selectOption("run-2");
  await second.waitForFunction(() => document.getElementById("run-title").textContent === "fictional-b");
  await ready(second);
  await remove(second);
  await second.waitForFunction(() => document.getElementById("run-title").textContent === "fictional-a");
  await ready(second);
  await first.locator("#run-select").selectOption("run-2");
  await first.waitForFunction(() => document.getElementById("message").textContent.includes("unavailable"));
  await ready(first);
  assert.equal(await first.locator("#run-select").inputValue(), "run-1");
  assert.equal(await first.locator("#run-title").textContent(), "fictional-a");
  assert.equal(JSON.parse((await readDownload(first, "export-run")).toString("utf8")).run_id, "fictional-a");
}

async function reloadFailure(context) {
  checkpoint = 17; // Interrupted reload preserves the unsaved draft.
  const first = await openPage(context), second = await openPage(context);
  await first.locator("details.metadata > summary").click();
  await first.locator("#meta-model").fill("Fictional unsaved model");
  await remove(second);
  await second.waitForFunction(() => document.getElementById("run-title").textContent === "fictional-b");
  await ready(second);
  await first.route("**/api/select", route => route.fulfill({status:503, contentType:"application/json", body:JSON.stringify({error:"Fictional interrupted selection."})}));
  first.once("dialog", dialog => dialog.accept());
  await first.locator("#reload-run").click();
  await first.waitForFunction(() => document.getElementById("message").textContent.includes("Fictional interrupted selection."));
  await ready(first);
  assert.equal(await first.locator("#run-select").inputValue(), "run-1");
  assert.equal(await first.locator("#run-title").textContent(), "fictional-a");
  assert.equal(await first.locator("#meta-model").inputValue(), "Fictional unsaved model");
  assert.equal(await first.locator("#save-run").isDisabled(), false);
  assert.equal(await first.locator("#export-run").isDisabled(), true);
  checkpoint = 18; // Retry after interrupted reload.
  await first.unroute("**/api/select");
  first.once("dialog", dialog => dialog.accept());
  await first.locator("#reload-run").click();
  await first.waitForFunction(() => document.getElementById("run-title").textContent === "fictional-b");
  await ready(first);
  assert.equal(await first.locator("#run-select").inputValue(), "run-2");
  assert.equal(await first.locator("#meta-model").inputValue(), "fictional-test-model");
}

async function main() {
  assert.match(origin, /^http:\/\/127\.0\.0\.1:[0-9]+$/);
  assert(engine === "chromium" || engine === "firefox");
  assert(["review-controls", "deleted-run", "failed-selection", "reload-failure"].includes(scenario));
  let browser, context;
  const errors = [], external = [];
  try {
    browser = engine === "chromium" ? await chromium.launch({headless:true}) : await firefox.launch({headless:true});
    context = await browser.newContext({viewport:{width:1440, height:1050}, acceptDownloads:true, serviceWorkers:"block"});
    context.setDefaultTimeout(10000);
    context.on("page", page => page.on("pageerror", () => errors.push(true)));
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin !== origin) { external.push(true); return route.abort(); }
      return route.continue();
    });
    await context.routeWebSocket("**/*", socket => { external.push(true); socket.close(); });
    if (scenario === "review-controls") await reviewControls(context);
    else if (scenario === "deleted-run") await deletedRun(context);
    else if (scenario === "failed-selection") await failedSelection(context);
    else await reloadFailure(context);
    checkpoint = 19; // External requests and page errors.
    assert.equal(external.length, 0);
    assert.equal(errors.length, 0);
    console.log(JSON.stringify({browser:engine, scenario, passed:true, external_requests:0, page_errors:0}));
  } finally {
    if (context) await context.close();
    if (browser) await browser.close();
  }
}
main().catch(error => {
  const errorKind = error?.name === "AssertionError" ? "assertion" : error?.name === "TimeoutError" ? "timeout" : "other";
  console.log(JSON.stringify({browser:engine, scenario, passed:false, checkpoint, error_kind:errorKind}));
  process.exitCode = 1;
});
