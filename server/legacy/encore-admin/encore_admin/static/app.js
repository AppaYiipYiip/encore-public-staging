'use strict';
/* The admin website. No framework, nothing loaded from the internet. Every text from the server is put in with textContent
   (never as markup), so a name somebody typed cannot run as script. */

const app = document.getElementById('app');
let me = null;
let poller = null;

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(method, path, body) {
  let res;
  try {
    res = await fetch('/admin/api' + path, {
      method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Encore-Admin': '1' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    return { ok: false, status: 0, data: { message: 'This page could not reach the server. Try again in a moment.' } };
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* an empty answer */ }
  if (res.status === 401 && path !== '/login' && path !== '/logout') {
    me = null;
    render();
  }
  return { ok: res.ok, status: res.status, data };
}

const clock = (seconds) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const day = (seconds) => new Date(seconds * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' });

function stopPolling() {
  if (poller) { clearInterval(poller); poller = null; }
}

// ---------------------------------------------------------------------------------------------------------- sign in

function loginView() {
  const error = h('p', { class: 'error', role: 'alert' });
  const user = h('input', { type: 'text', id: 'user', autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false', required: true });
  const pass = h('input', { type: 'password', id: 'pass', autocomplete: 'current-password', required: true });
  const button = h('button', { class: 'primary', type: 'submit' }, 'Sign in');
  const form = h('form', {
    onsubmit: async (event) => {
      event.preventDefault();
      button.disabled = true;
      error.textContent = '';
      const r = await api('POST', '/login', { user: user.value, password: pass.value });
      button.disabled = false;
      if (r.ok) { me = r.data; pass.value = ''; location.hash = '#/today'; render(); }
      else error.textContent = r.data.message || 'That did not work.';
    },
  }, h('label', { for: 'user' }, 'Name'), user, h('label', { for: 'pass' }, 'Password'), pass, error, button);
  return h('div', { class: 'login' },
    h('h1', { text: 'Encore' }),
    h('p', { class: 'muted' }, 'Sign in with the same name and password you use in the app. Only owners can manage this server.'),
    form);
}

// ---------------------------------------------------------------------------------------------------------- the frame

function shell(route, content) {
  const link = (name, label) => h('a', { href: '#/' + name, 'aria-current': route === name ? 'page' : null }, label);
  return h('div', null,
    h('header', { class: 'bar' },
      h('div', { class: 'brand' }, 'Encore', h('span', { text: me && me.server && me.server !== 'Encore' ? me.server : 'admin' })),
      h('nav', null, link('today', 'Today'), link('people', 'People'), link('quality', 'Quality'), link('recs', 'Suggestions'), link('youtube', 'YouTube'), link('parts', 'Parts')),
      h('button', { class: 'small', onclick: async () => { await api('POST', '/logout', {}); me = null; render(); } }, 'Sign out')),
    h('main', null, content));
}

// ---------------------------------------------------------------------------------------------------------- Today

async function todayView(main) {
  main.append(h('h1', { text: 'Today' }));
  const holder = h('div');
  main.append(holder);
  const r = await api('GET', '/today');
  if (!r.ok) { holder.append(h('p', { class: 'problem', text: r.data.message || 'Could not load this.' })); return; }
  const t = r.data;
  const needs = t.needsYou || [];
  holder.append(h('p', { class: 'lead', text: needs.length ? (needs.length === 1 ? 'One thing needs you.' : needs.length + ' things need you.') : 'Everything is working.' }));
  for (const item of needs) {
    holder.append(h('a', { class: 'card', href: item.link }, h('div', { class: 'row' }, h('span', { class: 'dot needs_you' }), h('span', { class: 'grow', text: item.text }), h('span', { class: 'faint', text: 'Open' }))));
  }
  if (t.people) {
    holder.append(h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'dot working' }), h('h2', { class: 'grow', text: 'People' })),
      h('p', { class: 'muted', text: t.people.count + (t.people.count === 1 ? ' person' : ' people') + ' on this server.' }),
      h('div', { class: 'actions' }, h('a', { class: 'button', href: '#/people' }, 'Manage'))));
  }
  if (t.address) {
    holder.append(h('div', { class: 'card' },
      h('h2', { text: 'The address for the app' }),
      h('p', { class: 'muted', text: 'Type this in the app to connect from anywhere:' }),
      h('p', null, h('code', { text: t.address }))));
  }
  if (t.quality) {
    const counts = t.quality.counts || {};
    const done = counts.ready || 0;
    const waiting = (counts.queued || 0) + (counts.getting_ready || 0) + (counts.searching || 0) + (counts.downloading || 0) + (counts.delivering || 0);
    holder.append(h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'dot ' + (t.quality.soulseek ? 'working' : 'off') }), h('h2', { class: 'grow', text: 'Best quality' })),
      h('p', { class: 'muted', text: t.quality.soulseek
        ? done + (done === 1 ? ' song' : ' songs') + ' upgraded, ' + waiting + ' being looked for.'
        : 'Switched off. Nothing is sent to the Soulseek network until you switch it on.' }),
      h('div', { class: 'actions' }, h('a', { class: 'button' + (t.quality.soulseek ? '' : ' primary'), href: '#/quality' }, t.quality.soulseek ? 'Manage' : 'Set up'))));
  }
  const y = t.youtube;
  if (y) {
    const signed = y.signedIn;
    const usable = y.accounts.filter((a) => a.state !== 'needs_you').length;
    const perHour = y.perHour !== null && y.perHour !== undefined ? y.perHour : y.visitorPerHour;
    const lines = y.accounts.map((a) => h('div', { class: 'row account-line' },
      h('span', { class: 'dot ' + a.state }), h('span', { class: 'grow', text: a.label }),
      h('span', { class: 'muted', text: a.thisHour + ' of ' + a.perHourAllowed + ' this hour' })));
    holder.append(h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'dot ' + (signed ? 'working' : '') }), h('h2', { class: 'grow', text: 'YouTube' })),
      h('p', { class: 'muted' }, signed
        ? 'Signed in with ' + usable + (usable === 1 ? ' account' : ' accounts') + '. Imports run at about ' + perHour + ' songs an hour.'
        : 'Not signed in. Imports run at about ' + y.visitorPerHour + ' songs an hour, and age-restricted songs cannot be fetched.'),
      lines,
      h('div', { class: 'actions' }, h('a', { class: 'button' + (signed ? '' : ' primary'), href: '#/youtube' }, signed ? 'Manage' : 'Sign in to YouTube'))));
  }
  if (t.parts && t.parts.length) {
    holder.append(h('div', { class: 'card' }, h('h2', { text: 'What is running' }),
      t.parts.map((p) => h('div', { class: 'row account-line' },
        h('span', { class: 'dot ' + p.state }), h('span', { class: 'grow', text: p.name }),
        h('span', { class: 'muted', text: p.note })))));
  }
}

