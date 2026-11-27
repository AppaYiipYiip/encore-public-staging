// The first run in the browser (docs/15 section 2, docs/36 section 2): the Host opens the link the installer showed, chooses the name and password of their account, and lands on
// the admin pages signed in. The setup code is in the address it was opened by: it is read once, taken out of the address bar at once, and kept only in this script's memory.
import { Problem, api, keepSession } from "/encore/web/api.js";
import { el } from "/encore/web/dom.js";

const app = document.getElementById("app");
const show = (...nodes) => app.replaceChildren(...nodes);

// The code goes out of the address bar (history, a screenshot, a shared screen) before anything else happens.
const params = new URLSearchParams(window.location.search);
let code = (params.get("code") || "").trim();
history.replaceState(null, "", "/encore/setup");

function plain(title, ...paragraphs) {
  show(el("main", { class: "plain" }, el("h1", {}, title), ...paragraphs.map((text) => el("p", { class: "lead" }, text))));
}

function closed() {
  const link = el("a", { href: "/encore/admin" }, "Sign in");
  show(el("main", { class: "plain" }, el("h1", {}, "This server is already set up"), el("p", { class: "lead" }, "Its owner has an account. ", link, " with it.")));
}

function askForCode(message) {
  const problem = el("p", { class: "error", role: "alert" }, message || "");
  const input = el("input", { type: "text", id: "code", autocomplete: "off", autocapitalize: "characters", spellcheck: "false", maxlength: "12", required: true });
  const button = el("button", { class: "primary", type: "submit" }, "Continue");
  const form = el(
    "form",
    { class: "login" },
    el("h1", {}, "Encore"),
    el("p", { class: "muted" }, "Use the link shown on the computer where you installed Encore. Or type the setup code shown there."),
    el("label", { for: "code" }, "Setup code"),
    input,
    problem,
    button,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    code = input.value.trim();
    button.disabled = true;
    await begin();
  });
  show(form);
  input.focus();
}

// The recovery key (docs/36 section 6): shown once, with the way to use it, a print button, and a "saved it" box that has to be ticked before going on. The server keeps only a
// hash of it; a lost one is replaced from the computer (sudo encore recovery-key), never looked up.
function recoveryKeyPage(username, key) {
  const saved = el("input", { type: "checkbox", id: "saved" });
  const go = el("button", { class: "primary", type: "button", disabled: true }, "Continue to the admin pages");
  const print = el("button", { class: "small", type: "button" }, "Print this page");
  saved.addEventListener("change", () => {
    go.disabled = !saved.checked;
  });
  print.addEventListener("click", () => window.print());
  go.addEventListener("click", () => window.location.replace("/encore/admin"));
  show(
    el(
      "main",
      { class: "login" },
      el("h1", {}, "Your recovery key"),
      el(
        "p",
        { class: "muted" },
        `If you ever forget your password, this key is how you get back in: on the computer where Encore is installed, run  sudo encore reset-password ${username}  and type it when asked. Write it down or print this page and keep it somewhere safe. Encore keeps no copy of it, so this is the only time it is shown.`,
      ),
      el("p", { class: "keybox", id: "key", "aria-label": "Your recovery key" }, key),
      print,
      el("p", { class: "muted" }, "If you lose it, make a new one on that computer with  sudo encore recovery-key  (the old one stops working)."),
      el("label", { class: "check", for: "saved" }, saved, " I have saved my recovery key"),
      go,
    ),
  );
  go.focus();
}

function ownerForm(serverName) {
  const problem = el("p", { class: "error", role: "alert" });
  const name = el("input", { type: "text", id: "name", autocomplete: "name", maxlength: "80" });
  const user = el("input", { type: "text", id: "user", autocomplete: "username", autocapitalize: "none", spellcheck: "false", required: true, maxlength: "32" });
  const password = el("input", { type: "password", id: "password", autocomplete: "new-password", required: true, minlength: "8", maxlength: "128" });
  const again = el("input", { type: "password", id: "again", autocomplete: "new-password", required: true, minlength: "8", maxlength: "128" });
  const reveal = el("input", { type: "checkbox", id: "reveal" });
  reveal.addEventListener("change", () => {
    password.type = again.type = reveal.checked ? "text" : "password";
  });
  const button = el("button", { class: "primary", type: "submit" }, "Create my account");
  const form = el(
    "form",
    { class: "login" },
    el("h1", {}, "Welcome to Encore"),
    el("p", { class: "muted" }, `Your own music service, on this computer. This server is called "${serverName}". Choose your account: it is the owner's, and you can invite everybody else afterwards.`),
    el("label", { for: "name" }, "Your name"),
    name,
    el("label", { for: "user" }, "Username (3 to 32 letters, digits, . - _)"),
    user,
    el("label", { for: "password" }, "Password (8 or more characters)"),
    password,
    el("label", { for: "again" }, "Type it again"),
    again,
    el("label", { class: "check", for: "reveal" }, reveal, " Show the password"),
    problem,
    button,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    problem.textContent = "";
    if (password.value !== again.value) {
      problem.textContent = "The two passwords are not the same.";
      return;
    }
    button.disabled = true;
    try {
      const body = { username: user.value.trim(), password: password.value };
      if (name.value.trim()) body.name = name.value.trim();
      const answer = await api("POST", "/setup/owner", body, { "X-Setup-Code": code });
      keepSession(answer.deviceToken);
      password.value = again.value = "";
      code = "";
      if (answer.recoveryKey) recoveryKeyPage(body.username, answer.recoveryKey);
      else window.location.replace("/encore/admin");
    } catch (error) {
      problem.textContent = error instanceof Problem ? error.message : "Your account could not be made. Try again.";
      if (error instanceof Problem && error.status === 404) closed();
      button.disabled = false;
    }
  });
  show(form);
  name.focus();
}

async function begin() {
  if (!code) {
    askForCode("");
    return;
  }
  try {
    const state = await api("GET", "/setup/state", undefined, { "X-Setup-Code": code });
    ownerForm(state.serverName || "your server");
  } catch (error) {
    if (error instanceof Problem && error.status === 404) closed();
    else if (error instanceof Problem && (error.status === 403 || error.status === 429)) askForCode(error.message);
    else plain("Your server did not answer", error instanceof Problem ? error.message : "Check that it is on, then reload this page.");
  }
}

begin();
