// ── Витрина подарков: настройки плитками с живыми мини-анимациями ─────────────
// Плитки ставят значения в прежние поля (sc_anim, sc_effect…), поэтому загрузка и
// сохранение остаются старыми и надёжными; справа — настоящая витрина вживую.
const SC_MODES = [
  ["grid", "Сетка", "страницы сменяют друг друга"],
  ["scroll", "Прокрутка", "список едет вверх без конца"],
  ["marquee", "Бегущая строка", "для ленты внизу экрана"],
  ["none", "Всё сразу", "без движения, все на месте"],
  ["auto", "Авто", "мало подарков — сетка, много — прокрутка"],
];
const SC_TRANS = [
  ["fade", "Затухание", "спокойно проявляются"], ["pulse", "Пульс", "все вместе с толчком"],
  ["wave", "Волна", "по очереди снизу"], ["flip", "Переворот", "разворачиваются"],
  ["zoom", "Зум", "вылетают из центра"], ["domino", "Домино", "падают по очереди"],
  ["carousel", "Карусель", "въезжают сбоку"], ["spiral", "Спираль", "закручиваются"],
  ["bounce", "Прыжок", "падают с отскоком"], ["diagonal", "Диагональ", "каскадом из угла"],
  ["flash", "Вспышка", "яркий старт"], ["blur", "Размытие", "из тумана"],
];
const SC_FX = [
  ["none", "Без эффекта", "карточки просто стоят"], ["glow", "Подсветка", "по рамкам бежит свет"],
  ["breathe", "Дыхание", "чуть увеличиваются"], ["float", "Парение", "плавают вверх-вниз"],
  ["wobble", "Покачивание", "качаются из стороны в сторону"], ["shine", "Блик", "по картинке пробегает свет"],
  ["neon", "Неон", "мерцает рамка"], ["rainbow", "Радуга", "рамка переливается"],
];
const SC_MOTION = [["smooth", "Плавно", "едет без остановки"], ["step", "По шагам", "сдвиг на карточку и пауза"]];
const SC_BADGE = [["br", "Справа снизу"], ["bl", "Слева снизу"], ["tr", "Справа сверху"], ["tl", "Слева сверху"], ["none", "Без значка"]];
const SC_SPEED = [[2, "🐇", "Быстро", "2 сек"], [5, "🚶", "Средне", "5 сек"], [8, "🐢", "Медленно", "8 сек"]];
const SC_EMO = ["🌹", "🦁", "🍩", "🎩", "🐶", "🌌", "🔥", "🍦", "💎", "🎈", "⭐", "🎁"];
const STAGGER = new Set(["wave", "domino", "diagonal", "carousel", "bounce", "spiral"]);

const scv = id => (document.getElementById(id) || {}).value;
const scCards = (n, cls = "", from = 0) =>
  Array.from({length: n}, (_, i) => `<i class="scm ${cls}" style="--h:${(i + from) * 47 % 360};--i:${i}">${SC_EMO[(i + from) % SC_EMO.length]}</i>`).join("");

function scSet(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.type === "checkbox") el.checked = value; else el.value = value;
  el.dispatchEvent(new Event("change", {bubbles: true}));
  if (typeof scTransUI === "function") scTransUI();
  scBuild();
  scLiveSoon();
}

function scTile(group, val, cur, title, desc, prev, extra = "") {
  return `<div class="sct${String(val) === String(cur) ? " on" : ""}" onclick="scSet('${group}', '${val}')" ${extra}>
    <div class="pv">${prev}</div><div class="sct-t">${title}</div>${desc ? `<div class="sct-d">${desc}</div>` : ""}</div>`;
}

function scModePrev(m) {
  if (m === "grid") return `<div class="pv-pages"><div class="pg a">${scCards(8)}</div><div class="pg b">${scCards(8, "", 4)}</div></div>`;
  if (m === "scroll") return `<div class="pv-scroll"><div class="trk">${scCards(12)}</div></div>`;
  if (m === "marquee") return `<div class="pv-marq"><div class="trk">${scCards(12)}${scCards(12)}</div></div>`;
  if (m === "none") return `<div class="pv-all">${scCards(10)}</div>`;
  return `<div class="pv-auto"><div class="pv-pages"><div class="pg a">${scCards(8)}</div><div class="pg b">${scCards(8, "", 4)}</div></div><b>АВТО</b></div>`;
}