// ---------------------------------------------------------------------------------------------------------- YouTube

const PACE_NAMES = { gentle: 'Gentle', normal: 'Normal', fast: 'Fast' };

async function youtubeView(main) {
  const state = {
    summary: null, signin: null, note: null, error: null, editing: null, confirming: null, label: '', shown: '',
    streak: 0, saving: false, checks: {}, checking: {},
  };
  main.append(h('h1', { text: 'YouTube' }),
    h('p', { class: 'lead', text: "Signing in lifts YouTube's limit from about 300 to about 2,000 songs an hour and lets Encore fetch age-restricted songs. Use an account you can afford to lose, not your main one." }));
  const holder = h('div');
  // Three boxes that are drawn on their own: the sign-in panel holds a live browser, and redrawing it would reload that browser and
  // throw the half-finished sign-in away, so it is redrawn only when its *stage* really changes.
  const top = h('div');
  const panelBox = h('div');
  const list = h('div');
  holder.append(top, panelBox, list);
  main.append(holder);
  let stageShown = null;
  const nodes = {};

  function stageOf(s) {
    if (!s) return 'none';
    if (s.state === 'failed') return 'failed';
    if (state.saving || s.state === 'signed_in') return 'saving';
    if (s.state === 'preparing' || s.state === 'starting' || !s.ready) return s.state === 'preparing' ? 'preparing' : 'starting';
    return 'window';
  }

  function updateStatus() {
    // what changes while the window is open, changed in place
    if (nodes.status && state.signin) nodes.status.textContent = 'Waiting for you to sign in…';
    if (nodes.detail && state.signin) nodes.detail.textContent = state.signin.detail || '';
  }

  async function load() {
    const r = await api('GET', '/youtube');
    if (r.ok) { state.summary = r.data; state.error = null; } else state.error = r.data.message || 'Could not load this.';
    const s = await api('GET', '/youtube/signin');
    state.signin = s.ok && s.data.state && s.data.state !== 'gone' ? s.data : null;
    draw();
    keepWatching();
  }

  function keepWatching() {
    stopPolling();
    if (!state.signin) return;
    poller = setInterval(async () => {
      if (!state.signin || state.saving) return;
      const r = await api('GET', '/youtube/signin/' + state.signin.window);
      if (!r.ok) return;
      if (r.data.state === 'gone') { state.signin = null; stopPolling(); await load(); return; }
      const before = stageOf(state.signin);
      state.signin = { ...state.signin, ...r.data };
      // Signed in for two looks in a row (a few seconds): save it by itself, nobody has to press anything.
      state.streak = r.data.state === 'signed_in' ? state.streak + 1 : 0;
      if (state.streak >= 2) { await finish(); return; }
      if (before !== stageOf(state.signin)) draw();
      else if (before === 'window') updateStatus();
    }, 3000);
  }

  async function startSignin(replace) {
    state.note = null;
    state.streak = 0;
    const r = await api('POST', '/youtube/signin', replace ? { replace } : {});
    if (r.ok) { state.signin = r.data; state.label = ''; draw(); keepWatching(); }
    else { state.error = r.data.message || 'Could not open the sign-in window.'; draw(); }
  }

  async function act(method, path, body, after) {
    const r = await api(method, path, body);
    if (r.ok) { state.summary = r.data; state.error = null; if (after) after(r.data); }
    else state.error = r.data.message || 'That did not work.';
    draw();
    return r;
  }

  async function runCheck(id) {
    state.checking[id] = true;
    delete state.checks[id];
    draw();
    const r = await api('POST', '/youtube/accounts/' + id + '/test', {});
    delete state.checking[id];
    state.checks[id] = r.ok ? r.data : { ok: false, message: r.data.message || 'The check did not run.' };
    draw();
  }

  async function finish() {
    const s = state.signin;
    if (!s || state.saving) return;
    state.saving = true;
    stopPolling();
    draw();
    const known = new Set(((state.summary && state.summary.accounts) || []).map((a) => a.id));
    const label = s.replace ? '' : (state.label || '');
    const r = await api('POST', '/youtube/signin/' + s.window + '/finish', { label });
    state.saving = false;
    if (r.ok) {
      state.summary = r.data; state.signin = null; state.error = null; state.streak = 0;
      const fresh = r.data.accounts.find((a) => s.replace ? a.id === s.replace : !known.has(a.id));
      state.note = fresh ? 'Signed in as ' + (fresh.email || fresh.label) + '. Imports now use this account.' : 'Signed in.';
      draw();
      if (fresh) runCheck(fresh.id);
      return;
    }
    state.error = r.data.message || 'That did not work.';
    state.streak = 0;
    draw();
    keepWatching();
  }

  async function closeSignin() {
    const s = state.signin;
    stopPolling();
    state.saving = false;
    if (s) await api('POST', '/youtube/signin/' + s.window + '/cancel', {});
    state.signin = null; state.streak = 0; draw();
  }

  function accountCard(a) {
    const word = a.state === 'working' ? 'Working' : a.state === 'resting' ? 'Resting until ' + clock(a.restUntil) : 'Needs you';
    const body = [];
    if (state.editing === a.id) {
      const input = h('input', { type: 'text', value: a.label, maxlength: '40', 'aria-label': 'Account name' });
      body.push(h('div', { class: 'row' }, input,
        h('button', { class: 'small primary', onclick: () => { state.editing = null; act('POST', '/youtube/accounts/' + a.id, { label: input.value }); } }, 'Save'),
        h('button', { class: 'small', onclick: () => { state.editing = null; draw(); } }, 'Cancel')));
    } else {
      body.push(h('div', { class: 'row' }, h('span', { class: 'dot ' + a.state }), h('strong', { class: 'grow', text: a.label }),
        h('span', { class: 'state', text: word })));
      if (a.email && a.email !== a.label) body.push(h('div', { class: 'faint who', text: a.name ? a.name + ' · ' + a.email : a.email }));
    }
    if (a.message) body.push(h('p', { class: a.state === 'needs_you' ? 'problem' : 'note', text: a.message }));
    body.push(h('div', { class: 'numbers' },
      h('div', null, h('b', { text: a.thisHour + ' of ' + a.perHourAllowed }), h('span', { text: 'this hour' })),
      h('div', null, h('b', { text: String(a.day) }), h('span', { text: 'last 24 hours' })),
      h('div', null, h('b', { text: String(a.refusalsDay) }), h('span', { text: 'refused' })),
      h('div', null, h('b', { text: day(a.signedInSince) }), h('span', { text: 'signed in' }))));
    if (a.day === 0 && a.state === 'working') {
      body.push(h('p', { class: 'faint', text: 'Not used yet: the next song your server fetches or imports will use it. The numbers above count songs fetched with this account.' }));
    }
    const check = state.checks[a.id];
    if (state.checking[a.id]) {
      body.push(h('div', { class: 'row' }, h('span', { class: 'spinner' }), h('span', { class: 'muted', text: 'Checking with YouTube…' })));
    } else if (check) {
      body.push(h('p', { class: check.ok ? 'state' : 'problem', text: (check.ok ? '✓ ' : '⚠ ') + check.message }));
    }
    const paces = (state.summary.paces) || {};
    body.push(h('div', { class: 'row' },
      h('div', { class: 'segmented', role: 'group', 'aria-label': 'Pace' }, ['gentle', 'normal', 'fast'].map((p) =>
        h('button', { 'aria-pressed': String(a.pace === p), title: (paces[p] || '') + ' songs an hour at most',
          onclick: () => act('POST', '/youtube/accounts/' + a.id, { pace: p }) }, PACE_NAMES[p]))),
      h('span', { class: 'grow' }),
      a.state === 'needs_you' ? h('button', { class: 'primary', onclick: () => startSignin(a.id) }, 'Sign in again') : null,
      h('button', { class: 'small', onclick: () => runCheck(a.id), disabled: !!state.checking[a.id] }, 'Check'),
      h('button', { class: 'small', onclick: () => { state.editing = a.id; draw(); } }, 'Rename'),
      h('button', { class: 'small danger', onclick: () => { state.confirming = a.id; draw(); } }, 'Sign out')));
    if (state.confirming === a.id) {
      body.push(h('div', { class: 'card quiet' },
        h('p', { text: 'Sign out of ' + a.label + '? This deletes its sign-in from your server. Imports go on with the other accounts, or at the visitor limit.' }),
        h('div', { class: 'row' },
          h('button', { class: 'danger', onclick: async () => {
            state.confirming = null;
            await act('POST', '/youtube/accounts/' + a.id + '/signout', {}, () => {
              state.note = 'Signed out. To end the session at Google as well, open your Google devices list.';
            });
          } }, 'Sign out'),
          h('button', { onclick: () => { state.confirming = null; draw(); } }, 'Keep it'))));
    }
    return h('div', { class: 'card' }, body);
  }

  function signinPanel(s) {
    const lines = [];
    if (s.state === 'failed') {
      lines.push(h('h2', { text: 'The sign-in window did not open' }));
      lines.push(h('p', { class: 'problem', text: s.message || 'Try again.' }));
      lines.push(h('div', { class: 'row' }, h('button', { class: 'primary', onclick: async () => { await closeSignin(); startSignin(s.replace); } }, 'Try again'), h('button', { onclick: () => closeSignin() }, 'Close')));
    } else if (s.state === 'preparing' || s.state === 'starting' || !s.ready) {
      const first = s.state === 'preparing';
      lines.push(h('div', { class: 'row' }, h('span', { class: 'spinner' }), h('h2', { class: 'grow', text: first ? 'Getting the sign-in window ready' : 'Opening the sign-in window' })));
      lines.push(h('p', { class: 'muted', text: first
        ? 'The first time, this downloads a small browser (about 330 MB), so it can take a few minutes on a slow connection. You can leave this page; it carries on.'
        : 'Almost there.' }));
      lines.push(h('div', { class: 'row' }, h('button', { onclick: () => closeSignin() }, 'Cancel')));
    } else {
      const signedIn = s.state === 'signed_in' || state.saving;
      lines.push(h('h2', { text: 'Sign in to Google' }));
      lines.push(h('p', { class: 'muted', text: 'This is a private browser running on your server. Sign in to Google here, the way you normally would. When you are signed in, this page saves it by itself.' }));
      if (!signedIn) lines.push(h('iframe', { class: 'window', src: s.path, title: 'Sign in to Google, in a private browser on your server', allow: 'clipboard-read; clipboard-write; fullscreen' }));
      nodes.status = null;
      nodes.detail = null;
      if (signedIn) {
        lines.push(h('div', { class: 'row' }, h('span', { class: 'spinner' }), h('span', { class: 'state', text: state.saving ? '✓ Signed in. Saving…' : '✓ Signed in. Saving in a moment…' })));
      } else {
        nodes.status = h('p', { class: 'muted', text: 'Waiting for you to sign in…' });
        nodes.detail = h('p', { class: 'faint', text: s.detail || '' });
        lines.push(nodes.status, nodes.detail);
      }
      if (!s.replace && !signedIn) {
        lines.push(h('label', { for: 'acct-name' }, 'Name this account (optional)'));
        lines.push(h('input', { type: 'text', id: 'acct-name', maxlength: '40', placeholder: "Leave empty to use the account's email", value: state.label || '',
          oninput: (e) => { state.label = e.target.value; } }));
      }
      lines.push(h('div', { class: 'row actions' },
        h('button', { onclick: () => closeSignin(), disabled: state.saving }, 'Cancel'),
        h('span', { class: 'faint grow', text: 'This window closes by itself at ' + clock(s.expiresAt) + '.' })));
    }
    return h('div', { class: 'card' }, lines);
  }

  function drawTop() {
    top.replaceChildren();
    const sum = state.summary;
    if (!sum) { top.append(h('p', { class: state.error ? 'problem' : 'muted', text: state.error || 'Loading…' })); return; }
    // While every account rests the queue goes at the visitor's pace, so that is the number to say.
    const accountsCarry = sum.perHour !== null && sum.perHour !== undefined;
    const rate = accountsCarry ? sum.perHour : sum.visitorPerHour;
    top.append(h('p', { class: 'state', text: 'Imports are running at about ' + rate + ' songs an hour' + (sum.signedIn && !accountsCarry ? ' (the accounts are resting).' : '.') }));
    if (state.error) top.append(h('p', { class: 'problem', role: 'alert', text: state.error }));
    if (state.note) {
      top.append(h('p', { class: 'note' }, state.note + ' ',
        state.note.startsWith('Signed out') ? h('a', { href: 'https://myaccount.google.com/device-activity', target: '_blank', rel: 'noopener' }, 'Open Google devices') : null));
    }
  }

  function drawList() {
    list.replaceChildren();
    const sum = state.summary;
    if (!sum) return;
    for (const a of sum.accounts) list.append(accountCard(a));
    list.append(advanced());
  }

  function drawPanel() {
    const sum = state.summary;
    panelBox.replaceChildren();
    if (state.signin) { panelBox.append(signinPanel(state.signin)); return; }
    if (!sum) return;
    panelBox.append(h('div', { class: 'row actions' }, h('button', { class: 'primary', onclick: () => startSignin(null) }, sum.accounts.length ? 'Add another account' : 'Sign in to YouTube')));
    if (!sum.accounts.length) {
      panelBox.append(h('p', { class: 'muted', text: 'Nobody is signed in yet. Everything still works, at the visitor limit. You never type a password into this page: you sign in on the Google page itself, in a private browser on your server.' }));
    }
  }

  function draw(forcePanel) {
    state.shown = stageOf(state.signin);
    drawTop();
    drawList();
    const stage = state.signin ? stageOf(state.signin) : 'none';
    if (forcePanel || stage !== stageShown || !state.summary || stage === 'none') {
      stageShown = stage;
      drawPanel();
    }
  }

  function advanced() {
    const cookies = h('textarea', { id: 'cookies', spellcheck: 'false', placeholder: '# Netscape HTTP Cookie File ...' });
    const label = h('input', { type: 'text', id: 'adv-label', maxlength: '40', value: 'YouTube account' });
    const file = h('input', { type: 'file', accept: '.txt,text/plain', 'aria-label': 'cookies.txt file',
      onchange: async (e) => { const f = e.target.files[0]; if (f && f.size < 400000) cookies.value = await f.text(); } });
    return h('details', null, h('summary', { text: 'Advanced: use a cookies file instead' }),
      h('p', { class: 'muted', text: 'A cookies file is a copy of a signed-in browser session. Most people should use the sign-in window above, which never asks you to export anything.' }),
      h('label', { for: 'adv-label' }, 'Name'), label, h('label', null, 'cookies.txt'), file, cookies,
      h('div', { class: 'row' }, h('button', { onclick: () => act('POST', '/youtube/accounts', { label: label.value, cookies: cookies.value }, () => { cookies.value = ''; }) }, 'Add account')));
  }

  await load();
}

