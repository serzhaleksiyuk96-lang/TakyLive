// ── Итоги эфира, пульт с телефона, анонсы в Telegram и Discord ─────────────

function openReport(id) {
  window.open("/web/report.html" + (id ? "?id=" + encodeURIComponent(id) : ""), "takylive_report",
              "width=1120,height=860");
}

const lvNum = n => Math.round(Number(n || 0)).toLocaleString("ru-RU");
const lvDur = s => { const m = Math.floor((s || 0) / 60); return m >= 60 ? `${Math.floor(m / 60)} ч ${String(m % 60).padStart(2, "0")} мин` : `${m} мин`; };

// ── Плитка «📊 Итоги эфира» на Панели ──
async function lvStats() {
  let d;
  try { d = await (await fetch("/api/stats/current", {cache: "no-store"})).json(); } catch (e) { return; }
  lvEndRender();
  const r = d.report, badge = document.getElementById("stBadge"), box = document.getElementById("stKpis");
  if (!badge || !box) return;
  badge.textContent = r ? "идёт · " + lvDur(r.duration) : "нет эфира";
  badge.classList.toggle("on", !!r);
  if (!r) return;
  const k = (v, l) => `<div class="lv-kpi"><b>${v}</b><span>${l}</span></div>`;
  box.innerHTML = k(lvNum(r.totals.coins), "💎 монет") + k(lvNum(r.totals.likes), "❤ лайков") +
    k(lvNum(r.totals.comments), "💬 сообщений") + k(r.viewers_now ? lvNum(r.viewers_now) : "—", "👀 зрителей");
}

// ── Кнопка «📣 Итоги в чаты»: слать ли итоги в Telegram / Discord после эфира ──
function lvChannels() {
  const c = DATA.config, out = [];
  if (c.ann_tg_on && String(c.ann_tg_token || "").trim() && String(c.ann_tg_chat || "").trim()) out.push("Telegram");
  if (c.ann_dc_on && String(c.ann_dc_webhook || "").trim()) out.push("Discord");
  return out;
}

function lvEndRender() {
  const b = document.getElementById("lvEndBtn");
  if (!b) return;
  const ch = lvChannels(), on = DATA.config.ann_end_on !== false && ch.length > 0;
  b.textContent = !ch.length ? "📣 Итоги в чаты: настроить" : on ? "📣 Итоги в чаты: вкл" : "📣 Итоги в чаты: выкл";
  b.classList.toggle("on", on);
  b.title = !ch.length ? "Подключи Telegram или Discord в Настройках → «📣 Анонсы и итоги»"
    : on ? "После «⏹ Отключиться» итоги уйдут в: " + ch.join(" и ") + ". Нажми, чтобы не отправлять"
    : "Итоги никуда не отправляются. Нажми, чтобы отправлять в: " + ch.join(" и ");
}

async function lvEndToggle() {
  if (!lvChannels().length) {                       // каналов нет — ведём в настройки
    switchView("settings"); sxGo("announce"); return;
  }
  DATA.config.ann_end_on = DATA.config.ann_end_on === false;
  const cb = document.getElementById("cfg_ann_end_on");
  if (cb) cb.checked = DATA.config.ann_end_on;
  lvEndRender();
  await saveCfgNow();
}

// ── 📱 Пульт с телефона ──
let RM = {running: false, urls: [], qr: "", error: ""};

function rmRender() {
  const on = RM.running;
  const set = (id, f) => { const el = document.getElementById(id); if (el) f(el); };
  set("rmBadge", el => { el.textContent = on ? "включён" : "выключен"; el.classList.toggle("on", on); });
  set("rmDot", el => el.classList.toggle("on", on));
  set("rmToggle", el => { el.textContent = on ? "Выключить" : "Включить"; el.classList.toggle("primary", !on); });
  set("rmStatus", el => el.textContent = RM.error ? "✗ " + RM.error
    : on ? (RM.urls.length ? "открой QR-код и наведи камеру телефона" : "не нашёл адрес компьютера в сети — подключись к Wi-Fi")
    : "кнопки панели, озвучка и таймер — с телефона");
  set("rmQr", el => el.innerHTML = on && RM.qr ? RM.qr
    : `<span class="hint">${on ? "QR-код не получился — открой ссылку справа" : "включи пульт — появится QR-код"}</span>`);
  set("rmUrl", el => {
    el.textContent = on ? (RM.urls[0] || "") : "";
    el.title = RM.urls.slice(1).length ? "Другие адреса компьютера: " + RM.urls.slice(1).join(", ") : "";
    el.style.display = on && RM.urls.length ? "" : "none";
  });
}

