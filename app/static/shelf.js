/* The Unwritten Shelf: draws data/shelf.json as books standing on shelves. */
(() => {
  "use strict";

  // Prompt types, in chip order, with their spine colors.
  const TYPES = [
    { key: "why us", slug: "why", label: "Why us", color: "#4395D5" },
    { key: "intellectual curiosity", slug: "curiosity", label: "Intellectual curiosity", color: "#8A5A96" },
    { key: "community", slug: "community", label: "Community", color: "#255A55" },
    { key: "activity", slug: "activity", label: "Activity", color: "#EE7D3F" },
    { key: "short take", slug: "short", label: "Short take", color: "#E1B965" },
    { key: "challenge", slug: "challenge", label: "Challenge", color: "#B25045" },
    { key: "UCAS", slug: "ucas", label: "UCAS", color: "#BEA9A1" },
    { key: "essay", slug: "essay", label: "Essays that worked", color: "#EAE4DA" },
  ];
  const TYPE = Object.fromEntries(TYPES.map((t) => [t.key, t]));

  // Short name and spine initials for each school.
  const SCHOOL = {
    yale: ["Yale", "YU"], harvard: ["Harvard", "HU"], princeton: ["Princeton", "PU"],
    stanford: ["Stanford", "SU"], mit: ["MIT", "MIT"], columbia: ["Columbia", "CU"],
    upenn: ["Penn", "UP"], brown: ["Brown", "BU"], dartmouth: ["Dartmouth", "DC"],
    cornell: ["Cornell", "COR"], duke: ["Duke", "DU"], jhu: ["Johns Hopkins", "JHU"],
    uchicago: ["UChicago", "UC"], northwestern: ["Northwestern", "NU"], caltech: ["Caltech", "CIT"],
    oxford: ["Oxford", "OX"], cambridge: ["Cambridge", "CAM"],
  };
  const PUBLISHER = {
    "Hamilton College": ["Hamilton", "HC"],
    "Connecticut College": ["Conn College", "CC"],
    "Tufts University": ["Tufts", "TU"],
    "College Essay Guy": ["College Essay Guy", "CEG"],
  };

  // Bauhaus cover palettes: background, then three shape colors.
  const COVER = {
    why: ["#4395D5", "#EAE4DA", "#282B2F", "#E1B965"],
    curiosity: ["#8A5A96", "#EAE4DA", "#282B2F", "#EE7D3F"],
    community: ["#255A55", "#EAE4DA", "#E1B965", "#B25045"],
    activity: ["#EE7D3F", "#EAE4DA", "#282B2F", "#4395D5"],
    short: ["#E1B965", "#282B2F", "#B25045", "#F4F8FD"],
    challenge: ["#B25045", "#EAE4DA", "#282B2F", "#E1B965"],
    ucas: ["#BEA9A1", "#282B2F", "#F4F8FD", "#255A55"],
    essay: ["#EAE4DA", "#B25045", "#282B2F", "#9DB8CC"],
  };

  const MARKS = ["circle", "half", "square", "bar", "ring", "none"];
  const GAP = 3;           // px between books (matches .shelf-books gap)
  const DIVIDER_W = 44;    // divider width plus margins
  const LEAN_DEG = 7;
  const HEADROOM = 46;     // px above the tallest book on a shelf, for hover and "Surprise me"

  const $ = (id) => document.getElementById(id);
  const bookcase = $("bookcase");
  const tip = $("tip");
  const backdrop = $("backdrop");
  const card = $("card");
  const search = $("search");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const state = { type: null, school: null, q: "", lit: null };  // lit: Set of ids the agents lit up
  let data, items = [], byId = new Map(), visible = [];
  let current = null, returnFocus = null, pulled = null, lastWidth = 0;

  // ---------- Helpers ----------

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const safeUrl = (u) => (/^https:\/\//.test(u || "") ? u : null);
  const domain = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function hash(s) {
    let h = 2166136261;
    for (const ch of s) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  function luminance(hex) {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const v = parseInt(hex.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  // White on dark colors, near-black on light ones: whichever reads better.
  const INK_DARK = "#1B1D20";
  function inkFor(hex) {
    const L = luminance(hex);
    return 1.05 / (L + 0.05) > (L + 0.05) / (luminance(INK_DARK) + 0.05) ? "#FFFFFF" : INK_DARK;
  }

  // Spine height follows the word limit (characters count as ~6 per word).
  function heightFor(limit) {
    const words = !limit ? 450 : limit.unit === "words" ? limit.max : limit.max / 6;
    const t = (Math.sqrt(clamp(words, 35, 650)) - Math.sqrt(35)) / (Math.sqrt(650) - Math.sqrt(35));
    return 118 + t * (330 - 118);
  }
  // Longer prompts make thicker books.
  const widthFor = (len) => clamp(30 + (Math.sqrt(len) - 4) * 1.25, 30, 58);

  // Spine title: the prompt's first short question, else its first sentence.
  function spineTitle(text) {
    const t = text.replace(/\s+/g, " ").trim();
    const sentences = (t.match(/[^.?!]+[.?!]+[”"’')]*/g) || [t]).map((s) => s.trim()).filter(Boolean);
    return sentences.find((s) => /\?[”"’')]*$/.test(s) && s.length <= 95) || sentences[0] || t;
  }

  // Split a title into spine lines; CSS ellipsizes whatever doesn't fit.
  function spineLines(text, capacity, lines) {
    if (lines === 1) return [text];
    const out = [];
    let cur = "";
    for (const word of text.split(" ")) {
      const next = cur ? `${cur} ${word}` : word;
      if (cur && out.length < lines - 1 && next.length > capacity) { out.push(cur); cur = word; }
      else cur = next;
    }
    out.push(cur);
    return out;
  }

  function limitText(p) {
    if (!p.limit) return "No stated limit";
    const { max, min, unit } = p.limit;
    const n = min ? `${min.toLocaleString()}–${max.toLocaleString()}` : max.toLocaleString();
    return `${n} ${unit}${p.type === "UCAS" ? ", shared" : ""}`;
  }

  // Notes cite sources as "[https://...]"; show those as small links.
  const fmtNotes = (s) => esc(s).replace(/\s*\[(https:\/\/[^\]\s]+)\]/g,
    (_, u) => ` <a class="note-link" href="${u}" target="_blank" rel="noopener noreferrer">${esc(domain(u.replace(/&amp;/g, "&")))} ↗</a>`);

  const fmtDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

  // ---------- Items ----------

  function buildItems() {
    const schoolByKey = new Map(data.schools.map((s) => [s.key, s]));
    const keyByName = new Map(data.schools.map((s) => [s.name, s.key]));
    const samplesFor = new Map();
    for (const s of data.sample_essays || []) {
      for (const id of s.prompt_ids) samplesFor.set(id, [...(samplesFor.get(id) || []), s]);
    }

    const prompts = data.prompts.map((p) => {
      const t = TYPE[p.type];
      const s = schoolByKey.get(p.school);
      return {
        kind: "prompt", id: p.id, p, t, school: p.school, schoolName: s.name, samples: samplesFor.get(p.id) || [],
        short: SCHOOL[p.school][0], initials: SCHOOL[p.school][1],
        title: spineTitle(p.prompt), h: heightFor(p.limit), w: widthFor(p.prompt.length),
        hay: [p.prompt, s.name, SCHOOL[p.school][0], p.type, p.notes].join(" ").toLowerCase(),
      };
    });

    const essays = data.essays_that_worked.map((e) => {
      const key = keyByName.get(e.school) || null;
      const [short, initials] = key ? SCHOOL[key] : PUBLISHER[e.school] || PUBLISHER[e.publisher] || [e.publisher, "EW"];
      const h = hash(e.id);
      return {
        kind: "essay", id: e.id, e, t: TYPE.essay, school: key, schoolName: e.school || e.publisher,
        short, initials, title: e.title || e.author || "An essay that worked",
        h: 236 + (h % 64), w: 40 + ((h >>> 8) % 14),
        hay: [e.title, e.author, e.school, e.publisher, e.year, e.about, e.prompt_answered, "essay essays that worked"].join(" ").toLowerCase(),
      };
    });

    items = [...prompts, ...essays];
    byId = new Map(items.map((it) => [it.id, it]));
    for (const it of items) it.el = makeBook(it);
  }

  function makeBook(it) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `book t-${it.t.slug}`;
    b.dataset.id = it.id;
    b.style.setProperty("--h", it.h.toFixed(1));
    b.style.setProperty("--w", it.w.toFixed(1));
    b.style.setProperty("--spine-ink", inkFor(it.t.color));

    const fs = it.h < 175 ? 12 : 13.5;
    b.style.setProperty("--fs", fs);
    const mark = it.h >= 190 ? MARKS[hash(it.id + "m") % MARKS.length] : "none";
    const titleSpace = it.h - 26 - 24 - 8 - (mark === "none" ? 0 : 20);
    const capacity = Math.max(4, Math.floor(titleSpace / (fs * 0.5)));  // Outfit averages ~0.5em per character
    const lines = spineLines(it.title, capacity, it.w >= 46 ? 2 : 1);

    b.innerHTML =
      `<span class="spine-title">${lines.map((l) => `<span>${esc(l)}</span>`).join("")}</span>` +
      `<span class="spine-mark m-${mark}" aria-hidden="true"></span>` +
      `<span class="spine-badge" aria-hidden="true">${esc(it.initials)}</span>` +
      `<span class="ribbon" aria-hidden="true"></span>`;
    b.setAttribute("aria-label", it.kind === "prompt"
      ? `${it.schoolName}, ${it.t.label}: ${it.p.prompt}`
      : `Essay that worked: ${it.title}, ${it.schoolName}`);
    return b;
  }

  // ---------- Filtering and layout ----------

  function matches(it) {
    if (state.type && it.t.key !== state.type) return false;
    if (state.school && it.school !== state.school) return false;
    if (state.q) return state.q.split(/\s+/).every((w) => it.hay.includes(w));
    return true;
  }

  // Books grouped by school (in shelf order), then the essays that worked.
  function groups() {
    const out = [];
    for (const s of data.schools) {
      const books = visible.filter((it) => it.kind === "prompt" && it.school === s.key);
      if (books.length) out.push({ label: SCHOOL[s.key][0], school: s.key, books });
    }
    const essays = visible.filter((it) => it.kind === "essay");
    if (essays.length) out.push({ label: "Essays that worked", type: "essay", books: essays });
    return out;
  }

  function makeDivider(g) {
    const d = document.createElement("button");
    d.type = "button";
    d.className = "divider";
    if (g.school) d.dataset.school = g.school;
    if (g.type) d.dataset.type = g.type;
    d.title = `Show only ${g.label}`;
    d.innerHTML = `<span>${esc(g.label)}</span>`;
    return d;
  }

  function layout() {
    const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--s")) || 1;
    const width = bookcase.clientWidth - 12;
    lastWidth = bookcase.clientWidth;
    releasePulled();

    // Pack dividers and books into rows; a divider never ends a row.
    const rows = [];
    let row = [], used = 0;
    const push = (tok, w) => { row.push(tok); used += w; };
    const breakRow = () => { if (row.length) rows.push({ row, used }); row = []; used = 0; };

    for (const g of groups()) {
      const divW = DIVIDER_W;
      const firstW = g.books[0].w * scale + GAP;
      if (used + divW + firstW > width) breakRow();
      push({ el: makeDivider(g) }, divW);
      for (const it of g.books) {
        const w = it.w * scale + GAP;
        if (used + w > width) breakRow();
        push({ el: it.el, it }, w);
      }
    }
    breakRow();

    const shelves = rows.map(({ row, used }) => {
      for (const tok of row) if (tok.it) { tok.el.classList.remove("lean", "pulled"); tok.el.style.removeProperty("--lean-gap"); }
      // Lean the last book on its neighbour when the shelf has room.
      const last = row[row.length - 1], prev = row[row.length - 2];
      if (last?.it && prev?.it) {
        const gap = Math.min(last.it.h, prev.it.h) * scale * Math.tan((LEAN_DEG * Math.PI) / 180);
        if (width - used > gap + 24) {
          last.el.classList.add("lean");
          last.el.style.setProperty("--lean-gap", gap.toFixed(1));
        }
      }
      const shelf = document.createElement("div");
      shelf.className = "shelf";
      const books = document.createElement("div");
      books.className = "shelf-books";
      const tallest = Math.max(160, ...row.filter((t) => t.it).map((t) => t.it.h));
      books.style.height = `${((tallest + HEADROOM) * scale).toFixed(1)}px`;
      books.append(...row.map((t) => t.el));
      const plank = document.createElement("div");
      plank.className = "plank";
      shelf.append(books, plank);
      return shelf;
    });
    bookcase.replaceChildren(...shelves);
  }

  function apply() {
    visible = items.filter(matches);
    layout();
    $("empty").hidden = visible.length > 0;
    document.querySelector(".hint").hidden = visible.length === 0;

    // Books the agents picked stay lit; the rest fade.
    for (const it of items) {
      it.el.classList.toggle("lit", !!state.lit?.has(it.id));
      it.el.classList.toggle("dim", !!state.lit && !state.lit.has(it.id));
    }

    const n = visible.length;
    const parts = [`${n} ${n === 1 ? "book" : "books"}`];
    if (state.type) parts.push(TYPE[state.type].label);
    if (state.school) parts.push(SCHOOL[state.school][0]);
    if (state.q) parts.push(`matching “${search.value.trim()}”`);
    const text = parts.length === 1 ? `${parts[0]} on the shelf` : parts.join(" · ");
    const lit = state.lit ? visible.filter((it) => state.lit.has(it.id)).length : 0;
    $("status").innerHTML = esc(text) + (state.lit
      ? ` · ${lit} lit up <button class="inline-link" type="button" data-act="unlight">clear</button>` : "");

    for (const c of document.querySelectorAll(".masthead .chip")) {
      const on = c.dataset.all !== undefined ? !state.type && !state.school
        : c.dataset.type ? state.type === c.dataset.type
        : state.school === c.dataset.school;
      c.setAttribute("aria-pressed", String(on));
    }
  }

  function renderChips() {
    $("type-chips").innerHTML =
      `<button class="chip" type="button" data-all>All</button>` +
      TYPES.map((t) => `<button class="chip" type="button" data-type="${esc(t.key)}"><i class="dot" style="--c:${t.color}"></i>${esc(t.label)}</button>`).join("");
    $("school-chips").innerHTML = data.schools
      .map((s) => `<button class="chip" type="button" data-school="${esc(s.key)}">${esc(SCHOOL[s.key][0])}</button>`).join("");
  }

  function setFilter({ type, school, reset }) {
    if (reset) { state.type = null; state.school = null; state.q = ""; search.value = ""; }
    if (type !== undefined) state.type = state.type === type ? null : type;
    if (school !== undefined) state.school = state.school === school ? null : school;
    apply();
  }

  // ---------- Tooltip ----------

  function showTip(el) {
    const it = byId.get(el.dataset.id);
    if (!it || current) return;
    const dot = `<i class="dot" style="--c:${it.t.color}"></i>`;
    if (it.kind === "prompt") {
      const req = it.p.required === "required" ? "Required" : "Optional";
      tip.innerHTML =
        `<div class="tip-head"><span class="tip-school">${esc(it.short)}</span><span class="tip-type">${dot}${esc(it.t.label)}</span></div>` +
        `<p class="tip-text">${esc(it.p.prompt)}</p>` +
        `<div class="tip-meta">${esc(limitText(it.p))} · ${req}${it.samples.length ? " · Sample essay" : ""}</div>`;
    } else {
      const e = it.e;
      tip.innerHTML =
        `<div class="tip-head"><span class="tip-school">${esc(it.short)}</span><span class="tip-type">${dot}Essay that worked</span></div>` +
        `<p class="tip-text"><strong>${esc(it.title)}.</strong> ${esc(e.about)}</p>` +
        `<div class="tip-meta">${esc([e.author, e.year].filter(Boolean).join(" · ") || e.publisher)}</div>`;
    }
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    const left = clamp(r.left + r.width / 2 - tw / 2, 12, innerWidth - tw - 12);
    const top = r.top - th - 14 >= 12 ? r.top - th - 14 : Math.min(r.bottom + 14, innerHeight - th - 12);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    tip.classList.add("show");
  }
  const hideTip = () => tip.classList.remove("show");

  // ---------- Reading card ----------

  function coverSvg(slug, seed) {
    const [bg, a, b, c] = COVER[slug];
    const shapes = [
      `<circle cx="170" cy="150" r="80" fill="${a}"/><rect x="34" y="232" width="94" height="94" fill="${b}"/>` +
        `<path d="M126 330a66 66 0 0 1 132 0z" fill="${c}"/>`,
      `<rect x="122" y="62" width="126" height="126" fill="${b}"/><circle cx="106" cy="206" r="72" fill="${a}" opacity=".92"/>` +
        `<path d="M44 336a62 62 0 0 1 124 0z" fill="${c}"/>`,
      `<path d="M22 312a118 118 0 0 1 236 0z" fill="${a}"/><circle cx="204" cy="100" r="30" fill="${b}"/>` +
        `<rect x="30" y="142" width="168" height="20" fill="${c}"/>`,
    ][seed % 3];
    return `<svg viewBox="0 0 280 400" preserveAspectRatio="xMidYMin meet" aria-hidden="true"><rect width="280" height="400" fill="${bg}"/>${shapes}</svg>`;
  }

  function cover(it, label) {
    return `<div class="cover" style="--c:${it.t.color};--spine-ink:${inkFor(it.t.color)}">` +
      coverSvg(it.t.slug, hash(it.id)) +
      `<div class="cover-top"><span>The Unwritten Shelf</span><span>${esc(label)}</span></div>` +
      `<div class="cover-bottom"><span class="cover-school">${esc(it.short)}</span><span class="badge">${esc(it.initials)}</span></div></div>`;
  }

  const typePill = (it) =>
    `<span class="type-pill t-${it.t.slug}" style="--c:${it.t.color};--spine-ink:${inkFor(it.t.color)}">${esc(it.t.label)}</span>`;

  function relatedItem(it, withSchool = false) {
    if (it.kind === "essay") {
      const e = it.e;
      return `<button class="related-item" type="button" data-open="${esc(it.id)}"><i class="mini-spine" style="--c:${it.t.color}"></i>` +
        `<span><strong>${esc(it.title)}</strong><small>${esc([e.author, e.year, it.schoolName].filter(Boolean).join(" · "))}</small></span></button>`;
    }
    return `<button class="related-item" type="button" data-open="${esc(it.id)}"><i class="mini-spine" style="--c:${it.t.color}"></i>` +
      `<span><strong>${withSchool ? `${esc(it.short)} · ` : ""}${esc(it.t.label)} · ${esc(limitText(it.p))}</strong><small>${esc(it.p.prompt)}</small></span></button>`;
  }

  // A prompt with no sample of its own points to a sample for the same type of prompt,
  // preferring the same school.
  function similarWithSample(it) {
    const pool = items.filter((x) => x.kind === "prompt" && x !== it && x.samples.length && x.t === it.t);
    const same = pool.filter((x) => x.school === it.school);
    const from = same.length ? same : pool;
    return from.length ? from[hash(it.id) % from.length] : null;
  }

  function sampleSection(it) {
    if (!it.samples.length) {
      const alt = similarWithSample(it);
      return `<section class="related"><h3 class="label">Sample essay</h3>` +
        `<p class="empty-related">College Essay Guy doesn't have a sample for this prompt.` +
        (alt ? ` Here's one for a similar ${esc(it.t.label.toLowerCase())} prompt:</p><div class="related-list">${relatedItem(alt, true)}</div>` : "</p>") +
        `</section>`;
    }
    const tabs = it.samples.length > 1
      ? `<div class="sample-tabs" role="tablist">${it.samples.map((_, i) =>
          `<button class="sample-tab" type="button" role="tab" aria-selected="${i === 0}" data-sample="${i}">Sample ${i + 1}</button>`).join("")}</div>`
      : "";
    return `<section class="samples" style="--c:${it.t.color};--spine-ink:${inkFor(it.t.color)}">` +
      `<div class="samples-head"><h3 class="label">Sample essay · College Essay Guy</h3>${tabs}</div>` +
      it.samples.map((s, i) => sampleBody(s, i, it)).join("") + `</section>`;
  }

  function sampleBody(s, i, it) {
    const src = safeUrl(s.source_url);
    const forWhom = !s.written_for ? `Written for ${it.short}`
      : s.written_for === "another school" ? "Written for another school's similar prompt"
      : s.written_for === "several schools" ? "Adapted for several schools' similar prompts"
      : `Written for ${s.written_for}'s similar prompt`;
    const lim = it.p.limit;
    const maxWords = lim ? (lim.unit === "words" ? lim.max : Math.round(lim.max / 6)) : null;
    const over = maxWords && s.approx_words > maxWords * 1.1;
    const length = s.approx_words ? `About ${s.approx_words} words` : "";
    // prompt_answered holds real prompt wording only; match_note explains looser matches.
    const notes = [
      s.prompt_answered ? `Answers: “${esc(s.prompt_answered)}”` : "",
      s.match_note ? esc(s.match_note) : s.prompt_match === "earlier version" ? "Written for an earlier version of this prompt." : "",
    ].filter(Boolean);
    const answered = notes.map((n) => `<p class="sample-earlier">${n}</p>`).join("");
    return `<article class="sample" role="tabpanel" data-panel="${i}"${i ? " hidden" : ""}>` +
      `<div class="sample-meta"><strong>${esc(forWhom)}</strong>${length ? `<span>${length}</span>` : ""}</div>` +
      (over ? `<p class="sample-earlier">Longer than this prompt's ${maxWords}-word limit: borrow the approach, not the length.</p>` : "") +
      answered +
      `<h4>What the writer did</h4><p>${esc(s.what_the_writer_did)}</p>` +
      `<h4>How it's built</h4><ol class="steps">${s.structure.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>` +
      `<h4>Why it works</h4><ul class="works">${s.why_it_works.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` +
      (src ? `<a class="btn" href="${esc(src)}" target="_blank" rel="noopener noreferrer">Read the full essay · ${esc(domain(src))} ↗</a>` : "") +
      `</article>`;
  }

  const nav =
    `<nav class="card-nav" aria-label="Browse books"><button class="link-btn" type="button" data-act="prev">← Previous</button>` +
    `<button class="link-btn" type="button" data-act="next">Next →</button></nav>`;

  function promptCard(it) {
    const p = it.p;
    const atSchool = items.filter((x) => x.kind === "prompt" && x.school === it.school);
    const n = atSchool.indexOf(it) + 1;
    const essays = items.filter((x) => x.kind === "essay" && (x.e.school === it.schoolName || x.e.prompt_answered === p.prompt));
    const src = safeUrl(p.source_url);
    const checked = p.status === "verified"
      ? `Verified ${fmtDate(p.date_checked)}${p.source_type === "backup" ? " (College Essay Guy)" : ""}`
      : `Unverified (${fmtDate(p.date_checked)})`;
    const choice = p.choice_group ? `<div><dt>Choose</dt><dd>${p.choice_group.pick} of ${p.choice_group.of}</dd></div>` : "";
    const allEssays = items.filter((x) => x.kind === "essay").length;

    return cover(it, `No. ${String(n).padStart(2, "0")}`) +
      `<div class="card-body">` +
      `<button class="close" type="button" aria-label="Close" data-act="close">×</button>` +
      `<div class="eyebrow">${typePill(it)}<span>Prompt ${n} of ${atSchool.length}</span></div>` +
      `<h2 class="card-title" id="card-title">${esc(it.schoolName)}</h2>` +
      `<p class="card-prompt ${p.prompt.length > 220 ? "long" : "big"}">${esc(p.prompt)}</p>` +
      `<dl class="facts">` +
      `<div><dt>Limit</dt><dd>${esc(limitText(p))}</dd></div>` +
      `<div><dt>Required</dt><dd>${p.required === "required" ? "Required" : "Optional"}</dd></div>${choice}` +
      `<div><dt>Checked</dt><dd>${esc(checked)}</dd></div></dl>` +
      (p.notes ? `<p class="notes">${fmtNotes(p.notes)}</p>` : "") +
      `<div class="actions">` +
      (src ? `<a class="btn primary" href="${esc(src)}" target="_blank" rel="noopener noreferrer">Source · ${esc(domain(src))} ↗</a>` : "") +
      `<button class="btn" type="button" data-act="copy">Copy link</button>` +
      (decoded.has(it.id) ? "" : `<button class="btn decode-btn" type="button" data-act="decode">Decode this prompt</button>`) +
      `</div>` +
      `<section class="decode"${decoded.has(it.id) ? "" : " hidden"}>${decoded.has(it.id) ? decodeSection(decoded.get(it.id)) : ""}</section>` +
      sampleSection(it) +
      `<section class="related"><h3 class="label">Essays that worked</h3>` +
      (essays.length
        ? `<div class="related-list">${essays.map(relatedItem).join("")}</div>`
        : `<p class="empty-related">No essays that worked from ${esc(it.short)} on the shelf yet. ` +
          `<button class="inline-link" type="button" data-act="essays">Browse all ${allEssays} →</button></p>`) +
      `</section>${nav}</div>`;
  }

  function essayCard(it) {
    const e = it.e;
    const src = safeUrl(e.source_url);
    const kind = { "personal statement": "Personal statement", supplemental: "Supplemental essay" }[e.essay_kind] || "";
    // Untitled essays use the author's name as their title, so don't repeat it.
    const by = [e.title ? e.author : null, e.year, e.school].filter(Boolean).join(" · ");
    const prompts = it.school ? items.filter((x) => x.kind === "prompt" && x.school === it.school) : [];

    return cover(it, e.year || "Essay") +
      `<div class="card-body">` +
      `<button class="close" type="button" aria-label="Close" data-act="close">×</button>` +
      `<div class="eyebrow">${typePill(it)}${kind ? `<span>${kind}</span>` : ""}</div>` +
      `<h2 class="card-title" id="card-title">${esc(it.title)}</h2>` +
      `<p class="byline">${esc(by || "Author not named")}</p>` +
      `<h3 class="label">The prompt it answered</h3>` +
      (e.prompt_answered
        ? `<blockquote class="answered">${esc(e.prompt_answered)}</blockquote>`
        : `<p class="about">${esc(e.publisher)} doesn't say which prompt this essay answered.</p>`) +
      `<h3 class="label">What it's about</h3><p class="about">${esc(e.about)}</p>` +
      `<p class="notes">The full essay is the author's own work, so it stays where ${esc(e.publisher)} published it.</p>` +
      `<div class="actions">` +
      (src ? `<a class="btn primary" href="${esc(src)}" target="_blank" rel="noopener noreferrer">Read the full essay · ${esc(domain(src))} ↗</a>` : "") +
      `<button class="btn" type="button" data-act="copy">Copy link</button></div>` +
      (prompts.length
        ? `<section class="related"><h3 class="label">Prompts from ${esc(it.short)}</h3><div class="related-list">${prompts.map(relatedItem).join("")}</div></section>`
        : "") +
      `${nav}</div>`;
  }

  // ---------- Decode this prompt (the Librarian) ----------

  const decoded = new Map();  // prompt id -> the Librarian's decode, kept for this visit

  function decodeSection(d) {
    const src = safeUrl(d.source_url);
    const reads = d.read_these.map((r) => {
      const target = byId.get(r.open_id);
      const color = r.kind === "essay" ? TYPE.essay.color : target?.t.color || TYPE.essay.color;
      const link = safeUrl(r.source_url);
      return `<div class="read-item"><button class="related-item" type="button" data-open="${esc(r.open_id)}" data-ref="${esc(r.id)}">` +
        `<i class="mini-spine" style="--c:${color}"></i><span><strong>${esc(r.kind === "sample" ? `Sample essay · ${target?.short || ""}` : r.title)}</strong>` +
        `<small>${esc(r.why)}</small></span></button>` +
        (link ? `<a class="read-src" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(domain(link))} ↗</a>` : "") + `</div>`;
    }).join("");
    return `<h3 class="label">Decoded by the Librarian</h3>` +
      `<h4>What it's really asking</h4><p>${esc(d.really_asking)}</p>` +
      `<h4>Common mistakes</h4><ul class="mistakes">${d.common_mistakes.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>` +
      (reads ? `<h4>Read these</h4><div class="related-list">${reads}</div>` : "") +
      (src ? `<p class="decode-source">Based only on the shelf's data. Prompt source: ` +
        `<a href="${esc(src)}" target="_blank" rel="noopener noreferrer">${esc(domain(src))} ↗</a></p>` : "");
  }

  async function decode(btn) {
    const it = current;
    if (!it || it.kind !== "prompt") return;
    const box = card.querySelector(".decode");
    btn.disabled = true;
    btn.textContent = "Decoding…";
    box.hidden = false;
    box.innerHTML = `<p class="agent-wait">The Librarian is reading this prompt and its examples…</p>`;
    try {
      const res = await fetch("/api/decode", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt_id: it.id }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `Something went wrong (${res.status}).`);
      decoded.set(it.id, body);
      if (current === it) { box.innerHTML = decodeSection(body); btn.remove(); }
    } catch (err) {
      if (current === it) {
        box.innerHTML = `<p class="agent-wait">${esc(err.message)}</p>`;
        btn.disabled = false;
        btn.textContent = "Try decoding again";
      }
    }
  }

  // A "Read these" sample for the prompt that's already open: show its tab instead of reopening.
  function showSample(ref) {
    const i = current?.samples?.findIndex((s) => s.id === ref) ?? -1;
    if (i < 0) return false;
    card.querySelector(`[data-sample="${i}"]`)?.click();
    card.querySelector(".samples")?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
    return true;
  }

  function openCard(it) {
    if (!it) return;
    hideTip();
    if (!current) returnFocus = document.activeElement;
    current = it;
    card.innerHTML = it.kind === "prompt" ? promptCard(it) : essayCard(it);
    card.scrollTop = 0;
    backdrop.hidden = false;
    requestAnimationFrame(() => backdrop.classList.add("open"));
    document.body.classList.add("modal-open");
    history.replaceState(null, "", `#${it.id}`);
    card.querySelector(".close").focus({ preventScroll: true });
  }

  function closeCard() {
    if (!current) return;
    current = null;
    backdrop.classList.remove("open");
    setTimeout(() => { if (!current) backdrop.hidden = true; }, 200);
    document.body.classList.remove("modal-open");
    history.replaceState(null, "", location.pathname + location.search);
    releasePulled();
    returnFocus?.focus?.({ preventScroll: true });
  }

  // Previous/next follow the shelf as it's shown; books opened from elsewhere use the full shelf.
  function step(dir) {
    const shown = groups().flatMap((g) => g.books);
    const seq = shown.includes(current) ? shown : items;
    const i = seq.indexOf(current);
    releasePulled();
    openCard(seq[(i + dir + seq.length) % seq.length]);
  }

  async function copyLink(btn) {
    try {
      await navigator.clipboard.writeText(location.href);
      btn.textContent = "Copied ✓";
    } catch {
      btn.textContent = location.href;
    }
  }

  // ---------- Surprise me ----------

  function releasePulled() {
    if (!pulled) return;
    pulled.classList.remove("pulled");
    pulled.closest(".shelf")?.querySelector(".beam")?.remove();
    pulled = null;
  }

  function surprise() {
    if (!visible.length) setFilter({ reset: true });
    closeCard();
    releasePulled();
    const pool = visible;
    const it = pool[Math.floor(Math.random() * pool.length)];
    const el = it.el;
    el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });

    setTimeout(() => {
      pulled = el;
      el.classList.add("pulled");
      // A mustard spotlight from a little lamp above the shelf.
      const shelf = el.closest(".shelf");
      const beam = document.createElement("div");
      beam.className = "beam";
      const w = el.offsetWidth + 90;
      const top = -46;
      beam.style.left = `${el.offsetLeft + el.offsetWidth / 2 - w / 2}px`;
      beam.style.width = `${w}px`;
      beam.style.top = `${top}px`;
      beam.style.height = `${Math.max(60, el.offsetTop - 34 - top + 6)}px`;
      beam.innerHTML =
        `<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">` +
        `<defs><linearGradient id="beam-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#E1B965" stop-opacity=".55"/>` +
        `<stop offset="1" stop-color="#E1B965" stop-opacity=".12"/></linearGradient></defs>` +
        `<polygon points="43,5 57,5 100,100 0,100" fill="url(#beam-g)"/><rect x="38" y="0" width="24" height="5" fill="#E1B965"/></svg>`;
      shelf.append(beam);
      requestAnimationFrame(() => beam.classList.add("on"));
      setTimeout(() => openCard(it), reduced ? 100 : 750);
    }, reduced ? 0 : 450);
  }

  // ---------- Events ----------

  function bind() {
    bookcase.addEventListener("pointerover", (e) => { const b = e.target.closest(".book"); if (b) showTip(b); });
    bookcase.addEventListener("pointerout", (e) => { const b = e.target.closest(".book"); if (b && !b.contains(e.relatedTarget)) hideTip(); });
    bookcase.addEventListener("focusin", (e) => { if (e.target.matches(".book")) showTip(e.target); });
    bookcase.addEventListener("focusout", hideTip);
    bookcase.addEventListener("click", (e) => {
      const b = e.target.closest(".book");
      if (b) return openCard(byId.get(b.dataset.id));
      const d = e.target.closest(".divider");
      if (d) setFilter(d.dataset.school ? { school: d.dataset.school } : { type: d.dataset.type });
    });
    addEventListener("scroll", hideTip, { passive: true });

    document.querySelector(".masthead").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="unlight"]')) return window.Shelf.light(null);
      const c = e.target.closest(".chip");
      if (!c) return;
      if (c.dataset.all !== undefined) setFilter({ reset: true });
      else if (c.dataset.type) setFilter({ type: c.dataset.type });
      else setFilter({ school: c.dataset.school });
    });

    let timer;
    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.q = search.value.trim().toLowerCase(); apply(); }, 90);
    });
    $("clear").addEventListener("click", () => setFilter({ reset: true }));
    $("surprise").addEventListener("click", surprise);

    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeCard(); });
    card.addEventListener("click", (e) => {
      const open = e.target.closest("[data-open]");
      if (open && open.dataset.open === current?.id && showSample(open.dataset.ref)) return;
      if (open) { releasePulled(); return openCard(byId.get(open.dataset.open)); }
      const tab = e.target.closest("[data-sample]");
      if (tab) {
        for (const t of card.querySelectorAll("[data-sample]")) t.setAttribute("aria-selected", String(t === tab));
        for (const p of card.querySelectorAll("[data-panel]")) p.hidden = p.dataset.panel !== tab.dataset.sample;
        return;
      }
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "close") closeCard();
      else if (act === "prev") step(-1);
      else if (act === "next") step(1);
      else if (act === "copy") copyLink(e.target.closest("[data-act]"));
      else if (act === "decode") decode(e.target.closest("[data-act]"));
      else if (act === "essays") { closeCard(); setFilter({ reset: true }); setFilter({ type: "essay" }); bookcase.scrollIntoView({ behavior: reduced ? "auto" : "smooth" }); }
    });

    document.addEventListener("keydown", (e) => {
      if (current) {
        if (e.key === "Escape") closeCard();
        else if (e.key === "ArrowRight") step(1);
        else if (e.key === "ArrowLeft") step(-1);
        else if (e.key === "Tab") trapFocus(e);
      } else if (e.key === "/" && document.activeElement !== search) {
        e.preventDefault();
        search.focus();
      }
    });

    new ResizeObserver(() => { if (bookcase.clientWidth !== lastWidth) layout(); }).observe(bookcase);
  }

  function trapFocus(e) {
    const f = [...card.querySelectorAll("button, a[href]")];
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  // ---------- Start ----------

  async function start() {
    try {
      const res = await fetch("/api/shelf");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      $("status").textContent = "Couldn't load the shelf. Is the server running?";
      return;
    }
    $("count").innerHTML =
      `<b>${data.schools.length}</b> schools · <b>${data.prompts.length}</b> prompts · <b>${data.essays_that_worked.length}</b> essays that worked`;
    buildItems();
    renderChips();
    bind();
    apply();
    const id = decodeURIComponent(location.hash.slice(1));
    if (byId.has(id)) openCard(byId.get(id));
    exposeShelf();
  }

  // What agents.js (Ask the shelf, Story Map) can use.
  function exposeShelf() {
    window.Shelf = {
      item: (id) => byId.get(id),
      open: (id) => openCard(byId.get(id)),
      // Light up these books and fade the rest; null clears it.
      light(ids) {
        state.lit = ids?.length ? new Set(ids) : null;
        if (state.lit) { state.type = null; state.school = null; state.q = ""; search.value = ""; }
        apply();
        document.dispatchEvent(new CustomEvent("shelf:lit", { detail: { lit: !!state.lit } }));
      },
      showLit() {
        const first = items.find((it) => state.lit?.has(it.id));
        first?.el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
      },
      schools: () => data.schools.map((s) => ({ key: s.key, name: s.name, short: SCHOOL[s.key][0] })),
      TYPE, inkFor, esc, safeUrl, domain, limitText,
    };
    document.dispatchEvent(new Event("shelf:ready"));
  }

  start();
})();
