// ── Вкладка «🖥 Серверы»: локальные серверы Minecraft с консолью ─────────────
const SRV = {list: [], javas: [], javaJob: null, sel: null, seq: 0, tList: null, tLog: null, versions: {}, cores: [],
             games: [], newGame: "minecraft"};
const SRV_STATUS = {
  offline: ["⚫", "выключен"], starting: ["🟡", "запускается…"], online: ["🟢", "работает"],
  stopping: ["🟠", "останавливается…"], creating: ["⏬", "скачивается…"], error: ["🔴", "ошибка"],
  external: ["🟣", "работает (запущен раньше)"], installing: ["⚙", "устанавливается…"],
};

function srvStart() {
  srvRefresh();
  clearInterval(SRV.tList); SRV.tList = setInterval(srvRefresh, 1500);
  clearInterval(SRV.tLog); SRV.tLog = setInterval(srvPollLog, 700);
}
function srvStop() { clearInterval(SRV.tList); clearInterval(SRV.tLog); }

async function srvRefresh() {
  try {
    const d = await (await fetch("/api/servers", {cache: "no-store"})).json();
    SRV.list = d.servers || []; SRV.javas = d.javas || []; SRV.javaJob = d.java_job;
    if (d.cores) SRV.cores = d.cores;
    if (d.games) SRV.games = d.games;
  } catch (e) { return; }
  if (SRV.sel && !SRV.list.some(s => s.id === SRV.sel)) srvSelect(null);
  if (!SRV.sel && SRV.list.length) srvSelect(SRV.list[0].id);
  srvRenderJava(); srvRenderList(); srvRenderHead();
}

function srvNeedJava() {
  const need = SRV.list.map(s => Math.max(s.java_min || 0, s.need_java || 0));
  return need.length ? Math.max(...need) : 0;
}

function srvRenderJava() {
  const el = document.getElementById("srvJava");
  if (!el) return;
  const j = SRV.javaJob;
  if (j && (j.state === "downloading" || j.state === "extracting")) {
    el.innerHTML = `☕ ${j.state === "extracting" ? "Распаковываю" : "Скачиваю"} Java ${j.feature}…
      <span class="srv-bar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></span> ${Math.round((j.progress || 0) * 100)}%`;
    return;
  }
  const need = srvNeedJava();
  const best = SRV.javas.length ? SRV.javas[0].version : 0;
  const have = SRV.javas.map(x => `${x.version}${x.bundled ? " (своя)" : ""}`).join(", ");
  let html = have ? `☕ Java: ${esc(have)}` : "☕ Java не найдена";
  if (need && best < need) {
    html += ` — серверу нужна Java ${need}. <button class="small primary" onclick="srvJavaDl(${need})">⬇ Скачать Java ${need}</button>
      <span class="hint">≈50 МБ, в папку программы, ничего не устанавливается в систему</span>`;
  }
  if (j && j.state === "error") html += ` <span style="color:var(--red)">✗ ${esc(j.error)}</span>`;
  el.innerHTML = html;
}