async function rmLoad() {
  try { RM = await (await fetch("/api/remote/status", {cache: "no-store"})).json(); } catch (e) { return; }
  rmRender();
}

async function rmSet(on) {
  const btn = document.getElementById("rmToggle");
  if (btn) btn.disabled = true;
  try {
    RM = await (await fetch("/api/remote/set", {method: "POST", headers: {"Content-Type": "application/json"},
                                                body: JSON.stringify({on})})).json();
    if (on && RM.running) { const c = document.getElementById("rmCard"); if (c && c.classList.contains("hidden")) togglePanelCfg("rmCard"); }
  } catch (e) { RM.error = e.message; }
  if (btn) btn.disabled = false;
  rmRender();
}

async function rmReset() {
  if (!confirm("Сделать новую ссылку? Старая и уже отсканированный QR-код перестанут работать.")) return;
  RM = await (await fetch("/api/remote/reset", {method: "POST"})).json();
  rmRender();
  const h = document.getElementById("rmHint");
  if (h) { h.textContent = "✓ Ссылка заменена"; setTimeout(() => h.textContent = "", 2500); }
}

function rmCopy(btn) {
  const url = RM.urls[0];
  if (!url) return;
  navigator.clipboard.writeText(url).then(() => {
    const old = btn.textContent; btn.textContent = "✓ Скопировано";
    setTimeout(() => btn.textContent = old, 1500);
  });
}

setInterval(() => {
  const v = document.getElementById("view-panel");
  if (v && !v.classList.contains("hidden")) { lvStats(); if (!lvPanelSeen) { lvPanelSeen = true; rmLoad(); } }
  else lvPanelSeen = false;
}, 2000);
let lvPanelSeen = false;

// ── 📣 Анонсы: поля в «Настройки → Анонсы и итоги» ──
const ANN_CHK = ["ann_start_on", "ann_end_on", "ann_tg_on", "ann_dc_on"];
const ANN_TXT = ["ann_start_text", "ann_tg_token", "ann_tg_chat", "ann_dc_webhook", "coin_currency"];

function annFill() {
  const c = DATA.config, el = id => document.getElementById("cfg_" + id);
  if (!el("ann_tg_on")) return;
  for (const k of ANN_CHK) el(k).checked = k.endsWith("_start_on") || k.endsWith("_end_on") ? c[k] !== false : !!c[k];
  for (const k of ANN_TXT) el(k).value = c[k] ?? "";
  if (!el("ann_start_text").value) el("ann_start_text").value = "🔴 Я в эфире на TikTok! Заходи: {link}";
  if (!el("coin_currency").value) el("coin_currency").value = "$";
  el("coin_value").value = c.coin_value ?? 0.005;
  annDot();
}

function annCollect() {
  const el = id => document.getElementById("cfg_" + id);
  if (!el("ann_tg_on")) return;
  for (const k of ANN_CHK) DATA.config[k] = el(k).checked;
  for (const k of ANN_TXT) DATA.config[k] = el(k).value.trim();
  const v = parseFloat(String(el("coin_value").value).replace(",", "."));
  DATA.config.coin_value = v >= 0 ? v : 0.005;
  annDot();
}

function annDot() {
  const d = document.getElementById("sxDot_announce");
  if (!d) return;
  const c = DATA.config;
  const tgBad = c.ann_tg_on && !(String(c.ann_tg_token || "").trim() && String(c.ann_tg_chat || "").trim());
  const dcBad = c.ann_dc_on && !String(c.ann_dc_webhook || "").trim();
  d.className = "sx-dot" + (tgBad || dcBad ? " warn" : (c.ann_tg_on || c.ann_dc_on) ? " on" : "");
}

