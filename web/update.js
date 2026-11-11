// ── Обновления через GitHub и перенос данных из старой папки ────────────────
let UPD = null;
function updReload() { location.reload(); }

async function updLoad(force) {
  try {
    UPD = await (await fetch(force ? "/api/update/check" : "/api/update/status",
                             {method: force ? "POST" : "GET", cache: "no-store"})).json();
  } catch (e) { return; }
  updBadge();
  updBanner();
  if (!document.getElementById("changelogModal").classList.contains("hidden")) updRender();
}

// Текст релиза с GitHub — простой Markdown: заголовки ##, **жирный**, `код`, списки «- ».
function updMd(s) {
  return esc(s).split(/\r?\n/).map(l => {
    l = l.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    if (/^#{1,6}\s+/.test(l)) return `<b>${l.replace(/^#{1,6}\s+/, "")}</b>`;
    if (/^[-*]\s+/.test(l)) return "• " + l.replace(/^[-*]\s+/, "");
    return l;
  }).join("<br>").replace(/(<br>){3,}/g, "<br><br>");
}

function updAvailable() { return !!(UPD && UPD.info && UPD.info.available); }

function updBadge() {
  const b = document.getElementById("appVersion");
  if (!b || !UPD) return;
  if (updAvailable()) {
    b.textContent = `⬆ v${UPD.info.version}`;
    b.classList.add("upd");
    b.title = `Доступна версия ${UPD.info.version} — нажми, чтобы обновить`;
  } else {
    b.textContent = `v${UPD.current}`;
    b.classList.remove("upd");
    b.title = "Что нового";
  }
}

function updRenderMain() {
  const box = document.getElementById("updBox");
  if (!box || !UPD) return;
  const j = UPD.job;
  if (j && ["downloading", "extracting", "restarting"].includes(j.state)) {
    const pct = Math.round((j.progress || 0) * 100);
    box.innerHTML = `<div class="upd-box"><b>${j.state === "restarting" ? "🔄 Перезапускаю TakyLive…" :
        j.state === "extracting" ? "📦 Распаковываю…" : `⬇ Скачиваю версию ${esc(j.version)}…`}</b>
      <div class="upd-bar"><i style="width:${pct}%"></i></div>
      <div class="hint">Не закрывай окно — после перезапуска оно обновится само.</div></div>`;
    return;
  }
  if (updAvailable()) {
    const i = UPD.info;
    const meta = [i.date, i.size ? `${(i.size / 1048576).toFixed(0)} МБ` : ""].filter(Boolean).join(" · ");
    box.innerHTML = `<div class="upd-box avail"><div class="row"><b>⬆ Доступна версия ${esc(i.version)}</b>
        <span class="hint" style="margin-left:8px">${esc(meta)}</span>
        <div class="spacer"></div>
        <button class="primary" onclick="updInstall()">Обновить</button></div>
      ${i.notes ? `<div class="upd-notes">${updMd(i.notes)}</div>`
        : i.page ? `<div class="hint"><a href="${esc(i.page)}" target="_blank" rel="noopener">Что нового — на GitHub</a></div>` : ""}
      <div class="hint">Настройки, вкладки, голоса зрителей и серверы не тронутся. Программа перезапустится сама.</div>
      ${j && j.state === "error" ? `<div class="upd-err">✗ ${esc(j.error)}</div>`
        : UPD.error ? `<div class="upd-err">⚠ ${esc(UPD.error)}</div>` : ""}</div>`;
    return;
  }
  box.innerHTML = `<div class="upd-box"><div class="row">
      <span>${UPD.error ? "⚠ " + esc(UPD.error) : UPD.info ? "✅ У тебя последняя версия" : "Обновления ещё не проверялись"}</span>
      <div class="spacer"></div>
      <button class="small" onclick="updCheckNow(this)">🔄 Проверить обновления</button></div>
      ${UPD.repo ? `<div class="hint">Обновления берутся с GitHub: ${esc(UPD.repo)}</div>` : ""}</div>`;
}

// окно версии: что с обновлением + выбор режима автообновления
function updRender() {
  updRenderMain();
  const box = document.getElementById("updBox");
  if (!box || !UPD) return;
  const m = UPD.mode || "auto";
  const opt = (v, t, d) => `<label class="upd-mode${m === v ? " on" : ""}"><input type="radio" name="updMode" ${m === v ? "checked" : ""}
      onchange="updSetMode('${v}')"><span><b>${t}</b><span class="hint">${d}</span></span></label>`;
  box.insertAdjacentHTML("beforeend", `<div class="upd-modes"><div class="upd-mh">🔄 Автообновление</div>
    ${opt("auto", "Обновлять само", "проверка раз в 30 минут; есть новая версия и ты не в эфире — через 25 секунд обновится, можно отложить")}
    ${opt("on_start", "При следующем запуске", "новая версия тихо скачается заранее и поставится, когда снова откроешь программу")}
    ${opt("notify", "Только сообщать", "значок версии станет золотым — обновишься сам кнопкой")}
    ${UPD.ready ? `<div class="hint" style="margin-top:6px">✓ Версия ${esc(UPD.ready.version)} уже скачана — поставится при следующем запуске</div>` : ""}
    <div class="hint" style="margin-top:6px">Во время эфира программа никогда не обновляется — дождётся, пока ты отключишься.</div></div>`);
}

async function updCheckNow(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Проверяю…"; }
  await updLoad(true);
}

async function updInstall() {
  const d = await (await fetch("/api/update/install", {method: "POST"})).json();
  if (!d.ok) { alert(d.error); await updLoad(false); return; }   // и в самом окне — не «Доступна» как ни в чём не бывало
  updWaitFor(d.version);
}

let UPD_WAIT = null;
function updWaitFor(target) {                                   // ждём, пока программа перезапустится новой версией
  if (UPD_WAIT) return;
  const tick = UPD_WAIT = setInterval(async () => {
    try {
      const v = await (await fetch("/api/version", {cache: "no-store"})).json();
      if (v.version === target) { clearInterval(tick); updReload(); return; }
    } catch (e) { /* программа перезапускается — ждём */ }
    try { await updLoad(false); } catch (e) {}
  }, 1000);
  updLoad(false);
}

// ── Автообновление: полоска с обратным отсчётом, «Обновить сейчас» / «Не сейчас» ──
let UPD_LEFT = 0, UPD_COUNT = null;
function updBanner() {
  const el = document.getElementById("updBanner");
  if (!el || !UPD) return;
  const j = UPD.job;
  if (j && ["downloading", "extracting", "restarting"].includes(j.state) && !j.prefetch) {
    el.className = "upd-banner busy";
    el.innerHTML = `⬇ Обновляю TakyLive до ${esc(j.version)}… ${Math.round((j.progress || 0) * 100)}% — не закрывай окно, оно перезапустится само`;
    updWaitFor(j.version);
    return;
  }
  if (UPD.auto) {
    UPD_LEFT = UPD.auto.left;
    el.className = "upd-banner";
    el.innerHTML = `<span>⬆ Через <b id="updLeft">${UPD_LEFT}</b> с TakyLive обновится до <b>${esc(UPD.auto.version)}</b> и перезапустится</span>
      <span class="spacer"></span>
      <button class="small primary" onclick="updInstall()">Обновить сейчас</button>
      <button class="small" onclick="updPostpone()">Не сейчас</button>`;
    clearInterval(UPD_COUNT);
    UPD_COUNT = setInterval(() => {
      const b = document.getElementById("updLeft");
      if (!b) { clearInterval(UPD_COUNT); return; }
      UPD_LEFT = Math.max(0, UPD_LEFT - 1);
      b.textContent = UPD_LEFT;
      if (!UPD_LEFT) { clearInterval(UPD_COUNT); setTimeout(() => updLoad(false), 1500); }
    }, 1000);
    return;
  }
  clearInterval(UPD_COUNT);
  el.className = "upd-banner hidden";
  el.innerHTML = "";
}

async function updPostpone() {
  await fetch("/api/update/postpone", {method: "POST"});
  await updLoad(false);
}

async function updSetMode(m) {
  DATA.config.auto_update = m;
  await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({auto_update: m})});
  await updLoad(false);
}

