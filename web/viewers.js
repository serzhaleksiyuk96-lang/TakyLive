// ── Озвучка: кнопки в шапке, защита от спама, голоса зрителей ─────────────
async function ttsStop() {
  try {
    const d = await (await fetch("/api/tts/stop", {method: "POST"})).json();
    flashTop(d.dropped ? `⏹ Озвучка остановлена, убрано из очереди: ${d.dropped}` : "⏹ Озвучка остановлена");
  } catch (e) {}
}

async function ttsSkip() {
  try { await fetch("/api/tts/skip", {method: "POST"}); flashTop("⏭ Пропущено"); } catch (e) {}
}

async function ttsToggle() {
  DATA.config.tts_enabled = !DATA.config.tts_enabled;
  const cb = document.getElementById("cfg_tts_on");
  if (cb) cb.checked = DATA.config.tts_enabled;
  ttsTopRender();
  try {
    await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"},
                                body: JSON.stringify({tts_enabled: DATA.config.tts_enabled})});
  } catch (e) {}
  if (!DATA.config.tts_enabled) ttsStop();
  flashTop(DATA.config.tts_enabled ? "🔊 Озвучка включена" : "🔇 Озвучка выключена");
}

function ttsTopRender() {
  const b = document.getElementById("ttsMuteBtn");
  if (!b) return;
  const on = !!(DATA.config || {}).tts_enabled;
  b.textContent = on ? "🔊" : "🔇";
  b.classList.toggle("off", !on);
  b.title = on ? "Озвучка включена — нажми, чтобы выключить" : "Озвучка выключена — нажми, чтобы включить";
}

function flashTop(text) {
  const el = document.getElementById("statusText");
  if (!el) return;
  const old = el.dataset.keep || el.textContent;
  el.dataset.keep = old;
  el.textContent = text;
  clearTimeout(flashTop.t);
  flashTop.t = setTimeout(() => { el.textContent = el.dataset.keep; delete el.dataset.keep; }, 2200);
}

// 🧪 Проверить фразу
async function guardCheck() {
  const t = document.getElementById("guardTest").value;
  const out = document.getElementById("guardVerdict");
  if (!t.trim()) { out.textContent = "впиши сообщение — покажу, что с ним сделает защита"; return; }
  await saveCfgNow();                                  // проверяем с текущими настройками
  try {
    const d = await (await fetch("/api/tts/check", {method: "POST", headers: {"Content-Type": "application/json"},
                                                    body: JSON.stringify({text: t})})).json();
    out.innerHTML = (d.ok ? "✅ " : "🚫 ") + esc(d.verdict);
  } catch (e) { out.textContent = "✗ " + e.message; }
}

// ── Голоса зрителей ──
let VV = [];
const vcVoices = () => {
  const list = [].concat((VOICES.edge || []).map(v => [v.v, "Microsoft · " + v.name]),
                         (VOICES.gt || []).map(v => [v.v, "Google · " + v.name]));
  const cur = DATA.config.tts_voice;
  for (const c of DATA.config.voice_cmds || []) if (c.voice && !list.some(x => x[0] === c.voice))
    list.push([c.voice, c.voice.startsWith("fish:") ? "Fish · " + (c.voice_title || c.voice.slice(5, 13)) : c.voice]);
  if (cur && !list.some(x => x[0] === cur))
    list.push([cur, cur.startsWith("fish:") ? "Fish · " + (DATA.config.fish_voice_title || "голос из «Голос»") : cur]);
  return list;
};

function vcRender() {
  const box = document.getElementById("vcList");
  if (!box) return;
  const cmds = DATA.config.voice_cmds || (DATA.config.voice_cmds = []);
  const opts = vcVoices();
  box.innerHTML = cmds.map((c, i) => `<div class="vc-row">
      <input class="sx-in" value="${esc(c.cmd || "")}" placeholder="!девочка" oninput="vcSet(${i},'cmd',this.value)">
      <input class="sx-in" value="${esc(c.label || "")}" placeholder="Девочка" oninput="vcSet(${i},'label',this.value)">
      ${voiceBtnHtml(c.voice, `vcPick(${i})`)}
      <button class="small" onclick="vcPreview(${i}, this)" title="Послушать">▶</button>
      <button class="icon danger" onclick="vcRemove(${i})" title="Удалить команду">🗑</button>
    </div>`).join("") || '<div class="hint" style="margin-bottom:8px">Команд пока нет.</div>';
}

function vcSet(i, k, v) {
  const c = DATA.config.voice_cmds[i];
  c[k] = k === "cmd" ? (v.trim() && !v.trim().startsWith("!") ? "!" + v.trim() : v.trim()) : v;
  scheduleCfgSave();
}

