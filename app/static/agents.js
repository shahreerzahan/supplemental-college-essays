/* The Unwritten Shelf: "Ask the shelf" (the Librarian) and "Build my Story Map" (the Essay Coach).
   Uses window.Shelf from shelf.js to open books and light them up. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const STORY_COLORS = ["#4395D5", "#EE7D3F", "#8A5A96", "#255A55", "#B25045"];
  const STORY_HINTS = [
    "e.g. Rebuilt my grandfather's radio", "e.g. Started a library tutoring program",
    "e.g. Translating for my family at appointments", "e.g. Lost the debate final", "e.g. Summer job at a bakery",
  ];
  const WAIT_LINES = [
    "Asking the Librarian for your schools' prompts…", "Matching your stories to each prompt…",
    "Checking that every required prompt is covered…", "Looking for stories that can do double duty…",
  ];
  let S;  // window.Shelf

  async function post(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let data = null;
    try { data = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) {
      const d = data?.detail;
      const msg = typeof d === "string" ? d
        : Array.isArray(d) ? d.map((x) => String(x.msg).replace(/^Value error, /, "")).join(" ")
        : `Something went wrong (${res.status}).`;
      throw new Error(msg);
    }
    return data;
  }

  const sources = (list) => list.length
    ? `<p class="answer-sources">Sources: ${list.map((s) => S.safeUrl(s.url)
        ? `<a href="${S.esc(s.url)}" target="_blank" rel="noopener noreferrer">${S.esc(s.label)} ↗</a>` : "").join(" ")}</p>`
    : "";

  const missing = (names) => names.length
    ? `<p class="answer-missing">Not on the shelf: ${S.esc(names.join(", "))}. Check ${names.length > 1 ? "their" : "its"} prompts on ${names.length > 1 ? "their" : "its"} own admissions site.</p>`
    : "";

  // ---------- Ask the shelf ----------

  function renderAnswer(a) {
    const panel = $("answer");
    const books = a.prompt_ids.map((id) => S.item(id)).filter(Boolean);
    panel.innerHTML =
      `<div class="answer-head"><span class="answer-who">The Librarian</span>` +
      `<button class="inline-link" type="button" data-act="clear-answer">Clear</button></div>` +
      `<p class="answer-text">${S.esc(a.answer)}</p>` + missing(a.not_on_shelf) +
      (books.length
        ? `<div class="answer-books">${books.map((it) =>
            `<button class="book-chip" type="button" data-open="${S.esc(it.id)}"><i class="mini-spine" style="--c:${it.t.color}"></i>` +
            `${S.esc(it.short)} · ${S.esc(it.t.label)} · ${S.esc(S.limitText(it.p))}</button>`).join("")}</div>` +
          `<button class="inline-link see-lit" type="button" data-act="show-lit">See ${books.length === 1 ? "it" : `all ${books.length}`} on the shelf ↓</button>`
        : "") +
      sources(a.sources) + S.meter(a.usage);
    panel.hidden = false;
  }

  function bindAsk() {
    const input = $("ask-input"), btn = $("ask-btn"), panel = $("answer");
    $("ask-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const question = input.value.trim();
      if (question.length < 3) return;
      btn.disabled = true;
      btn.textContent = "Asking…";
      panel.hidden = false;
      panel.innerHTML = `<p class="agent-wait">The Librarian is searching the shelf…</p>`;
      try {
        const a = await post("/api/ask", { question, lean: S.isLean() });
        S.light(a.prompt_ids);
        renderAnswer(a);
      } catch (err) {
        panel.innerHTML = `<p class="agent-wait">${S.esc(err.message)}</p>`;
      } finally {
        btn.disabled = false;
        btn.textContent = "Ask";
      }
    });
    panel.addEventListener("click", (e) => {
      const open = e.target.closest("[data-open]");
      if (open) return S.open(open.dataset.open);
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "clear-answer") { panel.hidden = true; S.light(null); }
      else if (act === "show-lit") S.showLit();
    });
    // Clearing the lit books from the status line also clears the answer.
    document.addEventListener("shelf:lit", (e) => { if (!e.detail.lit && panel.querySelector(".answer-text")) panel.hidden = true; });
  }

  // ---------- Build my Story Map ----------

  const storyChip = (k) =>
    `<span class="story-chip" style="--c:${STORY_COLORS[k - 1]};--chip-ink:${S.inkFor(STORY_COLORS[k - 1])}">Story ${k}</span>`;

  function renumberStories() {
    const items = [...$("story-list").children];
    items.forEach((li, i) => {
      const dot = li.querySelector(".story-dot");
      dot.textContent = i + 1;
      dot.style.setProperty("--c", STORY_COLORS[i]);
      dot.style.setProperty("--chip-ink", S.inkFor(STORY_COLORS[i]));
      li.querySelector("input").setAttribute("aria-label", `Story ${i + 1}`);
    });
    $("add-story").hidden = items.length >= 5;
  }

  function addStory(focus) {
    const list = $("story-list");
    const n = list.children.length;
    if (n >= 5) return;
    const li = document.createElement("li");
    li.innerHTML =
      `<i class="story-dot" aria-hidden="true"></i>` +
      `<input class="field" type="text" maxlength="160" placeholder="${S.esc(STORY_HINTS[n])}">` +
      (n >= 3 ? `<button class="story-remove" type="button" data-remove aria-label="Remove this story">×</button>` : "");
    list.append(li);
    renumberStories();
    if (focus) li.querySelector("input").focus();
  }

  const isShort = (r) => r.story == null && (r.type === "short take" || (r.limit_words != null && r.limit_words <= 60));

  function mapRow(r) {
    const type = S.TYPE[r.type] || S.TYPE.essay;
    const need = !r.required ? "Optional" : r.choice ? r.choice.replace(/\s*\(group [^)]+\)/, "") : "Required";
    const label = r.story != null
      ? `${storyChip(r.story)}<span class="fit">${S.esc(r.fit || "")} fit</span>`
      : isShort(r) ? `<span class="short-chip">Short answer</span>` : `<span class="gap-chip">Gap: no story yet</span>`;
    const src = S.safeUrl(r.source_url);
    return `<article class="map-row">` +
      `<div class="map-prompt"><button class="map-spine" type="button" data-open="${S.esc(r.prompt_id)}" aria-label="Open this prompt" style="--c:${type.color}"></button>` +
      `<div><p class="map-meta">${S.esc(type.label)} · ${S.esc(r.limit)} · ${S.esc(need)}</p>` +
      `<p class="map-text">${S.esc(r.prompt)}</p>` +
      `<p class="map-links"><button class="inline-link" type="button" data-open="${S.esc(r.prompt_id)}">Open the book</button>` +
      (src ? ` · <a href="${S.esc(src)}" target="_blank" rel="noopener noreferrer">${S.esc(S.domain(src))} ↗</a>` : "") + `</p></div></div>` +
      `<div class="map-fit"><div class="map-label">${label}</div>` +
      `<p class="map-why">${S.esc(r.why)}</p><p class="map-coach"><b>Coach:</b> ${S.esc(r.coaching)}</p></div>` +
      `</article>`;
  }

  function renderMap(m) {
    const out = $("map-result");
    if (!m.rows.length) {
      out.innerHTML = `<div class="map-card">${missing(m.not_on_shelf)}<p>None of these schools are on the shelf yet, so there's nothing to map.</p></div>`;
      return;
    }
    const uses = (k) => m.rows.filter((r) => r.story === k).length;
    const stats = [
      [m.rows.length, m.rows.length === 1 ? "prompt to write" : "prompts to write"],
      [`≈${m.total_words.toLocaleString()}`, "words in total"],
      [m.shared.length, m.shared.length === 1 ? "story doing double duty" : "stories doing double duty"],
      [m.gaps, m.gaps === 1 ? "gap to fill" : "gaps to fill"],
    ];
    const bySchool = new Map();
    for (const r of m.rows) bySchool.set(r.school_name, [...(bySchool.get(r.school_name) || []), r]);
    const short = (id) => { const it = S.item(id); return it ? `${it.short} · ${it.t.label}` : id; };

    out.innerHTML = `<div class="map-card">` +
      `<div class="map-head"><h3 class="map-title">Your Story Map</h3>` +
      `<button class="btn primary" type="button" data-act="light-map">Light these up on the shelf</button></div>` +
      `<div class="map-stats">${stats.map(([n, l]) => `<div><b>${S.esc(String(n))}</b><span>${S.esc(l)}</span></div>`).join("")}</div>` +
      `<p class="map-note">${S.esc(m.total_note)}</p>` + S.meter(m.usage) + missing(m.not_on_shelf) +
      `<h4 class="label">Your stories</h4><ol class="map-legend">${m.stories.map((s, i) =>
        `<li>${storyChip(i + 1)}<span>${S.esc(s)}</span><small>${uses(i + 1) ? `${uses(i + 1)} prompt${uses(i + 1) > 1 ? "s" : ""}` : "not used yet"}</small></li>`).join("")}</ol>` +
      [...bySchool].map(([school, rows]) => `<h4 class="map-school">${S.esc(school)}</h4>${rows.map(mapRow).join("")}`).join("") +
      (m.shared.length ? `<h4 class="label">Stories doing double duty</h4><ul class="map-shared">${m.shared.map((s) =>
        `<li>${storyChip(s.story)}<div><p class="map-meta">${s.prompt_ids.map((id) => S.esc(short(id))).join(" · ")}</p>` +
        `<p>${S.esc(s.how_to_vary)}</p></div></li>`).join("")}</ul>` : "") +
      (m.advice.length ? `<h4 class="label">Next steps</h4><ol class="map-advice">${m.advice.map((a) => `<li>${S.esc(a)}</li>`).join("")}</ol>` : "") +
      `<p class="map-foot">Prompts and limits come from the shelf's data; each one links to its source. The coach suggests angles and questions. The writing is yours.</p>` +
      `</div>`;
    out.dataset.ids = JSON.stringify(m.rows.map((r) => r.prompt_id));
  }

  function bindMap() {
    $("map-schools").innerHTML = S.schools()
      .map((s) => `<button class="chip" type="button" data-key="${S.esc(s.key)}" aria-pressed="false">${S.esc(s.short)}</button>`).join("");
    $("map-schools").addEventListener("click", (e) => {
      const c = e.target.closest(".chip");
      if (c) c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true"));
    });
    for (let i = 0; i < 3; i++) addStory(false);
    $("add-story").addEventListener("click", () => addStory(true));
    $("story-list").addEventListener("click", (e) => {
      const rm = e.target.closest("[data-remove]");
      if (rm) { rm.closest("li").remove(); renumberStories(); }
    });

    $("map-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = $("map-error"), btn = $("map-btn"), out = $("map-result");
      const schools = [...$("map-schools").querySelectorAll('[aria-pressed="true"]')].map((c) => c.dataset.key)
        .concat($("map-other").value.split(",").map((s) => s.trim()).filter(Boolean));
      const stories = [...$("story-list").querySelectorAll("input")].map((i) => i.value.trim()).filter(Boolean);
      err.textContent = !schools.length ? "Pick at least one school."
        : stories.length < 3 ? "Add at least 3 stories, a few words each." : "";
      if (err.textContent) return;

      btn.disabled = true;
      btn.textContent = "Mapping…";
      let line = 0;
      out.innerHTML = `<div class="map-card"><p class="agent-wait" id="map-wait">${WAIT_LINES[0]}</p></div>`;
      const timer = setInterval(() => {
        const w = $("map-wait");
        if (w) w.textContent = WAIT_LINES[++line % WAIT_LINES.length];
      }, 3500);
      try {
        const m = await post("/api/story-map", {
          schools, stories, applying_to: $("map-applying").value.trim() || null, lean: S.isLean(),
        });
        renderMap(m);
        out.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        out.innerHTML = `<div class="map-card"><p class="agent-wait">${S.esc(error.message)}</p></div>`;
      } finally {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = "Build my Story Map";
      }
    });

    $("map-result").addEventListener("click", (e) => {
      const open = e.target.closest("[data-open]");
      if (open) return S.open(open.dataset.open);
      if (e.target.closest('[data-act="light-map"]')) {
        S.light(JSON.parse($("map-result").dataset.ids || "[]"));
        S.showLit();
      }
    });
  }

  function showLean() {
    $("map-lean-note").textContent = S.isLean() ? "Lean mode is on (switch at the top of the page)." : "";
  }

  function start() {
    S = window.Shelf;
    bindAsk();
    bindMap();
    showLean();
    document.addEventListener("shelf:lean", showLean);
  }

  if (window.Shelf) start();
  else document.addEventListener("shelf:ready", start, { once: true });
})();
