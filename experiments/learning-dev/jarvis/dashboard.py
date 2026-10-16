from __future__ import annotations


COCKPIT_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="theme-color" content="#080b0f">
  <title>Jarvis Cockpit</title>
  <link rel="stylesheet" href="/assets/cockpit.css">
  <script defer src="/assets/cockpit.js"></script>
</head>
<body data-system-state="offline">
  <header class="topbar">
    <div class="brand" aria-label="Hive Jarvis Cockpit">
      <span class="brand-mark" aria-hidden="true"><span></span></span>
      <span class="brand-name">JARVIS</span>
      <span class="brand-divider" aria-hidden="true">//</span>
      <span class="brand-section">COCKPIT</span>
    </div>
    <div class="connection-pill" id="connection-pill" role="status" aria-live="polite">
      <span class="status-dot" aria-hidden="true"></span>
      <span id="connection-label">Connecting</span>
    </div>
  </header>

  <main>
    <section class="system-banner" aria-labelledby="system-title">
      <div class="telemetry-rail" aria-hidden="true"><span></span></div>
      <div class="system-copy">
        <p class="eyebrow">SYSTEM STATE</p>
        <h1 id="system-title">Locating Jarvis…</h1>
        <p class="system-message" id="system-message">Reading the supervisor and persisted evidence ledger.</p>
      </div>
      <div class="banner-actions">
        <div class="banner-controls">
          <button class="button" id="refresh-button" type="button">Refresh now</button>
          <button class="text-button" id="poll-button" type="button" aria-pressed="false">Pause auto-refresh</button>
        </div>
        <p class="updated">Updated <time id="updated-at">—</time></p>
      </div>
    </section>

    <section class="auth-panel" id="auth-panel" aria-labelledby="auth-title" hidden>
      <div>
        <p class="eyebrow">LOCAL AUTHORIZATION</p>
        <h2 id="auth-title">Connect to the protected supervisor</h2>
        <p>Enter the local API token. It is saved in this tab's session storage so it survives reloads; use Forget token to remove it.</p>
      </div>
      <div class="auth-field">
        <label for="api-token">API token</label>
        <input id="api-token" type="password" autocomplete="off" spellcheck="false" aria-describedby="auth-error" aria-invalid="false">
      </div>
      <div class="auth-actions">
        <button class="button" id="auth-connect" type="button">Connect</button>
        <button class="text-button" id="auth-forget" type="button">Forget token</button>
      </div>
      <p class="auth-error" id="auth-error" aria-live="polite"></p>
    </section>

    <section class="metrics" aria-label="Jarvis at a glance">
      <article class="metric">
        <p>Supervisor</p>
        <strong id="metric-supervisor">—</strong>
        <span id="metric-supervisor-detail">Waiting for heartbeat</span>
      </article>
      <article class="metric">
        <p>Active work</p>
        <strong id="metric-active">—</strong>
        <span id="metric-active-detail">Checking queue</span>
      </article>
      <article class="metric">
        <p>Needs approval</p>
        <strong id="metric-approval">—</strong>
        <span>Human authority gate</span>
      </article>
      <article class="metric">
        <p>Evidence</p>
        <strong id="metric-evidence">—</strong>
        <span id="metric-evidence-detail">Verifying ledger</span>
      </article>
    </section>

    <section class="cockpit-grid">
      <article class="panel current-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">CURRENT TASK</p>
            <h2 id="task-title">No task selected</h2>
          </div>
          <span class="status-chip neutral" id="task-status">UNKNOWN</span>
        </div>
        <p class="task-goal" id="task-goal">Jarvis is checking its durable queue.</p>
        <dl class="detail-grid">
          <div><dt>Task ID</dt><dd class="mono" id="task-id">—</dd></div>
          <div><dt>Stage</dt><dd id="task-stage">—</dd></div>
          <div><dt>Task age</dt><dd id="task-elapsed">—</dd></div>
          <div><dt>Attempt</dt><dd id="task-attempt">—</dd></div>
        </dl>
        <div class="activity-strip">
          <span class="activity-signal" aria-hidden="true"></span>
          <div>
            <span>Activity</span><strong id="task-activity">Reading persisted state</strong>
            <small id="task-checkpoint">Checkpoint —</small>
          </div>
        </div>
        <div class="verification-row">
          <span>Reported verification</span><strong id="verification-state">Pending status</strong>
        </div>
        <details class="log-disclosure">
          <summary>Inspect persisted result</summary>
          <pre id="result-log" tabindex="0" role="region" aria-label="Persisted task result">No result has been recorded.</pre>
        </details>
      </article>

      <article class="panel supervisor-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">SUPERVISOR</p><h2>Heartbeat</h2></div>
          <span class="status-dot large" id="worker-dot" aria-hidden="true"></span>
        </div>
        <dl class="stacked-details">
          <div><dt>Worker</dt><dd id="worker-state">Unknown</dd></div>
          <div><dt>Started</dt><dd id="worker-started">—</dd></div>
          <div><dt>Heartbeat</dt><dd id="worker-activity">—</dd></div>
          <div><dt>Recovery</dt><dd id="worker-recovery">—</dd></div>
          <div><dt>Errors</dt><dd id="worker-errors">—</dd></div>
          <div><dt>Ledger</dt><dd id="ledger-state">Checking</dd></div>
        </dl>
      </article>

      <article class="panel evidence-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">EVIDENCE</p><h2>Recent ledger events</h2></div>
          <span class="mono event-count" id="event-count">0</span>
        </div>
        <ol class="timeline" id="event-list">
          <li class="timeline-empty">Waiting for the ledger…</li>
        </ol>
      </article>

      <article class="panel grow-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">GROW-9</p><h2>Improvement gate</h2></div>
          <span class="status-chip neutral">NOT CONNECTED</span>
        </div>
        <p class="panel-copy">No proposal, test, or promotion loop is attached. GROW remains outside Jarvis authority until HiveGate integration is explicitly approved.</p>
        <div class="gate-path" aria-label="Future governed improvement path">
          <span>Propose</span><i></i><span>Verify</span><i></i><span>Approve</span>
        </div>
      </article>

      <article class="panel failure-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">FAILURES</p><h2>Next safe action</h2></div>
          <span class="status-chip success" id="failure-count">CLEAR</span>
        </div>
        <p class="failure-message" id="failure-message">No active failures.</p>
        <p class="next-action" id="next-action">Jarvis is ready for the next human-approved task.</p>
      </article>
    </section>
  </main>

  <footer>
    <span>LOCAL CONTROL SURFACE</span>
    <span class="mono" id="ledger-tip">LEDGER —</span>
  </footer>
  <div class="sr-only" id="announcer" aria-live="polite"></div>
