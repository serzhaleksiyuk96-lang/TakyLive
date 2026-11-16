// 🎙 ИИ-голос стримера: мастер установки и управление голосовой программой (deiteris/voice-changer).
// Сервер: /api/vc/* (app.py) → voicechanger.py.

let VC = null, vcTimer = null, vcModelFile = null, VC_PRESETS = null;
const vcEl = id => document.getElementById(id);

function vcOpen() {
  const c = DATA.config;
  iaChk("vc_autostart", c.vc_autostart); iaChk("vc_say", c.vc_say !== false); iaVal("vc_secs", c.vc_secs ?? 30);
  vcRefresh();
  clearInterval(vcTimer);
  vcTimer = setInterval(() => {                          // пока открыта вкладка — следим за установкой/запуском
    if (document.getElementById("view-interactive")?.classList.contains("hidden")) { clearInterval(vcTimer); return; }
    vcRefresh();
  }, 2500);
}

async function vcApi(path, body) {
  const opt = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  return (await fetch("/api/vc/" + path, opt)).json();
}

function vcStep(n, state) {                              // ok | todo | off | ""
  const li = vcEl("vcS" + n);
  if (li) li.className = state || "";
}

async function vcRefresh(force) {
  try { VC = await vcApi("status"); } catch (e) { return; }
  const s = VC, c = DATA.config;
  const badge = vcEl("vcBadge");
  // 1. Видеокарта
  const nv = s.nvidia || {};
  if (!s.platform_ok) {
    vcEl("vcGpu").textContent = "ИИ-голос работает только на Windows";
    [1, 2, 3, 4, 5, 6].forEach(n => vcStep(n, "off"));
    badge.textContent = "только Windows"; return;
  }
  if (nv.ok) {
    vcEl("vcGpu").innerHTML = `✓ ${esc(nv.name)} · драйвер ${esc(nv.driver)}` +
      (nv.driver_ok ? "" : ` — <b>обнови драйвер NVIDIA</b> (нужен 528.33 или новее)`);
    vcStep(1, nv.driver_ok ? "ok" : "todo");
  } else {
    vcEl("vcGpu").innerHTML = "Видеокарта NVIDIA не найдена — поставлю версию для любой видеокарты (DirectML), но она медленнее";
    vcStep(1, "todo");
  }
  // 2. Программа
  const ins = s.install || {};
  const bar = vcEl("vcBar"), btns = vcEl("vcProgBtns");
  if (ins.running) {
    const pct = ins.total ? Math.floor(ins.done / ins.total * 100) : 0;
    const gb = x => (x / 1073741824).toFixed(2);
    vcEl("vcProg").textContent = ins.stage + (ins.total && ins.total > 10000 ? ` — ${gb(ins.done)} из ${gb(ins.total)} ГБ (${pct}%)`
                                              : ins.total ? ` — ${pct}%` : "");
    bar.classList.remove("hidden"); vcEl("vcBarFill").style.width = pct + "%";
    btns.innerHTML = `<button class="small" onclick="vcApi('install_cancel', {})">✕ Отменить</button>`;
    vcStep(2, "todo"); badge.textContent = "ставлю…";
  } else {
    bar.classList.add("hidden");
    if (s.running) {
      vcEl("vcProg").innerHTML = "✓ Работает" + (s.ours ? "" : " (осталась с прошлого запуска)");
      btns.innerHTML = `<button class="small" onclick="vcStartStop(false)">⏹ Остановить</button>`;
      vcStep(2, "ok");
    } else if (!s.installed) {
      vcEl("vcProg").innerHTML = (ins.error ? `<span style="color:#f87171">✗ ${esc(ins.error)}</span> · ` : "") +
        "Не установлена (≈3–4 ГБ, скачается с GitHub)";
      btns.innerHTML = `<button class="small primary" onclick="vcInstall()">⬇ Скачать и установить</button>`;
      vcStep(2, "todo");
    } else if (s.starting) {
      const st = s.start || {};
      const mm = Math.floor((st.secs || 0) / 60), ss = String((st.secs || 0) % 60).padStart(2, "0");
      vcEl("vcProg").textContent = `Запускается… ${mm}:${ss}. В первый раз программа качает свои файлы (≈1 ГБ)` +
        (st.mb ? ` — уже ${st.mb} МБ` : "") + (st.note ? `. ${st.note[0].toUpperCase() + st.note.slice(1)}` : "") +
        ". Ждать у окна не нужно";
      btns.innerHTML = `<button class="small" onclick="vcStartStop(false)">✕ Отменить</button>`;
      vcStep(2, "todo");
    } else {
      const err = (s.start || {}).error;
      vcEl("vcProg").innerHTML = (err ? `<span style="color:#f87171">✗ ${esc(err)}</span> · ` : "") + "Установлена, не запущена";
      btns.innerHTML = `<button class="small primary" onclick="vcStartStop(true)">▶ Запустить</button>`;
      vcStep(2, "todo");
    }
  }
  const inf = s.info;
  // 3. Кабель
  if (!s.running) {
    vcEl("vcCable").textContent = "проверю, когда запустится голосовая программа";
    vcStep(3, "off");
  } else if (s.cable) {
    vcEl("vcCable").textContent = "✓ VB-CABLE есть";
    vcStep(3, "ok");
  } else {
    vcEl("vcCable").innerHTML = `Нужен бесплатный VB-CABLE: через него ИИ-голос попадёт в OBS.
      <button class="small primary" onclick="vcCable(this)">⬇ Установить VB-CABLE</button>
      <span class="hint">Windows спросит разрешение → «Да» → Install Driver → перезагрузи ПК</span>`;
    vcStep(3, "todo");
  }
  // 4. Звук
  const on = inf && inf.settings && +inf.settings.serverAudioStated === 1;
  if (inf) {
    vcFill("vcMic", inf.inputs, c.vc_mic_name, "— выбери —");
    vcFill("vcOut", inf.outputs, c.vc_out_name || (inf.outputs.find(d => /cable input/i.test(d.name)) || {}).name, "— выбери —");
    vcFill("vcMon", inf.outputs, c.vc_monitor_name, "не слышать");
  }
  vcStep(4, !s.running ? "off" : on ? "ok" : "todo");
  vcEl("vcOnBtn").textContent = on ? "↻ Применить" : "▶ Включить ИИ-голос";
  // 5. Голоса
  const slots = (inf && inf.slots) || [];
  const act = s.active;
  if (!vcEl("vcVoices").contains(document.activeElement))          // не перерисовываем, пока выбирают высоту
  vcEl("vcVoices").innerHTML = !s.running ? `<span class="hint">появятся, когда запустится голосовая программа</span>`
    : slots.length ? slots.map(v => `<span class="vc-voice${act && act.name === v.name ? " on" : ""}">${esc(v.name)}
          ${vcTuneSel(v.name, (inf.tunes || {})[v.name] || 0)}
          <button class="small" title="Включить на 10 секунд" onclick="vcTry(${JSON.stringify(v.name).replace(/"/g, "&quot;")})">▶ 10 с</button>
          <button class="small" title="Скопировать команду для подарка" onclick="vcCopy(${JSON.stringify(v.name).replace(/"/g, "&quot;")})">📋</button></span>`).join("")
    : `<span class="hint">Пока нет голосов — добавь .pth</span>`;
  vcPresetsRender(slots, s.running);
  const nsel = vcEl("vcNormal");
  if (document.activeElement !== nsel)
    nsel.innerHTML = `<option value="">🙂 Мой голос (без ИИ)</option>` +
      slots.map(v => `<option value="${esc(v.name)}"${c.vc_normal === v.name ? " selected" : ""}>🎙 ${esc(v.name)}</option>`).join("");
  vcStep(5, !s.running ? "off" : slots.length ? "ok" : "todo");
  vcStep(6, slots.length && on ? "ok" : "");
  badge.textContent = act ? `🎙 «${act.name}» ${act.left} с` : on ? "включён" : s.running ? "не включён" : s.installed ? "не запущен" : "не установлен";
}

