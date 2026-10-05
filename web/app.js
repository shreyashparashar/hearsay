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
const INK = { blue: "#0078BF", pink: "#FF48B0", yellow: "#FFE800", ink: "#000", grey: "#9A9C97", green: "#00A95C", orange: "#FF6C2F", purple: "#765BA7", teal: "#00838A" };
const STORY_COLORS = [INK.blue, INK.pink, INK.ink, INK.orange, INK.green, INK.purple, INK.teal, "#B8A800", INK.grey, "#C2185B"];

const S = { images: [], spec: null, archetypes: {}, fullPlan: [], disabled: new Set(), hours: {}, result: null, frames: null, frame: 0, playing: null };

// ------------------------------------------------------------------ boot
fetch("/api/health").then(r => r.json()).then(j => {
  const el = $("#modelStatus");
  if (j.model) el.textContent = `Reading with ${j.model}`;
  else { el.textContent = "No AI model set: using the keyword reader"; el.classList.add("warn"); }
  $("#agents").max = j.max_agents;
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
$("#exampleBtn").addEventListener("click", () => {
  $("#text").value = "Brewly is launching the Brewly One, an $899 countertop espresso machine that grinds, tamps and learns each person's taste. It ships in three weeks. A few beta units had leaking seals, which we've fixed. Our main rival sells a similar machine for $650.";
  $("#context").value = "Premium kitchen appliance, US and UK, buyers mostly 28-45";
});
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
    $("#stepSpec").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  } catch (e) { showErr("#readErr", e.message); }
  finally { btn.disabled = false; btn.textContent = "Read it"; }
});
function showErr(sel, msg) { const el = $(sel); el.textContent = msg; el.hidden = false; }
function hideErr(sel) { $(sel).hidden = true; }

// ------------------------------------------------------------------ step 2: spec
const DIALS = [
  ["valence", "How it reflects on the brand", -1, 1, "badly", "well"],
  ["emotionality", "Emotional charge", 0, 1, "flat", "explosive"],
  ["credibility", "How believable it is", 0, 1, "doubtful", "certain"],
  ["identity", "Touches politics or identity", 0, 1, "not at all", "entirely"],
  ["lean", "Which side it flatters", -1, 1, "progressive", "traditional"],
  ["harm", "Harm to people", 0, 1, "none", "severe"],
  ["responsibility", "Blame on the brand", 0, 1, "none", "all of it"],
  ["hype", "Anticipation beforehand", 0, 1, "none", "huge"],
  ["price", "How much it's about money", 0, 1, "not at all", "entirely"],
  ["prominence", "How famous the brand is", 0, 1, "unknown", "household name"],
  ["novelty", "How surprising it is", 0, 1, "expected", "shocking"],
];
const EXTRA = [["quality", "How good it really is, once tried", -1, 1, "poor", "excellent"],
               ["substitutes", "How easy it is to switch to a rival", 0, 1, "hard", "trivial"]];

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
["#sTitle", "#sBrand", "#sSummary"].forEach(id => $(id).addEventListener("input", e => {
  if (!S.spec) return;
  S.spec[{ "#sTitle": "title", "#sBrand": "brand", "#sSummary": "summary" }[id]] = e.target.value;
}));
$("#sArche").addEventListener("change", e => { S.spec.archetype = e.target.value; S.spec.audience = []; renderAudience(); schedulePreview(0); });

