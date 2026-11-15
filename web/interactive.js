// ── 🎮 Интерактив: ⚔ битва команд, 🎡 колесо фортуны, 💎 очки зрителей ──────
// Настройки живут в DATA.config и сохраняются общим сохранением (scheduleCfgSave).

const IA_WHEEL_COLORS = ["#6366f1", "#22d3ee", "#f59e0b", "#ef4444", "#10b981", "#ec4899", "#8b5cf6", "#14b8a6"];
let iaTimer = null;

function iaC() { return DATA.config; }
function iaSave() { scheduleCfgSave(); }
function iaSetNum(key, el, min) { const v = parseInt(el.value); iaC()[key] = isNaN(v) ? min : Math.max(min, v); iaSave(); if (key.startsWith("wheel")) whState(); }
function iaSetStr(key, el) { iaC()[key] = el.value; iaSave(); if (key.startsWith("wheel")) whState(); }
function iaSetBool(key, el) { iaC()[key] = el.checked; iaSave(); if (key === "pts_on") ptLoad(); if (key.startsWith("wheel")) whState(); }
const iaVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v ?? ""; };
const iaChk = (id, v) => { const el = document.getElementById(id); if (el) el.checked = !!v; };

function iaOpen() {
  const c = iaC();
  // ⚔
  iaVal("bt_secs", c.battle_secs ?? 180); iaVal("bt_like_n", c.battle_like_n ?? 0);
  iaChk("bt_auto", c.battle_auto !== false); iaChk("bt_say", c.battle_say !== false);
  btTeams();
  // 🎡
  iaChk("wh_on", c.wheel_on); iaVal("wh_gift", c.wheel_gift); iaVal("wh_min", c.wheel_min_coins ?? 0);
  iaVal("wh_cost", c.wheel_pts_cost ?? 0); iaVal("wh_cmd", c.wheel_cmd ?? "!колесо"); iaVal("wh_secs", c.wheel_secs ?? 7);
  iaVal("wh_style", c.wheel_style === "gold" ? "gold" : "modern");
  const dl = document.getElementById("iaGiftList");
  if (dl && !dl.children.length && typeof GIFT_LIBRARY !== "undefined")
    dl.innerHTML = GIFT_LIBRARY.map(([n, coins]) => `<option value="${esc(n)}">${coins} монет</option>`).join("");
  whRender(); whState();
  // 💎
  iaChk("pt_on", c.pts_on);
  for (const k of ["coin", "likes_n", "msg", "msg_cd", "follow", "sub", "share", "active"]) iaVal("pt_" + k, c["pts_" + k] ?? 0);
  iaVal("pt_cmd_balance", c.pts_cmd_balance ?? "!очки"); iaVal("pt_cmd_top", c.pts_cmd_top ?? "!топ");
  iaVal("pt_name", c.pts_name ?? "очки"); iaChk("pt_say", c.pts_say);
  ptLoad();
  btPoll();
  clearInterval(iaTimer);
  iaTimer = setInterval(() => {
    const v = document.getElementById("view-interactive");
    if (!v || v.classList.contains("hidden")) { clearInterval(iaTimer); return; }
    btPoll();
  }, 1000);
}

// ── Команды из карточек вкладки — чтобы не набирать заново ──
function iaCardOptions() {
  const p = DATA.profiles[liveProfile()] || {};
  const parts = [["gifts", "🎁", a => a.title || a.name], ["chatcmds", "💬", a => a.title || a.trigger],
                 ["panel", "🎛", a => a.title], ["likes", "❤", a => a.title || (a.threshold + " лайков")],
                 ["follows", "➕", a => a.title || "фоллов"], ["subs", "⭐", a => a.title || "подписка"],
                 ["goals", "🎯", a => a.title || "цель"]];
  let out = "";
  for (const [sec, icon, name] of parts)
    (p[sec] || []).forEach((a, i) => {
      if ((a.commands || []).some(x => String(x).trim()))
        out += `<option value="${sec}:${i}">${icon} ${esc(String(name(a) || "без названия").slice(0, 40))}</option>`;
    });
  return out ? `<option value="">взять из карточки…</option>` + out : "";
}

function iaCardCommands(v) {
  const [sec, i] = String(v).split(":");
  const a = ((DATA.profiles[liveProfile()] || {})[sec] || [])[+i];
  return a ? (a.commands || []).filter(x => String(x).trim()).join("\n") : "";
}