function vcPick(i) {
  const c = DATA.config.voice_cmds[i];
  openVoicePick({cur: c.voice, label: `команды ${c.cmd || ""}`.trim(), onPick: (v, t) => {
    c.voice = v; if (t && v.startsWith("fish:")) c.voice_title = t;
    vcRender(); scheduleCfgSave();
  }});
}

function vcSetVoice(i, v) {
  const c = DATA.config.voice_cmds[i];
  if (v === "__cur") {                                 // любой голос, выбранный в «Голос», в том числе Fish
    v = DATA.config.tts_voice;
    if (v.startsWith("fish:")) c.voice_title = DATA.config.fish_voice_title || "";
    if (!confirm(`Взять текущий голос из раздела «Голос»?\n${v.startsWith("fish:") ? "Fish Audio: " + (c.voice_title || v) : v}\n\n` +
                 "Чтобы выбрать другой — сначала выбери его в «🗣 Голос», потом вернись сюда.")) { vcRender(); return; }
  }
  c.voice = v;
  vcRender();
  scheduleCfgSave();
}

function vcAdd() {
  (DATA.config.voice_cmds = DATA.config.voice_cmds || []).push({cmd: "!", label: "", voice: DATA.config.tts_voice});
  vcRender();
  scheduleCfgSave();
}

function vcRemove(i) {
  DATA.config.voice_cmds.splice(i, 1);
  vcRender();
  scheduleCfgSave();
}

function vcPreview(i, btn) {
  const c = DATA.config.voice_cmds[i];
  if (c && c.voice && typeof vpPreview === "function") vpPreview(c.voice, "", btn);
}

async function vvLoad() {
  try {
    const d = await (await fetch("/api/viewer_voices", {cache: "no-store"})).json();
    VV = d.items || [];
    const st = Object.entries(d.stats || {});
    const g = document.getElementById("guardStats");
    if (g) g.textContent = st.length
      ? "Отфильтровано за этот запуск: " + st.map(([k, n]) => `${k} — ${n}`).join(" · ")
      : "Отфильтровано за этот запуск: пока ничего.";
  } catch (e) { VV = []; }
  vvRender();
}