function srvRenderList() {
  const box = document.getElementById("srvList");
  if (!box) return;
  if (!SRV.list.length) {
    box.innerHTML = `<div class="srv-empty">Серверов пока нет.<br>Нажми «+ Новый сервер» — программа сама скачает Paper,
      настроит RCON и подключит подарки.</div>`;
    return;
  }
  box.innerHTML = SRV.list.map(s => {
    const [dot, word] = SRV_STATUS[s.status] || ["⚫", s.status];
    const busy = ["online", "starting", "stopping", "external", "installing"].includes(s.status);
    const players = s.players && s.players.length ? ` · игроки: ${esc(s.players.join(", "))}` : "";
    let btns = "";
    if (s.status === "creating") {
      btns = `<span class="srv-bar"><i style="width:${Math.round((s.progress || 0) * 100)}%"></i></span>`;
    } else {
      if (s.need_java && !SRV.javas.some(j => j.version >= s.need_java))
        btns += `<button class="small primary" onclick="event.stopPropagation(); srvJavaDl(${s.need_java})">⬇ Java ${s.need_java}</button>`;
      if (s.status === "offline" || s.status === "error")
        btns += s.status === "error" ? "" : `<button class="small green" onclick="event.stopPropagation(); srvAction('${s.id}','start')">▶ Запустить</button>`;
      if (busy && s.status !== "stopping")
        btns += `<button class="small danger" onclick="event.stopPropagation(); srvAction('${s.id}','stop')">⏹ Остановить</button>`;
      if (s.gift_ok) btns += s.connected
        ? `<span class="srv-linked">✓ подарки идут сюда</span>`
        : `<button class="small" onclick="event.stopPropagation(); srvAction('${s.id}','connect')">🔌 Подарки сюда</button>`;
      if (s.game && s.game !== "minecraft" && !busy)
        btns += `<button class="small" onclick="event.stopPropagation(); srvAction('${s.id}','update')" title="Скачать обновление сервера через SteamCMD">⬆ Обновить</button>`;
      btns += `<button class="small" onclick="event.stopPropagation(); srvAction('${s.id}','open_folder')" title="Открыть папку сервера">📂</button>`;
      if (s.kind === "mods" || s.kind === "hybrid")
        btns += `<button class="small" onclick="event.stopPropagation(); srvAction('${s.id}','open_folder','mods')" title="Папка модов">📂 mods</button>`;
      if (s.kind === "plugins" || s.kind === "hybrid")
        btns += `<button class="small" onclick="event.stopPropagation(); srvAction('${s.id}','open_folder','plugins')" title="Папка плагинов">📂 plugins</button>`;
      if (!busy) btns += `<button class="small danger" onclick="event.stopPropagation(); srvDelete('${s.id}')" title="Удалить сервер">🗑</button>`;
    }
    return `<div class="srv-card${s.id === SRV.sel ? " sel" : ""}" onclick="srvSelect('${s.id}')">
      <div class="srv-name">${dot} <img class="srv-gico" src="/media/games/${esc(s.game || "minecraft")}.png" alt=""
        onerror="this.remove()">${esc(s.name)} <span class="srv-st">${word}</span></div>
      <div class="srv-meta"><span class="srv-core k-${esc(s.kind || "plugins")}">${esc(s.core_name || "Paper")}</span>
        ${s.game && s.game !== "minecraft" ? `localhost:${s.port} · нужно ${esc(s.ram_hint)} ОЗУ`
          : `${esc(s.version)}${s.loader ? " · " + esc(s.loader) : ""} · localhost:${s.port} · до ${s.ram} ГБ`}${players}</div>
      ${s.error ? `<div class="srv-err">✗ ${esc(s.error)}</div>` : ""}
      <div class="srv-btns">${btns}</div>
    </div>`;
  }).join("");
}

function srvRenderHead() {
  const h = document.getElementById("srvConHead");
  const s = SRV.list.find(x => x.id === SRV.sel);
  if (!h) return;
  h.innerHTML = s ? `Консоль: <b>${esc(s.name)}</b> <span class="hint">· зайти в игре: <code>localhost:${s.port}</code></span>`
                  : "Выбери сервер слева";
  const q = document.getElementById("srvQuick");
  const nick = String((DATA.config || {}).minecraft_nick || "").trim();
  const cmds = [["list", "👥 кто онлайн"], ["time set day", "☀ день"], ["weather clear", "🌤 ясно"], ["save-all", "💾 сохранить"]];
  if (nick) cmds.push([`op ${nick}`, `👑 op ${nick}`], [`gamemode creative ${nick}`, "🎨 творческий"],
                      [`gamemode survival ${nick}`, "⛏ выживание"]);
  const inp = document.getElementById("srvCmd");
  if (inp) {
    const noCon = s && s.has_console === false;
    inp.disabled = !!noCon;
    inp.placeholder = noCon ? "у этой игры нет консоли команд — тут только лог сервера"
                            : "команда сервера — Enter отправит";
  }
  if (s && s.game && s.game !== "minecraft") {
    const G = {rust: [["say Привет из программы", "💬 say"], ["status", "👥 status"], ["server.save", "💾 сохранить"],
                      ["env.time 12", "☀ день"]],
               palworld: [["ShowPlayers", "👥 игроки"], ["Save", "💾 сохранить"], ["Info", "ℹ инфо"]],
               ark: [["ListPlayers", "👥 игроки"], ["SaveWorld", "💾 сохранить"], ["SetTimeOfDay 12:00", "☀ день"]],
               "7dtd": [["lp", "👥 игроки"], ["saveworld", "💾 сохранить"], ['say "Привет из программы"', "💬 say"]],
               zomboid: [["players", "👥 игроки"], ["save", "💾 сохранить"], ['servermsg "Привет из программы"', "💬 сообщение"]]};
    if (q) q.innerHTML = (G[s.game] || []).map(([c, n]) =>
      `<span class="srv-chip" onclick="srvSend(${JSON.stringify(c).replace(/"/g, "&quot;")})">${esc(n)}</span>`).join("");
    return;
  }
  if (q) q.innerHTML = s ? cmds.map(([c, n]) => `<span class="srv-chip" onclick="srvSend(${JSON.stringify(c).replace(/"/g, "&quot;")})">${esc(n)}</span>`).join("") : "";
}