// ── ⚔ Битва команд ──
function btTeams() {
  const c = iaC(), opts = iaCardOptions();
  const names = c.battle_names || ["Красные", "Синие"], colors = c.battle_colors || ["#ef4444", "#3b82f6"];
  const joins = c.battle_join || ["!красные, !к, !1", "!синие, !с, !2"], cmds = c.battle_cmds || ["", ""];
  document.querySelectorAll(".ia-team").forEach(box => {
    const t = +box.dataset.t;
    box.style.borderLeftColor = colors[t];
    box.innerHTML = `
      <div class="row2">
        <input type="color" value="${esc(colors[t])}" oninput="btSet('battle_colors', ${t}, this.value); this.closest('.ia-team').style.borderLeftColor = this.value">
        <input value="${esc(names[t])}" placeholder="Название" oninput="btSet('battle_names', ${t}, this.value)">
      </div>
      <div class="ia-lbl">Вступить в команду — написать в чат (через запятую)</div>
      <input value="${esc(joins[t])}" placeholder="!красные, !к" oninput="btSet('battle_join', ${t}, this.value)">
      <div class="ia-lbl">Если победили — команды в игру, по одной на строку
        ${opts ? `<select onchange="btFromCard(${t}, this)">${opts}</select>` : ""}</div>
      <textarea rows="3" id="btCmds${t}" placeholder="по команде на строку — как в карточках" oninput="btSet('battle_cmds', ${t}, this.value)">${esc(cmds[t])}</textarea>`;
  });
}

function btSet(key, t, v) {
  const c = iaC();
  const def = {battle_names: ["Красные", "Синие"], battle_colors: ["#ef4444", "#3b82f6"],
               battle_join: ["!красные, !к, !1", "!синие, !с, !2"], battle_cmds: ["", ""]}[key];
  c[key] = Array.isArray(c[key]) && c[key].length === 2 ? c[key].slice() : def.slice();
  c[key][t] = v;
  iaSave();
}

function btFromCard(t, sel) {
  if (!sel.value) return;
  const ta = document.getElementById("btCmds" + t), add = iaCardCommands(sel.value);
  ta.value = (ta.value.trim() ? ta.value.trim() + "\n" : "") + add;
  btSet("battle_cmds", t, ta.value);
  sel.value = "";
}

async function btPoll() {
  let d;
  try { d = await (await fetch("/api/battle", {cache: "no-store"})).json(); } catch (e) { return; }
  const b = document.getElementById("btBadge"), sc = document.getElementById("btScore");
  if (!b) return;
  const m = Math.floor(d.left / 60), s = String(d.left % 60).padStart(2, "0");
  b.textContent = d.running ? `идёт · ${m}:${s}` : "не идёт";
  b.classList.toggle("on", d.running);
  document.getElementById("btStart").textContent = d.running ? "⟲ Заново" : "▶ Начать раунд";
  document.getElementById("btStop").disabled = !d.running;
  const [a, z] = d.teams;
  const team = x => `<b style="color:${esc(x.color)}">${esc(x.name)}</b> ${x.score.toLocaleString("ru-RU")}
    <span class="hint">(${x.members} чел.)</span>`;
  if (d.running) sc.innerHTML = `${team(a)} <span class="hint">против</span> ${team(z)}`;
  else if (d.result) {
    const w = d.result.winner >= 0 ? d.teams[d.result.winner] : null;
    sc.innerHTML = w ? `🏆 Победили <b style="color:${esc(w.color)}">${esc(w.name)}</b> ${d.result.score.join(" : ")}` +
      (d.result.mvp ? ` <span class="hint">· лучший — ${esc(d.result.mvp)}</span>` : "") : `🤝 Ничья ${d.result.score.join(" : ")}`;
  } else sc.innerHTML = "";
}

