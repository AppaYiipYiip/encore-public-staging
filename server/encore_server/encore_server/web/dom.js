// Small helpers for the admin pages (docs/36 section 2). Everything that comes from the server is written into the page as text: there is no way in this file to
// write markup, on purpose (a person's name is data, not HTML).

const SVG = "http://www.w3.org/2000/svg";

export function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "class") node.className = value;
    else if (value === true) node.setAttribute(name, "");
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(name, value);
  }
  for (const child of children) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}

// The few pictures the pages use: 24 by 24, drawn with a line, in the colour of the text around them.
const ICONS = {
  people: ["circle:12:8:4", "M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"],
  "user-plus": ["circle:10:8:4", "M2 21c0-4.4 3.4-7 8-7", "M18 8v6", "M15 11h6"],
  key: ["circle:8:15:4", "M11 12l9-9", "M16 7l3 3", "M14 9l2 2"],
  more: ["circle:5:12:1.4", "circle:12:12:1.4", "circle:19:12:1.4"],
  logout: ["M10 4H5v16h5", "M15 8l4 4-4 4", "M19 12H9"],
  copy: ["rect", "M5 15V5a1 1 0 0 1 1-1h10"],
  lock: ["rect2", "M8 11V8a4 4 0 0 1 8 0v3"],
  check: ["M5 12l5 5 9-10"],
};

export function icon(name) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "ic");
  svg.setAttribute("aria-hidden", "true");
  for (const part of ICONS[name] || []) {
    let shape;
    if (part.startsWith("circle:")) {
      const [, cx, cy, r] = part.split(":");
      shape = document.createElementNS(SVG, "circle");
      shape.setAttribute("cx", cx);
      shape.setAttribute("cy", cy);
      shape.setAttribute("r", r);
    } else if (part === "rect" || part === "rect2") {
      shape = document.createElementNS(SVG, "rect");
      const box = part === "rect" ? [9, 9, 11, 11] : [5, 11, 14, 10];
      ["x", "y", "width", "height"].forEach((key, i) => shape.setAttribute(key, box[i]));
      shape.setAttribute("rx", "2");
    } else {
      shape = document.createElementNS(SVG, "path");
      shape.setAttribute("d", part);
    }
    svg.append(shape);
  }
  return svg;
}

// "today", "yesterday", "12 days ago": the words the People page uses for when somebody last signed in.
export function ago(ms, now = Date.now()) {
  if (ms === null || ms === undefined) return null;
  const days = Math.floor((startOfDay(now) - startOfDay(ms)) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return days + " days ago";
}

function startOfDay(ms) {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

// A name has one of six colours, always the same one (a class, never a style written into the page).
export function colourOf(name) {
  let sum = 0;
  for (const ch of String(name)) sum = (sum + ch.charCodeAt(0)) % 6;
  return "av-" + sum;
}

// A sheet in front of the page: a native dialog (it traps the keyboard and closes on Escape by itself). The first action is what the keyboard finds first,
// which for a question that cannot be undone is Cancel.
export function sheet(title, body, actions) {
  const dialog = el("dialog", { class: "sheet", "aria-labelledby": "sheet-title" });
  const row = el("div", { class: "row end" });
  for (const action of actions) {
    const button = el("button", { type: "button", class: action.kind || "" }, action.label);
    button.addEventListener("click", async () => {
      button.disabled = true;
      let keep = false;
      try {
        keep = action.run ? (await action.run()) === false : false;
      } finally {
        button.disabled = false;
      }
      if (!keep) dialog.close();
    });
    row.append(button);
  }
  dialog.append(el("h2", { id: "sheet-title" }, title), body, row);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

// Copying: the page is on a home address that is not a secure context, where the clipboard API is not offered, so the text is also selectable in a field.
export async function copyText(text, field) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the selection below
  }
  field.focus();
  field.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  }
}