function srvSelect(id) {
  SRV.sel = id; SRV.seq = 0;
  const log = document.getElementById("srvLog");
  if (log) log.innerHTML = "";
  srvRenderList(); srvRenderHead(); srvPollLog();
}

function srvLineClass(t) {
  if (t.startsWith(">")) return "c-cmd";
  if (/ERROR|Exception|✗/.test(t)) return "c-err";
  if (/WARN|⚠/.test(t)) return "c-warn";
  if (/joined the game|Done \(|✓/.test(t)) return "c-ok";
  if (t.startsWith("──")) return "c-sys";
  return "";
}

async function srvPollLog() {
  if (!SRV.sel) return;
  const id = SRV.sel;
  let d;
  try { d = await (await fetch(`/api/servers/${encodeURIComponent(id)}/log?since=${SRV.seq}`, {cache: "no-store"})).json(); }
  catch (e) { return; }
  if (!d.ok || id !== SRV.sel) return;
  const log = document.getElementById("srvLog");
  if (!log || !d.lines.length) return;
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const frag = document.createDocumentFragment();
  for (const [n, t] of d.lines) {
    const div = document.createElement("div");
    div.className = srvLineClass(t);
    div.textContent = t;
    frag.appendChild(div);
    SRV.seq = Math.max(SRV.seq, n);
  }
  log.appendChild(frag);
  while (log.childNodes.length > 1500) log.removeChild(log.firstChild);
  if (atBottom) log.scrollTop = log.scrollHeight;
}

async function srvSend(cmd) {
  const input = document.getElementById("srvCmd");
  const text = (cmd !== undefined ? cmd : (input ? input.value : "")).trim();
  if (!text || !SRV.sel) return;
  if (cmd === undefined && input) input.value = "";
  const d = await (await fetch(`/api/servers/${encodeURIComponent(SRV.sel)}/command`, {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify({cmd: text})})).json();
  if (!d.ok) srvLocalLine("✗ " + d.error);
  srvPollLog();
}

function srvLocalLine(t) {
  const log = document.getElementById("srvLog");
  if (!log) return;
  const div = document.createElement("div");
  div.className = srvLineClass(t); div.textContent = t;
  log.appendChild(div); log.scrollTop = log.scrollHeight;
}

async function srvAction(id, action, sub) {
  const q = sub ? `?sub=${encodeURIComponent(sub)}` : "";
  const d = await (await fetch(`/api/servers/${encodeURIComponent(id)}/${action}${q}`, {method: "POST",
    headers: {"Content-Type": "application/json"}, body: "{}"})).json();
  if (!d.ok) {
    if (id === SRV.sel) srvLocalLine("✗ " + d.error);
    else alert(d.error);
  }
  if (action === "connect" && d.ok) {
    try { DATA.config = (await (await fetch("/api/state", {cache: "no-store"})).json()).config || DATA.config; } catch (e) {}
  }
  srvRefresh();
}

async function srvDelete(id) {
  const s = SRV.list.find(x => x.id === id);
  if (!s || !confirm(`Удалить сервер «${s.name}» вместе с миром? Это нельзя отменить.`)) return;
  srvAction(id, "delete");
}

async function srvJavaDl(feature) {
  const d = await (await fetch("/api/servers/java", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({feature})})).json();
  if (!d.ok) alert(d.error);
  srvRefresh();
}

// ── Окно «Новый сервер» ──
const SRV_KINDS = [["plugins", "Плагины"], ["plain", "Без плагинов и модов"], ["mods", "Моды"],
                   ["hybrid", "Гибриды: моды + плагины"]];

function srvRenderGames() {
  const box = document.getElementById("srvGames");
  if (!box) return;
  const all = [{id: "minecraft", name: "Minecraft"}].concat(SRV.games);
  box.innerHTML = all.map(g => `<div class="srv-game${g.id === SRV.newGame ? " active" : ""}" onclick="srvPickGame('${g.id}')">
    <img src="/media/games/${g.id}.png" alt="" onerror="this.remove()">${esc(g.name)}</div>`).join("");
  document.querySelector("#srvModal .mdl-box").dataset.game = SRV.newGame;
}

function srvPickGame(id) {
  SRV.newGame = id;
  srvRenderGames();
  const used = new Set(SRV.list.flatMap(s => [s.port, s.rcon_port, s.rest_port || 0]));
  const g = SRV.games.find(x => x.id === id);
  let port = g ? g.port : 25565; while (used.has(port)) port += (g ? 10 : 1);
  document.getElementById("srvPort").value = port;
  if (g) {
    document.getElementById("srvPlayers").value = g.players;
    document.getElementById("srvSteamInfo").innerHTML = `⚠ Скачается ${esc(g.disk)} через SteamCMD — первый раз 10–40 минут.
      Серверу нужно <b>${esc(g.ram)} оперативной памяти</b> — вместе с игрой и OBS ноутбук может не потянуть.
      ${g.gifts ? "Подарки на этот сервер подключаются кнопкой «🔌 Подарки сюда»." :
        "Подарки через сервер в этой игре не работают — для них вкладка «⌨ Любая игра»."}`;
  }
  document.getElementById("srvCreateHint").textContent = "";
}