function vcFill(id, devs, cur, empty) {
  const el = vcEl(id);
  if (!el || document.activeElement === el) return;
  el.innerHTML = `<option value="">${empty}</option>` +
    (devs || []).map(d => `<option value="${esc(d.name)}"${d.name === cur ? " selected" : ""}>${esc(d.name)}</option>`).join("");
}

async function vcInstall() {
  const nv = (VC && VC.nvidia) || {};
  if (!confirm(`Скачать голосовую программу (≈3–4 ГБ) с GitHub (deiteris/voice-changer)` +
               (nv.ok ? ` для ${nv.name}?` : " в версии для любой видеокарты?") +
               "\n\nКуда: " + (VC ? VC.dir : "") + "\nЭто займёт время — можно пользоваться программой дальше.")) return;
  await vcApi("install", {});
  vcRefresh();
}

async function vcStartStop(start) {
  const r = await vcApi(start ? "start" : "stop", {});
  if (r && r.ok === false) alert("Не запустилась: " + r.error);
  else if (r && r.error) alert(r.error);
  vcRefresh();
}

// высота голоса: мужской голос + женская модель обычно звучит правильно на +12, наоборот — на −12
function vcTuneSel(name, cur) {
  const vals = [-12, -8, -5, -3, 0, 3, 5, 8, 12];
  if (!vals.includes(cur)) vals.push(cur);
  vals.sort((a, b) => a - b);
  const lab = t => t === 0 ? "высота 0" : t === 12 ? "+12 выше" : t === -12 ? "−12 ниже" : (t > 0 ? "+" : "−") + Math.abs(t);
  return `<select class="vc-tune" title="Высота голоса в полутонах. Мужской голос → женская модель: +12. Женский → мужская: −12"
    onchange="vcTune(${JSON.stringify(name).replace(/"/g, "&quot;")}, this)">` +
    vals.map(t => `<option value="${t}"${t === cur ? " selected" : ""}>${lab(t)}</option>`).join("") + `</select>`;
}

