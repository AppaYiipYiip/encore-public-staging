// The People page (W-03, docs/15 section 4): who is on this server, an invitation for somebody new, a person locked or removed. The words are the drawn ones
// (docs/design, "W-03"), except where the server's own rule is different: nothing here says a wrong password locks an account (only the owner does that).
import { Problem, api } from "/encore/web/api.js";
import { ago, colourOf, copyText, el, icon, sheet } from "/encore/web/dom.js";

// The address an invitation is made for: the away address when the server has one (a friend is not in this house), else the one this page was opened by.
async function invitationBase() {
  try {
    const server = await api("GET", "/server");
    const away = server.addresses.find((a) => a.kind === "away");
    const home = server.addresses.find((a) => a.kind === "home");
    return { base: (away || home || { url: window.location.origin }).url.replace(/\/+$/, ""), serverId: server.serverId || null };
  } catch {
    return { base: window.location.origin, serverId: null };
  }
}

function linkField(link) {
  const field = el("input", { type: "text", class: "linkfield", readonly: true, value: link, "aria-label": "The link", spellcheck: "false" });
  const note = el("span", { class: "faint", role: "status" });
  const copy = el("button", { type: "button", class: "small" }, icon("copy"), el("span", {}, "Copy link"));
  copy.addEventListener("click", async () => {
    note.textContent = (await copyText(link, field)) ? "Copied." : "Select the link and copy it.";
  });
  field.addEventListener("focus", () => field.select());
  return el("div", { class: "row" }, field, copy, note);
}

function problemText(error) {
  return error instanceof Problem ? error.message : "That did not work. Try again.";
}

function invitationSheet(onMade) {
  const note = el("input", { type: "text", id: "invite-for", maxlength: "80", placeholder: "Sara", autocomplete: "off" });
  const role = el(
    "select",
    { id: "invite-role", "aria-label": "What they can do" },
    el("option", { value: "member" }, "A member: listens, has their own library"),
    el("option", { value: "owner" }, "Another owner: looks after this server too"),
  );
  const problem = el("p", { class: "error", role: "alert" });
  const body = el("div", {}, el("label", { for: "invite-for" }, "Who is it for?"), note, el("label", { for: "invite-role" }, "They are"), role, problem);
  const dialog = sheet("Invite someone", body, [
    { label: "Cancel" },
    {
      label: "Make the invitation",
      kind: "primary",
      run: async () => {
        problem.textContent = "";
        try {
          const made = (await api("POST", "/invites", { role: role.value, note: note.value.trim() || null })).invite;
          const { base, serverId } = await invitationBase();
          const link = `${base}/encore/join/${made.code}` + (serverId ? `?id=${encodeURIComponent(serverId)}` : "");
          const who = made.note ? " for " + made.note : "";
          body.replaceChildren(
            el("p", { class: "good" }, icon("check"), ` Invitation made${who}.`),
            el("p", {}, "Copy it now: the code is shown only once. Valid for 7 days."),
            linkField(link),
            el("p", { class: "faint" }, "Send it by message. Encore sends nothing by itself."),
          );
          dialog.querySelectorAll(".row.end button").forEach((b) => (b.hidden = true));
          const done = el("button", { type: "button", class: "primary" }, "Done");
          done.addEventListener("click", () => dialog.close());
          dialog.querySelector(".row.end").append(done);
          onMade();
          return false;
        } catch (error) {
          problem.textContent = problemText(error);
          return false;
        }
      },
    },
  ]);
}

function removeSheet(person, onDone) {
  const problem = el("p", { class: "error", role: "alert" });
  const first = person.name;
  sheet(
    `Remove ${first}?`,
    el(
      "div",
      {},
      el("p", {}, `${first}'s account, playlists, likes, history and devices are deleted from this server. The music files stay.`),
      el("p", {}, `${first}'s phone will say "Sign in again", and then nothing will work. This cannot be undone.`),
      problem,
    ),
    [
      { label: "Cancel" },
      {
        label: "Remove",
        kind: "danger",
        run: async () => {
          try {
            await api("DELETE", `/people/${person.id}`);
            onDone();
            return true;
          } catch (error) {
            problem.textContent = problemText(error);
            return false;
          }
        },
      },
    ],
  );
}

async function setLocked(person, locked, onDone, report) {
  try {
    await api("PATCH", `/people/${person.id}`, { locked });
    onDone();
  } catch (error) {
    report(problemText(error));
  }
}

