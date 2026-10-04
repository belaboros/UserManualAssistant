"use strict";
(function () {
  const MODE_KEY = "uma-mode";
  // Blind labels end at Z: three columns are X/Y/Z, four are W/X/Y/Z.
  function blindLabel(i, n) {
    return "Answer " + String.fromCharCode("Z".charCodeAt(0) - (n - 1) + i);
  }
  const STATUS_TEXT = {
    answered: "✓ answered",
    not_covered: "not covered",
    contradiction_found: "⚠ contradiction found",
  };

  const $ = (sel, root) => (root || document).querySelector(sel);
  const form = $("#question-form");
  const input = $("#question-input");
  const modeToggle = $("#mode-toggle");
  const columnsEl = $("#columns");
  const warning = $("#corpus-warning");
  const questionError = $("#question-error");
  const askButton = $("#ask-button");
  const panel = $("#citation-panel");
  const dialog = $("#how-dialog");

  const state = {
    mode: "labelled",
    strategies: [], // from /api/strategies, in display order
    byId: {},
    question: null, // {id, blind, es, done, finished, rated, revealed}
    panelSeq: 0,
  };

  const columns = {};
  columnsEl.querySelectorAll(".column").forEach((el) => {
    columns[el.dataset.strategy] = el;
  });

  // ---- helpers ----
  function lsGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function lsSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }
  function show(el, on) { el.hidden = !on; }

  async function errorText(resp) {
    try {
      const body = await resp.json();
      if (body && typeof body.detail === "string") return body.detail;
      if (body && body.detail) return JSON.stringify(body.detail);
    } catch (e) { /* not json */ }
    return "Request failed (" + resp.status + ")";
  }

  // Markdown -> sanitized HTML string.
  function renderMarkdown(text) {
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      // Libraries failed to load: fall back to escaped plain text (never raw HTML).
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }
    return DOMPurify.sanitize(marked.parse(text));
  }

  // Replace [n] in text nodes of already-sanitized HTML with citation buttons.
  function linkCitations(html, citations, onClick) {
    const tpl = document.createElement("template");
    tpl.innerHTML = html; // html was sanitized by renderMarkdown
    const walker = document.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (node.parentElement && node.parentElement.closest("code, pre, a, button")) continue;
      const text = node.nodeValue;
      if (!/\[\d+\]/.test(text)) continue;
      const frag = document.createDocumentFragment();
      let last = 0;
      for (const m of text.matchAll(/\[(\d+)\]/g)) {
        const n = Number(m[1]);
        const cit = citations[n - 1];
        if (!cit) continue;
        frag.append(text.slice(last, m.index));
        const b = document.createElement("button");
        b.type = "button";
        b.className = "cite";
        b.textContent = "[" + n + "]";
        b.title = cit.manual_title + " › " + (cit.heading_path || []).join(" › ");
        b.addEventListener("click", () => onClick(cit.section_id, b));
        frag.append(b);
        last = m.index + m[0].length;
      }
      frag.append(text.slice(last));
      node.replaceWith(frag);
    }
    return tpl.content;
  }

  // ---- mode & ordering ----
  function titleOf(id) { return state.byId[id] ? state.byId[id].title : id; }

  function applyMode() {
    modeToggle.textContent = "Mode: " + state.mode;
    modeToggle.setAttribute("aria-pressed", String(state.mode === "blind"));
  }

  function shuffle(arr) { // Fisher-Yates
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function layoutColumns(blind) {
    const ids = state.strategies.map((s) => s.id).filter((id) => columns[id]);
    const order = blind ? shuffle(ids) : ids;
    // Blind mode keeps the maximized SLOT (screen position), not the strategy: following the
    // id across a reshuffle would tell the viewer which strategy is now in the wide column.
    const maxCol = columns[columnsEl.dataset.maximized];
    const slot = maxCol ? Array.prototype.indexOf.call(columnsEl.children, maxCol) : -1;
    order.forEach((id, i) => {
      const col = columns[id];
      columnsEl.append(col); // moves the node into its new position
      col.dataset.label = blindLabel(i, order.length);
      const hidden = blind && !(state.question && state.question.revealed.has(id));
      $(".column-title", col).textContent = hidden ? col.dataset.label : titleOf(id);
      show($(".reveal", col), hidden && !!state.question);
      show($(".how-it-works", col), !hidden);
      col.classList.toggle("blind-hidden", hidden);
    });
    if (blind && slot >= 0) setMaximized(columnsEl.children[slot].dataset.strategy);
  }

  function reveal(id) {
    const q = state.question;
    if (!q) return;
    q.revealed.add(id);
    const col = columns[id];
    $(".column-title", col).textContent = col.dataset.label + " — " + titleOf(id);
    show($(".reveal", col), false);
    show($(".how-it-works", col), true);
    col.classList.remove("blind-hidden");
  }

  // ---- maximize / restore ----
  // #columns[data-maximized="<id>"] gives one column the remaining width and collapses the
  // others to narrow strips (CSS, >=700px only). Strips keep the on-screen (possibly shuffled)
  // order because the layout follows DOM order. Not persisted: a reload starts with equal widths.
  const wideQuery = window.matchMedia ? window.matchMedia("(min-width: 700px)") : null;
  const reducedMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  function isWide() { return !wideQuery || wideQuery.matches; }

  function setMaximized(id) {
    const target = id && columns[id] ? id : null;
    if (target) columnsEl.dataset.maximized = target;
    else delete columnsEl.dataset.maximized;
    for (const [cid, col] of Object.entries(columns)) {
      const on = cid === target;
      const title = $(".column-title", col);
      if (on) title.title = "Click to restore equal widths";
      else title.removeAttribute("title");
      col.classList.toggle("is-maximized", on);
      col.classList.toggle("is-collapsed", !!target && !on);
      const btn = $(".maximize", col);
      btn.setAttribute("aria-pressed", String(on));
      btn.setAttribute("aria-label", on ? "Restore equal widths" : "Maximize this column");
      btn.textContent = on ? "\u2921" : "\u2922"; // ⤡ restore, ⤢ maximize
    }
  }

  // Below 700px the columns stack; drop the state so no button shows a pressed "Restore".
  if (wideQuery) {
    const onWidth = () => { if (!wideQuery.matches) setMaximized(null); };
    if (wideQuery.addEventListener) wideQuery.addEventListener("change", onWidth);
    else if (wideQuery.addListener) wideQuery.addListener(onWidth);
  }

  function toggleMaximize(col) {
    if (!isWide()) { // stacked full width already: just bring the column into view
      const smooth = !(reducedMotion && reducedMotion.matches);
      col.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" });
      return;
    }
    const id = col.dataset.strategy;
    setMaximized(columnsEl.dataset.maximized === id ? null : id);
  }

  // ---- column state ----
  function resetColumn(col) {
    const answer = $(".answer", col);
    answer.textContent = "";
    answer.classList.add("streaming");
    answer.setAttribute("aria-busy", "true");
    const badge = $(".status-badge", col);
    badge.hidden = true;
    badge.textContent = "";
    delete badge.dataset.status;
    $(".metrics", col).textContent = "";
    const trace = $(".trace", col);
    trace.hidden = true;
    trace.open = false;
    $(".trace-list", col).textContent = "";
    const err = $(".vote-error", col);
    err.hidden = true;
    err.textContent = "";
    delete col.dataset.voting;
    delete col.dataset.placeholder;
    col.dataset.rating = "0";
    setStars(col, 0, true);
    if (isBlindHidden(col)) showPlaceholder(col);
  }

  function setStars(col, value, disabled) {
    col.querySelectorAll(".stars button").forEach((b) => {
      b.classList.toggle("on", Number(b.dataset.stars) <= value);
      b.setAttribute("aria-pressed", String(Number(b.dataset.stars) === value));
      b.disabled = disabled;
    });
  }

  function formatMetrics(m) {
    const secs = ((m.latency_ms || 0) / 1000).toFixed(1);
    const u = m.usage || {};
    const cost = typeof m.cost_usd === "number" ? "$" + m.cost_usd.toFixed(4) : "$—";
    const manuals = (m.manuals_used || []).join(", ") || "—";
    return secs + " s · " + (u.input_tokens || 0) + "/" + (u.output_tokens || 0) +
      " tok · " + cost + " · " + manuals;
  }

  // A blind column that is not yet revealed shows a neutral placeholder instead of the live
  // stream: intermediate narration and raw [§id] markers would give the strategy away.
  function isBlindHidden(col) {
    const q = state.question;
    return !!(q && q.blind && !q.revealed.has(col.dataset.strategy));
  }

  function showPlaceholder(col) {
    const answer = $(".answer", col);
    const p = document.createElement("p");
    p.className = "placeholder";
    p.textContent = "Answering…";
    answer.replaceChildren(p);
    col.dataset.placeholder = "1";
  }

  function onDelta(col, p) {
    if (isBlindHidden(col)) {
      if (!col.dataset.placeholder) showPlaceholder(col);
      return;
    }
    const answer = $(".answer", col);
    if (col.dataset.placeholder) { // revealed mid-stream: stream from here on
      answer.textContent = "";
      delete col.dataset.placeholder;
    }
    answer.append(document.createTextNode(p.text || ""));
  }

  function onTrace(col, p) {
    $(".trace", col).hidden = false;
    const li = document.createElement("li");
    let detail = "";
    try { detail = JSON.stringify(p.detail || {}); } catch (e) { /* ignore */ }
    li.textContent = p.kind + (detail && detail !== "{}" ? " " + detail : "");
    $(".trace-list", col).append(li);
  }

  function onFinal(col, p) {
    state.question.finished.add(col.dataset.strategy);
    const a = p.answer;
    const answerEl = $(".answer", col);
    answerEl.classList.remove("streaming");
    answerEl.removeAttribute("aria-busy");
    delete col.dataset.placeholder;
    // Replaces everything streamed so far (preamble, raw [§id] markers) or the placeholder.
    const html = renderMarkdown(a.text || "");
    answerEl.replaceChildren(linkCitations(html, a.citations || [], openSection));
    const badge = $(".status-badge", col);
    badge.textContent = STATUS_TEXT[a.status] || a.status;
    badge.dataset.status = a.status;
    badge.hidden = false;
    $(".metrics", col).textContent = formatMetrics(a.metrics || {});
    setStars(col, 0, false);
  }

  function onFailed(col, p) {
    state.question.finished.add(col.dataset.strategy);
    const answerEl = $(".answer", col);
    answerEl.classList.remove("streaming");
    answerEl.removeAttribute("aria-busy");
    delete col.dataset.placeholder;
    answerEl.textContent = ""; // drop any partial streamed text or the placeholder
    const msg = document.createElement("p");
    msg.className = "error";
    msg.textContent = p.message || "This strategy failed.";
    answerEl.append(msg);
    if (p.hint_doc) {
      const link = document.createElement("a");
      link.href = p.hint_doc;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "How to fix this";
      answerEl.append(link);
    }
    const badge = $(".status-badge", col);
    badge.textContent = "failed";
    badge.dataset.status = "failed";
    badge.hidden = false;
    setStars(col, 0, true);
  }

  // ---- streaming ----
  function finishStream(q, reason) {
    if (q.es) { q.es.close(); q.es = null; }
    if (reason) {
      for (const id of Object.keys(columns)) {
        if (!q.finished.has(id)) onFailed(columns[id], { message: reason, hint_doc: null });
      }
    }
    if (state.question === q) askButton.disabled = false;
  }

  function startStream(q) {
    const es = new EventSource("/api/questions/" + encodeURIComponent(q.id) + "/stream");
    q.es = es;
    es.onmessage = (ev) => {
      if (state.question !== q || q.es !== es) { es.close(); return; }
      let p;
      try { p = JSON.parse(ev.data); } catch (e) { return; }
      if (p.type === "done") { q.done = true; finishStream(q, null); return; }
      const col = columns[p.strategy];
      if (!col) return;
      if (p.type === "delta") onDelta(col, p);
      else if (p.type === "trace") onTrace(col, p);
      else if (p.type === "final") onFinal(col, p);
      else if (p.type === "failed") onFailed(col, p);
    };
    es.onerror = () => {
      // EventSource would auto-reconnect (and re-run or hit 409); never allow that.
      if (q.es !== es) { es.close(); return; }
      if (q.done) { finishStream(q, null); return; }
      finishStream(q, "Connection to the server was lost before this answer finished.");
    };
  }

  async function submit(ev) {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    questionError.hidden = true;
    askButton.disabled = true;
    const blind = state.mode === "blind";
    let resp;
    try {
      resp = await fetch("/api/questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, blind }),
      });
    } catch (e) {
      questionError.textContent = "Could not reach the server.";
      questionError.hidden = false;
      askButton.disabled = false;
      return;
    }
    if (!resp.ok) {
      questionError.textContent = await errorText(resp);
      questionError.hidden = false;
      askButton.disabled = false;
      return;
    }
    const { question_id } = await resp.json();
    if (state.question && state.question.es) state.question.es.close();
    const q = {
      id: question_id, blind, es: null, done: false,
      finished: new Set(), rated: new Set(), revealed: new Set(),
    };
    state.question = q;
    closePanel();
    layoutColumns(blind);
    Object.values(columns).forEach(resetColumn);
    startStream(q);
  }

  // ---- ratings ----
  async function rate(col, stars) {
    const q = state.question;
    if (!q) return;
    const id = col.dataset.strategy;
    const err = $(".vote-error", col);
    err.hidden = true;
    if (col.dataset.voting) return;
    col.dataset.voting = "1";
    const prev = Number(col.dataset.rating || 0);
    col.querySelectorAll(".stars button").forEach((b) => { b.disabled = true; });
    let ok = false;
    let msg = "";
    try {
      const resp = await fetch("/api/votes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: q.id, strategy: id, stars, blind: q.blind }),
      });
      ok = resp.ok;
      if (!ok) msg = await errorText(resp);
    } catch (e) {
      msg = "Could not reach the server.";
    }
    delete col.dataset.voting;
    if (state.question !== q) return; // a new question started meanwhile
    if (!ok) {
      err.textContent = "Rating not saved: " + msg;
      err.hidden = false;
      setStars(col, prev, false);
      return;
    }
    col.dataset.rating = String(stars);
    setStars(col, stars, false);
    q.rated.add(id);
    if (q.blind) reveal(id);
  }

  // ---- citation panel ----
  let panelOpener = null;
  function closePanel(restoreFocus) {
    panel.hidden = true;
    state.panelSeq++;
    const opener = panelOpener;
    panelOpener = null;
    if (restoreFocus === true && opener && opener.isConnected) {
      // The opener may sit in a column collapsed to a strip since: focus its strip button.
      const col = opener.closest(".column");
      if (opener.getClientRects().length === 0 && col) $(".maximize", col).focus();
      else opener.focus();
    }
  }

  async function openSection(sectionId, opener) {
    if (opener) panelOpener = opener;
    const seq = ++state.panelSeq;
    panel.hidden = false;
    $("#panel-title").textContent = "Loading…";
    $("#panel-path").textContent = "";
    $("#panel-body").textContent = "";
    show($("#panel-source"), false);
    try {
      const resp = await fetch("/api/sections/" + encodeURIComponent(sectionId));
      if (!resp.ok) throw new Error(await errorText(resp));
      const s = await resp.json();
      if (seq !== state.panelSeq) return;
      $("#panel-title").textContent = s.manual_title;
      $("#panel-path").textContent = (s.heading_path || []).join(" › ");
      $("#panel-body").innerHTML = renderMarkdown(s.text || "");
      if (s.source_url && /^https?:\/\//i.test(s.source_url)) {
        const link = $("#panel-source");
        link.href = s.source_url;
        link.hidden = false;
      }
      $("#panel-close").focus();
    } catch (e) {
      if (seq !== state.panelSeq) return;
      $("#panel-title").textContent = "Section unavailable";
      $("#panel-body").textContent = String(e.message || e);
    }
  }

  // ---- how it works ----
  let mermaidReady = false;
  let diagramCounter = 0;
  async function renderDiagram(url, box, title) {
    if (!url) throw new Error("not available");
    const resp = await fetch(url);
    if (!resp.ok) throw new Error("not available");
    const source = await resp.text();
    if (typeof mermaid === "undefined") throw new Error("mermaid not loaded");
    if (!mermaidReady) {
      const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      mermaid.initialize({ startOnLoad: false, theme: dark ? "dark" : "default" });
      mermaidReady = true;
    }
    const { svg } = await mermaid.render("uma-diagram-" + (++diagramCounter), source);
    const h = document.createElement("h3");
    h.textContent = title;
    const holder = document.createElement("div");
    holder.innerHTML = svg; // generated by mermaid (strict security level)
    box.append(h, holder);
  }

  async function openHowItWorks(id) {
    const s = state.byId[id];
    if (!s) return;
    $("#how-title").textContent = "How " + s.title + " works";
    const body = $("#how-body");
    body.textContent = "";
    $("#how-doc").href = s.doc;
    if (!dialog.open) dialog.showModal();
    let rendered = 0;
    for (const [url, title] of [[s.flow, "Flow"], [s.sequence, "Sequence"]]) {
      const box = document.createElement("div");
      body.append(box);
      try {
        await renderDiagram(url, box, title);
        rendered++;
      } catch (e) {
        box.remove();
      }
    }
    if (!rendered) {
      const p = document.createElement("p");
      p.textContent = "Diagram not available yet. ";
      const a = document.createElement("a");
      a.href = s.doc;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Read the written explanation instead.";
      p.append(a);
      body.append(p);
    }
  }

  // ---- wiring ----
  form.addEventListener("submit", submit);
  modeToggle.addEventListener("click", () => {
    state.mode = state.mode === "blind" ? "labelled" : "blind";
    lsSet(MODE_KEY, state.mode);
    applyMode();
    // Takes effect from the next question; before any question, update the layout now.
    if (!state.question) layoutColumns(state.mode === "blind");
  });
  columnsEl.addEventListener("click", (ev) => {
    const title = ev.target.closest(".column-title");
    if (title && title.closest(".column.is-maximized") && isWide()) { setMaximized(null); return; }
    const btn = ev.target.closest("button");
    if (!btn) return;
    const col = btn.closest(".column");
    if (!col) return;
    if (btn.dataset.stars) rate(col, Number(btn.dataset.stars));
    else if (btn.classList.contains("reveal")) reveal(col.dataset.strategy);
    else if (btn.classList.contains("how-it-works")) openHowItWorks(col.dataset.strategy);
    else if (btn.classList.contains("maximize")) toggleMaximize(col);
  });
  $("#panel-close").addEventListener("click", () => closePanel(true));
  $("#how-close").addEventListener("click", () => dialog.close());
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (dialog.open) return; // the dialog handles Escape itself; panel stays open beneath
    if (!panel.hidden) { closePanel(true); return; }
    if (columnsEl.dataset.maximized) setMaximized(null);
  });

  async function init() {
    state.mode = lsGet(MODE_KEY) === "blind" ? "blind" : "labelled";
    applyMode();
    try {
      const resp = await fetch("/api/strategies");
      if (!resp.ok) throw new Error("strategies");
      state.strategies = await resp.json();
    } catch (e) {
      state.strategies = Object.keys(columns).map((id) => ({
        id, title: $(".column-title", columns[id]).textContent, flow: "", sequence: "", doc: "",
      }));
    }
    state.byId = Object.fromEntries(state.strategies.map((s) => [s.id, s]));
    layoutColumns(state.mode === "blind");
    Object.values(columns).forEach((col) => setStars(col, 0, true));
    try {
      const resp = await fetch("/api/status");
      const status = await resp.json();
      show(warning, !status.corpus_ready);
    } catch (e) { /* leave warning hidden */ }
  }
  init();
})();