async function vcTune(name, sel) {
  const r = await vcApi("tune", {name, tune: +sel.value});
  if (r.ok) DATA.config.vc_tune = r.tunes;                 // чтобы общее сохранение настроек не затёрло
  else alert(r.error);
  sel.blur();
  vcRefresh();
}

async function vcCable(btn) {
  btn.disabled = true;
  const r = await vcApi("cable", {});
  btn.disabled = false;
  if (!r.ok) alert("VB-CABLE: " + r.error);
  else alert("Установщик VB-CABLE открыт.\n\n1. Windows спросит разрешение — «Да».\n2. Нажми «Install Driver».\n3. Перезагрузи компьютер.");
}

async function vcAudio(off) {
  const hint = vcEl("vcAudioHint");
  if (off) { await vcApi("audio", {off: true}); hint.textContent = "ИИ-голос выключен"; vcRefresh(); return; }
  const body = {vc_mic_name: vcEl("vcMic").value, vc_out_name: vcEl("vcOut").value, vc_monitor_name: vcEl("vcMon").value};
  Object.assign(DATA.config, body);                       // чтобы общее сохранение настроек не затёрло выбор
  hint.textContent = "Включаю…";
  const r = await vcApi("audio", body);
  hint.textContent = r.ok ? `✓ ${r.mic} → ${r.out}` + (r.monitor ? ` · слышно в ${r.monitor}` : "") : "✗ " + r.error;
  vcRefresh();
}

async function vcTry(name) {
  const r = await vcApi("voice", {name, secs: 10});
  if (!r.ok) alert(r.error);
  vcRefresh();
}

function vcCopy(name) {
  const cmd = `voice:${name}:${DATA.config.vc_secs || 30}`;
  (navigator.clipboard ? navigator.clipboard.writeText(cmd) : Promise.reject()).then(
    () => { vcEl("vcUpHint").textContent = `Скопировано: ${cmd} — вставь в команды подарка`; },
    () => prompt("Команда для подарка:", cmd));
}

async function vcNormal(name) {
  DATA.config.vc_normal = name;
  const r = await vcApi("normal", {name});
  if (!r.ok) vcEl("vcAudioHint").textContent = "✗ " + r.error;
}

function vcPickModel(inp) {
  vcModelFile = inp.files && inp.files[0];
  inp.value = "";
  if (!vcModelFile) return;
  if (confirm(`Голос: ${vcModelFile.name}\n\nЕсть к нему файл .index? Он делает голос похожее.\nОК — выбрать .index, Отмена — загрузить без него.`))
    vcEl("vcIndex").click();
  else vcUpload();
}