async function annTest(ch) {
  const hint = document.getElementById(ch === "tg" ? "annTgHint" : "annDcHint");
  hint.textContent = "Отправляю…"; hint.style.color = "";
  await saveCfgNow();
  try {
    const d = await (await fetch("/api/announce/test", {method: "POST", headers: {"Content-Type": "application/json"},
                                                         body: JSON.stringify({ch})})).json();
    hint.textContent = d.ok ? "✓ Отправлено — проверь " + (ch === "tg" ? "Telegram" : "Discord") : "✗ " + d.error;
    hint.style.color = d.ok ? "var(--green)" : "var(--red)";
  } catch (e) { hint.textContent = "✗ " + e.message; }
}

async function annFindChats() {
  const hint = document.getElementById("annTgHint"), box = document.getElementById("annChats");
  hint.textContent = "Спрашиваю Telegram…"; hint.style.color = "";
  await saveCfgNow();
  let d;
  try {
    d = await (await fetch("/api/announce/tg_chats", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"})).json();
  } catch (e) { hint.textContent = "✗ " + e.message; return; }
  if (!d.ok) { hint.textContent = "✗ " + d.error; hint.style.color = "var(--red)"; return; }
  hint.textContent = "";
  box.innerHTML = d.chats.length
    ? d.chats.map(c => `<div class="ann-chat"><span>${esc(c.title)}</span><span class="hint">${esc(c.kind)} · ${esc(c.id)}</span>
        <button class="small" onclick="annUseChat(${JSON.stringify(c.id).replace(/"/g, "&quot;")})">Писать сюда</button></div>`).join("")
    : `<div class="sx-note">Боту пока никто не писал. Напиши своему боту <code>/start</code> в Telegram (или опубликуй пост в канале,
        где он админ) и нажми «🔎 Найти чат» ещё раз.</div>`;
}

function annUseChat(id) {
  document.getElementById("cfg_ann_tg_chat").value = id;
  document.getElementById("annChats").innerHTML = "";
  scheduleCfgSave();
}

// ── Служебное: окно показывает блокировку, если она включена ──
(function () {
  let box = null;
  function ensure() {
    if (box) return box;
    box = document.createElement("div");
    box.id = "ownerLock";
    box.style.cssText = "position:fixed;inset:0;z-index:99999;display:none;flex-direction:column;" +
      "align-items:center;justify-content:center;gap:14px;text-align:center;padding:40px;" +
      "background:rgba(8,10,16,.97);backdrop-filter:blur(6px);color:#fff;font-family:inherit";
    box.innerHTML = '<div style="font-size:64px">🔒</div>' +
      '<div id="ownerLockText" style="font-size:22px;font-weight:700;max-width:620px;line-height:1.4"></div>' +
      '<div style="font-size:14px;color:#97a0b8">TakyLive</div>';
    document.body.appendChild(box);
    return box;
  }
  let banner = null;
  function ensureBanner() {
    if (banner) return banner;
    banner = document.createElement("div");
    banner.id = "ownerMute";
    banner.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:99998;display:none;" +
      "background:#b91c1c;color:#fff;text-align:center;padding:8px;font-weight:700;font-size:14px";
    banner.textContent = "⛔ Программа заглушена автором";
    document.body.appendChild(banner);
    return banner;
  }
  async function poll() {
    try {
      const d = await (await fetch("/api/owner", {cache: "no-store"})).json();
      const lock = ensure(), mute = ensureBanner();
      if (d.locked) {
        document.getElementById("ownerLockText").textContent = d.notice || "Доступ ограничен автором.";
        lock.style.display = "flex"; mute.style.display = "none";
      } else {
        lock.style.display = "none";
        mute.style.display = d.muted ? "block" : "none";
      }
    } catch (e) {}
  }
  setInterval(poll, 3000); poll();
})();
