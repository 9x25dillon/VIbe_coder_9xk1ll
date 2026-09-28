// VibeCoder in a browser: screens, navigation and the fight's pacing.
//
// This file renders facts and sends intents; it decides nothing about the
// game. Seeds, difficulty, attempts, the solve clock, scores and saves all
// belong to the Python engine (`vibecoder.service`), reached through
// `engine.js`. The one clock kept here is the fight's animation, and it is
// *reported* to the engine so that watching slowly is never scored as solving
// slowly -- the same subtraction `cli._Pacer` makes.

import { bar, bossArt, logo, pips, stars } from "./ascii.js";
import { $, $$, html, mmss, mount, raw, sleep } from "./dom.js";
import { CodeEditor, keybar } from "./editor.js";
import { Engine, EngineError } from "./engine.js";

const root = document.documentElement;
const app = $("#app");

// CLI parity: seconds per watched line, and laps of one line worth watching.
const LIVE_DELAY = 0.35;
const LOOP_PATIENCE = 3;

const state = {
  engine: null,
  info: {},
  hello: {},
  catalogue: null,
  stack: [],
  current: null,
  sheet: null,
  drafts: new Map(),
  settings: loadSettings(),
};

// ------------------------------------------------------------- settings

function loadSettings() {
  const defaults = { crt: true, motion: "auto", haptics: true, size: "m", speed: 1, seen: false };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem("vibecoder.settings") || "{}") };
  } catch {
    return defaults;
  }
}

function saveSettings() {
  try { localStorage.setItem("vibecoder.settings", JSON.stringify(state.settings)); } catch { /* private mode */ }
  applySettings();
}

function applySettings() {
  const s = state.settings;
  root.classList.toggle("no-crt", !s.crt);
  root.classList.toggle("calm", s.motion === "off");
  root.classList.toggle("motion", s.motion === "on");
  root.dataset.size = s.size;
  root.dataset.haptics = s.haptics ? "on" : "off";
}

function calm() {
  if (root.classList.contains("calm")) return true;
  if (root.classList.contains("motion")) return false;
  return matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function buzz(pattern) {
  if (state.settings.haptics && navigator.vibrate) {
    try { navigator.vibrate(pattern); } catch { /* not allowed */ }
  }
}

let toastTimer = 0;
function toast(text, ms = 2800) {
  let el = $(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    document.body.append(el);
  }
  el.textContent = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), ms);
}

// ----------------------------------------------------------- navigation

const SCREENS = {};

function go(name, params = {}, { replace = false } = {}) {
  closeSheet();
  if (state.current && state.current.cleanup) state.current.cleanup();
  if (replace && state.stack.length) state.stack.pop();
  else if (state.stack.length) history.pushState({ depth: state.stack.length + 1 }, "");
  state.stack.push({ name, params });
  render();
}

function render() {
  const { name, params } = state.stack[state.stack.length - 1];
  state.current = { name, actions: {}, cleanup: null };
  window.scrollTo(0, 0);
  SCREENS[name](params, state.current);
}

// The single back path: the Android shell, the browser's back button and the
// on-screen arrow all end up here.
async function internalBack() {
  if (closeSheet()) return true;
  if (state.current && state.current.beforeLeave) {
    const leave = await state.current.beforeLeave();
    if (!leave) {
      history.pushState({ depth: state.stack.length }, "");
      return true;
    }
  }
  if (state.stack.length <= 1) return false;
  if (state.current && state.current.cleanup) state.current.cleanup();
  state.stack.pop();
  render();
  return true;
}

window.addEventListener("popstate", () => { internalBack(); });

// Called by the Android shell. Answers synchronously whether the app will
// handle it; the shell closes the activity on `false`.
window.vcBack = () => {
  if (state.sheet) { closeSheet(); return true; }
  if (state.stack.length > 1 || (state.current && state.current.beforeLeave)) {
    history.back();
    return true;
  }
  return false;
};

app.addEventListener("click", (event) => {
  const target = event.target.closest("[data-act]");
  if (!target || !state.current) return;
  const action = state.current.actions[target.dataset.act] || GLOBAL[target.dataset.act];
  if (action) {
    event.preventDefault();
    action(target.dataset, target, event);
  }
});

const GLOBAL = {
  back: () => history.back(),
  home: () => { state.stack = []; go("home"); },
  nav: (data) => {
    if (state.current && state.current.name === data.to) return;
    state.stack = [];
    go(data.to);
  },
};

function navBar(active) {
  const item = (to, glyph, label) => html`
    <button data-act="nav" data-to="${to}" aria-current="${active === to ? "page" : "false"}">
      <span aria-hidden="true">${glyph}</span>${label}</button>`;
  return html`<nav class="nav" aria-label="main">
    ${item("home", "▦", "Campaign")}${item("stats", "▲", "Stats")}${item("settings", "⚙\uFE0E", "Setup")}
  </nav>`;
}

function topBar({ title, small = "", meta = "", backLabel = "back" }) {
  return html`<header class="bar">
    <button class="icon-btn" data-act="back" aria-label="${backLabel}">&lt;</button>
    <div class="title">${title}${small ? html`<small>${small}</small>` : ""}</div>
    ${meta ? html`<div class="meta">${meta}</div>` : ""}
  </header>`;
}

// ---------------------------------------------------------------- sheets

function openSheet(template, { cls = "", onClose = null, dismissable = true } = {}) {
  closeSheet();
  const scrim = document.createElement("div");
  scrim.className = "sheet-scrim";
  const sheet = document.createElement("section");
  sheet.className = `sheet ${cls}`;
  sheet.setAttribute("role", "dialog");
  sheet.innerHTML = `<div class="grip" aria-hidden="true"></div><div class="sheet-body"></div>`;
  mount(sheet.querySelector(".sheet-body"), template);
  document.body.append(scrim, sheet);
  const entry = { sheet, scrim, onClose, dismissable, actions: {} };
  if (dismissable) scrim.addEventListener("click", () => closeSheet());
  sheet.addEventListener("click", (event) => {
    const target = event.target.closest("[data-act]");
    if (!target) return;
    const action = entry.actions[target.dataset.act];
    if (action) {
      event.preventDefault();
      action(target.dataset, target, event);
    }
  });
  state.sheet = entry;
  return entry;
}

function closeSheet() {
  const entry = state.sheet;
  if (!entry) return false;
  if (!entry.dismissable && !entry.forced) return true;
  state.sheet = null;
  entry.sheet.remove();
  entry.scrim.remove();
  if (entry.onClose) entry.onClose();
  return true;
}

function forceClose() {
  if (state.sheet) state.sheet.forced = true;
  return closeSheet();
}

