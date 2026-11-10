// ── Выбор картинки для витрины: свои файлы и библиотека ccLeaf Vault (ccvaults.com) ──
const VAULT_THUMB = "https://ccvaults.com/thumbnails/";
let VAULT = null;                       // {key: {label, paths}}
const IP = {idx: null, tab: "vault", cat: "all", q: ""};

// Подсказки: слова из названия события → подходящие картинки (новые — первыми)
const VAULT_HINTS = [
  [/зомби|орд/, ["Zombie_Adult", "Zombie_Adult_Targetting", "Zombie_Baby", "Husk_Adult"]],
  [/хаск|кадавр/, ["Husk_Adult", "Husk_Adult_Aggressive"]],
  [/крипер/, ["Creeper", "Creeper_Charged"]],
  [/тнт|tnt|взрыв/, ["Tnt", "Tnt_Minecart", "explosion_4"]],
  [/ведьм/, ["Witch", "Witch_Drinking"]],
  [/разорит/, ["Ravager"]],
  [/варден/, ["Warden", "Darkness"]],
  [/иссушит|конец всему/, ["Wither", "Wither_Skeleton"]],
  [/скелет/, ["Skeleton_Aiming", "Stray_Aiming"]],
  [/паук/, ["Spider", "Cave_Spider"]],
  [/паутин/, ["Cobweb"]],
  [/наковальн/, ["Anvil", "Chipped_Anvil", "Damaged_Anvil"]],
  [/молни|гроз/, ["Lightning_Rod", "Trident"]],
  [/слепот|тьма/, ["Blindness", "Darkness"]],
  [/тошнот/, ["Nausea"]],
  [/замедлен/, ["Slowness", "Mining_Fatigue"]],
  [/голод/, ["Hunger", "Rotten_Flesh"]],
  [/подброс|прыг|левитац/, ["Levitation", "Jump_Boost"]],
  [/пол[её]т|100 блок|в небо/, ["Feather", "Elytra", "Phantom"]],
  [/отобра|предмет из рук/, ["Barrier"]],
  [/ноч/, ["Clock", "Phantom"]],
  [/лечен|здоров|спаст/, ["Instant_Health", "Regeneration", "Golden_Apple"]],
  [/алмаз/, ["Diamond"]],
  [/яблок/, ["Golden_Apple", "Enchanted_Golden_Apple"]],
  [/брон/, ["Iron_Chestplate", "Diamond_Chestplate"]],
  [/меч/, ["Netherite_Sword", "Diamond_Sword"]],
  [/тотем|бессмерт/, ["Totem_Of_Undying", "Resistance"]],
  [/куриц/, ["Chicken"]],
  [/салют|фейерверк/, ["Firework_Rocket"]],
  [/фантом/, ["Phantom"]],
  [/еда|стейк/, ["Cooked_Beef", "Bread"]],
  [/скорост/, ["Speed", "Sugar"]],
  [/незерит/, ["Netherite_Ingot"]],
  [/печень/, ["Cookie"]],
  [/день|солнц/, ["Clock", "Sunflower"]],
  [/яд|отрав/, ["Poison"]],
];

const vaultName = p => p.split("/").pop().replace(/\.[^.]+$/, "");
const vaultThumb = p => VAULT_THUMB + encodeURI(p);

async function vaultLoad() {
  if (VAULT) return VAULT;
  try {
    VAULT = (await (await fetch("/api/vault/index", {cache: "force-cache"})).json()).categories || {};
  } catch (e) { VAULT = {}; }
  return VAULT;
}

function vaultAll() {
  const out = [];
  for (const [cat, c] of Object.entries(VAULT || {})) for (const p of c.paths || []) out.push({cat, p});
  return out;
}

// Картинки по названию события: 3–4 варианта
function vaultSuggest(text) {
  const t = String(text || "").toLowerCase();
  const names = [];
  for (const [re, list] of VAULT_HINTS) if (re.test(t)) names.push(...list);
  if (!names.length || !VAULT) return [];
  const all = vaultAll(), seen = new Set(), out = [];
  for (const n of names) {
    for (const x of all) {
      if (vaultName(x.p).toLowerCase() === n.toLowerCase() && !seen.has(x.p)) {
        seen.add(x.p); out.push(x.p);
        break;                                  // по одной картинке на название
      }
    }
    if (out.length >= 4) break;
  }
  return out;
}

async function openIconPick(idx) {
  IP.idx = idx; IP.q = ""; IP.cat = "all"; IP.tab = "vault";
  document.getElementById("iconPickModal").classList.remove("hidden");
  document.getElementById("ipBody").innerHTML = '<div class="hint">Загружаю библиотеку…</div>';
  await vaultLoad();
  ipRender();
}
function closeIconPick() { document.getElementById("iconPickModal").classList.add("hidden"); }

function ipCard() { return (curList() || [])[IP.idx] || {}; }

