"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
};
const fmtPct = (x, d = 0) => (x * 100 < 10 && d === 0 ? (x * 100).toFixed(1) : (x * 100).toFixed(d)) + "%";
const fmtSigned = x => Math.abs(x) < 0.005 ? "0.00" : (x > 0 ? "+" : "−") + Math.abs(x).toFixed(2);
const dayLabel = hr => `Day ${(hr / 24).toFixed(1)}`;
const C = { for: "#6ef2c0", against: "#ff6fb5", mixed: "#b9a6d9", none: "#4a2c57", accent: "#ffd23f", text: "#fff4d6",
  muted: "#d3bfdf", faint: "#a089b0", line: "#3d2049", spread: "#ffd23f", ink: "#0b0410", stage: "#170820" };
const STORY_COLORS = ["#ffd23f", "#8db7ff", "#ff6fb5", "#6ef2c0", "#ff8a3d", "#c9a2ff", "#7fe7ff", "#f4ff7a", "#ffb3d9", "#a8ffcf", "#ffc78a"];
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const S = { images: [], spec: null, archetypes: {}, fullPlan: [], disabled: new Set(), hours: {}, result: null, preview: null };

// ------------------------------------------------------------------ boot
fetch("/api/health").then(r => r.json()).then(j => {
  const el = $("#modelStatus");
  if (j.model) el.textContent = `Reading with ${j.model} · ${j.events_in_memory} past events`;
  else { el.textContent = "No AI model set: using the keyword reader"; el.classList.add("warn"); }
  $("#agents").max = j.max_agents;
  S.optionAgents = j.option_agents;
  eta();
}).catch(() => { $("#modelStatus").textContent = "Server not reachable"; });

$$(".tab").forEach(b => b.addEventListener("click", () => {
  $$(".tab").forEach(x => x.classList.toggle("is-on", x === b));
  $$(".view").forEach(v => v.hidden = v.id !== b.dataset.view);
  if (b.dataset.view === "memory") loadMemory();
}));

// ------------------------------------------------------------------ images
const drop = $("#drop"), files = $("#files");
drop.addEventListener("click", e => { if (e.target.tagName !== "BUTTON") files.click(); });
drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); files.click(); } });
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => addFiles(e.dataTransfer.files));
files.addEventListener("change", () => { addFiles(files.files); files.value = ""; });
document.addEventListener("paste", e => { const f = [...(e.clipboardData?.files || [])]; if (f.length) addFiles(f); });
function addFiles(list) {
  for (const f of list) {
    if (!f.type.startsWith("image/")) continue;
    if (S.images.length >= 4) { showErr("#readErr", "Four images is the limit. Remove one to add another."); break; }
    S.images.push(f);
  }
  renderThumbs();
}
function renderThumbs() {
  const t = $("#thumbs"); t.replaceChildren();
  S.images.forEach((f, i) => {
    const url = URL.createObjectURL(f);
    t.append(h("figure", {}, h("img", { src: url, alt: f.name }),
      h("button", { type: "button", "aria-label": `Remove ${f.name}`, onclick: () => { S.images.splice(i, 1); renderThumbs(); } }, "×")));
  });
}

// ------------------------------------------------------------------ step 1: read
const EXAMPLES = {
  launch: ["Brewly is launching the Brewly One, an $899 countertop espresso machine that grinds, tamps and learns each person's taste. It ships in three weeks. A few beta units had leaking seals, which we've fixed. Our main rival sells a similar machine for $650.", "Premium kitchen appliance, US and UK, buyers mostly 28-45"],
  policy: ["From 1 January the state will make helmets compulsory for pillion riders on two-wheelers, with a ₹2,000 fine and a three-month licence suspension. The first 50,000 low-income riders get a free helmet.", "Uttar Pradesh, India. Most families travel two or three to a scooter; state elections next year"],
  crisis: ["A video shows a delivery rider for QuickCart being slapped by a customer over a late order; QuickCart's support account replied 'we'll look into it' and then nothing for a day. #BoycottQuickCart is trending.", "Indian quick-commerce app, urban customers 20-40"],
};
$$("[data-example]").forEach(b => b.addEventListener("click", () => {
  const [t, c] = EXAMPLES[b.dataset.example]; $("#text").value = t; $("#context").value = c; $("#text").focus();
}));
$("#readBtn").addEventListener("click", async () => {
  const text = $("#text").value.trim();
  if (!text && !S.images.length) return showErr("#readErr", "Describe what happened, or add an image of it.");
  hideErr("#readErr");
  const btn = $("#readBtn"); btn.disabled = true; btn.textContent = S.images.length ? "Looking at the images…" : "Reading…";
  const fd = new FormData();
  fd.append("text", text); fd.append("context", $("#context").value);
  S.images.forEach(f => fd.append("images", f));
  try {
    const r = await fetch("/api/read", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "The reader failed.");
    S.spec = j.spec; S.archetypes = j.archetypes; S.disabled = new Set(); S.hours = {};
    renderSpec();
    $("#stepSpec").hidden = false;
    $("#stepSpec").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" });
  } catch (e) { showErr("#readErr", e.message); }
  finally { btn.disabled = false; btn.textContent = "Read it"; }
});
function showErr(sel, msg) { const el = $(sel); el.textContent = msg; el.hidden = false; }
function hideErr(sel) { $(sel).hidden = true; }

// ------------------------------------------------------------------ step 2: spec
const DIALS = [
  ["valence", "How it reflects on them", -1, 1, "badly", "well"],
  ["emotionality", "Emotional charge", 0, 1, "flat", "explosive"],
  ["credibility", "How believable it is", 0, 1, "doubtful", "certain"],
  ["identity", "Touches politics or identity", 0, 1, "not at all", "entirely"],
  ["lean", "Which side it flatters", -1, 1, "progressive", "traditional"],
  ["harm", "Harm or cost to people", 0, 1, "none", "severe"],
  ["responsibility", "Blame on them", 0, 1, "none", "all of it"],
  ["hype", "Anticipation beforehand", 0, 1, "none", "huge"],
  ["price", "How much it's about money", 0, 1, "not at all", "entirely"],
  ["prominence", "How well known they are", 0, 1, "unknown", "household name"],
  ["novelty", "How surprising it is", 0, 1, "expected", "shocking"],
];
const EXTRA = [["quality", "How good it really is, once tried", -1, 1, "poor", "excellent"],
               ["substitutes", "How easy it is to switch away", 0, 1, "hard", "trivial"]];

function renderSpec() {
  const s = S.spec;
  $("#sTitle").value = s.title; $("#sBrand").value = s.brand; $("#sSummary").value = s.summary;
  const sel = $("#sArche"); sel.replaceChildren(...Object.entries(S.archetypes).map(([k, v]) => h("option", { value: k, selected: k === s.archetype }, v)));
  const note = $("#readerNote");
  note.hidden = !s.reader_note; note.textContent = s.reader_note || "";
  const obs = $("#obs");
  const lines = [...(s.image_observations || []).map(x => ["In the images", x]), ...(s.strengths || []).map(x => ["Working for you", x]), ...(s.risks || []).map(x => ["Risk", x])];
  obs.hidden = !lines.length;
  obs.replaceChildren(...lines.map(([k, v]) => h("p", {}, h("b", {}, k + ": "), v)));
  const dials = $("#dials"); dials.replaceChildren();
  for (const [key, label, lo, hi, a, b] of [...DIALS, ...EXTRA]) {
    const isFeat = DIALS.some(d => d[0] === key);
    const val = isFeat ? s.features[key] : s[key];
    const out = h("output", {}, (+val).toFixed(2));
    const inp = h("input", { type: "range", min: lo, max: hi, step: 0.05, value: val, "aria-label": label });
    inp.addEventListener("input", () => {
      out.textContent = (+inp.value).toFixed(2);
      if (isFeat) s.features[key] = +inp.value; else s[key] = +inp.value;
      schedulePreview();
    });
    dials.append(h("label", { class: "dial" }, h("span", {}, label), out, inp, h("small", {}, h("span", {}, a), h("span", {}, b))));
  }
  renderAudience();
  schedulePreview(0);
}
[["#sTitle", "title"], ["#sBrand", "brand"], ["#sSummary", "summary"]].forEach(([id, key]) => $(id).addEventListener("input", e => { if (S.spec) S.spec[key] = e.target.value; }));
$("#sArche").addEventListener("change", e => { S.spec.archetype = e.target.value; S.spec.audience = []; renderAudience(); schedulePreview(0); });

