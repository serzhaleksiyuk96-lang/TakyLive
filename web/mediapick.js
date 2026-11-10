// ── Медиа: окно выбора видео / картинок / звуков с превью, загрузкой и «починкой» видео ──
const MP = {idx: null, slot: "screen", tab: "video", q: "", uploads: [], poll: null};

async function mpLoad() {
  try {
    const d = await (await fetch("/api/media_list", {cache: "no-store"})).json();
    MEDIA_FILES = d.files || [];
    return d;
  } catch (e) { return {}; }
}

async function openMediaPick(idx, slot) {
  MP.idx = idx; MP.slot = slot; MP.q = "";
  MP.tab = slot === "sound" ? "sound" : (MP.tab === "sound" ? "video" : MP.tab);
  document.getElementById("mediaPickModal").classList.remove("hidden");
  await mpLoad();
  mpRender();
  mpWatch();
}

function closeMediaPick() {
  document.getElementById("mediaPickModal").classList.add("hidden");
  clearInterval(MP.poll); MP.poll = null;
  document.querySelectorAll("#mpBody video").forEach(v => v.pause());
  if (MP.audio) { MP.audio.pause(); MP.audio = null; }
}

// пока что-то обрабатывается или создаются превью — обновляем список
function mpWatch() {
  clearInterval(MP.poll);
  MP.poll = setInterval(async () => {
    if (document.getElementById("mediaPickModal").classList.contains("hidden")) { clearInterval(MP.poll); return; }
    const busy = MEDIA_FILES.some(f => f.job && f.job.state === "processing") || MP.uploads.some(u => u.state !== "done");
    const d = await mpLoad();
    if (busy || d.busy) mpRender(true);
  }, 1200);
}

function mpCur() { return (curList() || [])[MP.idx] || {}; }

function mpRender(keepScroll) {
  const body = document.getElementById("mpBody");
  const grid = body.querySelector(".mp-grid");
  const st = keepScroll && grid ? grid.scrollTop : 0;
  const a = mpCur();
  const title = (a.title || a.name || a.trigger || "события").replace(/^💀\s*/, "");
  document.getElementById("mpTitle").textContent = MP.slot === "sound" ? `Звук для «${title}»` : `Медиа на экран для «${title}»`;
  const tabs = MP.slot === "sound" ? [["sound", "🔊 Звуки"]] : [["video", "🎬 Видео"], ["image", "🖼 Картинки и гифки"]];
  const cnt = k => MEDIA_FILES.filter(f => k === "image" ? ["image", "gif"].includes(f.kind) : f.kind === k).length;
  document.getElementById("mpTabs").innerHTML = tabs.map(([k, n]) =>
    `<span class="ip-tab${MP.tab === k ? " active" : ""}" onclick="MP.tab='${k}'; mpRender()">${n} <b>${cnt(k)}</b></span>`).join("");
  const q = MP.q.trim().toLowerCase();
  const list = MEDIA_FILES.filter(f => (MP.tab === "image" ? ["image", "gif"].includes(f.kind) : f.kind === MP.tab))
                          .filter(f => !q || f.name.toLowerCase().includes(q))
                          .sort((x, y) => (y.mtime || 0) - (x.mtime || 0) || x.name.localeCompare(y.name));
  const sel = MP.slot === "sound" ? a.sound_file : a.media_file;
  const ups = MP.uploads.filter(u => u.state !== "done").map(u => `<div class="mp-card up">
      <div class="mp-thumb"><div class="mp-spin">⬆</div></div>
      <div class="mp-name">${esc(u.name)}</div>
      <div class="mp-bar"><i style="width:${Math.round(u.p * 100)}%"></i></div>
      <div class="mp-meta">${u.state === "error" ? "✗ " + esc(u.error) : "загрузка " + Math.round(u.p * 100) + "%"}</div></div>`).join("");
  body.innerHTML = `
    <div class="mp-top">
      <input class="sx-in" placeholder="🔎 Поиск по имени" value="${esc(MP.q)}"
             oninput="MP.q=this.value; mpRender(); const s=this; setTimeout(()=>{const i=document.querySelector('#mpBody .mp-top input'); i.focus(); i.setSelectionRange(i.value.length,i.value.length)})">
      <button class="primary" onclick="document.getElementById('mpFile').click()">⬆ Загрузить с ПК</button>
    </div>
    <div class="mp-drop" id="mpDrop">Перетащи файлы сюда — видео любой длины и формата (с телефона, из Telegram, с iPhone): программа сама подготовит их для OBS</div>
    <div class="mp-grid">
      ${MP.slot !== "sound" ? `<div class="mp-card none${!sel ? " sel" : ""}" onclick="mpChoose('')"><div class="mp-thumb"><span>—</span></div>
        <div class="mp-name">Без медиа</div><div class="mp-meta">только звук или ничего</div></div>` :
        `<div class="mp-card none${!sel ? " sel" : ""}" onclick="mpChoose('')"><div class="mp-thumb"><span>🔇</span></div>
        <div class="mp-name">Без звука</div><div class="mp-meta">&nbsp;</div></div>`}
      ${ups}
      ${list.map(f => mpCard(f, f.name === sel)).join("") || `<div class="hint" style="grid-column:1/-1">${q ? "Ничего не нашлось." : "Пока пусто — загрузи файлы кнопкой выше или перетащи их в окно."}</div>`}
    </div>`;
  const g2 = body.querySelector(".mp-grid");
  if (g2 && st) g2.scrollTop = st;
}