function renderAudience() {
  const tb = $("#audTable tbody"); tb.replaceChildren();
  const aud = S.spec.audience;
  if (!aud.length) {
    tb.append(h("tr", {}, h("td", { colspan: 6 }, "Using the typical audience for this kind of event. Add a group to define your own.")));
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
    const buy = h("input", { type: "checkbox", checked: g.can_adopt, "aria-label": "Could buy" });
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
    disabled_stories: [...S.disabled], story_hours: S.hours,
  };
}
$$("#stepSpec aside select, #stepSpec aside input").forEach(el => el.addEventListener("change", () => schedulePreview()));
$("#agents").addEventListener("input", () => { $("#agentsOut").textContent = (+$("#agents").value).toLocaleString(); eta(); });
["#days", "#runs"].forEach(id => $(id).addEventListener("input", eta));
function eta() {
  const sec = (+$("#agents").value / 1e6) * 0.6 * (+$("#days").value * 24) * +$("#runs").value + 5 * (+$("#agents").value / 1e6);
  $("#eta").textContent = `Takes about ${sec < 90 ? Math.ceil(sec / 5) * 5 + " seconds" : Math.ceil(sec / 60) + " minutes"} on a free server.`;
}
eta();

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
    cb.addEventListener("change", () => { cb.checked ? S.disabled.delete(p.id) : S.disabled.add(p.id); li.classList.toggle("off", !cb.checked); });
    const hr = h("input", { type: "number", min: 0, max: 720, value: S.hours[p.id] ?? p.start, disabled: fixed, "aria-label": `Start hour for ${p.label}` });
    hr.addEventListener("change", () => { S.hours[p.id] = +hr.value; });
    const li = h("li", { class: off ? "off" : "" }, cb,
      h("span", {}, h("span", { class: "s-label" }, p.label), originTag(p.origin), p.truth === false ? h("span", { class: "tagp false" }, "false") : null),
      h("span", { class: "s-hour" }, "hour", hr),
      p.description ? h("p", { class: "s-desc" }, p.description) : null);
    ol.append(li);
  }
}
function renderHistorySide(j) {
  const el = $("#history"); el.replaceChildren();
  el.append(h("h4", {}, `Read as: ${j.archetype_label}`));
  const pr = j.priors;
  el.append(h("p", { class: "hint" }, `Similar past events held attention for about ${pr.halflife_days.toFixed(0)} days, moved opinion by ${fmtSigned(pr.opinion_shift)} and hit business by ${fmtSigned(pr.commercial)} (−1 to +1).`));
  el.append(h("h4", {}, "Closest past events"));
  j.analogs.slice(0, 4).forEach(a => el.append(h("div", { class: "mini-analog" },
    h("b", {}, `${a.name}, ${a.year}`), h("span", { class: "sim-bar", style: `width:${Math.round(a.similarity * 80)}px` }), `${Math.round(a.similarity * 100)}% similar`)));
  if (j.patterns.length) {
    el.append(h("h4", {}, "Patterns that apply"));
    j.patterns.forEach(p => el.append(h("p", { class: "hint" }, h("b", {}, p.title + ". "), p.text)));
  }
}

// ------------------------------------------------------------------ run
$("#runBtn").addEventListener("click", run);
$("#againBtn").addEventListener("click", () => $("#stepSpec").scrollIntoView({ behavior: "smooth" }));
async function run() {
  const btn = $("#runBtn"); btn.disabled = true;
  $("#stepRun").hidden = false; $("#bar").style.width = "2%"; $("#runMsg").textContent = "Sending to the simulator";
  $("#stepRun").scrollIntoView({ behavior: "smooth", block: "center" });
  try {
    const r = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec: S.spec, settings: settings() }) });
    const j = await r.json(); if (!r.ok) throw new Error(j.detail || "Could not start the simulation.");
    await poll(j.job);
  } catch (e) { $("#runMsg").textContent = e.message; }
  finally { btn.disabled = false; }
}
async function poll(id) {
  for (;;) {
    await new Promise(r => setTimeout(r, 1200));
    const r = await fetch(`/api/jobs/${id}`); const j = await r.json();
    if (!r.ok) throw new Error(j.detail);
    $("#bar").style.width = `${Math.max(2, j.progress * 100)}%`;
    $("#runMsg").textContent = j.status === "queued" && j.queue_position > 1 ? `Waiting in line (position ${j.queue_position})` : j.message;
    if (j.status === "error") throw new Error(`${j.message}: ${j.error}`);
    if (j.status === "done") { S.result = j.result; renderResult(); return; }
  }
}

// ------------------------------------------------------------------ results
function renderResult() {
  const R = S.result;
  $("#stepRun").hidden = true; $("#stepResult").hidden = false;
  const k = R.kpis;
  const loud = Math.min(1, Math.abs(k.opinion_change) * 5 + Math.max(0, k.negative_peak - k.negative_start) * 4 + k.reach * 0.4);
  const vt = $("#verdictTitle");
  vt.textContent = R.verdict.title;
  vt.style.fontVariationSettings = `"wdth" ${Math.round(55 + loud * 95)}, "wght" ${Math.round(600 + loud * 300)}`;
  vt.style.color = k.opinion_change < -0.03 ? INK.pink : k.opinion_change > 0.03 ? INK.blue : INK.ink;
  $("#verdictLine").textContent = R.verdict.line;
  setupCrowd(R); renderKpis(R); renderTimeline(R);
  $("#briefing").replaceChildren(...R.briefing.split(/\n\s*\n/).map(p => h("p", {}, p)));
  renderVsHistory(R); renderCharts(R); renderSegments(R); renderVoices(R); renderAnalogs(R);
  $("#meta").textContent = `${R.meta.agents.toLocaleString()} people, ${R.meta.ties.toLocaleString()} social ties, ${Math.round(R.meta.hours / 24)} days, ${R.meta.runs} run${R.meta.runs > 1 ? "s" : ""} (ranges show the spread between runs), ${R.meta.seconds}s. Read as: ${R.meta.archetype}.`;
  $("#stepResult").scrollIntoView({ behavior: "smooth" });
}