function renderAudience() {
  const tb = $("#audTable tbody"); tb.replaceChildren();
  const aud = S.spec.audience;
  if (!aud.length) {
    tb.append(h("tr", {}, h("td", { colspan: 6, class: "hint" }, "Using the typical audience for this kind of event (shown in the summary on the right). Add a group to define your own.")));
    return;
  }
  aud.forEach((g, i) => {
    const num = (key, min, max, step) => {
      const inp = h("input", { type: "number", min, max, step, value: g[key] });
      inp.addEventListener("change", () => { g[key] = +inp.value; schedulePreview(); });
      return inp;
    };
    const name = h("input", { value: g.name, "aria-label": "Group name" });
    name.addEventListener("change", () => { g.name = name.value || "group"; schedulePreview(); });
    const buy = h("input", { type: "checkbox", checked: g.can_adopt, "aria-label": "Could take it up" });
    buy.addEventListener("change", () => { g.can_adopt = buy.checked; schedulePreview(); });
    tb.append(h("tr", {}, h("td", {}, name), h("td", {}, num("share", 0.005, 1, 0.01)), h("td", {}, num("baseline_opinion", -1, 1, 0.05)),
      h("td", { class: "c" }, buy), h("td", {}, num("already_customer", 0, 1, 0.05)),
      h("td", {}, h("button", { type: "button", "aria-label": `Remove ${g.name}`, onclick: () => { aud.splice(i, 1); renderAudience(); schedulePreview(); } }, "×"))));
  });
}
$("#addGroup").addEventListener("click", () => {
  if (!S.spec) return;
  if (!S.spec.audience.length && S.preview) {
    S.spec.audience = S.preview.segments.map(g => ({ name: g.name, share: +g.share.toFixed(3), baseline_opinion: g.baseline_opinion, can_adopt: g.can_adopt,
      already_customer: g.already_adopted || 0, need: g.need ?? 0.5, price_sensitivity: g.price_sensitivity ?? 0.5, ideology: g.ideology || 0, note: g.note || "" }));
  }
  S.spec.audience.push({ name: "new group", share: 0.1, baseline_opinion: 0, can_adopt: false, already_customer: 0, need: 0.5, price_sensitivity: 0.5, ideology: 0, note: "" });
  renderAudience(); schedulePreview();
});

function settings() {
  return {
    agents: +$("#agents").value, days: +$("#days").value, runs: +$("#runs").value,
    response: { type: $("#respType").value, hour: +$("#respHour").value },
    economy: $("#economy").value, news_load: $("#newsLoad").value, polarization: $("#polar").value, season: $("#season").value,
    competing_event: { on: $("#compete").checked, hour: +$("#competeHour").value }, global: $("#global").checked,
    disabled_stories: [...S.disabled], story_hours: S.hours, test_options: $("#testOpts").checked,
  };
}
$$("#stepSpec aside select, #stepSpec aside input").forEach(el => el.addEventListener("change", () => schedulePreview()));
$("#agents").addEventListener("input", () => { $("#agentsOut").textContent = (+$("#agents").value).toLocaleString(); eta(); });
["#days", "#runs", "#testOpts"].forEach(id => $(id).addEventListener("input", eta));
function eta() {
  const n = +$("#agents").value / 1e6, d = +$("#days").value, r = +$("#runs").value;
  let sec = n * 0.4 * d * 24 * r + 5 * n;
  if ($("#testOpts").checked) sec += 6 * ((S.optionAgents || 25000) / 1e6) * 0.4 * Math.min(d, 7) * 24 + 4;
  $("#eta").textContent = `About ${sec < 90 ? Math.ceil(sec / 5) * 5 + " seconds" : Math.ceil(sec / 60) + " minutes"} on a fast machine; small servers take a few times longer. The network starts moving within seconds.`;
}

let previewTimer;
function schedulePreview(ms = 400) { clearTimeout(previewTimer); previewTimer = setTimeout(preview, ms); }
async function preview() {
  if (!S.spec) return;
  const st = settings(); st.disabled_stories = []; st.story_hours = {};
  try {
    const r = await fetch("/api/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: S.spec, settings: st }) });
    const j = await r.json(); if (!r.ok) throw new Error(j.detail);
    S.preview = j; S.fullPlan = j.plan;
    renderStories(); renderHistorySide(j);
  } catch (e) { console.error(e); }
}
function originTag(o) {
  if (o === "history") return h("span", { class: "tagp hist", title: "Typical for this kind of event, from past cases" }, "from history");
  if (o === "your plan") return h("span", { class: "tagp you" }, "your move");
  if (o === "model") return h("span", { class: "tagp" }, "predicted");
  return h("span", { class: "tagp" }, "your input");
}
function renderStories() {
  const ol = $("#storyList"); ol.replaceChildren();
  for (const p of S.fullPlan) {
    const fixed = p.id === "the_event" || p.id === "your_response";
    const off = S.disabled.has(p.id);
    const cb = h("input", { type: "checkbox", checked: !off, disabled: fixed, "aria-label": `Include ${p.label}` });
    const li = h("li", { class: off ? "off" : "" });
    cb.addEventListener("change", () => { cb.checked ? S.disabled.delete(p.id) : S.disabled.add(p.id); li.classList.toggle("off", !cb.checked); });
    const hr = h("input", { type: "number", min: 0, max: 720, value: S.hours[p.id] ?? p.start, disabled: fixed, "aria-label": `Start hour for ${p.label}` });
    hr.addEventListener("change", () => { S.hours[p.id] = +hr.value; });
    li.append(cb, h("span", {}, h("span", { class: "s-label" }, p.label), originTag(p.origin), p.truth === false ? h("span", { class: "tagp false" }, "false") : null),
      h("span", { class: "s-hour" }, "hour", hr), p.description ? h("p", { class: "s-desc" }, p.description) : null);
    ol.append(li);
  }
}
function renderHistorySide(j) {
  const el = $("#history"); el.replaceChildren();
  el.append(h("h4", {}, `Read as: ${j.archetype_label}`));
  if (!S.spec.audience.length) el.append(h("p", { class: "hint" }, "Audience: " + j.segments.map(g => `${g.name} (${Math.round(g.share * 100)}%)`).join(", ") + "."));
  const pr = j.priors;
  el.append(h("p", { class: "hint" }, `Similar past events held attention for about ${pr.halflife_days.toFixed(0)} days, moved opinion by ${fmtSigned(pr.opinion_shift)} and moved outcomes by ${fmtSigned(pr.commercial)} on a −1 to +1 scale.`));
  el.append(h("h4", {}, "Closest past events"));
  j.analogs.slice(0, 4).forEach(a => el.append(h("div", { class: "mini-analog" },
    h("b", {}, `${a.name}, ${a.year}`), h("span", { class: "sim-bar", style: `width:${Math.round(a.similarity * 80)}px` }), `${Math.round(a.similarity * 100)}% similar`)));
  if (j.patterns.length) {
    el.append(h("h4", {}, "Patterns that apply"));
    j.patterns.forEach(p => el.append(h("p", { class: "hint" }, h("b", {}, p.title + ". "), p.text)));
  }
}

// ------------------------------------------------------------------ run + live polling
$("#runBtn").addEventListener("click", run);
$("#againBtn").addEventListener("click", () => $("#stepSpec").scrollIntoView({ behavior: "smooth" }));
async function run() {
  const btn = $("#runBtn"); btn.disabled = true;
  $("#stepResult").hidden = true;
  $("#stepRun").hidden = false; $("#bar").style.width = "2%"; $("#runMsg").textContent = "Sending to the simulator";
  Net.reset(); $("#netHome").replaceChildren();
  $("#stepRun").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const r = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: S.spec, settings: settings() }) });
    const j = await r.json(); if (!r.ok) throw new Error(j.detail || "Could not start the simulation.");
    await poll(j.job);
  } catch (e) { $("#runMsg").textContent = e.message; }
  finally { btn.disabled = false; }
}
async function poll(id) {
  let got = 0;
  for (;;) {
    const r = await fetch(`/api/jobs/${id}?since=${got}`); const j = await r.json();
    if (!r.ok) throw new Error(j.detail);
    if (j.graph && !Net.g) { Net.init(j.graph, $("#netHome")); Net.setLive(true); }
    if (j.lines) Net.lines = j.lines;
    if (j.frames?.length) { Net.addFrames(j.frames); got += j.frames.length; }
    $("#bar").style.width = `${Math.max(2, j.progress * 100)}%`;
    $("#runMsg").textContent = j.status === "queued" && j.queue_position > 1 ? `Waiting in line (position ${j.queue_position})` : j.message;
    if (j.status === "error") throw new Error(`${j.message}: ${j.error}`);
    if (j.status === "done" && j.result) { S.result = j.result; renderResult(); return; }
    if (got < (j.frames_total || 0)) continue;
    await new Promise(res => setTimeout(res, 700));
  }
}