async function vcUpload() {
  const idx = vcEl("vcIndex").files && vcEl("vcIndex").files[0];
  vcEl("vcIndex").value = "";
  if (!vcModelFile) return;
  const hint = vcEl("vcUpHint");
  hint.textContent = "Загружаю голос… (большие файлы — до минуты)";
  const fd = new FormData();
  fd.append("slot", "auto");
  fd.append("model", vcModelFile, vcModelFile.name);
  if (idx) fd.append("index", idx, idx.name);
  try {
    const r = await (await fetch("/api/vc/upload", {method: "POST", body: fd})).json();
    hint.textContent = r.ok ? `✓ Голос загружен (слот ${r.slot}). Имя голоса — как у файла; переименовать можно в окне голосовой программы`
                            : "✗ " + r.error;
  } catch (e) { hint.textContent = "✗ " + e.message; }
  vcModelFile = null;
  vcRefresh();
}

async function vcOpenUi() {
  if (!VC || !VC.running) { alert("Сначала запусти голосовую программу (шаг 2)"); return; }
  await vcApi("open", {});
}

// ── 🔎 Библиотека голосов (модели RVC на Hugging Face) ─────────────────────────
function vcHubToggle() {
  const box = vcEl("vcHub");
  box.classList.toggle("hidden");
  if (!box.classList.contains("hidden") && !VC_HUB_ITEMS.length) vcHubSearch();   // как в каталоге Fish — сразу популярные
}

function vcSize(b) { return !b ? "" : b > 1073741824 ? (b / 1073741824).toFixed(1) + " ГБ" : Math.max(1, Math.round(b / 1048576)) + " МБ"; }

let VC_HUB_ITEMS = [], VC_HUB_SHOWN = 0;
const VC_HUB_PAGE = 30;

async function vcHubSearch() {
  const q = vcEl("vcHubQ").value.trim(), hint = vcEl("vcHubHint"), sort = vcEl("vcHubSort").value;
  if (q.length === 1) { hint.textContent = "Впиши хотя бы 2 буквы"; return; }
  hint.textContent = q ? "Ищу…" : "Загружаю каталог…";
  vcEl("vcHubList").innerHTML = ""; vcEl("vcHubMore").classList.add("hidden");
  let r;
  try { r = await (await fetch(`/api/vc/hub/search?q=${encodeURIComponent(q)}&sort=${sort}`)).json(); }
  catch (e) { hint.textContent = "✗ " + e.message; return; }
  if (!r.ok) { hint.textContent = "✗ " + r.error; return; }
  VC_HUB_ITEMS = r.items; VC_HUB_SHOWN = 0;
  const asked = r.terms && r.terms.length && r.terms.join(" ") !== q.toLowerCase() ? `Искал: ${r.terms.join(", ")}` +
    (r.unknown && r.unknown.length ? ` (не понял: ${r.unknown.join(", ")})` : "") + ". " : "";
  hint.textContent = asked + (r.items.length ? (r.browse ? `В каталоге: ${r.items.length}. ` : `Найдено: ${r.items.length}. `) +
    "«Открыть» — выбрать голос" : "Ничего не нашлось — попробуй другое слово, лучше по-английски");
  vcHubMore();
}

function vcHubMore() {
  const list = vcEl("vcHubList");
  const part = VC_HUB_ITEMS.slice(VC_HUB_SHOWN, VC_HUB_SHOWN + VC_HUB_PAGE);
  list.insertAdjacentHTML("beforeend", part.map((m, k) => {
    const i = VC_HUB_SHOWN + k;
    const [owner, name] = m.id.split("/");
    return `<div><div class="vc-hub-row"><span class="nm" title="${esc(m.id)}">${esc(name)} <span class="st">· ${esc(owner)}</span></span>
      <span class="st">⬇ ${m.downloads} · ♥ ${m.likes}</span>
      <button class="small" onclick="vcHubOpen(${i}, ${JSON.stringify(m.id).replace(/"/g, "&quot;")})">Открыть</button></div>
      <div class="vc-hub-files" id="vcHubF${i}"></div></div>`;
  }).join(""));
  VC_HUB_SHOWN += part.length;
  vcEl("vcHubMore").classList.toggle("hidden", VC_HUB_SHOWN >= VC_HUB_ITEMS.length);
  vcEl("vcHubMore").textContent = `Показать ещё (${VC_HUB_ITEMS.length - VC_HUB_SHOWN})`;
}