function scBuild() {
  const box = document.getElementById("scNew");
  if (!box) return;
  const anim = scv("sc_anim") || "auto", trans = scv("sc_trans_grid") || "pulse", fx = scv("sc_effect") || "none";
  const motion = scv("sc_motion") || "smooth", badge = scv("sc_badge") || "br";
  const speed = parseFloat(scv("sc_speed")) || 5, per = parseInt(scv("sc_per")) || 7, rows = parseInt(scv("sc_rows")) || 3;
  const icon = parseInt(scv("sc_icon")) || 88, bsize = parseInt(scv("sc_bsize")) || 38;
  const showTrans = anim !== "scroll" && anim !== "marquee", showMotion = anim !== "grid" && anim !== "none";
  const types = [["gifts", "🎁", "Подарки"], ["likes", "❤", "Лайки"], ["subs", "⭐", "Подписки"],
                 ["follows", "➕", "Фолловы"], ["chatcmds", "💬", "Чат-команды"]];
  const chk = id => { const el = document.getElementById(id); return el && el.checked; };
  const grid = Array.from({length: Math.min(rows, 6)}, () =>
    `<div class="mg-row">${Array.from({length: Math.min(per, 12)}, () => "<i></i>").join("")}</div>`).join("");
  const steps = `
      <div class="sc-step"><div class="sc-h"><b>1</b> Что показывать в витрине</div>
        <div class="sc-types2">${types.map(([k, e, n]) => `<div class="sct-type${chk("sct_" + k) ? " on" : ""}" onclick="scSet('sct_${k}', ${!chk("sct_" + k)})">
          <span class="e">${e}</span>${n}<span class="tick">${chk("sct_" + k) ? "✓" : ""}</span></div>`).join("")}</div>
      </div>

      <div class="sc-step"><div class="sc-h"><b>2</b> Как листать, когда подарков много</div>
        <div class="sct-grid five">${SC_MODES.map(([v, t, d]) => scTile("sc_anim", v, anim, t, d, scModePrev(v))).join("")}</div>
        ${showMotion ? `<div class="sc-sub">Как едет</div>
        <div class="sct-grid two">${SC_MOTION.map(([v, t, d]) => scTile("sc_motion", v, motion, t, d,
          `<div class="pv-marq ${v === "step" ? "step" : ""}"><div class="trk">${scCards(12)}${scCards(12)}</div></div>`)).join("")}</div>` : ""}
      </div>

      <div class="sc-step"><div class="sc-h"><b>3</b> Как выглядят карточки</div>
        ${showTrans ? `<div class="sc-sub">Появление — при смене страницы</div>
        <div class="sct-grid six">${SC_TRANS.map(([v, t, d]) => scTile("sc_trans_grid", v, trans, t, d,
          `<div class="pv-tr">${scCards(3, "tr-" + v + (STAGGER.has(v) ? " stg" : ""))}</div>`)).join("")}</div>` : ""}
        <div class="sc-sub">Эффект — работает всегда</div>
        <div class="sct-grid four">${SC_FX.map(([v, t, d]) => scTile("sc_effect", v, fx, t, d,
          `<div class="pv-fx">${scCards(2, "big fx-" + v)}</div>`)).join("")}</div>
        <div class="sc-sub">Значок подарка поверх картинки</div>
        <div class="sct-grid five small">${SC_BADGE.map(([v, t]) => scTile("sc_badge", v, badge, t, "",
          `<div class="pv-badge"><i class="scm big" style="--h:330">🧟</i>${v !== "none" ? `<em class="bdg ${v}">🌹</em>` : ""}</div>`)).join("")}</div>
      </div>

      <div class="sc-step"><div class="sc-h"><b>4</b> Размер и скорость</div>
        <div class="sc-sizes">
          <div class="sc-size">
            <div class="sc-lbl">Скорость — сколько держится страница или карточка</div>
            <div class="sc-speed">${SC_SPEED.map(([v, e, t, d]) => `<div class="sct-sp${speed === v ? " on" : ""}" onclick="scSet('sc_speed', ${v})">
              <span class="e">${e}</span><b>${t}</b><span>${d}</span></div>`).join("")}
              <label class="sct-sp own${SC_SPEED.some(x => x[0] === speed) ? "" : " on"}">✏ Своё
                <input type="number" min="1" step="0.5" value="${speed}" onchange="scSet('sc_speed', Math.max(1, parseFloat(this.value) || 5))"> сек</label></div>
          </div>
          ${anim === "grid" || anim === "auto" ? `<div class="sc-size">
            <div class="sc-lbl">Сетка: ${per} в ряд × ${rows} ${rows === 1 ? "ряд" : rows < 5 ? "ряда" : "рядов"}</div>
            <div class="sc-grid-ctl">
              <div class="stp"><span>в ряд</span><button onclick="scSet('sc_per', Math.max(1, ${per} - 1))">−</button><b>${per}</b><button onclick="scSet('sc_per', Math.min(12, ${per} + 1))">+</button></div>
              <div class="stp"><span>рядов</span><button onclick="scSet('sc_rows', Math.max(1, ${rows} - 1))">−</button><b>${rows}</b><button onclick="scSet('sc_rows', Math.min(6, ${rows} + 1))">+</button></div>
              <div class="mini-grid">${grid}</div>
            </div></div>` : ""}
          <div class="sc-size">
            <div class="sc-lbl">Размер картинок: <b>${icon}px</b></div>
            <div class="sc-slide"><span class="s">🎁</span><input type="range" min="40" max="180" step="4" value="${icon}"
              oninput="this.closest('.sc-size').querySelector('b').textContent=this.value+'px'" onchange="scSet('sc_icon', this.value)"><span class="l">🎁</span></div>
          </div>
          ${badge !== "none" ? `<div class="sc-size">
            <div class="sc-lbl">Размер значка: <b>${bsize}%</b> от картинки</div>
            <div class="sc-slide"><span class="s">🌹</span><input type="range" min="15" max="70" step="1" value="${bsize}"
              oninput="this.closest('.sc-size').querySelector('b').textContent=this.value+'%'" onchange="scSet('sc_bsize', this.value)"><span class="l">🌹</span></div>
          </div>` : ""}
          <label class="chk" style="margin-top:6px"><input type="checkbox" ${chk("sc_online") ? "checked" : ""}
            onchange="scSet('sc_online', this.checked)"> 🌐 Брать иконки подарков с серверов TikTok</label>
        </div>
      </div>`;
  if (!box.querySelector(".sc-wrap")) {
    box.innerHTML = `<div class="sc-wrap"><div class="sc-steps"></div>
    <div class="sc-live">
      <div class="sc-live-h">👁 Так видят зрители <span class="hint">— меняется сразу</span></div>
      <div class="sc-live-box" id="scLiveBox"></div>
      <div class="hint" style="margin-top:8px">Это настоящая витрина с подарками твоей вкладки. В OBS — оверлей «🎁 Витрина подарков».</div>
      <button class="small" style="margin-top:8px" onclick="openOv('ov9')">↗ Открыть оверлей отдельно</button>
    </div></div>`;
  }
  box.querySelector(".sc-steps").innerHTML = steps;
  const card = document.getElementById("scSettings");
  scLiveToggle(card && !card.classList.contains("hidden"));
}