// ------------------------------------------------------------------ results
const CALL = {
  go: ["Go", "go"], go_with_changes: ["Go, with a change", "change"], change_first: ["Change it first", "change"],
  dont: ["Don't go ahead", "stop"], change: ["Change your response", "change"],
};
function renderResult() {
  const R = S.result, W = R.words || {};
  $("#stepRun").hidden = true; $("#stepResult").hidden = false;
  const d = R.decision, P = R.plain;
  const [label, cls] = CALL[d.call] || ["Result", "change"];
  $("#decisionCall").replaceChildren(h("span", { class: `pill ${cls}` }, label), `Confidence: ${d.confidence}`);
  $("#decisionHead").textContent = d.headline;
  $("#bottomLine").textContent = P.bottom_line;
  $("#reasons").replaceChildren(...d.reasons.map(x => h("li", {}, x)));
  if (R.network) { if (!Net.g) Net.init(R.network.graph, $("#netSlot")); Net.lines = R.network.lines || Net.lines; Net.finish(R.network.frames, $("#netSlot")); }
  renderPeople(R); renderActions(R); renderOptions(R); renderProgram(R);
  renderKpis(R); renderTimeline(R); renderVsHistory(R); renderCharts(R); renderSegments(R); renderVoices(R); renderAnalogs(R);
  $("#meta").textContent = `${R.meta.agents.toLocaleString()} people, ${R.meta.ties.toLocaleString()} social ties, ${Math.round(R.meta.hours / 24)} days, ${R.meta.runs} run${R.meta.runs > 1 ? "s" : ""}, ${R.meta.seconds}s. Read as: ${R.meta.archetype}. Plain-language text written by ${P.written_by === "model" ? "the AI model from the simulation's numbers" : "templates from the simulation's numbers"}.`;
  $("#stepResult").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" });
}

function renderPeople(R) {
  const P = R.people, o = P.overall;
  $("#peopleLede").textContent = `Among everyone who heard about it: ${fmtPct(o.for)} ended up for it, ${fmtPct(o.against)} against, the rest undecided. ${fmtPct(o.heard)} of people heard about it at all.`;
  const segShare = Object.fromEntries(R.segments.map(s => [s.name, s.share]));
  $("#groups").replaceChildren(...P.groups.map(g => {
    const heard = g.heard, f = g.for * heard, a = g.against * heard, m = Math.max(0, heard - f - a);
    return h("div", { class: "group" },
      h("div", {}, h("h4", {}, cap(g.name)), h("span", { class: "gshare" }, `${fmtPct(segShare[g.name] || 0)} of the population`)),
      h("div", {},
        h("div", { class: "stack", role: "img", "aria-label": `${fmtPct(f)} for, ${fmtPct(m)} undecided, ${fmtPct(a)} against, ${fmtPct(1 - heard)} never heard` },
          h("i", { class: "s-for", style: `width:${f * 100}%` }), h("i", { class: "s-mixed", style: `width:${m * 100}%` }), h("i", { class: "s-against", style: `width:${a * 100}%` })),
        h("div", { class: "stack-key" }, h("span", { class: "k-for" }, h("b", {}, fmtPct(g.for)), " of those who heard are for it"),
          h("span", { class: "k-against" }, h("b", {}, fmtPct(g.against)), " against"), h("span", {}, `${fmtPct(1 - heard)} never heard`)),
        h("p", {}, g.sentence)));
  }));
}
function renderActions(R) {
  const a = R.actions, W = R.words || {};
  const per = x => { const v = x * 100; return v >= 1 ? v.toFixed(0) : v >= 0.1 ? v.toFixed(1) : v > 0 ? "<0.1" : "0"; };
  const tiles = [[per(a.heard), "in 100 heard about it"], [per(a.talked), "in 100 said something online"],
    [per(a.won_over), "in 100 were won over", "pos"], [per(a.turned_against), "in 100 turned against", "neg"]];
  if (a.spread_hostile > 0.0005) tiles.push([per(a.spread_hostile), "in 100 spread something hostile or false", "neg"]);
  if (a.believed_false > 0.0005) tiles.push([per(a.believed_false), "in 100 believed a false claim", "neg"]);
  if (a.bought > 0.0005) tiles.push([per(a.bought), `in 100 ${W.adopt || "took it up"}`, "pos"]);
  if (a.left > 0.0005) tiles.push([per(a.left), `in 100 ${W.churn || "walked away"}`, "neg"]);
  $("#actionTiles").replaceChildren(...tiles.map(([v, k, c]) => h("div", { class: "tile" }, h("div", { class: `v ${c || ""}` }, v), h("div", { class: "k" }, k))));
  $("#whoDid").textContent = R.plain.who_did_what;
}
function renderOptions(R) {
  const T = R.options;
  $("#optionsBlock").hidden = !T;
  if (!T) return;
  const o = T.options, plan = o[0];
  $("#optionsLede").textContent = `Each alternative was run through the same simulated society (${T.agents.toLocaleString()} people, ${T.days} days, same random seed), so the only difference is the plan. Bars show the change in feeling toward them and the share who ${(R.words || {}).churn || "walked away"}. The number on the right is the overall outcome score against your plan, in points (feeling, take-up and losses combined; above about +2 is a real difference).`;
  const maxO = Math.max(0.05, ...o.map(x => Math.abs(x.opinion_change)));
  const maxC = Math.max(0.01, ...o.map(x => x.churn));
  $("#options").replaceChildren(...[...o].sort((a, b) => (a.id === "plan" ? -1 : b.id === "plan" ? 1 : b.score - a.score)).map(x => {
    const w = Math.abs(x.opinion_change) / maxO * 50;
    const col = x.opinion_change >= 0 ? C.for : C.against;
    const dv = x.vs_plan;
    return h("div", { class: `opt ${x.best ? "best" : ""}` },
      h("div", {}, h("h4", {}, x.label, x.best ? h("span", { class: "best-tag" }, "best of those tested") : null), h("p", {}, x.why)),
      h("div", { class: "bars" },
        h("div", { class: "bar-row" }, h("span", {}, "feeling"), h("span", { class: "track" }, h("span", { class: "mid" }),
          h("i", { style: `background:${col};width:${w}%;${x.opinion_change >= 0 ? "left:50%" : `left:${50 - w}%`}` })), h("span", {}, fmtSigned(x.opinion_change))),
        h("div", { class: "bar-row" }, h("span", {}, "lost"), h("span", { class: "track" }, h("i", { style: `background:${C.against};left:0;width:${x.churn / maxC * 100}%` })), h("span", {}, fmtPct(x.churn, 1)))),
      x.id === "plan" ? h("div", { class: "delta" }, "baseline") :
        h("div", { class: `delta ${dv > 0.005 ? "pos" : dv < -0.005 ? "neg" : ""}` }, (dv >= 0 ? "+" : "−") + Math.abs(dv * 100).toFixed(1), h("small", {}, "points vs your plan")));
  }));
}
function renderProgram(R) {
  const P = R.plain, mode = (R.words || {}).mode;
  $("#programHead").textContent = mode === "respond" ? "How to respond, step by step" : "The plan to follow";
  $("#program").replaceChildren(...P.program.map(s => h("li", {}, h("span", { class: "when" }, s.when), h("span", { class: "what" }, s.what))));
  $("#toChange").replaceChildren(...P.what_to_change.map(x => h("li", {}, x)));
  $("#watchFor").replaceChildren(...P.watch_for.map(x => h("li", {}, x)));
}
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;