function rowOf(person, me, ctx) {
  const mine = person.id === me.id;
  const seen = ago(person.lastSeen);
  const menu = el("div", { class: "menu", hidden: true });
  const more = el("button", { type: "button", class: "ibtn", "aria-label": `More about ${person.name}`, "aria-expanded": "false" }, icon("more"));
  more.addEventListener("click", () => {
    menu.hidden = !menu.hidden;
    more.setAttribute("aria-expanded", String(!menu.hidden));
  });
  if (!mine) {
    const lock = el("button", { type: "button" }, icon("lock"), el("span", {}, person.locked ? `Unlock ${person.name}` : `Lock ${person.name}`));
    lock.addEventListener("click", () => setLocked(person, !person.locked, ctx.reload, ctx.report));
    const remove = el("button", { type: "button", class: "danger" }, `Remove ${person.name}`);
    remove.addEventListener("click", () => {
      menu.hidden = true;
      removeSheet(person, ctx.reload);
    });
    menu.append(lock, remove);
  } else {
    menu.append(el("p", { class: "faint" }, "This is you."));
  }
  return el(
    "div",
    { class: "pt-r", role: "row" },
    el(
      "span",
      { class: "who" },
      el("span", { class: "av " + colourOf(person.name), "aria-hidden": "true" }, icon("people")),
      el(
        "span",
        { class: "tx" },
        el(
          "span",
          { class: "nm" },
          person.name + " ",
          el("span", { class: "pill-tag acc" }, person.role === "owner" ? "Owner" : "Member"),
          mine ? " " : null,
          mine ? el("span", { class: "pill-tag acc" }, "You") : null,
          person.locked ? " " : null,
          person.locked ? el("span", { class: "pill-tag warn" }, "Locked") : null,
        ),
        el("span", { class: "sm" }, seen === null ? "Has not signed in yet" : `Signed in ${seen}`),
      ),
    ),
    el("span", { class: "sm" }, seen === null ? "never" : seen),
    el("span", { class: "sm" }, person.devices === 1 ? "1 device" : `${person.devices} devices`),
    el("span", { class: "sm" }, person.invitedBy || "—"),
    el("span", { class: "acts" }, more, menu),
  );
}

export async function renderPeople(main, me, serverName) {
  const heading = el(
    "div",
    { class: "ahead" },
    el(
      "div",
      { class: "tx" },
      el("h1", {}, "People"),
      el(
        "p",
        { class: "lead" },
        `Everybody who can listen on ${serverName}. Each person has their own library, playlists and password; you see who is here, never what anybody plays.`,
      ),
    ),
  );
  const invite = el("button", { type: "button", class: "primary" }, icon("user-plus"), el("span", {}, "Invite someone"));
  heading.append(el("div", { class: "acts" }, invite));
  const status = el("p", { class: "error", role: "alert" });
  const list = el("div", { class: "ptab", role: "table", "aria-label": "People" });
  const waiting = el("div", {});
  main.replaceChildren(heading, status, list, waiting);

  async function reload() {
    status.textContent = "";
    try {
      const [people, invites] = await Promise.all([api("GET", "/people"), api("GET", "/invites")]);
      draw(people.items, invites.items);
    } catch (error) {
      status.textContent = problemText(error);
    }
  }
  const ctx = { reload, report: (text) => (status.textContent = text) };
  invite.addEventListener("click", () => invitationSheet(reload));

  function draw(people, invites) {
    const rows = [];
    for (const person of people.filter((p) => p.locked)) {
      const unlock = el("button", { type: "button", class: "small" }, icon("lock"), el("span", {}, `Unlock ${person.name}`));
      unlock.addEventListener("click", () => setLocked(person, false, reload, ctx.report));
      rows.push(
        el(
          "div",
          { class: "card quiet", role: "note" },
          el("p", {}, `${person.name}'s account is locked.`),
          el("p", { class: "muted" }, `Unlock it and ${person.name} signs in again with their own password. Their devices were signed out.`),
          unlock,
        ),
      );
    }
    if (people.length <= 1) {
      rows.push(
        el(
          "div",
          { class: "card quiet" },
          el("h2", {}, "Nobody else yet."),
          el("p", { class: "muted" }, "Invite someone with a link. Each link works once, for one person."),
        ),
      );
    }
    rows.push(
      el(
        "div",
        { class: "pt-h", role: "row" },
        ...["Person", "Last signed in", "Devices", "Invited by", ""].map((t) => el("span", { role: "columnheader" }, t)),
      ),
    );
    for (const person of people) rows.push(rowOf(person, me, ctx));
    list.replaceChildren(...rows);

    const open = invites.filter((i) => i.state === "open");
    const items = open.map((i) => {
      const cancel = el("button", { type: "button", class: "small" }, "Cancel the invitation");
      cancel.addEventListener("click", async () => {
        try {
          await api("DELETE", `/invites/${i.id}`);
          reload();
        } catch (error) {
          ctx.report(problemText(error));
        }
      });
      return el(
        "div",
        { class: "card row" },
        el("span", { class: "grow" }, i.note ? `Invitation for ${i.note}` : "An invitation", el("span", { class: "faint" }, ` (${i.role === "owner" ? "another owner" : "a member"}, valid until ${new Date(i.expiresAt).toLocaleDateString()})`)),
        cancel,
      );
    });
    waiting.replaceChildren(...(items.length ? [el("h2", {}, "Waiting to join"), ...items] : []));
  }

  await reload();
}
