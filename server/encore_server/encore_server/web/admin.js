// The admin site (docs/36 section 2, `15` section 4). This is the first brick: the sign-in and the frame the pages go in. Every word that comes from the server
// (a name, a sentence) is written into the page as text, never as markup.
import { Problem, api, hasSession, signIn, signOut } from "/encore/web/api.js";

const app = document.getElementById("app");

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "class") node.className = value;
    else node.setAttribute(name, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function show(...nodes) {
  app.replaceChildren(...nodes);
}

function signInPage(message) {
  const problem = el("p", { class: "error", role: "alert" }, message || "");
  const user = el("input", { type: "text", id: "user", autocomplete: "username", autocapitalize: "none", spellcheck: "false", required: "" });
  const password = el("input", { type: "password", id: "password", autocomplete: "current-password", required: "" });
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

function frame(me) {
  const out = el("button", { class: "small", type: "button" }, "Sign out");
  out.addEventListener("click", async () => {
    await signOut();
    signInPage("");
  });
  const when = me.session.expiresAt === null ? "" : "This browser stays signed in while you use it; it signs out after 12 hours unused.";
  show(
    el(
      "header",
      { class: "bar" },
      el("div", { class: "brand" }, "Encore", el("span", {}, "your server")),
      el("span", { class: "muted" }, me.person.name),
      out,
    ),
    el(
      "main",
      {},
      el("h1", {}, "Hello, " + me.person.name),
      el("p", { class: "lead" }, "The pages for your people, your settings and your backups are being built; they will appear here."),
      el("p", { class: "faint" }, when),
    ),
  );
}

async function start() {
  if (!hasSession()) {
    signInPage("");
    return;
  }
  try {
    frame(await api("GET", "/admin/session"));
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