// ---------------------------------------------------------------------------------------------------------- People

const ROLE_NAMES = { owner: 'Owner', inviter: 'Can invite', guest: 'Guest' };

function ago(seconds) {
  if (!seconds) return 'not yet';
  const days = Math.floor((Date.now() / 1000 - seconds) / 86400);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 45) return days + ' days ago';
  return Math.round(days / 30) + ' months ago';
}

// A secret the owner has to read out or send once: shown big, selectable, with a Copy button (which falls back to selecting it).
function secretBox(text) {
  const code = h('span', { class: 'secret big', text });
  const copy = h('button', { class: 'small', onclick: async () => {
    try { await navigator.clipboard.writeText(text); copy.textContent = 'Copied'; }
    catch (e) { const r = document.createRange(); r.selectNodeContents(code); const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r); copy.textContent = 'Selected: press Ctrl+C'; }
  } }, 'Copy');
  return h('div', { class: 'row' }, code, copy);
}

async function peopleView(main) {
  const state = { data: null, error: null, notes: {}, confirming: null, resetting: null, added: null, invite: null, newRole: 'guest' };
  main.append(h('h1', { text: 'People' }),
    h('p', { class: 'lead', text: 'Everybody who can listen on this server. Each person has their own library, their own playlists and their own password; you can see who is here and look after their accounts, never what they play.' }));
  const holder = h('div');
  main.append(holder);

  async function load() {
    const r = await api('GET', '/people');
    if (r.ok) { state.data = r.data; state.error = null; } else state.error = r.data.message || r.data.error || 'Could not load this.';
    draw();
  }

  async function act(path, body, then) {
    const r = await api('POST', path, body || {});
    if (r.ok) { if (then) then(r.data); await load(); }
    else { state.error = r.data.error || r.data.message || 'That did not work.'; draw(); }
    return r;
  }

  function secretNote(person, data) {
    state.notes[person] = data.temporaryPassword
      ? { kind: 'temp', text: data.temporaryPassword }
      : { kind: 'link', text: data.url || data.code, hasUrl: !!data.url, expires: data.expiresAt };
  }

  function requestCard(r) {
    return h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'dot needs_you' }), h('strong', { class: 'grow', text: r.user + ' asked for a new password' }),
        h('span', { class: 'faint', text: ago(r.askedAt) })),
      h('p', { class: 'muted', text: 'Send them a one-time link, or give them a temporary password to read out. They will be asked to choose their own.' }),
      h('div', { class: 'row' },
        h('button', { class: 'primary', onclick: () => act('/people/' + r.user + '/password', { mode: 'link' }, (d) => secretNote(r.user, d)) }, 'Send a link'),
        h('button', { onclick: () => act('/people/' + r.user + '/password', { mode: 'temporary' }, (d) => secretNote(r.user, d)) }, 'Temporary password'),
        h('button', { class: 'small', onclick: () => act('/resets/' + r.user + '/dismiss') }, 'Dismiss')));
  }

  function noteBox(person) {
    const note = state.notes[person];
    if (!note) return null;
    if (note.kind === 'temp') {
      return h('div', { class: 'card quiet' },
        h('p', { text: 'Their temporary password (shown once; they will be asked to choose their own the first time they sign in):' }),
        secretBox(note.text));
    }
    return h('div', { class: 'card quiet' },
      h('p', { text: note.hasUrl ? 'Send them this link. It works once, for an hour (until ' + clock(note.expires) + '):' : 'Your server has no public address, so there is no link to send. Give them this code instead; it works once, for an hour:' }),
      secretBox(note.text));
  }

  function personCard(p) {
    const body = [];
    const pills = [h('span', { class: 'pill', text: ROLE_NAMES[p.role] || p.role })];
    if (p.paused) pills.push(h('span', { class: 'pill warn', text: 'Paused' }));
    if (p.mustChange) pills.push(h('span', { class: 'pill', text: 'Has a temporary password' }));
    body.push(h('div', { class: 'row' }, h('span', { class: 'avatar', text: p.user.slice(0, 1).toUpperCase() }),
      h('strong', { class: 'grow', text: p.user }), pills));
    const where = p.fixed ? 'Founding owner' : p.invitedBy ? 'Invited by ' + p.invitedBy + (p.joinedAt ? ' on ' + day(p.joinedAt) : '')
      : p.createdAt ? 'Joined ' + day(p.createdAt) : '';
    body.push(h('div', { class: 'faint who', text: [where, 'Last here ' + ago(p.lastAccess)].filter(Boolean).join(' · ') }));
    if (p.resetAsked) body.push(h('p', { class: 'note', text: 'Asked for a new password ' + ago(p.resetAsked) + '.' }));
    const nb = noteBox(p.user);
    if (nb) body.push(nb);
    if (state.resetting === p.user) {
      body.push(h('div', { class: 'card quiet' },
        h('p', { text: 'Reset ' + p.user + "'s password:" }),
        h('div', { class: 'row' },
          h('button', { class: 'primary', onclick: () => { state.resetting = null; act('/people/' + p.user + '/password', { mode: 'link' }, (d) => secretNote(p.user, d)); } }, 'One-time link'),
          h('button', { onclick: () => { state.resetting = null; act('/people/' + p.user + '/password', { mode: 'temporary' }, (d) => secretNote(p.user, d)); } }, 'Temporary password'),
          h('button', { class: 'small', onclick: () => { state.resetting = null; draw(); } }, 'Cancel'))));
    }
    if (state.confirming && state.confirming.person === p.user) {
      const remove = state.confirming.what === 'remove';
      body.push(h('div', { class: 'card quiet' },
        h('p', { text: remove
          ? 'Remove ' + p.user + '? Their account is deleted and what they handed out stops working. Their music files are not deleted.'
          : 'Lock ' + p.user + "'s account? They cannot sign in until you reset their password." }),
        h('div', { class: 'row' },
          h('button', { class: 'danger', onclick: () => { state.confirming = null; act('/people/' + p.user + (remove ? '/remove' : '/lock')); } }, remove ? 'Remove' : 'Lock'),
          h('button', { onclick: () => { state.confirming = null; draw(); } }, 'Keep'))));
    }
    if (!p.fixed) {
      const role = h('select', { 'aria-label': 'Role of ' + p.user, onchange: (e) => act('/people/' + p.user + '/role', { role: e.target.value }) },
        ['guest', 'inviter', 'owner'].map((r) => h('option', { value: r, selected: p.role === r ? true : null }, ROLE_NAMES[r])));
      body.push(h('div', { class: 'row actions' },
        h('button', { class: 'small', onclick: () => { state.resetting = p.user; state.confirming = null; draw(); } }, 'Reset password'),
        role,
        p.paused ? h('button', { class: 'small', onclick: () => act('/people/' + p.user + '/unlock', {}, (d) => secretNote(p.user, d)) }, 'Unlock')
          : h('button', { class: 'small', onclick: () => { state.confirming = { person: p.user, what: 'lock' }; state.resetting = null; draw(); } }, 'Lock'),
        h('span', { class: 'grow' }),
        h('button', { class: 'small danger', onclick: () => { state.confirming = { person: p.user, what: 'remove' }; state.resetting = null; draw(); } }, 'Remove')));
    }
    return h('div', { class: 'card' }, body);
  }

  function addCard() {
    const name = h('input', { type: 'text', id: 'new-name', placeholder: 'a name, in lower case letters', autocapitalize: 'none', spellcheck: 'false', maxlength: '32' });
    const role = h('select', { id: 'new-role', 'aria-label': 'What they may do' }, h('option', { value: 'guest' }, 'Guest: listens'), h('option', { value: 'inviter' }, 'Can invite others'));
    const result = state.added ? h('div', { class: 'card quiet' },
      h('p', { text: state.added.user + ' can sign in now, with the name ' + state.added.user + ' and this temporary password (shown once; they will be asked to choose their own):' }),
      secretBox(state.added.temporaryPassword)) : null;
    return h('div', { class: 'card' }, h('h2', { text: 'Add a person' }),
      h('p', { class: 'muted', text: 'Make an account yourself: you give them the name and a temporary password. No link and no public address needed.' }),
      h('div', { class: 'row' }, name, role,
        h('button', { class: 'primary', onclick: async () => {
          state.added = null;
          const r = await act('/people', { name: name.value.trim().toLowerCase(), role: role.value }, (d) => { state.added = d; });
          if (!r.ok) draw();
        } }, 'Add person')),
      result);
  }

  function inviteCard() {
    const d = state.data;
    if (!d.inviteLinks) {
      return h('div', { class: 'card quiet' }, h('h2', { text: 'Invite by link' }),
        h('p', { class: 'muted', text: 'An invitation is a link a friend opens on their phone, so it needs your server to have an address people can reach from outside (remote access). Until then, add people above.' }));
    }
    const role = h('select', { 'aria-label': 'What they may do' }, h('option', { value: 'guest' }, 'Guest: listens'), h('option', { value: 'inviter' }, 'Can invite others'));
    const made = state.invite ? h('div', { class: 'card quiet' },
      h('p', { text: 'Send them this link. It works once, for a few days:' }), secretBox(state.invite.url)) : null;
    const open = d.invites.map((i) => h('div', { class: 'row account-line' },
      h('span', { class: 'grow', text: 'Open invitation for a ' + (ROLE_NAMES[i.role] || i.role).toLowerCase() + (i.createdAt ? ', made ' + ago(i.createdAt) : '') }),
      h('button', { class: 'small', onclick: () => act('/invites/' + i.id + '/revoke') }, 'Cancel it')));
    return h('div', { class: 'card' }, h('h2', { text: 'Invite by link' }),
      h('p', { class: 'muted', text: 'A friend opens the link on their phone, chooses their own name and password, and is in. You see who invited whom below.' }),
      h('div', { class: 'row' }, role,
        h('button', { class: 'primary', onclick: () => { state.invite = null; act('/invites', { role: role.value }, (x) => { state.invite = x; }); } }, 'Make a link')),
      made, open);
  }

  function draw() {
    holder.replaceChildren();
    if (!state.data) { holder.append(h('p', { class: state.error ? 'problem' : 'muted', text: state.error || 'Loading…' })); return; }
    if (state.error) holder.append(h('p', { class: 'problem', role: 'alert', text: state.error }));
    if (state.data.library) {
      holder.append(h('p', { class: 'faint', text: state.data.library === 'shared'
        ? 'On this server everybody shares one music library. Each person still has their own playlists, likes, listening history and password.'
        : 'On this server each person has a private library of their own, plus the shared one.' }));
    }
    for (const r of state.data.requests) holder.append(requestCard(r));
    for (const p of state.data.people) holder.append(personCard(p));
    holder.append(addCard(), inviteCard());
  }

  await load();
}