function ipRender() {
  const a = ipCard();
  const title = (a.title || a.name || a.trigger || "").replace(/^💀\s*/, "");
  document.getElementById("ipTitle").textContent = `Картинка для «${title || "события"}»`;
  document.querySelectorAll("#ipTabs .ip-tab").forEach(t => t.classList.toggle("active", t.dataset.t === IP.tab));
  const body = document.getElementById("ipBody");
  if (IP.tab === "local") {
    const files = MEDIA_FILES.filter(f => ["image", "gif"].includes(f.kind));
    body.innerHTML = `<div class="ip-grid">
      <div class="ip-tile${!a.icon_file ? " sel" : ""}" onclick="ipChoose('')"><div class="ip-auto">авто</div><span>как в алерте</span></div>
      ${files.map(f => `<div class="ip-tile${f.name === a.icon_file ? " sel" : ""}" onclick='ipChoose(${JSON.stringify(f.name)})'>
        <img src="/media/${encodeURI(f.name)}" loading="lazy" alt=""><span>${esc(f.name.split("/").pop())}</span></div>`).join("")}
    </div>`;
    return;
  }
  const sug = vaultSuggest(`${a.title || ""} ${a.trigger || ""}`);
  const cats = [["all", "Все"]].concat(Object.entries(VAULT || {}).map(([k, c]) => [k, c.label]));
  const q = IP.q.trim().toLowerCase();
  let list = vaultAll().filter(x => IP.cat === "all" || x.cat === IP.cat);
  if (q) {
    const ru = new Set();                               // поиск по-русски через подсказки
    for (const [re, names] of VAULT_HINTS) if (re.test(q)) names.forEach(n => ru.add(n.toLowerCase()));
    list = list.filter(x => vaultName(x.p).toLowerCase().replace(/_/g, " ").includes(q.replace(/_/g, " "))
                            || ru.has(vaultName(x.p).toLowerCase()));
  }
  const total = list.length;
  list = list.slice(0, 120);
  const tile = p => `<div class="ip-tile${("vault/" + p) === a.icon_file ? " sel" : ""}" onclick='ipChoose(${JSON.stringify("vault/" + p)})'
      title="${esc(p)}"><img src="${vaultThumb(p)}" loading="lazy" alt="" onerror="ipThumbFail(this, ${JSON.stringify(p).replace(/"/g, "&quot;")})">
      <span>${esc(vaultName(p).replace(/_/g, " "))}</span></div>`;
  body.innerHTML = `
    ${sug.length ? `<div class="ip-sug"><div class="ip-sub">✨ Подходит к этому событию</div><div class="ip-grid">${sug.map(tile).join("")}</div></div>` : ""}
    <div class="ip-bar">
      <input id="ipSearch" placeholder="Поиск: zombie, tnt, зомби, слепота…" value="${esc(IP.q)}"
             oninput="IP.q=this.value; ipRender(); const s=document.getElementById('ipSearch'); s.focus(); s.setSelectionRange(s.value.length, s.value.length)">
    </div>
    <div class="ip-cats">${cats.map(([k, n]) => `<span class="fish-tag${k === IP.cat ? " active" : ""}" onclick="IP.cat='${k}'; ipRender()">${esc(n)}</span>`).join("")}</div>
    <div class="ip-grid">${list.map(x => tile(x.p)).join("") || '<div class="hint">Ничего не нашлось — попробуй по-английски: zombie, sword, potion</div>'}</div>
    ${total > list.length ? `<div class="hint" style="margin-top:8px">Показано ${list.length} из ${total} — уточни поиск или категорию.</div>` : ""}`;
}

// Превью с их сайта не открылось — пробуем через нашу программу (она скачает картинку)
function ipThumbFail(img, p) {
  if (img.dataset.tried) { img.replaceWith(Object.assign(document.createElement("div"), {className: "ip-auto", textContent: "?"})); return; }
  img.dataset.tried = "1";
  img.src = "/media/vault/" + encodeURI(p);
}

function ipChoose(file) {
  const a = ipCard();
  a.icon_file = file;
  if (file.startsWith("vault/")) fetch("/media/" + encodeURI(file)).catch(() => {});   // скачать заранее
  closeIconPick();
  renderCards();
}

// 🪄 Одной кнопкой — подходящие картинки ко всем событиям вкладки
async function ipAutoAll() {
  await vaultLoad();
  const p = DATA.profiles[activeProfile];
  if (!p) return;
  const plan = [];
  for (const sec of ["gifts", "likes", "subs", "follows", "chatcmds"]) {
    for (const a of p[sec] || []) {
      const s = vaultSuggest(`${a.title || ""} ${a.trigger || ""}`)[0];
      if (s && a.icon_file !== "vault/" + s) plan.push([a, "vault/" + s]);
    }
  }
  if (!plan.length) { alert("Для событий этой вкладки подходящих картинок не нашлось — выбери вручную."); return; }
  if (!confirm(`Поставить картинки из ccLeaf Vault для ${plan.length} ${plural(plan.length, "события", "событий", "событий")}? ` +
               "Там, где ничего не подошло, останутся твои картинки.")) return;
  for (const [a, f] of plan) {
    a.icon_file = f;
    fetch("/media/" + encodeURI(f)).catch(() => {});
  }
  closeIconPick();
  renderCards();
  const hint = document.getElementById("saveHint");
  if (hint) hint.textContent = `✓ Картинки обновлены у ${plan.length} событий`;
}
