// ── 🎵 Заказ музыки: зритель пишет «!трек название» — трек встаёт в очередь ──────────────────────────────
// Сервисы: YouTube Music (играет в оверлее), Spotify (очередь Spotify стримера, нужен Premium),
// Яндекс Музыка (экспериментально, играет в оверлее). Настройки — в DATA.config, общим сохранением.

let MU = null, muTimer = null;
const MU_SRC = {youtube: "▶ YouTube Music", spotify: "🟢 Spotify", yandex: "🟡 Яндекс Музыка"};

function muOpen() {
  const c = iaC();
  iaChk("mu_on", c.music_on);
  iaVal("mu_cmd", c.music_cmd ?? "!трек"); iaVal("mu_cost", c.music_cost ?? 0);
  iaGiftBtn("mu_gift", "music_gift"); iaVal("mu_gift_orders", c.music_gift_orders ?? 1);
  iaVal("mu_user_cd", c.music_user_cd ?? 120); iaVal("mu_max_min", c.music_max_min ?? 6);
  iaVal("mu_queue_max", c.music_queue_max ?? 15); iaVal("mu_block", c.music_block ?? "");
  iaVal("mu_volume", c.music_volume ?? 60); iaVal("mu_yt_key", c.music_yt_key ?? "");
  iaVal("mu_sp_client", c.music_sp_client ?? "");
  const rd = document.getElementById("muRedirect");
  if (rd) rd.textContent = `http://127.0.0.1:${location.port || 80}/api/music/spotify/callback`;
  muSrcUI();
  muRefresh();
  clearInterval(muTimer);
  muTimer = setInterval(() => {
    const v = document.getElementById("view-interactive");
    if (!v || v.classList.contains("hidden")) { clearInterval(muTimer); return; }
    muRefresh();
  }, 2000);
}

function muSetSrc(src) {
  iaC().music_source = src; iaSave(); muSrcUI(); muRefresh();
}

function muSrcUI() {
  const src = iaC().music_source || "youtube";
  document.querySelectorAll("#muSrc button").forEach(b => b.classList.toggle("primary", b.dataset.src === src));
  for (const s of Object.keys(MU_SRC)) {
    const el = document.getElementById("muSet_" + s);
    if (el) el.style.display = s === src ? "" : "none";
  }
}

async function muRefresh() {
  try { MU = await (await fetch("/api/music")).json(); } catch (e) { return; }
  const c = iaC(), src = MU.source;
  // состояние сервиса
  let ok = true, why = "";
  if (src === "youtube" && !MU.libs.ytmusicapi && !String(c.music_yt_key || "").trim()) {
    ok = false; why = "нет библиотеки поиска — впиши ключ YouTube или обнови программу";
  } else if (src === "spotify" && !MU.sp_linked) { ok = false; why = "войди в Spotify"; }
  else if (src === "yandex" && !MU.ya_linked) { ok = false; why = "войди в Яндекс"; }
  else if (src === "yandex" && !MU.libs.yandex_music) { ok = false; why = "нет библиотеки yandex-music"; }
  const badge = document.getElementById("muBadge");
  badge.textContent = !c.music_on ? "выключено" : !ok ? "не готово: " + why
    : MU.current ? (MU.paused ? "⏸ пауза" : "🎵 играет") : "ждёт заказов";
  const spSt = document.getElementById("muSpState");
  if (spSt) spSt.innerHTML = MU.sp_linked
    ? `<span style="color:#34d399">✓ Spotify подключён</span> <button class="small" onclick="muSpLogout()">Выйти</button>`
    : `<span class="hint">не подключён</span>`;
  const yaSt = document.getElementById("muYaState"), yl = MU.ya_login || {};
  if (yaSt) yaSt.innerHTML = yl.running ? `<span class="hint">⏳ жду входа в открывшемся окне…</span>`
    : MU.ya_linked ? `<span style="color:#34d399">✓ Яндекс Музыка подключена</span> <button class="small" onclick="muYaLogin(true)">Выйти</button>`
    : yl.error ? `<span style="color:#f87171">✗ ${esc(yl.error)}</span>` : `<span class="hint">не подключена</span>`;
  const ov = document.getElementById("muOv");
  if (ov) ov.innerHTML = src === "spotify" ? "Звук идёт из приложения Spotify на ПК (захвати его в OBS как обычно)."
    : MU.ov_open ? `<span style="color:#34d399">✓ Оверлей «🎵 Заказ музыки» открыт — звук идёт в OBS через него</span>`
    : `<span style="color:#fbbf24">⚠ Музыка играет в оверлее «🎵 Заказ музыки» — добавь его в OBS («📺 Оверлеи OBS»), иначе заказы не зазвучат</span>`;
  // очередь
  const cur = MU.current, q = MU.queue || [];
  const row = (t, a, u, extra) => `<div class="mu-row">${extra}<span class="mu-t">${esc(a ? a + " — " + t : t)}</span>` +
    (u ? `<span class="hint">· ${esc(u)}</span>` : "") + `</div>`;
  document.getElementById("muQueue").innerHTML =
    (cur ? row(cur.title, cur.artist, cur.user, `<b>${MU.paused ? "⏸" : "▶"}</b>`) : `<div class="hint">Сейчас ничего не играет</div>`) +
    q.map(it => row(it.title, it.artist, it.user,
      `<button class="small" title="Убрать из очереди" onclick="muCtl('remove', ${it.n})">✕</button>`)).join("");
  document.getElementById("muPause").textContent = MU.paused ? "▶ Играть" : "⏸ Пауза";
}

async function muCtl(what, n) {
  const r = await (await fetch("/api/music/control", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({do: what, n})})).json();
  if (!r.ok) alert(r.error);
  muRefresh();
}

async function muOrder() {
  const inp = document.getElementById("muTest");
  if (!inp.value.trim()) return;
  const r = await (await fetch("/api/music/request", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({query: inp.value, user: ""})})).json();
  document.getElementById("muTestRes").textContent = (r.ok ? "✓ " : "✗ ") + r.message;
  if (r.ok) inp.value = "";
  muRefresh();
}

async function muSpLogin() {
  const client = document.getElementById("mu_sp_client").value.trim();
  const r = await (await fetch("/api/music/spotify/login", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({client})})).json();
  if (!r.ok) { alert(r.error); return; }
  iaC().music_sp_client = client;
  window.open(r.url, "_blank");
}

async function muSpLogout() {
  await fetch("/api/music/spotify/logout", {method: "POST"});
  muRefresh();
}

async function muYaLogin(logout) {
  const r = await (await fetch("/api/music/yandex/login", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({logout: !!logout})})).json();
  if (!r.ok) alert(r.error);
  muRefresh();
}

function muCopy(id) {
  const t = document.getElementById(id).textContent;
  (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(
    () => { const el = document.getElementById(id); el.style.color = "#34d399"; setTimeout(() => el.style.color = "", 800); },
    () => prompt("Скопируй:", t));
}
