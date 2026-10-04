(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const actorLabel = id => ({ host: "Host", planner: "Planner", skeptic: "Skeptic", pi: "PI", runner: "Runner" }[id] || id);
  const niceTime = stamp => new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "UTC" }).format(new Date(stamp));
  const fmtCount = n => Number(n).toLocaleString("en-US");
  let data, activeStage = 0, cohort = "discovery", threshold = "0.05", activeRole = "host", timer = null, playing = false;

  function fail(error) {
    console.error(error);
    const target = $("#runSummary");
    target.innerHTML = '<div class="error-message">The local evidence package could not be loaded. Keep <code>data.json</code> beside this page and serve the folder as a static site.</div>';
  }

  function init(payload) {
    data = payload;
    renderSummary(); renderTimeline(); renderStage(0); renderResults(); renderChoices(); renderRoles(); renderEvidence();
    wireControls(); startAmbient();
  }

  function renderSummary() {
    const r = data.run;
    const metrics = [
      ["03", "registered science Results", "three canonical exports"],
      ["02", "recorded reviews", "linked to Results"],
      ["01", "frozen holdout", "single controlled attempt"],
      ["188 s", "reported trace span", "not a speed benchmark"]
    ];
    $("#runSummary").innerHTML = metrics.map((m, i) => `<div class="run-metric"><strong class="${i===0?"metric-accent":""}">${m[0]}</strong><span>${m[1]} · ${m[2]}</span></div>`).join("");
    $("#totalBeats").textContent = `${data.stages.length} beats`;
  }

  function stageSeqLabel(stage) {
    if (!stage.event_sequences.length) return "export";
    const nums = stage.event_sequences;
    const lo = Math.min(...nums), hi = Math.max(...nums);
    return lo === hi ? `#${lo}` : `#${lo}–${hi}`;
  }

  function renderTimeline() {
    $("#timeline").innerHTML = data.stages.map((s, i) => `<li><button class="stage-button" type="button" data-stage="${i}" aria-current="${i===activeStage?"step":"false"}" aria-label="Stage ${i+1}: ${s.label}, events ${stageSeqLabel(s)}"><span class="stage-marker" aria-hidden="true"></span><span class="stage-name">${s.label}</span><span class="stage-seq">${stageSeqLabel(s)}</span></button></li>`).join("");
    $$(".stage-button").forEach(btn => btn.addEventListener("click", () => { stopReplay(); setStage(Number(btn.dataset.stage)); }));
    updateProgress();
  }

  function eventsFor(stage) {
    const nums = new Set(stage.event_sequences);
    return data.events.filter(event => nums.has(event.seq));
  }

  function renderStage(index) {
    activeStage = Math.max(0, Math.min(index, data.stages.length - 1));
    const stage = data.stages[activeStage];
    $$(".stage-button").forEach((btn, i) => btn.setAttribute("aria-current", i === activeStage ? "step" : "false"));
    $("#activeBeat").textContent = String(activeStage + 1).padStart(2, "0");
    $("#stageDetail").innerHTML = `
      <div class="stage-info"><div class="stage-meta">${stageSeqLabel(stage)} · ${stage.time}</div><h3>${stage.title}</h3><p>${stage.summary}</p></div>
      <div class="stage-facts">${stage.facts.map(f => `<div class="fact-row"><span class="fact-dot"></span><span>${f}</span></div>`).join("")}</div>
      <div class="event-trail" aria-label="Events in this phase">${eventsFor(stage).map(e => `<span class="event-chip"><b>#${e.seq}</b> ${actorLabel(e.actor)} · ${e.type}</span>`).join("") || `<span class="event-chip">Published export · ${niceTime(data.run.exported_at_utc)} UTC</span>`}</div>`;
    updateProgress();
    if (!playing) $("#replayStatus").textContent = `Stage ${activeStage + 1} of ${data.stages.length} · ${stage.label} · recorded replay`;
  }

  function setStage(index) { renderStage(index); }

  function updateProgress() {
    const progress = data ? (activeStage / Math.max(1, data.stages.length - 1)) * 100 : 0;
    $("#timelineProgress").style.width = `${progress}%`;
  }

  function startReplay() {
    if (playing) { stopReplay(); return; }
    if (activeStage >= data.stages.length - 1) setStage(0);
    playing = true;
    $("#replayToggle").classList.add("is-playing");
    $("#replayToggle").setAttribute("aria-pressed", "true");
    $("#replayToggle").innerHTML = '<span aria-hidden="true">Ⅱ</span><span>Pause replay</span>';
    $("#replayStatus").textContent = "Playing annotated stages from the recorded event order · visual pacing only.";
    timer = window.setInterval(() => {
      if (activeStage + 1 >= data.stages.length) { stopReplay(); $("#replayStatus").textContent = "Replay complete · all displayed values remain from the exported run."; return; }
      renderStage(activeStage + 1);
    }, 2350);
  }

  function stopReplay() {
    if (timer !== null) window.clearInterval(timer);
    timer = null; playing = false;
    const btn = $("#replayToggle");
    if (!btn) return;
    btn.classList.remove("is-playing"); btn.setAttribute("aria-pressed", "false");
    btn.innerHTML = '<span class="play-glyph" aria-hidden="true">▶</span><span>Replay verified run</span>';
  }

  function setCohort(next) {
    cohort = next;
    $$(".cohort-choice").forEach(btn => btn.setAttribute("aria-pressed", String(btn.dataset.cohort === cohort)));
    renderResults();
  }

  function setThreshold(next) {
    threshold = next;
    $$(".threshold-choice").forEach(btn => { const active = btn.dataset.threshold === threshold; btn.classList.toggle("is-active", active); btn.setAttribute("aria-pressed", String(active)); });
    renderResults();
  }

  function signed(value) { const n = Number(value); return `${n > 0 ? "+" : ""}${value}`; }
  function displayPp(value) { const n = Number(value); return `${n > 0 ? "+" : ""}${n.toFixed(5)}`; }

  function drawCI(result) {
    const lo = Number(result.ci95_pp[0]), hi = Number(result.ci95_pp[1]), point = Number(result.delta_pp);
    const span = Math.max(hi, 0) - Math.min(lo, 0) || 1;
    const pad = span * .13;
    const min = Math.min(lo, 0) - pad, max = Math.max(hi, 0) + pad;
    const x = value => Math.max(0, Math.min(100, 100 * (value - min) / (max - min)));
    const zeroX = x(0), pointX = x(point), left = x(lo), right = x(hi);
    const start = min.toFixed(3), end = max.toFixed(3);
    return `<div class="ci-panel">
      <div class="ci-copy"><strong>95% resampling interval</strong><span>Difference in passing rates · percentage points</span></div>
      <div class="ci-chart" role="img" aria-label="95 percent interval from ${signed(result.ci95_pp[0])} to ${signed(result.ci95_pp[1])} percentage points. Point estimate ${signed(result.delta_pp)}. ${result.ci_crosses_zero ? "Interval crosses zero." : "Interval is above zero."}">
        <div class="ci-track" style="--ci-left:${left}%;--ci-width:${right-left}%;--ci-zero:${zeroX}%;--ci-point:${pointX}%"><span class="ci-bar"></span><span class="ci-zero"></span><span class="ci-point"></span></div>
        <div class="ci-axis"><span>${start}</span><span>${end}</span></div>
        <div class="ci-zero-note ${result.ci_crosses_zero ? "crosses" : ""}">${result.ci_crosses_zero ? "interval crosses zero" : "interval above zero"}</div>
      </div>
    </div>`;
  }

  function renderResults() {
    const result = data.thresholds[threshold][cohort];
    const isHoldout = cohort === "holdout";
    const o = result.oxide, c = result.chalcogenide;
    const status = isHoldout ? result.status : result.status;
    const statusClass = isHoldout ? "status-pill inconclusive" : "status-pill";
    const subStatus = isHoldout ? `Scientific status: ${result.scientific_status}` : "Observed Result · discovery snapshot";
    $("#resultView").innerHTML = `
      <div class="result-topline"><div><div class="result-title">${isHoldout ? "Controlled holdout" : "Primary discovery"}</div><div class="threshold-tag">ehull ≤ ${threshold} eV/atom · ${isHoldout ? "frozen cohort" : "discovery cohort"}</div></div><span class="${statusClass}">${status}</span></div>
      <div class="metric-grid">
        <div class="metric-card"><div class="metric-label">Oxides · pass / observed</div><div class="metric-main">${o.passes} / ${fmtCount(o.observed)}</div><div class="metric-sub">100% recorded field coverage</div></div>
        <div class="metric-card"><div class="metric-label">Chalcogenides · pass / observed</div><div class="metric-main">${c.passes} / ${fmtCount(c.observed)}</div><div class="metric-sub">100% recorded field coverage</div></div>
        <div class="metric-card delta-card"><div class="metric-label">Chalcogenide − oxide · observed difference</div><div class="metric-main">${displayPp(result.delta_pp)}</div><div class="metric-sub">percentage points ·${" " + subStatus}</div></div>
        <div class="metric-card interval-card"><div class="metric-label">95% interval · percentage points</div><div class="metric-main">[${displayPp(result.ci95_pp[0])}, ${displayPp(result.ci95_pp[1])}]</div><div class="metric-sub">${isHoldout ? "Direction consistent; replication inconclusive" : "Stored as supported_in_snapshot"}</div></div>
      </div>${drawCI(result)}`;
  }

  function renderChoices() {
    $("#optionList").innerHTML = data.choices.map((choice, i) => `<div class="option-card ${choice.selected ? "selected" : ""}"><span class="option-icon" aria-hidden="true">${choice.selected ? "✓" : ["↗","◇"][Math.max(0,i-1)]}</span><span><strong>${choice.name}</strong><p>${choice.note}</p></span><span class="option-status">${choice.status}</span></div>`).join("");
  }

  function renderRoles() {
    $("#roleList").innerHTML = data.roles.map(role => `<button class="role-button" type="button" data-role="${role.id}" aria-pressed="${role.id===activeRole}">${role.label}</button>`).join("");
    $$(".role-button").forEach(btn => btn.addEventListener("click", () => { activeRole = btn.dataset.role; renderRoleDetail(); }));
    renderRoleDetail();
  }

  function renderRoleDetail() {
    $$(".role-button").forEach(btn => btn.setAttribute("aria-pressed", String(btn.dataset.role === activeRole)));
    const role = data.roles.find(item => item.id === activeRole);
    const events = data.events.filter(event => event.actor === activeRole);
    $("#roleDetail").innerHTML = `<h3>${role.label} <span class="soft-inline">· ${events.length} recorded events</span></h3><p>${role.description}</p><div class="role-event-list">${events.map(e => `<span>#${e.seq} ${e.type}</span>`).join("")}</div>`;
  }

  function renderEvidence() {
    const lineages = [
      ["Primary discovery · Result 1", data.lineage.primary_discovery],
      ["Threshold follow-up · Result 2", data.lineage.threshold_followup],
      ["Frozen protocol", data.lineage.frozen_protocol],
      ["Controlled holdout · Result 3", data.lineage.holdout]
    ];
    $("#lineageView").innerHTML = `<div class="lineage-grid">${lineages.map(([title, record]) => `<section class="lineage-card"><h3>${title}</h3>${Object.entries(record).map(([key,value]) => `<div class="lineage-row"><label>${key.replaceAll("_"," ")}</label><div class="hash-value"><span>${value}</span>${String(value).length > 32 ? `<button class="copy-button" type="button" data-copy="${value}" aria-label="Copy ${key.replaceAll("_"," ")}">Copy</button>` : ""}</div></div>`).join("")}</section>`).join("")}</div>`;
    $("#sourceList").innerHTML = data.sources.map(source => `<div class="source-row"><code>${source.path}</code><span>SHA-256 · ${source.sha256}</span></div>`).join("");
    $("#boundaryList").innerHTML = data.boundaries.map(note => `<li>${note}</li>`).join("");
    $$(".copy-button").forEach(button => button.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(button.dataset.copy); button.textContent = "Copied"; }
      catch { button.textContent = "Select ID"; }
      window.setTimeout(() => { button.textContent = "Copy"; }, 1200);
    }));
  }

  function wireControls() {
    $("#replayToggle").addEventListener("click", startReplay);
    $("#heroReplay").addEventListener("click", () => { $("#replay").scrollIntoView({ behavior: "smooth", block: "start" }); if (!playing) startReplay(); });
    $("#replayRestart").addEventListener("click", () => { stopReplay(); setStage(0); $("#replayStatus").textContent = "Replay reset · ready at event 1."; });
    $$(".cohort-choice").forEach(btn => btn.addEventListener("click", () => setCohort(btn.dataset.cohort)));
    $$(".threshold-choice").forEach(btn => btn.addEventListener("click", () => setThreshold(btn.dataset.threshold)));
    const dialog = $("#evidenceDialog");
    const open = () => { if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", ""); };
    const close = () => { if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open"); };
    ["#openEvidenceTop", "#openEvidenceHero", "#openEvidenceBottom"].forEach(id => $(id).addEventListener("click", open));
    ["#closeEvidence", "#closeEvidenceBottom"].forEach(id => $(id).addEventListener("click", close));
    dialog.addEventListener("click", event => { if (event.target === dialog) close(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape" && dialog.open) close(); });
  }

  function startAmbient() {
    const canvas = $("#ambient"), ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, points = [], raf = 0;
    const resize = () => {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      w = window.innerWidth; h = window.innerHeight;
      canvas.width = Math.floor(w*dpr); canvas.height = Math.floor(h*dpr); canvas.style.width = `${w}px`; canvas.style.height = `${h}px`; ctx.setTransform(dpr,0,0,dpr,0,0);
      const count = Math.min(46, Math.max(20, Math.floor((w*h)/43000)));
      points = Array.from({length:count}, (_,i) => ({x:(i*97.13%w), y:(i*167.9%h), dx:((i%3)-1)*.045, dy:((i%5)-2)*.035, phase:i*.9}));
      paint(0);
    };
    const paint = time => {
      raf = 0;
      ctx.clearRect(0,0,w,h);
      for (let i=0;i<points.length;i++) {
        const p=points[i];
        if (!reduceMotion) { p.x += p.dx; p.y += p.dy; if(p.x<0||p.x>w)p.dx*=-1; if(p.y<0||p.y>h)p.dy*=-1; }
        for(let j=i+1;j<points.length;j++) { const q=points[j],dx=p.x-q.x,dy=p.y-q.y,d=Math.hypot(dx,dy); if(d<145){ctx.strokeStyle=`rgba(64,190,201,${(1-d/145)*.075})`;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();} }
        ctx.fillStyle = `rgba(99,196,211,${.11 + .08*Math.sin(time*.0004+p.phase)})`;ctx.beginPath();ctx.arc(p.x,p.y,1.2,0,Math.PI*2);ctx.fill();
      }
      if (!reduceMotion) raf=requestAnimationFrame(paint);
    };
    window.addEventListener("resize", resize, {passive:true}); resize();
    window.addEventListener("pagehide", () => { if(raf)cancelAnimationFrame(raf); }, {once:true});
  }

  fetch("./data.json", { cache: "no-store" }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }).then(init).catch(fail);
})();