function ask({ title, body, ok = "Confirm", cancel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    let answered = false;
    const entry = openSheet(html`
      <div class="verdict ${danger ? "bad" : "good"}">${title}</div>
      <p class="muted">${body}</p>
      <div class="row">
        <button class="btn quiet" data-act="no">${cancel}</button>
        <button class="btn ${danger ? "danger" : ""} primary" data-act="yes">${ok}</button>
      </div>`, {
      cls: danger ? "red" : "",
      onClose: () => { if (!answered) resolve(false); },
    });
    entry.actions.yes = () => { answered = true; closeSheet(); resolve(true); };
    entry.actions.no = () => { answered = true; closeSheet(); resolve(false); };
  });
}

function failure(error) {
  if (error instanceof EngineError) {
    toast(error.message);
    if (error.code === "internal") console.error(error.trace);
  } else {
    toast(String((error && error.message) || error));
    console.error(error);
  }
}

// ----------------------------------------------------------------- boot

async function boot() {
  applySettings();
  let lines = [];
  const logLine = (label, value = "", cls = "") => {
    lines = lines.filter((line) => line.label !== label);
    lines.push({ label, value, cls });
    const log = $(".boot-log");
    if (log) {
      mount(log, html`${lines.map((line) => html`<span>&gt; ${line.label.padEnd(26, ".")} <span class="${line.cls}">${line.value}</span>\n</span>`)}<span class="cursor"></span>`);
    }
  };

  mount(app, html`<section class="screen boot">
    <div class="logo-wrap">${logo(app.clientWidth || innerWidth)}</div>
    <div class="tagline">python // acid // punk</div>
    <pre class="boot-log" aria-live="polite"></pre>
  </section>`);

  try {
    state.info = await (await fetch("build-info.json", { cache: "no-store" })).json();
  } catch { state.info = {}; }
  logLine(`vibecoder ${state.info.engine || ""}`, `build ${state.info.build || "dev"}`, "faint");

  if (typeof WebAssembly !== "object" || typeof Worker !== "function") {
    logLine("webassembly", "MISSING", "bad");
    return;
  }

  const cores = navigator.hardwareConcurrency || 4;
  const engine = new Engine({
    poolSize: cores >= 4 ? 2 : 1,
    onStatus: (text) => logLine("engine", text),
    onWarn: (text) => toast(text),
  });
  state.engine = engine;
  engine.pool.onBoot = (count) => logLine("sandboxes", `${count} warm`, "ok");
  logLine(`python ${state.info.python || "3"} → wasm`, "loading");

  try {
    await engine.ready;
    logLine(`python ${state.info.python || "3"} → wasm`, "online", "ok");
    state.hello = await engine.call("hello");
    logLine("engine", `v${state.hello.engine} online`, "ok");
    state.catalogue = await engine.call("catalogue");
    logLine("save file", `${state.catalogue.player.cleared}/${state.catalogue.player.levels} cleared`, "ok");
  } catch (error) {
    logLine("engine", "FAILED", "bad");
    mount($(".boot"), html`${raw($(".boot").innerHTML)}
      <div class="panel red"><span class="tag">boot failed</span>
        <p>${String((error && error.message) || error)}</p>
        <p class="muted small">VibeCoder runs Python in WebAssembly. It needs a
        recent browser with WebAssembly and module workers.</p>
        <button class="btn danger" data-act="reload">Retry</button></div>`);
    state.current = { actions: { reload: () => location.reload() } };
    return;
  }
  await sleep(calm() ? 0 : 450);
  history.replaceState({ depth: 1 }, "");
  go("home");
}

// ----------------------------------------------------------------- home

function allRows() {
  const rows = [];
  for (const world of state.catalogue.worlds) {
    for (const level of world.levels) rows.push({ ...level, world: world.world, world_title: world.title });
  }
  return rows;
}

function findLevel(id) {
  return allRows().find((row) => row.id === id);
}

function findBoss(id) {
  for (const world of state.catalogue.worlds) {
    const boss = world.bosses.find((b) => b.id === id);
    if (boss) return { ...boss, world: world.world, world_title: world.title };
  }
  return null;
}

SCREENS.home = async (params, screen) => {
  try { state.catalogue = await state.engine.call("catalogue"); } catch (error) { failure(error); }
  if (state.current !== screen) return;
  const { worlds, player, daily } = state.catalogue;
  const next = state.catalogue.next;
  const fresh = !player.cleared && !allRows().some((row) => row.attempts);

  const levelRow = (level) => {
    const cls = [level.stars ? "done" : "", level.id === next ? "next" : ""].join(" ");
    return html`<li><button class="level-row ${cls}" data-act="open" data-id="${level.id}">
      <span class="num">${String(level.index).padStart(2, "0")}</span>
      <span class="name"><b>${level.title}</b><small>${level.summary}</small></span>
      <span class="right">${stars(level.stars)}<br><span class="faint">${level.best ? level.best.toFixed(1) : "--"}</span></span>
    </button></li>`;
  };
  const bossRow = (boss) => html`<li><button class="level-row boss" data-act="boss" data-id="${boss.id}">
      <span class="num">☠\uFE0E</span>
      <span class="name"><b>BOSS :: ${boss.title}</b><small>${boss.steps} steps · ${boss.summary}</small></span>
      <span class="right red-t">FIGHT</span>
    </button></li>`;

  mount(app, html`<section class="screen">
    <div class="scroll">
      <div class="logo-wrap">${logo(app.clientWidth)}</div>
      <div class="tagline">write it right // write it fast // make it lean</div>
      <div class="hud">
        <div class="stat"><span>score</span><b>${player.total_score.toFixed(0)}</b></div>
        <div class="stat pink"><span>streak</span><b>${player.streak}${player.streak > 1 ? html`<small class="small"> x${player.streak_multiplier.toFixed(1)}</small>` : ""}</b></div>
        <div class="stat yellow"><span>stars</span><b>${player.stars}/${player.max_stars}</b></div>
        <div class="stat wide-only"><span>cleared</span><b>${player.cleared}/${player.levels}</b></div>
      </div>

      ${fresh ? html`<div class="panel cyan"><span class="tag">how you're scored</span>
        <div class="axes">
          <div class="axis"><b>Accuracy</b><span>the share of hidden tests your code passes. <span class="faint">50%</span></span></div>
          <div class="axis"><b>Speed</b><span>how long <i>you</i> took, against par. Not how fast your code runs. <span class="faint">25%</span></span></div>
          <div class="axis"><b>Functional</b><span>how much work your code does next to the reference: lines executed, memory. <span class="faint">25%</span></span></div>
        </div>
        <p class="small muted" style="margin-top:10px">Correct but wasteful code still gets called out. That's the point.</p>
      </div>` : ""}

      ${daily ? html`<div class="panel pink"><span class="tag">daily // ${daily.date}</span>
        <div class="daily">
          <div><h3>${daily.title}</h3>
            <div class="small muted">same level, same variant, for everyone today${daily.streak ? html` · <span class="pink-t">${daily.streak} day streak</span>` : ""}</div>
            ${daily.played ? html`<div class="small">ranked: <b class="acid">${daily.played.total.toFixed(1)}</b> ${stars(daily.played.stars)}</div>` : ""}
          </div>
          <button class="btn pink ${daily.played ? "" : "primary"}" data-act="daily" data-id="${daily.level_id}">${daily.played ? "Replay" : "Play"}</button>
        </div></div>` : ""}

      <div class="worlds">
      ${worlds.map((world) => html`<div class="panel"><span class="tag">world ${String(world.world).padStart(2, "0")} :: ${world.title}</span>
        <ul class="level-list">${world.levels.map(levelRow)}${world.bosses.map(bossRow)}</ul>
      </div>`)}
      </div>

      <div class="ticker" aria-hidden="true"><span>
        // NO CLOUD // NO ACCOUNTS // NO TELEMETRY // YOUR CODE NEVER LEAVES THIS DEVICE //
        PYTHON ${state.hello.python || ""} ON WEBASSEMBLY // CORRECT IS NOT THE SAME AS GOOD //
      </span></div>
    </div>
    ${navBar("home")}
  </section>`);

  screen.actions.open = (data) => go("brief", { id: data.id });
  screen.actions.daily = (data) => go("brief", { id: data.id, daily: true });
  screen.actions.boss = (data) => go("boss", { id: data.id });
};

