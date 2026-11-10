// ── Обновления через GitHub и перенос данных из старой папки ────────────────
let UPD = null;
function updReload() { location.reload(); }

async function updLoad(force) {
  try {
    UPD = await (await fetch(force ? "/api/update/check" : "/api/update/status",
                             {method: force ? "POST" : "GET", cache: "no-store"})).json();
  } catch (e) { return; }
  updBadge();
  if (!document.getElementById("changelogModal").classList.contains("hidden")) updRender();
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

function updRender() {
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
    box.innerHTML = `<div class="upd-box avail"><div class="row"><b>⬆ Доступна версия ${esc(i.version)}</b>
        <span class="hint" style="margin-left:8px">${esc(i.date || "")} · ${(i.size / 1048576).toFixed(0)} МБ</span>
        <div class="spacer"></div>
        <button class="primary" onclick="updInstall()">Обновить</button></div>
      ${i.notes ? `<div class="upd-notes">${esc(i.notes).replace(/\n/g, "<br>")}</div>` : ""}
      <div class="hint">Настройки, вкладки, голоса зрителей и серверы не тронутся. Программа перезапустится сама.</div>
      ${j && j.state === "error" ? `<div class="upd-err">✗ ${esc(j.error)}</div>` : ""}</div>`;
    return;
  }
  box.innerHTML = `<div class="upd-box"><div class="row">
      <span>${UPD.error ? "⚠ " + esc(UPD.error) : UPD.info ? "✅ У тебя последняя версия" : "Обновления ещё не проверялись"}</span>
      <div class="spacer"></div>
      <button class="small" onclick="updCheckNow(this)">🔄 Проверить обновления</button></div>
      ${UPD.repo ? `<div class="hint">Обновления берутся с GitHub: ${esc(UPD.repo)}</div>` : ""}</div>`;
}

async function updCheckNow(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Проверяю…"; }
  await updLoad(true);
}

async function updInstall() {
  const d = await (await fetch("/api/update/install", {method: "POST"})).json();
  if (!d.ok) { alert(d.error); return; }
  const target = d.version;
  const tick = setInterval(async () => {
    try {
      const v = await (await fetch("/api/version", {cache: "no-store"})).json();
      if (v.version === target) { clearInterval(tick); updReload(); return; }
    } catch (e) { /* программа перезапускается — ждём */ }
    try { await updLoad(false); } catch (e) {}
  }, 1000);
  updLoad(false);
}

// ── Перенос данных: для установленной версии со старой папки ──
async function migRender() {
  const box = document.getElementById("stMigrate");
  if (!box) return;
  if (Object.keys(DATA.profiles || {}).length) { box.innerHTML = ""; return; }
  let items = [];
  try { items = (await (await fetch("/api/migrate/find", {cache: "no-store"})).json()).items || []; } catch (e) {}
  box.innerHTML = `<div class="mig-box">
    <div class="mig-title">📦 Пользовался программой раньше? Перенеси вкладки, настройки, голоса зрителей и серверы</div>
    ${items.map(x => `<div class="mig-row"><span class="mono">${esc(x.path)}</span>
        <span class="hint">вкладок: ${x.tabs}</span>
        <button class="small primary" onclick='migDo(${JSON.stringify(x.path)})'>Перенести</button></div>`).join("")}
    <div class="mig-row"><input id="migPath" class="sx-in mono" placeholder="или вставь путь к старой папке, например C:\\Users\\…\\Desktop\\TikTok-Minecraft-Bridge">
      <button class="small" onclick="migDo(document.getElementById('migPath').value)">Перенести</button></div>
    <div class="hint" id="migHint"></div></div>`;
}

async function migDo(path) {
  const hint = document.getElementById("migHint");
  if (!String(path || "").trim()) { hint.textContent = "✗ Укажи папку"; return; }
  hint.textContent = "Переношу…";
  const d = await (await fetch("/api/migrate", {method: "POST", headers: {"Content-Type": "application/json"},
                                                body: JSON.stringify({path})})).json();
  if (!d.ok) { hint.textContent = "✗ " + d.error; return; }
  hint.textContent = `✓ Перенесено: ${d.copied.join(", ")} — вкладок: ${d.tabs}`;
  setTimeout(() => updReload(), 1200);
}