function renderKpis(R) {
  const k = R.kpis, per = 1e6 / R.meta.agents, W = R.words || {};
  const items = [
    [fmtPct(k.reach), "heard about it", ""],
    [Math.round(k.peak_posts * per).toLocaleString(), "posts an hour at the peak, per million people", `on ${dayLabel(k.peak_posts_hour).toLowerCase()}`],
    [fmtSigned(k.opinion_change), "change in attitude (−1 to +1)", `from ${fmtSigned(k.opinion_start)}`, k.opinion_change < 0 ? "neg" : "pos"],
    [fmtPct(k.negative_peak), "felt negative at the worst moment", `${fmtPct(k.negative_start)} before`, "neg"],
    [fmtPct(k.adoption, 1), `of ${W.adopters || "potential buyers"} ${W.adopt || "bought"}`, `range ${fmtPct(k.adoption_lo, 1)}–${fmtPct(k.adoption_hi, 1)}`, "pos"],
    [fmtPct(k.churn, 1), `of ${W.customers || "customers"} ${W.churn || "left"}`, `range ${fmtPct(k.churn_lo, 1)}–${fmtPct(k.churn_hi, 1)}`, "neg"],
  ];
  if (k.incidents) items.push([Math.round(k.incidents * per).toLocaleString(), "incident posts, per million people", ""]);
  $("#kpis").replaceChildren(...items.map(([v, label, r, cls]) => h("div", { class: "kpi" }, h("div", { class: `v ${cls || ""}` }, v), h("div", { class: "k" }, label), h("div", { class: "r" }, r))));
}
function renderTimeline(R) {
  $("#timeline").replaceChildren(...R.timeline.map(e => h("li", { class: e.kind }, h("span", { class: "when" }, dayLabel(e.hour)), h("span", {}, e.text))));
}
function renderVsHistory(R) {
  const H = R.history, ex = H.expected, sm = H.simulated;
  const row = (label, a, b) => h("tr", {}, h("td", {}, label), h("td", {}, a), h("td", {}, b));
  $("#vsHistory").replaceChildren(h("table", { class: "vs" },
    h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Similar past events"), h("th", {}, "This simulation"))),
    h("tbody", {},
      row("Share of public aware", fmtPct(ex.awareness), fmtPct(sm.awareness)),
      row("Attitude shift", fmtSigned(ex.opinion_shift), fmtSigned(sm.opinion_shift)),
      row("Conversation half-life", `${ex.halflife_days.toFixed(0)} days`, sm.halflife_days == null ? "still going" : `${sm.halflife_days.toFixed(1)} days`),
      row("Practical outcome (−1 to +1)", fmtSigned(ex.commercial), "see the options above"))),
    h("p", { class: "hint" }, "Past numbers are hand-coded estimates from public reporting, weighted by similarity."));
}