let VC_HUB = {};
async function vcHubOpen(i, repo) {
  const box = vcEl("vcHubF" + i);
  if (box.innerHTML) { box.innerHTML = ""; return; }
  box.innerHTML = `<span class="hint">Смотрю файлы…</span>`;
  const r = await (await fetch("/api/vc/hub/files?repo=" + encodeURIComponent(repo))).json();
  if (!r.ok) { box.innerHTML = `<span class="hint">✗ ${esc(r.error)}</span>`; return; }
  VC_HUB[repo] = r;
  const lic = r.license ? `Лицензия: <b>${esc(r.license)}</b>` : "Лицензия не указана — уточни у автора";
  box.innerHTML = `<div class="hint">${lic} · <a href="${esc(r.url)}" target="_blank" rel="noopener">страница модели</a></div>` +
    (r.candidates.length ? r.candidates.map((c, j) => `<div class="vc-hub-row">
        <span class="nm">${c.zip ? "📦" : "🎙"} ${esc(c.label)}</span>
        <span class="st">${c.zip ? "архив" : c.index ? ".pth + .index" : ".pth"} ${vcSize(c.size)}</span>
        <button class="small primary" onclick="vcHubInstall(${JSON.stringify(repo).replace(/"/g, "&quot;")}, ${j})">⬇ Поставить</button></div>`).join("")
      : `<span class="hint">В этой модели нет файлов голоса (.pth или .zip)</span>`);
}

async function vcHubInstall(repo, j) {
  if (!VC || !VC.running) { alert("Сначала запусти голосовую программу (шаг 2)"); return; }
  const c = VC_HUB[repo].candidates[j];
  const name = prompt("Как назвать голос? (это имя пойдёт в команду voice:Имя:секунды)", c.label);
  if (name === null) return;
  const r = await (await fetch("/api/vc/hub/install", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({repo, model: c.model, index: c.index, zip: c.zip, name: name.trim() || c.label})})).json();
  if (!r.ok) { alert(r.error); return; }
  vcHubWatch();
}

let vcHubTimer = null;
function vcHubWatch() {
  clearInterval(vcHubTimer);
  const hint = vcEl("vcUpHint");
  vcHubTimer = setInterval(async () => {
    const s = await vcApi("status");
    const h = s.hub || {};
    if (h.running) {
      hint.textContent = h.stage + (h.total ? ` — ${Math.floor(h.done / h.total * 100)}%` : h.done ? ` — ${vcSize(h.done)}` : "");
      return;
    }
    clearInterval(vcHubTimer);
    hint.textContent = h.error ? "✗ " + h.error : h.ok || "Готово";
    vcRefresh();
  }, 1000);
}

// ── ⭐ Рекомендуемые голоса (ссылки на Hugging Face) ───────────────────────────
async function vcPresetsRender(slots, running) {
  if (VC_PRESETS === null) {
    VC_PRESETS = [];
    try { VC_PRESETS = (await (await fetch("/api/vc/presets")).json()).voices || []; } catch (e) {}
  }
  const box = vcEl("vcPresets");
  box.classList.toggle("hidden", !VC_PRESETS.length);
  if (!VC_PRESETS.length) return;
  const have = new Set((slots || []).map(v => v.name.toLowerCase()));
  vcEl("vcPresetList").innerHTML = VC_PRESETS.map((p, i) => {
    const ok = have.has(p.name.toLowerCase());
    return `<div class="vc-preset" title="${esc(p.repo)} · лицензия ${esc(p.license || "?")}">
      <span class="em">${esc(p.emoji)}</span>
      <div class="tx"><b>${esc(p.name)}</b><span>${esc(p.desc || p.repo)}${p.size_mb ? " · " + p.size_mb + " МБ" : ""}</span></div>
      ${ok ? `<span class="hint">✓ есть</span>`
           : `<button class="small primary" ${running ? "" : "disabled"} title="${running ? "Скачать и поставить" : "Сначала запусти голосовую программу (шаг 2)"}" onclick="vcPresetInstall(${i})">⬇</button>`}</div>`;
  }).join("");
}

async function vcPresetInstall(i) {
  const p = VC_PRESETS[i];
  const r = await (await fetch("/api/vc/hub/install", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({repo: p.repo, model: p.model, index: p.index, zip: p.zip, name: p.name, auto: !!p.auto})})).json();
  if (!r.ok) { alert(r.error); return; }
  vcHubWatch();
}