// ---------------------------------------------------------------------------------------------------------- Music quality

const SOULSEEK_NOTICE = [
  'Soulseek is a network of people who share music with each other. When Encore asks it for a song, the people it downloads from can see this server\u2019s internet address.',
  'Copyright rules are different in every country, and what is fetched is up to you: Encore only ever asks for songs that someone on this server already has.',
  'Nothing from your library is shared with the network.',
];

const CHECK_DOT = { ok: 'working', problem: 'down', off: 'off' };

async function qualityView(main) {
  main.append(h('h1', { text: 'Music quality' }),
    h('p', { class: 'lead', text: 'Encore plays a song from YouTube the moment somebody asks for it. With best quality switched on it also looks for the same song in lossless quality and swaps it in when it finds it. That can take minutes, days or never: a lot of music is simply not shared.' }));
  const holder = h('div');
  main.append(holder);
  const state = { summary: null, installed: true, error: null, test: null, testing: false, saved: null, busy: false };

  async function load() {
    const r = await api('GET', '/quality');
    if (!r.ok) { state.error = r.data.message || 'Could not load this.'; }
    else if (r.data.installed === false) { state.installed = false; state.error = null; }
    else { state.installed = true; state.summary = r.data; state.error = null; if (!state.test && r.data.lastSelfTest) state.test = r.data.lastSelfTest; }
    draw();
  }

  async function change(body, note) {
    state.busy = true; state.saved = null; draw();
    const r = await api('PUT', '/quality/settings', body);
    state.busy = false;
    if (r.ok) { state.summary = r.data; state.error = null; state.saved = note; }
    else state.error = r.data.error || r.data.message || 'That did not work.';
    draw();
  }

  async function check() {
    state.testing = true; draw();
    const r = await api('POST', '/quality/selftest', {});
    state.testing = false;
    if (r.ok) state.test = r.data; else state.error = r.data.error || r.data.message || 'The check could not run.';
    draw();
  }

  async function retry(id) {
    const r = await api('POST', '/quality/requests/' + id + '/retry', {});
    if (!r.ok) state.error = r.data.error || r.data.message || 'That did not work.';
    await load();
  }

  function soulseekCard(s) {
    const on = s.settings.soulseek;
    const slskd = s.health.slskd || {};
    if (!on) {
      return h('div', { class: 'card' },
        h('div', { class: 'row' }, h('span', { class: 'dot off' }), h('h2', { class: 'grow', text: 'Soulseek is off' })),
        h('p', { class: 'muted', text: 'Nothing is sent to the network, and nothing is looked for, until you switch it on.' }),
        SOULSEEK_NOTICE.map((line) => h('p', { text: line })),
        h('div', { class: 'actions' }, h('button', { class: 'primary', disabled: state.busy, onclick: () => change({ soulseek: true }, 'Soulseek is on.') }, 'I understand, switch it on')));
    }
    const connected = slskd.connected;
    return h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'dot ' + (connected ? 'working' : 'starting') }), h('h2', { class: 'grow', text: 'Soulseek is on' })),
      h('p', { class: 'muted', text: connected
        ? 'Connected. Encore asks the network for what your people request, and shares nothing.'
        : 'Not connected yet. This is tried again every few minutes.' }),
      h('div', { class: 'actions' }, h('button', { disabled: state.busy, onclick: () => change({ soulseek: false }, 'Soulseek is off.') }, 'Switch it off')));
  }

  function progressCard(s) {
    const c = s.counts || {};
    const n = (...keys) => keys.reduce((sum, k) => sum + (c[k] || 0), 0);
    const rows = [
      ['Waiting its turn', n('queued', 'getting_ready')], ['Being looked for', n('searching', 'downloading')], ['Being put in place', n('delivering')],
      ['Now in best quality', n('ready')], ['Nobody shares them yet', n('not_found', 'no_match')],
    ];
    const total = rows.reduce((sum, r) => sum + r[1], 0) + n('failed', 'cancelled');
    return h('div', { class: 'card' }, h('h2', { text: 'How it is going' }),
      total === 0
        ? h('p', { class: 'muted', text: 'Nobody has asked for better quality yet.' })
        : rows.map(([label, count]) => h('div', { class: 'row account-line' }, h('span', { class: 'grow', text: label }), h('span', { class: 'muted', text: String(count) }))),
      h('p', { class: 'faint', text: 'Albums started today: ' + (s.today.started || 0) + ' of ' + s.today.limit + '.' + (s.freeGb !== null && s.freeGb !== undefined ? ' Free space: ' + s.freeGb + ' GB.' : '') }));
  }

  function checkCard() {
    const t = state.test;
    const headline = !t ? null : (t.ok ? 'Everything works.' : 'Something needs attention.');
    return h('div', { class: 'card' }, h('h2', { text: 'Check everything' }),
      h('p', { class: 'muted', text: 'Asks every part a plain question: is it there, is it set up, can the files be shared without a second copy. It does not download anything.' }),
      t ? h('p', { class: 'lead', text: headline }) : null,
      t ? t.checks.map((c) => h('div', { class: 'row account-line' }, h('span', { class: 'dot ' + (CHECK_DOT[c.state] || '') }), h('span', { class: 'grow', text: c.name }), h('span', { class: 'muted', text: c.note }))) : null,
      t ? h('p', { class: 'faint', text: 'Checked ' + clock(t.at) + '.' }) : null,
      h('div', { class: 'actions' }, h('button', { disabled: state.testing, onclick: check }, state.testing ? 'Checking\u2026' : 'Check everything')));
  }

  function settingsCard(s) {
    const cap = h('input', { type: 'number', id: 'cap', min: '1', max: '500', value: String(s.settings.dailyCap) });
    const free = h('input', { type: 'number', id: 'free', min: '0', max: '5000', value: String(s.settings.minFreeGb) });
    return h('div', { class: 'card' }, h('h2', { text: 'Limits' }),
      h('label', { for: 'cap' }, 'Albums to look for per day'), cap,
      h('p', { class: 'faint', text: 'A polite pace for a shared network, and a bound on what one big playlist can ask for.' }),
      h('label', { for: 'free' }, 'Keep this much space free (GB)'), free,
      h('p', { class: 'faint', text: 'When the server has less room than this, it stops asking for new albums.' }),
      h('div', { class: 'actions' }, h('button', { disabled: state.busy, onclick: () => change({ dailyCap: Number(cap.value), minFreeGb: Number(free.value) }, 'Saved.') }, 'Save')));
  }

  function troubleCard(s) {
    if (!s.trouble.length) return null;
    return h('div', { class: 'card' }, h('h2', { text: 'Songs that could not be upgraded' }),
      s.trouble.map((t) => h('div', { class: 'row account-line' },
        h('span', { class: 'grow' }, h('strong', { text: t.title }), ' ', h('span', { class: 'muted', text: t.artist }), h('div', { class: 'faint', text: t.message })),
        h('button', { class: 'small', onclick: () => retry(t.id) }, 'Try again'))));
  }

  function draw() {
    const active = document.activeElement;
    if (active && holder.contains(active) && active.tagName === 'INPUT') return;  // do not wipe what is being typed
    holder.replaceChildren();
    if (state.error) holder.append(h('p', { class: 'problem', text: state.error }));
    if (state.saved) holder.append(h('p', { class: 'good', text: state.saved }));
    if (!state.installed) {
      holder.append(h('div', { class: 'card' }, h('h2', { text: 'Best quality is not set up on this server' }),
        h('p', { class: 'muted' }, 'To add it, run ', h('code', { text: 'QUALITY=1 bash setup.sh' }), ' in the Encore folder, then come back here. It downloads about 2.5 GB the first time.')));
      return;
    }
    const s = state.summary;
    if (!s) { holder.append(h('p', { class: 'muted', text: 'Loading\u2026' })); return; }
    const parts = [soulseekCard(s), progressCard(s), checkCard(), settingsCard(s), troubleCard(s)];
    for (const part of parts) if (part) holder.append(part);
  }

  await load();
  poller = setInterval(load, 10000);
}

