// The Backups page (W-04, docs/15 section 4, docs/36 section 3): when each backup was made, how big, who made it, a button to make one now, and how to put one back, which is a
// command on the server and never a button, so that nobody restores by mistake (the drawn sentence). A backup holds the accounts, playlists and likes and the keys this install needs;
// only the backup key the Host saved can open it. The button asks the computer's helper; without it the page says how to get it.
import { Problem, api } from "/encore/web/api.js";
import { ago, el } from "/encore/web/dom.js";

function size(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function when(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function row(item) {
  return el(
    "div",
    { class: "hrow", "data-backup": item.name },
    el("i", { class: "dot " + (item.locked ? "ok" : "warn"), "aria-hidden": "true" }),
    el(
      "span",
      { class: "tx" },
      el("span", { class: "nm" }, when(item.madeAt)),
      el("span", { class: "stt " + (item.locked ? "ok" : "warn") }, item.locked ? "Locked" : "Not locked"),
      el(
        "span",
        { class: "sm" },
        `${size(item.bytes)} · ${item.pool === "admin" ? "made from this page" : "made by the computer"} · ${ago(item.madeAt)}`,
      ),
    ),
  );
}

export async function renderBackups(main) {
  const head = el(
    "div",
    { class: "ahead" },
    el(
      "div",
      { class: "tx" },
      el("h1", {}, "Backups"),
      el(
        "p",
        { class: "lead" },
        "A copy of the accounts, playlists and likes, made every night at about 03:30 and whenever you ask. Your music is not in it.",
      ),
    ),
  );
  const status = el("p", { class: "muted", role: "status" });
  const problem = el("p", { class: "error", role: "alert" });
  const body = el("div", {});
  const make = el("button", { type: "button", class: "primary", id: "make-backup" }, "Back up now");
  main.replaceChildren(head, el("div", { class: "row" }, make, status), problem, body);

  async function load() {
    try {
      const answer = await api("GET", "/admin/backups");
      const nodes = [];
      if (!answer.installed) {
        nodes.push(
          el(
            "div",
            { class: "card need", role: "note" },
            el(
              "div",
              { class: "tx" },
              el("p", { class: "nm" }, "This page cannot make a backup yet."),
              el("p", { class: "muted" }, "It needs a small helper on the server computer. There, run:"),
              el("p", { class: "keybox" }, answer.how),
              el("p", { class: "muted" }, "A backup is still made every night, and with  sudo encore backup  at the computer."),
            ),
          ),
        );
        make.disabled = true;
      } else {
        make.disabled = false;
        nodes.push(
          answer.items.length
            ? el("div", { class: "card hlist" }, ...answer.items.map(row))
            : el("p", { class: "muted" }, "There is no backup yet. Back up now makes the first."),
        );
      }
      nodes.push(
        el(
          "div",
          { class: "card quiet" },
          el("p", { class: "nm" }, "What is in a backup"),
          el(
            "p",
            { class: "muted" },
            "It holds the accounts, playlists and likes, and the keys this install needs: keep it private. Only the backup key you saved can open it. Encore does not keep that key.",
          ),
          el("p", { class: "nm" }, "Putting one back"),
          el(
            "p",
            { class: "muted" },
            "A restore replaces what is on the server now, so it is a command on the server computer and never a button, and it asks for your backup key:",
          ),
          el("p", { class: "keybox" }, answer.restore),
        ),
      );
      body.replaceChildren(...nodes);
    } catch (error) {
      problem.textContent = error instanceof Problem ? error.message : "The backups did not load. Try again.";
    }
  }

  make.addEventListener("click", async () => {
    make.disabled = true;
    problem.textContent = "";
    status.textContent = "Copying the databases…";
    try {
      const done = await api("POST", "/admin/backups");
      status.textContent = done.done || "A backup was made.";
    } catch (error) {
      status.textContent = "";
      problem.textContent = error instanceof Problem ? error.message : "The backup did not work. Try again.";
    }
    make.disabled = false;
    await load();
  });

  await load();
}