// ---------------------------------------------------------------- brief

SCREENS.brief = (params, screen) => {
  const level = findLevel(params.id);
  if (!level) { go("home", {}, { replace: true }); return; }
  mount(app, html`<section class="screen">
    ${topBar({ title: params.daily ? "Daily" : `World ${level.world}`, small: `level ${level.index}` })}
    <div class="scroll">
      <div class="small pink-t">${level.world_title.toUpperCase()}${params.daily ? " // DAILY" : ""}</div>
      <h1 class="brief-title glitch" data-text="${level.title}">${level.title}</h1>
      <div class="small faint">${level.id}</div>
      <div class="panel"><span class="tag">briefing</span>
        <p class="brief-text">${level.summary}</p>
        <p class="faint small">The full brief is in the editor's docstring. Your function is judged on hidden tests.</p>
      </div>
      <div class="panel cyan"><span class="tag">record</span>
        <dl class="kv">
          <dt>best</dt><dd>${level.best ? level.best.toFixed(1) : "--"} ${stars(level.stars)}</dd>
          <dt>attempts</dt><dd>${level.attempts}</dd>
          <dt>par</dt><dd>${mmss(level.par)}</dd>
          <dt>worth</dt><dd>x${level.multiplier.toFixed(1)} to your score</dd>
        </dl>
        ${level.tags.length ? html`<div class="chips" style="margin-top:10px">${level.tags.map((tag) => html`<span class="chip">${tag}</span>`)}</div>` : ""}
      </div>
      <p class="small muted" style="margin-top:18px">The clock starts when the editor opens. Speed is <i>your</i> time to the first passing run.</p>
    </div>
    <div class="actions">
      <button class="btn primary run" data-act="start"><span class="label">Jack in ▶</span></button>
    </div>
  </section>`);

  screen.actions.start = async (data, button) => {
    button.classList.add("busy");
    $(".label", button).textContent = "calibrating…";
    try {
      const opened = await state.engine.call("open_level", { level_id: level.id, daily: Boolean(params.daily) });
      if (state.current !== screen) { state.engine.call("abandon", { play_id: opened.play }); return; }
      go("play", { opened, daily: Boolean(params.daily) }, { replace: true });
    } catch (error) {
      failure(error);
      button.classList.remove("busy");
      $(".label", button).textContent = "Jack in ▶";
    }
  };
};

// ----------------------------------------------------------------- play

