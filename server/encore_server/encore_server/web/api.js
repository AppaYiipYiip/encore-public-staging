// The admin site's one way to talk to its server (docs/36 section 2). The device token lives in sessionStorage: it goes when the tab closes, the page never
// writes it anywhere else, and every request carries it as a bearer token (no cookie, so nothing here can be made to act by another site).

const BASE = "/encore/api/v1";
const KEY = "encore.admin.token";

export class Problem extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function hasSession() {
  return sessionStorage.getItem(KEY) !== null;
}

export async function api(method, path, body) {
  const headers = { Accept: "application/json" };
  const token = sessionStorage.getItem(KEY);
  if (token !== null) headers.Authorization = "Bearer " + token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
    });
  } catch {
    throw new Problem(0, "offline", "Your server did not answer. Check that it is on, then try again.");
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    if (response.status === 401) sessionStorage.removeItem(KEY);
    const error = data && data.error ? data.error : {};
    throw new Problem(response.status, error.code || "error", error.message || "Something went wrong.");
  }
  return data;
}

// A browser device: the server ends it after 12 hours unused or 7 days in all, whatever this tab says (docs/36 section 2).
export async function signIn(username, password) {
  const data = await api("POST", "/auth/login", { username, password, deviceName: "Browser (admin pages)", deviceKind: "web" });
  sessionStorage.setItem(KEY, data.deviceToken);
  return data;
}

export async function signOut() {
  try {
    await api("POST", "/auth/logout");
  } catch {
    // The device is gone on the server already, or the server is not there: either way this tab forgets it.
  }
  sessionStorage.removeItem(KEY);
}