function renderKpis(R) {
  const k = R.kpis, per = 1e6 / R.meta.agents;
  const items = [
    [fmtPct(k.reach), "heard about it", ""],
    [Math.round(k.peak_posts * per).toLocaleString(), "posts an hour at the peak, per million people", `on ${dayLabel(k.peak_posts_hour).toLowerCase()}`],
    [fmtSigned(k.opinion_change), "change in attitude (−1 to +1)", `from ${fmtSigned(k.opinion_start)}`, k.opinion_change < 0 ? "neg" : "pos"],
    [fmtPct(k.negative_peak), "felt negative at the worst moment", `${fmtPct(k.negative_start)} before`, "neg"],
    [fmtPct(k.adoption, 1), "of potential buyers bought", `range ${fmtPct(k.adoption_lo, 1)}–${fmtPct(k.adoption_hi, 1)}`, "pos"],
    [fmtPct(k.churn, 1), "of existing customers left", `range ${fmtPct(k.churn_lo, 1)}–${fmtPct(k.churn_hi, 1)}`, "neg"],
  ];
  if (k.incidents) items.push([Math.round(k.incidents * per).toLocaleString(), "buyer incident posts, per million people", ""]);
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
      row("Business impact (−1 to +1)", fmtSigned(ex.commercial), "see buying and leaving above"))),
    h("p", { class: "hint" }, "Past numbers are hand-coded estimates from public reporting, weighted by similarity. Big gaps are worth a second look at the dials."));
}

// ------------------------------------------------------------------ crowd replay
function b64(s, Type) { const bin = atob(s); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new Type(u.buffer); }
function setupCrowd(R) {
  const c = R.crowd; if (!c) return;
  const n = c.n, T = c.hours.length;
  S.frames = { n, T, hours: c.hours, seg: b64(c.segment, Uint8Array), op: b64(c.opinion, Int8Array), fl: b64(c.flags, Uint8Array) };
  const sc = $("#scrub"); sc.max = T - 1; sc.value = T - 1; S.frame = T - 1;
  sc.oninput = () => { S.frame = +sc.value; drawCrowd(); };
  $("#play").onclick = togglePlay;
  const counts = {}; for (const s of S.frames.seg) counts[s] = (counts[s] || 0) + 1;
  $("#crowdLabels").replaceChildren(...R.meta.segments.map((name, i) => h("span", {}, h("b", {}, name), ` ${counts[i] || 0} people shown`)));
  drawCrowd();
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) { S.frame = 0; sc.value = 0; togglePlay(); }
}
function togglePlay() {
  const btn = $("#play");
  if (S.playing) { clearInterval(S.playing); S.playing = null; btn.textContent = "Play"; return; }
  if (S.frame >= S.frames.T - 1) S.frame = 0;
  btn.textContent = "Pause";
  S.playing = setInterval(() => {
    S.frame++; $("#scrub").value = S.frame; drawCrowd();
    if (S.frame >= S.frames.T - 1) togglePlay();
  }, 110);
}
function drawCrowd() {
  const F = S.frames, cv = $("#crowd"), ctx = cv.getContext("2d");
  const cols = 96, rows = Math.ceil(F.n / cols), cell = 10, W = cols * cell;
  if (cv.width !== W) cv.width = W;
  cv.height = rows * cell;
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, cv.height);
  const base = S.frame * F.n;
  // two ink passes with a 1px misregistration, like a riso print
  for (const pass of ["blue", "pink"]) {
    ctx.globalCompositeOperation = "multiply";
    const off = pass === "pink" ? 1 : 0;
    for (let i = 0; i < F.n; i++) {
      const x = (i % cols) * cell + off, y = Math.floor(i / cols) * cell + off;
      const o = F.op[base + i] / 127, f = F.fl[base + i];
      const aware = f & 1, spreading = f & 2;
      if (!aware) { if (pass === "blue") { ctx.fillStyle = "#cfd1cc"; ctx.fillRect(x + cell * .3, y + cell * .3, cell * .4, cell * .4); } continue; }
      const strength = Math.min(1, Math.abs(o) * 1.6 + 0.15);
      if (pass === "blue" && o > 0.02) { ctx.fillStyle = `rgba(0,120,191,${strength})`; ctx.fillRect(x + 1, y + 1, cell - 2, cell - 2); }
      if (pass === "pink" && o < -0.02) { ctx.fillStyle = `rgba(255,72,176,${strength})`; ctx.fillRect(x, y, cell - 2, cell - 2); }
      if (pass === "blue" && Math.abs(o) <= 0.02) { ctx.fillStyle = "#b9bbb6"; ctx.fillRect(x + 1, y + 1, cell - 2, cell - 2); }
    }
  }
  ctx.globalCompositeOperation = "source-over";
  for (let i = 0; i < F.n; i++) {   // spreading = yellow chip on top; bought = black dot; left = black cross
    const f = F.fl[base + i]; if (!(f & 26)) continue;
    const x = (i % cols) * cell, y = Math.floor(i / cols) * cell;
    if (f & 2) { ctx.fillStyle = INK.yellow; ctx.fillRect(x + 2, y + 2, cell - 5, cell - 5); ctx.strokeStyle = "#000"; ctx.lineWidth = 1; ctx.strokeRect(x + 2.5, y + 2.5, cell - 6, cell - 6); }
    ctx.fillStyle = "#000";
    if (f & 8) ctx.fillRect(x + cell * .38, y + cell * .38, cell * .24, cell * .24);
    if (f & 16) { ctx.fillRect(x + 1, y + cell / 2 - 1, cell - 3, 2); ctx.fillRect(x + cell / 2 - 1, y + 1, 2, cell - 3); }
  }
  // segment boundaries
  ctx.fillStyle = "#000";
  let prev = F.seg[0];
  for (let i = 1; i < F.n; i++) if (F.seg[i] !== prev) { prev = F.seg[i]; const r = Math.floor(i / cols); ctx.fillRect((i % cols) * cell, r * cell, 3, cell); ctx.fillRect(0, (r + 1) * cell - 1, (i % cols) * cell, 2); ctx.fillRect((i % cols) * cell, r * cell, W - (i % cols) * cell, 2); }
  $("#scrubOut").textContent = dayLabel(F.hours[S.frame]);
}