function mpCard(f, selected) {
  const n = JSON.stringify(f.name).replace(/"/g, "&quot;");
  const job = f.job;
  let thumb;
  if (job && job.state === "processing") {
    thumb = `<div class="mp-proc"><div class="mp-spin">⚙</div><div>Готовлю для OBS… ${Math.round((job.progress || 0) * 100)}%</div></div>`;
  } else if (f.kind === "video") {
    thumb = (f.thumb ? `<img src="${mediaUrl(f.thumb)}" alt="" loading="lazy">` : `<span>🎬</span>`) +
      `<video muted loop playsinline preload="none" data-src="${mediaUrl(f.name)}"></video><i class="mp-play">▶</i>`;
  } else if (f.kind === "sound") {
    thumb = `<span class="mp-note">🎵</span><button class="mp-listen" onclick="event.stopPropagation(); mpListen(${n}, this)">▶</button>`;
  } else {
    thumb = `<img src="${mediaUrl(f.name)}" alt="" loading="lazy">`;
  }
  const dur = f.duration ? `<b class="mp-dur">${fmtDur(f.duration)}</b>` : (f.kind === "gif" ? `<b class="mp-dur">GIF</b>` : "");
  const res = f.w && f.h ? ` · ${f.w}×${f.h}` : "";
  const fix = f.kind === "video" && f.fix && !(job && job.state === "processing")
    ? `<button class="mp-fix" onclick="event.stopPropagation(); mpFix(${n})" title="Видео может не играть в OBS — подготовить">🔧 починить</button>` : "";
  const err = job && job.state === "error" ? `<div class="mp-err">✗ ${esc(job.error)}</div>` : "";
  return `<div class="mp-card${selected ? " sel" : ""}" onclick="mpChoose(${n})"
              onmouseenter="mpHover(this, true)" onmouseleave="mpHover(this, false)">
    <div class="mp-thumb">${thumb}${dur}</div>
    <div class="mp-name" title="${esc(f.name)}">${esc(f.name.split("/").pop())}</div>
    <div class="mp-meta">${fmtSize(f.size)}${res}</div>${fix}${err}
    ${f.name.includes("/") ? "" : `<button class="mp-del" onclick="event.stopPropagation(); mpDelete(${n})" title="Удалить файл">🗑</button>`}
  </div>`;
}

// наведение на видео — живое превью без звука
function mpHover(card, on) {
  const v = card.querySelector("video");
  if (!v) return;
  if (on) { if (!v.src) v.src = v.dataset.src; v.style.opacity = 1; v.play().catch(() => {}); }
  else { v.pause(); v.style.opacity = 0; }
}

function mpListen(name, btn) {
  if (MP.audio) { MP.audio.pause(); const was = MP.audio.dataset.name; MP.audio = null;
                  document.querySelectorAll(".mp-listen").forEach(b => b.textContent = "▶"); if (was === name) return; }
  MP.audio = new Audio(mediaUrl(name)); MP.audio.dataset.name = name;
  MP.audio.play().catch(() => {}); btn.textContent = "■";
  MP.audio.onended = () => { btn.textContent = "▶"; MP.audio = null; };
}

function mpChoose(name) {
  const a = mpCur();
  if (MP.slot === "sound") a.sound_file = name;
  else {
    a.media_file = name;
    const f = MEDIA_FILES.find(x => x.name === name);
    a.media_kind = f ? f.kind : "";
  }
  closeMediaPick();
  renderCards();
  if (typeof scheduleSave === "function") scheduleSave();
}

async function mpDelete(name) {
  const used = Object.values(DATA.profiles || {}).some(p => Object.values(p || {}).some(sec => Array.isArray(sec) &&
                 sec.some(a => a && (a.media_file === name || a.sound_file === name))));
  if (!confirm(`Удалить «${name}»?` + (used ? "\n\nОн используется в событиях — там станет «без медиа»." : ""))) return;
  await fetch("/api/media_delete", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name})});
  await mpLoad(); mpRender(true);
}

async function mpFix(name) {
  await fetch("/api/media/fix", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name})});
  await mpLoad(); mpRender(true); mpWatch();
}

// загрузка: кнопкой и перетаскиванием, с полосой прогресса
function mpUploadFiles(files) {
  for (const file of files) {
    const u = {name: file.name, p: 0, state: "up", error: ""};
    MP.uploads.push(u);
    const fd = new FormData(); fd.append("file", file);
    const x = new XMLHttpRequest();
    x.open("POST", "/api/media_upload");
    x.upload.onprogress = e => { if (e.lengthComputable) { u.p = e.loaded / e.total; mpRender(true); } };
    x.onload = async () => {
      let d = {}; try { d = JSON.parse(x.responseText); } catch (e) {}
      u.state = d.ok ? "done" : "error"; u.error = d.error || "не загрузилось";
      if (d.ok) {
        if (["video", "image", "gif"].includes(d.kind) && MP.slot !== "sound") MP.tab = d.kind === "video" ? "video" : "image";
        if (d.kind === "sound") MP.tab = "sound";
      }
      await mpLoad(); mpRender(true); mpWatch();
    };
    x.onerror = () => { u.state = "error"; u.error = "нет связи с программой"; mpRender(true); };
    x.send(fd);
  }
  mpRender(true);
}

document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("mediaPickModal");
  if (!modal) return;
  ["dragenter", "dragover"].forEach(ev => modal.addEventListener(ev, e => { e.preventDefault(); modal.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach(ev => modal.addEventListener(ev, e => { e.preventDefault(); if (ev === "drop" || e.target === modal) modal.classList.remove("dragging"); }));
  modal.addEventListener("drop", e => { if (e.dataTransfer && e.dataTransfer.files.length) mpUploadFiles(e.dataTransfer.files); });
});
