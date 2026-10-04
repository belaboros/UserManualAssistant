"use strict";
(function () {
  const MODE_KEY = "uma-leaderboard-mode";
  const MODES = ["all", "blind", "labelled"];
  const $ = (id) => document.getElementById(id);
  const DASH = "–";

  function lsGet(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function lsSet(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* ignore */ } }

  function el(tag, text, attrs) {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = text;
    if (attrs) for (const k of Object.keys(attrs)) n.setAttribute(k, attrs[k]);
    return n;
  }

  function showError(msg) {
    const p = $("lb-error");
    p.textContent = msg || "";
    p.hidden = !msg;
  }

  async function getJson(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " returned " + r.status);
    return r.json();
  }

  const isNone = (v) => v === null || v === undefined;
  const fmt = (v, digits) => (isNone(v) ? DASH : Number(v).toFixed(digits));

  function distributionCell(dist, strategyTitle) {
    // JSON object keys arrive as strings "1".."5".
    const counts = [1, 2, 3, 4, 5].map((s) => Number((dist || {})[String(s)] || 0));
    const total = counts.reduce((a, b) => a + b, 0);
    const bar = el("div", null, { class: "dist-bar", role: "group",
      "aria-label": strategyTitle + " star distribution" });
    counts.forEach((n, i) => {
      const stars = i + 1;
      const seg = el("span", n > 0 ? String(n) : "", { class: "dist-seg dist-" + stars,
        role: "img",
        "aria-label": stars + (stars === 1 ? " star: " : " stars: ") + n + (n === 1 ? " vote" : " votes"),
        title: stars + "★: " + n });
      seg.style.width = total ? (100 * n / total) + "%" : "0";
      if (n === 0) seg.hidden = true;
      bar.appendChild(seg);
    });
    if (!total) bar.appendChild(el("span", DASH, { class: "dist-empty" }));
    return bar;
  }

  function renderLeaderboard(rows) {
    const body = $("leaderboard-table").tBodies[0];
    body.replaceChildren();
    if (!rows.length) {
      const tr = el("tr");
      tr.appendChild(el("td", "No strategies.", { colspan: "10" }));
      body.appendChild(tr);
      return;
    }
    rows.forEach((r, i) => {
      const tr = el("tr");
      tr.appendChild(el("td", String(i + 1)));
      tr.appendChild(el("th", r.title, { scope: "row" }));
      tr.appendChild(el("td", fmt(r.avg_stars, 1)));
      tr.appendChild(el("td", String(r.votes)));
      const d = el("td");
      d.appendChild(distributionCell(r.distribution, r.title));
      tr.appendChild(d);
      tr.appendChild(el("td", String(r.wins)));
      tr.appendChild(el("td", isNone(r.avg_latency_ms) ? DASH : (r.avg_latency_ms / 1000).toFixed(1)));
      tr.appendChild(el("td", fmt(r.avg_cost_usd, 4)));
      tr.appendChild(el("td", isNone(r.not_covered_rate) ? DASH : (r.not_covered_rate * 100).toFixed(0)));
      tr.appendChild(el("td", String(r.errors)));
      body.appendChild(tr);
    });
  }

  function renderRecent(recent, strategies) {
    const table = $("recent-table");
    const head = el("tr");
    head.appendChild(el("th", "Question", { scope: "col" }));
    strategies.forEach((s) => head.appendChild(el("th", s.title, { scope: "col" })));
    head.appendChild(el("th", "Spread", { scope: "col" }));
    table.tHead.replaceChildren(head);
    const body = table.tBodies[0];
    body.replaceChildren();
    if (!recent.length) {
      const tr = el("tr");
      tr.appendChild(el("td", "No rated questions yet.", { colspan: String(strategies.length + 2) }));
      body.appendChild(tr);
      return;
    }
    recent.forEach((q) => {
      const tr = el("tr");
      tr.appendChild(el("td", q.text, { class: "q-text" }));
      strategies.forEach((s) => {
        const v = (q.ratings || {})[s.id];
        tr.appendChild(el("td", isNone(v) ? DASH : String(v)));
      });
      tr.appendChild(el("td", String(q.spread)));
      body.appendChild(tr);
    });
  }

  let loadSeq = 0;
  async function load() {
    const seq = ++loadSeq;
    const mode = $("mode-filter").value;
    try {
      const [strategies, data] = await Promise.all([
        getJson("/api/strategies"),
        getJson("/api/leaderboard?mode=" + encodeURIComponent(mode)),
      ]);
      if (seq !== loadSeq) return;
      renderLeaderboard(data.rows);
      renderRecent(data.recent, strategies);
      showError("");
    } catch (e) {
      if (seq === loadSeq) showError("Could not load the leaderboard: " + e.message);
    }
  }

  async function reset() {
    if (!window.confirm("Delete all votes? This cannot be undone.")) return;
    try {
      const r = await fetch("/api/reset-votes", { method: "POST" });
      if (!r.ok) throw new Error("reset returned " + r.status);
    } catch (e) {
      showError("Could not reset votes: " + e.message);
      return;
    }
    load();
  }

  const select = $("mode-filter");
  const saved = lsGet(MODE_KEY);
  if (MODES.indexOf(saved) >= 0) select.value = saved;
  select.addEventListener("change", () => { lsSet(MODE_KEY, select.value); load(); });
  $("reset-votes").addEventListener("click", reset);
  load();
})();