// ------------------------------------------------------------------ charts (hand-built SVG)
const NS = "http://www.w3.org/2000/svg";
const sv = (tag, attrs = {}) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };
function lineChart(el, { x, series, ymin, ymax, yfmt = v => v.toFixed(2), zero = false, events = [] }) {
  const W = 960, H = 280, m = { l: 58, r: 34, t: 14, b: 34 };
  const all = series.flatMap(s => [...s.values, ...(s.band ? [...s.band[0], ...s.band[1]] : [])]);
  let lo = ymin ?? Math.min(...all), hi = ymax ?? Math.max(...all);
  if (hi - lo < 1e-6) { hi += 0.01; lo -= 0.01; }
  const pad = (hi - lo) * 0.08; if (ymin === undefined) lo -= pad; if (ymax === undefined) hi += pad;
  const X = v => m.l + (v - x[0]) / (x[x.length - 1] - x[0] || 1) * (W - m.l - m.r);
  const Y = v => H - m.b - (v - lo) / (hi - lo) * (H - m.t - m.b);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const defs = sv("defs"); svg.append(defs);
  // axes + grid
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, y = Y(v);
    svg.append(sv("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: "#000", "stroke-opacity": .12 }));
    const t = sv("text", { x: m.l - 8, y: y + 4, "text-anchor": "end", "font-size": 13 }); t.textContent = yfmt(v); svg.append(t);
  }
  const days = Math.round((x[x.length - 1] - x[0]) / 24), step = days > 14 ? 3 : days > 7 ? 2 : 1;
  for (let d = 0; d <= days; d += step) {
    const xx = X(x[0] + d * 24);
    svg.append(sv("line", { x1: xx, x2: xx, y1: H - m.b, y2: H - m.b + 6, stroke: "#000", "stroke-width": 2 }));
    const t = sv("text", { x: xx, y: H - m.b + 22, "text-anchor": "middle", "font-size": 13 }); t.textContent = `day ${d}`; svg.append(t);
  }
  if (zero && lo < 0 && hi > 0) svg.append(sv("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: "#000", "stroke-width": 1.5, "stroke-dasharray": "2 4" }));
  for (const e of events) { const xx = X(e.hour); svg.append(sv("line", { x1: xx, x2: xx, y1: m.t, y2: H - m.b, stroke: e.color || "#000", "stroke-width": 2, "stroke-dasharray": "6 4" })); }
  svg.append(sv("line", { x1: m.l, x2: m.l, y1: m.t, y2: H - m.b, stroke: "#000", "stroke-width": 3 }));
  svg.append(sv("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: "#000", "stroke-width": 3 }));
  series.forEach((s, si) => {
    if (s.band) {
      const pid = `hatch${Math.random().toString(36).slice(2, 7)}`;
      const pat = sv("pattern", { id: pid, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
      pat.append(sv("rect", { width: 2.5, height: 6, fill: s.color, "fill-opacity": .45 })); defs.append(pat);
      const top = s.band[1].map((v, i) => `${X(x[i])},${Y(v)}`), bot = s.band[0].map((v, i) => `${X(x[i])},${Y(v)}`).reverse();
      svg.append(sv("polygon", { points: [...top, ...bot].join(" "), fill: `url(#${pid})` }));
    }
    const pts = s.values.map((v, i) => `${X(x[i])},${Y(v)}`).join(" ");
    svg.append(sv("polyline", { points: pts, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-opacity": .35, transform: "translate(1.5 1.5)" }));
    svg.append(sv("polyline", { points: pts, fill: "none", stroke: s.color, "stroke-width": s.width || 3, "stroke-dasharray": s.dash || "", "stroke-linejoin": "round" }));
  });
  const legend = h("div", { class: "legend" }, ...series.map(s => h("span", {}, h("i", { style: `background:${s.color}` }), s.name)),
    ...events.map(e => h("span", {}, h("i", { style: `background:repeating-linear-gradient(90deg,${e.color || "#000"} 0 5px,transparent 5px 8px)` }), e.label)));
  el.replaceChildren(legend, svg);
}
function renderCharts(R) {
  const x = R.series.hours, xs = R.stories.length ? x.slice(0, R.stories[0].aware.length) : x;
  const resp = R.stories.find(s => s.id === "your_response");
  const ev = resp ? [{ hour: resp.start, label: "your response", color: INK.blue }] : [];
  lineChart($("#chartReach"), { x: xs, ymin: 0, yfmt: v => fmtPct(v, 0), events: ev,
    series: R.stories.map((s, i) => ({ name: s.label + (s.truth === false ? " (false)" : ""), values: s.aware, color: STORY_COLORS[i % STORY_COLORS.length], dash: s.truth === false ? "8 5" : "" })) });
  const se = R.series;
  lineChart($("#chartMood"), { x, zero: true, events: ev, series: [
    { name: "average attitude (−1 to +1)", values: se.mean_opinion_p50, band: [se.mean_opinion_p10, se.mean_opinion_p90], color: INK.ink },
    { name: "share feeling negative", values: se.negative_share_p50, color: INK.pink },
    { name: "share feeling positive", values: se.positive_share_p50, color: INK.blue },
    { name: "emotional heat", values: se.buzz, color: INK.orange, dash: "3 4", width: 2 }] , yfmt: v => v.toFixed(2) });
  lineChart($("#chartAct"), { x, ymin: 0, yfmt: v => fmtPct(v, 1), events: ev, series: [
    { name: "potential buyers who bought", values: se.adoption_p50, band: [se.adoption_p10, se.adoption_p90], color: INK.blue },
    { name: "existing customers who left", values: se.churn_p50, band: [se.churn_p10, se.churn_p90], color: INK.pink }] });
}

function spark(values, color) {
  const W = 220, H = 46, lo = Math.min(...values, -0.05), hi = Math.max(...values, 0.05);
  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H });
  const Y = v => H - 4 - (v - lo) / (hi - lo) * (H - 8);
  svg.append(sv("line", { x1: 0, x2: W, y1: Y(0), y2: Y(0), stroke: "#000", "stroke-dasharray": "2 3" }));
  svg.append(sv("polyline", { points: values.map((v, i) => `${i / (values.length - 1) * W},${Y(v)}`).join(" "), fill: "none", stroke: color, "stroke-width": 3 }));
  return svg;
}
function renderSegments(R) {
  $("#segments").replaceChildren(...R.segments.map(c => {
    const d = c.opinion_end - c.opinion_start, col = d < -0.01 ? INK.pink : d > 0.01 ? INK.blue : INK.ink;
    return h("div", { class: "seg" },
      h("h4", {}, c.name), h("p", {}, `${fmtPct(c.share)} of the population`),
      h("div", { class: "shift", style: `color:${col}` }, fmtSigned(d)),
      h("p", {}, `attitude ${fmtSigned(c.opinion_start)} → ${fmtSigned(c.opinion_end)}; ${fmtPct(c.aware)} heard about it`),
      spark(c.curve, col),
      c.adoption != null ? h("p", {}, `${fmtPct(c.adoption, 1)} bought`) : null,
      c.churn != null ? h("p", {}, `${fmtPct(c.churn, 1)} of customers left`) : null,
      c.drivers.length ? h("ul", {}, ...c.drivers.map(dv => h("li", {}, `${dv.label}: believed by ${fmtPct(dv.share)}`))) : null,
      c.note ? h("p", { class: "hint" }, c.note) : null);
  }));
}
function renderVoices(R) {
  $("#voices").replaceChildren(...R.voices.map(v => {
    const d = v.opinion_end - v.opinion_start;
    const cls = v.opinion_end < -0.15 ? "against" : v.opinion_end > 0.15 ? "for" : "flat";
    return h("figure", { class: `voice ${cls}` }, h("q", {}, v.quote),
      h("div", { class: "arc" }, `${fmtSigned(v.opinion_start)} → ${fmtSigned(v.opinion_end)}${v.bought ? ", bought" : ""}${v.left ? ", left" : ""}`),
      h("figcaption", { class: "who" }, `Person ${v.agent.toLocaleString()}, ${v.segment}. ${v.who[0].toUpperCase() + v.who.slice(1)}${v.followers > 50 ? `, ${v.followers.toLocaleString()} followers` : ""}.`),
      v.stories.length ? h("div", { class: "who" }, v.stories.map(s => `${s.label}: ${s.status}`).join("; ")) : null);
  }));
}
function analogCard(a) {
  const o = a.outcome;
  return h("div", { class: "analog" }, h("h4", {}, `${a.name}, ${a.year}`),
    a.similarity != null ? h("p", {}, h("span", { class: "sim-bar", style: `width:${Math.round(a.similarity * 90)}px` }), `${Math.round(a.similarity * 100)}% similar`) : null,
    h("p", {}, a.summary), ...(a.lessons || []).map(l => h("p", { class: "lesson" }, l)),
    h("div", { class: "outc" }, h("span", {}, `attention ~${o.halflife_days}d`), h("span", {}, `opinion ${fmtSigned(o.opinion_shift)}`),
      h("span", {}, `business ${fmtSigned(o.commercial)}`), h("span", {}, `split ${o.polarization.toFixed(1)}`)));
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
  const blob = new Blob([JSON.stringify({ spec: S.spec, settings: settings(), result: { ...S.result, crowd: undefined } }, null, 2)], { type: "application/json" });
  const a = h("a", { href: URL.createObjectURL(blob), download: "hearsay-results.json" }); a.click();
});

// ------------------------------------------------------------------ memory
let memLoaded = null;
async function loadMemory() {
  if (!memLoaded) memLoaded = await (await fetch("/api/library")).json();
  const L = memLoaded, sel = $("#memFilter");
  if (sel.options.length === 1) {
    Object.entries(L.archetypes).forEach(([k, v]) => sel.append(h("option", { value: k }, v)));
    sel.addEventListener("change", loadMemory);
    const names = Object.fromEntries(L.events.map(e => [e.id, `${e.name} (${e.year})`]));
    $("#memPatterns").replaceChildren(...L.patterns.map(p => patternCard({ ...p, evidence: p.evidence.map(id => names[id] || id) })));
  }
  const f = sel.value;
  $("#memList").replaceChildren(...L.events.filter(e => !f || e.archetype === f).sort((a, b) => b.year - a.year).map(e =>
    h("div", { class: "mem" }, h("span", { class: "yr" }, e.year), h("h4", {}, e.name), h("p", { class: "hint" }, L.archetypes[e.archetype]),
      h("p", {}, e.summary), ...(e.lessons || []).map(l => h("p", { class: "lesson" }, h("i", {}, l))),
      h("div", { class: "outc" }, h("span", {}, `attention ~${e.outcome.halflife_days}d`), h("span", {}, `opinion ${fmtSigned(e.outcome.opinion_shift)}`),
        h("span", {}, `business ${fmtSigned(e.outcome.commercial)}`), h("span", {}, e.attention_source)))));
}
