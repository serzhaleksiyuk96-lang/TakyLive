// ============================================================
//  TakyLive — логика редактора
// ============================================================

let DATA = { config: {}, profiles: {}, connected: false };
let activeProfile = null;
let activeSection = "gifts";
let FILTER = "all";                     // фильтр списка событий: all | тип
const EXPANDED = new WeakSet();         // какие карточки развёрнуты (не сохраняется)
const SEC_ORDER = ["gifts","likes","subs","follows","welcome","chatcmds","goals","panel"];
const TYPE_META = {
  gifts:    {e:"🎁", n:"Подарок",       d:"выбор из библиотеки",       chip:"🎁 Подарки"},
  likes:    {e:"❤",  n:"Лайки",         d:"каждые N лайков",           chip:"❤ Лайки"},
  subs:     {e:"⭐", n:"Подписка",      d:"платная подписка",           chip:"⭐ Подписки"},
  follows:  {e:"➕", n:"Фоллов",        d:"подписался на профиль",     chip:"➕ Фолловы"},
  welcome:  {e:"👋", n:"Приветствие",   d:"по нику зрителя",           chip:"👋 Приветствия"},
  chatcmds: {e:"💬", n:"Чат-команда",   d:"!моб, !тнт в чате",         chip:"💬 Чат"},
  goals:    {e:"🎯", n:"Цель",          d:"прогресс стрима",           chip:"🎯 Цели"},
  panel:    {e:"🎛", n:"Кнопка панели", d:"жмёшь сам во время стрима", chip:"🎛 Панель"},
};
const GOAL_UNITS = {likes:"лайков", coins:"монет", follows:"фолловеров", subs:"подписок", gifts:"подарков"};
// Обработчики в карточке сначала переключают «текущий тип» на тип своей карточки
function S(sec) { activeSection = sec; }   // gifts | likes | subs | follows | welcome
let MEDIA_FILES = [];          // список загруженных медиафайлов

// ── Медиафайлы ───────────────────────────────────────────────
async function loadMediaList() {
  try {
    const r = await fetch("/api/media_list");
    const d = await r.json();
    MEDIA_FILES = d.files || [];
  } catch(e) { MEDIA_FILES = []; }
}

function updMedia(idx, key, val, section) {
  const a = curList()[idx];
  a[key] = val;
  if (key === "media_file") {
    const f = MEDIA_FILES.find(x => x.name === val);
    a.media_kind = f ? f.kind : "video";
  }
}

function updMediaVol(idx, key, val, spanId) {
  curList()[idx][key] = parseInt(val);
  const span = document.getElementById(spanId);
  if (span) span.textContent = val;
}

async function uploadMediaFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await fetch("/api/media_upload", { method: "POST", body: fd });
    const d = await r.json();
    if (d.ok) {
      await loadMediaList();
      renderCards();
      alert(`Файл «${d.name}» загружен!`);
    } else {
      alert("Ошибка загрузки: " + (d.error || "?"));
    }
  } catch(e) { alert("Ошибка загрузки: " + e.message); }
}

// ── Загрузка состояния с сервера ─────────────────────────────
async function loadState() {
  const r = await fetch("/api/state");
  DATA = await r.json();
  activeProfile = DATA.config.active_profile;
  if (!DATA.profiles[activeProfile]) {
    activeProfile = Object.keys(DATA.profiles)[0] || null;
  }
  await loadMediaList();
  await loadGiftIcons();
  fillSettings();
  fillPanelCfg();
  renderProfiles();
  renderCards();
  renderOverlays();
  renderPanelButtons();
  markSaved();          // только что загрузили — сохранять нечего
  updateStatus();
  if (!STARTED) {
    STARTED = true; switchView("start");                     // при входе — выбор: игра и шаблон
    if (typeof updLoad === "function") { updLoad(false); setTimeout(() => updLoad(false), 9000); }
  }
}
let STARTED = false;

let liveRendered = false;
function updateStatus() {
  const dot = document.getElementById("dot");
  const txt = document.getElementById("statusText");
  const btn = document.getElementById("btnConnect");
  if (DATA.connected) {
    dot.classList.add("on");
    txt.textContent = "Подключено к @" + (DATA.config.tiktok_username || "");
    btn.textContent = "⏹ Отключиться";
    btn.classList.remove("green");
    btn.classList.add("danger");
    if (!liveRendered) { liveRendered = true; renderProfiles(); }
  } else {
    if (liveRendered) { liveRendered = false; renderProfiles(); }
    dot.classList.remove("on");
    txt.textContent = "Не подключено";
    btn.textContent = "▶ Подключиться";
    btn.classList.add("green");
    btn.classList.remove("danger");
  }
}

// ── Переключение верхних вкладок ─────────────────────────────
function switchView(view) {
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.dataset.view === view));
  ["start", "events", "settings", "log", "overlays", "panel", "servers"].forEach(v =>
    document.getElementById("view-" + v).classList.toggle("hidden", v !== view));
  if (typeof srvStart === "function") { if (view === "servers") srvStart(); else srvStop(); }
  if (view === "start") renderStart();
  if (view === "log") startLogPolling();
  else stopLogPolling();
  if (view === "panel") { fillPanelCfg(); renderPanelButtons(); pollTimer(); }
  if (view === "overlays" && !overlaysLoaded) loadOverlayPreviews();
}

// ── Профили (вкладки стримов) ────────────────────────────────
function renderProfiles() {
  const bar = document.getElementById("profileBar");
  bar.innerHTML = "";
  Object.keys(DATA.profiles).forEach(name => {
    const chip = document.createElement("div");
    const isLive = DATA.connected && name === liveProfile();
    chip.className = "profile-chip" + (name === activeProfile ? " active" : "") + (isLive ? " live" : "");
    chip.innerHTML = `<span onclick="selectProfile('${esc(name)}')">${isLive ? "🔴 " : ""}${esc(name)}</span>`;
    if (isLive) chip.title = "Эта вкладка сейчас работает в эфире";
    if (Object.keys(DATA.profiles).length > 1) {
      const x = document.createElement("span");
      x.className = "x";
      x.textContent = "×";
      x.onclick = (e) => { e.stopPropagation(); deleteProfile(name); };
      chip.appendChild(x);
    }
    bar.appendChild(chip);
  });
  renderLiveBanner();
}

function selectProfile(name) {
  activeProfile = name;
  if (!DATA.connected) DATA.config.active_profile = name;   // во время эфира — только редактирование
  renderProfiles();
  renderCards();
}

// Во время эфира события идут во «вкладку эфира», открытая вкладка — только для правок
function liveProfile() { return DATA.config.active_profile || activeProfile; }

function renderLiveBanner() {
  const el = document.getElementById("liveBanner");
  if (!el) return;
  const live = liveProfile();
  if (DATA.connected && live !== activeProfile && DATA.profiles[live]) {
    el.innerHTML = `📡 В эфире работает вкладка <b>«${esc(live)}»</b> — правки этой вкладки на стрим не влияют.
      <button class="small" onclick="makeLive()">Перевести эфир сюда</button>
      <button class="small" onclick="selectProfile(liveProfile())">Открыть эфирную</button>`;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

async function makeLive() {
  DATA.config.active_profile = activeProfile;
  try {
    await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({active_profile: activeProfile})});
  } catch (e) {}
  renderProfiles();
}

function addProfile() { openNewTab(); }   // «+ Новая вкладка» — мастер: игра → пустая или шаблон

function deleteProfile(name) {
  if (Object.keys(DATA.profiles).length <= 1) { alert("Нельзя удалить последнюю вкладку"); return; }
  if (DATA.connected && name === liveProfile()) {
    alert(`«${name}» сейчас работает в эфире. Сначала переведи эфир на другую вкладку или отключись.`);
    return;
  }
  if (!confirm(`Удалить вкладку "${name}" со всеми подарками?`)) return;
  delete DATA.profiles[name];
  if (activeProfile === name) activeProfile = Object.keys(DATA.profiles)[0];
  renderProfiles();
  renderCards();
}

function renameProfile() {
  const newName = prompt("Новое название вкладки:", activeProfile);
  if (!newName || newName === activeProfile) return;
  if (DATA.profiles[newName]) { alert("Такая вкладка уже есть"); return; }
  DATA.profiles[newName] = DATA.profiles[activeProfile];
  delete DATA.profiles[activeProfile];
  activeProfile = newName;
  renderProfiles();
  renderCards();
}

// ── Секции (подарки/лайки/подписки/фолловы) ──────────────────
function switchSection(sec) { setFilter(sec); }   // совместимость со старым кодом

function setFilter(f) { FILTER = f; renderCards(); }

function renderFilters() {
  const box = document.getElementById("evFilters");
  const p = DATA.profiles && DATA.profiles[activeProfile];
  if (!box || !p) return;
  const total = SEC_ORDER.reduce((s, k) => s + (p[k] ? p[k].length : 0), 0);
  let html = `<span class="ev-chip${FILTER === "all" ? " active" : ""}" onclick="setFilter('all')">Все<b>${total}</b></span>`;
  for (const k of SEC_ORDER) {
    const cnt = p[k] ? p[k].length : 0;
    if (!cnt && FILTER !== k) continue;
    html += `<span class="ev-chip${FILTER === k ? " active" : ""}" onclick="setFilter('${k}')">${TYPE_META[k].chip}<b>${cnt}</b></span>`;
  }
  box.innerHTML = html;
}

// ── Отрисовка карточек действий ──────────────────────────────
function curList() {
  const p = DATA.profiles[activeProfile];
  if (!p[activeSection]) p[activeSection] = [];
  return p[activeSection];
}