</body>
</html>
""".encode("utf-8")


COCKPIT_CSS = """:root {
  color-scheme: dark;
  --bg: #080b0f;
  --panel: #10161d;
  --panel-raised: #141d26;
  --line: #26323d;
  --line-hot: #3b4b58;
  --text: #edf5f7;
  --muted: #91a1ad;
  --cyan: #49ded8;
  --green: #4de19b;
  --yellow: #f4c95d;
  --red: #ff6b6b;
  --gray: #76838e;
  --state: var(--gray);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }
[hidden] { display: none !important; }
html { background: var(--bg); font-size: 16px; }
body {
  min-width: 20rem;
  min-height: 100vh;
  margin: 0;
  color: var(--text);
  background:
    linear-gradient(rgba(73, 222, 216, .025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(73, 222, 216, .025) 1px, transparent 1px),
    radial-gradient(circle at 15% -10%, rgba(73, 222, 216, .10), transparent 32rem),
    var(--bg);
  background-size: 2.5rem 2.5rem, 2.5rem 2.5rem, auto, auto;
}
body[data-system-state="online"] { --state: var(--green); }
body[data-system-state="attention"] { --state: var(--yellow); }
body[data-system-state="failed"] { --state: var(--red); }
body[data-system-state="offline"] { --state: var(--gray); }

button { font: inherit; }
.topbar {
  height: 4.25rem;
  padding: 0 clamp(1rem, 3vw, 2.5rem);
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
  background: rgba(8, 11, 15, .88);
  backdrop-filter: blur(1rem);
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand { display: flex; align-items: center; gap: .65rem; letter-spacing: .13em; font-weight: 750; }
.brand-mark { width: 1.55rem; height: 1.55rem; display: grid; place-items: center; border: 1px solid var(--cyan); transform: rotate(30deg); }
.brand-mark span { width: .55rem; height: .55rem; display: block; background: var(--cyan); box-shadow: 0 0 1rem rgba(73, 222, 216, .65); }
.brand-name { color: var(--text); }
.brand-divider, .brand-section { color: var(--muted); font-size: .85rem; }
.connection-pill { min-height: 2.25rem; padding: .45rem .75rem; display: flex; align-items: center; gap: .55rem; border: 1px solid var(--line); background: var(--panel); color: var(--muted); font-size: .85rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.status-dot { width: .58rem; height: .58rem; border-radius: 50%; background: var(--state); box-shadow: 0 0 .7rem color-mix(in srgb, var(--state) 65%, transparent); flex: 0 0 auto; }
.status-dot.large { width: .8rem; height: .8rem; }

main { width: min(96rem, 100%); margin: 0 auto; padding: clamp(1rem, 2.5vw, 2.5rem); }
.system-banner {
  min-height: 9.5rem;
  display: grid;
  grid-template-columns: .35rem minmax(0, 1fr) auto;
  gap: clamp(1rem, 2.5vw, 2rem);
  align-items: center;
  padding: clamp(1.25rem, 3vw, 2rem);
  border: 1px solid var(--line-hot);
  background: linear-gradient(110deg, rgba(20, 29, 38, .98), rgba(12, 17, 23, .96));
  box-shadow: 0 1.5rem 4rem rgba(0, 0, 0, .25);
}
.telemetry-rail { align-self: stretch; width: .3rem; background: color-mix(in srgb, var(--state) 22%, var(--line)); position: relative; overflow: hidden; }
.telemetry-rail span { position: absolute; inset: 0; height: 32%; background: var(--state); box-shadow: 0 0 1rem var(--state); animation: scan 2.8s ease-in-out infinite; }
@keyframes scan { 0%, 100% { transform: translateY(-110%); } 50% { transform: translateY(310%); } }
.eyebrow { margin: 0 0 .55rem; color: var(--cyan); font: 700 .75rem/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .16em; }
h1, h2, p { overflow-wrap: anywhere; }
h1 { margin: 0; font-size: clamp(1.65rem, 4vw, 3rem); line-height: 1.05; letter-spacing: -.035em; }
h2 { margin: 0; font-size: 1.12rem; line-height: 1.3; }
.system-message { max-width: 54rem; margin: .75rem 0 0; color: var(--muted); line-height: 1.55; }
.banner-actions { min-width: 10rem; text-align: right; }
.banner-controls { display: flex; justify-content: flex-end; align-items: center; gap: .75rem; flex-wrap: wrap; }
.button { min-height: 2.75rem; padding: .65rem 1rem; color: var(--text); border: 1px solid var(--line-hot); background: #18232d; cursor: pointer; font-weight: 700; }
.button:hover { border-color: var(--cyan); background: #1c2a35; }
.button:focus-visible { outline: .15rem solid var(--cyan); outline-offset: .18rem; }
.button[disabled], .text-button[disabled] { cursor: wait; opacity: .6; }
.updated { margin: .65rem 0 0; color: var(--muted); font-size: .78rem; }
.auth-panel { margin-top: 1rem; padding: 1.25rem; display: grid; grid-template-columns: minmax(16rem, 1fr) minmax(13rem, .7fr) auto; align-items: end; gap: 1rem; border: 1px solid color-mix(in srgb, var(--yellow) 55%, var(--line)); background: #171710; }
.auth-panel p { margin: .35rem 0 0; color: var(--muted); line-height: 1.45; }
.auth-field { min-width: 0; display: grid; gap: .4rem; }
.auth-panel label { color: var(--muted); font-size: .8rem; font-weight: 700; }
.auth-panel input { width: 100%; min-height: 2.75rem; padding: .65rem .75rem; border: 1px solid var(--line-hot); background: #080b0f; color: var(--text); font: .9rem ui-monospace, SFMono-Regular, Consolas, monospace; }
.auth-panel input:focus-visible { outline: .15rem solid var(--yellow); outline-offset: .12rem; }
.auth-actions { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.text-button { min-height: 2.75rem; padding: .5rem .25rem; border: 0; background: transparent; color: var(--muted); cursor: pointer; }
.text-button:hover { color: var(--text); }
.text-button:focus-visible { outline: .15rem solid var(--cyan); outline-offset: .12rem; }
.text-button[disabled] { cursor: wait; opacity: .6; }
.auth-error { grid-column: 1 / -1; color: var(--red) !important; font-size: .82rem; }

.metrics { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); border-top: 0; }
.metric { min-height: 7.3rem; padding: 1.15rem 1.25rem; border-right: 1px solid var(--line); background: rgba(13, 18, 24, .86); }
.metric:last-child { border-right: 0; }
.metric p { margin: 0; color: var(--muted); font-size: .82rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.metric strong { display: block; margin: .55rem 0 .2rem; font: 750 1.65rem/1 ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
.metric span { color: var(--muted); font-size: .8rem; }

.cockpit-grid { margin-top: 1rem; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(17rem, .8fr); gap: 1rem; }
.panel { min-width: 0; padding: clamp(1.15rem, 2vw, 1.55rem); border: 1px solid var(--line); background: rgba(16, 22, 29, .94); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.panel-heading > div { min-width: 0; }
.current-panel { min-height: 20rem; }
.task-goal { min-height: 3.2rem; margin: 1.45rem 0; max-width: 58rem; color: #cbd7dc; font-size: 1.05rem; line-height: 1.58; }
.status-chip { padding: .35rem .55rem; border: 1px solid var(--line-hot); color: var(--muted); background: #161d24; font: 700 .7rem/1 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .07em; white-space: nowrap; }
.status-chip.success { color: var(--green); border-color: color-mix(in srgb, var(--green) 40%, var(--line)); }
.status-chip.warning { color: var(--yellow); border-color: color-mix(in srgb, var(--yellow) 40%, var(--line)); }
.status-chip.danger { color: var(--red); border-color: color-mix(in srgb, var(--red) 40%, var(--line)); }
.detail-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0; border: 1px solid var(--line); }
.detail-grid div { min-width: 0; padding: .85rem; border-right: 1px solid var(--line); }
.detail-grid div:last-child { border-right: 0; }
dt { color: var(--muted); font-size: .75rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
dd { min-width: 0; margin: .3rem 0 0; color: var(--text); line-height: 1.35; overflow-wrap: anywhere; }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.activity-strip { margin-top: 1rem; padding: .8rem 1rem; display: flex; align-items: center; gap: .8rem; border-left: .18rem solid var(--state); background: #0b1117; }
.activity-signal { width: .65rem; height: .65rem; border: .13rem solid var(--state); border-radius: 50%; }
.activity-strip div { min-width: 0; display: grid; gap: .15rem; }
.activity-strip span { color: var(--muted); font-size: .7rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
.activity-strip strong { min-width: 0; font-size: .9rem; overflow-wrap: anywhere; }
.activity-strip small { min-width: 0; display: block; margin-top: .28rem; color: var(--muted); font-size: .74rem; overflow-wrap: anywhere; }
.verification-row { margin-top: 1rem; padding: .75rem 0; display: flex; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.verification-row span { color: var(--muted); font-size: .75rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.verification-row strong { min-width: 0; color: var(--muted); font-size: .86rem; text-align: right; overflow-wrap: anywhere; }
.verification-row strong.success { color: var(--green); }
.log-disclosure { margin-top: .9rem; }
.log-disclosure summary { min-height: 2.75rem; display: flex; align-items: center; color: var(--muted); cursor: pointer; font-size: .84rem; font-weight: 700; }
.log-disclosure summary:hover { color: var(--text); }
.log-disclosure summary:focus-visible { outline: .15rem solid var(--cyan); outline-offset: .12rem; }
.log-disclosure pre { max-height: 18rem; overflow: auto; margin: 0; padding: 1rem; border: 1px solid var(--line); background: #070b0f; color: #b9c8ce; font: .76rem/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; }
.log-disclosure pre:focus-visible { outline: .15rem solid var(--cyan); outline-offset: .12rem; }

.stacked-details { margin: 1.2rem 0 0; }
.stacked-details div { padding: .75rem 0; display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--line); }
.stacked-details div:last-child { border-bottom: 0; }
.stacked-details dd { text-align: right; font-size: .88rem; }
.evidence-panel { min-height: 17rem; }
.event-count { min-width: 2rem; text-align: center; padding: .25rem .4rem; background: #0a1015; color: var(--muted); }
.timeline { margin: 1rem 0 0; padding: 0; list-style: none; }
.timeline li { position: relative; margin-left: .4rem; padding: .65rem 0 .65rem 1.3rem; border-left: 1px solid var(--line-hot); }
.timeline li::before { content: ""; position: absolute; width: .48rem; height: .48rem; left: -.28rem; top: 1rem; border-radius: 50%; background: var(--cyan); }
.timeline strong { display: block; font-size: .83rem; letter-spacing: .025em; overflow-wrap: anywhere; }
.timeline span { display: block; margin-top: .2rem; color: var(--muted); font-size: .76rem; overflow-wrap: anywhere; }
.timeline .timeline-empty { color: var(--muted); border-left-color: var(--line); }
.timeline .timeline-empty::before { background: var(--gray); }
.timeline .timeline-unavailable { color: var(--yellow); border-left-color: color-mix(in srgb, var(--yellow) 45%, var(--line)); }
.timeline .timeline-unavailable::before { background: var(--yellow); }
.panel-copy { margin: 1.2rem 0; color: var(--muted); line-height: 1.55; }
.gate-path { display: flex; align-items: center; gap: .55rem; color: var(--muted); font: 700 .72rem/1 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .05em; text-transform: uppercase; }
.gate-path i { height: 1px; flex: 1; background: var(--line-hot); }
.failure-message { margin: 1.25rem 0 .45rem; font-weight: 700; }
.next-action { margin: 0; color: var(--muted); line-height: 1.5; }

footer { width: min(96rem, 100%); margin: 0 auto; padding: 1rem clamp(1rem, 2.5vw, 2.5rem) 2rem; display: flex; justify-content: space-between; gap: 1rem; color: var(--muted); font-size: .72rem; letter-spacing: .08em; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

@media (max-width: 62rem) {
  .auth-panel { grid-template-columns: 1fr 1fr; }
  .auth-panel > div:first-child { grid-column: 1 / -1; }
  .metrics { grid-template-columns: repeat(2, 1fr); }
  .metric:nth-child(2) { border-right: 0; }
  .metric:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
  .cockpit-grid { grid-template-columns: 1fr; }
}
@media (max-width: 42rem) {
  .topbar { height: auto; min-height: 4.25rem; gap: 1rem; }
  .brand-divider, .brand-section { display: none; }
  .connection-pill { padding-inline: .55rem; }
  .system-banner { grid-template-columns: .28rem 1fr; }
  .auth-panel { grid-template-columns: 1fr; align-items: stretch; }
  .auth-panel > div:first-child, .auth-error { grid-column: 1; }
  .banner-actions { grid-column: 2; text-align: left; }
  .banner-controls { justify-content: flex-start; }
  .metrics { grid-template-columns: 1fr; }
  .metric, .metric:nth-child(2) { border-right: 0; border-bottom: 1px solid var(--line); }
  .metric:last-child { border-bottom: 0; }
  .detail-grid { grid-template-columns: repeat(2, 1fr); }
  .detail-grid div:nth-child(2) { border-right: 0; }
  .detail-grid div:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
  footer { flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; animation-iteration-count: 1 !important; }
}
""".encode("utf-8")


COCKPIT_JS = r"""(() => {
  'use strict';

  const byId = (id) => document.getElementById(id);
  const terminal = new Set(['SUCCEEDED', 'FAILED', 'REJECTED', 'CANCELLED']);
  const fetchTimeoutMs = 8000;
  let refreshing = false;
  let pollingPaused = false;
  let authorizationRequired = false;
  let announcementTimer = 0;
  let lastOperationalSignature = null;
  let apiToken = '';
  try { apiToken = sessionStorage.getItem('jarvis-api-token') || ''; } catch (_) { /* session storage unavailable */ }

  function text(id, value) {
    const node = byId(id);
    if (!node) return;
    const next = value == null ? '\u2014' : String(value);
    if (node.textContent !== next) node.textContent = next;
  }

  function announce(message) {
    const node = byId('announcer');
    window.clearTimeout(announcementTimer);
    node.textContent = '';
    announcementTimer = window.setTimeout(() => { node.textContent = message; }, 0);
  }

  function setAuthError(message = '') {
    text('auth-error', message);
    byId('api-token').setAttribute('aria-invalid', message ? 'true' : 'false');
  }

  function setVerification(message, success = false) {
    const node = byId('verification-state');
    node.className = success ? 'success' : '';
    text('verification-state', message);
  }

  function when(value, withSeconds = false) {
    if (!value) return '\u2014';
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return '\u2014';
    return new Intl.DateTimeFormat(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      second: withSeconds ? '2-digit' : undefined,
    }).format(date);
  }

  function relative(value) {
    if (!value) return 'No heartbeat yet';
    const seconds = Math.max(0, Math.round((Date.now() - new Date(value).valueOf()) / 1000));
    if (seconds < 5) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return when(value);
  }

  function elapsed(start, end = null) {
    if (!start) return '—';
    const total = Math.max(0, Math.floor((new Date(end || Date.now()).valueOf() - new Date(start).valueOf()) / 1000));
    if (!Number.isFinite(total)) return '—';
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
  }

  function parsedOutcome(task) {
    if (!task || task.kind !== 'agent' || !task.result || !task.result.outcome) return null;
    const outcome = task.result.outcome;
    if (!outcome || outcome.success !== true || typeof outcome.summary !== 'string') return null;
    if (!Array.isArray(outcome.files_changed) || !outcome.files_changed.every((item) => typeof item === 'string')) return null;
    if (!Array.isArray(outcome.verification) || !outcome.verification.every((item) => typeof item === 'string')) return null;
    if (outcome.blocker !== null && typeof outcome.blocker !== 'string') return null;
    return outcome;
  }

  function resultLog(task) {
    if (!task) return 'No task selected.';
    const result = task.result || {};
    const sections = [];
    if (task.error) sections.push(`ERROR\n${task.error}`);
    if (result.stdout) sections.push(`RESULT\n${String(result.stdout).trim()}`);
    if (result.stderr) sections.push(`ADAPTER LOG (tail)\n${String(result.stderr).slice(-8000).trim()}`);
    return sections.join('\n\n') || 'No result has been recorded.';
  }

  async function json(path, tolerateStatus = false) {
    const headers = { Accept: 'application/json' };
    if (apiToken) headers.Authorization = `Bearer ${apiToken}`;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), fetchTimeoutMs);
    try {
      const response = await fetch(path, { cache: 'no-store', headers, signal: controller.signal });
      let body;
      try {
        body = await response.json();
      } catch (_) {
        const error = new Error(`The supervisor returned an invalid response (${response.status}).`);
        error.status = response.status;
        throw error;
      }
      if (!response.ok && (!tolerateStatus || response.status === 401)) {
        const error = new Error(body.error || `Request failed (${response.status})`);
        error.status = response.status;
        throw error;
      }
      return body;
    } catch (error) {
      if (error && error.name === 'AbortError') {
        const timeoutError = new Error('The supervisor did not respond before the request timed out.');
        timeoutError.timedOut = true;
        throw timeoutError;
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function setSystemState(state, title, message, connectionLabel = null) {
    document.body.dataset.systemState = state;
    text('system-title', title);
    text('system-message', message);
    text('connection-label', connectionLabel || (state === 'online' ? 'Online' : state === 'attention' ? 'Needs attention' : state === 'failed' ? 'Failed' : 'Offline'));
  }

  function statusClass(status) {
    if (status === 'SUCCEEDED') return 'success';
    if (status === 'WAITING_APPROVAL' || status === 'READY' || status === 'RUNNING') return 'warning';
    if (status === 'FAILED' || status === 'REJECTED' || status === 'CANCELLED') return 'danger';
    return 'neutral';
  }

  function renderTimelineMessage(message, unavailable = false) {
    const list = byId('event-list');
    list.replaceChildren();
    const item = document.createElement('li');
    item.className = unavailable ? 'timeline-empty timeline-unavailable' : 'timeline-empty';
    item.textContent = message;
    list.append(item);
    text('event-count', unavailable ? '\u2014' : '0');
  }

  function renderTimeline(events, emptyMessage = 'No evidence events have been recorded for this task.') {
    const list = byId('event-list');
    list.replaceChildren();
    const recent = events.slice(-5).reverse();
    if (!recent.length) {
      renderTimelineMessage(emptyMessage);
      return;
    } else {
      for (const event of recent) {
        const item = document.createElement('li');
        const label = document.createElement('strong');
        const meta = document.createElement('span');
        label.textContent = String(event.type || 'EVENT').replaceAll('_', ' ');
        meta.textContent = `#${event.seq}  \u00b7  ${when(event.timestamp, true)}`;
        item.append(label, meta);
        list.append(item);
      }
    }
    text('event-count', events.length);
  }

  function countFor(counts, status) {
    const value = Number(counts && counts[status]);
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  }

  function workerAvailable(worker) {
    return worker == null || Boolean(worker.alive && worker.thread_alive !== false && !worker.heartbeat_stale);
  }

  function renderFailure(counts, worker, health) {
    const failures = countFor(counts, 'FAILED');
    const waiting = countFor(counts, 'WAITING_APPROVAL');
    const activeError = worker && worker.consecutive_errors > 0 && worker.last_error;
    const chip = byId('failure-count');
    if (!health.ledger_ok) {
      chip.className = 'status-chip danger';
      text('failure-count', 'LEDGER ERROR');
      text('failure-message', 'Evidence-ledger verification failed.');
      text('next-action', 'Do not approve new work until the persisted evidence chain is repaired and verified.');
    } else if (activeError) {
      chip.className = 'status-chip danger';
      text('failure-count', 'WORKER ERROR');
      text('failure-message', activeError);
      text('next-action', 'Inspect the worker log and resolve the reported error before approving more work.');
    } else if (worker && !workerAvailable(worker)) {
      chip.className = 'status-chip danger';
      text('failure-count', worker.heartbeat_stale ? 'STALE' : 'OFFLINE');
      text('failure-message', worker.heartbeat_stale ? 'The worker heartbeat is stale.' : 'The worker is not running.');
      text('next-action', 'Restart Jarvis and confirm a fresh heartbeat before approving more work.');
    } else if (failures) {
      chip.className = 'status-chip warning';
      text('failure-count', `${failures} RECORDED`);
      text('failure-message', `${failures} task${failures === 1 ? '' : 's'} ended in failure.`);
      text('next-action', 'Open the failed task evidence before retrying or changing its approval state.');
    } else if (waiting) {
      chip.className = 'status-chip warning';
      text('failure-count', 'APPROVAL');
      text('failure-message', `${waiting} task${waiting === 1 ? '' : 's'} await human approval.`);
      text('next-action', 'Review the task boundary and evidence before approving or rejecting it.');
    } else {
      chip.className = 'status-chip success';
      text('failure-count', 'CLEAR');
      text('failure-message', 'No active failures.');
      text('next-action', 'Jarvis is ready for the next human-approved task.');
    }
  }

  function scrubProtected(mode) {
    const protectedState = mode === 'unauthorized';
    text('metric-supervisor', protectedState ? 'PROTECTED' : 'OFFLINE');
    text('metric-supervisor-detail', protectedState ? 'Authorization required' : 'Status unavailable');
    text('metric-active', '\u2014');
    text('metric-active-detail', protectedState ? 'Protected state' : 'Status unavailable');
    text('metric-approval', '\u2014');
    text('metric-evidence', protectedState ? 'LOCKED' : 'UNKNOWN');
    text('metric-evidence-detail', protectedState ? 'Authorization required' : 'Status unavailable');

    text('task-title', protectedState ? 'Protected state' : 'Status unavailable');
    text('task-status', protectedState ? 'LOCKED' : 'UNKNOWN');
    byId('task-status').className = 'status-chip neutral';
    text('task-goal', protectedState ? 'Enter the local API token to inspect persisted tasks.' : 'Reconnect to Jarvis to inspect persisted tasks.');
    text('task-id', '\u2014');
    text('task-stage', '\u2014');
    text('task-elapsed', '\u2014');
    text('task-attempt', '\u2014');
    text('task-activity', protectedState ? 'Protected' : 'Connection unavailable');
    text('task-checkpoint', 'Checkpoint \u2014');
    setVerification('Unavailable');
    text('result-log', protectedState ? 'Persisted results are protected.' : 'Persisted results are unavailable while disconnected.');
    renderTimelineMessage(protectedState ? 'Evidence events are protected.' : 'Evidence events are unavailable while disconnected.', true);

    text('worker-state', protectedState ? 'Unknown' : 'Offline');
    text('worker-started', '\u2014');
    text('worker-activity', protectedState ? 'Authorization required' : 'Connection unavailable');
    text('worker-recovery', 'Unknown');
    text('worker-errors', 'Unknown');
    text('ledger-state', protectedState ? 'Protected' : 'Unknown');
    text('ledger-tip', 'LEDGER \u2014');

    const chip = byId('failure-count');
    chip.className = protectedState ? 'status-chip neutral' : 'status-chip danger';
    text('failure-count', protectedState ? 'LOCKED' : 'OFFLINE');
    text('failure-message', protectedState ? 'Supervisor state is protected.' : 'The Cockpit cannot reach the supervisor.');
    text('next-action', protectedState ? 'Enter the token configured in JARVIS_API_TOKEN.' : 'Start Jarvis or restore the connection, then refresh this page.');
  }

  function updateOperationalAnnouncement(health, active, counts, total, worker) {
    const running = countFor(counts, 'RUNNING');
    const waiting = countFor(counts, 'WAITING_APPROVAL');
    const ready = countFor(counts, 'READY');
    const failed = countFor(counts, 'FAILED');
    const signature = [
      Boolean(health.ok), Boolean(health.ledger_ok), workerAvailable(worker),
      worker ? Number(worker.consecutive_errors || 0) : 0,
      running, waiting, ready, failed, total,
      active ? active.id : '', active ? active.status : '',
    ].join('|');
    if (lastOperationalSignature === null) {
      lastOperationalSignature = signature;
      return false;
    }
    if (lastOperationalSignature === signature) return false;
    lastOperationalSignature = signature;
    if (!health.ok) announce('Jarvis needs attention.');
    else if (waiting && running) announce(`Jarvis is working; ${waiting} task${waiting === 1 ? '' : 's'} also need approval.`);
    else if (waiting) announce(`${waiting} task${waiting === 1 ? '' : 's'} need human approval.`);
    else if (running) announce(`${running} task${running === 1 ? ' is' : 's are'} running.`);
    else if (ready) announce(`${ready} task${ready === 1 ? ' is' : 's are'} ready to run.`);
    else if (active && active.status === 'FAILED') announce(`Task ${active.id} failed.`);
    else announce('Jarvis is online and idle.');
    return true;
  }

  async function render(data) {
    const { health, overview } = data;
    const recentTasks = Array.isArray(data.tasks) ? data.tasks : [];
    const overviewTasks = overview && Array.isArray(overview.nonterminal) ? overview.nonterminal : [];
    const lessons = Array.isArray(data.lessons) ? data.lessons : [];
    const counts = overview && overview.by_status && typeof overview.by_status === 'object' ? overview.by_status : {};
    const total = Number.isFinite(Number(overview && overview.total)) ? Math.max(0, Math.floor(Number(overview.total))) : recentTasks.length;
    const worker = health.worker;

    const mergedById = new Map();
    for (const task of recentTasks) mergedById.set(task.id, task);
    for (const task of overviewTasks) {
      const current = mergedById.get(task.id);
      const currentStamp = current ? new Date(current.updated_at).valueOf() : -Infinity;
      const overviewStamp = new Date(task.updated_at).valueOf();
      if (!current || !Number.isFinite(currentStamp) || overviewStamp >= currentStamp) mergedById.set(task.id, task);
    }
    const seen = new Set();
    const nonterminal = [];
    for (const task of overviewTasks) {
      const merged = mergedById.get(task.id) || task;
      if (!terminal.has(merged.status) && !seen.has(merged.id)) {
        seen.add(merged.id);
        nonterminal.push(merged);
      }
    }
    for (const task of recentTasks) {
      const merged = mergedById.get(task.id) || task;
      if (!terminal.has(merged.status) && !seen.has(merged.id)) {
        seen.add(merged.id);
        nonterminal.push(merged);
      }
    }

    const runningTasks = nonterminal.filter((task) => task.status === 'RUNNING');
    const waitingTasks = nonterminal.filter((task) => task.status === 'WAITING_APPROVAL');
    const readyTasks = nonterminal.filter((task) => task.status === 'READY');
    const active = runningTasks[0] || waitingTasks[0] || readyTasks[0] || recentTasks[0] || null;
    const runningCount = countFor(counts, 'RUNNING');
    const waitingCount = countFor(counts, 'WAITING_APPROVAL');
    const readyCount = countFor(counts, 'READY');
    const workerIsAvailable = workerAvailable(worker);
    const workerErrors = worker ? Number(worker.consecutive_errors || 0) : 0;

    authorizationRequired = false;
    byId('auth-panel').hidden = true;
    setAuthError('');

    if (!health.ok) {
      setSystemState('failed', 'Jarvis needs attention', health.ledger_ok ? 'The API is reachable, but the supervisor heartbeat or worker loop is unhealthy.' : 'The evidence ledger did not pass verification. Do not approve new work.', 'Failed');
    } else if (runningCount && waitingCount) {
      setSystemState('attention', 'Jarvis is working and needs your approval', `${runningCount} task${runningCount === 1 ? ' is' : 's are'} running; ${waitingCount} other task${waitingCount === 1 ? '' : 's'} await human approval.${readyCount ? ` ${readyCount} more ${readyCount === 1 ? 'is' : 'are'} ready.` : ''}`, 'Approval needed');
    } else if (runningCount) {
      setSystemState('online', 'Jarvis is working', `${runningCount} task${runningCount === 1 ? ' is' : 's are'} executing inside the approved boundary.${readyCount ? ` ${readyCount} more ${readyCount === 1 ? 'is' : 'are'} ready.` : ''}`);
    } else if (waitingCount) {
      setSystemState('attention', 'Jarvis is waiting for your review', `${waitingCount} task${waitingCount === 1 ? '' : 's'} await human approval.${readyCount ? ` ${readyCount} separate ${readyCount === 1 ? 'task is' : 'tasks are'} ready.` : ''}`, 'Approval needed');
    } else if (readyCount) {
      setSystemState('online', 'Jarvis has queued work', `${readyCount} task${readyCount === 1 ? ' is' : 's are'} ready for the supervisor to claim.`);
    } else {
      setSystemState('online', 'Jarvis is online and idle', 'No task is running, ready, or awaiting approval. Completed work and evidence remain available below.');
    }

    const supervisorLabel = worker == null ? 'ONLINE' : !workerIsAvailable ? 'OFFLINE' : workerErrors ? 'DEGRADED' : 'ONLINE';
    text('metric-supervisor', supervisorLabel);
    text('metric-supervisor-detail', worker == null ? 'API inspection mode' : worker.heartbeat_stale ? 'Heartbeat stale' : `${worker.pid ? `PID ${worker.pid} · ` : ''}${relative(worker.last_activity_at)}`);
    const activeParts = [];
    if (runningCount) activeParts.push(`${runningCount} RUNNING`);
    if (readyCount) activeParts.push(`${readyCount} READY`);
    text('metric-active', activeParts.join(' · ') || 'IDLE');
    text('metric-active-detail', total ? `${nonterminal.length} nonterminal · ${total} persisted` : 'No persisted tasks');
    text('metric-approval', waitingCount);
    text('metric-evidence', health.ledger_ok ? 'VERIFIED' : 'BROKEN');
    text('metric-evidence-detail', `${lessons.length} learned outcome${lessons.length === 1 ? '' : 's'}`);

    const workerState = worker == null ? 'API-only view' : !workerIsAvailable ? (worker.heartbeat_stale ? 'Heartbeat stale' : 'Offline') : workerErrors ? 'Degraded' : `Online${worker.pid ? ` · PID ${worker.pid}` : ''}`;
    text('worker-state', workerState);
    text('worker-started', worker ? when(worker.started_at, true) : 'Not reported');
    text('worker-activity', worker ? relative(worker.last_activity_at) : 'API-only view');
    text('worker-recovery', worker ? (worker.recoveries ? `${worker.recoveries} task${worker.recoveries === 1 ? '' : 's'} · ${relative(worker.last_recovery_at)}` : 'No recovery needed') : 'Not reported');
    text('worker-errors', worker ? (workerErrors || 'None') : 'Not reported');
    text('ledger-state', health.ledger_ok ? 'Verified' : 'Verification failed');
    text('ledger-tip', `LEDGER ${String(health.ledger_tip || '\u2014').slice(0, 12)}`);

    if (active) {
      const checkpoint = active.checkpoint || {};
      const outcome = parsedOutcome(active);
      const outcomeVerification = outcome && Array.isArray(outcome.verification) ? outcome.verification.filter((item) => typeof item === 'string' && item) : [];
      text('task-title', active.kind ? `${active.kind.toUpperCase()} TASK` : 'Persisted task');
      text('task-status', active.status);
      byId('task-status').className = `status-chip ${statusClass(active.status)}`;
      text('task-goal', active.goal);
      text('task-id', active.id);
      text('task-stage', checkpoint.stage || (terminal.has(active.status) ? 'terminal' : String(active.status).toLowerCase()));
      text('task-elapsed', elapsed(active.created_at, terminal.has(active.status) ? active.updated_at : null));
      text('task-attempt', `${active.attempts} / ${active.max_attempts}`);
      text('task-checkpoint', `Checkpoint ${checkpoint.stage || '—'} · ${when(active.updated_at, true)}`);
      if (active.status === 'RUNNING') text('task-activity', (worker && worker.current_task && worker.current_task.id === active.id && worker.activity) || 'Executing approved work');
      else if (active.status === 'WAITING_APPROVAL') text('task-activity', 'Waiting for human approval');
      else if (active.status === 'READY') text('task-activity', 'Ready for the supervisor');
      else text('task-activity', (outcome && outcome.summary) || `Task ${String(active.status).toLowerCase()}`);
      if (!health.ledger_ok) setVerification('Unavailable — ledger verification failed');
      else if (outcomeVerification.length) setVerification(outcomeVerification.join(' · '), true);
      else setVerification(active.status === 'SUCCEEDED' ? 'Task completed; no structured verification detail' : 'No completed verification');
      text('result-log', resultLog(active));
      try {
        renderTimeline(await json(`/tasks/${encodeURIComponent(active.id)}/events`));
      } catch (error) {
        if (error && error.status === 401) throw error;
        renderTimelineMessage(error && error.timedOut ? 'Evidence events timed out and are currently unavailable.' : 'Evidence events could not be loaded.', true);
      }
    } else {
      text('task-title', total ? 'Task details unavailable' : 'No persisted tasks');
      text('task-status', total ? 'UNKNOWN' : 'IDLE');
      byId('task-status').className = total ? 'status-chip neutral' : 'status-chip success';
      text('task-goal', total ? 'Task details were not returned in this refresh.' : 'Create a task to begin building durable evidence.');
      text('task-id', '\u2014'); text('task-stage', total ? '\u2014' : 'idle'); text('task-elapsed', '\u2014'); text('task-attempt', '\u2014'); text('task-checkpoint', 'Checkpoint \u2014');
      text('task-activity', total ? 'Details unavailable' : 'Waiting for a human-created task');
      setVerification('Nothing pending');
      text('result-log', total ? 'No task result was returned.' : 'No task exists yet, so no result has been recorded.');
      renderTimelineMessage(total ? 'No task is available to select for evidence.' : 'No task exists yet; evidence will appear after one is created.');
    }

    renderFailure(counts, worker, health);
    markUpdated();
    return updateOperationalAnnouncement(health, active, counts, total, worker);
  }

  function markUpdated() {
    const stamp = new Date().toISOString();
    text('updated-at', when(stamp, true));
    byId('updated-at').dateTime = stamp;
  }

  function showAuthPanel(errorMessage = '') {
    const panel = byId('auth-panel');
    const wasHidden = panel.hidden;
    panel.hidden = false;
    setAuthError(errorMessage);
    if (wasHidden) window.setTimeout(() => byId('api-token').focus({ preventScroll: true }), 0);
  }

  async function refresh(announceCompletion = false) {
    if (refreshing) return;
    refreshing = true;
    const button = byId('refresh-button');
    button.disabled = true;
    byId('auth-connect').disabled = true;
    byId('auth-forget').disabled = true;
    try {
      const [health, tasks, overview, lessons] = await Promise.all([
        json('/health', true), json('/tasks'), json('/overview'), json('/lessons'),
      ]);
      const stateChanged = await render({ health, tasks, overview, lessons });
      if (announceCompletion && !stateChanged) announce('Jarvis status refreshed.');
    } catch (error) {
      const unauthorized = Boolean(error && error.status === 401);
      lastOperationalSignature = null;
      if (unauthorized) {
        authorizationRequired = true;
        setSystemState('attention', 'Authorization required', 'The supervisor is protected. Enter its local API token to view persisted state.', 'Protected');
        scrubProtected('unauthorized');
        showAuthPanel(apiToken ? 'That token was not accepted.' : '');
        if (announceCompletion) announce('Authorization is required to refresh Jarvis status.');
      } else {
        authorizationRequired = false;
        byId('auth-panel').hidden = true;
        setAuthError('');
        const timedOut = Boolean(error && error.timedOut);
        setSystemState('offline', timedOut ? 'Jarvis did not respond' : 'Jarvis is offline', timedOut ? 'The local supervisor did not answer before the request timed out. Retry after confirming Jarvis is responsive.' : 'The Cockpit lost contact with the local supervisor. Start Jarvis or restore the connection, then refresh this page.', 'Offline');
        scrubProtected('offline');
        if (timedOut) {
          text('failure-message', 'The supervisor request timed out.');
          text('next-action', 'Confirm Jarvis is responsive, then retry the refresh.');
        }
        if (announceCompletion) announce(timedOut ? 'Jarvis status refresh timed out.' : 'Jarvis status refresh failed.');
      }
      markUpdated();
    } finally {
      refreshing = false;
      button.disabled = false;
      byId('auth-connect').disabled = false;
      byId('auth-forget').disabled = false;
    }
  }

  byId('refresh-button').addEventListener('click', () => refresh(true));
  byId('poll-button').addEventListener('click', () => {
    pollingPaused = !pollingPaused;
    const button = byId('poll-button');
    button.textContent = pollingPaused ? 'Resume auto-refresh' : 'Pause auto-refresh';
    button.setAttribute('aria-pressed', pollingPaused ? 'true' : 'false');
    announce(pollingPaused ? 'Automatic status refresh paused.' : 'Automatic status refresh resumed.');
    if (!pollingPaused && !authorizationRequired) refresh(false);
  });
  byId('auth-connect').addEventListener('click', () => {
    const supplied = byId('api-token').value.trim();
    if (!supplied) {
      setAuthError('Enter the local API token.');
      byId('api-token').focus();
      return;
    }
    apiToken = supplied;
    authorizationRequired = false;
    setAuthError('');
    try { sessionStorage.setItem('jarvis-api-token', apiToken); } catch (_) { /* session storage unavailable */ }
    refresh(true);
  });
  byId('auth-forget').addEventListener('click', () => {
    apiToken = '';
    byId('api-token').value = '';
    try { sessionStorage.removeItem('jarvis-api-token'); } catch (_) { /* session storage unavailable */ }
    authorizationRequired = true;
    lastOperationalSignature = null;
    setSystemState('attention', 'Authorization required', 'The saved browser-session token was removed. Enter a token to view protected supervisor state.', 'Protected');
    scrubProtected('unauthorized');
    showAuthPanel('');
    markUpdated();
    announce('Saved API token removed. Protected state is now hidden.');
    refresh(true);
  });
  byId('api-token').addEventListener('input', () => setAuthError(''));
  byId('api-token').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') byId('auth-connect').click();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !pollingPaused && !authorizationRequired) refresh(false);
  });
  refresh(false);
  window.setInterval(() => {
    if (!document.hidden && !pollingPaused && !authorizationRequired) refresh(false);
  }, 3000);
})();
""".encode("utf-8")