// ------------------------------------------------------------------ charts (hand-built SVG)
const NS = "http://www.w3.org/2000/svg";
const sv = (tag, attrs = {}) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };
function lineChart(el, { x, series, ymin, ymax, yfmt = v => v.toFixed(2), zero = false, events = [] }) {
  const W = 960, H = 280, m = { l: 58, r: 24, t: 14, b: 34 };
  const all = series.flatMap(s => [...s.values, ...(s.band ? [...s.band[0], ...s.band[1]] : [])]);
  let lo = ymin ?? Math.min(...all), hi = ymax ?? Math.max(...all);
  if (hi - lo < 1e-6) { hi += 0.01; lo -= 0.01; }
  const pad = (hi - lo) * 0.08; if (ymin === undefined) lo -= pad; if (ymax === undefined) hi += pad;
  const X = v => m.l + (v - x[0]) / (x[x.length - 1] - x[0] || 1) * (W - m.l - m.r);
  const Y = v => H - m.b - (v - lo) / (hi - lo) * (H - m.t - m.b);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, y = Y(v);
    svg.append(sv("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: C.line }));
    const t = sv("text", { x: m.l - 8, y: y + 4, "text-anchor": "end", "font-size": 12 }); t.textContent = yfmt(v); svg.append(t);
  }
  const days = Math.round((x[x.length - 1] - x[0]) / 24), step = days > 14 ? 3 : days > 7 ? 2 : 1;
  for (let d = 0; d <= days; d += step) {
    const xx = X(x[0] + d * 24);
    const t = sv("text", { x: xx, y: H - m.b + 20, "text-anchor": "middle", "font-size": 12 }); t.textContent = `day ${d}`; svg.append(t);
  }
  if (zero && lo < 0 && hi > 0) svg.append(sv("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: C.faint, "stroke-dasharray": "2 4" }));
  for (const e of events) { const xx = X(e.hour); svg.append(sv("line", { x1: xx, x2: xx, y1: m.t, y2: H - m.b, stroke: e.color || C.accent, "stroke-width": 1.5, "stroke-dasharray": "5 4" })); }
  series.forEach(s => {
    if (s.band) {
      const top = s.band[1].map((v, i) => `${X(x[i])},${Y(v)}`), bot = s.band[0].map((v, i) => `${X(x[i])},${Y(v)}`).reverse();
      svg.append(sv("polygon", { points: [...top, ...bot].join(" "), fill: s.color, "fill-opacity": .14 }));
    }
    svg.append(sv("polyline", { points: s.values.map((v, i) => `${X(x[i])},${Y(v)}`).join(" "), fill: "none", stroke: s.color, "stroke-width": s.width || 2.2, "stroke-dasharray": s.dash || "", "stroke-linejoin": "round" }));
  });
  const legend = h("div", { class: "legend-chart" }, ...series.map(s => h("span", {}, h("i", { style: `background:${s.color}` }), s.name)),
    ...events.map(e => h("span", {}, h("i", { style: `background:${e.color || C.accent}` }), e.label)));
  el.replaceChildren(legend, svg);
}
function renderCharts(R) {
  const x = R.series.hours, xs = R.stories.length ? x.slice(0, R.stories[0].aware.length) : x;
  const resp = R.stories.find(s => s.id === "your_response");
  const ev = resp ? [{ hour: resp.start, label: "your response", color: C.accent }] : [];
  lineChart($("#chartReach"), { x: xs, ymin: 0, yfmt: v => fmtPct(v, 0), events: ev,
    series: R.stories.map((s, i) => ({ name: s.label + (s.truth === false ? " (false)" : ""), values: s.aware, color: STORY_COLORS[i % STORY_COLORS.length], dash: s.truth === false ? "6 4" : "" })) });
  const se = R.series, W = R.words || {};
  lineChart($("#chartMood"), { x, zero: true, events: ev, series: [
    { name: "average attitude (−1 to +1)", values: se.mean_opinion_p50, band: [se.mean_opinion_p10, se.mean_opinion_p90], color: C.text },
    { name: "share feeling negative", values: se.negative_share_p50, color: C.against },
    { name: "share feeling positive", values: se.positive_share_p50, color: C.for },
    { name: "emotional heat", values: se.buzz, color: C.accent, dash: "3 4", width: 1.6 }] });
  lineChart($("#chartAct"), { x, ymin: 0, yfmt: v => fmtPct(v, 1), events: ev, series: [
    { name: `${W.adopters || "potential buyers"} who ${W.adopt || "bought"}`, values: se.adoption_p50, band: [se.adoption_p10, se.adoption_p90], color: C.for },
    { name: `${W.customers || "customers"} who ${W.churn || "left"}`, values: se.churn_p50, band: [se.churn_p10, se.churn_p90], color: C.against }] });
}
function spark(values, color) {
  const W = 220, H = 46, lo = Math.min(...values, -0.05), hi = Math.max(...values, 0.05);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H });
  const Y = v => H - 4 - (v - lo) / (hi - lo) * (H - 8);
  svg.append(sv("line", { x1: 0, x2: W, y1: Y(0), y2: Y(0), stroke: C.line, "stroke-dasharray": "2 3" }));
  svg.append(sv("polyline", { points: values.map((v, i) => `${i / (values.length - 1) * W},${Y(v)}`).join(" "), fill: "none", stroke: color, "stroke-width": 2 }));
  return svg;
}
function renderSegments(R) {
  const W = R.words || {};
  $("#segments").replaceChildren(...R.segments.map(c => {
    const d = c.opinion_end - c.opinion_start, col = d < -0.01 ? C.against : d > 0.01 ? C.for : C.text;
    return h("div", { class: "seg" },
      h("h4", {}, cap(c.name)), h("p", {}, `${fmtPct(c.share)} of the population`),
      h("div", { class: "shift", style: `color:${col}` }, fmtSigned(d)),
      h("p", {}, `attitude ${fmtSigned(c.opinion_start)} → ${fmtSigned(c.opinion_end)}; ${fmtPct(c.aware)} heard about it`),
      spark(c.curve, col),
      c.adoption != null ? h("p", {}, `${fmtPct(c.adoption, 1)} ${W.adopt || "bought"}`) : null,
      c.churn != null ? h("p", {}, `${fmtPct(c.churn, 1)} ${W.churn || "left"}`) : null,
      c.drivers.length ? h("ul", {}, ...c.drivers.map(dv => h("li", {}, `${dv.label}: believed by ${fmtPct(dv.share)}`))) : null,
      c.note ? h("p", { class: "hint" }, c.note) : null);
  }));
}
function renderVoices(R) {
  $("#voices").replaceChildren(...R.voices.map(v => {
    const cls = v.opinion_end < -0.15 ? "against" : v.opinion_end > 0.15 ? "for" : "flat";
    return h("figure", { class: `voice ${cls}` }, h("q", {}, v.quote),
      h("div", { class: "arc" }, `${fmtSigned(v.opinion_start)} → ${fmtSigned(v.opinion_end)}${v.bought ? ", took it up" : ""}${v.left ? ", walked away" : ""}`),
      h("figcaption", { class: "who" }, `Person ${v.agent.toLocaleString()}, ${v.segment}. ${cap(v.who)}${v.followers > 50 ? `, ${v.followers.toLocaleString()} followers` : ""}.`),
      v.stories.length ? h("div", { class: "who" }, v.stories.map(s => `${s.label}: ${s.status}`).join("; ")) : null);
  }));
}
function analogCard(a) {
  const o = a.outcome;
  return h("div", { class: "analog" }, h("h4", {}, `${a.name}, ${a.year}`),
    a.similarity != null ? h("p", {}, h("span", { class: "sim-bar", style: `width:${Math.round(a.similarity * 90)}px` }), ` ${Math.round(a.similarity * 100)}% similar`) : null,
    h("p", {}, a.summary), ...(a.lessons || []).map(l => h("p", { class: "lesson" }, l)),
    h("div", { class: "outc" }, h("span", {}, `attention ~${o.halflife_days}d`), h("span", {}, `opinion ${fmtSigned(o.opinion_shift)}`),
      h("span", {}, `outcome ${fmtSigned(o.commercial)}`), h("span", {}, `split ${o.polarization.toFixed(1)}`)));
}
function patternCard(p) {
  return h("div", { class: "pattern" }, h("h4", {}, p.title), h("p", {}, p.text),
    p.evidence?.length ? h("small", {}, "Seen in: " + p.evidence.map(e => typeof e === "string" ? e : `${e.name} (${e.year})`).join(", ")) : null);
}
function renderAnalogs(R) {
  $("#analogs").replaceChildren(...R.analogs.map(analogCard));
  $("#patterns").replaceChildren(...R.patterns.map(patternCard));
}
$("#dlBtn").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify({ spec: S.spec, settings: settings(), result: S.result }, null, 1)], { type: "application/json" });
  const a = h("a", { href: URL.createObjectURL(blob), download: "hearsay-results.json" }); a.click();
});

// ------------------------------------------------------------------ the live network
function b64(s, Type) { const bin = atob(s); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new Type(u.buffer); }
const CHANNEL = ["someone they follow", "someone outside this view", "the trending feed", "the news", "started it", "a denial of it", "their own experience"];
const hash = (a, b) => { let x = (a * 374761393 + b * 668265263) | 0; x = (x ^ (x >>> 13)) * 1274126177; return ((x ^ (x >>> 16)) >>> 0) / 4294967296; };