SCREENS.play = ({ opened }, screen) => {
  const level = opened.level;
  const draftKey = `${level.id}`;
  const started = performance.now();
  let attempt = 0;
  let busy = false;
  let lastRun = null;
  let finished = false;

  mount(app, html`<section class="screen play">
    <header class="bar">
      <button class="icon-btn" data-act="back" aria-label="leave level">✕</button>
      <div class="title">${level.title}<small class="attempt">variant ${opened.seed}</small></div>
      <div class="meta"><span class="timer nums">00:00</span><br><span class="faint small">par ${mmss(level.par)}</span></div>
    </header>
    <div class="play-body">
      <div class="play-main">
        <div class="ed-host" style="flex:1;min-height:0;display:flex"></div>
        <div class="kb-host"></div>
      </div>
      <aside class="play-side">${briefPanels(opened)}</aside>
    </div>
    <div class="actions">
      <button class="btn cyan brief-btn" data-act="brief">Brief</button>
      <button class="btn primary run" data-act="run"><span class="label">Run ▶</span></button>
    </div>
  </section>`);

  const editor = new CodeEditor($(".ed-host"), {
    value: state.drafts.get(draftKey) || level.starter,
    onRun: () => screen.actions.run(),
    label: `${level.func_name} source`,
  });
  keybar($(".kb-host"), editor);
  editor.text.addEventListener("input", () => state.drafts.set(draftKey, editor.value));

  const timer = $(".timer");
  const tick = setInterval(() => {
    const seconds = (performance.now() - started) / 1000;
    timer.textContent = mmss(seconds);
    timer.classList.toggle("over", seconds > level.par);
  }, 250);

  screen.cleanup = () => {
    clearInterval(tick);
    state.engine.onProgress = null;
  };
  screen.beforeLeave = async () => {
    if (finished) return true;
    const leave = await ask({
      title: "Leave?",
      body: "Leaving banks nothing and the variant is dropped. Your draft stays until you close the app.",
      ok: "Leave", cancel: "Stay", danger: true,
    });
    if (leave) {
      finished = true;
      state.engine.call("abandon", { play_id: opened.play }).catch(() => {});
    }
    return leave;
  };

  screen.actions.brief = () => {
    openSheet(html`${briefPanels(opened)}
      <div class="row" style="margin-top:14px"><button class="btn wide" data-act="close">Back to code</button></div>`)
      .actions.close = () => closeSheet();
  };

  screen.actions.run = async () => {
    if (busy || finished) return;
    busy = true;
    const button = $(".btn.run");
    button.classList.add("busy");
    $(".label", button).textContent = "running…";
    attempt += 1;
    $(".attempt").textContent = `variant ${opened.seed} · attempt ${attempt}`;
    editor.clearMarks();

    const cases = Array.from({ length: opened.cases }, (_, i) => i);
    const sheet = openSheet(html`
      <div class="verdict">RUNNING</div>
      <div class="cases" aria-label="test progress">${cases.map((i) => html`<span class="case wait" data-case="${i}">·</span>`)}</div>
      <p class="small faint">each case runs in a fresh python sandbox</p>`, { dismissable: false });
    state.engine.onProgress = (event) => {
      const cell = $(`[data-case="${event.index}"]`, sheet.sheet);
      if (!cell) return;
      cell.classList.remove("wait");
      cell.classList.add(event.passed ? "pass" : "fail");
      cell.textContent = event.passed ? "✓" : "✗";
    };

    let ran;
    try {
      ran = await state.engine.call("run", { play_id: opened.play, code: editor.value });
    } catch (error) {
      busy = false;
      forceClose();
      button.classList.remove("busy");
      $(".label", button).textContent = "Run ▶";
      failure(error);
      return;
    }
    lastRun = ran;
    state.engine.onProgress = null;
    busy = false;
    button.classList.remove("busy");
    $(".label", button).textContent = "Run ▶";

    if (ran.all_passed) {
      buzz([20, 40, 60]);
      forceClose();
      await finish(false);
      return;
    }
    buzz([80, 60, 80]);
    forceClose();
    showResult(ran);
  };

  function showResult(ran) {
    const failed = ran.first_failure;
    const entry = openSheet(html`
      <div class="verdict bad">${ran.fatal ? (ran.error_type || "crashed") : `${ran.passed}/${ran.total} passed`}</div>
      ${ran.outcomes.length ? html`<div class="cases">${ran.outcomes.map((o) => html`<span class="case ${o.passed ? "pass" : "fail"}" title="${o.name}">${o.passed ? "✓" : "✗"}</span>`)}</div>` : ""}
      ${ran.fatal ? html`<div class="fail-box"><b class="red-t">${ran.error}</b></div>` : ""}
      ${failed ? html`<div class="fail-box">
        <div class="small faint">first failure: ${failed.name}</div>
        <dl class="kv">
          ${failed.given ? html`<dt>given</dt><dd>${failed.given}</dd>` : ""}
          ${failed.error
            ? html`<dt>raised</dt><dd class="bad">${failed.error}</dd>`
            : html`<dt>expected</dt><dd>${failed.expected}</dd><dt>you gave</dt><dd class="bad">${failed.got}</dd>`}
        </dl>
        ${failed.others ? html`<div class="small faint">${failed.others_same ? `the other ${failed.others} failed the same way` : `${failed.others} more failed`}</div>` : ""}
      </div>` : ""}
      ${ran.stdout ? html`<div class="small faint">stdout</div><pre class="out">${ran.stdout}</pre>` : ""}
      ${ran.hints.map((hint, i) => html`<div class="hint"><b>HINT ${i + 1}</b> ${hint}</div>`)}
      <div class="row" style="margin-top:14px">
        <button class="btn quiet" data-act="giveup">Give up &amp; bank</button>
        <button class="btn primary" data-act="edit">Fix it</button>
      </div>`, { cls: "red" });
    entry.actions.edit = () => { closeSheet(); editor.focus(); };
    entry.actions.giveup = async () => {
      closeSheet();
      const sure = await ask({
        title: "Bank it?",
        body: "Your last run is scored as it stands and saved to your record. Unsolved levels bank at zero stars.",
        ok: "Bank", cancel: "Keep going", danger: true,
      });
      if (sure) await finish(true);
    };
  }

  async function finish(giveUp) {
    try {
      const result = await state.engine.call("finish", { play_id: opened.play, give_up: giveUp });
      finished = true;
      state.drafts.delete(draftKey);
      go("score", { result, level, daily: opened.daily }, { replace: true });
    } catch (error) {
      failure(error);
    }
  }
};

function briefPanels(opened) {
  const level = opened.level;
  return html`
    <div class="panel"><span class="tag">objective</span>
      <p><b class="acid">${level.func_name}()</b></p>
      <p class="muted small" style="white-space:pre-wrap">${level.brief}</p>
    </div>
    ${level.style_goals.length ? html`<div class="panel pink"><span class="tag">style goal +5%</span>
      ${level.style_goals.map((goal) => html`<p class="small">${goal}</p>`)}</div>` : ""}
    <div class="panel cyan"><span class="tag">variant</span>
      <dl class="kv">
        <dt>cases</dt><dd>${opened.cases} hidden</dd>
        <dt>par</dt><dd>${mmss(level.par)}</dd>
        <dt>difficulty</dt><dd>${opened.difficulty.band}</dd>
      </dl>
      ${opened.difficulty.source !== "default" ? html`<p class="small faint" style="margin-top:6px">${opened.difficulty.reason}</p>` : ""}
    </div>`;
}

// ---------------------------------------------------------------- score

function gauge(label, value, weight, detail, cls = "") {
  return html`<div class="gauge ${cls}">
    <div class="gauge-top"><b>${label}</b><span class="nums">${value.toFixed(1)} <span class="faint">x${weight.toFixed(2)}</span></span></div>
    ${meter(value, 100)}
    ${detail ? html`<small>${detail}</small>` : ""}
  </div>`;
}

const BONUS_NAMES = { first_try: "first try", elegance: "elegance", clean_first_run: "clean first run" };

