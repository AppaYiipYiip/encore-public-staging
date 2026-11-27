// The Away from home page (W-04, docs/22 section 5, docs/36 section 3): the address phones outside the house use, what Tailscale on the computer says, how long its key lasts, and the one
// thing a page may do: switch the address on or off for a Tailscale that is already set up. Installing Tailscale and signing in to it stay at the computer's terminal: a sign-in link joins the
// computer to the network of whoever completes it, so no page is allowed to show one.
import { Problem, api } from "/encore/web/api.js";
import { el } from "/encore/web/dom.js";

const DAY = 24 * 3600 * 1000;

function keyWords(ms) {
  const days = Math.floor((ms - Date.now()) / DAY);
  if (days < 0) return "The key has expired.";
  return `The key lasts another ${days} day${days === 1 ? "" : "s"}.`;
}

export async function renderAway(main) {
  const head = el(
    "div",
    { class: "ahead" },
    el(
      "div",
      { class: "tx" },
      el("h1", {}, "Away from home"),
      el("p", { class: "lead" }, "So you and your people can listen outside your home, with no router settings."),
    ),
  );
  const status = el("p", { class: "muted", role: "status" });
  const problem = el("p", { class: "error", role: "alert" });
  const body = el("div", {});
  main.replaceChildren(head, problem, status, body);

  // The server is recreated after it has answered: ask again every few seconds until it is back, and say so in words if it is not.
  async function afterRestart(tries) {
    for (let i = 0; i < tries; i++) {
      await new Promise((resolve) => setTimeout(resolve, 4000));
      try {
        await api("GET", "/admin/away");
        status.textContent = "";
        await load();
        return;
      } catch {
        // not back yet
      }
    }
    problem.textContent = "The server has not come back yet. Reload this page in a moment.";
  }

  async function act(path, working) {
    problem.textContent = "";
    status.textContent = working;
    try {
      const done = await api("POST", path);
      status.textContent = `${done.done} The server restarts to learn the new address; this page comes back in a few seconds.`;
      afterRestart(8);
    } catch (error) {
      status.textContent = "";
      problem.textContent = error instanceof Problem ? error.message : "That did not work. Try again.";
      await load();
    }
  }

  async function load() {
    try {
      const answer = await api("GET", "/admin/away");
      const nodes = [];
      const setUp = answer.tailscale === "ready";
      if (answer.address) {
        nodes.push(
          el(
            "div",
            { class: "card" },
            el("p", { class: "nm" }, "On"),
            el("p", { class: "keybox", id: "away-address" }, answer.address),
            el("p", { class: "muted" }, "Phones that are signed in learn this address by themselves, and invitations carry it."),
            answer.keyExpiresAt ? el("p", { class: "muted" }, keyWords(answer.keyExpiresAt)) : null,
          ),
        );
      } else {
        nodes.push(el("div", { class: "card" }, el("p", { class: "nm" }, "Not set up"), el("p", { class: "muted" }, "Your phones work at home. Outside, they need this.")));
      }
      if (!answer.installed) {
        nodes.push(
          el(
            "div",
            { class: "card need", role: "note" },
            el(
              "div",
              { class: "tx" },
              el("p", { class: "nm" }, "This page cannot switch the address yet."),
              el("p", { class: "muted" }, "It needs a small helper on the server computer. There, run:  sudo encore helper install"),
            ),
          ),
        );
      } else if (!setUp) {
        nodes.push(
          el(
            "div",
            { class: "card need", role: "note" },
            el(
              "div",
              { class: "tx" },
              el(
                "p",
                { class: "nm" },
                answer.tailscale === "signedout" ? "Your server can't be reached from outside: Tailscale says this computer is signed out." : "Tailscale is not on the server computer yet.",
              ),
              el("p", { class: "muted" }, "Setting it up needs a sign-in, which is done once at the computer, never from a page. There, run:"),
              el("p", { class: "keybox" }, answer.how),
            ),
          ),
        );
      } else {
        const toggle = answer.address
          ? el("button", { type: "button", id: "away-off" }, "Turn off")
          : el("button", { type: "button", class: "primary", id: "away-on" }, "Turn on");
        toggle.addEventListener("click", () => {
          toggle.disabled = true;
          return answer.address ? act("/admin/away/off", "Turning it off…") : act("/admin/away/on", "Turning it on…");
        });
        nodes.push(el("div", { class: "row" }, toggle));
      }
      body.replaceChildren(...nodes);
    } catch (error) {
      problem.textContent = error instanceof Problem ? error.message : "The page did not load. Try again.";
    }
  }

  await load();
}