setInterval(() => { if (typeof DATA !== "undefined" && DATA.config) updLoad(false); }, 20000);

// ── Перенос данных из другой папки: объединяет, ничего не затирает, можно отменить ──
let MIG_OPEN = false;
async function migRender() {
  const box = document.getElementById("stMigrate");
  if (!box) return;
  const empty = !Object.keys(DATA.profiles || {}).length;
  if (!empty && !MIG_OPEN) {
    box.innerHTML = `<div class="mig-link"><span onclick="MIG_OPEN=true; migRender()">📦 Перенести данные из другой папки программы</span></div>`;
    return;
  }
  let d = {items: [], current: null, backups: []};
  try { d = await (await fetch("/api/migrate/find", {cache: "no-store"})).json(); } catch (e) {}
  const items = d.items || [];
  const card = (x, i) => `<div class="mig-row${i === 0 ? " fresh" : ""}">
      <div class="mig-info"><span class="mono">${esc(x.path)}</span>
        <span class="hint">изменено ${esc(x.changed || "—")} · вкладок ${x.tabs} · зрителей с голосами ${x.viewers} · команд голосов ${x.voice_cmds}</span></div>
      ${i === 0 && items.length > 1 ? '<span class="mig-new">самая свежая</span>' : ""}
      <button class="small primary" onclick='migDo(${JSON.stringify(x.path)})'>Перенести</button></div>`;
  box.innerHTML = `<div class="mig-box">
    <div class="row"><div class="mig-title">📦 Перенос из другой папки программы</div><div class="spacer"></div>
      ${!empty ? `<button class="icon" onclick="MIG_OPEN=false; migRender()" title="Свернуть">✕</button>` : ""}</div>
    <div class="hint" style="margin-bottom:10px">Перенос <b>объединяет</b>: вкладки, зрители с голосами и команды голосов из обеих папок
      останутся, пустое не затрёт заполненное. Перед переносом делается резервная копия — можно отменить.
      ${d.current ? `Сейчас здесь: вкладок ${d.current.tabs}, зрителей ${d.current.viewers}, команд голосов ${d.current.voice_cmds}.` : ""}</div>
    ${items.map(card).join("") || '<div class="hint">На рабочем столе, в загрузках и документах других папок программы не нашлось.</div>'}
    <div class="mig-row"><input id="migPath" class="sx-in mono" placeholder="или вставь путь к папке, например C:\\Users\\…\\Desktop\\TikTok-Minecraft-Bridge">
      <button class="small" onclick="migDo(document.getElementById('migPath').value)">Перенести</button></div>
    <div class="hint" id="migHint"></div>
    ${(d.backups || []).length ? `<button class="small" onclick="migUndo()">↩ Отменить последний перенос</button>` : ""}</div>`;
}

async function migUndo() {
  if (!confirm("Вернуть данные, какими они были до последнего переноса?")) return;
  const d = await (await fetch("/api/migrate/undo", {method: "POST"})).json();
  const hint = document.getElementById("migHint");
  if (hint) hint.textContent = d.ok ? "✓ Перенос отменён" : "✗ " + d.error;
  if (d.ok) setTimeout(() => updReload(), 900);
}

async function migDo(path) {
  const hint = document.getElementById("migHint");
  if (!String(path || "").trim()) { hint.textContent = "✗ Укажи папку"; return; }
  hint.textContent = "Переношу…";
  const d = await (await fetch("/api/migrate", {method: "POST", headers: {"Content-Type": "application/json"},
                                                body: JSON.stringify({path})})).json();
  if (!d.ok) { hint.textContent = "✗ " + d.error; return; }
  hint.textContent = `✓ ${d.copied.join("; ")}`;
  setTimeout(() => updReload(), 2500);
}