// ---------------------------------------------------------------------------------------------------------- Suggestions

const SURFACE_NAMES = {
  'made-for-you': 'Made for you', 'deeper-cuts': 'Deeper cuts', because: 'Because you play \u2026', 'new-releases': 'New from artists you love',
  pool: 'Suggested while shuffling', radio: 'Radio',
};

async function recsView(main) {
  main.append(h('h1', { text: 'Suggestions' }),
    h('p', { class: 'lead', text: 'Each person gets lists made from what they play and like: \u201cMade for you\u201d, \u201cBecause you play \u2026\u201d, deeper cuts and new releases from artists they love. They are made at night on this server, and shown in the app.' }));
  const holder = h('div');
  main.append(holder);
  const state = { summary: null, installed: true, error: null, busy: false };

  async function load() {
    const r = await api('GET', '/recs');
    if (!r.ok) state.error = r.data.message || 'Could not load this.';
    else if (r.data.installed === false) { state.installed = false; state.error = null; }
    else { state.installed = true; state.summary = r.data; state.error = null; }
    draw();
  }

  async function switchTo(enabled) {
    state.busy = true; draw();
    const r = await api('PUT', '/recs/settings', { enabled });
    state.busy = false;
    if (r.ok) { state.summary = r.data; state.error = null; } else state.error = r.data.error || r.data.message || 'That did not work.';
    draw();
  }

  async function rebuild() {
    state.busy = true; draw();
    const r = await api('POST', '/recs/rebuild', {});
    state.busy = false;
    if (!r.ok) state.error = r.data.error || r.data.message || 'That did not work.';
    await load();
  }

  function whenText(seconds) {
    return day(seconds) + ', ' + clock(seconds);
  }

  function draw() {
    holder.replaceChildren();
    if (state.error) holder.append(h('p', { class: 'problem', text: state.error }));
    if (!state.installed) {
      holder.append(h('div', { class: 'card' }, h('h2', { text: 'Suggestions are not set up on this server' }),
        h('p', { class: 'muted' }, 'To add them, run ', h('code', { text: 'RECS=1 bash setup.sh' }), ' in the Encore folder, then come back here. Nothing to fill in.')));
      return;
    }
    const s = state.summary;
    if (!s) { holder.append(h('p', { class: 'muted', text: 'Loading\u2026' })); return; }

    holder.append(h('div', { class: 'card' },
      h('div', { class: 'row' }, h('span', { class: 'dot ' + (s.enabled ? 'working' : 'off') }), h('h2', { class: 'grow', text: s.enabled ? 'Suggestions are on' : 'Suggestions are off' })),
      h('p', { class: 'muted', text: s.sentence }),
      h('p', { class: 'muted', text: 'You do not see anybody\u2019s lists, and nobody sees yours: this page only counts.' }),
      h('div', { class: 'actions' }, s.enabled
        ? h('button', { disabled: state.busy, onclick: () => switchTo(false) }, 'Switch them off')
        : h('button', { class: 'primary', disabled: state.busy, onclick: () => switchTo(true) }, 'Switch them on'))));

    const run = s.lastRun;
    const lines = [];
    if (run) {
      lines.push(h('p', { class: 'muted', text: 'Last run: ' + whenText(run.at) + '. ' + run.built + (run.built === 1 ? ' person' : ' people') + ' got new lists'
        + (run.empty ? ', ' + run.empty + ' not yet (they need to play a few songs first)' : '') + '.' }));
      if (run.throttled) lines.push(h('p', { class: 'note', text: 'A public music catalogue was busy, so the run stopped early. It tries again later and the lists from before stay.' }));
      if (run.unreadable) lines.push(h('p', { class: 'problem', text: 'The music server\u2019s database could not be read, so no lists could be made.' }));
    } else {
      lines.push(h('p', { class: 'muted', text: 'Nothing has been made yet. The first lists are made within a few minutes of somebody playing enough.' }));
    }
    holder.append(h('div', { class: 'card' }, h('h2', { text: 'Lists' }),
      h('p', { class: 'muted', text: s.peopleWithLists + (s.peopleWithLists === 1 ? ' person has' : ' people have') + ' lists at the moment.' }),
      lines,
      h('div', { class: 'actions' }, h('button', { disabled: state.busy || s.rebuilding || !s.enabled, onclick: rebuild },
        s.rebuilding ? 'Making them\u2026' : 'Make everybody\u2019s lists now'))));

    const names = Object.keys(s.surfaces || {});
    if (names.length) {
      holder.append(h('div', { class: 'card' }, h('h2', { text: 'How the suggestions are doing' }),
        h('p', { class: 'muted', text: 'Counted over everybody together, so the app can be made better. It never says who.' }),
        names.map((name) => {
          const c = s.surfaces[name];
          return h('div', { class: 'row account-line' }, h('span', { class: 'grow', text: SURFACE_NAMES[name] || name }),
            h('span', { class: 'muted', text: (c.shown || 0) + ' shown, ' + (c.played || 0) + ' played, ' + (c.starred || 0) + ' liked' }));
        })));
    }
  }

  await load();
  poller = setInterval(load, 10000);
}