function renderCards() {
  const list = document.getElementById("cardsList");
  const p = DATA.profiles && DATA.profiles[activeProfile];
  if (list && !p) {
    list.innerHTML = `<div class="ev-empty">Вкладок пока нет.<br><br>
      <button class="primary" onclick="switchView('start')">🏠 Выбрать игру и шаблон</button></div>`;
    const cur = document.getElementById("gameCur"); if (cur) cur.textContent = "—";
    return;
  }
  if (!list || !p) return;
  SEC_ORDER.forEach(k => { if (!p[k]) p[k] = []; });
  renderGameBar();
  renderFilters();
  list.innerHTML = "";
  const keep = activeSection;
  let shown = 0;
  for (const sec of SEC_ORDER) {
    if (FILTER !== "all" && FILTER !== sec) continue;
    p[sec].forEach((action, idx) => {
      activeSection = sec;
      const card = buildCard(action, idx);
      card.innerHTML = card.innerHTML.replace(
        /(\s)on(click|input|change|keydown)="/g, `$1on$2="S('${sec}');`);
      list.appendChild(card);
      shown++;
    });
  }
  activeSection = keep;
  if (!shown) {
    list.innerHTML = `<div class="card" style="text-align:center; color:var(--text-mut); padding:24px">
      ${FILTER === "all" ? "Событий пока нет — нажми «+ Создать событие»." : "Таких событий пока нет."}</div>`;
  }
}

// TikTok присылает названия подарков по-английски: русское имя без ID не сработает никогда
function giftNeedsId(sec, a) {
  return sec === "gifts" && /[а-яё]/i.test(a.name || "") && !String(a.gift_id || "").trim() && !ruKnown(a.name);
}

// Сводка для свёрнутой карточки: «Роза → ×50 зомби»
function cardSummaryHtml(sec, a) {
  const mult = parseInt(a.multiplier) || 1;
  const act = String(a.title || "").trim();
  const arrow = (txt) => txt ? ` <i>→ ${esc(txt)}</i>` : "";
  const x = mult > 1 ? `×${mult} ` : "";
  switch (sec) {
    case "gifts":    return esc(a.name || "Подарок не выбран") + arrow(act ? x + act : "");
    case "likes":    return esc(`Каждые ${a.threshold || 100} лайков`) + arrow(act ? x + act : "");
    case "subs":     return "Подписка" + arrow(act ? x + act : "");
    case "follows":  return "Фоллов" + arrow(act ? x + act : "");
    case "welcome":  return esc(a.nick ? "@" + a.nick : "Приветствие") + arrow(a.caption || "");
    case "chatcmds": return esc(a.trigger || "Чат-команда") + arrow(act ? x + act : "");
    case "goals":    return esc(act || "Цель") + arrow(`${a.target || 0} ${GOAL_UNITS[a.metric] || ""}`);
    case "panel":    return esc(act || "Кнопка");
  }
  return esc(act);
}

// ── Создание события: сначала тип ──
function openTypePicker() {
  document.getElementById("typeGrid").innerHTML = SEC_ORDER.map(k => {
    const m = TYPE_META[k];
    return `<div class="type-tile" onclick="makeEvent('${k}')">
      <div class="te">${m.e}</div><div class="tn">${m.n}</div><div class="td">${m.d}</div></div>`;
  }).join("");
  document.getElementById("typeModal").classList.remove("hidden");
}

function closeTypePicker() { document.getElementById("typeModal").classList.add("hidden"); }

function makeEvent(sec) {   // не createEvent — это имя занято у document
  closeTypePicker();
  if (FILTER !== "all" && FILTER !== sec) FILTER = "all";
  activeSection = sec;
  addAction();
  const idx = curList().length - 1;
  if (sec === "gifts") openGiftLib(idx);   // для подарка сразу открываем библиотеку
  setTimeout(() => {
    const el = document.querySelector(`#cardsList .card[data-sec="${sec}"][data-idx="${idx}"]`);
    if (el && el.scrollIntoView) el.scrollIntoView({behavior: "smooth", block: "center"});
  }, 60);
}

function addLabel() {
  return { gifts: "Добавить подарок", likes: "Добавить порог лайков",
           subs: "Добавить действие подписки", follows: "Добавить действие фоллова",
           welcome: "Добавить приветствие для ника",
           chatcmds: "Добавить чат-команду", goals: "Добавить цель",
           panel: "Добавить кнопку панели" }[activeSection];
}

function buildCard(action, idx) {
  const card = document.createElement("div");
  const enabled = action.enabled !== false;  // по умолчанию включён
  const collapsed = !EXPANDED.has(action);   // по умолчанию свёрнута — видна сводка
  card.className = "card" + (enabled ? "" : " disabled") + (collapsed ? " collapsed" : "");
  card.dataset.sec = activeSection;
  card.dataset.idx = idx;

  // Заголовок (название триггера) для сводки
  const autoTitle = (activeSection === "gifts") ? (action.name || "Новый подарок")
    : (activeSection === "likes") ? `Каждые ${action.threshold||100} лайков`
    : (activeSection === "welcome") ? (action.nick ? "@"+action.nick : "Новое приветствие")
    : (activeSection === "chatcmds") ? (action.trigger || "Новая команда")
    : (activeSection === "goals") ? (action.title || `Цель: ${action.target||0}`)
    : (activeSection === "panel") ? (action.title || "Кнопка")
    : (activeSection === "subs") ? "Подписка" : "Фоллов";
  const title = action.title || autoTitle;

  // ── Шапка: тумблер, иконка, сводка «Роза → ×50 зомби», метка типа ──
  const typeIco = (activeSection === "gifts")
    ? giftIconHtml(action.name, 30)
    : `<span class="type-ico">${TYPE_META[activeSection].e}</span>`;
  let bar = `<div class="card-bar">
    <button class="toggle ${enabled?'on':''}" onclick="event.stopPropagation();toggleEnabled(${idx})" title="${enabled?'Включено':'Выключено'}">
      <span class="knob"></span>
    </button>
    <div class="card-title-wrap" onclick="toggleCollapse(${idx})">
      ${typeIco}
      <span class="card-title card-sum">${cardSummaryHtml(activeSection, action)}</span>
      ${giftNeedsId(activeSection, action) ? '<span class="warn-badge" title="Программа пока не знает это русское название">⚠ проверь название</span>' : ""}
      ${!enabled?'<span class="off-badge">выкл</span>':''}
    </div>
    <span class="t-badge t-${activeSection}">${TYPE_META[activeSection].n.toLowerCase()}</span>
    <span class="chevron" onclick="toggleCollapse(${idx})" style="cursor:pointer">${collapsed?'▾':'▴'}</span>
    <button class="icon danger" onclick="event.stopPropagation();delAction(${idx})">🗑</button>
  </div>`;

  if (giftNeedsId(activeSection, action)) {
    bar += `<div class="warn-line">⚠ Программа пока не знает подарок «${esc(action.name)}». TikTok присылает
      названия по-английски, а русские программа узнаёт у TikTok сама — при подключении к эфиру. Если после
      подключения предупреждение не пропало — значит, в TikTok этот подарок называется иначе: выбери его
      кнопкой «📚 Выбрать».</div>`;
  }
  // Тело карточки (скрывается при сворачивании)
  let body = `<div class="card-body">`;

  // Название триггера (своё имя)
  body += `<div class="title-row">
    <label>${({goals:"Название цели", panel:"Надпись на кнопке", welcome:"Название (для себя)"})[activeSection]
              || "Что произойдёт — коротко, это видно на витрине"}</label>
    <input placeholder="${({gifts:"например: зомби", likes:"например: фейерверк", subs:"например: алмазы",
              follows:"например: приветствие", chatcmds:"например: бык", goals:"например: 1000 лайков",
              panel:"например: 💥 Взрыв", welcome:"например: друг Вася"})[activeSection] || esc(autoTitle)}"
           value="${esc(action.title||'')}"
           oninput="updTitle(${idx},this.value)">
  </div>`;

  // Специфичные поля секции
  // Левая колонка (только для подарков): кто дарит
  const giftCol = (activeSection !== "gifts") ? "" : `
    <div class="col-gift">
      <div class="cg-pic">${giftIconHtml(action.name, 72)}</div>
      <input class="cg-name" placeholder="Название подарка" value="${esc(action.name||"")}"
             oninput="upd(${idx},'name',this.value)">
      <button class="small lib-pick-btn" onclick="openGiftLib(${idx})">📚 Выбрать</button>
      <div class="cg-row">
        <input class="mono" placeholder="ID" value="${esc(action.gift_id||"")}"
               oninput="upd(${idx},'gift_id',this.value)" title="ID подарка (необязательно)">
        <label class="cg-mult" title="Сколько раз выполнить за один подарок">⚡
          <input class="mono" type="number" min="1" max="100" value="${action.multiplier||1}"
                 oninput="upd(${idx},'multiplier',parseInt(this.value)||1)"></label>
      </div>
    </div>`;

  let head = `<div class="card-head"><div class="meta">`;
  if (activeSection === "gifts") {
    head += "";
  } else if (activeSection === "likes") {
    head += `
      <span style="color:var(--text-dim);font-size:13px">Каждые</span>
      <input class="gift-id" type="number" placeholder="100" value="${action.threshold||100}"
             oninput="upd(${idx},'threshold',parseInt(this.value)||1)">
      <span style="color:var(--text-dim);font-size:13px">лайков</span>`;
  } else if (activeSection === "welcome") {
    head += `
      <span style="color:var(--text-dim);font-size:13px">Ник в TikTok:</span>
      <input placeholder="ник зрителя (без @)" value="${esc(action.nick||"")}"
             oninput="upd(${idx},'nick',this.value)">`;
  } else if (activeSection === "chatcmds") {
    head += `
      <span style="color:var(--text-dim);font-size:13px">Команда:</span>
      <input class="gift-id" style="width:130px" placeholder="!моб" value="${esc(action.trigger||"")}"
             oninput="upd(${idx},'trigger',this.value)">
      <span style="color:var(--text-dim);font-size:13px">Кулдаун</span>
      <input class="gift-id" type="number" min="0" value="${action.cooldown??10}"
             oninput="upd(${idx},'cooldown',parseFloat(this.value)||0)">
      <span style="color:var(--text-dim);font-size:13px">сек</span>`;
  } else if (activeSection === "goals") {
    head += `
      <span style="color:var(--text-dim);font-size:13px">Цель:</span>
      <select style="width:auto" onchange="upd(${idx},'metric',this.value)">
        <option value="likes" ${action.metric==="likes"?"selected":""}>❤ Лайки</option>
        <option value="coins" ${action.metric==="coins"?"selected":""}>💎 Монеты (донат)</option>
        <option value="follows" ${action.metric==="follows"?"selected":""}>➕ Фолловеры</option>
        <option value="subs" ${action.metric==="subs"?"selected":""}>⭐ Подписки</option>
        <option value="gifts" ${action.metric==="gifts"?"selected":""}>🎁 Подарки (шт)</option>
      </select>
      <input class="gift-id" type="number" min="1" placeholder="1000" value="${action.target||""}"
             oninput="upd(${idx},'target',parseInt(this.value)||0)">`;
  } else if (activeSection === "panel") {
    head += `<span style="color:var(--text-dim);font-size:13px">Кнопка для вкладки «Панель» — название задаётся сверху</span>`;
  } else {
    const labels = {subs:"При подписке зрителя", follows:"При фоллове зрителя"};
    head += `<span style="color:var(--text-dim);font-size:13px">${labels[activeSection]||""}</span>`;
  }
  head += `</div></div>`;
  if (activeSection !== "gifts") body += head;

  // Для приветствия — поле надписи
  if (activeSection === "welcome") {
    body += `
      <div class="caption-row">
        <label>Надпись на экране</label>
        <input placeholder="Например: С возвращением, {user}!" value="${esc(action.caption||"")}"
               oninput="upd(${idx},'caption',this.value)">
      </div>`;
  }

  // Цепочка команд
  let chain = `<div class="chain">`;
  const cmds = action.commands || [];
  const delays = action.delays || [];
  cmds.forEach((cmd, ci) => {
    chain += `
      <div class="cmd-row">
        <div class="cmd-num">${ci+1}</div>
        <input class="cmd mono" placeholder="${cmdPlaceholder()}" value="${esc(cmd)}"
               oninput="updCmd(${idx},${ci},this.value)">
        <span class="delay-label">пауза</span>
        <input class="delay mono" type="number" step="0.1" min="0"
               value="${delays[ci]||0}" oninput="updDelay(${idx},${ci},this.value)">
        <span class="delay-label">сек</span>
        <button class="icon" onclick="delCmd(${idx},${ci})">✕</button>
      </div>`;
  });
  chain += `</div>`;
  chain += `<div class="add-row">
    <button class="add-cmd" onclick="addCmd(${idx})">+ Добавить команду</button>
    <button class="add-cmd lib" onclick="openCmdPicker(${idx})">📖 Команды игры</button>
  </div>`;
  body += chain;

  // Медиа-блок
  body += (activeSection === "likes")
    ? buildIconBlock(action, idx)          // у лайков только иконка для витрины
    : buildMediaBlock(action, idx);        // у остальных медиа + иконка внутри

  // Подвал
  let foot = `<div class="card-foot">`;
  foot += `<label class="chk"><input type="checkbox" ${action.random?"checked":""}
           onchange="upd(${idx},'random',this.checked)"> 🎲 Случайная из цепочки</label>`;
  if (activeSection === "gifts") {
    foot += `<label class="chk"><input type="checkbox" ${action.repeat_by_count?"checked":""}
             onchange="upd(${idx},'repeat_by_count',this.checked)"> ✖ Повтор по количеству</label>`;
  }
  if (activeSection !== "gifts") {
    foot += `<label class="chk">⚡ Активаций
             <input class="delay mono" type="number" min="1" max="100" style="width:58px"
             value="${action.multiplier||1}" oninput="upd(${idx},'multiplier',parseInt(this.value)||1)"></label>`;
  }
  if (["gifts","likes","subs","follows","chatcmds"].includes(activeSection)) {
    foot += `<label class="chk"><input type="checkbox" ${action.showcase !== false ? "checked" : ""}
             onchange="upd(${idx},'showcase',this.checked)"> 🎁 На витрине</label>`;
  }
  foot += `<div class="spacer"></div>`;
  foot += `<button class="small" onclick="testAction(${idx})">▶ Тест</button>`;
  foot += `</div>`;
  body += foot;

  body += `</div>`;  // конец card-body

  // Для подарков — две колонки: слева подарок, справа что он делает
  if (activeSection === "gifts") {
    body = `<div class="card-body"><div class="card-cols">${giftCol}
      <div class="col-act">${body.replace('<div class="card-body">', "").slice(0, -6)}</div>
    </div></div>`;
  }

  card.innerHTML = bar + body;
  return card;
}

// ── Управление карточками: название, сворачивание, вкл/выкл ──
function updTitle(idx, val) {
  const a = curList()[idx];
  a.title = val;
  // обновляем сводку в шапке без полной перерисовки (чтобы не терять фокус ввода)
  const el = document.querySelector(`#cardsList .card[data-sec="${activeSection}"][data-idx="${idx}"] .card-sum`);
  if (el) el.innerHTML = cardSummaryHtml(activeSection, a);
}

function toggleCollapse(idx) {
  const a = curList()[idx];
  if (EXPANDED.has(a)) EXPANDED.delete(a); else EXPANDED.add(a);
  renderCards();
}

function toggleEnabled(idx) {
  const a = curList()[idx];
  a.enabled = (a.enabled === false) ? true : false;
  renderCards();
}

// ── Медиа-блок карточки: видео/гифка/картинка + звук + громкость ──
const fmtDur = s => { s = Math.round(s || 0); return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
                                                               : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const fmtSize = b => b >= 1048576 ? (b / 1048576).toFixed(1) + " МБ" : Math.max(1, Math.round((b || 0) / 1024)) + " КБ";
const mediaUrl = n => "/media/" + encodeURI(n);

function buildMediaBlock(action, idx) {
  const mf = MEDIA_FILES.find(f => f.name === action.media_file);
  const sf = MEDIA_FILES.find(f => f.name === action.sound_file);
  const meta = (f, name) => !name ? "" : !f ? "⚠ файл не найден — выбери заново" :
    [f.duration ? fmtDur(f.duration) : (f.kind === "gif" ? "GIF" : f.kind === "image" ? "картинка" : ""),
     f.w && f.h ? `${f.w}×${f.h}` : "", fmtSize(f.size)].filter(Boolean).join(" · ");
  let prev = `<div class="ms-ph">📺</div>`;
  if (action.media_file) {
    if (mf && mf.job && mf.job.state === "processing") prev = `<div class="ms-ph">⚙</div>`;
    else if (mf && mf.kind === "video") prev = mf.thumb ? `<img src="${mediaUrl(mf.thumb)}" alt=""><i class="ms-play">▶</i>` : `<div class="ms-ph">🎬</div>`;
    else prev = `<img src="${mediaUrl(action.media_file)}" alt="">`;
  }
  const isPic = mf && ["image", "gif"].includes(mf.kind);
  const sec = activeSection;
  return `
    <div class="media-block">
      <div class="media-title">📺 Медиа на экране (оверлей)</div>
      <div class="ms-slot">
        <div class="ms-prev${action.media_file ? "" : " empty"}" onclick="openMediaPick(${idx}, 'screen')">${prev}</div>
        <div class="ms-info">
          <div class="ms-name">${action.media_file ? esc(action.media_file.split("/").pop()) : "Ничего не выбрано"}</div>
          <div class="ms-meta">${action.media_file ? esc(meta(mf, action.media_file)) : "видео, гифка или картинка поверх игры"}</div>
          ${mf && mf.job && mf.job.state === "processing" ? `<div class="ms-meta" style="color:var(--gold)">⚙ готовлю видео для OBS… ${Math.round((mf.job.progress || 0) * 100)}%</div>` : ""}
          <div class="ms-ctl">
            ${action.media_file && !isPic ? `<label>🔉 <input type="range" min="0" max="100" value="${action.media_volume ?? 100}"
                 oninput="updMediaVol(${idx},'media_volume',this.value,'mv-${sec}-${idx}')"> <span id="mv-${sec}-${idx}">${action.media_volume ?? 100}</span>%</label>` : ""}
            ${isPic ? `<label>⏱ показывать <input type="number" min="1" max="600" value="${action.media_seconds || 5}" class="ms-sec"
                 onchange="upd(${idx},'media_seconds',Math.max(1, parseFloat(this.value) || 5))"> сек</label>` : ""}
          </div>
        </div>
        <div class="ms-btns">
          <button class="small primary" onclick="openMediaPick(${idx}, 'screen')">🎬 Выбрать</button>
          ${action.media_file ? `<button class="small" onclick="updMedia(${idx},'media_file','','${sec}');renderCards()" title="Убрать">✕</button>` : ""}
        </div>
      </div>
      <div class="media-title" style="margin-top:12px">🔊 Звук</div>
      <div class="ms-slot snd">
        <div class="ms-prev snd${action.sound_file ? "" : " empty"}" onclick="openMediaPick(${idx}, 'sound')"><div class="ms-ph">${action.sound_file ? "🎵" : "🔇"}</div></div>
        <div class="ms-info">
          <div class="ms-name">${action.sound_file ? esc(action.sound_file.split("/").pop()) : "Без звука"}</div>
          <div class="ms-meta">${action.sound_file ? esc(meta(sf, action.sound_file)) : "mp3, wav, ogg — играет вместе с медиа"}</div>
          ${action.sound_file ? `<div class="ms-ctl"><label>🔉 <input type="range" min="0" max="100" value="${action.sound_volume ?? 100}"
               oninput="updMediaVol(${idx},'sound_volume',this.value,'sv-${sec}-${idx}')"> <span id="sv-${sec}-${idx}">${action.sound_volume ?? 100}</span>%</label></div>` : ""}
        </div>
        <div class="ms-btns">
          ${action.sound_file ? `<button class="small" onclick="msListen(${JSON.stringify(action.sound_file).replace(/"/g, "&quot;")}, this)" title="Послушать">▶</button>` : ""}
          <button class="small primary" onclick="openMediaPick(${idx}, 'sound')">🎵 Выбрать</button>
          ${action.sound_file ? `<button class="small" onclick="upd(${idx},'sound_file','');renderCards()" title="Убрать">✕</button>` : ""}
        </div>
      </div>
    </div>` + buildIconBlock(action, idx);
}

let MS_AUDIO = null;
function msListen(name, btn) {
  if (MS_AUDIO) { MS_AUDIO.pause(); MS_AUDIO = null; btn.textContent = "▶"; return; }
  MS_AUDIO = new Audio(mediaUrl(name)); MS_AUDIO.play().catch(() => {}); btn.textContent = "■";
  MS_AUDIO.onended = () => { btn.textContent = "▶"; MS_AUDIO = null; };
}

function buildIconBlock(action, idx) {
  if (!["gifts","likes","subs","follows","chatcmds"].includes(activeSection)) return "";
  const cur = action.icon_file || "";
  const preview = cur
    ? `<img src="/media/${encodeURI(cur)}" style="width:48px;height:48px;object-fit:contain;border-radius:8px;background:rgba(255,255,255,0.06)">`
    : `<div class="gl-ph" style="width:48px;height:48px;font-size:17px">${esc((action.name||"?").charAt(0).toUpperCase())}</div>`;
  const label = !cur ? "авто — картинка алерта или иконка подарка"
    : cur.startsWith("vault/") ? "ccLeaf: " + cur.split("/").pop().replace(/\.[^.]+$/, "").replace(/_/g, " ")
    : cur;
  return `
    <div class="media-block" style="border-color:rgba(251,191,36,0.3)">
      <div class="media-title" style="color:var(--gold)">🎁 Иконка для витрины подарков</div>
      <div style="display:flex;align-items:center;gap:12px">
        ${preview}
        <div style="flex:1;min-width:0"><div class="ic-name">${esc(label)}</div>
          <div class="hint">Её увидят зрители в оверлее «Витрина подарков»</div></div>
        <button class="small primary" onclick="openIconPick(${idx})">🖼 Выбрать картинку</button>
        <button class="small" onclick="document.getElementById('mediaUpload').click()">⬆ Загрузить</button>
      </div>
    </div>`;
}

// ── Редактирование данных ────────────────────────────────────
function upd(idx, key, val) { curList()[idx][key] = val; }
function updCmd(idx, ci, val) { curList()[idx].commands[ci] = val; }
function updDelay(idx, ci, val) {
  const a = curList()[idx];
  if (!a.delays) a.delays = [];
  a.delays[ci] = parseFloat(val) || 0;
}

function addAction() {
  const a = { commands: [""], delays: [0], random: false, enabled: true, multiplier: 1,
              title: "", showcase: true,
              media_file: "", media_kind: "video", sound_file: "",
              media_volume: 100, sound_volume: 100 };
  if (activeSection === "gifts") { a.name = ""; a.gift_id = ""; a.repeat_by_count = false; }
  if (activeSection === "likes") a.threshold = 100;
  if (activeSection === "welcome") { a.nick = ""; a.caption = ""; }
  if (activeSection === "chatcmds") { a.trigger = ""; a.cooldown = 10; }
  if (activeSection === "goals") { a.metric = "likes"; a.target = 1000; }
  curList().push(a);
  EXPANDED.add(a);
  renderCards();
}

function delAction(idx) {
  if (!confirm("Удалить это действие?")) return;
  curList().splice(idx, 1);
  renderCards();
}

function addCmd(idx) {
  const a = curList()[idx];
  if (!a.commands) a.commands = [];
  if (!a.delays) a.delays = [];
  a.commands.push("");
  a.delays.push(0);
  renderCards();
}

function delCmd(idx, ci) {
  const a = curList()[idx];
  a.commands.splice(ci, 1);
  if (a.delays) a.delays.splice(ci, 1);
  renderCards();
}

// ── Сохранение ───────────────────────────────────────────────
async function saveAll() {
  if (!DATA.connected) DATA.config.active_profile = activeProfile;
  await fetch("/api/profiles", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ profiles: DATA.profiles })
  });
  await fetch("/api/config", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify(DATA.config)
  });
  markSaved();
  const hint = document.getElementById("saveHint");
  if (hint) { hint.textContent = "✓ Сохранено"; hint.classList.remove("pending"); }
}

// ── Игра вкладки: куда идут команды ──────────────────────────
const GAMES = [
  {id: "minecraft", e: "⛏", t: "Minecraft"},
  {id: "gta5",      e: "🚗", t: "GTA 5"},
  {id: "cs2",       e: "🎯", t: "CS2"},
  {id: "ark",       e: "🦖", t: "ARK"},
  {id: "rust",      e: "🪓", t: "Rust"},
  {id: "palworld",  e: "🐾", t: "Palworld"},
  {id: "zomboid",   e: "🧟", t: "Project Zomboid"},
  {id: "7dtd",      e: "🩸", t: "7 Days to Die"},
  {id: "valheim",   e: "⚔", t: "Valheim"},
  {id: "keyboard",  e: "⌨", t: "Любая игра"},
].map(g => ({...g, n: g.e + " " + g.t}));

// Иконка игры из media/games/<id>.png; не загрузилась — подставится эмодзи
function gameIcon(id, size) {
  const g = GAMES.find(x => x.id === id);
  if (!g) return "";
  return `<img class="gicon" src="/media/games/${id}.png" alt="" width="${size}" height="${size}"
           data-e="${g.e}" data-size="${size}" onerror="gameIconFail(this)">`;
}
function gameIconFail(img) {
  const s = document.createElement("span");
  s.className = "gicon-e";
  s.textContent = img.dataset.e || "🎮";
  const sz = parseInt(img.dataset.size || img.getAttribute("width")) || 18;
  s.style.cssText = `display:inline-flex;align-items:center;justify-content:center;width:${sz}px;height:${sz}px;` +
                    `font-size:${Math.round(sz * 0.72)}px;line-height:1`;
  img.replaceWith(s);
}
const SERVER_GAMES = {ark: "ARK", rust: "Rust", palworld: "Palworld", zomboid: "Project Zomboid", "7dtd": "7 Days to Die"};
let MOD_STATUS = {};

function curGame() {
  const p = DATA.profiles && DATA.profiles[activeProfile];
  return (p && p.game) || "minecraft";
}

function cmdPlaceholder() {
  return ({gta5: "команда GTA 5, например vehicle adder",
           cs2: "key:g, turn:180, spin:3 или команда консоли",
           zomboid: "команда сервера, например createhorde 10 \"{nick}\"",
           "7dtd": "команда сервера, например spawnentity {pid} zombieArlene 3",
           valheim: "команда консоли F5, например spawn Troll 1",
           ark: "команда сервера ARK, например ServerChat привет",
           rust: "команда сервера Rust, например say привет",
           palworld: "команда Palworld, например announce привет",
           keyboard: "текст в консоль игры или key:f5"})[curGame()] || "команда без /";
}

function renderGameBar() {
  const cur = document.getElementById("gameCur");
  if (!cur) return;
  const x = GAMES.find(v => v.id === curGame()) || GAMES[0];
  cur.innerHTML = `${gameIcon(x.id, 22)}<span>${esc(x.t)}</span>`;
  updGameStatus();
}

// ── 🧩 Мод для игры: у GTA 5 — установщик, у остальных — нужен ли мод вообще ──
const MOD_INFO = {
  minecraft: ["⛏", "Мод не нужен", "Команды идут на сервер Minecraft (RCON или ServerTap). Свой сервер с готовыми настройками — вкладка «🖥 Серверы»."],
  cs2: ["⌨", "Мод не нужен", "Программа сама нажимает клавиши и вводит команды в консоль CS2 — работает и в сетевой игре."],
  valheim: ["⌨", "Мод не нужен", "Команды вводятся в консоль Valheim (F5) прямо в окне игры."],
  keyboard: ["⌨", "Мод не нужен", "Программа нажимает клавиши в окне любой игры."],
  ark: ["🖥", "Мод не нужен", "Подарки идут на сервер ARK через RCON. Свой сервер — вкладка «🖥 Серверы»."],
  rust: ["🖥", "Мод не нужен", "Подарки идут на сервер Rust через WebRCON. Свой сервер — вкладка «🖥 Серверы»."],
  zomboid: ["🖥", "Мод не нужен", "Подарки идут на сервер Project Zomboid через RCON. Свой сервер — вкладка «🖥 Серверы»."],
  "7dtd": ["🖥", "Мод не нужен", "Подарки идут на сервер 7 Days to Die через Telnet. Свой сервер — вкладка «🖥 Серверы»."],
  palworld: ["🖥", "Мод не обязателен", "Объявления и сохранение работают через сервер. Спавн палов и предметов — только с модом сервера (UE4SS), он в планах."],
};

async function openModPanel() {
  const g = curGame();
  const box = document.getElementById("modBody");
  document.getElementById("modTitle").textContent = "🧩 Мод для " + ((GAMES.find(x => x.id === g) || {}).t || "игры");
  document.getElementById("modModal").classList.remove("hidden");
  if (g !== "gta5") {
    const [i, h, d] = MOD_INFO[g] || ["🎮", "Мод не нужен", ""];
    box.innerHTML = `<div class="mod-none"><div class="mod-ico">${i}</div><div><b>${h}</b><div class="hint" style="margin-top:4px">${d}</div></div></div>`;
    return;
  }
  box.innerHTML = '<div class="hint">Ищу GTA 5 на компьютере…</div>';
  let d;
  try { d = await (await fetch("/api/mods/gta5", {cache: "no-store"})).json(); } catch (e) { box.innerHTML = "✗ " + e.message; return; }
  MOD_STATE = d;
  modRender();
}
let MOD_STATE = null;

function modRender() {
  const d = MOD_STATE, box = document.getElementById("modBody");
  const st = (d.games || []).find(x => x.path === d.current) || (d.games || [])[0];
  const row = (ok, title, desc, action) => `<div class="mod-row ${ok ? "ok" : "no"}"><span class="mod-ic">${ok ? "✅" : "❌"}</span>
    <div class="mod-t"><b>${title}</b><div class="hint">${desc}</div></div>${action || ""}</div>`;
  box.innerHTML = `
    <div class="mod-path">
      ${st ? `<div>📁 Игра найдена: <span class="mono">${esc(st.path)}</span> · ${st.edition === "enhanced" ? "GTA 5 Enhanced" : "GTA 5"}</div>`
           : `<div>😕 GTA 5 не нашлась автоматически — укажи папку игры (там, где GTA5.exe)</div>`}
      ${(d.games || []).length > 1 ? `<select class="sx-in" onchange="MOD_STATE.current=this.value; modRender()">${d.games.map(x =>
          `<option value="${esc(x.path)}"${x.path === (st && st.path) ? " selected" : ""}>${esc(x.path)}</option>`).join("")}</select>` : ""}
      <div class="row" style="gap:8px;margin-top:8px"><input id="modPath" class="sx-in mono" style="flex:1"
        placeholder="или вставь путь, например D:\\SteamLibrary\\steamapps\\common\\Grand Theft Auto V">
        <button class="small" onclick="modUsePath()">Проверить</button></div>
    </div>
    ${st ? `<div class="mod-list">
      ${row(st.shv, "Script Hook V", st.shv ? "стоит" : "нужен — авторы не разрешают его раздавать, скачай с их сайта: ScriptHookV.dll и dinput8.dll → в папку игры",
            st.shv ? "" : `<a class="btn small" href="${d.links.shv}" target="_blank" rel="noopener">↗ Сайт</a>`)}
      ${row(st.shvdn, "Script Hook V .NET Enhanced", st.shvdn ? "стоит" : "нужен — для обычной GTA 5 и для Enhanced; файлы ScriptHookVDotNet* и MinHook.x64.dll → в папку игры",
            st.shvdn ? "" : `<a class="btn small" href="${d.links.shvdn}" target="_blank" rel="noopener">↗ Страница</a>`)}
      ${row(st.mod_current, "Мод TakyLive — 80 команд", st.mod_current ? "стоит последняя версия" : st.mod ? "стоит старая версия — обнови" : "не установлен",
            `<button class="small primary" onclick="modInstall()">${st.mod_current ? "↻ Переустановить" : st.mod ? "⬆ Обновить" : "⬇ Установить"}</button>`)}
      ${st.old.length ? `<div class="gh-warn">⚠ В scripts лежит старый мод (${esc(st.old.join(", "))}) — при установке он удалится, иначе подарки сработают дважды.</div>` : ""}
    </div>
    <div class="row" style="margin-top:10px;gap:8px"><button class="small" onclick="modOpen()">📂 Открыть папку scripts</button>
      <a class="btn small" href="${d.download}" download="TakyLive.3.cs">⬇ Скачать файл мода</a><div class="spacer"></div>
      <span class="hint" id="modHint"></span></div>` : ""}
    <div class="gh-warn" style="margin-top:12px">⚠ Только сюжетный режим — в GTA Online моды = бан.</div>`;
}

async function modUsePath() {
  const p = document.getElementById("modPath").value.trim().replace(/^"|"$/g, "");
  if (!p) return;
  const d = await (await fetch("/api/mods/gta5?path=" + encodeURIComponent(p), {cache: "no-store"})).json();
  if (d.ok === false) { document.getElementById("modBody").insertAdjacentHTML("afterbegin", `<div class="gh-warn">✗ ${esc(d.error)}</div>`); return; }
  MOD_STATE = d;
  modRender();
}

async function modInstall() {
  const d = await (await fetch("/api/mods/gta5/install", {method: "POST", headers: {"Content-Type": "application/json"},
                                                          body: JSON.stringify({path: MOD_STATE.current})})).json();
  if (!d.ok) { alert(d.error); return; }
  await openModPanel();
  const h = document.getElementById("modHint");
  if (h) h.textContent = "✓ Мод установлен" + (d.removed.length ? ", старый удалён" : "") + " — запусти GTA 5 в сюжетном режиме";
}

async function modOpen() {
  const d = await (await fetch("/api/mods/gta5/open", {method: "POST", headers: {"Content-Type": "application/json"},
                                                       body: JSON.stringify({path: MOD_STATE.current})})).json();
  if (!d.ok) alert(d.error);
}

function openGamePick() {
  const box = document.getElementById("gamePickBody");
  const g = curGame();
  box.innerHTML = GAMES.map(x => `<div class="type-tile${x.id === g ? " sel" : ""}" onclick="gamePickChoose('${x.id}')">
      <div class="te">${gameIcon(x.id, 44)}</div><div class="tn">${esc(x.t)}</div></div>`).join("");
  document.getElementById("gamePickModal").classList.remove("hidden");
}
function closeGamePick() { document.getElementById("gamePickModal").classList.add("hidden"); }
function gamePickChoose(id) { closeGamePick(); setGame(id); }

function setGame(id) {
  const p = DATA.profiles[activeProfile];
  if (!p) return;
  p.game = id;               // автосохранение подхватит само
  renderCards();             // подсказки в полях команд меняются под игру
  pollModStatus();
}

async function pollModStatus() {
  try {
    const r = await fetch("/api/mod/status", {cache: "no-store"});
    MOD_STATUS = await r.json();
  } catch (e) {}
  updGameStatus();
}

function updGameStatus() {
  const el = document.getElementById("gameStatus");
  if (!el) return;
  const g = curGame();
  if (g === "gta5") {
    const s = (MOD_STATUS.games || {}).gta5 || {};
    el.innerHTML = s.connected
      ? '<span class="gs-on">● мод подключён</span>'
      : '<span class="gs-off">● мод не запущен — запусти GTA 5 с модом</span>';
  } else if (g === "valheim") {
    el.innerHTML = MOD_STATUS.keyboard === false
      ? '<span class="gs-off">● нажатия клавиш работают только на Windows</span>'
      : '<span class="gs-hint">команды вводятся в консоль Valheim (F5) — окно игры должно быть активным</span>';
  } else if (g === "cs2") {
    el.innerHTML = MOD_STATUS.keyboard === false
      ? '<span class="gs-off">● нажатия клавиш работают только на Windows</span>'
      : '<span class="gs-hint">клавиши и мышь уходят в окно CS2 — оно должно быть активным</span>';
  } else if (g === "keyboard") {
    el.innerHTML = MOD_STATUS.keyboard === false
      ? '<span class="gs-off">● нажатия клавиш работают только на Windows</span>'
      : '<span class="gs-hint">клавиши уходят в активное окно игры</span>';
  } else if (SERVER_GAMES[g]) {
    el.innerHTML = `<span class="gs-hint">команды идут на сервер ${SERVER_GAMES[g]} — Настройки → Серверные игры</span>`;
  } else if (!String(DATA.config.minecraft_nick || "").trim()) {
    el.innerHTML = '<span class="gs-off">⚠ не задан ник Minecraft — команды с {nick} пойдут на @p. Настройки → Minecraft</span>';
  } else {
    el.innerHTML = '<span class="gs-hint">команды идут на сервер — Настройки → Minecraft</span>';
  }
}
setInterval(() => {
  const v = document.getElementById("view-events");
  if (v && !v.classList.contains("hidden") && curGame() !== "minecraft") pollModStatus();
}, 2000);

// ── Каталог готовых команд: клик — и команда в цепочке ──────
// GTA 5 — 80 команд мода TakyLive, по группам
const GTA_GROUPS = [
 [
  "🚗 Транспорт",
  [
   [
    "vehicle adder",
    "🚗 Машина",
    "перед тобой: adder, zentorno, rhino (танк), bmx, bus, monster…"
   ],
   [
    "random_vehicle",
    "🎲 Случайная машина",
    "из весёлого списка: танк, мусоровоз, газонокосилка…"
   ],
   [
    "vehicle_in rhino",
    "🪖 Посадить в машину",
    "спавнит и сажает тебя за руль"
   ],
   [
    "rain_cars 5",
    "🌧 Дождь из машин",
    "N машин падают с неба (до 15)"
   ],
   [
    "boost 60",
    "🚀 Нитро",
    "машина резко ускоряется"
   ],
   [
    "jump_car 15",
    "🦘 Прыжок машины",
    "машину подбрасывает вверх"
   ],
   [
    "flip",
    "🙃 Перевернуть машину",
    "колёсами кверху"
   ],
   [
    "pop_tires",
    "🛞 Пробить шины",
    "все колёса сразу"
   ],
   [
    "slippery 20",
    "🧊 Скользкие шины",
    "машину заносит N секунд"
   ],
   [
    "engine_off 10",
    "🔇 Заглушить мотор",
    "двигатель не работает N секунд"
   ],
   [
    "eject",
    "🪂 Выкинуть из машины",
    "персонаж выпрыгивает на ходу"
   ],
   [
    "explode_car",
    "💥 Взорвать машину",
    "ту, в которой сидишь"
   ],
   [
    "delete_car",
    "👻 Машина исчезла",
    "выходишь — а её нет"
   ],
   [
    "repair",
    "🔧 Починить машину",
    "как новая"
   ],
   [
    "upgrade",
    "⚙ Тюнинг на максимум",
    "все улучшения сразу"
   ],
   [
    "paint",
    "🎨 Перекрасить",
    "случайный цвет"
   ],
   [
    "car_power 3",
    "⚡ Мощность ×N",
    "машина становится зверем"
   ]
  ]
 ],
 [
  "🧍 Игрок",
  [
   [
    "heal",
    "❤ Лечение",
    "здоровье и броня на максимум"
   ],
   [
    "armor",
    "🛡 Броня",
    "полная броня"
   ],
   [
    "kill",
    "💀 Убить",
    "персонаж падает замертво"
   ],
   [
    "god 30",
    "😇 Бессмертие",
    "N секунд неуязвимости"
   ],
   [
    "invisible 20",
    "🫥 Невидимка",
    "N секунд тебя не видно"
   ],
   [
    "superjump 30",
    "🦘 Суперпрыжок",
    "прыжки на крыши N секунд"
   ],
   [
    "fast_run 30",
    "🏃 Быстрый бег",
    "бег и плавание быстрее N секунд"
   ],
   [
    "drunk 20",
    "🍺 Пьяный",
    "шатается и качается камера N секунд"
   ],
   [
    "ragdoll 3",
    "🤸 Упасть",
    "персонаж валится N секунд"
   ],
   [
    "launch 25",
    "🚀 Подбросить",
    "в небо на N метров"
   ],
   [
    "skydive 400",
    "🪂 Прыжок с парашютом",
    "телепорт на высоту + парашют"
   ],
   [
    "fire_player",
    "🔥 Поджечь",
    "персонаж загорается"
   ],
   [
    "wanted 3",
    "🚓 Розыск",
    "звёзды 0–5"
   ],
   [
    "clear_wanted",
    "😌 Снять розыск",
    ""
   ],
   [
    "teleport random",
    "🌀 Телепорт",
    "airport, chiliad, maze_bank, beach, vinewood_sign, sandy, docks, zancudo, paleto, prison или random"
   ],
   [
    "teleport_waypoint",
    "📍 Телепорт к метке",
    "куда поставишь метку на карте"
   ],
   [
    "money 1000",
    "💵 Дать денег",
    "в сюжете — текущему герою"
   ],
   [
    "take_money 1000",
    "💸 Отнять деньги",
    ""
   ],
   [
    "random_outfit",
    "👕 Случайная одежда",
    "переодевает героя"
   ]
  ]
 ],
 [
  "🔫 Оружие",
  [
   [
    "weapon weapon_rpg 10",
    "🔫 Дать оружие",
    "weapon_rpg, weapon_minigun, weapon_railgun, weapon_stungun…"
   ],
   [
    "random_weapon",
    "🎲 Случайное оружие",
    ""
   ],
   [
    "all_weapons",
    "🧰 Весь арсенал",
    "16 видов оружия сразу"
   ],
   [
    "remove_weapons",
    "🚫 Отобрать оружие",
    "всё до последнего ножа"
   ],
   [
    "infinite_ammo 30",
    "♾ Бесконечные патроны",
    "N секунд без перезарядки"
   ],
   [
    "explosive_ammo 20",
    "💣 Взрывные пули",
    "N секунд"
   ],
   [
    "fire_ammo 20",
    "🔥 Огненные пули",
    "N секунд"
   ],
   [
    "explosive_punch 20",
    "👊 Взрывной кулак",
    "удары взрываются N секунд"
   ]
  ]
 ],
 [
  "🧟 Люди и звери",
  [
   [
    "zombies 5",
    "🧟 Зомби",
    "толпа зомби нападает"
   ],
   [
    "clowns 4",
    "🤡 Клоуны с битами",
    ""
   ],
   [
    "army 3",
    "🪖 Армия",
    "морпехи с автоматами"
   ],
   [
    "aliens 2",
    "👽 Пришельцы",
    "с лучевыми пистолетами"
   ],
   [
    "cops 3",
    "👮 Копы",
    "нападают + 2 звезды розыска"
   ],
   [
    "juggernaut 1",
    "🦾 Джаггернаут",
    "в броне и с миниганом"
   ],
   [
    "cougar 1",
    "🐆 Пума",
    "дикая кошка атакует"
   ],
   [
    "enemies 3 weapon_pistol",
    "😈 Враги",
    "N врагов с оружием"
   ],
   [
    "bodyguards 2",
    "🕴 Охрана",
    "N телохранителей за тобой"
   ],
   [
    "peds 5",
    "👥 Толпа людей",
    "N случайных прохожих"
   ],
   [
    "animal a_c_chimp",
    "🐒 Животное",
    "a_c_chimp, a_c_chop, a_c_cow, a_c_boar, a_c_cat_01…"
   ],
   [
    "angry_peds 40",
    "😡 Все злые",
    "прохожие в радиусе N нападают с битами"
   ],
   [
    "panic 50",
    "😱 Паника",
    "все вокруг разбегаются"
   ],
   [
    "clear_area 60",
    "🧹 Очистить район",
    "убрать людей и машины вокруг"
   ]
  ]
 ],
 [
  "🌍 Мир",
  [
   [
    "meteors 8",
    "☄ Метеоритный дождь",
    "N взрывов падают вокруг"
   ],
   [
    "airstrike",
    "✈ Авиаудар",
    "серия взрывов идёт прямо на тебя"
   ],
   [
    "explode",
    "💥 Взрыв",
    "в нескольких метрах перед тобой"
   ],
   [
    "fire",
    "🔥 Пожар",
    "огонь перед тобой"
   ],
   [
    "fireworks 6",
    "🎆 Салют",
    "N залпов вокруг"
   ],
   [
    "geyser",
    "⛲ Гейзер",
    "струя воды подбрасывает тебя"
   ],
   [
    "poop 5",
    "💩 Птичий налёт",
    "сверху падают птичьи «подарки»"
   ],
   [
    "weather THUNDER",
    "⛈ Погода",
    "THUNDER, RAIN, CLEAR, SNOW, XMAS, FOGGY, BLIZZARD, HALLOWEEN"
   ],
   [
    "time 0",
    "🌙 Время",
    "час 0–23"
   ],
   [
    "add_hours 6",
    "⏩ Перемотать время",
    "+N часов"
   ],
   [
    "slowmo 5",
    "🐢 Замедление",
    "мир медленнее N секунд"
   ],
   [
    "moon_gravity 20",
    "🌕 Лунная гравитация",
    "прыжки как на Луне N секунд"
   ],
   [
    "riot 30",
    "🔥 Бунт",
    "весь город дерётся N секунд"
   ],
   [
    "blackout 30",
    "🌑 Блэкаут",
    "в городе гаснет свет N секунд"
   ]
  ]
 ],
 [
  "📺 Экран",
  [
   [
    "shake 0.6",
    "📳 Тряска камеры",
    "сила 0.1–2"
   ],
   [
    "trip 12",
    "🌈 Глюки",
    "случайный «кислотный» эффект N секунд"
   ],
   [
    "screen_fx Rampage 10",
    "🎞 Эффект экрана",
    "Rampage, ChopVision, DrugsMichaelAliensFight, DeathFailOut…"
   ],
   [
    "fade 3",
    "⬛ Темнота",
    "экран гаснет на N секунд"
   ],
   [
    "notify {user} подарил {giftname}!",
    "💬 Уведомление",
    "сообщение в углу экрана"
   ],
   [
    "big_text {user} устроил хаос!",
    "🔠 Большой текст",
    "крупная надпись внизу экрана"
   ]
  ]
 ],
 [
  "🎲 Хаос",
  [
   [
    "random_chaos",
    "🎲 Случайный хаос",
    "одна из 20 весёлых команд наугад"
   ],
   [
    "reset",
    "♻ Сбросить всё",
    "снять все эффекты: гравитацию, бессмертие, глюки…"
   ]
  ]
 ]
];
const GAME_CMDS = {
  gta5: GTA_GROUPS.flatMap(g => g[1]),
  minecraft: [
    ["summon zombie ~ ~ ~",                            "🧟 Зомби",    ""],
    ["summon creeper ~ ~ ~",                           "💚 Крипер",   ""],
    ["summon tnt ~ ~ ~",                               "🧨 ТНТ",      ""],
    ["execute at {nick} run summon lightning_bolt ~ ~ ~", "🌩 Молния", ""],
    ["give {nick} diamond 5",                          "💎 Алмазы",   ""],
    ["effect give {nick} speed 30 2",                  "⚡ Скорость", "30 секунд"],
    ["weather thunder",                                "⛈ Гроза",     ""],
    ["time set night",                                 "🌙 Ночь",     ""],
    ["title {nick} title {\"text\":\"{user}!\"}",      "💬 Надпись",  "крупный текст на экране"],
  ],
  cs2: [
    ["key:g",           "🔫 Выбросить оружие",    "клавиша G — выбрасывает то, что в руках"],
    ["key:space",       "⤴ Прыжок",               ""],
    ["hold:ctrl:2",     "🦆 Присесть на 2 сек",    ""],
    ["hold:w:2",        "🏃 Бежать вперёд 2 сек",  ""],
    ["hold:mouse1:1",   "💥 Стрелять 1 сек",       "тратит патроны в никуда"],
    ["key:r",           "🔄 Перезарядка",          "в самый неудобный момент"],
    ["key:f",           "🔍 Осмотреть оружие",     ""],
    ["key:3",           "🔪 Нож в руки",           ""],
    ["turn:180",        "↩ Развернуть на 180°",    "точность зависит от чувствительности в «Как подключить»"],
    ["turn:90",         "↪ Повернуть на 90°",      "минус — влево: turn:-90"],
    ["turn:0:60",       "⬆ Посмотреть в небо",     "минус — в пол: turn:0:-60"],
    ["spin:3",          "🌀 Крутиться 3 сек",      ""],
    ["buy negev",       "🛒 Купить Negev",         "команда консоли — работает во время закупки"],
    ["release:all",     "🛑 Отпустить все клавиши", "если что-то залипло"],
  ],
  zomboid: [
    ['servermsg "{user} подарил {giftname}!"', "📢 Сообщение всем",       "видят все игроки"],
    ['createhorde 10 "{nick}"',              "🧟 Орда зомби (10)",       "число можно менять"],
    ['createhorde 50 "{nick}"',              "🧟 Большая орда (50)",     ""],
    ["chopper",                               "🚁 Вертолёт",              "шумит и зовёт зомби со всей округи"],
    ["gunshot",                               "🔫 Выстрел",               "зомби идут на звук"],
    ['lightning "{nick}"',                   "⚡ Молния в игрока",        ""],
    ['thunder "{nick}"',                     "🌩 Гром",                  ""],
    ['startrain "100"',                      "🌧 Ливень",                ""],
    ['startstorm "1"',                       "⛈ Шторм",                 "длительность в часах игры"],
    ["stopweather",                           "☀ Убрать погоду",          ""],
    ['additem "{nick}" Base.Axe 1',          "🪓 Дать топор",            ""],
    ['additem "{nick}" Base.Pills 1',        "💊 Дать таблетки",         ""],
    ['addvehicle "Base.VanAmbulance" "{nick}"', "🚑 Машина скорой",      ""],
    ['godmodeplayer "{nick}" -true',         "🛡 Бессмертие",            "-false — выключить"],
  ],
  "7dtd": [
    ['say "{user} подарил {giftname}!"',     "📢 Сообщение в чат",       ""],
    ["spawnentity {pid} zombieArlene 3",      "🧟 3 зомби рядом",         "{pid} — ID игрока, программа узнаёт сама"],
    ["spawnentity {pid} zombieScreamer 1",    "😱 Крикунья",              "зовёт других зомби"],
    ["spawnentity {pid} zombieDog 2",         "🐕 Зомби-собаки",          ""],
    ["spawnentity {pid} animalBear 1",        "🐻 Медведь",               ""],
    ["spawnentity {pid} zombieFatCop 1",      "👮 Толстый коп",           "плюётся кислотой"],
    ["spawnwanderinghorde",                   "🧟 Бродячая орда",         "идёт к игрокам"],
    ["spawnscouts",                           "📣 Разведчики-крикуны",    ""],
    ["spawnairdrop",                          "📦 Сброс припасов",        "помощь от зрителей"],
    ["buffplayer {nick} buffLegBroken",       "🦴 Сломать ногу",          ""],
    ["give {nick} medicalBandage 3",          "🩹 Бинты",                 "падают перед игроком"],
    ["give {nick} drinkJarBoiledWater 2",     "💧 Чистая вода",           ""],
  ],
  valheim: [
    ["devcommands",          "🔓 Включить devcommands", "один раз за сессию — без этого остальное не работает"],
    ["spawn Greyling 5",     "👹 5 грейлингов",       ""],
    ["spawn Troll 1",        "🧌 Тролль",             ""],
    ["spawn Skeleton 3",     "💀 3 скелета",           ""],
    ["spawn Draugr 2",       "🧟 2 драугра",           ""],
    ["spawn Boar 3",         "🐗 3 кабана",            ""],
    ["spawn Neck 5",         "🦎 5 некков",            ""],
    ["event army_eikthyr",   "⚡ Набег",               "рейд — если включены в мире"],
    ["tod 0",                "🌙 Ночь",                "tod -1 — вернуть обычное время"],
    ["heal",                 "❤ Лечение",              ""],
    ["killall",              "🧹 Убить мобов рядом",    ""],
  ],
  ark: [
    ["ServerChat {user} подарил {giftname}!", "💬 Сообщение в чат", "видно всем игрокам"],
    ["Broadcast {user} подарил {giftname}!",  "📢 Объявление",      "крупно по центру экрана"],
    ["SetTimeOfDay 00:00",                    "🌙 Ночь",            "время ЧЧ:ММ"],
    ["SetTimeOfDay 12:00",                    "☀ День",             ""],
    ["GiveExpToPlayer {nick} 5000 0 1",       "⭐ Опыт",            "{nick} — твой ID игрока из настроек"],
    ["GiveItemToPlayer {nick} \"Blueprint'/Game/PrimalEarth/CoreBlueprints/Resources/PrimalItemResource_MetalIngot.PrimalItemResource_MetalIngot'\" 50 0 0",
                                              "🔩 Металлические слитки", "путь любого предмета — на ark.wiki.gg"],
    ["GiveItemToPlayer {nick} \"Blueprint'/Game/PrimalEarth/CoreBlueprints/Resources/PrimalItemResource_Crystal.PrimalItemResource_Crystal'\" 30 0 0",
                                              "💎 Кристаллы",        ""],
    ["DestroyWildDinos",                      "☄ Вымирание",        "дикие динозавры исчезнут и появятся заново"],
    ["KillPlayer {nick}",                     "☠ Убить персонажа",  ""],
    ["SaveWorld",                             "💾 Сохранить мир",   ""],
  ],
  rust: [
    ["say {user} подарил {giftname}!",           "💬 Сообщение в чат", ""],
    ["inventory.giveto \"{nick}\" rifle.ak 1",    "🔫 Автомат",         "выдать предмет: rifle.ak, scrap, wood…"],
    ["inventory.giveto \"{nick}\" ammo.rifle 128","🎯 Патроны",         ""],
    ["inventory.giveto \"{nick}\" scrap 100",     "⚙ Скрап",            ""],
    ["inventory.giveto \"{nick}\" syringe.medical 5", "💉 Аптечки",     ""],
    ["inventory.giveall wood 500",               "🪵 Дерево всем",     "всем игрокам на сервере"],
    ["env.time 0",                               "🌙 Ночь",            "время 0–24"],
    ["env.time 12",                              "☀ День",             ""],
    ["weather.rain 1",                           "🌧 Ливень",          "0 — выключить"],
    ["weather.fog 1",                            "🌫 Туман",           ""],
    ["weather.wind 1",                           "💨 Ветер",           ""],
    ["server.save",                              "💾 Сохранить мир",   ""],
  ],
  palworld: [
    ["announce {user} подарил {giftname}!", "📢 Объявление",      "через REST API — с пробелами и русскими буквами"],
    ["Save",                                "💾 Сохранить мир",   ""],
    ["ShowPlayers",                         "👥 Кто на сервере",  "ответ появится в «Лог событий»"],
  ],
  keyboard: [
    ["key:space",        "⎵ Нажать клавишу",   "a–z, 0–9, f1–f12, enter, esc, space, shift, ctrl…"],
    ["key:ctrl+shift+a", "🎹 Сочетание",       "несколько клавиш сразу через +"],
    ["hold:w:3",         "⏳ Зажать на N сек", "например, бежать вперёд 3 секунды"],
    ["type:spawn Troll", "⌨ Напечатать текст", "для консоли игры — сначала открой её"],
    ["key:enter",        "↵ Enter",            ""],
    ["key:grave",        "~ Консоль",          "клавиша ~ открывает консоль во многих играх"],
    ["click:left",       "🖱 Клик мышью",      "left, right, middle"],
  ],
};
let cmdTarget = null, CMD_VIEW = [];

function openCmdPicker(idx) {
  cmdTarget = {sec: activeSection, idx};
  const g = curGame();
  CMD_VIEW = [];
  if (g === "gta5") GTA_GROUPS.forEach(([t, list]) => CMD_VIEW.push(["GTA 5 · " + t, list]));
  if (g === "cs2") CMD_VIEW.push(["🎯 CS2 — подлянки от зрителей", GAME_CMDS.cs2]);
  if (g === "valheim") CMD_VIEW.push(["⚔ Valheim — консоль F5", GAME_CMDS.valheim]);
  if (SERVER_GAMES[g]) CMD_VIEW.push([GAMES.find(x => x.id === g).n + " — команды сервера", GAME_CMDS[g]]);
  if (g === "minecraft") CMD_VIEW.push(["⛏ Minecraft", GAME_CMDS.minecraft]);
  CMD_VIEW.push(["⌨ Клавиатура и мышь — работают в любой игре", GAME_CMDS.keyboard]);
  let html = "";
  if (g === "valheim") html += `<div class="hint" style="margin-bottom:10px">Строка без key:/type: уходит в консоль
    Valheim (F5). Сначала один раз за сессию — <b>devcommands</b>.</div>`;
  if (g === "cs2") html += `<div class="hint" style="margin-bottom:10px">Строка без key:/hold:/turn:
    уходит в консоль CS2 (~) — например <b>buy negev</b>.</div>`;
  if (g === "keyboard") html += `<div class="hint" style="margin-bottom:10px">Обычная строка без key:/type:
    программа напечатает её и нажмёт Enter — удобно для консоли игры.</div>`;
  CMD_VIEW.forEach(([title, list], gi) => {
    html += `<div class="cmd-group">${title}</div>`;
    html += list.map(([cmd, name, desc], ci) => `<div class="ci" onclick="pickCmd(${gi},${ci})">
        <span class="cn">${name}</span><span class="cc">${esc(cmd)}</span><span class="cd">${esc(desc)}</span>
        <button class="small ci-try" title="Попробовать сейчас, не добавляя"
                onclick="event.stopPropagation(); tryCmd(${gi},${ci})">▶</button>
      </div>`).join("");
  });
  document.getElementById("cmdList").innerHTML =
    `<div class="hint" id="cmdHint" style="margin-bottom:8px">Клик по строке — добавить в событие, ▶ — попробовать сразу</div>` + html;
  document.getElementById("cmdModal").classList.remove("hidden");
}

async function tryCmd(gi, ci) {
  const cmd = CMD_VIEW[gi][1][ci][0];
  const kb = /^(key|hold|type|click):/i.test(cmd) || curGame() === "keyboard";
  const hint = document.getElementById("cmdHint");
  try {
    const r = await fetch("/api/game/try", {method: "POST", headers: {"Content-Type": "application/json"},
                          body: JSON.stringify({cmd, delay: kb ? 3 : 0})});
    const d = await r.json();
    if (hint) hint.textContent = !d.ok ? "✗ " + d.error
      : kb ? "⏳ Через 3 секунды — переключись в окно игры!" : "✓ Отправлено: " + cmd;
  } catch (e) { if (hint) hint.textContent = "✗ " + e.message; }
}

function closeCmdPicker() { document.getElementById("cmdModal").classList.add("hidden"); }

function pickCmd(gi, ci) {
  if (!cmdTarget) return;
  const cmd = CMD_VIEW[gi][1][ci][0];
  activeSection = cmdTarget.sec;
  const a = curList()[cmdTarget.idx];
  if (!a) return;
  if (!a.commands) a.commands = [];
  if (!a.delays) a.delays = [];
  const empty = a.commands.findIndex(x => !String(x || "").trim());
  if (empty >= 0) a.commands[empty] = cmd;          // пустую строку заменяем
  else { a.commands.push(cmd); a.delays.push(0); }
  closeCmdPicker();
  EXPANDED.add(a);
  renderCards();
}

// ── Как подключить игру ─────────────────────────────────────
function openGameHelp() {
  const g = curGame();
  const t = document.getElementById("ghTitle"), b = document.getElementById("ghBody");
  if (g === "gta5") {
    t.textContent = "🚗 Как подключить GTA 5";
    b.innerHTML = `<div class="gh-ok" style="margin-bottom:10px">🧩 Проще всего — кнопка <b>«Мод для игры»</b> рядом:
      программа сама найдёт GTA 5, проверит, что нужно, и поставит мод одной кнопкой.</div>
    Вручную:<ol>
      <li>Поставь <b>Script Hook V</b> — сайт <b>dev-c.com</b>, раздел GTA V. Файлы <code>ScriptHookV.dll</code>
          и <code>dinput8.dll</code> — в папку игры.</li>
      <li>Поставь <b>ScriptHookVDotNet Enhanced</b> — сайт <b>gta5-mods.com</b>. Подходит и для обычной GTA 5,
          и для Enhanced. Файлы <code>ScriptHookVDotNet*</code> — в папку игры.
          Для Enhanced авторы ещё советуют <b>DirectStorageFix</b>.</li>
      <li>Создай в папке игры папку <code>scripts</code> и положи туда мод:
          <a href="/mods/GTA5/TakyLive.3.cs" download="TakyLive.3.cs"><b>⬇ скачать TakyLive.3.cs</b></a>
          или <button class="small" onclick="openModFolder('gta5')">📂 открыть папку с модом</button>
          <span id="ghFolder" class="hint"></span></li>
      <li>Запусти <b>сначала эту программу</b>, потом GTA 5 → сюжетный режим.
          В игре появится «TakyLive подключён», а здесь — <span class="gs-on">● мод подключён</span>.
          Старый файл <code>TikTokBridge.3.cs</code> из <code>scripts</code> удали — иначе подарки сработают дважды.</li>
      <li>Нажми «▶ Тест» на любом событии — в игре должно сработать.</li>
    </ol>
    <div class="gh-warn">⚠ Только сюжетный режим — в GTA Online моды = бан.<br>
      Если мод не запустился — пришли мне файл <b>ScriptHookVDotNet.log</b> из папки игры.
      Ошибки команд мод сам присылает в «📋 Лог событий».</div>`;
  } else if (g === "cs2") {
    t.textContent = "🎯 Как подключить CS2";
    const sens = DATA.config.cs2_sensitivity ?? 2.0;
    b.innerHTML = `Программа «нажимает» клавиши и двигает мышь прямо в окне игры — работает и в сетевой игре.
      <ol style="margin-top:10px">
        <li>В настройках CS2 включи <b>«Консоль разработчика (~)»</b> — для команд вроде <code>buy negev</code>.</li>
        <li>Впиши свою <b>чувствительность мыши</b> из настроек CS2 — от неё зависит, чтобы разворот был ровно на 180°:
            <input id="cs2Sens" type="number" step="0.01" min="0.05" value="${esc(sens)}"
                   style="width:90px;margin-left:6px" onchange="saveCs2Sens(this.value)">
            <span id="cs2SensHint" class="hint"></span></li>
        <li>Клавиши в командах — стандартные: G выбросить, R перезарядка, F осмотр, Ctrl присесть. Если ты их
            переназначал — поправь команды под себя.</li>
        <li>Окно CS2 должно быть активным. Если что-то залипло — кнопка «🛑 Отпустить все клавиши».</li>
      </ol>
      <div class="gh-warn">⚠ <b>Аккаунт:</b> Valve кикает с официальных серверов за автоматизацию ввода. Наши команды
        тебе мешают, а не помогают, но гарантий нет — на аккаунте с дорогим инвентарём лучше не рисковать.<br>
        ⚠ <b>Тиммейты:</b> в соревновательном и Premier это подставляет команду — на тебя будут жаловаться.
        Лучшие режимы: бой насмерть, гонка вооружений, обычный, комьюнити-серверы.</div>`;
  } else if (SERVER_GAMES[g]) {
    const H = {
      ark: ["🦖 Как подключить ARK", `Нужен <b>свой сервер</b> ARK (Survival Ascended или Evolved).
        <ol style="margin-top:10px">
          <li>В файле <code>ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini</code> в разделе
              <code>[ServerSettings]</code> добавь: <code>RCONEnabled=True</code>, <code>RCONPort=27020</code>,
              <code>ServerAdminPassword=придумай_пароль</code>.</li>
          <li>Открой порт RCON в разделе «Сеть» хостинга и перезапусти сервер.</li>
          <li><b>Настройки → Серверные игры → ARK</b>: IP, порт, пароль и <b>свой ID игрока</b> — число из
              импланта (Specimen Implant) в инвентаре. Оно подставляется в <code>{nick}</code>.</li>
        </ol>`, "Через сервер нельзя заспавнить динозавра рядом с тобой — сервер не знает, где ты стоишь. Работают чат, объявления, время, предметы и опыт по твоему ID."],
      rust: ["🪓 Как подключить Rust", `Нужен <b>свой сервер</b> Rust.
        <ol style="margin-top:10px">
          <li>Запусти сервер с параметрами <code>+rcon.web 1 +rcon.port 28016 +rcon.password придумай_пароль</code>.</li>
          <li>Открой порт RCON в разделе «Сеть» хостинга.</li>
          <li><b>Настройки → Серверные игры → Rust</b>: IP, порт, пароль и свой ник или SteamID64 —
              подставляется в <code>{nick}</code>.</li>
        </ol>`, "Спавн мобов рядом с тобой через сервер не работает — нужны координаты. Работают выдача предметов, время, погода и чат."],
      palworld: ["🐾 Как подключить Palworld", `Нужен <b>свой сервер</b> Palworld.
        <ol style="margin-top:10px">
          <li>В <code>PalWorldSettings.ini</code>: <code>RCONEnabled=True</code>, <code>RCONPort=25575</code>,
              <code>RESTAPIEnabled=True</code>, <code>RESTAPIPort=8212</code>, <code>AdminPassword=придумай_пароль</code>.</li>
          <li>Открой порты на хостинге и перезапусти сервер.</li>
          <li><b>Настройки → Серверные игры → Palworld</b>: IP, порты и пароль.</li>
        </ol>`, "Сервер Palworld умеет только объявления и сохранение. Спавн палов и предметы — только через мод, его сделаем отдельно."],
      zomboid: ["🧟 Как подключить Project Zomboid", `Проще всего — <b>свой сервер в программе</b>: вкладка «🖥 Серверы» →
        «+ Новый сервер» → Project Zomboid → «🔌 Подарки сюда». RCON программа включит сама.
        <ol style="margin-top:10px">
          <li>Для своего сервера на хостинге: в <code>Zomboid/Server/&lt;имя&gt;.ini</code> впиши
              <code>RCONPort=27015</code> и <code>RCONPassword=придумай_пароль</code>, перезапусти.</li>
          <li><b>Настройки → Серверные игры → Project Zomboid</b>: IP, порт, пароль и <b>свой ник</b> в игре —
              подставляется в <code>{nick}</code>.</li>
        </ol>`, "Орда, молния и гром бьют по нику, а вертолёт и выстрел — по случайному игроку на сервере. Команды сверены со списком Build 42."],
      "7dtd": ["🩸 Как подключить 7 Days to Die", `Проще всего — <b>свой сервер в программе</b>: вкладка «🖥 Серверы» →
        «+ Новый сервер» → 7 Days to Die → «🔌 Подарки сюда». Telnet программа включит сама.
        <ol style="margin-top:10px">
          <li>Для своего сервера на хостинге: в <code>serverconfig.xml</code> — <code>TelnetEnabled=true</code>,
              <code>TelnetPort=8081</code>, <code>TelnetPassword=придумай_пароль</code>.</li>
          <li><b>Настройки → Серверные игры → 7 Days to Die</b>: IP, порт, пароль и <b>свой ник</b>.</li>
          <li>Существ сервер призывает по <b>ID игрока</b>, а не по нику — пиши <code>{pid}</code>,
              программа узнает ID сама.</li>
        </ol>`, "Не ставь на подарки settime day / settime night — в 7 Days to Die они переводят календарь на день 1–2, это откат дней выживания."],
    }[g];
    t.textContent = H[0];
    b.innerHTML = H[1] + `<div class="gh-warn">⚠ ${H[2]}<br>Работает только на своём сервере, где у тебя есть пароль админа.</div>`;
  } else if (g === "valheim") {
    t.textContent = "⚔ Как подключить Valheim";
    b.innerHTML = `Команды вводятся в <b>консоль Valheim</b> — программа сама откроет её (F5), впишет команду и закроет.
      <ol style="margin-top:10px">
        <li>Окно Valheim должно быть на переднем плане.</li>
        <li>Один раз за сессию отправь <code>devcommands</code> (кнопка на панели) — без этого спавн не работает.</li>
        <li>На выделенном сервере ты должен быть в <code>adminlist.txt</code>.</li>
      </ol>
      <div class="gh-warn">⚠ У сервера Valheim нет своей консоли, поэтому всё идёт через окно игры на твоём ПК.</div>`;
  } else if (g === "keyboard") {
    t.textContent = "⌨ Любая игра через клавиатуру";
    b.innerHTML = `Команды <code>key:</code> <code>hold:</code> <code>type:</code> <code>click:</code> нажимают
      клавиши в <b>активном окне</b> — как будто жмёшь сам. Обычная строка печатается и отправляется Enter.
      <ol style="margin-top:10px">
        <li>Окно игры должно быть на переднем плане.</li>
        <li>Если игра запущена от администратора — запусти программу тоже от администратора.</li>
        <li>Пример для консоли Valheim: <code>key:f5</code> → <code>spawn Troll 1</code> → <code>key:f5</code></li>
      </ol>
      <div class="gh-warn">⚠ Не используй в онлайн-играх с античитом.<br>
        Не подставляй <b>{comment}</b> в <code>type:</code> — зритель сможет вписать в консоль игры что угодно.</div>`;
  } else {
    t.textContent = "⛏ Как подключить Minecraft";
    b.innerHTML = `Команды идут на твой сервер через <b>ServerTap</b> или <b>RCON</b> — выбери способ и заполни
      поля в <b>Настройки → Minecraft</b>, там же кнопка «Проверить».
      <div style="margin-top:10px">Клавиатура тоже работает: <code>key:space</code> — прыжок, если окно Minecraft активно.</div>`;
  }
  document.getElementById("gameHelpModal").classList.remove("hidden");
}

async function saveCs2Sens(v) {
  const n = parseFloat(String(v).replace(",", "."));
  const el = document.getElementById("cs2SensHint");
  if (!(n > 0)) { if (el) el.textContent = "✗ нужно число"; return; }
  DATA.config.cs2_sensitivity = n;
  try {
    await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({cs2_sensitivity: n})});
    if (el) el.textContent = "✓ сохранено";
  } catch (e) { if (el) el.textContent = "✗ " + e.message; }
}

function closeGameHelp() { document.getElementById("gameHelpModal").classList.add("hidden"); }

async function openModFolder(game) {
  const el = document.getElementById("ghFolder");
  try {
    const r = await fetch("/api/mod/open_folder", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({game})});
    const d = await r.json();
    if (el) el.textContent = d.ok ? "✓ открыл" : ("✗ " + d.error + (d.path ? " — " + d.path : ""));
  } catch (e) { if (el) el.textContent = "✗ " + e.message; }
}

// ── Новая вкладка: выбор игры → пустая или готовый шаблон ────
let TEMPLATES = [], NT_GAME = null, NT_NAME_TOUCHED = false;
const SEC_NAMES = {gifts: "подарков", likes: "лайков", subs: "подписок", follows: "фолловов",
                   chatcmds: "чат-команд", goals: "целей", panel: "кнопок"};
const GAME_DEFAULT_NAME = {minecraft: "Minecraft стрим", gta5: "GTA 5 стрим", cs2: "CS2 стрим", ark: "ARK стрим",
                           rust: "Rust стрим", palworld: "Palworld стрим", zomboid: "Zomboid стрим",
                           "7dtd": "7 Days стрим", valheim: "Valheim стрим", keyboard: "Новая игра"};

function uniqueTabName(base) {
  let name = String(base || "Новая вкладка").trim() || "Новая вкладка", n = 2;
  const b = name;
  while (DATA.profiles[name]) name = `${b} ${n++}`;
  return name;
}

async function openNewTab() {
  NT_GAME = null;
  document.getElementById("newTabModal").classList.remove("hidden");
  ntRender();
  try {
    const r = await fetch("/api/templates", {cache: "no-store"});
    TEMPLATES = (await r.json()).templates || [];
  } catch (e) { TEMPLATES = []; }
  // шаблоны подгрузились — перерисовываем окно на любом шаге (введённое название сохранится)
  if (!document.getElementById("newTabModal").classList.contains("hidden")) ntRender();
}

function closeNewTab() { document.getElementById("newTabModal").classList.add("hidden"); }

function ntPickGame(g) {
  NT_GAME = g;
  NT_NAME_TOUCHED = false;
  ntRender();
}

function ntBack() { NT_GAME = null; ntRender(); }

function ntRender() {
  const t = document.getElementById("ntTitle"), b = document.getElementById("ntBody");
  if (!NT_GAME) {
    t.textContent = "Новая вкладка — для какой игры?";
    b.innerHTML = `<div class="type-grid">` + GAMES.map(x => {
      const n = TEMPLATES.filter(tp => tp.game === x.id).length;
      return `<div class="type-tile" onclick="ntPickGame('${x.id}')">
        <div class="te">${gameIcon(x.id, 48)}</div><div class="tn">${esc(x.t)}</div>
        <div class="td">${n ? n + " " + plural(n, "шаблон", "шаблона", "шаблонов") : "&nbsp;"}</div></div>`;
    }).join("") + `</div>`;
    return;
  }
  const game = GAMES.find(x => x.id === NT_GAME);
  const list = TEMPLATES.map((tp, i) => [tp, i]).filter(([tp]) => tp.game === NT_GAME);
  t.innerHTML = `Новая вкладка — ${gameIcon(NT_GAME, 22)} ${esc(game.t)}`;
  const cur = document.getElementById("ntName");
  const nameVal = cur && NT_NAME_TOUCHED ? cur.value : GAME_DEFAULT_NAME[NT_GAME];
  b.innerHTML = `
    <div class="row" style="margin-bottom:14px">
      <button class="small" onclick="ntBack()">← другая игра</button>
      <label class="nt-name">Название <input id="ntName" value="${esc(nameVal)}"
             oninput="NT_NAME_TOUCHED = true"></label>
    </div>
    <div class="tpl nt-empty">
      <div class="tpl-ico">✏</div>
      <div class="tpl-body"><div class="tpl-title">Пустая вкладка</div>
        <div class="tpl-desc">Настроишь всё сам — события добавляются кнопкой «+ Создать событие»</div></div>
      <button class="small" onclick="ntCreateEmpty()">Создать пустую</button>
    </div>
    <div class="nt-sub">${list.length ? "Или возьми готовый шаблон:" : "Для этой игры шаблонов пока нет"}</div>
    ${list.map(([tp, i]) => {
      const counts = Object.entries(tp.counts || {}).map(([k, n]) => `${n} ${SEC_NAMES[k] || k}`).join(" · ");
      return `<div class="tpl">
        <div class="tpl-ico">${esc(tp.icon)}</div>
        <div class="tpl-body"><div class="tpl-title">${esc(tp.title)}</div>
          <div class="tpl-desc">${esc(tp.description)}</div><div class="tpl-counts">${esc(counts)}</div></div>
        <button class="primary small" onclick="ntUseTemplate(${i})">Взять шаблон</button>
      </div>`;
    }).join("")}`;
}

function ntFinish(name, prof) {
  prof.game = NT_GAME;
  SEC_ORDER.forEach(k => { if (!prof[k]) prof[k] = []; });
  DATA.profiles[name] = prof;
  activeProfile = name;
  FILTER = "all";
  closeNewTab();
  renderProfiles();
  renderCards();
  pollModStatus();
  const hint = document.getElementById("saveHint");
  if (hint) hint.textContent = `✓ Создана вкладка «${name}»`;
  switchView("events");
}

// Склонение: 1 шаблон, 3 шаблона, 5 шаблонов, 21 шаблон
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

// ── Стартовый экран: продолжить вкладку или новая под игру ──
async function renderStart() {
  const cont = document.getElementById("stContinue"), games = document.getElementById("stGames");
  if (!cont || !games) return;
  const names = Object.keys(DATA.profiles || {});
  const live = DATA.connected ? liveProfile() : "";
  cont.innerHTML = names.length ? `<div class="st-head">▶ Продолжить</div><div class="st-tabs">${names.map(n => {
      const p = DATA.profiles[n], gid = (p && p.game) || "minecraft";
      const gm = GAMES.find(x => x.id === gid) || GAMES[0];
      const cnt = SEC_ORDER.reduce((s, k) => s + ((p && p[k]) || []).length, 0);
      return `<div class="st-tab${n === live ? " live" : ""}" onclick="startOpen(${JSON.stringify(n).replace(/"/g, "&quot;")})">
        ${gameIcon(gid, 40)}<div><div class="st-tab-name">${n === live ? "🔴 " : ""}${esc(n)}</div>
        <div class="st-tab-meta">${esc(gm.t)} · событий: ${cnt}</div></div>
        <button class="icon danger st-del" title="Удалить вкладку"
          onclick="event.stopPropagation(); startDelete(${JSON.stringify(n).replace(/"/g, "&quot;")})">🗑</button></div>`;
    }).join("")}</div>` : "";
  if (!TEMPLATES.length) {
    try { TEMPLATES = (await (await fetch("/api/templates", {cache: "no-store"})).json()).templates || []; } catch (e) {}
  }
  if (typeof migRender === "function") migRender();
  games.innerHTML = GAMES.map(x => {
    const n = TEMPLATES.filter(t => t.game === x.id).length;
    return `<div class="st-game" onclick="startNew('${x.id}')">${gameIcon(x.id, 56)}
      <div class="st-game-name">${esc(x.t)}</div>
      <div class="st-game-cnt">${n ? n + " " + plural(n, "шаблон", "шаблона", "шаблонов") : "с нуля"}</div></div>`;
  }).join("");
}

function startOpen(name) {
  selectProfile(name);
  switchView("events");
}

async function startNew(game) {
  await openNewTab();
  ntPickGame(game);
}

function startDelete(name) {
  if (DATA.connected && name === liveProfile()) {
    alert(`«${name}» сейчас работает в эфире. Сначала переведи эфир на другую вкладку или отключись.`);
    return;
  }
  if (!confirm(`Удалить вкладку «${name}» со всеми событиями?`)) return;
  delete DATA.profiles[name];
  if (activeProfile === name) activeProfile = Object.keys(DATA.profiles)[0] || null;
  if (!DATA.connected) DATA.config.active_profile = activeProfile || "";
  renderProfiles(); renderCards(); renderStart();
}

function ntCreateEmpty() {
  const typed = (document.getElementById("ntName") || {}).value;
  ntFinish(uniqueTabName(typed || GAME_DEFAULT_NAME[NT_GAME]), {});
}

function ntUseTemplate(i) {
  const tp = TEMPLATES[i];
  if (!tp) return;
  const typed = (document.getElementById("ntName") || {}).value;
  // своё название — если вписал; иначе — название шаблона
  const name = uniqueTabName(NT_NAME_TOUCHED && typed ? typed : tp.title);
  ntFinish(name, JSON.parse(JSON.stringify(tp.profile)));   // копия — шаблон не меняется
}

// ── Версия программы и «Что нового» ─────────────────────────
async function openChangelog() {
  const body = document.getElementById("changelogBody");
  body.innerHTML = '<div class="hint">Загружаю…</div>';
  document.getElementById("changelogModal").classList.remove("hidden");
  if (typeof updRender === "function") updRender();
  try {
    const d = await (await fetch("/api/version", {cache: "no-store"})).json();
    const fmt = s => { const [y, m, dd] = String(s || "").split("-"); return dd ? `${dd}.${m}.${y}` : s; };
    const list = d.changelog || [];
    body.innerHTML = `<div class="hint" style="margin-bottom:10px">Сейчас установлена <b>v${esc(d.version)}</b>
        от ${esc(fmt(d.date))}</div>` +
      (list.length ? list.map(v => `<div class="cl-ver">v${esc(v.version)}<span>${esc(fmt(v.date))}</span></div>
        <ul class="cl-list">${(v.changes || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul>`).join("")
        : '<div class="hint">Список изменений пуст.</div>');
  } catch (e) { body.innerHTML = '<div class="hint">✗ ' + esc(e.message) + '</div>'; }
}

function closeChangelog() { document.getElementById("changelogModal").classList.add("hidden"); }

// ── Автосохранение: любое изменение событий уходит на диск само ──
let SAVED_SNAP = null, DIRTY_AT = 0, SAVING = false;
function profilesSnap() { return JSON.stringify([DATA.profiles, activeProfile]); }
function markSaved() { if (DATA && DATA.profiles) SAVED_SNAP = profilesSnap(); DIRTY_AT = 0; }

async function autoSaveTick() {
  if (!DATA || !DATA.profiles || SAVING) return;
  const snap = profilesSnap();
  if (SAVED_SNAP === null) { SAVED_SNAP = snap; return; }
  const hint = document.getElementById("saveHint");
  if (snap === SAVED_SNAP) { DIRTY_AT = 0; return; }
  if (!DIRTY_AT) {
    DIRTY_AT = Date.now();
    if (hint) { hint.textContent = "● Сохраняю…"; hint.classList.add("pending"); }
    return;
  }
  if (Date.now() - DIRTY_AT < 600) return;   // ждём, пока закончишь печатать
  SAVING = true;
  try {
    const r1 = await fetch("/api/profiles", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({profiles: DATA.profiles})});
    if (!DATA.connected) DATA.config.active_profile = activeProfile;   // во время эфира эфир не трогаем
    await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({active_profile: DATA.config.active_profile || activeProfile})});
    if (r1 && r1.ok === false) throw new Error("сервер не принял");
    SAVED_SNAP = snap; DIRTY_AT = 0;
    if (hint) { hint.textContent = "✓ Сохранено"; hint.classList.remove("pending"); }
  } catch (e) {
    DIRTY_AT = Date.now();   // повторим попытку
    if (hint) hint.textContent = "✗ Не сохранилось — программа запущена?";
  } finally { SAVING = false; }
}
setInterval(autoSaveTick, 300);

// ── Импорт / Экспорт вкладок ─────────────────────────────────
async function exportProfile() {
  // Скачиваем ZIP с профилем и всеми медиафайлами (POST — надёжно с кириллицей)
  try {
    const r = await fetch("/api/export_zip", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ name: activeProfile })
    });
    if (!r.ok) { alert("Ошибка экспорта"); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "вкладка_" + activeProfile + ".zip";
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert("Ошибка экспорта: " + e.message);
  }
}

async function importProfile(event) {
  const file = event.target.files[0];
  if (!file) return;
  // Поддержка и ZIP (с медиа), и старого JSON
  if (file.name.toLowerCase().endsWith(".zip")) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch("/api/import_zip", { method: "POST", body: fd });
      const d = await r.json();
      if (d.ok) {
        await loadState();       // перезагружаем профили и медиа с сервера
        await loadMediaList();
        selectProfile(d.name);
        alert(`Вкладка "${d.name}" импортирована!\nМедиафайлов распаковано: ${d.media_count}`);
      } else {
        alert("Ошибка импорта: " + (d.error || "?"));
      }
    } catch (err) {
      alert("Ошибка импорта: " + err.message);
    }
    event.target.value = "";
    return;
  }
  // Старый формат — чистый JSON без медиа
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      let name = data.name || "Импорт";
      let profile = data.profile || data;
      let finalName = name, n = 2;
      while (DATA.profiles[finalName]) { finalName = name + " " + n; n++; }
      DATA.profiles[finalName] = {
        game: profile.game || "minecraft",
        chatcmds: profile.chatcmds || [], goals: profile.goals || [], panel: profile.panel || [],
        gifts: profile.gifts || [], likes: profile.likes || [],
        subs: profile.subs || [], follows: profile.follows || [], welcome: profile.welcome || []
      };
      activeProfile = finalName;
      renderProfiles();
      renderCards();
      alert(`Вкладка "${finalName}" импортирована! (без медиа — это старый JSON-формат)`);
    } catch (err) {
      alert("Ошибка импорта: " + err.message);
    }
  };
  reader.readAsText(file);
  event.target.value = "";
}

// ── Подключение / отключение ─────────────────────────────────
async function toggleConnect() {
  if (DATA.connected) {
    await fetch("/api/disconnect", {method:"POST"});
  } else {
    collectSettings();                    // ник мог быть введён только что — автосохранение ещё не успело
    await saveAll();
    const r = await fetch("/api/connect", {method:"POST"});
    const res = await r.json();
    if (!res.ok) alert(res.message);
  }
  setTimeout(refreshState, 1000);
}

async function refreshState() {
  const r = await fetch("/api/state");
  const s = await r.json();
  DATA.connected = s.connected;
  updateStatus();
}

// ── Настройки ────────────────────────────────────────────────
function fillSettings() {
  const c = DATA.config;
  document.getElementById("cfg_tiktok").value = c.tiktok_username || "";
  document.getElementById("cfg_host").value = c.servertap_host || "127.0.0.1";
  document.getElementById("cfg_port").value = c.servertap_port || 4567;
  document.getElementById("cfg_pass").value = c.servertap_key || "";
  document.getElementById("cfg_nick").value = c.minecraft_nick || "";
  document.getElementById("cfg_tls").checked = !!c.use_tls;
  document.getElementById("cfg_rcon_port").value = c.rcon_port || 25575;
  document.getElementById("cfg_rcon_pass").value = c.rcon_password || "";
  setTransport(c.mc_transport === "rcon" ? "rcon" : "servertap", true);
  for (const g of ["ark", "rust", "palworld", "zomboid", "7dtd"]) {
    document.getElementById(`cfg_${g}_host`).value = c[`${g}_host`] || "";
    document.getElementById(`cfg_${g}_port`).value = c[`${g}_port`] || "";
    document.getElementById(`cfg_${g}_pass`).value = c[`${g}_password`] || "";
    if (g !== "palworld") document.getElementById(`cfg_${g}_player`).value = c[`${g}_player`] || "";
  }
  document.getElementById("cfg_palworld_rest").value = c.palworld_rest_port || "";
  sgShow(SERVER_GAMES[curGame()] ? curGame() : SG_CUR);
  document.getElementById("cfg_tts_on").checked = !!c.tts_enabled;
  const chk = (id, v) => { const el = document.getElementById(id); if (el) el.checked = v; };
  const val2 = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
  chk("cfg_tts_guard", c.tts_guard !== false);
  val2("cfg_tts_profanity", c.tts_profanity || "beep");
  val2("cfg_tts_bad_words", c.tts_bad_words || "");
  chk("cfg_tts_skip_junk", c.tts_skip_junk !== false);
  val2("cfg_tts_cooldown", c.tts_user_cooldown ?? 8);
  chk("cfg_tts_dupes", c.tts_skip_dupes !== false);
  val2("cfg_tts_maxq", c.tts_max_queue ?? 5);
  val2("cfg_tts_block", c.tts_block_list || "");
  chk("cfg_voice_on", c.voice_cmds_on !== false);
  val2("cfg_voice_reset", c.voice_reset_cmd || "!сброс");
  chk("cfg_voice_confirm", c.voice_cmd_confirm !== false);
  if (typeof ttsTopRender === "function") ttsTopRender();
  document.getElementById("cfg_tts_voice").value = c.tts_voice || "ru-RU-DmitryNeural";
  document.getElementById("cfg_fish_key").value = c.fish_api_key || "";
  document.getElementById("cfg_fish_model").value = c.fish_model || "s2.1-pro-free";
  vpSetProvider(vpProviderOf(c.tts_voice || "ru-RU-DmitryNeural"));
  document.getElementById("cfg_tts_vol").value = c.tts_volume ?? 100;
  document.getElementById("tts_vol_label").textContent = c.tts_volume ?? 100;
  document.getElementById("cfg_tts_name").checked = c.tts_read_name !== false;
  document.getElementById("cfg_tts_local").checked = c.tts_play_local !== false;
  document.getElementById("cfg_tts_filter").value = c.tts_filter_mode || "all";
  document.getElementById("cfg_tts_list").value = c.tts_filter_list || "";
  document.getElementById("cfg_tts_coins").value = c.tts_filter_coins ?? 1;
  document.getElementById("cfg_tts_likes").value = c.tts_filter_likes ?? 100;
  ttsFilterUI();
  updSxDots();
}

function ttsFilterUI() {
  const m = document.getElementById("cfg_tts_filter").value;
  document.getElementById("tts_f_list").style.display = (m === "list") ? "" : "none";
  document.getElementById("tts_f_coins").style.display = (m === "gifters") ? "" : "none";
  document.getElementById("tts_f_likes").style.display = (m === "likers") ? "" : "none";
  document.getElementById("tts_f_hint").style.display = (m === "all" || m === "list") ? "none" : "";
}

function collectSettings() {
  DATA.config.tiktok_username = document.getElementById("cfg_tiktok").value.trim();
  DATA.config.servertap_host = document.getElementById("cfg_host").value.trim();
  DATA.config.servertap_port = parseInt(document.getElementById("cfg_port").value) || 4567;
  DATA.config.servertap_key = document.getElementById("cfg_pass").value;
  DATA.config.minecraft_nick = document.getElementById("cfg_nick").value.trim();
  DATA.config.use_tls = document.getElementById("cfg_tls").checked;
  DATA.config.mc_transport = document.getElementById("cfg_transport").value === "rcon" ? "rcon" : "servertap";
  DATA.config.rcon_port = parseInt(document.getElementById("cfg_rcon_port").value) || 25575;
  DATA.config.rcon_password = document.getElementById("cfg_rcon_pass").value;
  for (const g of ["ark", "rust", "palworld", "zomboid", "7dtd"]) {
    DATA.config[`${g}_host`] = document.getElementById(`cfg_${g}_host`).value.trim();
    DATA.config[`${g}_port`] = parseInt(document.getElementById(`cfg_${g}_port`).value) || ({ark: 27020, rust: 28016, palworld: 25575, zomboid: 27015, "7dtd": 8081})[g];
    DATA.config[`${g}_password`] = document.getElementById(`cfg_${g}_pass`).value;
    if (g !== "palworld") DATA.config[`${g}_player`] = document.getElementById(`cfg_${g}_player`).value.trim();
  }
  DATA.config.palworld_rest_port = parseInt(document.getElementById("cfg_palworld_rest").value) || 8212;
  DATA.config.tts_enabled = document.getElementById("cfg_tts_on").checked;
  const gchk = id => { const el = document.getElementById(id); return el ? el.checked : true; };
  const gval = (id, d) => { const el = document.getElementById(id); return el ? el.value : d; };
  DATA.config.tts_guard = gchk("cfg_tts_guard");
  DATA.config.tts_profanity = gval("cfg_tts_profanity", "beep");
  DATA.config.tts_bad_words = gval("cfg_tts_bad_words", "");
  DATA.config.tts_skip_junk = gchk("cfg_tts_skip_junk");
  DATA.config.tts_user_cooldown = Math.max(0, parseFloat(gval("cfg_tts_cooldown", 8)) || 0);
  DATA.config.tts_skip_dupes = gchk("cfg_tts_dupes");
  DATA.config.tts_max_queue = Math.max(0, parseInt(gval("cfg_tts_maxq", 5)) || 0);
  DATA.config.tts_block_list = gval("cfg_tts_block", "");
  DATA.config.voice_cmds_on = gchk("cfg_voice_on");
  DATA.config.voice_reset_cmd = (gval("cfg_voice_reset", "!сброс") || "!сброс").trim();
  DATA.config.voice_cmd_confirm = gchk("cfg_voice_confirm");
  if (typeof ttsTopRender === "function") ttsTopRender();
  DATA.config.tts_voice = document.getElementById("cfg_tts_voice").value;
  DATA.config.fish_api_key = document.getElementById("cfg_fish_key").value.trim();
  DATA.config.fish_model = document.getElementById("cfg_fish_model").value;
  DATA.config.tts_volume = parseInt(document.getElementById("cfg_tts_vol").value) || 100;
  DATA.config.tts_read_name = document.getElementById("cfg_tts_name").checked;
  DATA.config.tts_play_local = document.getElementById("cfg_tts_local").checked;
  DATA.config.tts_filter_mode = document.getElementById("cfg_tts_filter").value;
  DATA.config.tts_filter_list = document.getElementById("cfg_tts_list").value;
  DATA.config.tts_filter_coins = parseInt(document.getElementById("cfg_tts_coins").value) || 1;
  DATA.config.tts_filter_likes = parseInt(document.getElementById("cfg_tts_likes").value) || 100;
}

async function saveSettings() { await saveCfgNow(); }   // совместимость

// ── Настройки: разделы слева, автосохранение ──────────────────
const SX_META = {
  tiktok: ["🎵 TikTok", "Откуда программа берёт события стрима"],
  mc:     ["🎮 Сервер Minecraft", "Куда отправлять команды"],
  servers:["🖥 Серверные игры", "ARK, Rust и Palworld — на своём сервере"],
  tts:    ["🔊 Озвучка чата", "Чтение сообщений зрителей вслух"],
  voice:  ["🗣 Голос", "Каким голосом читать чат"],
  filter: ["🛡 Кого озвучивать", "Фильтр, чтобы не читать спам"],
  guard:  ["🧹 Защита от спама", "Мат, растяжки, флуд и повторы не попадут в озвучку"],
  vvoices:["🎭 Голоса зрителей", "Зритель пишет команду — и его читают выбранным голосом"],
};

function sxGo(s) {
  document.querySelectorAll("#sxNav .sx-it").forEach(it => it.classList.toggle("active", it.dataset.s === s));
  document.querySelectorAll("#view-settings .sx-sec").forEach(sec => sec.classList.toggle("hidden", sec.dataset.s !== s));
  document.getElementById("sxTitle").textContent = SX_META[s][0];
  document.getElementById("sxSub").textContent = SX_META[s][1];
  if (s === "vvoices" && typeof vcRender === "function") { vcRender(); vvLoad(); roleRender(); vvRecentLoad(); }
  if (s === "guard" && typeof vvLoad === "function") vvLoad();
}

function setTransport(v, silent) {
  document.getElementById("cfg_transport").value = v;
  document.getElementById("sxMain").dataset.tr = v;
  document.querySelectorAll("#sxTransport .sx-seg-b").forEach(b => b.classList.toggle("active", b.dataset.v === v));
  const hint = document.getElementById("rconHint");
  if (hint) hint.textContent = "";
  if (!silent) scheduleCfgSave();
}

// Зелёная точка у раздела — всё заполнено; жёлтая — чего-то не хватает
let SG_CUR = "ark";
function sgShow(g) {
  SG_CUR = g;
  document.querySelectorAll("#sgSeg .sx-seg-b").forEach(b => b.classList.toggle("active", b.dataset.g === g));
  document.querySelectorAll("#view-settings .sg-block").forEach(b => b.classList.toggle("on", b.dataset.g === g));
}

async function pingGame(g) {
  const el = document.getElementById("sgPing_" + g);
  if (el) { el.textContent = "Проверяю…"; el.style.color = ""; }
  await saveCfgNow();
  try {
    const r = await fetch("/api/game/ping", {method: "POST", headers: {"Content-Type": "application/json"},
                          body: JSON.stringify({game: g})});
    const d = await r.json();
    if (el) { el.textContent = (d.ok ? "✓ " : "✗ ") + d.message; el.style.color = d.ok ? "var(--green)" : "var(--red)"; }
  } catch (e) { if (el) el.textContent = "✗ " + e.message; }
}

function updSxDots() {
  const val = id => ((document.getElementById(id) || {}).value || "");
  const chk = id => !!(document.getElementById(id) || {}).checked;
  const set = (s, cls) => { const d = document.getElementById("sxDot_" + s);
                            if (d) d.className = "sx-dot" + (cls ? " " + cls : ""); };
  set("tiktok", val("cfg_tiktok").trim() ? "on" : "warn");
  const rcon = val("cfg_transport") === "rcon";
  set("mc", val("cfg_host").trim() && (rcon ? val("cfg_rcon_pass") : val("cfg_port")) ? "on" : "warn");
  set("tts", chk("cfg_tts_on") ? "on" : "");
  set("voice", val("cfg_tts_voice").startsWith("fish:") && !val("cfg_fish_key").trim() ? "warn" : "on");
  set("filter", val("cfg_tts_filter") !== "all" ? "on" : "");
  set("servers", ["ark", "rust", "palworld"].some(g => val(`cfg_${g}_host`).trim() && val(`cfg_${g}_pass`)) ? "on" : "");
}

let CFG_SAVE_T = null;
function scheduleCfgSave() {
  const hint = document.getElementById("cfgSaveHint");
  if (hint) { hint.textContent = "● Сохраняю…"; hint.classList.add("pending"); }
  clearTimeout(CFG_SAVE_T);
  CFG_SAVE_T = setTimeout(saveCfgNow, 600);
  updSxDots();
}

async function saveCfgNow() {
  clearTimeout(CFG_SAVE_T);
  collectSettings();
  const hint = document.getElementById("cfgSaveHint");
  try {
    const r = await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"},
                                          body: JSON.stringify(DATA.config)});
    if (r && r.ok === false) throw new Error();
    if (hint) { hint.textContent = "✓ Сохранено"; hint.classList.remove("pending"); }
  } catch (e) {
    if (hint) hint.textContent = "✗ Не сохранилось — программа запущена?";
  }
}

// любое изменение во вкладке настроек сохраняется само
(function () {
  const v = document.getElementById("view-settings");
  if (!v) return;
  const h = e => {
    const id = e.target && e.target.id;
    if (id === "fishQuery" || id === "fishLang") return;   // поиск голосов — не настройка
    scheduleCfgSave();
  };
  v.addEventListener("input", h);
  v.addEventListener("change", h);
})();

async function testRcon() {
  collectSettings();
  const hint = document.getElementById("rconHint");
  hint.textContent = "Проверяю...";
  hint.style.color = "var(--text-dim)";
  const r = await fetch("/api/test_rcon", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(DATA.config)
  });
  const res = await r.json();
  hint.textContent = res.message;
  hint.style.color = res.ok ? "var(--green)" : "var(--red)";
}

// ── Тест действия ────────────────────────────────────────────
async function testAction(idx) {
  collectSettings();
  await fetch("/api/config", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(DATA.config)
  });
  const action = curList()[idx];
  // Для приветствия — сохраняем и симулируем первое сообщение от этого ника
  if (activeSection === "welcome") {
    if (!(action.nick || "").trim()) { alert("Сначала впиши ник зрителя в TikTok!"); return; }
    await saveAll();
    const nick = action.nick.trim();
    await fetch("/api/simulate", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ kind: "welcome", user: nick })
    });
  } else {
    await fetch("/api/test_action", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ action, count: 1, user: "ТестЗритель" })
    });
  }
  if (action.media_file || action.sound_file) {
    const btn = event.target;
    const old = btn.textContent;
    btn.textContent = "✓ Отправлено на оверлей";
    setTimeout(() => btn.textContent = old, 2000);
  }
}

// ── Симуляция события ────────────────────────────────────────
function simulateMenu() {
  const kind = prompt("Что симулировать? Напиши: подарок / лайк / подписка / фоллов");
  if (!kind) return;
  let payload = { user: "ТестЗритель" };
  const k = kind.toLowerCase();
  if (k.includes("подар")) {
    payload.kind = "gift";
    payload.name = prompt("Название подарка:", "Роза") || "Роза";
    payload.count = parseInt(prompt("Количество:", "1")) || 1;
    payload.diamonds = 10;
  } else if (k.includes("лайк")) {
    payload.kind = "like";
    payload.count = parseInt(prompt("Сколько лайков:", "100")) || 100;
  } else if (k.includes("подпис")) {
    payload.kind = "sub";
  } else if (k.includes("фолл")) {
    payload.kind = "follow";
  } else { return; }
  fetch("/api/simulate", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });
}

// ── Лог в реальном времени ───────────────────────────────────
let logTimer = null;
function startLogPolling() {
  if (logTimer) return;
  pollLog();
  logTimer = setInterval(pollLog, 1000);
}
function stopLogPolling() {
  if (logTimer) { clearInterval(logTimer); logTimer = null; }
}
async function pollLog() {
  const r = await fetch("/api/log");
  const d = await r.json();
  const box = document.getElementById("logBox");
  box.innerHTML = d.log.map(e =>
    `<div class="log-line ${esc(e.kind)}"><span class="lt">${e.time}</span>
     <span class="lk">${esc(e.kind)}</span> ${esc(e.text)}</div>`
  ).join("");
  box.scrollTop = box.scrollHeight;
  renderSeenGifts(d.seen_gifts || []);
}

function renderSeenGifts(gifts) {
  const box = document.getElementById("seenGifts");
  if (!gifts.length) {
    box.innerHTML = '<div class="hint">Пока подарков не было. Включись в эфир — они появятся здесь с точным названием и ID.</div>';
    return;
  }
  box.innerHTML = gifts.map(g => `
    <div class="seen-gift">
      <div class="sg-info">
        <span class="sg-name">${esc(g.name)}</span>
        <span class="sg-meta">ID: ${esc(g.id||"—")} · получено ${g.count}×</span>
      </div>
      <button class="small" onclick="addSeenGift('${esc(g.name)}','${esc(g.id||"")}')">+ В подарки</button>
    </div>`).join("");
}

function addSeenGift(name, id) {
  // Переключаемся на вкладку событий, секцию подарков, добавляем карточку
  switchView("events");
  switchSection("gifts");
  const a = { name: name, gift_id: id, commands: [""], delays: [0], random: false, repeat_by_count: false };
  curList().push(a);
  renderCards();
  alert(`Подарок «${name}» добавлен! Впиши команду и сохрани.`);
}


// ── Выбор голоса озвучки: провайдеры, карточки, предпрослушка ──
const VOICES = {
  gt: [
    {v:"gt:ru", name:"Русский",     desc:"Голос Google-переводчика. Простой и надёжный, работает без библиотек", lang:"ru"},
    {v:"gt:uk", name:"Українська",  desc:"Украинский голос Google", lang:"uk"},
    {v:"gt:kk", name:"Қазақша",     desc:"Казахский голос Google", lang:"kk"},
    {v:"gt:en", name:"English",     desc:"Английский голос Google", lang:"en"},
    {v:"gt:de", name:"Deutsch",     desc:"Немецкий голос Google", lang:"de"},
    {v:"gt:ja", name:"日本語",       desc:"Японский голос Google", lang:"ja"},
  ],
  edge: [
    {v:"ru-RU-DmitryNeural",   name:"Дмитрий",  desc:"Мужской нейроголос, спокойный и чёткий", lang:"ru"},
    {v:"ru-RU-SvetlanaNeural", name:"Светлана", desc:"Женский нейроголос, мягкий и дружелюбный", lang:"ru"},
    {v:"uk-UA-OstapNeural",    name:"Остап",    desc:"Мужской украинский нейроголос", lang:"uk"},
    {v:"uk-UA-PolinaNeural",   name:"Полина",   desc:"Женский украинский нейроголос", lang:"uk"},
    {v:"kk-KZ-DauletNeural",   name:"Даулет",   desc:"Мужской казахский нейроголос", lang:"kk"},
    {v:"kk-KZ-AigulNeural",    name:"Айгуль",   desc:"Женский казахский нейроголос", lang:"kk"},
    {v:"en-US-GuyNeural",      name:"Guy",      desc:"Мужской американский нейроголос", lang:"en"},
    {v:"en-US-JennyNeural",    name:"Jenny",    desc:"Женский американский нейроголос", lang:"en"},
    {v:"de-DE-ConradNeural",   name:"Conrad",   desc:"Мужской немецкий нейроголос", lang:"de"},
    {v:"ja-JP-NanamiNeural",   name:"Nanami",   desc:"Женский японский нейроголос", lang:"ja"},
  ],
};
let vpProvider = "edge";
let FISH_RESULTS = [];
let vpAudio = null, vpPlayingKey = "";

function vpProviderOf(voice) {
  if (String(voice).startsWith("gt:")) return "gt";
  if (String(voice).startsWith("fish:")) return "fish";
  return "edge";
}

// Режим «выбрать голос для…»: то же окно голосов открывается поверх программы
let VP_PICK = null;          // {cur, title, label, allowDefault, onPick}
let VP_HOME = null;          // куда вернуть блок голосов после выбора
function vpCurVoice() { return VP_PICK ? (VP_PICK.cur || "") : document.getElementById("cfg_tts_voice").value; }

function voiceTitle(v) {
  const t = (DATA.config.voice_titles || {})[v];
  if (t) return t;
  if (v === DATA.config.tts_voice && DATA.config.fish_voice_title) return DATA.config.fish_voice_title;
  return "";
}

// «Microsoft · Светлана», «Google · Русский», «Fish · Меллстрой»
function voiceLabel(v) {
  if (!v) return "как у всех";
  const p = vpProviderOf(v);
  if (p === "fish") return "Fish · " + (voiceTitle(v) || "голос " + v.slice(5, 11));
  const o = (VOICES[p] || []).find(x => x.v === v);
  return (p === "gt" ? "Google · " : "Microsoft · ") + (o ? o.name : v);
}

// кнопка выбора голоса — для команд, ролей, особенных зрителей
function voiceBtnHtml(v, onclick, emptyText) {
  const p = v ? vpProviderOf(v) : "";
  const icon = !v ? "👥" : p === "fish" ? "🐟" : p === "gt" ? "⚡" : "🎙";
  return `<button class="vbtn${v ? "" : " empty"}" onclick="${onclick}" title="Выбрать голос">
    <span class="vbtn-i">${icon}</span><span class="vbtn-t">${esc(v ? voiceLabel(v) : (emptyText || "выбрать голос"))}</span><span class="vbtn-a">▾</span></button>`;
}

function openVoicePick(opts) {
  VP_PICK = opts;
  const vp = document.querySelector(".vp");
  if (!VP_HOME) VP_HOME = {parent: vp.parentNode, next: vp.nextSibling};
  document.getElementById("vpModalSlot").appendChild(vp);
  document.getElementById("vpmTitle").textContent = "Голос для " + (opts.label || "выбора");
  document.getElementById("vpmDefault").classList.toggle("hidden", !opts.allowDefault);
  document.getElementById("voicePickModal").classList.remove("hidden");
  vpSetProvider(opts.cur ? vpProviderOf(opts.cur) : (vpProvider || "edge"));
}

function closeVoicePick() {
  document.getElementById("voicePickModal").classList.add("hidden");
  if (vpAudio) { try { vpAudio.pause(); } catch (e) {} vpAudio = null; vpPlayingKey = ""; }
  const vp = document.querySelector(".vp");
  if (VP_HOME && vp) VP_HOME.parent.insertBefore(vp, VP_HOME.next);
  VP_PICK = null;
  vpRender();
}

function vpPickDefault() {
  const cb = VP_PICK && VP_PICK.onPick;
  closeVoicePick();
  if (cb) cb("", "");
}

function vpSetProvider(p) {
  vpProvider = p;
  document.querySelectorAll("#vpTabs .vp-tab").forEach(t =>
    t.classList.toggle("active", t.dataset.p === p));
  document.getElementById("vpFish").classList.toggle("hidden", p !== "fish");
  vpRender();
  if (p === "fish") {
    fishRenderTags();
    if (!FISH_RESULTS.length && !FISH_LOADING) fishSearch();   // как на сайте — популярные сразу
  }
  fishUpdMore();
}

function vpCardHtml(o) {
  const sel = (o.v === vpCurVoice());
  const ava = (o.cover || o.coverAlt)
    ? `<img class="vp-ava" src="${esc(o.cover || o.coverAlt)}" alt="" data-alt="${esc(o.cover ? (o.coverAlt || "") : "")}"
           data-letter="${esc((o.name || "?").charAt(0).toUpperCase())}" onerror="vpAvaFail(this)">`
    : `<div class="vp-ava">${esc((o.name || "?").charAt(0).toUpperCase())}</div>`;
  const langs = (o.langs || [o.lang]).filter(Boolean)
    .map(l => `<span class="vp-lang">${esc(l)}</span>`).join("");
  const meta = o.uses ? `<span class="vp-meta">▶ ${o.uses > 999 ? Math.round(o.uses/1000) + "k" : o.uses}</span>` : "";
  const key = esc(o.v);
  return `<div class="vp-card${sel ? " sel" : ""}" onclick="vpSelect('${key}', '${esc(o.name).replace(/'/g,"&#39;")}')">
    <div class="vp-top">${ava}<div class="vp-name" title="${esc(o.name)}">${esc(o.name)}</div></div>
    <div class="vp-desc">${esc(o.desc || "")}</div>
    <div class="vp-bot">${langs}${sel ? '<span class="vp-sel">Выбран</span>' : ""}${meta}
      <button class="vp-play${vpPlayingKey === o.v ? " on" : ""}" title="Послушать"
              onclick="event.stopPropagation(); vpPreview('${key}', '${esc(o.sample || "")}', this)">${vpPlayingKey === o.v ? "■" : "▶"}</button>
    </div>
  </div>`;
}

function vpRender() {
  const grid = document.getElementById("vpGrid");
  if (!grid) return;
  const cur = vpCurVoice();
  // строка «Выбран: …»
  let curName = cur;
  const all = [...VOICES.gt, ...VOICES.edge];
  const found = all.find(x => x.v === cur);
  if (found) curName = found.name + (cur.startsWith("gt:") ? " (Google)" : " (Edge)");
  else if (cur.startsWith("fish:")) curName = (DATA.config.fish_voice_title || "голос Fish Audio") + " (Fish Audio)";
  if (VP_PICK) curName = cur ? voiceLabel(cur) : "как у всех";
  document.getElementById("vpCurrent").innerHTML = VP_PICK
    ? `Сейчас у ${esc(VP_PICK.label || "")}: <b>${esc(curName)}</b> — нажми на голос, чтобы поставить`
    : `Сейчас озвучивает: <b>${esc(curName)}</b>`;

  let list;
  if (vpProvider === "fish") {
    list = FISH_RESULTS.map(m => ({v: "fish:" + m.id, name: m.title, desc: m.description,
      langs: m.languages, cover: m.cover, coverAlt: m.cover_alt, sample: m.sample, uses: m.uses}));
    // выбранный голос Fish всегда виден, даже если его нет в результатах поиска
    if (cur.startsWith("fish:") && !list.some(x => x.v === cur)) {
      list.unshift({v: cur, name: (VP_PICK ? voiceTitle(cur) : DATA.config.fish_voice_title) || "Выбранный голос",
                    desc: "Твой текущий голос из библиотеки Fish Audio", langs: []});
    }
    document.getElementById("vpHint").textContent = list.length ? "" :
      "Найди голос через поиск выше — например «диктор», «аниме», «бас» или имя персонажа.";
  } else {
    list = VOICES[vpProvider];
    document.getElementById("vpHint").textContent = "";
  }
  grid.innerHTML = list.map(vpCardHtml).join("");
  if (typeof updSxDots === "function") updSxDots();
}

async function vpSelect(voice, title) {
  if (voice.startsWith("fish:") && title) {                  // запоминаем имя голоса Fish — для подписей везде
    DATA.config.voice_titles = DATA.config.voice_titles || {};
    DATA.config.voice_titles[voice] = title;
  }
  if (VP_PICK) {                                             // выбор «для команды / роли / зрителя»
    const cb = VP_PICK.onPick;
    closeVoicePick();
    if (cb) cb(voice, title);
    if (typeof scheduleCfgSave === "function") scheduleCfgSave();
    return;
  }
  document.getElementById("cfg_tts_voice").value = voice;
  DATA.config.tts_voice = voice;
  if (voice.startsWith("fish:")) DATA.config.fish_voice_title = title;
  vpRender();
  // применяем сразу, как в видео — без кнопки «Сохранить»
  try {
    await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({tts_voice: voice, fish_voice_title: DATA.config.fish_voice_title || ""})});
  } catch (e) {}
}

// Обложка не загрузилась — пробуем запасной адрес, и только потом показываем букву
function vpAvaFail(img) {
  const alt = img.dataset.alt;
  if (alt && img.getAttribute("src") !== alt) { img.dataset.alt = ""; img.src = alt; return; }
  const d = document.createElement("div");
  d.className = "vp-ava";
  d.textContent = img.dataset.letter || "?";
  img.replaceWith(d);
}

async function vpPreview(voice, sampleUrl, btn) {
  // повторный клик по играющему — стоп
  if (vpAudio && vpPlayingKey === voice) {
    vpAudio.pause(); vpAudio = null; vpPlayingKey = ""; vpRender(); return;
  }
  if (vpAudio) { vpAudio.pause(); vpAudio = null; }
  vpPlayingKey = voice; vpRender();
  let url = sampleUrl;
  if (!url) {
    const hint = document.getElementById("vpHint");
    hint.textContent = "Генерирую пример…";
    try {
      const r = await fetch("/api/tts_preview", {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({voice})});
      const d = await r.json();
      if (!d.ok) { hint.textContent = "✗ " + d.error; vpPlayingKey = ""; vpRender(); return; }
      url = d.url; hint.textContent = "";
    } catch (e) { hint.textContent = "✗ " + e.message; vpPlayingKey = ""; vpRender(); return; }
  }
  vpAudio = new Audio(url);
  vpAudio.volume = Math.max(0, Math.min(1, (parseInt(document.getElementById("cfg_tts_vol").value) || 100) / 100));
  const done = () => { vpAudio = null; vpPlayingKey = ""; vpRender(); };
  const fail = () => {
    done();
    if (sampleUrl && url === sampleUrl) {           // готовый пример не загрузился — генерируем свой
      const hint = document.getElementById("vpHint");
      if (hint) hint.textContent = "Пример с сайта не загрузился — генерирую свой…";
      vpPreview(voice, "", btn);
    }
  };
  vpAudio.onended = done; vpAudio.onerror = fail;
  vpAudio.play().catch(fail);
}

// Каталог Fish Audio — как страница «Открытие» на сайте: популярные сразу, дальше по кнопке
const FISH_TAGS = [["", "Все"], ["male", "Мужские"], ["female", "Женские"], ["narration", "Дикторы"],
                   ["anime", "Аниме"], ["meme", "Мемы"], ["game", "Игры"], ["character", "Персонажи"]];
// если по английскому тегу пусто — ищем по русскому слову в названии
const FISH_TAG_WORDS = {meme: "мем", game: "игр", anime: "аниме", narration: "диктор", character: "персонаж"};
let FISH_WORD = "";
let FISH_PAGE = 1, FISH_TOTAL = 0, FISH_TAG = "", FISH_LOADING = false;

function fishRenderTags() {
  const box = document.getElementById("fishTags");
  if (!box) return;
  box.innerHTML = FISH_TAGS.map(([t, n]) =>
    `<span class="fish-tag${t === FISH_TAG ? " active" : ""}" onclick="fishSetTag('${t}')">${n}</span>`).join("");
}

function fishSetTag(t) { FISH_TAG = t; fishRenderTags(); fishSearch(); }

async function fishLoad(page) {
  const q = document.getElementById("fishQuery").value.trim() || FISH_WORD;
  const lang = document.getElementById("fishLang").value;
  const sort = (document.getElementById("fishSort") || {}).value || "task_count";
  const tag = FISH_WORD ? "" : FISH_TAG;
  const url = `/api/fish_search?q=${encodeURIComponent(q)}&lang=${encodeURIComponent(lang)}` +
              `&sort=${sort}&tag=${encodeURIComponent(tag)}&page=${page}&size=24`;
  const r = await fetch(url, {cache: "no-store"});
  return r.json();
}

function fishUpdMore() {
  const b = document.getElementById("fishMore");
  if (b) b.classList.toggle("hidden", !(vpProvider === "fish" && FISH_RESULTS.length && FISH_RESULTS.length < FISH_TOTAL));
}

async function fishSearch() {
  if (FISH_LOADING) return;
  const hint = document.getElementById("vpHint");
  FISH_LOADING = true;
  await fishSaveCfg();
  hint.textContent = "Загружаю голоса…";
  try {
    FISH_WORD = "";
    let d = await fishLoad(1);
    let note = "";
    const word = FISH_TAG_WORDS[FISH_TAG];
    if (d.ok && !(d.items || []).length && word && !document.getElementById("fishQuery").value.trim()) {
      FISH_WORD = word;                                   // по тегу пусто — пробуем по слову
      d = await fishLoad(1);
      note = ` (по категории пусто — показал поиск «${word}»)`;
    }
    if (!d.ok) { FISH_RESULTS = []; FISH_TOTAL = 0; vpRender(); hint.textContent = "✗ " + d.error; return; }
    FISH_PAGE = 1;
    FISH_TOTAL = d.total || 0;
    FISH_RESULTS = d.items || [];
    vpRender();
    hint.textContent = FISH_RESULTS.length
      ? `Голосов: ${FISH_TOTAL.toLocaleString("ru")}${note}. Клик по карточке — выбрать, ▶ — послушать.`
      : "Ничего не нашлось — попробуй другое слово, категорию или «все языки».";
  } catch (e) { hint.textContent = "✗ " + e.message; }
  finally { FISH_LOADING = false; fishUpdMore(); }
}

async function fishMore() {
  if (FISH_LOADING) return;
  const hint = document.getElementById("vpHint");
  FISH_LOADING = true;
  try {
    const d = await fishLoad(FISH_PAGE + 1);
    if (!d.ok) { hint.textContent = "✗ " + d.error; return; }
    FISH_PAGE += 1;
    const have = new Set(FISH_RESULTS.map(m => m.id));
    FISH_RESULTS = FISH_RESULTS.concat((d.items || []).filter(m => !have.has(m.id)));
    vpRender();
    hint.textContent = `Показано ${FISH_RESULTS.length} из ${FISH_TOTAL.toLocaleString("ru")}.`;
  } catch (e) { hint.textContent = "✗ " + e.message; }
  finally { FISH_LOADING = false; fishUpdMore(); }
}

async function fishSaveCfg() {
  DATA.config.fish_api_key = document.getElementById("cfg_fish_key").value.trim();
  DATA.config.fish_model = document.getElementById("cfg_fish_model").value;
  try {
    await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({fish_api_key: DATA.config.fish_api_key, fish_model: DATA.config.fish_model})});
  } catch (e) {}
}

// ── Тест озвучки ─────────────────────────────────────────────
async function testTTS() {
  collectSettings();
  const hint = document.getElementById("ttsHint");
  hint.textContent = "Генерирую...";
  hint.style.color = "var(--text-dim)";
  try {
    const r = await fetch("/api/tts_test", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        tts_enabled: DATA.config.tts_enabled, tts_voice: DATA.config.tts_voice,
        tts_volume: DATA.config.tts_volume, tts_read_name: DATA.config.tts_read_name,
        user: "Стример", text: "Привет! Это проверка озвучки чата."
      })
    });
    const d = await r.json();
    hint.textContent = (d.ok ? "✓ " : "✗ ") + (d.message || (d.ok ? "Готово" : "Ошибка"));
    hint.style.color = d.ok ? "var(--green)" : "var(--red)";
  } catch(e) { hint.textContent = "Ошибка: " + e.message; hint.style.color = "var(--red)"; }
}

// ── Диагностика озвучки ──────────────────────────────────────
async function diagTTS() {
  collectSettings();
  await fetch("/api/config", { method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(DATA.config) });
  const box = document.getElementById("ttsDiag");
  box.innerHTML = '<div class="hint">Проверяю по шагам (до 20 секунд)...</div>';
  try {
    const r = await fetch("/api/tts_diag", {cache:"no-store"});
    const d = await r.json();
    box.innerHTML = d.report.map(x => `
      <div style="padding:6px 10px;margin-bottom:6px;border-radius:8px;font-size:13px;
                  background:${x.ok?'rgba(52,211,153,0.1)':'rgba(248,113,113,0.12)'};
                  border:1px solid ${x.ok?'rgba(52,211,153,0.4)':'rgba(248,113,113,0.5)'}">
        ${x.ok?'✅':'❌'} <b>${x.step}</b> — ${x.detail}
      </div>`).join("");
  } catch(e) {
    box.innerHTML = '<div class="hint" style="color:var(--red)">Ошибка диагностики: '+e.message+'</div>';
  }
}


// ── Панель стримера: таймер, случайные события, кнопки ──────
let RND_ITEMS = [];

let PANEL_SAVE_T = null;
function schedulePanelSave() {
  document.querySelectorAll("[data-panelsave]").forEach(h => {
    h.textContent = "● Сохраняю…"; h.classList.add("pending"); });
  clearTimeout(PANEL_SAVE_T);
  PANEL_SAVE_T = setTimeout(async () => {
    try {
      await savePanelCfg(true);
      document.querySelectorAll("[data-panelsave]").forEach(h => {
        h.textContent = "✓ Сохранено"; h.classList.remove("pending"); });
    } catch (e) {
      document.querySelectorAll("[data-panelsave]").forEach(h => h.textContent = "✗ Не сохранилось");
    }
  }, 600);
}

// любое изменение на панели (таймер, случайные события, витрина) сохраняется само
(function () {
  const v = document.getElementById("view-panel");
  if (!v) return;
  const h = () => { if (typeof updPanelStatus === "function") updPanelStatus(); schedulePanelSave(); };
  v.addEventListener("input", h);
  v.addEventListener("change", h);
})();

function togglePanelCfg(id, btn) {
  const el = document.getElementById(id);
  if (!el) return;
  const open = el.classList.toggle("hidden") === false;
  if (btn) btn.classList.toggle("cfg-open", open);
  if (open) el.scrollIntoView({behavior: "smooth", block: "nearest"});
  if (id === "scSettings" && typeof scLiveToggle === "function") scLiveToggle(open);
}

function scTransUI() {
  const m = document.getElementById("sc_anim");
  if (!m) return;
  const v = m.value;
  // появление — для сетки и статичного списка; движение — для прокрутки и бегущей строки
  document.getElementById("fld_trans_grid").classList.toggle("hidden", v === "scroll" || v === "marquee");
  document.getElementById("fld_motion").classList.toggle("hidden", v === "grid" || v === "none");
}

function updPanelStatus() {
  const el = id => document.getElementById(id);
  if (!el("rndStatus")) return;
  const on = el("rnd_on") ? el("rnd_on").checked : false;
  const n = RND_ITEMS.filter(i => (i.command||"").trim() || i.media_file || i.sound_file).length;
  el("rndStatus").textContent = on
    ? `включены · ${n} шт · раз в ${el("rnd_interval").value || "?"} сек`
    : "выключены";
  el("rndDot").classList.toggle("on", on);
  const modes = {auto:"авто", none:"без анимации", scroll:"прокрутка",
                 grid:"сетка", marquee:"бегущая строка"};
  scTransUI();
  const m = el("sc_anim") ? el("sc_anim").value : "grid";
  el("scStatus").textContent = (m === "grid")
    ? `сетка ${el("sc_per").value}×${el("sc_rows").value}`
    : (modes[m] || m);
}

function fillPanelCfg() {
  const c = DATA.config;
  const el = id => document.getElementById(id);
  if (!el("tm_start")) return;
  if (el("sc_anim")) {
    el("sc_anim").value = c.showcase_anim || "auto";
    el("sc_speed").value = c.showcase_speed ?? 5;
    el("sc_per").value = c.showcase_per_row ?? 7;
    el("sc_rows").value = c.showcase_rows ?? 3;
    el("sc_icon").value = c.showcase_icon ?? 88;
    el("sc_trans_grid").value = c.showcase_trans_grid || "pulse";
    const oldList = c.showcase_trans_list || "scroll";
    el("sc_motion").value = c.showcase_motion || (oldList === "step" ? "step" : "smooth");
    el("sc_effect").value = c.showcase_effect ||
      (oldList === "glow" || oldList === "breathe" ? oldList : "none");
    scTransUI();
    el("sc_badge").value = c.showcase_badge || "br";
    el("sc_online").checked = c.gift_icons_online !== false;
    const types = c.showcase_types || ["gifts"];
    ["gifts","likes","subs","follows","chatcmds"].forEach(t => {
      const box = el("sct_" + t);
      if (box) box.checked = types.includes(t);
    });
    el("sc_bsize").value = c.showcase_badge_size ?? 38;
    el("sc_bsize_lbl").textContent = c.showcase_badge_size ?? 38;
    el("sc_icon_lbl").textContent = c.showcase_icon ?? 88;
    if (typeof scBuild === "function") scBuild();
  }
  el("tm_start").value = c.timer_start_min ?? 30;
  el("tm_percoin").value = c.timer_sec_per_coin ?? 5;
  el("tm_endcmd").value = c.timer_end_command || "";
  el("rnd_on").checked = !!c.random_enabled;
  el("rnd_interval").value = c.random_interval_sec ?? 300;
  el("rnd_gift").checked = !!c.random_on_gift;
  // события: новый формат, либо конвертируем старый текстовый список
  RND_ITEMS = Array.isArray(c.random_items) && c.random_items.length
    ? JSON.parse(JSON.stringify(c.random_items))
    : String(c.random_commands || "").split("\n").filter(l => l.trim())
        .map(l => ({command: l.trim(), media_file: "", media_kind: "video", sound_file: ""}));
  renderRndItems();
  updPanelStatus();
}

function renderRndItems() {
  updPanelStatus();
  const box = document.getElementById("rndItems");
  if (!box) return;
  if (!RND_ITEMS.length) {
    box.innerHTML = '<div class="hint">Событий пока нет — нажми «+ Добавить событие»</div>';
    return;
  }
  const vids = MEDIA_FILES.filter(f => ["video","gif","image"].includes(f.kind));
  const snds = MEDIA_FILES.filter(f => f.kind === "sound");
  const opt = (list, sel) => '<option value="">— нет —</option>' +
    list.map(f => `<option value="${esc(f.name)}" ${f.name===sel?"selected":""}>${esc(f.name)}</option>`).join("");
  box.innerHTML = RND_ITEMS.map((it, i) => `
    <div class="rnd-item">
      <input class="mono" placeholder="команда без / (можно пусто)" value="${esc(it.command||"")}"
             oninput="RND_ITEMS[${i}].command=this.value">
      <select onchange="updRndMedia(${i}, this.value)" title="Видео/гифка">
        ${opt(vids, it.media_file)}
      </select>
      <select onchange="RND_ITEMS[${i}].sound_file=this.value" title="Звук">
        ${opt(snds, it.sound_file)}
      </select>
      <button class="icon danger" onclick="RND_ITEMS.splice(${i},1);renderRndItems();schedulePanelSave()">🗑</button>
    </div>`).join("");
}

function updRndMedia(i, val) {
  RND_ITEMS[i].media_file = val;
  const f = MEDIA_FILES.find(x => x.name === val);
  RND_ITEMS[i].media_kind = f ? f.kind : "video";
}

function addRndItem() {
  RND_ITEMS.push({command: "", media_file: "", media_kind: "video", sound_file: "",
                  media_volume: 100, sound_volume: 100});
  renderRndItems();
  schedulePanelSave();
}

async function testRnd(btn) {
  await savePanelCfg(true);
  const r = await fetch("/api/random_fire", {method: "POST",
    headers: {"Content-Type": "application/json"}, body: "{}"});
  const d = await r.json();
  const h = document.getElementById("panelHint");
  h.textContent = (d.ok ? "🎰 " : "✗ ") + d.message;
  h.style.color = d.ok ? "var(--green)" : "var(--red)";
  setTimeout(() => h.textContent = "", 3500);
}

async function savePanelCfg(silent) {
  const el = id => document.getElementById(id);
  DATA.config.timer_start_min = parseFloat(el("tm_start").value) || 30;
  DATA.config.timer_sec_per_coin = parseFloat(el("tm_percoin").value) || 0;
  DATA.config.timer_end_command = el("tm_endcmd").value.trim();
  DATA.config.random_enabled = el("rnd_on").checked;
  DATA.config.random_interval_sec = parseFloat(el("rnd_interval").value) || 300;
  DATA.config.random_on_gift = el("rnd_gift").checked;
  if (el("sc_anim")) {
    DATA.config.showcase_anim = el("sc_anim").value;
    DATA.config.showcase_speed = parseFloat(el("sc_speed").value) || 5;
    DATA.config.showcase_per_row = parseInt(el("sc_per").value) || 7;
    DATA.config.showcase_rows = parseInt(el("sc_rows").value) || 3;
    DATA.config.showcase_icon = parseInt(el("sc_icon").value) || 88;
    DATA.config.showcase_trans_grid = el("sc_trans_grid").value;
    DATA.config.showcase_motion = el("sc_motion").value;
    DATA.config.showcase_effect = el("sc_effect").value;
    DATA.config.showcase_badge = el("sc_badge").value;
    DATA.config.gift_icons_online = el("sc_online").checked;
    DATA.config.showcase_types = ["gifts","likes","subs","follows","chatcmds"]
      .filter(t => el("sct_" + t) && el("sct_" + t).checked);
    DATA.config.showcase_badge_size = parseInt(el("sc_bsize").value) || 38;
  }
  DATA.config.random_items = RND_ITEMS.filter(it =>
    (it.command||"").trim() || it.media_file || it.sound_file);
  await fetch("/api/config", { method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(DATA.config) });
  if (!silent) {
    const h = document.getElementById("panelHint");
    h.textContent = "✓ Сохранено"; h.style.color = "var(--green)";
    updPanelStatus();
    setTimeout(() => h.textContent = "", 2000);
  }
}

async function timerCtl(action) {
  const el = id => document.getElementById(id);
  const body = { action,
    timer_start_min: parseFloat(el("tm_start").value) || 30,
    timer_sec_per_coin: parseFloat(el("tm_percoin").value) || 0,
    timer_end_command: el("tm_endcmd").value.trim() };
  if (action === "add") body.seconds = 60;
  const r = await fetch("/api/timer", { method:"POST",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify(body) });
  const d = await r.json();
  showTimer(d);
}

function showTimer(d) {
  const el = document.getElementById("timerDisplay");
  if (!el) return;
  const s = d.remaining;
  const h = Math.floor(s/3600);
  const mm = String(Math.floor((s%3600)/60)).padStart(2,"0");
  const ss = String(s%60).padStart(2,"0");
  el.textContent = (h > 0 ? h + ":" : "") + mm + ":" + ss;
  el.classList.toggle("off", !d.running);
  const badge = document.getElementById("timerBadge");
  if (badge) {
    badge.textContent = d.running ? "идёт" : "остановлен";
    badge.classList.toggle("on", d.running);
  }
}

async function pollTimer() {
  const view = document.getElementById("view-panel");
  if (!view || view.classList.contains("hidden")) return;
  try {
    const r = await fetch("/api/timer", {cache:"no-store"});
    showTimer(await r.json());
  } catch(e) {}
}
setInterval(pollTimer, 1000);

function renderPanelButtons() {
  const box = document.getElementById("panelButtons");
  if (!box) return;
  const items = (DATA.profiles[activeProfile] || {}).panel || [];
  if (!items.length) {
    box.innerHTML = '<div class="hint pb-empty">Кнопок пока нет — на главной нажми «+ Создать событие» → «🎛 Кнопка панели»</div>';
    return;
  }
  box.innerHTML = items.map((a, i) => `
    <button class="pb-btn" onclick="panelFire(${i}, this)">${esc(a.title || ("Кнопка " + (i+1)))}</button>`).join("");
}

async function panelFire(i, btn) {
  const old = btn.textContent;
  btn.textContent = "⚡ ...";
  try {
    await fetch("/api/panel_fire", { method:"POST",
      headers:{"Content-Type":"application/json"}, body: JSON.stringify({index: i}) });
    btn.textContent = "✓";
  } catch(e) { btn.textContent = "✗"; }
  setTimeout(() => btn.textContent = old, 900);
}


// ── Библиотека подарков TikTok (название, цена в монетах) ───
const GIFT_LIBRARY = [
  ["A Shard of Hope",1],["Alien Pet",1],["Basketball",1],["Birthday Cake",1],
  ["Blow a kiss",1],["Blue Heart",1],["Blue Lightning",1],["Cake Slice",1],
  ["Cat Paws",1],["Chili",1],["Chilli Pepper",1],["Clap Clap",1],
  ["Club Cheers",1],["Coffee",1],["coldy",1],["Community Heart",1],
  ["Congratulations",1],["Cool",1],["Creeper",1],["Dolce Vita",1],
  ["Flame heart",1],["Football",1],["Freestyle",1],["GG",1],
  ["Gingerbread Heart",1],["Give It All",1],["Glass of Airan",1],["Glow Stick",1],
  ["Go Popular",1],["Good Job",1],["Graduation Bouquet",1],["Guardian Wings",1],
  ["Heart",1],["Heart Me",1],["Heart Puff",1],["Hello",1],
  ["Ice Cream Cone",1],["It's Match Time",1],["It’s corn",1],["Lightning Bolt",1],
  ["Little Life",1],["LIVE",1],["Love you",1],["Love you so much",1],
  ["Mamma Mia",1],["McChortles Nose",1],["Morning Bloom",1],["Music  Album",1],
  ["Music Album",1],["My First Rose",1],["Oldies",1],["Orange Juice",1],
  ["OSEL",1],["Pop",1],["Power hug",1],["Rainbow",1],
  ["Rose",1],["Slay",1],["So Cute",1],["Spidey Pin",1],
  ["Squirrel",1],["Steven Wingman",1],["Thumbs Up",1],["TikTok",1],
  ["Tom the Tomato",1],["Treasure Clover",1],["umbrella",1],["White Dove",1],
  ["White Rose",1],["Wink Charm",1],["Wink wink",1],["Yellow Lightning",1],
  ["You're awesome",1],["Максончик",1],["Модный Дуэт",1],["Team Bracelet",2],
  ["Choc Chip Cookie",5],["Duckling",5],["Duit Raya",5],["Embroidered Heart",5],
  ["Finger Heart",5],["Fire",5],["Golden Player",5],["Hello Traveler",5],
  ["I’m blue",5],["Name shoutout",5],["Overreact",5],["Peach",5],
  ["Pomegranate",5],["Potato",5],["Spinning Soccer",5],["Tofu",5],
  ["Wave Firework",5],["Yes TikTok Live",5],["Divine Fingers",6],["Applause",9],
  ["Cheer You Up",9],["Club Power",9],["Super Popular",9],["ASMR Time",10],
  ["Banana Peel",10],["Bunny",10],["Cherry Blossom Bunny",10],["Chocolate",10],
  ["Crocodile",10],["DJ Vinyl",10],["EWC",10],["FANDOM Fan",10],
  ["Friendship Necklace",10],["Gold Boxing Gloves",10],["Gutab",10],["Heart Gaze",10],
  ["Hi Bear",10],["Horseshoe",10],["I Like What I See",10],["I love you",10],
  ["Ice Lolly",10],["Intimacy",10],["Journey Pass",10],["League Ball",10],
  ["LIVE Ranking Ticket",10],["Lucky Pony",10],["Mind Blown",10],["Music Cloud",10],
  ["Panther",10],["Potato with ice cream",10],["Rosa",10],["Rugby Ball",10],
  ["Sing Together",10],["Slow motion",10],["Songs of LIVE",10],["Style Me Up",10],
  ["Tiny Diny",10],["Treasure's Key",10],["Whistle",10],["You're the Best!",10],
  ["Bravo!",15],["Disco Love",15],["Kudos for My Star",15],["Pumped Up",15],
  ["Aerith",20],["Barret",20],["Cait Sith",20],["Cloud",20],
  ["Dombra",20],["G.O.A.T. Busker",20],["Perfume",20],["S Flowers",20],
  ["Sephiroth",20],["Summer Sun",20],["Sushi Set",20],["Tifa",20],
  ["Traffic Cone",20],["Capybara",30],["Doughnut",30],["Energy Capsule",30],
  ["U make Miso happy!",30],["You are my Jam",30],["You are on a Roll",30],["Bagel",35],
  ["Sign language love",49],["Beach is calling",50],["Single Strike",70],["Butterfly",88],
  ["Family",90],["Fist bump",90],["Sending strength",90],["Birthday Crown",99],
  ["Birthday Hat",99],["Bloom Melody",99],["Breakthrough Star",99],["Bubble Gum",99],
  ["Cap",99],["Charmer Bow",99],["Club Victory",99],["Community Style",99],
  ["Cow-napping",99],["Cupid's Bow",99],["Cursed Kick",99],["Fiesta Accordion",99],
  ["Greeting Heart",99],["Groove Guitar",99],["Grumpy Glasses",99],["Guitar",99],
  ["Hat and Mustache",99],["Kiss your Heart",99],["Level-up Sparks",99],["Like-Pop",99],
  ["Little Crown",99],["LIVE On Air",99],["Love Painting",99],["Mark of Love",99],
  ["My favourite",99],["Paper Crane",99],["Pearl Chime",99],["Self care mask",99],
  ["Singing Mushroom",99],["Stabilizer",99],["Star",99],["Sundae Bowl",99],
  ["Wobbler",99],["Confetti",100],["FANDOM Stamp",100],["Game Controller",100],
  ["Gate to Treasure",100],["Hand Heart",100],["Hand Hearts",100],["Heart My Earthling",100],
  ["Marvelous Confetti",100],["Mini Star",100],["Mishka Bear",100],["Pim's Red Nose",100],
  ["Power Chip",100],["Rainbow Slide",100],["Shell Energy",100],["Singing Magic",100],
  ["Super GG",100],["Balloon Crown",149],["Big Shout Out",149],["Bowknot",149],
  ["Caterpillar Chaos",149],["Catrina",149],["Chatting Popcorn",149],["Fairy Hide",149],
  ["Feather Tiara",149],["Frog Conductor",149],["Groove Clarinet",149],["Love Glasses",149],
  ["Masquerade",149],["Raving Snail",149],["Santa Cocoa",149],["Tempo Flute",149],
  ["Kiss",150],["Potato Transformation",150],["Sceptre",150],["Umbrella",150],
  ["Bruiser",153],["Birthday Glasses",199],["Bloom Brass",199],["Cheer For You",199],
  ["Cheering Crab",199],["Chirpy Kisses",199],["Coconut Juice",199],["Coffee Magic",199],
  ["Cowboy Hat",199],["Crown",199],["Eye See You",199],["Fan Cat",199],
  ["Floating Octopus",199],["Flower Crown",199],["Flower Headband",199],["Gamer Cat",199],
  ["Garland Headpiece",199],["Hanging Lights",199],["Heart Hood",199],["Hearts",199],
  ["Joker Ball",199],["Juicy Smile",199],["Knight Helmet",199],["League Countdown",199],
  ["Lemond Buddy",199],["Lock and Key",199],["Love You",199],["Panther Paws",199],
  ["Party Pony",199],["Puppy Love",199],["Rhythm Bot",199],["Rose Hand",199],
  ["Sending positivity",199],["Side by Side",199],["Smile Latte",199],["Sour Buddy",199],
  ["Spin with me",199],["Suitcase",199],["Sunglasses",199],["Sunny Side Up",199],
  ["The Passion Rose",199],["Baglama",200],["Magic Genie",200],["Semsemia",200],
  ["Rose Bear",214],["Amped Up",249],["Blast Drum",249],["Candy Bouquet",249],
  ["Cheer Mic",249],["Dreamy Strings",249],["Face-pulling",249],["Forest Elf",249],
  ["Ice Cream Mic",249],["Melodic birds",249],["Midsummer Hair",249],["Music Bubbles",249],
  ["Palm Breeze",249],["Party Blossom",249],["Pinch Face",249],["Poetry Score",249],
  ["Singing Frog",249],["Snow Bloom",249],["Star Goggles",249],["Surfing Penguin",249],
  ["Sweet Flutter",249],["Treasured Voice",249],["Triple Thunder",289],["Bat Headwear",299],
  ["Boxing Gloves",299],["Budding Heart",299],["Butterfly for You",299],["Cello Romance",299],
  ["Cheering Towel",299],["Come On!",299],["Corgi",299],["Crystal Shoe",299],
  ["Dash",299],["Diva’s Hat",299],["Duck",299],["EID Gift Box",299],
  ["Elephant trunk",299],["Fake smile",299],["Falling For You",299],["FrankTastic",299],
  ["Fruit Friends",299],["Go Hamster",299],["Greek crown",299],["Gus the Groundhog",299],
  ["Henry the Hedgehog",299],["Hero Landing",299],["Hi! Rosie!",299],["Kicker Challenge",299],
  ["Labor Power",299],["LIVE Ranking Crown",299],["LIVE Ranking Headband",299],["Love Call",299],
  ["Lover’s Glasses",299],["Lucy the Llama",299],["Melody Glasses",299],["Mr. Orange",299],
  ["Music Mate",299],["Naughty Chicken",299],["Penguin Snowpal",299],["Play for you",299],
  ["Play for You",299],["Pony Lantern",299],["Puppy Kisses",299],["Rain Doll",299],
  ["Reindeer",299],["Rhythm Crown",299],["Rock Star",299],["Sail Away",299],
  ["Sax Groove",299],["Scroll",299],["Spring Sprout",299],["Superpower",299],
  ["Swing Cello",299],["TikTok Crown",299],["United Heart",299],["Wakey Mallow",299],
  ["You’re sweet",299],["Feather Mask",300],["Galaxy's Bestest",300],["Random Red Nose",300],
  ["Backing Monkey",349],["Batwing Hat",349],["Beach Maracas",349],["Become Kitten",349],
  ["Butterfly Vibe",349],["Chopin in the Rain",349],["Craft Dreamer",349],["Djembe Master",349],
  ["Electro Vibes",349],["Festival Bracelet",349],["Gingerbread Man",349],["Juicy Cap",349],
  ["Marked with Love",349],["Mom's Bonnet",349],["Mystic Drink",349],["Retro Headset",349],
  ["Retro Melody",349],["Rocking Shroom",349],["Sparkle Pony",349],["Spring Bouquet",349],
  ["Ukulele Player",349],["Vintage flight",349],["Vinyl Flip",349],["Singing frogs",398],
  ["Alien Buddy",399],["Aurora Groove",399],["Beat Wings",399],["Blossom Fairy",399],
  ["Cactus Shuffle",399],["Confetti Bear",399],["Cotton the Seal",399],["DJ Set",399],
  ["Dreamy Hat",399],["Echo Mom",399],["Fairy Locket",399],["Fire up",399],
  ["Floral Serenade",399],["Flower Flight",399],["Forever Rosa",399],["Health Potion",399],
  ["Jollie the Joy Bean",399],["Jollie's Community",399],["Kitten Kneading",399],["Let butterfly dances",399],
  ["Magic Rhythm",399],["Melody Headset",399],["Mic Check",399],["Panda Snap",399],
  ["Papa Capybara",399],["Pharaoh Mask",399],["Relaxed Goose",399],["Rocky the Rock Bean",399],
  ["Rosie the Rose Bean",399],["Rosie's Concert",399],["Sage the Smart Bean",399],["Sage's Slash",399],
  ["Santa Owl Surprise",399],["Shoot the Apple",399],["Singing Mic",399],["Singing Sax",399],
  ["Tiger Lift",399],["Tom's Hug",399],["Vocal Bear",399],["Bounce Speakers",400],
  ["Cheeky Pup",400],["Crystal Dreams",400],["DJ Wave",400],["FANDOM Fever",400],
  ["Glorious Chef",400],["Magic Accordion",400],["Mic Champ",400],["Pop Parrot",400],
  ["Punch Cuddle",400],["Reindeer Milk",400],["Rock Cats",400],["Rock Idol",400],
  ["Super Dad",400],["Taraxacum Corgi",400],["Wishing Cake",400],["Batting Cutie",449],
  ["Beating Heart",449],["Candy Loot",449],["Captured Vocals",449],["Clown Boogie",449],
  ["Electronic Love Song",449],["Encore Clap",449],["Pirate's Treasure",449],["Rock and Roll",449],
  ["Space Love",449],["Terminator Face",449],["Xmas Tree Hat",449],["Celebration Hat",450],
  ["City Pop",450],["Clover Hat",450],["Cupid Koala",450],["Groove Straw",450],
  ["Halloween Fun Hat",450],["Hat of Joy",450],["Music Conductor",450],["Office Penguin",450],
  ["Over the Cloud",450],["Paw Call",450],["Pink Cowboy",450],["Powerful Mind",450],
  ["Sloth Peek",450],["Steady on the Beam",450],["Superwoman",450],["Coral",499],
  ["Eye on the Ball",499],["Gold Microphone",499],["Hands Up",499],["Key Master",499],
  ["Magic Potion",499],["Music",499],["Panda Hug",499],["Rose Soundwave",499],
  ["Sakura Corgi",499],["Baby Chicks",500],["Big Potato",500],["Bunny Crown",500],
  ["Couch Potato",500],["Cozy Xmas Set",500],["Cuddle with Me",500],["DJ Glasses",500],
  ["Dragon Crown",500],["Dream Team",500],["Drum Genius",500],["Drum Pop",500],
  ["Flower Show",500],["Gardening",500],["Gem Gun",500],["Halloween Ghost",500],
  ["Heart Guitar",500],["Honey Strummer",500],["Jungle Blitzy",500],["Jungle Cooper",500],
  ["Jungle Diny",500],["Jungle Tom",500],["Lion’s Mane",500],["Lost in Your Music",500],
  ["Magic Prop",500],["Manifesting",500],["Match Master",500],["Mic Drop",500],
  ["Money Gun",500],["Mystery Box",500],["Out Pops Jollie!",500],["Prairie Blitzy",500],
  ["Prairie Cooper",500],["Prairie Diny",500],["Prairie Tom",500],["Prince",500],
  ["Puyo Shower!",500],["Roo Mother",500],["Shell of a Warrior",500],["Sound Spell",500],
  ["Spaghetti Kiss",500],["Starry Fluff",500],["Trophy",500],["VR Goggles",500],
  ["Window basket",500],["Wingman",500],["XXXL Flowers",500],["You’re Amazing",500],
  ["Bubbly Kiss",530],["Drum Hamster",549],["Hive Escape",549],["Money Magnet",549],
  ["Fully Bloomed Sakura",599],["League Trophy",599],["Soccer Holo",599],["Join Butterflies",600],
  ["Sakura-style DJ",600],["Seahorse Pop",649],["Swan",699],["Colorful Wings",700],
  ["Sax Appeal",700],["The Van Cat",799],["Claw machine",800],["Epic Pianist",800],
  ["Love Flight",800],["It’s a Match!",899],["Train",899],["Medium Fandom",900],
  ["Divine Flame",999],["Enchanted Guitar",999],["Flamingo Floaty",999],["Grand show",999],
  ["Lovely Music",999],["Lucky Airdrop Box",999],["Music Burst",999],["Raining gifts",999],
  ["Travel with You",999],["Trending Figure",999],["Blooming Ribbons",1000],["Desert Blitzy",1000],
  ["Desert Cooper",1000],["Desert Diny",1000],["Desert Tom",1000],["Dinosaur",1000],
  ["dinosaur",1000],["Disco ball",1000],["Drums",1000],["Email Message",1000],
  ["Fairy Wings",1000],["Feather Flock",1000],["Firepit Blitzy",1000],["Firepit Cooper",1000],
  ["Firepit Diny",1000],["Firepit Tom",1000],["Flamingo Groove",1000],["Galaxy",1000],
  ["Gerry the Giraffe",1000],["Giraffe",1000],["Glowing Jellyfish",1000],["Gold Mine",1000],
  ["Matchtacular!",1000],["Mirror Bloom",1000],["Picnic basket",1000],["Red Nose Cannon",1000],
  ["Shiny air balloon",1000],["Shiny Air Balloon",1000],["Sparkle Dance",1000],["Tundra Blitzy",1000],
  ["Tundra Cooper",1000],["Tundra Diny",1000],["Tundra Tom",1000],["Watermelon Love",1000],
  ["Candy Puffs",1030],["Joy Floats",1030],["Diamond Tree",1088],["Fireworks",1088],
  ["Exclusive Spark",1099],["Golden Stars",1099],["Bunny DJ",1200],["Epic GG",1200],
  ["Fountain",1200],["Gaming Chair",1200],["Take a Drive",1200],["Travel in the US",1200],
  ["Umbrella of Love",1200],["Hydrangea Sea",1299],["Spider Web",1299],["Spider Web 2.0",1299],
  ["Party Laser",1300],["Moonlight flower",1400],["Vibrant Stage",1400],["Cheer for You",1499],
  ["Astrobear",1500],["Champion",1500],["Chasing the Dream",1500],["Diamond Ring",1500],
  ["EWC Trophy",1500],["Future Encounter",1500],["Galaxy Globe",1500],["Garland",1500],
  ["Greeting Card",1500],["Ignition Check",1500],["Level Ship",1500],["Lover’s Lock",1500],
  ["Pim Bear",1500],["Potato floating",1500],["Racing Debut",1500],["Raya Gift Card",1500],
  ["Space Cat",1500],["Under Control",1500],["Viking Hammer",1500],["Wild Mic",1500],
  ["You're So Fly",1500],["Shooting Stars",1580],["ASMR Starter Kit",1599],["Blooming Heart",1599],
  ["Penlight",1599],["Hug It Better",1600],["Center Stage",1799],["Here We Go",1799],
  ["Fox Legend",1800],["Love Drop",1800],["Watch out",1800],["Airship",1999],
  ["Beach Cabin",1999],["Cooper Flies Home",1999],["Doll New Year Greeting",1999],["Gift Box",1999],
  ["Let Us Dance",1999],["Make-up Box",1999],["Mystery Firework",1999],["Rabbit",1999],
  ["Star Adventures",1999],["Star of Red Carpet",1999],["Super Cake",1999],["Baby Dragon",2000],
  ["Club",2000],["Club Music",2000],["Power Couple",2000],["Sky Drift",2000],
  ["Take My Rose!",2000],["Tiny Diny Chill",2000],["Vacation LIVE",2000],["Whale diving",2150],
  ["Whale Diving",2150],["Blow Rosie Kisses",2199],["Jetski",2199],["Jollie's Heartland",2199],
  ["Lemon Love Booth",2199],["Rocky's Punch",2199],["Sage's Coinbot",2199],["Lamb",2200],
  ["Wave Lights",2200],["By the Glaziers",2380],["Funnyboyenam World",2399],["Summer Pass L",2499],
  ["Tom Thunderfoot",2499],["Animal Band",2500],["FANDOM Cheer",2500],["Space Dog",2500],
  ["Magic Stage",2599],["Celebration Tape",2800],["Samfaring Tom",2850],["Concert",2888],
  ["Motorcycle",2988],["Pink Dream",2988],["Beach Day",2999],["Bull",2999],
  ["Community Rally",2999],["Level-up Spotlight",2999],["Love in Sunset",2999],["Match Maniac",2999],
  ["Party Bus",2999],["Rhythmic Bear",2999],["Ring Of Honor-Cube",2999],["Surprise Baby Mob",2999],
  ["Car Drifting",3000],["Dancing Bears",3000],["Ferris Wheel",3000],["Golden Party",3000],
  ["Meteor Shower",3000],["Summoning Horn",3000],["Sea Blitzy",3088],["Sea Cooper",3088],
  ["Sea Diny",3088],["Sea Tom",3088],["Hip-Hop Hen",3200],["Dream Big",3350],
  ["Look Up",3350],["Giant",3999],["Go Home",3999],["LIVE Ranking Party",3999],
  ["Spring train",3999],["Cloud DJ",4000],["Flower Overflow",4000],["Gaming Keyboard",4000],
  ["Magic World",4088],["Rugby Pim bear",4088],["Shine Bright",4088],["Superstar",4088],
  ["Next Level",4099],["Tractor",4099],["Your Concert",4500],["Dynamic Music",4888],
  ["Fiery Dragon",4888],["Leon the Kitten",4888],["Private Jet",4888],["Signature Jet",4888],
  ["Sugar Whiskers",4918],["Benny the Calf",4999],["Guardian's Pledge",4999],["Hero Space Ship",4999],
  ["Pool Party",4999],["Sage’s Venture",4999],["Stage of ring",4999],["Stage of SpiderMan",4999],
  ["1st Anniversary",5000],["Autumn Farm",5000],["Bird Whisperer",5000],["Crowd Cheering",5000],
  ["Cycling",5000],["Diamond Gun",5000],["DJ Alien",5000],["Draco",5000],
  ["Ellie the Elephant",5000],["Flying Jets",5000],["League Fandom",5000],["Leon's Sigil Cape",5000],
  ["LIVE on holiday",5000],["Mimi & Fifi",5000],["Motorcycle Together",5000],["Seaside Romance",5000],
  ["Silver Sports Car",5000],["Unicorn Fantasy",5000],["Wanda the Witch",5000],["Wolf",5000],
  ["Ice Cream Machine",5288],["Fluffy Buddies",5388],["Cub on Clouds",5888],["Valiant Odyssey",5888],
  ["Devoted Heart",5999],["Chick Stampede",6000],["Future City",6000],["Goal Highlight-US",6000],
  ["Rust Reforged",6000],["Sam in New City",6000],["Strong Finish",6000],["With you",6000],
  ["Work Hard Play Harder",6000],["Lili the Leopard",6599],["Birthday Party",6999],["Celebration Time",6999],
  ["Happy Party",6999],["2nd Anniversary",7000],["Black Swan",7000],["Sports Car",7000],
  ["Majestic Hearts",7238],["Go Big Alpha Drifter",7700],["Diamond Shield",7999],["Monster Truck",7999],
  ["Star Throne",7999],["Mount Olympus",8000],["Ultimate FANDOM",8000],["Saxophone",9000],
  ["Leon and Lili",9699],["Travel Memories",9999],["Festival Flags",10000],["Garden Fantasy",10000],
  ["Interstellar",10000],["Octopus",10000],["Sunset Speedway",10000],["Falcon",10999],
  ["3rd Anniversary",12000],["Convertible Car",12000],["Crystal Power",12000],["Red Lightning",12000],
  ["Level-up Spectacle",12999],["Summer Pass XL",13500],["Spaceship",13999],["Chrono Rewinder",14999],
  ["Crystal Heart",14999],["Invincible Hammer",14999],["Lucky Crown",14999],["Storm Blade",14999],
  ["Tidecaller Trident",14999],["Arabian Cheetah",15000],["Battle Champion",15000],["Big Ben",15000],
  ["Black Wolf",15000],["Community Support",15000],["Dream Ride",15000],["Enchanted statue",15000],
  ["Future Journey",15000],["Gaming Console",15000],["Go Big Stallion",15000],["Golden Gallop",15000],
  ["Leopard",15000],["Look! Meteor Shower",15000],["Maggie",15000],["Maro Spider Man",15000],
  ["Movie Time",15000],["Paris",15000],["Party On&On",15000],["peacock",15000],
  ["Pirate’s Ship",15000],["Pyramids",15000],["Rosa Nebula",15000],["Sneaky Jockey",15000],
  ["Time for Family",15000],["Stadium",15999],["White Tiger",15999],["Amusement Park",17000],
  ["Diamond flight",18000],["Diamond Flight",18000],["Rust vs World",18999],["Fly Love",19999],
  ["Castle Fantasy",20000],["Corgi's Drone Show",20000],["Premium Shuttle",20000],["Red Devil Corgi",20000],
  ["Spark",20000],["TikTok Shuttle",20000],["Yacht",20000],["Black Tiger",22000],
  ["Infinite Heart",23999],["Adam’s Dream",25999],["Cyber Roar",25999],["Light Castle",25999],
  ["Mystic Castle",25999],["Phoenix",25999],["Skyforge Citadel",25999],["T-rex",25999],
  ["Undersea Kingdom",25999],["Dragon Flame",26999],["Lion",29999],["Gorilla",30000],
  ["Sam the Whale",30000],["Guardian Rhino",30999],["Leon and Lion",34000],["Zeus",34000],
  ["Seal and Whale",34500],["TikTok Universe+",34999],["Thunder Falcon",39999],["TikTok Stars",39999],
  ["Fire Phoenix",41999],["King Leonardo",42999],["Legend Marcellus",42999],["Pegasus",42999],
  ["Julius the Champion",43999],["Valerian's Oath",43999],["TikTok Universe",44999],
];
let GIFT_ICONS = {};   // {название_lowercase: путь к картинке в media/gifts}
let GIFT_ICONS_ONLINE = {};  // {название_lowercase: ссылка на иконку TikTok}
let GIFT_IDS = {};           // {название_lowercase: ID} — ID одинаковый на любом языке
let GIFT_RU = {};            // {ID: «Роза»} — русские названия, TikTok отдаёт их при подключении
const normGift = s => String(s || "").toLowerCase().replace(/ё/g, "е").split(/\s+/).filter(Boolean).join(" ");
function ruNameOf(en) { const id = GIFT_IDS[String(en).toLowerCase()]; return id ? (GIFT_RU[id] || "") : ""; }
function ruKnown(name) { const n = normGift(name); return Object.values(GIFT_RU).some(v => normGift(v) === n); }
let libTarget = -1;   // индекс карточки, в которую подставляем подарок
let libSection = "gifts";

// Картинка подарка по названию — для карточек и библиотеки
function giftIconHtml(name, size) {
  const n = String(name || "").trim();
  const letter = esc((n || "?").charAt(0).toUpperCase());
  const key = n.toLowerCase();
  const local = GIFT_ICONS[key];
  const online = GIFT_ICONS_ONLINE[key];
  const url = local ? "/media/" + local : (online || "");
  const st = `width:${size}px;height:${size}px;flex:none`;
  return url
    ? `<img src="${url}" alt="" loading="lazy" data-ph="${letter}" onerror="imgFail(this)"
            style="${st};object-fit:contain;border-radius:8px;background:rgba(255,255,255,0.05)">`
    : `<div class="gl-ph" style="${st};font-size:${Math.round(size * 0.42)}px">${letter}</div>`;
}

// Ссылка не открылась — подставляем кружок с буквой того же размера
function imgFail(img) {
  const ph = document.createElement("div");
  ph.className = "gl-ph";
  ph.textContent = img.dataset.ph || "?";
  const w = img.style.width;
  if (w) {
    ph.style.width = w; ph.style.height = img.style.height; ph.style.flex = "none";
    ph.style.fontSize = Math.round(parseInt(w) * 0.42) + "px";
  }
  img.replaceWith(ph);
}

let GIFT_CAT = {gifts: [], regions: {}, known: []};   // каталог подарков всех регионов (от TikTok)
let LIB_REGION = "";                                   // фильтр библиотеки по региону

async function loadGiftIcons() {
  try {
    const r = await fetch("/api/gift_icons", {cache: "no-store"});
    const d = await r.json();
    GIFT_ICONS = d.icons || {};
    GIFT_ICONS_ONLINE = d.online || {};
    GIFT_IDS = d.ids || {};
    GIFT_RU = d.ru || {};
  } catch (e) { GIFT_ICONS = {}; GIFT_ICONS_ONLINE = {}; }
  try {
    GIFT_CAT = await (await fetch("/api/gift_catalog", {cache: "no-store"})).json();
    for (const g of GIFT_CAT.gifts || []) {          // картинки и ID из каталога — для всех карточек
      const k = String(g.name).toLowerCase();
      if (g.icon && !GIFT_ICONS_ONLINE[k]) GIFT_ICONS_ONLINE[k] = g.icon;
      if (!GIFT_IDS[k]) GIFT_IDS[k] = String(g.id);
    }
  } catch (e) {}
}

// Все подарки для библиотеки: встроенный список + каталог регионов (без повторов)
function libItems() {
  // встроенный список — один в один (номера совпадают с GIFT_LIBRARY), подарки каталога — после него
  const items = GIFT_LIBRARY.map(([n, p]) => ({name: n, coins: p, regions: [], id: ""}));
  const first = new Map();
  items.forEach((it, i) => { const k = it.name.toLowerCase(); if (!first.has(k)) first.set(k, i); });
  for (const g of GIFT_CAT.gifts || []) {
    const k = String(g.name).toLowerCase();
    if (first.has(k)) {
      const cur = items[first.get(k)];
      cur.regions = [...new Set(cur.regions.concat(g.regions || []))];
      cur.id = cur.id || String(g.id);
    } else {
      first.set(k, items.length);
      items.push({name: g.name, coins: g.coins || 0, regions: g.regions || [], id: String(g.id)});
    }
  }
  return items;
}

async function libFetchRegion() {
  const btn = document.getElementById("libRegionBtn"), hint = document.getElementById("libRegionHint");
  btn.disabled = true; btn.textContent = "⏳ Спрашиваю TikTok…";
  try {
    const d = await (await fetch("/api/gift_catalog/fetch", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({region: "ALL"})})).json();
    hint.textContent = d.ok ? `✓ TikTok прислал ${d.total} подарков, новых в библиотеке — ${d.new}` : "✗ " + d.error;
    if (d.ok) { await loadGiftIcons(); LIB_REGION = "tiktok"; renderGiftLib(); }
  } catch (e) { hint.textContent = "✗ " + e.message; }
  finally { btn.disabled = false; btn.textContent = "🌍 Загрузить весь список"; }
}
// подарок из списка TikTok (любой загрузки, кроме своего эфира)
const fromTikTok = rg => (rg || []).some(r => r !== "эфир");

async function openGiftLib(idx) {
  libTarget = idx;
  libSection = activeSection;
  // окно открываем сразу — иконки уже загружены при старте программы
  document.getElementById("giftLibModal").classList.remove("hidden");
  renderGiftLib();
  // а в фоне подтягиваем свежие (вдруг добавил картинки в media/gifts)
  await loadGiftIcons();
  if (!document.getElementById("giftLibModal").classList.contains("hidden")) renderGiftLib();
}

function closeGiftLib() {
  document.getElementById("giftLibModal").classList.add("hidden");
  libTarget = -1;
}

function renderGiftLib() {
  const box = document.getElementById("giftLibBox");
  if (!box || libTarget < 0) return;
  const q = (document.getElementById("libSearch")?.value || "").toLowerCase();
  const onlyPic = document.getElementById("libOnlyPic")?.checked;
  LIB_ALL = libItems();
  const items = LIB_ALL
    .map((g, i) => [g.name, g.coins, i, g.regions])
    .filter(([n]) => !q || n.toLowerCase().includes(q) || normGift(ruNameOf(n)).includes(normGift(q)))
    .filter(([n]) => !onlyPic || GIFT_ICONS[n.toLowerCase()] || GIFT_ICONS_ONLINE[n.toLowerCase()])
    .filter(([, , , rg]) => !LIB_REGION || (LIB_REGION === "tiktok" ? fromTikTok(rg) : (rg || []).includes(LIB_REGION)))
    .sort((a, b) => a[1] - b[1]);
  const known = GIFT_CAT.known || [];
  const loaded = Object.entries(GIFT_CAT.regions || {});
  const rname = code => (known.find(k => k[0] === code) || [code, code])[1];
  const tiktokN = (GIFT_CAT.gifts || []).filter(g => fromTikTok(g.regions)).length;
  const cur = ((DATA.profiles[activeProfile][libSection] || [])[libTarget] || {}).name || "";
  box.innerHTML = `
    <div class="row" style="margin-bottom:12px">
      <h3 style="margin:0">📚 Библиотека подарков</h3>
      <input id="libSearch" placeholder="поиск: Rose или Роза" value="${esc(q)}"
             oninput="renderGiftLib()" style="max-width:200px">
      <label class="chk"><input type="checkbox" id="libOnlyPic" ${onlyPic?"checked":""}
             onchange="renderGiftLib()"> только с картинками</label>
      <div class="spacer"></div>
      <span class="hint">найдено: ${items.length}</span>
      <button class="icon danger" onclick="closeGiftLib()">✕</button>
    </div>
    <div class="lib-reg">
      <span class="lib-reg-t">🌍 Все подарки TikTok:</span>
      <button class="small primary" id="libRegionBtn" onclick="libFetchRegion()">🌍 Загрузить весь список</button>
      <span class="hint" id="libRegionHint">с ID и картинками. TikTok отдаёт список по твоему интернету — в нём уже есть подарки соседних стран, например казахстанские Dombra и Yurt</span>
    </div>
    ${loaded.length ? `<div class="lib-chips"><span class="fish-tag${!LIB_REGION ? " active" : ""}" onclick="LIB_REGION=''; renderGiftLib()">Все</span>
      ${tiktokN ? `<span class="fish-tag${LIB_REGION === "tiktok" ? " active" : ""}" onclick="LIB_REGION='tiktok'; renderGiftLib()">🌍 Список TikTok · ${tiktokN}</span>` : ""}
      ${GIFT_CAT.regions["эфир"] ? `<span class="fish-tag${LIB_REGION === "эфир" ? " active" : ""}" onclick="LIB_REGION='эфир'; renderGiftLib()">📡 Мой эфир · ${GIFT_CAT.regions["эфир"].count}</span>` : ""}
    </div>` : ""}
    <div class="gift-lib-grid">
      ${items.map(([n, p, gi]) => {
        const key = n.toLowerCase();
        const local = GIFT_ICONS[key];
        const online = GIFT_ICONS_ONLINE[key];
        const url = local ? "/media/" + local : (online || "");
        const letter = esc(n.charAt(0).toUpperCase());
        const img = url
          ? `<img src="${url}" alt="" loading="lazy" onerror="imgFail(this)" data-ph="${letter}">`
          : `<div class="gl-ph">${letter}</div>`;
        const sel = (n === cur) ? ' style="border-color:var(--cyan)"' : "";
        return `<div class="gift-lib-item"${sel} onclick="pickGift(${gi})">
          ${img}<div class="gl-name">${esc(n)}</div>${ruNameOf(n) ? `<div class="gl-ru">${esc(ruNameOf(n))}</div>` : ""}
          <div class="gl-price">${p} 🪙</div></div>`;
      }).join("")}
    </div>
    <div class="hint" style="margin-top:10px">
      💡 Свои картинки: положи файл в <b>media/gifts/</b> с именем как у подарка (например <b>Rose.png</b>).
    </div>`;
  const s = document.getElementById("libSearch");
  if (s && q) { s.focus(); s.setSelectionRange(q.length, q.length); }
}

let LIB_ALL = [];
function pickGift(gi) {
  const g = LIB_ALL[gi];
  if (!g || libTarget < 0) return;
  activeSection = libSection;
  const a = curList()[libTarget];
  a.name = g.name;
  // ID одинаковый на любом языке — TikTok может прислать название по-английски или по-русски.
  // Старый ID обязательно сбрасываем, иначе карточка продолжит ловить прошлый подарок.
  a.gift_id = g.id || GIFT_IDS[g.name.toLowerCase()] || "";
  closeGiftLib();
  renderCards();
}


// ── Оверлеи OBS ──────────────────────────────────────────────
// ── Список оверлеев с живым превью ──────────────────────────
const OVERLAYS = [
  {id:"ov1", file:"alerts.html",    icon:"🎁", name:"Алерты подарков",
   desc:"Всплывающие уведомления о подарках, лайках, подписках", w:500,  h:300},
  {id:"ov2", file:"top.html",       icon:"🏆", name:"Топ донатеров",
   desc:"Таблица лидеров по подаркам", w:320,  h:400},
  {id:"ov3", file:"feed.html",      icon:"📜", name:"Лента событий",
   desc:"Последние события бегущей лентой", w:360,  h:400},
  {id:"ov4", file:"media.html",     icon:"🎬", name:"Медиа-алерты (видео/гифки + звук)",
   desc:"Видео или гифка по центру со звуком при подарке", w:1920, h:1080, vw:960, vh:540},
  {id:"ov5", file:"top_likes.html", icon:"❤", name:"Топ-3 по лайкам",
   desc:"Три зрителя с наибольшим числом лайков", w:420,  h:330, vw:420, vh:330},
  {id:"ov9", file:"showcase.html",  icon:"🎁", name:"Витрина подарков",
   desc:"Что и как влияет на игру: подарки, лайки, подписки, чат-команды. Лента внизу — добавь ?layout=row",
   w:1000, h:400, vw:720, vh:400},
  {id:"ov7", file:"goals.html",     icon:"🎯", name:"Цели стрима",
   desc:"Прогресс-бары целей: лайки, монеты, фолловеры", w:320,  h:400},
  {id:"ov8", file:"timer.html",     icon:"⏱", name:"Таймер-челлендж",
   desc:"Большой обратный отсчёт, подарки добавляют время", w:420,  h:140},
  {id:"ov6", file:"tts.html",       icon:"🔊", name:"Озвучка чата (TTS)",
   desc:"Невидимый оверлей — читает сообщения голосом", w:400,  h:200, novis:true},
];
let overlaysLoaded = false;

function renderOverlays() {
  const box = document.getElementById("overlayList");
  if (!box) return;
  const base = window.location.origin;
  box.innerHTML = OVERLAYS.map(o => {
    const url = `${base}/web/overlays/${o.file}`;
    // вписываем оверлей целиком: у каждого свой размер превью
    const MAXW = 232, MAXH = 168;
    // vw/vh — размер «экрана» для превью: меньше = крупнее, больше = мельче
    const vw = o.vw || o.w, vh = o.vh || o.h;
    const scale = Math.min(MAXW / vw, MAXH / vh);
    const pw = Math.round(vw * scale), ph = Math.round(vh * scale);
    const prev = o.novis
      ? `<div class="ov-prev novis" style="width:180px;height:110px">🔊<span>только звук</span></div>`
      : `<div class="ov-prev" style="width:${pw}px;height:${ph}px">
           <iframe data-src="${url}?demo=1" style="width:${vw}px;height:${vh}px;
                   transform:scale(${scale});transform-origin:0 0" scrolling="no"></iframe>
         </div>`;
    return `
      <div class="overlay-item ov-live">
        <div class="ov-slot">${prev}</div>
        <div class="ov-body">
          <div class="ov-name">${o.icon} ${esc(o.name)}
            ${o.novis ? "" : '<span class="ov-dot">● живое</span>'}</div>
          <div class="ov-desc">${esc(o.desc)} · размер ${o.w}×${o.h}</div>
          <div class="row" style="margin-top:7px">
            <input class="mono" id="${o.id}" readonly value="${url}">
            <button class="small" onclick="copyOv('${o.id}')">Копировать</button>
            <button class="small" onclick="openOv('${o.id}')">Открыть</button>
            ${o.novis ? "" : `<button class="small" onclick="bigPreview('${o.file}',${o.w},${o.h})"
                     title="Посмотреть пример в полный размер">🔍 Крупнее</button>`}
          </div>
        </div>
      </div>`;
  }).join("");
}

// Превью грузим только когда открыта вкладка — чтобы не тормозить старт
function loadOverlayPreviews() {
  document.querySelectorAll("#overlayList iframe[data-src]").forEach(f => {
    f.src = f.dataset.src;
    f.removeAttribute("data-src");
  });
  overlaysLoaded = true;
}

function toggleVarsHelp(btn) {
  const el = document.getElementById("varsFull");
  if (!el) return;
  const open = el.classList.toggle("hidden") === false;
  btn.textContent = open ? "Свернуть" : "Показать все";
}

function bigPreview(file, w, h) {
  const url = `${window.location.origin}/web/overlays/${file}?demo=1`;
  window.open(url, "_blank", `width=${Math.min(w + 40, 1200)},height=${Math.min(h + 60, 800)}`);
}

function copyOv(id) {
  const inp = document.getElementById(id);
  inp.select();
  navigator.clipboard.writeText(inp.value).then(() => {
    const btn = event.target;
    const old = btn.textContent;
    btn.textContent = "✓ Скопировано";
    setTimeout(() => btn.textContent = old, 1500);
  });
}
function openOv(id) {
  window.open(document.getElementById(id).value, "_blank");
}

// ── Утилиты ──────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}


// Автообновление статуса подключения
setInterval(refreshState, 3000);

// Старт
loadState();
