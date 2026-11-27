// The admin site (docs/36 section 2, `15` section 4): the sign-in, the frame the pages go in (the rail of the drawings) and the pages that are built. Every word that
// comes from the server (a name, a sentence) is written into the page as text, never as markup.
import { Problem, api, hasSession, signIn, signOut } from "/encore/web/api.js";
import { el, icon } from "/encore/web/dom.js";
import { renderHome } from "/encore/web/home.js";
import { renderPeople } from "/encore/web/people.js";

const app = document.getElementById("app");

function show(...nodes) {
  app.replaceChildren(...nodes);
}

function signInPage(message) {
  const problem = el("p", { class: "error", role: "alert" }, message || "");
  const user = el("input", { type: "text", id: "user", autocomplete: "username", autocapitalize: "none", spellcheck: "false", required: true });
  const password = el("input", { type: "password", id: "password", autocomplete: "current-password", required: true });
  const button = el("button", { class: "primary", type: "submit" }, "Sign in");
  const form = el(
    "form",
    { class: "login" },
    el("h1", {}, "Encore"),
    el("p", { class: "muted" }, "Sign in with the account you made when you set this server up."),
    el("label", { for: "user" }, "Username"),
    user,
    el("label", { for: "password" }, "Password"),
    password,
    problem,
    button,
    el("p", { class: "faint" }, "Forgot your password? On the computer where Encore is installed, run  sudo encore reset-password YOURUSERNAME"),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    problem.textContent = "";
    try {
      await signIn(user.value.trim(), password.value);
      password.value = "";
      await start();
    } catch (error) {
      problem.textContent = error instanceof Problem ? error.message : "Signing in did not work. Try again.";
      button.disabled = false;
    }
  });
  show(form);
  user.focus();
}

// The pages that exist, in the order of the rail. The rail lists only these: a page that is not built is not a dead button. A page's render may return `{stop}` (a timer
// to clear when the Host goes elsewhere).
const PAGES = [
  { id: "home", label: "Home", icon: "home", render: renderHome },
  { id: "people", label: "People", icon: "people", render: renderPeople },
];

function frame(me, serverName) {
  const main = el("main", { class: "amain" });
  const out = el("button", { type: "button", class: "navi" }, icon("logout"), el("span", {}, "Sign out"));
  out.addEventListener("click", async () => {
    stop();
    await signOut();
    signInPage("");
  });
  const buttons = PAGES.map((page) => {
    const button = el("button", { type: "button", class: "navi" }, icon(page.icon), el("span", {}, page.label));
    button.addEventListener("click", () => go(page.id));
    return [page, button];
  });
  const rail = el(
    "aside",
    { class: "arail" },
    el("div", { class: "brand-x" }, el("span", {}, "Encore"), el("span", { class: "tagadm" }, "ADMIN")),
    ...buttons.map(([, button]) => button),
    el("span", { class: "sp" }),
    out,
    el("div", { class: "srv" }, el("span", { class: "nm" }, serverName), el("span", { class: "sm" }, `Signed in as ${me.person.name}`)),
  );
  show(el("div", { class: "adm" }, rail, main));

  let current = null;
  function stop() {
    if (current && current.stop) current.stop();
    current = null;
  }
  // The page is named in the address (#/people), so a reload and a link come back to the same page.
  function go(id) {
    const page = PAGES.find((p) => p.id === id) || PAGES[0];
    stop();
    for (const [p, button] of buttons) {
      if (p === page) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    history.replaceState(null, "", "#/" + page.id);
    const pages = { go, has: (name) => PAGES.some((p) => p.id === name), label: (name) => (PAGES.find((p) => p.id === name) || {}).label || "" };
    try {
      const made = page.render(main, me.person, serverName, pages);
      if (made && typeof made.then === "function") {
        made.catch(() => main.replaceChildren(el("p", { class: "error" }, "This page did not load. Reload it to try again.")));
      } else {
        current = made;
      }
    } catch {
      main.replaceChildren(el("p", { class: "error" }, "This page did not load. Reload it to try again."));
    }
  }
  go(window.location.hash.replace(/^#\//, ""));
}

async function serverName() {
  try {
    const info = await api("GET", "/info");
    return info.name || "your server";
  } catch {
    return "your server";
  }
}

async function start() {
  if (!hasSession()) {
    signInPage("");
    return;
  }
  try {
    const me = await api("GET", "/admin/session");
    frame(me, await serverName());
  } catch (error) {
    if (error instanceof Problem && error.status === 403) {
      await signOut();
      signInPage("Only the owner of this server can use these pages.");
    } else if (error instanceof Problem && error.status === 401) {
      signInPage(error.message);
    } else if (error instanceof Problem && error.status === 404) {
      show(el("main", { class: "plain" }, el("h1", {}, "Not here"), el("p", { class: "lead" }, "These pages are only reachable from your home network.")));
    } else {
      show(el("main", { class: "plain" }, el("h1", {}, "Encore"), el("p", { class: "error" }, error instanceof Problem ? error.message : "Something went wrong.")));
    }
  }
}

start();