async function srvOpenCreate() {
  document.getElementById("srvModal").classList.remove("hidden");
  SRV.newGame = "minecraft";
  srvRenderGames();
  document.getElementById("srvCreateHint").textContent = "";
  const used = new Set(SRV.list.flatMap(s => [s.port, s.rcon_port]));
  let port = 25565; while (used.has(port)) port++;
  document.getElementById("srvPort").value = port;
  const cs = document.getElementById("srvCore");
  if (!cs.options.length) {
    const cores = SRV.cores.length ? SRV.cores : [{id: "paper", name: "Paper", kind: "plugins", desc: ""}];
    cs.innerHTML = SRV_KINDS.map(([k, title]) => {
      const list = cores.filter(c => c.kind === k);
      return list.length ? `<optgroup label="${esc(title)}">${list.map(c =>
        `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("")}</optgroup>` : "";
    }).join("");
    cs.value = "paper";
  }
  srvCoreChanged();
}

async function srvCoreChanged() {
  const core = document.getElementById("srvCore").value;
  const info = SRV.cores.find(c => c.id === core) || {};
  const sel = document.getElementById("srvVersion");
  const hint = document.getElementById("srvCreateHint");
  document.getElementById("srvCoreDesc").textContent = info.desc || "";
  document.getElementById("srvHybridWarn").classList.toggle("hidden", info.kind !== "hybrid");
  hint.textContent = "";
  if (!SRV.versions[core]) {
    sel.innerHTML = "<option>загружаю версии…</option>";
    try {
      const d = await (await fetch(`/api/servers/versions?core=${encodeURIComponent(core)}`, {cache: "no-store"})).json();
      if (!d.ok) { sel.innerHTML = ""; hint.textContent = "✗ " + d.error; return; }
      SRV.versions[core] = d.versions || [];
    } catch (e) { hint.textContent = "✗ " + e.message; return; }
  }
  if (document.getElementById("srvCore").value !== core) return;     // пока грузилось, выбрали другое ядро
  const vers = SRV.versions[core];
  sel.innerHTML = vers.length
    ? vers.map((v, i) => `<option value="${esc(v.id)}">${esc(v.label)}${i === 0 ? " — новейшая" : ""}</option>`).join("")
    : "<option value=''>нет версий</option>";
}

function srvCloseCreate() { document.getElementById("srvModal").classList.add("hidden"); }

async function srvCreate() {
  const val = id => document.getElementById(id).value;
  const hint = document.getElementById("srvCreateHint");
  if (SRV.newGame !== "minecraft") {
    const body = {game: SRV.newGame, name: val("srvName").trim() || (SRV.games.find(g => g.id === SRV.newGame) || {}).name,
                  port: parseInt(val("srvPort")), players: parseInt(val("srvPlayers")) || 10,
                  worldsize: parseInt(val("srvWorldSize")) || 2000, seed: parseInt(val("srvRustSeed")) || 0,
                  world: val("srvWorld").trim(), password: val("srvVhPass").trim()};
    const d = await (await fetch("/api/servers/create", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)})).json();
    if (!d.ok) { hint.textContent = "✗ " + d.error; return; }
    srvCloseCreate();
    SRV.sel = d.id; SRV.seq = 0;
    const log = document.getElementById("srvLog"); if (log) log.innerHTML = "";
    srvRefresh();
    return;
  }
  if (!document.getElementById("srvEula").checked) { hint.textContent = "✗ Нужно принять EULA Minecraft"; return; }
  if (!val("srvVersion")) { hint.textContent = "✗ Выбери версию"; return; }
  const body = {name: val("srvName").trim() || "Мой сервер", core: val("srvCore"), version: val("srvVersion"),
                port: parseInt(val("srvPort")) || 25565,
                ram: parseInt(val("srvRam")) || 3, online_mode: !document.getElementById("srvCracked").checked,
                gamemode: val("srvMode"), difficulty: val("srvDiff"), seed: val("srvSeed").trim(), eula: true};
  const d = await (await fetch("/api/servers/create", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)})).json();
  if (!d.ok) { hint.textContent = "✗ " + d.error; return; }
  srvCloseCreate();
  SRV.sel = d.id; SRV.seq = 0;
  const log = document.getElementById("srvLog"); if (log) log.innerHTML = "";
  srvRefresh();
}