// живая витрина грузится, только пока панель открыта — закрыл, и она не работает впустую
function scLiveToggle(on) {
  const holder = document.getElementById("scLiveBox");
  if (!holder) return;
  const f = document.getElementById("scLiveFrame");
  if (on && !f) holder.innerHTML = '<iframe id="scLiveFrame" src="/web/overlays/showcase.html" title="Витрина"></iframe>';
  if (!on && f) holder.innerHTML = "";
  scLiveFit();
}

// витрина рисуется в «экране» 1280×512 и уменьшается ровно под ширину блока — видна целиком
function scLiveFit() {
  const holder = document.getElementById("scLiveBox"), f = document.getElementById("scLiveFrame");
  if (!holder || !f) return;
  const narrow = window.innerWidth <= 1250;                 // превью сверху — не выше 230 px, чтобы не закрывать плитки
  const k = Math.max(0.2, Math.min(holder.clientWidth / 1280, narrow ? 230 / 512 : 1));
  f.style.transform = `scale(${k})`;
  f.style.left = Math.max(0, Math.round((holder.clientWidth - 1280 * k) / 2)) + "px";
  holder.style.height = Math.round(512 * k) + "px";
}
window.addEventListener("resize", scLiveFit);

// превью уже живое (витрина сама подхватывает настройки); перезагружаем только если оно «застряло»
let SC_LIVE_T = null;
function scLiveSoon() {
  clearTimeout(SC_LIVE_T);
  SC_LIVE_T = setTimeout(() => {
    const f = document.getElementById("scLiveFrame");
    try { if (f && f.contentWindow) f.contentWindow.location.reload(); } catch (e) {}
  }, 1600);
}