// ---------------------------------------------------------------------------------------------------------- Parts

const PART_DOT = { running: 'working', starting: 'starting', unhealthy: 'down', restarting: 'down', stopped: 'down' };

async function partsView(main) {
  main.append(h('h1', { text: 'Parts' }),
    h('p', { class: 'lead', text: 'Everything this server is made of. If something is not working, read its recent messages or restart it: a restart takes a few seconds and changes nothing else.' }));
  const holder = h('div');
  main.append(holder);
  const state = { data: null, error: null, open: null, lines: null, confirming: null, busy: null, note: null };

  async function load() {
    const r = await api('GET', '/components');
    if (r.ok) { state.data = r.data; state.error = null; } else state.error = r.data.message || 'Could not load this.';
    draw();
  }

  async function messages(container) {
    if (state.open === container) { state.open = null; draw(); return; }
    state.open = container; state.lines = null; draw();
    const r = await api('GET', '/components/' + container + '/logs');
    state.lines = r.ok ? r.data.lines : ['The messages could not be read just now.'];
    draw();
  }

  async function restart(part) {
    if (state.confirming !== part.container) { state.confirming = part.container; state.note = null; draw(); return; }
    state.confirming = null; state.busy = part.container; draw();
    const r = await api('POST', '/components/' + part.container + '/restart', {});
    state.busy = null;
    state.note = r.ok ? part.name + ' was restarted. Give it a few seconds.' : (r.data.message || 'That did not work.');
    await load();
  }

  function draw() {
    holder.replaceChildren();
    if (state.error) holder.append(h('p', { class: 'problem', text: state.error }));
    if (state.note) holder.append(h('p', { class: 'good', text: state.note }));
    const d = state.data;
    if (!d) { holder.append(h('p', { class: 'muted', text: 'Loading\u2026' })); return; }
    if (!d.dockerOk) {
      holder.append(h('div', { class: 'card' }, h('h2', { text: 'The parts cannot be listed from here' }),
        h('p', { class: 'muted', text: 'This website could not talk to Docker. Everything else on this server is unaffected; you can still see how each part is doing on the Today page.' })));
      return;
    }
    for (const part of d.parts) {
      const confirming = state.confirming === part.container;
      holder.append(h('div', { class: 'card' },
        h('div', { class: 'row' }, h('span', { class: 'dot ' + (PART_DOT[part.state] || '') }), h('h2', { class: 'grow', text: part.name }), h('span', { class: 'muted', text: part.note })),
        part.image ? h('p', { class: 'faint', text: part.image }) : null,
        h('div', { class: 'actions' },
          h('button', { class: 'small', onclick: () => messages(part.container) }, state.open === part.container ? 'Hide messages' : 'Recent messages'),
          part.canRestart ? h('button', { class: 'small' + (confirming ? ' danger' : ''), disabled: state.busy === part.container, onclick: () => restart(part) },
            confirming ? 'Press again to restart ' + part.name : 'Restart') : null),
        state.open === part.container
          ? h('pre', { class: 'messages' }, state.lines === null ? 'Reading\u2026' : (state.lines.length ? state.lines.join('\n') : 'Nothing has been said yet.'))
          : null));
    }
  }

  await load();
  poller = setInterval(load, 10000);
}

// ---------------------------------------------------------------------------------------------------------- start

async function render() {
  stopPolling();
  app.replaceChildren();
  if (!me) { app.append(loginView()); return; }
  const route = (location.hash.replace(/^#\//, '') || 'today').split('/')[0];
  const main = h('div');
  const known = ['youtube', 'people', 'quality', 'recs', 'parts'].includes(route) ? route : 'today';
  app.append(shell(known, main));
  if (known === 'youtube') await youtubeView(main);
  else if (known === 'people') await peopleView(main);
  else if (known === 'quality') await qualityView(main);
  else if (known === 'recs') await recsView(main);
  else if (known === 'parts') await partsView(main);
  else await todayView(main);
}

window.addEventListener('hashchange', render);
(async () => {
  const r = await api('GET', '/me');
  me = r.ok ? r.data : null;
  render();
})();