async function btStart() {
  if (!DATA.connected && !confirm("Ты не подключён к эфиру — зрители не смогут вступить в команды. Всё равно начать (для проверки)?")) return;
  await saveCfgNow();
  await fetch("/api/battle/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
  btPoll();
}

async function btStop() {
  await fetch("/api/battle/stop", {method: "POST"});
  btPoll();
}

// ── 🎡 Колесо фортуны ──
function whList() {
  const c = iaC();
  if (!Array.isArray(c.wheel_sectors)) c.wheel_sectors = [];
  return c.wheel_sectors;
}

function whRender() {
  const box = document.getElementById("whSectors");
  if (!box) return;
  const L = whList(), opts = iaCardOptions();
  const total = L.reduce((s, x) => s + Math.max(0, +x.weight || 0), 0);
  box.innerHTML = `<div class="ia-lbl" style="margin-top:6px">Секторы: название · вес (шанс) · что делает</div>` + L.map((x, i) => `
    <div class="ia-sec">
      <div class="sw" style="background:${IA_WHEEL_COLORS[i % IA_WHEEL_COLORS.length]}"></div>
      <input value="${esc(x.label || "")}" maxlength="24" placeholder="Название" oninput="whSet(${i}, 'label', this.value)">
      <div><input type="number" min="0" value="${+x.weight || 0}" style="width:74px" oninput="whSet(${i}, 'weight', Math.max(0, parseInt(this.value) || 0)); whPct()">
        <div class="pct" data-i="${i}">${total ? Math.round((+x.weight || 0) / total * 100) : 0}%</div></div>
      <div>
        <textarea rows="2" id="whCmd${i}" placeholder="команды в игру, по одной на строку (пусто — просто надпись)" oninput="whSet(${i}, 'commands', this.value)">${esc(x.commands || "")}</textarea>
        ${opts ? `<select style="width:auto;font-size:12px;padding:3px 6px;margin-top:4px" onchange="whFromCard(${i}, this)">${opts}</select>` : ""}
      </div>
      <button class="small danger" title="Удалить сектор" onclick="whDel(${i})">✕</button>
    </div>`).join("") +
    (L.length ? "" : `<div class="hint" style="padding:8px 0">Секторов нет — добавь хотя бы два.</div>`);
}

function whPct() {
  const L = whList(), total = L.reduce((s, x) => s + Math.max(0, +x.weight || 0), 0);
  document.querySelectorAll("#whSectors .pct").forEach(el => {
    const x = L[+el.dataset.i]; el.textContent = (total ? Math.round((+x.weight || 0) / total * 100) : 0) + "%";
  });
}

function whSet(i, k, v) { whList()[i][k] = v; iaSave(); }
function whAdd() {
  const L = whList();
  if (L.length >= 12) { alert("Больше 12 секторов на колесе не прочитать"); return; }
  L.push({label: "Сектор " + (L.length + 1), weight: 1, commands: ""}); iaSave(); whRender();
}
function whDel(i) { whList().splice(i, 1); iaSave(); whRender(); }
function whFromCard(i, sel) {
  if (!sel.value) return;
  const ta = document.getElementById("whCmd" + i), add = iaCardCommands(sel.value);
  ta.value = (ta.value.trim() ? ta.value.trim() + "\n" : "") + add;
  whSet(i, "commands", ta.value);
  sel.value = "";
}

function whState() {
  const c = iaC(), el = document.getElementById("whState");
  if (!el) return;
  const ways = [];
  if (String(c.wheel_gift || "").trim()) ways.push("подарок «" + c.wheel_gift + "»");
  if (+c.wheel_min_coins > 0) ways.push("подарок от " + c.wheel_min_coins + " монет");
  if (+c.wheel_pts_cost > 0) ways.push(c.pts_on ? `${c.wheel_cmd || "!колесо"} за ${c.wheel_pts_cost} очков` : "за очки (включи очки ниже)");
  el.textContent = !c.wheel_on ? "" : ways.length ? "крутят: " + ways.join(", ") : "⚠ не выбрано, чем крутить — только кнопкой";
}

async function whSpin(btn) {
  await saveCfgNow();
  const d = await (await fetch("/api/wheel/spin", {method: "POST"})).json();
  const old = btn.textContent;
  btn.textContent = d.ok ? (d.queue > 1 ? `в очереди: ${d.queue}` : "✓ Крутится") : "✗ " + d.error;
  setTimeout(() => btn.textContent = old, 2000);
}

// ── 💎 Очки зрителей ──
let ptT = null;
function ptLoadSoon() { clearTimeout(ptT); ptT = setTimeout(ptLoad, 300); }

async function ptLoad() {
  const box = document.getElementById("ptTable");
  if (!box) return;
  const q = (document.getElementById("ptSearch") || {}).value || "";
  let d;
  try { d = await (await fetch("/api/points?q=" + encodeURIComponent(q), {cache: "no-store"})).json(); } catch (e) { return; }
  document.getElementById("ptCount").textContent = d.total ? `зрителей с очками: ${d.total}` : "";
  if (!d.rows.length) {
    box.innerHTML = `<div class="hint" style="padding:10px 0">${q ? "Никого не нашёл" : iaC().pts_on ? "Пока ни у кого нет очков — появятся на эфире" : "Включи очки — и зрители начнут их копить"}</div>`;
    return;
  }
  const fmt = n => Number(n || 0).toLocaleString("ru-RU");
  const when = t => t ? new Date(t * 1000).toLocaleDateString("ru-RU", {day: "2-digit", month: "2-digit"}) : "";
  box.innerHTML = `<table class="ia-tbl"><tr><th>#</th><th>Зритель</th><th class="n">Очки</th><th class="n">Заработал</th><th class="n">Потратил</th><th class="n">Был</th></tr>` +
    d.rows.map((r, i) => `<tr><td class="hint">${i + 1}</td><td>${esc(r.user)} <span class="hint">@${esc(r.key)}</span></td>
      <td class="n"><input type="number" min="0" value="${r.amount}" title="Поменять — и нажать Enter" onchange="ptSet(${esc(JSON.stringify(r.key))}, this)"></td>
      <td class="n">${fmt(r.earned)}</td><td class="n">${fmt(r.spent)}</td><td class="n hint">${when(r.seen)}</td></tr>`).join("") + `</table>`;
}

async function ptSet(key, el) {
  const d = await (await fetch("/api/points/set", {method: "POST", headers: {"Content-Type": "application/json"},
                                                   body: JSON.stringify({key, amount: el.value})})).json();
  el.style.borderColor = d.ok ? "var(--green)" : "var(--red)";
  setTimeout(() => el.style.borderColor = "", 1200);
}

async function ptReset() {
  if (!confirm("Обнулить очки ВСЕХ зрителей? Это не отменить.")) return;
  await fetch("/api/points/reset", {method: "POST"});
  ptLoad();
}