function vvRender() {
  const box = document.getElementById("vvList");
  if (!box) return;
  const q = ((document.getElementById("vvSearch") || {}).value || "").trim().toLowerCase();
  const list = VV.filter(x => !q || String(x.nick).toLowerCase().includes(q) || String(x.user).toLowerCase().includes(q));
  document.getElementById("vvCount").textContent = VV.length ? `(${VV.length})` : "";
  const opts = vcVoices();
  if (!opts.some(o => o[0] === "")) opts.unshift(["", "— обычный —"]);
  box.innerHTML = list.map(x => {
    const k = JSON.stringify(x.key).replace(/"/g, "&quot;");
    const vo = opts.some(o => o[0] === x.voice) ? opts : opts.concat([[x.voice, x.label || x.voice]]);
    return `<div class="vv-row${x.pinned ? " pinned" : ""}">
      <span class="vv-nick">${esc(x.nick)}</span><span class="vv-meta">@${esc(String(x.user || "").replace(/^@/, ""))} ·
        ${esc(x.cmd === "вручную" ? "назначил ты" : (x.cmd || ""))} · ${esc(x.at || "")}</span>
      <span class="vv-label">🎭 ${esc(x.label || "")}</span>
      <span class="vv-voice">${voiceBtnHtml(x.voice, `vvPickVoice(${k})`)}</span>
      <button class="icon vv-pin${x.pinned ? " on" : ""}" onclick="vvPin(${k}, ${!x.pinned})"
        title="${x.pinned ? "Закреплён — зритель не сменит голос командой. Нажми, чтобы открепить" : "Закрепить голос"}">📌</button>
      <button class="icon danger" onclick="vvRemove(${k})" title="Убрать голос">🗑</button>
    </div>`;
  }).join("") || `<div class="hint">${VV.length ? "Никого не нашлось." : "Пока никто не выбрал голос — зрители пишут в чат команду, например !девочка."}</div>`;
}

async function vvRemove(key) {
  await fetch("/api/viewer_voices/remove", {method: "POST", headers: {"Content-Type": "application/json"},
                                            body: JSON.stringify({key})});
  vvLoad();
}

async function vvClear() {
  const pinned = VV.filter(x => x.pinned).length;
  if (!VV.length || !confirm(`Сбросить голоса у зрителей (${VV.length - pinned})? Они снова будут говорить обычным голосом.` +
                             (pinned ? `\nЗакреплённые тобой (${pinned}) останутся.` : ""))) return;
  await fetch("/api/viewer_voices/clear", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
  vvLoad();
}

async function vvSet(body) {
  const d = await (await fetch("/api/viewer_voices/set", {method: "POST", headers: {"Content-Type": "application/json"},
                                                          body: JSON.stringify(body)})).json();
  if (!d.ok) alert(d.error);
  vvLoad();
  return d;
}

function vvPickVoice(key) {
  const x = VV.find(v => v.key === key) || {};
  openVoicePick({cur: x.voice, label: x.nick || "зрителя", onPick: v => {
    if (!v) return;
    vvSet({key, voice: v, label: x.label || voiceLabel(v).replace(/^(Microsoft|Google|Fish) · /, "")});
  }});
}

function vvSetVoice(key, voice) {
  if (!voice) { vvRemove(key); return; }
  const n = (vcVoices().find(o => o[0] === voice) || [voice, voice])[1].replace(/^(Microsoft|Google|Fish) · /, "");
  vvSet({key, voice, label: n});
}

function vvPin(key, on) { vvSet({key, pinned: on}); }

// ⭐ особенный зритель вручную
let VV_NEW = "";
function vvNewPick() {
  openVoicePick({cur: VV_NEW || DATA.config.tts_voice, label: "особенного зрителя", onPick: v => {
    VV_NEW = v; document.getElementById("vvNewVoiceBox").innerHTML = voiceBtnHtml(VV_NEW, "vvNewPick()");
  }});
}

async function vvAddSpecial() {
  const nick = document.getElementById("vvNewNick").value.trim();
  let voice = VV_NEW || DATA.config.tts_voice;
  const hint = document.getElementById("vvAddHint");
  if (voice === "__cur") voice = DATA.config.tts_voice;
  const opt = vcVoices().find(o => o[0] === voice);
  const label = document.getElementById("vvNewLabel").value.trim() || (opt ? opt[1].replace(/^(Microsoft|Google|Fish) · /, "") : "особый");
  const rec = (VV_RECENT || []).find(r => `${r.nick} (@${r.user})` === nick);
  const d = await vvSet(rec ? {key: rec.key, voice, label, pinned: document.getElementById("vvNewPin").checked}
                            : {nick, voice, label, pinned: document.getElementById("vvNewPin").checked});
  if (d.ok) {
    hint.textContent = `✓ ${rec ? rec.nick : nick} теперь говорит голосом «${label}»` +
      (rec ? "" : " — привяжется к аккаунту, когда зритель напишет в чат");
    document.getElementById("vvNewNick").value = ""; document.getElementById("vvNewLabel").value = "";
  }
}

let VV_RECENT = [];
async function vvRecentLoad() {
  try { VV_RECENT = (await (await fetch("/api/viewers/recent", {cache: "no-store"})).json()).items || []; } catch (e) { VV_RECENT = []; }
  const dl = document.getElementById("vvRecent");
  if (dl) dl.innerHTML = VV_RECENT.map(r => `<option value="${esc(r.nick)} (@${esc(r.user)})">писал в ${esc(r.seen)}</option>`).join("");
  const box = document.getElementById("vvNewVoiceBox");
  if (box) box.innerHTML = voiceBtnHtml(VV_NEW || DATA.config.tts_voice, "vvNewPick()");
}

// 👑 голоса по ролям
const ROLES = [["moderator", "🛡 Модераторы"], ["superfan", "⭐ Супер-фаны (подписка)"],
               ["friend", "🤝 Друзья (взаимная подписка)"], ["gifter", "🎁 Кто дарил подарки"], ["follower", "👤 Подписчики"]];
function roleRender() {
  const box = document.getElementById("roleList");
  if (!box) return;
  const rv = DATA.config.role_voices || (DATA.config.role_voices = {});
  const opts = [["", "— как у всех —"]].concat(vcVoices());
  box.innerHTML = ROLES.map(([r, n]) => {
    const vo = !rv[r] || opts.some(o => o[0] === rv[r]) ? opts : opts.concat([[rv[r], rv[r]]]);
    return `<div class="role-row"><span>${n}</span>${voiceBtnHtml(rv[r] || "", `rolePick('${r}')`, "как у всех")}</div>`;
  }).join("");
}
function rolePick(r) {
  const n = (ROLES.find(x => x[0] === r) || [r, r])[1].replace(/^\S+\s/, "");
  openVoicePick({cur: (DATA.config.role_voices || {})[r] || "", label: n.toLowerCase(), allowDefault: true,
                 onPick: v => roleSet(r, v)});
}

function roleSet(r, v) {
  if (v === "__cur") v = DATA.config.tts_voice;
  (DATA.config.role_voices = DATA.config.role_voices || {})[r] = v;
  roleRender();
  scheduleCfgSave();
}