const Net = {
  g: null, el: null, frames: [], lines: {},
  reset() { cancelAnimationFrame(this.raf); this.g = null; this.frames = []; this.lines = {}; this.el = null; },
  init(g, home) {
    this.g = g; const n = g.n;
    const node = $("#netTpl").content.firstElementChild.cloneNode(true);
    home.replaceChildren(node); this.el = node;
    this.cv = $("#netCanvas", node); this.ctx = this.cv.getContext("2d");
    this.x = Float32Array.from(g.x); this.y = Float32Array.from(g.y);
    this.vx = new Float32Array(n); this.vy = new Float32Array(n);
    this.r = new Float32Array(n);
    for (let i = 0; i < n; i++) this.r[i] = g.hub[i] ? 3.4 + Math.log10(g.followers[i] + 10) * 1.2 : 1.6 + Math.min(2.2, Math.log10(g.followers[i] + 1) * 0.9);
    this.out = Array.from({ length: n }, () => []);
    for (const [a, b, m] of g.ties) { this.out[a].push(b); if (m) this.out[b].push(a); }
    this.op = new Int8Array(n); this.fl = new Uint8Array(n);
    this.storyCol = g.stories.map((s, i) => STORY_COLORS[i % STORY_COLORS.length]);
    const sel = $("#netStory", node);
    g.stories.forEach((s, i) => sel.append(h("option", { value: i }, s.label + (s.truth === false ? " (false)" : ""))));
    sel.addEventListener("change", () => { this.filter = +sel.value; this.seek(Math.floor(this.head)); });
    $("#netTies", node).addEventListener("change", e => { this.showTies = e.target.checked; });
    $("#netPlay", node).addEventListener("click", () => this.togglePlay());
    $("#netSpeed", node).addEventListener("change", e => { this.speed = +e.target.value; });
    const sc = $("#netScrub", node);
    sc.addEventListener("input", () => { this.live = false; this.playing = false; $("#netPlay", node).textContent = "Play"; this.seek(+sc.value); });
    this.cv.addEventListener("mousemove", e => this.hover(e));
    this.cv.addEventListener("mouseleave", () => { this.hoverI = -1; $("#netTip", node).hidden = true; });
    this.cv.addEventListener("click", () => { this.pin = this.hoverI === this.pin ? -1 : this.hoverI; });
    this.filter = -1; this.showTies = false; this.speed = 9; this.playing = !reduceMotion; this.live = true;
    this.pin = -1; this.hoverI = -1; this.ticks = reduceMotion ? 0 : 320;
    if (reduceMotion) for (let k = 0; k < 320; k++) this.relax(1 - k / 320);
    this.clearState(); this.head = -1; this.applied = -1; this.last = performance.now();
    this.resize(); this.fit(true);
    addEventListener("resize", () => this.resize());
    const loop = t => { this.frame(t); this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  },
  clearState() {
    const n = this.g.n;
    this.trails = new Map(); this.pulses = []; this.bubbles = [];
    this.heard = Array.from({ length: n }, () => ({})); this.said = new Array(n).fill(null);
    this.posted = new Uint8Array(n); this.chan = new Array(7).fill(0); this.feedItems = [];
    this.op.fill(0); this.fl.fill(0);
  },
  setLive(on) { this.live = on; $("#liveTag", this.el).hidden = !on; },
  addFrames(fr) { for (const f of fr) this.frames.push(f); $("#netScrub", this.el).max = this.frames.length - 1; },
  finish(frames, slot) {
    if (frames && frames.length > this.frames.length) this.addFrames(frames.slice(this.frames.length));
    if (this.el && slot && this.el.parentElement !== slot) slot.replaceChildren(this.el);
    this.setLive(false);
    this.resize();
  },
  togglePlay() {
    this.playing = !this.playing;
    if (this.playing && this.head >= this.frames.length - 1) this.seek(0);
    $("#netPlay", this.el).textContent = this.playing ? "Pause" : "Play";
  },
  resize() {
    if (!this.cv) return;
    const dpr = Math.min(devicePixelRatio || 1, 2), rect = this.cv.getBoundingClientRect();
    this.W = rect.width; this.H = rect.height;
    this.cv.width = Math.round(rect.width * dpr); this.cv.height = Math.round(rect.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.fit(true);
  },
  fit(now) {
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (let i = 0; i < this.g.n; i++) { x0 = Math.min(x0, this.x[i]); x1 = Math.max(x1, this.x[i]); y0 = Math.min(y0, this.y[i]); y1 = Math.max(y1, this.y[i]); }
    const pad = 24, top = this.W < 600 ? 86 : 64, s = Math.min((this.W - 2 * pad) / Math.max(x1 - x0, 1), (this.H - pad - top) / Math.max(y1 - y0, 1));
    const target = { s, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 - (top - pad) / 2 / s };
    this.k = Math.max(0.55, Math.min(1, this.W / 900));
    if (now || !this.cam) this.cam = target;
    else for (const k of ["s", "cx", "cy"]) this.cam[k] += (target[k] - this.cam[k]) * 0.08;
  },
  sx(i) { return this.W / 2 + (this.x[i] - this.cam.cx) * this.cam.s; },
  sy(i) { return this.H / 2 + (this.y[i] - this.cam.cy) * this.cam.s; },
  // a light force layout: ties pull, close neighbours push, friend circles stay together
  relax(alpha) {
    const g = this.g, n = g.n, x = this.x, y = this.y, vx = this.vx, vy = this.vy;
    for (const [a, b] of g.ties) {
      const dx = x[b] - x[a], dy = y[b] - y[a], d = Math.hypot(dx, dy) || 1;
      const L = g.hub[a] || g.hub[b] ? 90 : 16, k = (g.hub[a] || g.hub[b] ? 0.004 : 0.03) * alpha;
      const f = (d - L) * k / d;
      vx[a] += dx * f; vy[a] += dy * f; vx[b] -= dx * f; vy[b] -= dy * f;
    }
    const cell = 14, grid = new Map();
    for (let i = 0; i < n; i++) { const key = ((x[i] / cell) | 0) * 100003 + ((y[i] / cell) | 0); let a = grid.get(key); if (!a) grid.set(key, a = []); a.push(i); }
    for (let i = 0; i < n; i++) {
      const cx = (x[i] / cell) | 0, cy = (y[i] / cell) | 0;
      for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) {
        const a = grid.get((cx + ox) * 100003 + cy + oy); if (!a) continue;
        for (const j of a) {
          if (j <= i) continue;
          const dx = x[j] - x[i], dy = y[j] - y[i], d2 = dx * dx + dy * dy + 0.01;
          if (d2 > cell * cell) continue;
          const f = 6 * alpha / d2;
          vx[i] -= dx * f; vy[i] -= dy * f; vx[j] += dx * f; vy[j] += dy * f;
        }
      }
    }
    for (let i = 0; i < n; i++) {
      const tx = g.hub[i] ? g.x[i] * 0.6 : g.x[i], ty = g.hub[i] ? g.y[i] * 0.6 : g.y[i];
      vx[i] += (tx - x[i]) * 0.006 * alpha; vy[i] += (ty - y[i]) * 0.006 * alpha;
      vx[i] *= 0.82; vy[i] *= 0.82; x[i] += vx[i]; y[i] += vy[i];
    }
  },
  // apply one hour of the simulation to the picture
  apply(fi, animate) {
    const f = this.frames[fi]; if (!f) return;
    this.op = b64(f.op, Int8Array); this.fl = b64(f.fl, Uint8Array);
    const now = performance.now(), hourMs = 1000 / this.speed;
    for (const [j, k, src, ch, acc] of f.hears) {
      this.heard[j][k] = { ch, src, acc, h: f.h };
      this.chan[ch]++;
      if (this.filter >= 0 && k !== this.filter) continue;
      if (src >= 0) {
        this.trails.set(src * 100000 + j, { s: src, t: j, k, h: f.h });
        if (animate) this.pulses.push({ s: src, t: j, k, t0: now + Math.random() * hourMs, dur: 650 + Math.random() * 300 });
      } else if (animate && ch !== 1) this.pulses.push({ s: -1, t: j, k, ch, t0: now + Math.random() * hourMs, dur: 700 });
    }
    let shown = 0;
    const posts = f.posts.filter(([i, k]) => this.filter < 0 || k === this.filter)
      .sort((a, b) => this.g.followers[b[0]] - this.g.followers[a[0]]);
    for (const [i, k] of posts) {
      this.posted[i] = 1; this.said[i] = { k, h: f.h };
      if (animate) for (const t of this.out[i].slice(0, 14)) this.pulses.push({ s: i, t, k, t0: now + Math.random() * hourMs, dur: 800, faint: true });
      const recent = this.feedItems.slice(-6).some(x => x.i === i);
      if (shown < 2 && !recent && (this.g.hub[i] || hash(i, f.h) < 0.35)) {
        shown++;
        this.feed({ i, k, h: f.h });
        if (animate && this.bubbles.length < 3 && !this.bubbles.some(b => Math.abs(this.sy(b.i) - this.sy(i)) < 34 && Math.abs(this.sx(b.i) - this.sx(i)) < 260))
          this.bubbles.push({ i, k, text: this.line(i, k, f.h), t0: now, dur: 2600 });
      }
    }
  },
  line(i, k, hr) {
    const id = this.g.stories[k]?.id, arr = this.lines[id];
    if (!arr || !arr.length) return this.g.stories[k]?.label || "";
    return arr[Math.floor(hash(i, hr) * arr.length)];
  },
  when(hr) { const t = 9 + hr; return `Day ${Math.floor(t / 24) - Math.floor(9 / 24) + 1}, ${String(t % 24).padStart(2, "0")}:00`; },
  feed(item, silent) {
    this.feedItems.push(item);
    if (this.feedItems.length > 60) this.feedItems.shift();
    if (silent) return;
    const ol = $("#feed", this.el); ol.prepend(this.feedLi(item));
    while (ol.children.length > 40) ol.lastChild.remove();
  },
  feedLi({ i, k, h: hr }) {
    const g = this.g, st = g.stories[k], v = st.valence, tone = v > 0.15 ? "pos" : v < -0.15 ? "neg" : "mid";
    return h("li", { class: tone }, `${this.when(hr)} · Person ${g.id[i].toLocaleString()}, ${g.segments[g.segment[i]]}${g.followers[i] > 200 ? `, ${g.followers[i].toLocaleString()} followers` : ""}`,
      h("span", { class: "q" }, this.line(i, k, hr)), h("span", { class: "story" }, `sharing “${st.label}”`));
  },
  seek(fi) {
    fi = Math.max(0, Math.min(fi, this.frames.length - 1));
    this.clearState();
    for (let f = 0; f <= fi; f++) this.apply(f, false);
    const ol = $("#feed", this.el); ol.replaceChildren(...this.feedItems.slice(-40).reverse().map(x => this.feedLi(x)));
    this.applied = fi; this.head = fi;
    $("#netScrub", this.el).value = fi;
  },
  frame(t) {
    const dt = Math.min(0.1, (t - this.last) / 1000); this.last = t;
    if (this.ticks > 0) { this.relax(Math.max(0.15, this.ticks / 320)); this.ticks--; this.fit(false); }
    if (this.playing && this.frames.length) {
      const avail = this.frames.length - 1;
      let sp = this.speed;
      if (this.live && avail - this.head > 24) sp = Math.max(sp, (avail - this.head) / 2.5);
      this.head = Math.min(avail, this.head + dt * sp);
      while (this.applied < Math.floor(this.head)) { this.applied++; this.apply(this.applied, avail - this.applied < 60); }
      $("#netScrub", this.el).value = this.applied;
      if (!this.live && this.head >= avail) { this.playing = false; $("#netPlay", this.el).textContent = "Play"; }
    }
    this.draw(t);
  },
  draw(now) {
    const c = this.ctx, g = this.g, n = g.n, W = this.W, H = this.H;
    c.fillStyle = C.stage; c.fillRect(0, 0, W, H);
    const hr = Math.max(0, Math.floor(this.head));
    // every tie, faintly: the web the stories can travel on
    c.lineWidth = 0.6; c.strokeStyle = this.showTies ? "rgba(211,191,223,.18)" : "rgba(211,191,223,.06)";
    c.beginPath();
    for (const [a, b] of g.ties) { c.moveTo(this.sx(a), this.sy(a)); c.lineTo(this.sx(b), this.sy(b)); }
    c.stroke();
    // word-of-mouth trails: who actually told whom
    for (const tr of this.trails.values()) {
      const age = Math.max(0, this.head - tr.h), fresh = Math.exp(-age / 5);
      c.strokeStyle = this.storyCol[tr.k]; c.globalAlpha = 0.22 + 0.6 * fresh; c.lineWidth = 0.8 + 1.2 * fresh;
      c.beginPath(); c.moveTo(this.sx(tr.s), this.sy(tr.s)); c.lineTo(this.sx(tr.t), this.sy(tr.t)); c.stroke();
    }
    c.globalAlpha = 1;
    if (this.pin >= 0) {
      c.strokeStyle = "rgba(255,244,214,.6)"; c.lineWidth = 1.2; c.beginPath();
      for (const t of this.out[this.pin]) { c.moveTo(this.sx(this.pin), this.sy(this.pin)); c.lineTo(this.sx(t), this.sy(t)); }
      c.stroke();
    }
    // nodes
    for (let i = 0; i < n; i++) {
      const X = this.sx(i), Y = this.sy(i), f = this.fl[i], o = this.op[i] / 127;
      let col = C.none, r = this.r[i] * this.k;
      if (f & 1) col = o > 0.2 ? C.for : o < -0.2 ? C.against : C.mixed;
      if (!(f & 1)) r *= 0.8;
      c.globalAlpha = f & 1 ? 0.55 + 0.45 * Math.min(1, Math.abs(o) * 1.4 + 0.2) : 0.9;
      c.fillStyle = col; c.beginPath(); c.arc(X, Y, r, 0, 6.283); c.fill();
      c.globalAlpha = 1;
      if (r > 3) { c.strokeStyle = C.ink; c.lineWidth = 1.2; c.stroke(); }
      if (f & 2) { c.strokeStyle = f & 4 ? "rgba(255,138,61,.95)" : "rgba(255,210,63,.9)"; c.lineWidth = 1.6; c.beginPath(); c.arc(X, Y, r + 2.4, 0, 6.283); c.stroke(); }
      if (g.hub[i]) { c.strokeStyle = "rgba(255,244,214,.85)"; c.lineWidth = 1.4; c.setLineDash([3, 2]); c.beginPath(); c.arc(X, Y, r + (f & 2 ? 5 : 2.5), 0, 6.283); c.stroke(); c.setLineDash([]); }
      if (f & 8) { c.fillStyle = C.ink; c.beginPath(); c.arc(X, Y, Math.max(1, r * 0.38), 0, 6.283); c.fill(); }
      if (f & 16) { c.strokeStyle = C.text; c.lineWidth = 1.2; c.beginPath(); c.moveTo(X - r, Y - r); c.lineTo(X + r, Y + r); c.moveTo(X + r, Y - r); c.lineTo(X - r, Y + r); c.stroke(); }
    }
    // pulses: a story moving along a tie, or arriving from the feed or the news
    this.pulses = this.pulses.filter(p => now < p.t0 + p.dur);
    for (const p of this.pulses) {
      if (now < p.t0) continue;
      const u = (now - p.t0) / p.dur, col = this.storyCol[p.k];
      if (p.s >= 0) {
        const x0 = this.sx(p.s), y0 = this.sy(p.s), x1 = this.sx(p.t), y1 = this.sy(p.t);
        const px = x0 + (x1 - x0) * u, py = y0 + (y1 - y0) * u, bx = x0 + (x1 - x0) * Math.max(0, u - 0.25), by = y0 + (y1 - y0) * Math.max(0, u - 0.25);
        c.strokeStyle = col; c.globalAlpha = p.faint ? 0.35 : 0.9; c.lineWidth = p.faint ? 1 : 1.8;
        c.beginPath(); c.moveTo(bx, by); c.lineTo(px, py); c.stroke();
        if (!p.faint) { c.fillStyle = col; c.beginPath(); c.arc(px, py, 2, 0, 6.283); c.fill(); }
      } else {
        const X = this.sx(p.t), Y = this.sy(p.t);
        c.strokeStyle = col; c.globalAlpha = 0.8 * (1 - u); c.lineWidth = 1.2;
        c.beginPath(); c.arc(X, Y, 3 + 10 * u, 0, 6.283); c.stroke();
      }
    }
    c.globalAlpha = 1;
    // speech bubbles
    this.bubbles = this.bubbles.filter(b => now < b.t0 + b.dur);
    c.font = '600 13px "Bricolage Grotesque", system-ui, sans-serif';
    for (const b of this.bubbles) {
      const a = Math.min(1, (now - b.t0) / 200, (b.t0 + b.dur - now) / 400);
      let text = b.text.length > 64 ? b.text.slice(0, 62) + "…" : b.text;
      const w = c.measureText(text).width + 20, X = Math.min(W - w - 8, Math.max(6, this.sx(b.i) + 8)), Y = Math.max(8, this.sy(b.i) - 38);
      c.globalAlpha = a;
      c.fillStyle = C.ink; c.beginPath(); c.roundRect ? c.roundRect(X + 3, Y + 3, w, 26, [13, 13, 13, 3]) : c.rect(X + 3, Y + 3, w, 26); c.fill();
      c.fillStyle = this.storyCol[b.k]; c.strokeStyle = C.ink; c.lineWidth = 2;
      c.beginPath(); c.roundRect ? c.roundRect(X, Y, w, 26, [13, 13, 13, 3]) : c.rect(X, Y, w, 26); c.fill(); c.stroke();
      c.fillStyle = C.ink; c.fillText(text, X + 10, Y + 17.5);
    }
    c.globalAlpha = 1;
    if (this.hoverI >= 0) { c.strokeStyle = C.accent; c.lineWidth = 2.5; c.beginPath(); c.arc(this.sx(this.hoverI), this.sy(this.hoverI), this.r[this.hoverI] * this.k + 5, 0, 6.283); c.stroke(); }
    this.hud(hr);
  },
  hud(hr) {
    if (!this.frames.length) { $("#netHud", this.el).replaceChildren(h("span", {}, "Wiring the network…")); return; }
    const n = this.g.n; let heard = 0, fo = 0, ag = 0, sp = 0;
    for (let i = 0; i < n; i++) { const f = this.fl[i]; if (f & 1) { heard++; const o = this.op[i] / 127; if (o > 0.2) fo++; else if (o < -0.2) ag++; } if (f & 2) sp++; }
    let posted = 0; for (let i = 0; i < n; i++) posted += this.posted[i];
    const key = `${hr}|${heard}|${this.trails.size}|${posted}`;
    if (key === this.hudKey) return; this.hudKey = key;
    $("#netHud", this.el).replaceChildren(
      h("div", {}, h("b", {}, this.when(hr))),
      h("div", {}, `${heard.toLocaleString()} of ${n.toLocaleString()} people here have heard · `, h("b", { style: `color:${C.for}` }, fo), " for · ", h("b", { style: `color:${C.against}` }, ag), " against"),
      h("div", {}, `${posted} have posted · ${sp} spreading now · ${this.trails.size} word-of-mouth links`));
    $("#netTime", this.el).textContent = this.when(hr);
    const tot = this.chan.reduce((a, b) => a + b, 0);
    if (tot) $("#channelStats", this.el).textContent = "How people in this view first heard: " +
      [[[0, 1], "from someone they know or follow"], [[3], "from the news"], [[2], "from the trending feed"],
       [[4], "started it themselves"], [[5], "through a denial of it"], [[6], "from their own experience"]]
        .map(([ix, l]) => [l, ix.reduce((a, i) => a + this.chan[i], 0)]).filter(([, v]) => v / tot >= 0.005)
        .map(([l, v]) => `${Math.round(v / tot * 100)}% ${l}`).join(", ") + ".";
  },
  hover(e) {
    const rect = this.cv.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
    let best = -1, bd = 12 * 12;
    for (let i = 0; i < this.g.n; i++) { const dx = this.sx(i) - mx, dy = this.sy(i) - my, d = dx * dx + dy * dy; if (d < bd) { bd = d; best = i; } }
    this.hoverI = best;
    const tip = $("#netTip", this.el);
    if (best < 0) { tip.hidden = true; return; }
    const g = this.g, f = this.fl[best], o = this.op[best] / 127;
    const stance = !(f & 1) ? "hasn't heard yet" : o > 0.2 ? `for it (${fmtSigned(o)})` : o < -0.2 ? `against it (${fmtSigned(o)})` : `undecided (${fmtSigned(o)})`;
    const heard = Object.entries(this.heard[best]).map(([k, x]) => {
      const st = g.stories[k]; const from = x.src >= 0 ? `Person ${g.id[x.src].toLocaleString()}` : CHANNEL[x.ch];
      return h("div", {}, `${st.label}: ${x.acc ? "believed" : "rejected"}, from ${from}`);
    });
    const said = this.said[best];
    tip.replaceChildren(h("div", {}, h("b", {}, `Person ${g.id[best].toLocaleString()}`), `, ${g.segments[g.segment[best]]}`),
      h("div", {}, `${cap(g.who[best])} · ${g.followers[best].toLocaleString()} followers`), h("div", {}, `Now ${stance}${f & 8 ? ", took it up" : ""}${f & 16 ? ", walked away" : ""}`),
      ...heard, said ? h("div", { class: "q" }, `“${this.line(best, said.k, said.h)}”`) : null);
    tip.hidden = false;
    tip.style.left = Math.min(mx + 14, this.W - 290) + "px"; tip.style.top = Math.min(my + 14, this.H - 140) + "px";
  },
};

// ------------------------------------------------------------------ memory
let memLoaded = null;
async function loadMemory() {
  if (!memLoaded) memLoaded = await (await fetch("/api/library")).json();
  const L = memLoaded, sel = $("#memFilter"), dom = $("#memDomain");
  if (sel.options.length === 1) {
    Object.entries(L.archetypes).forEach(([k, v]) => sel.append(h("option", { value: k }, v)));
    const DN = { brand: "Brands and companies", policy: "Government policy", economy: "Economy and markets", geopolitics: "Geopolitics", health: "Public health", politics: "Politics", labour: "Work and labour", tech: "Technology" };
    (L.domains || []).forEach(d => dom.append(h("option", { value: d }, DN[d] || cap(d))));
    [sel, dom].forEach(x => x.addEventListener("change", loadMemory));
    $("#memSearch").addEventListener("input", loadMemory);
    const names = Object.fromEntries(L.events.map(e => [e.id, `${e.name} (${e.year})`]));
    $("#memPatterns").replaceChildren(...L.patterns.map(p => patternCard({ ...p, evidence: p.evidence.map(id => names[id] || id) })));
  }
  const f = sel.value, d = dom.value, q = $("#memSearch").value.trim().toLowerCase();
  const list = L.events.filter(e => (!f || e.archetype === f) && (!d || e.domain === d) &&
    (!q || `${e.name} ${e.summary} ${e.country} ${e.year}`.toLowerCase().includes(q))).sort((a, b) => b.year - a.year);
  $("#memCount").textContent = `${list.length} of ${L.events.length} events`;
  $("#memList").replaceChildren(...list.map(e =>
    h("div", { class: "mem" }, h("span", { class: "yr" }, e.year), " ", h("span", { class: "where" }, [e.country, L.archetypes[e.archetype]].filter(Boolean).join(" · ")),
      h("h4", {}, e.name), h("p", {}, e.summary), ...(e.lessons || []).map(l => h("p", { class: "lesson" }, l)),
      h("div", { class: "outc" }, h("span", {}, `attention ~${e.outcome.halflife_days}d`), h("span", {}, `opinion ${fmtSigned(e.outcome.opinion_shift)}`),
        h("span", {}, `outcome ${fmtSigned(e.outcome.commercial)}`), h("span", {}, e.attention_source)))));
}
