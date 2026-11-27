// The Home page (W-02, docs/15 section 4): one sentence that says how things are, what needs the Host first, then one plain row per part. Counts only, never titles. A part
// that Encore cannot know says so in words; nothing here is drawn as "all good" unless the server said it.
import { Problem, api } from "/encore/web/api.js";
import { el, icon } from "/encore/web/dom.js";

const REFRESH_MS = 30000;

function when(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function clock(ms) {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// "Last checked" is measured on THIS browser's clock from the moment the answer arrived, never against the server's clock: a laptop whose clock is a few minutes out would
// otherwise say "47 minutes ago" on a fresh page (the same class of mistake as the picture tickets, B-115).
function checked(arrivedAt, now) {
  const s = Math.max(0, Math.round((now - arrivedAt) / 1000));
  return s < 20 ? "Last checked a moment ago." : `Last checked ${Math.round(s / 60) || 1} minutes ago.`;
}

// What a row says as words: the server's own words, with the two times a computer's clock is better placed to write (when YouTube is resting until, when the last backup was made).
function wordsOf(row) {
  if (row.id === "youtube" && row.restingUntil) return `Resting until ${clock(row.restingUntil)}`;
  if (row.id === "backup" && row.at) return when(row.at);
  return row.words;
}

function dot(state) {
  return el("i", { class: "dot " + (state === "ok" ? "ok" : state === "down" ? "down" : state === "warn" ? "warn" : state === "resting" ? "warn" : "off"), "aria-hidden": "true" });
}

function rowNode(row) {
  return el(
    "div",
    { class: "hrow", "data-row": row.id },
    dot(row.state),
    el(
      "span",
      { class: "tx" },
      el("span", { class: "nm" }, row.title),
      el("span", { class: "stt " + row.state }, wordsOf(row)),
      row.detail ? el("span", { class: "sm" }, row.detail) : null,
    ),
  );
}

function needNode(need, go, label) {
  const open = need.page && go && label ? el("button", { type: "button", class: "small" }, "Open " + label) : null;
  if (open) open.addEventListener("click", () => go(need.page));
  return el("div", { class: "card need", role: "note" }, icon("alert"), el("div", { class: "tx" }, el("p", { class: "nm" }, need.words), el("p", { class: "muted" }, need.detail), open));
}

export function renderHome(main, me, serverName, pages) {
  const head = el("div", { class: "ahead" }, el("div", { class: "tx" }, el("h1", {}, "Home"), el("p", { class: "lead", id: "summary" }, "…")));
  const body = el("div", {});
  const problem = el("p", { class: "error", role: "alert" });
  main.replaceChildren(head, problem, body);
  let answer = null;
  let arrivedAt = 0;

  function paintSummary() {
    if (answer) head.querySelector("#summary").textContent = `${answer.summary.words} ${checked(arrivedAt, Date.now())}`;
  }

  async function load() {
    try {
      answer = await api("GET", "/admin/health");
      arrivedAt = Date.now();
      problem.textContent = "";
      paintSummary();
      const go = (id) => pages && pages.go && pages.has(id) && pages.go(id);
      const known = (id) => !!(pages && pages.has && pages.has(id));
      const label = (id) => (known(id) && pages.label ? pages.label(id) : "");
      body.replaceChildren(
        ...answer.needsYou.map((n) => needNode(known(n.page) ? n : { ...n, page: null }, go, label(n.page))),
        el("div", { class: "card hlist" }, ...answer.rows.map(rowNode)),
      );
    } catch (error) {
      problem.textContent = error instanceof Problem ? error.message : "The page did not load. Try again.";
    }
  }

  load();
  const timer = setInterval(() => {
    if (!document.hidden) load();
  }, REFRESH_MS);
  const tick = setInterval(paintSummary, 10000);
  // a tab that was in the background comes back with a fresh answer, not a minutes-old one
  const visible = () => {
    if (!document.hidden) load();
  };
  document.addEventListener("visibilitychange", visible);
  return {
    stop: () => {
      clearInterval(timer);
      clearInterval(tick);
      document.removeEventListener("visibilitychange", visible);
    },
  };
}