SCREENS.score = ({ result, level }, screen) => {
  const s = result.score;
  const cleared = result.all_passed;
  const next = result.next;
  mount(app, html`<section class="screen">
    <header class="bar">
      <button class="icon-btn" data-act="home" aria-label="campaign">▦</button>
      <div class="title">Score<small>${level.title}</small></div>
    </header>
    <div class="scroll">
      <div class="verdict ${cleared ? "good" : "bad"}">${cleared ? "LEVEL CLEAR" : "BANKED"}</div>
      <div class="small muted">${result.passed}/${result.total} cases · ${mmss(result.elapsed)} solve time</div>
      <div class="score-head">
        <div class="big-total" aria-label="total ${s.total}">0.0</div>
        <div class="score-stars" aria-label="${s.stars} stars">${[0, 1, 2].map((i) => html`<span class="${i < s.stars ? "on" : "off"}" style="animation-delay:${0.9 + i * 0.18}s">${i < s.stars ? "★" : "☆"}</span>`)}</div>
      </div>
      <div class="row" style="gap:6px;margin:10px 0 0">
        ${Object.keys(s.bonuses).map((name) => html`<span class="sticker acid">+${Math.round(s.bonuses[name] * 100)}% ${BONUS_NAMES[name] || name}</span>`)}
        ${result.outcome.improved ? html`<span class="sticker">new personal best</span>` : ""}
        ${result.outcome.streak > 1 ? html`<span class="sticker yellow">streak ${result.outcome.streak} · x${result.outcome.streak_multiplier.toFixed(1)}</span>` : ""}
        ${result.daily ? html`<span class="sticker violet">${result.daily.ranked ? "daily ranked" : "daily replay"}</span>` : ""}
        ${next && next.world_complete ? html`<span class="sticker cyan">world complete</span>` : ""}
        ${next && next.campaign_complete ? html`<span class="sticker cyan">campaign complete</span>` : ""}
      </div>

      <div class="panel"><span class="tag">three axes</span>
        ${gauge("accuracy", s.accuracy, result.weights.accuracy, `${result.passed}/${result.total} hidden cases`)}
        ${gauge("speed", s.speed, result.weights.speed, cleared ? `${mmss(result.elapsed)} vs ${mmss(result.par)} par — your time, not your code's` : "only scored once every case passes", "pink")}
        ${gauge("functional", s.functional, result.weights.functional, `${result.ops.toLocaleString()} ops vs ${result.ref_ops.toLocaleString()} reference · ${(result.peak_bytes / 1024).toFixed(1)} KiB peak`, "cyan")}
        <div class="small muted" style="margin-top:8px">subtotal ${s.subtotal.toFixed(1)}${Object.keys(s.bonuses).length ? html` × ${(1 + Object.values(s.bonuses).reduce((a, b) => a + b, 0)).toFixed(2)} bonuses` : ""}</div>
      </div>

      ${result.tips.length ? html`<div class="panel pink"><span class="tag">vibe tips</span>
        <ul class="tips">${result.tips.map((tip) => html`<li>${tip}</li>`)}</ul></div>` : ""}

      ${next && next.drill ? html`<div class="panel cyan"><span class="tag">drill</span>
        <p class="small">${next.drill.reason}</p></div>` : ""}
      ${next && next.level ? html`<div class="panel"><span class="tag">next up</span>
        <p><b class="acid">${next.level.title}</b></p><p class="small muted">${next.level.summary}</p></div>` : ""}
    </div>
    <div class="actions">
      ${result.trace.length ? html`<button class="btn cyan" data-act="replay">Replay</button>` : ""}
      ${next && next.level
        ? html`<button class="btn primary run" data-act="next" data-id="${next.level.id}">Next ▸</button>`
        : html`<button class="btn primary run" data-act="home">Campaign</button>`}
    </div>
  </section>`);

  countUp($(".big-total"), s.total);
  if (!calm()) animateBars();

  screen.actions.replay = () => go("replay", { code: result.code, trace: result.trace, title: level.title });
  screen.actions.next = (data) => { state.stack = [{ name: "home", params: {} }]; go("brief", { id: data.id }); };
};

function countUp(element, target) {
  if (calm()) { element.textContent = target.toFixed(1); return; }
  const start = performance.now();
  const duration = 900;
  const frame = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    element.textContent = (target * eased).toFixed(1);
    if (t < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function animateBars() {
  $$(".gauge > .gauge-bar[data-max]").forEach((element, index) => {
    const value = Number(element.dataset.value);
    const max = Number(element.dataset.max);
    let shown = 0;
    const step = () => {
      if (!element.isConnected) return;
      shown = Math.min(value, shown + max / 25);
      fitBar(element, shown);
      if (shown < value) setTimeout(step, 16);
    };
    fitBar(element, 0);
    setTimeout(step, 200 + index * 220);
  });
}

// A text bar as wide as its box: the cell count is measured, not guessed, so
// a meter fills a phone and a desktop panel alike and the glyph grid holds.
function meter(value, max, cls = "") {
  return html`<div class="gauge-bar ${cls}" data-value="${value}" data-max="${max}" role="img" aria-label="${Math.round(value)} of ${max}"></div>`;
}

function fitBar(element, value = Number(element.dataset.value)) {
  const size = parseFloat(getComputedStyle(element).fontSize) || 13;
  const cells = Math.max(4, Math.floor(element.clientWidth / (size * 0.6 - 0.5)));
  mount(element, bar(value, Number(element.dataset.max), cells));
  element.dataset.fit = "1";
}

function fitBars(scope = document, all = false) {
  $$(all ? "[data-max]" : "[data-max]:not([data-fit])", scope).forEach((element) => fitBar(element));
}

new MutationObserver(() => fitBars()).observe(document.body, { childList: true, subtree: true });

// --------------------------------------------------------------- replay

SCREENS.replay = ({ code, trace, title }, screen) => {
  let index = 0;
  let playing = false;
  let timer = 0;
  mount(app, html`<section class="screen">
    ${topBar({ title: "Replay", small: title })}
    <div class="ed-host" style="flex:1;min-height:0;display:flex"></div>
    <div style="padding:8px var(--gutter)"><dl class="locals" aria-live="polite"></dl></div>
    <div class="transport">
      <button class="icon-btn" data-act="first" aria-label="first step">«</button>
      <button class="icon-btn" data-act="prev" aria-label="previous step">‹</button>
      <div class="step nums"></div>
      <button class="icon-btn" data-act="toggle" aria-label="play or pause">▶</button>
      <button class="icon-btn" data-act="next" aria-label="next step">›</button>
    </div>
  </section>`);
  const editor = new CodeEditor($(".ed-host"), { value: code, readOnly: true, label: "replayed source" });
  const locals = $(".locals");
  let previous = {};

  const show = () => {
    const step = trace[index];
    if (!step) return;
    editor.mark(step.line, "cur");
    renderLocals(locals, step.locals, previous);
    previous = step.locals;
    $(".transport .step").textContent = `step ${index + 1}/${trace.length} · line ${step.line} · ${step.func}()`;
  };
  const stop = () => { playing = false; clearTimeout(timer); $("[data-act=toggle]").textContent = "▶"; };
  const play = () => {
    playing = true;
    $("[data-act=toggle]").textContent = "❚❚";
    const tick = () => {
      if (!playing) return;
      if (index >= trace.length - 1) { stop(); return; }
      index += 1;
      show();
      timer = setTimeout(tick, (LIVE_DELAY * 1000) / state.settings.speed);
    };
    timer = setTimeout(tick, 200);
  };
  screen.actions.first = () => { stop(); index = 0; previous = {}; show(); };
  screen.actions.prev = () => { stop(); index = Math.max(0, index - 1); show(); };
  screen.actions.next = () => { stop(); index = Math.min(trace.length - 1, index + 1); show(); };
  screen.actions.toggle = () => (playing ? stop() : play());
  screen.cleanup = stop;
  show();
  if (!calm()) play();
};

function renderLocals(element, values, previous = {}) {
  const names = Object.keys(values || {});
  if (!names.length) { mount(element, html`<dt class="faint">locals</dt><dd class="faint">(none yet)</dd>`); return; }
  mount(element, html`${names.map((name) => html`<dt>${name}</dt><dd class="${previous[name] !== values[name] ? "changed" : ""}">${values[name]}</dd>`)}`);
}

// ----------------------------------------------------------------- boss

SCREENS.boss = (params, screen) => {
  const meta = findBoss(params.id);
  if (!meta) { go("home", {}, { replace: true }); return; }
  let fight = null;
  let info = null;
  let slept = 0;
  let over = false;
  let skip = false;
  let editor = null;
  let started = 0;
  let tick = 0;

  mount(app, html`<section class="screen">
    ${topBar({ title: `Boss :: ${meta.title}`, small: `world ${meta.world}` })}
    <div class="scroll">
      <pre class="boss-art" aria-hidden="true">${bossArt(meta.id)}</pre>
      <h1 class="brief-title glitch center" data-text="${meta.title}">${meta.title}</h1>
      <div class="panel red"><span class="tag">threat</span>
        <p class="small">${meta.summary}</p>
        <p class="small muted">${meta.steps} functions in one file. Each step runs live, line by line.
        When it breaks, the fight pauses on the line that broke.</p>
      </div>
      <div class="panel cyan"><span class="tag">rules of engagement</span>
        <p class="small">◆\uFE0E Every fix costs a <b class="cyan-t">repair</b>. You have five.</p>
        <p class="small">♥\uFE0E A repair heals the boss by how wrong the code was.</p>
        <p class="small">☠\uFE0E Only a fight with nothing spent puts the boss <b class="acid">down</b>.</p>
        <p class="small faint">Watching is free: the replay's animation is taken off your clock.</p>
      </div>
    </div>
    <div class="actions"><button class="btn danger primary run" data-act="engage"><span class="label">Engage ▶</span></button></div>
  </section>`);

  screen.cleanup = () => { clearInterval(tick); over = true; };
  screen.beforeLeave = async () => {
    if (!fight || over) return true;
    const leave = await ask({ title: "Retreat?", body: "The fight ends here and is scored on what it achieved.", ok: "Retreat", cancel: "Fight on", danger: true });
    if (leave) await retreat();
    return false;
  };

  screen.actions.engage = async (data, button) => {
    button.classList.add("busy");
    $(".label", button).textContent = "summoning…";
    try {
      info = await state.engine.call("open_boss", { boss_id: meta.id });
      fight = info.fight;
    } catch (error) {
      failure(error);
      button.classList.remove("busy");
      $(".label", button).textContent = "Engage ▶";
      return;
    }
    started = performance.now();
    arena();
    await attempt(info.code);
  };

  function arena() {
    mount(app, html`<section class="screen boss-screen">
      <header class="bar">
        <button class="icon-btn" data-act="back" aria-label="retreat">✕</button>
        <div class="title">${meta.title}<small class="step-label"></small></div>
        <div class="meta"><span class="timer nums">00:00</span></div>
      </header>
      <div style="padding:8px var(--gutter) 0">
        <pre class="boss-art" aria-hidden="true" style="font-size:clamp(7px,2.2vw,11px)">${bossArt(meta.id)}</pre>
        <div class="hp"><div class="row" style="justify-content:space-between"><b class="red-t">BOSS HP</b><span class="hp-num nums"></span></div>
          <div class="hp-bar"></div>
          <div class="row" style="justify-content:space-between;margin-top:4px"><span class="faint">REPAIRS</span><span class="pip-host"></span></div>
        </div>
        <ul class="boss-steps"></ul>
        <div class="status small muted" aria-live="polite" style="min-height:1.5em;margin-top:6px"></div>
      </div>
      <div class="fight-code"><div class="ed-host" style="flex:1;min-height:0;display:flex"></div></div>
      <div style="padding:6px var(--gutter)"><dl class="locals" aria-live="off"></dl></div>
      <div class="actions">
        <button class="btn quiet" data-act="speed"><span class="speed-label">${state.settings.speed}x</span></button>
        <button class="btn cyan run" data-act="skip">Skip ▸▸</button>
      </div>
    </section>`);
    editor = new CodeEditor($(".ed-host"), { value: info.code, readOnly: true, label: "fight source" });
    tick = setInterval(() => { $(".timer").textContent = mmss((performance.now() - started) / 1000); }, 250);
    hud(info.state, 0);
  }

  function hud(fightState, index) {
    $(".hp-num").textContent = `${fightState.remaining}/${fightState.hp}`;
    const hp = $(".hp-bar");
    hp.dataset.value = fightState.remaining;
    hp.dataset.max = fightState.hp;
    fitBar(hp);
    mount($(".pip-host"), pips(fightState.repairs_left, fightState.spent));
    mount($(".boss-steps"), html`${info.boss.steps.map((step, i) => html`<li class="${i < fightState.cleared ? "won" : i === index ? "now" : ""}">${i + 1}. ${step.title} <span class="faint">${step.func_name}()</span></li>`)}`);
    const step = info.boss.steps[Math.min(index, info.boss.steps.length - 1)];
    $(".step-label").textContent = `step ${Math.min(index + 1, info.boss.steps.length)}/${info.boss.steps.length} · ${step.func_name}()`;
  }

  const say = (text, cls = "muted") => {
    const el = $(".status");
    if (el) { el.className = `status small ${cls}`; el.textContent = text; }
  };

  // Play events [from, until) at the fight's pace. Only the sleeps are
  // counted as animation; everything else is the player's time.
  async function watch(events, from, until) {
    const seen = new Map();
    let previous = {};
    const delay = () => (LIVE_DELAY * 1000) / state.settings.speed;
    skip = false;
    for (let i = from; i < until; i += 1) {
      if (over) return;
      const event = events[i];
      const laps = (seen.get(event.line) || 0) + 1;
      seen.set(event.line, laps);
      if (skip && i < until - 1) continue;
      editor.mark(event.line, "cur");
      renderLocals($(".locals"), event.locals, previous);
      previous = event.locals;
      if (laps <= LOOP_PATIENCE && !skip) {
        const t0 = performance.now();
        await sleep(calm() ? delay() / 3 : delay());
        slept += (performance.now() - t0) / 1000;
      } else if (i % 40 === 0) {
        await sleep(0);
      }
    }
  }

  function report() {
    const value = slept;
    slept = 0;
    return value;
  }

  async function attempt(code) {
    say("running the step live…");
    let body;
    try {
      body = await state.engine.call("boss_attempt", { fight_id: fight, code, slept: report() });
    } catch (error) { failure(error); return; }
    await resolve(body);
  }

  async function resolve(body) {
    if (over) return;
    editor.value = body.code;
    editor.clearMarks();
    hud(body.fight, body.step);
    if (body.divergence) toast(`replay diverged: ${body.divergence.reason}`, 4200);
    const events = body.events;
    const until = body.outcome === "crashed" ? body.paused_at + 1 : events.length;
    say(body.repair ? `${body.repair.message} — resuming at step ${body.resume_at + 1}` : "watching…", body.repair ? "pink-t" : "muted");
    await watch(events, body.resume_at || 0, until);
    if (over) return;

    if (body.outcome === "cleared") {
      buzz([30, 30, 90]);
      const art = $(".boss-art");
      art.classList.remove("hit");
      void art.offsetWidth;
      art.classList.add("hit");
      say(`STEP CLEARED — boss takes ${body.dealt}${body.spent ? ` (after ${body.spent} repair${body.spent > 1 ? "s" : ""})` : " (first try)"}`, "acid");
      hud(body.fight, body.state === "won" ? info.boss.steps.length : body.step + 1);
      await sleep(calm() ? 300 : 1400);
      if (body.state === "won") { await end(); return; }
      info.code = body.code;
      await attempt(null);
      return;
    }

    buzz([120, 50, 120]);
    $(".boss-screen").classList.add("shake", "flash-red");
    setTimeout(() => $(".boss-screen") && $(".boss-screen").classList.remove("shake", "flash-red"), 500);
    if (body.outcome === "crashed") {
      editor.mark(body.line, "err");
      say(`line ${body.line}: ${body.error}`, "red-t");
    } else {
      say(body.error || "wrong answer", "red-t");
    }
    if (body.state === "over") {
      say("no repairs left — the fight stops here", "red-t");
      await sleep(calm() ? 300 : 1400);
      await end();
      return;
    }
    repairSheet(body);
  }

  function repairSheet(body) {
    const failed = body.verdict.first_failure;
    const entry = openSheet(html`
      <div class="verdict bad">${body.outcome === "crashed" ? "Crashed" : "Wrong answer"}</div>
      <div class="fail-box">
        <b class="red-t">${body.outcome === "crashed" ? `line ${body.line}: ${body.error}` : body.error}</b>
        ${failed && body.outcome !== "crashed" && failed.given ? html`<div class="small faint">given ${failed.given}</div>` : ""}
        <div class="small muted" style="margin-top:4px">${Math.round(body.accuracy * 100)}% of this step's cases pass as written. Repairing costs ◆1; the boss heals more the lower that is.</div>
      </div>
      <div class="repair-ed" style="height:48dvh;display:flex;border:1px solid var(--line)"></div>
      <div class="repair-kb"></div>
      <div class="row" style="margin-top:10px">
        <button class="btn quiet" data-act="retreat">Retreat</button>
        <button class="btn primary" data-act="repair"><span class="label">Spend repair ◆</span></button>
      </div>`, { cls: "red tall", dismissable: false });
    const fixer = new CodeEditor($(".repair-ed", entry.sheet), { value: body.code, label: "repair source" });
    keybar($(".repair-kb", entry.sheet), fixer);
    fixer.mark(body.line, "err");
    requestAnimationFrame(() => { fixer.moveCaretToLine(body.line); fixer.focus(); });
    entry.actions.retreat = async () => { forceClose(); await retreat(); };
    entry.actions.repair = async (data, button) => {
      button.classList.add("busy");
      $(".label", button).textContent = "patching…";
      let next;
      try {
        next = await state.engine.call("boss_repair", { fight_id: fight, code: fixer.value, slept: report() });
      } catch (error) {
        button.classList.remove("busy");
        $(".label", button).textContent = "Spend repair ◆";
        failure(error);
        if (error.code === "no_repairs") { forceClose(); await end(); }
        return;
      }
      forceClose();
      await resolve(next);
    };
  }

  async function retreat() {
    say("retreating — scoring what the fight achieved");
    await end();
  }

  async function end() {
    if (over) return;
    over = true;
    clearInterval(tick);
    say("measuring every step against your final source…");
    try {
      const result = await state.engine.call("boss_finish", { fight_id: fight, slept: report() });
      go("bossEnd", { result, meta }, { replace: true });
    } catch (error) {
      failure(error);
      go("home", {}, { replace: true });
    }
  }

  screen.actions.skip = () => { skip = true; };
  screen.actions.speed = () => {
    const speeds = [0.5, 1, 2, 4];
    state.settings.speed = speeds[(speeds.indexOf(state.settings.speed) + 1) % speeds.length];
    saveSettings();
    $(".speed-label").textContent = `${state.settings.speed}x`;
  };
};

SCREENS.bossEnd = ({ result, meta }, screen) => {
  const s = result.score;
  const endings = {
    down: ["BOSS DOWN", "good", "flawless — nothing spent"],
    survives: ["BOSS SURVIVES", "warn", `every step cleared, ${result.fight.spent} repair${result.fight.spent === 1 ? "" : "s"} spent — it limps away on ${result.fight.remaining} HP`],
    stopped: ["FIGHT OVER", "bad", `${result.fight.cleared}/${result.steps.length} steps cleared`],
  };
  const [title, tone, note] = endings[result.ending];
  mount(app, html`<section class="screen">
    <header class="bar">
      <button class="icon-btn" data-act="home" aria-label="campaign">▦</button>
      <div class="title">${meta.title}<small>fight score</small></div>
    </header>
    <div class="scroll">
      <pre class="boss-art ${result.ending === "down" ? "hit" : ""}" aria-hidden="true" style="${result.ending === "down" ? "color:var(--faint);text-shadow:none" : ""}">${bossArt(meta.id)}</pre>
      <div class="banner ${tone} glitch" data-text="${title}">${title}</div>
      <p class="center small muted">${note}</p>
      <div class="score-head"><div class="big-total">0.0</div>
        <div class="score-stars">${[0, 1, 2].map((i) => html`<span class="${i < s.stars ? "on" : "off"}" style="animation-delay:${0.9 + i * 0.18}s">${i < s.stars ? "★" : "☆"}</span>`)}</div></div>
      <div class="row" style="gap:6px;margin-top:10px">${Object.keys(s.bonuses).map((name) => html`<span class="sticker acid">+${Math.round(s.bonuses[name] * 100)}% ${BONUS_NAMES[name] || name}</span>`)}</div>
      <div class="panel"><span class="tag">three axes // boss weights</span>
        ${gauge("accuracy", s.accuracy, result.weights.accuracy, `${result.steps.reduce((a, x) => a + x.passed, 0)}/${result.steps.reduce((a, x) => a + x.total, 0)} cases across every step`)}
        ${gauge("speed", s.speed, result.weights.speed, s.speed ? `${mmss(result.elapsed)} vs ${mmss(result.par)} par · ${mmss(result.animation)} of replay taken off` : "only scored when every step clears", "pink")}
        ${gauge("functional", s.functional, result.weights.functional, `${result.steps.reduce((a, x) => a + x.ops, 0).toLocaleString()} ops vs ${result.steps.reduce((a, x) => a + x.ref_ops, 0).toLocaleString()} reference`, "cyan")}
      </div>
      <div class="panel cyan"><span class="tag">steps</span>
        ${result.steps.map((step, i) => html`<div class="mastery-row"><span>${i + 1}. ${step.title}</span>${meter(step.passed, step.total)}<span class="nums">${step.passed}/${step.total}</span></div>`)}
      </div>
      <p class="small faint">Boss fights are scored, but not saved to your record yet.</p>
    </div>
    <div class="actions">
      <button class="btn danger" data-act="rematch">Rematch</button>
      <button class="btn primary run" data-act="home">Campaign</button>
    </div>
  </section>`);
  countUp($(".big-total"), s.total);
  if (!calm()) animateBars();
  screen.actions.rematch = () => go("boss", { id: meta.id }, { replace: true });
};

// ---------------------------------------------------------------- stats

SCREENS.stats = async (params, screen) => {
  let player;
  try { player = await state.engine.call("player"); } catch (error) { failure(error); return; }
  if (state.current !== screen) return;
  mount(app, html`<section class="screen">
    <div class="scroll">
      <h1 class="brief-title glitch" data-text="STATS">STATS</h1>
      <div class="hud">
        <div class="stat"><span>score</span><b>${player.total_score.toFixed(1)}</b></div>
        <div class="stat pink"><span>streak</span><b>${player.streak}</b></div>
        <div class="stat yellow"><span>stars</span><b>${player.stars}/${player.max_stars}</b></div>
      </div>
      <div class="panel"><span class="tag">campaign</span>
        <div class="mastery-row"><span>cleared</span>${meter(player.cleared, player.levels)}<span class="nums">${player.cleared}/${player.levels}</span></div>
        <div class="mastery-row"><span>stars</span>${meter(player.stars, player.max_stars)}<span class="nums">${player.stars}</span></div>
        <p class="small faint" style="margin-top:6px">Your score is the sum of your best run on each level, times its world's multiplier. Replaying never lowers it.</p>
      </div>
      <div class="panel cyan"><span class="tag">mastery // measured</span>
        ${player.mastery.length
          ? player.mastery.map((m) => html`<div class="mastery-row"><span>${m.tag}</span>${meter(m.value, 1)}<span class="nums ${m.confident ? "acid" : "faint"}">${Math.round(m.value * 100)}</span></div>`)
          : html`<p class="empty-state">Nothing measured yet. Mastery moves when you bank a level, by tag, weakest first.</p>`}
        ${player.mastery.length ? html`<p class="small faint" style="margin-top:6px">Bright numbers are confident (enough runs); dim ones are still settling. Old results fade.</p>` : ""}
      </div>
    </div>
    ${navBar("stats")}
  </section>`);
};

// ------------------------------------------------------------- settings

SCREENS.settings = (params, screen) => {
  const s = state.settings;
  const seg = (key, options) => html`<span class="seg">${options.map(([value, label]) => html`<button data-act="set" data-key="${key}" data-value="${value}" aria-pressed="${String(s[key]) === String(value)}">${label}</button>`)}</span>`;
  mount(app, html`<section class="screen">
    <div class="scroll">
      <h1 class="brief-title glitch" data-text="SETUP">SETUP</h1>
      <div class="panel"><span class="tag">display</span>
        <div class="setting"><div>CRT scanlines<small>the flicker and the lines</small></div>${seg("crt", [[true, "on"], [false, "off"]])}</div>
        <div class="setting"><div>Motion<small>auto follows your system setting</small></div>${seg("motion", [["auto", "auto"], ["on", "on"], ["off", "off"]])}</div>
        <div class="setting"><div>Code size</div>${seg("size", [["s", "S"], ["m", "M"], ["l", "L"]])}</div>
        <div class="setting"><div>Haptics<small>buzz on pass, fail and hits</small></div>${seg("haptics", [[true, "on"], [false, "off"]])}</div>
      </div>
      <div class="panel cyan"><span class="tag">privacy</span>
        <p class="small">The game, the Python interpreter and your code all run on this device.
        No accounts, no analytics, and nothing you write is ever sent anywhere. Progress is
        stored locally, in this app's own storage.</p>
      </div>
      <div class="panel"><span class="tag">about</span>
        <dl class="kv">
          <dt>engine</dt><dd>vibecoder ${state.hello.engine || "?"}</dd>
          <dt>python</dt><dd>${state.hello.python || "?"} (pyodide ${state.info.pyodide || "?"})</dd>
          <dt>build</dt><dd>${state.info.build || "dev"} · ${state.info.commit || ""}</dd>
          <dt>sandbox</dt><dd>fresh interpreter per run; isolation, not security</dd>
        </dl>
        <p class="small faint" style="margin-top:8px">VibeCoder is EPL-2.0. Pyodide is MPL-2.0.
        JetBrains Mono and VT323 are OFL-1.1.</p>
        <div class="row">
          <button class="btn quiet" data-act="license" data-file="VibeCoder-EPL-2.0.txt">EPL</button>
          <button class="btn quiet" data-act="license" data-file="Pyodide-MPL-2.0.txt">MPL</button>
          <button class="btn quiet" data-act="license" data-file="JetBrainsMono-OFL.txt">OFL</button>
        </div>
      </div>
      <div class="panel red"><span class="tag">danger zone</span>
        <p class="small">Wipe every score, streak, daily and saved run on this device.</p>
        <button class="btn danger" data-act="reset">Reset progress</button>
      </div>
    </div>
    ${navBar("settings")}
  </section>`);

  screen.actions.set = (data) => {
    const raw_ = data.value;
    state.settings[data.key] = raw_ === "true" ? true : raw_ === "false" ? false : raw_;
    saveSettings();
    render();
  };
  screen.actions.license = async (data) => {
    const text = await (await fetch(`licenses/${data.file}`)).text();
    openSheet(html`<pre class="out" style="max-height:70dvh">${text}</pre>`, { cls: "tall" });
  };
  screen.actions.reset = async () => {
    const sure = await ask({ title: "Wipe it all?", body: "Every score, streak and saved run on this device is deleted. This cannot be undone.", ok: "Wipe", danger: true });
    if (!sure) return;
    try {
      const done = await state.engine.call("reset");
      state.drafts.clear();
      toast(`progress wiped · ${done.runs_removed} saved runs deleted`);
      state.stack = [];
      go("home");
    } catch (error) { failure(error); }
  };
};

// ---------------------------------------------------------------- start

window.addEventListener("resize", () => {
  fitBars(document, true);
  const logoEl = $(".logo-wrap");
  if (logoEl && state.current && (state.current.name === "home")) mount(logoEl, logo(app.clientWidth));
});

if ("serviceWorker" in navigator && location.protocol === "https:" && !navigator.userAgent.includes("VibeCoderApp")) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

boot();
