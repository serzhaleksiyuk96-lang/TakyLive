"""Локальные серверы Minecraft (Paper) прямо из программы: создание, запуск, консоль.

Ядро Paper качается через Fill v3 (fill.papermc.io) — старый api.papermc.io отключён.
Java при необходимости качается с Adoptium (Eclipse Temurin JRE) в папку java/.
"""
import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sys
import tarfile
import time
import zipfile
from collections import deque

from aiohttp import ClientSession, ClientTimeout, web

from steamservers import GIFT_GAMES, STEAM_GAMES, SteamMixin

FILL_API = "https://fill.papermc.io/v3"
SOURCES = {
    "purpur": "https://api.purpurmc.org/v2/purpur",
    "mojang": "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
    "fabric": "https://meta.fabricmc.net/v2",
    "forge_promos": "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json",
    "forge_maven": "https://maven.minecraftforge.net",
    "neo_maven": "https://maven.neoforged.net",
    "mohist": "https://api.mohistmc.com",
    "github": "https://api.github.com",
}
# kind: plugins — плагины, mods — моды, hybrid — моды + плагины, plain — без ничего
CORES = {
    "paper":    {"name": "Paper",    "kind": "plugins", "desc": "Плагины Bukkit/Spigot/Paper. Быстрый и стабильный — рекомендую"},
    "purpur":   {"name": "Purpur",   "kind": "plugins", "desc": "Тот же Paper, но с кучей дополнительных настроек геймплея"},
    "vanilla":  {"name": "Vanilla",  "kind": "plain",   "desc": "Чистый сервер от Mojang — без плагинов и модов"},
    "fabric":   {"name": "Fabric",   "kind": "mods",    "desc": "Лёгкие моды Fabric. Первым выходит на новые версии"},
    "neoforge": {"name": "NeoForge", "kind": "mods",    "desc": "Большие моды и сборки на новых версиях (1.20.2+)"},
    "forge":    {"name": "Forge",    "kind": "mods",    "desc": "Классические моды и старые сборки (1.12.2, 1.16.5, 1.20.1…)"},
    "youer":    {"name": "Youer",    "kind": "hybrid",  "desc": "Моды NeoForge + плагины Paper/Purpur (1.21+)"},
    "arclight": {"name": "Arclight", "kind": "hybrid",  "desc": "Моды Forge, NeoForge или Fabric + плагины Bukkit"},
    "silkard":  {"name": "Silkard",  "kind": "hybrid",  "desc": "Моды Fabric + плагины Spigot (новые версии)"},
    "mohist":   {"name": "Mohist",   "kind": "hybrid",  "desc": "Моды Forge + плагины — для старых сборок (до 1.20.1)"},
}
GITHUB_REPOS = {"arclight": "IzzelAliz/Arclight", "silkard": "MohistMC/Silkard"}
MOHIST_FALLBACK = {"youer": ["1.21.1"], "mohist": ["1.20.1", "1.16.5", "1.12.2", "1.7.10"]}
ADOPTIUM_URL = "https://api.adoptium.net/v3/binary/latest/{feature}/ga/{os}/{arch}/jre/hotspot/normal/eclipse"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CLASS_TO_JAVA = {52: 8, 55: 11, 61: 17, 65: 21, 66: 22, 67: 23, 68: 24, 69: 25, 70: 26, 71: 27}
WIN = sys.platform == "win32"


_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _slug(name):
    """ID сервера и имя папки — только латиница: так надёжнее для Windows, Java и адресов."""
    s = "".join(_TR.get(ch, ch) for ch in str(name).lower())
    s = re.sub(r"[^a-z0-9_-]+", "-", s).strip("-")[:24] or "server"
    return f"{s}-{secrets.token_hex(2)}"


def _port_busy(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def vkey(v):
    """Ключ сортировки версий: «1.21.11» < «26.1» < «26.3»; бета — ниже релиза."""
    nums = [int(x) for x in re.findall(r"\d+", str(v).split("-")[0])[:5]]
    return tuple(nums + [0] * (5 - len(nums))) + ((0,) if "-" in str(v) else (1,))


def guess_java(version, core="paper"):
    """Какая Java нужна (минимум, максимум). Старые моды (Forge 1.16.5 и ниже) работают только на Java 8."""
    v = str(version)
    try:
        major = int(v.split(".")[0])
    except ValueError:
        return 21, None
    if major >= 26:
        return 25, None
    parts = [int(x) for x in re.findall(r"\d+", v)[:3]] + [0, 0]
    minor = (parts[1], parts[2])
    if minor >= (20, 5):
        return 21, None
    if minor >= (17, 0):
        return 17, None
    return (8, 8) if core in ("forge", "mohist") else (8, 16)


def neo_mc(neo):
    """Версия NeoForge → версия Minecraft: 21.1.77 → 1.21.1, 21.0.5 → 1.21, 26.1.2.13 → 26.1.2."""
    nums = re.findall(r"\d+", str(neo).split("-")[0])
    if len(nums) < 3:
        return ""
    if int(nums[0]) >= 26:
        mc = ".".join(nums[:-1])
        return mc[:-2] if mc.endswith(".0") and mc.count(".") >= 2 else mc
    return f"1.{nums[0]}" if nums[1] == "0" else f"1.{nums[0]}.{nums[1]}"


def _find_min_java(obj):
    """Ищет в ответе PaperMC требование вида java → version → minimum."""
    if isinstance(obj, dict):
        j = obj.get("java")
        if isinstance(j, dict):
            v = j.get("version")
            if isinstance(v, dict) and isinstance(v.get("minimum"), int):
                return v["minimum"]
        for val in obj.values():
            r = _find_min_java(val)
            if r:
                return r
    elif isinstance(obj, list):
        for val in obj:
            r = _find_min_java(val)
            if r:
                return r
    return None


class LocalServers(SteamMixin):
    def __init__(self, base_dir, log, cfg, save_cfg, rcon_cmd, user_agent, game_rcon=None):
        self.base = base_dir
        self.dir = os.path.join(base_dir, "servers")
        self.java_dir = os.path.join(base_dir, "java")
        os.makedirs(self.dir, exist_ok=True)
        self.file = os.path.join(self.dir, "servers.json")
        self.log, self.cfg, self.save_cfg, self.rcon_cmd = log, cfg, save_cfg, rcon_cmd
        self.ua = user_agent
        self.game_rcon = game_rcon
        self.servers = self._load()
        self.run = {}            # id → {proc, lines, seq, status, players, need_java}
        self.jobs = {}           # id → {state, progress, error} — создание
        self.java_job = None     # {state, progress, error, feature}
        self._versions = (0.0, [])

    # ── хранение ──────────────────────────────────────────────────────────
    def _load(self):
        try:
            with open(self.file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self.servers, f, ensure_ascii=False, indent=1)

    def _get(self, sid):
        return next((s for s in self.servers if s["id"] == sid), None)

    def _folder(self, s):
        return os.path.join(self.dir, s["id"])

    def _api(self):
        return str(self.cfg().get("paper_api") or FILL_API).rstrip("/")

    # ── консоль ───────────────────────────────────────────────────────────
    def _rt(self, sid):
        r = self.run.get(sid)
        if r is None:
            r = self.run[sid] = {"proc": None, "lines": deque(maxlen=1500), "seq": 0,
                                 "status": "offline", "players": set(), "need_java": 0}
        return r

    def _push(self, sid, text):
        r = self._rt(sid)
        r["seq"] += 1
        r["lines"].append((r["seq"], text))

    def status(self, s):
        r = self.run.get(s["id"])
        if s["id"] in self.jobs and self.jobs[s["id"]]["state"] in ("downloading", "error"):
            return self.jobs[s["id"]]["state"] == "error" and "error" or "creating"
        if r and r["proc"] is not None:
            return r["status"]                                  # starting / online / stopping / installing
        game = s.get("game", "minecraft")
        if game != "minecraft":
            if not s.get("installed"):
                return "offline"
            g = STEAM_GAMES.get(game, {})
            return "external" if g.get("rcon") and _port_busy(s["rcon_port"]) else "offline"
        return "external" if _port_busy(s["port"]) else "offline"

    # ── Java ──────────────────────────────────────────────────────────────
    async def java_version(self, path):
        try:
            p = await asyncio.create_subprocess_exec(path, "-version", stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.PIPE, **self._noconsole())
            out, err = await asyncio.wait_for(p.communicate(), 15)
        except Exception:
            return 0
        m = re.search(r'version "(\d+)(?:\.(\d+))?', (err + out).decode("utf-8", "replace"))
        if not m:
            return 0
        major = int(m.group(1))
        return int(m.group(2) or 0) if major == 1 else major       # «1.8» → 8

    async def javas(self):
        """Все найденные Java: своя из папки java/, указанная в настройках и из системы."""
        cands = []
        if os.path.isdir(self.java_dir):
            for root, dirs, files in os.walk(self.java_dir):
                exe = "java.exe" if WIN else "java"
                if os.path.basename(root) == "bin" and exe in files:
                    cands.append(os.path.join(root, exe))
        custom = str(self.cfg().get("java_path") or "").strip()
        if custom:
            cands.append(custom)
        sysjava = shutil.which("java")
        if sysjava:
            cands.append(sysjava)
        out, seen = [], set()
        for c in cands:
            if c in seen:
                continue
            seen.add(c)
            v = await self.java_version(c)
            if v:
                out.append({"path": c, "version": v, "bundled": c.startswith(self.java_dir)})
        return sorted(out, key=lambda j: -j["version"])

    async def pick_java(self, minimum, maximum=None):
        for j in await self.javas():
            if j["version"] >= minimum and (not maximum or j["version"] <= maximum):
                return j
        return None

    async def _download(self, url, dest, progress):
        """Скачивание с прогрессом. Возвращает (sha256, sha1) скачанного."""
        h, h1 = hashlib.sha256(), hashlib.sha1()
        async with ClientSession(timeout=ClientTimeout(total=1800, sock_read=60),
                                 headers={"User-Agent": self.ua}) as cs:
            async with cs.get(url, allow_redirects=True) as r:
                if r.status != 200:
                    raise RuntimeError(f"сервер ответил {r.status} на {url}")
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                with open(dest, "wb") as f:
                    async for chunk in r.content.iter_chunked(256 * 1024):
                        f.write(chunk)
                        h.update(chunk)
                        h1.update(chunk)
                        got += len(chunk)
                        if total:
                            progress(got / total)
        return h.hexdigest(), h1.hexdigest()

    async def _java_job(self, feature):
        job = self.java_job
        try:
            osn = "windows" if WIN else ("mac" if sys.platform == "darwin" else "linux")
            url = (str(self.cfg().get("adoptium_url") or ADOPTIUM_URL)
                   .format(feature=feature, os=osn, arch="x64"))
            os.makedirs(self.java_dir, exist_ok=True)
            tmp = os.path.join(self.java_dir, f"download-{feature}.tmp")

            def prog(p):
                job["progress"] = round(p * 0.9, 3)
            await self._download(url, tmp, prog)
            job["state"], job["progress"] = "extracting", 0.92
            target = os.path.join(self.java_dir, f"jre-{feature}")
            shutil.rmtree(target, ignore_errors=True)
            os.makedirs(target, exist_ok=True)
            if zipfile.is_zipfile(tmp):
                with zipfile.ZipFile(tmp) as z:
                    z.extractall(target)
            else:
                with tarfile.open(tmp) as t:
                    t.extractall(target)
            os.remove(tmp)
            if not WIN:                                      # права на запуск после распаковки
                for root, _d, files in os.walk(target):
                    if os.path.basename(root) == "bin":
                        for fn in files:
                            os.chmod(os.path.join(root, fn), 0o755)
            got = await self.pick_java(feature)
            if not got:
                raise RuntimeError("Java скачалась, но не запускается")
            job["state"], job["progress"] = "done", 1.0
            self.log("СЕРВЕРЫ", f"Java {got['version']} готова: {got['path']}")
        except Exception as e:
            job["state"], job["error"] = "error", str(e)
            self.log("ОШИБКА СЕРВЕРА", f"скачивание Java {feature}: {e}")

    # ── PaperMC ───────────────────────────────────────────────────────────
    async def _get_json(self, url):
        async with ClientSession(timeout=ClientTimeout(total=20), headers={"User-Agent": self.ua}) as cs:
            async with cs.get(url) as r:
                if r.status != 200:
                    raise RuntimeError(f"PaperMC ответил {r.status}")
                return await r.json(content_type=None)

    def _src(self, key):
        """Адрес источника — можно переопределить в настройках (для тестов)."""
        return str(self.cfg().get("src_" + key) or SOURCES[key]).rstrip("/")

    async def versions(self, core="paper"):
        """Список версий для ядра: [{id, label}], новые сверху."""
        key = core
        cache = getattr(self, "_vcache", {})
        self._vcache = cache
        if key in cache and time.time() - cache[key][0] < 600:
            return cache[key][1]
        ids = []
        if core == "paper":
            data = await self._get_json(f"{self._api()}/projects/paper")
            groups = data.get("versions") or {}
            for vals in (groups.values() if isinstance(groups, dict) else [groups]):
                ids += [str(v) for v in (vals if isinstance(vals, list) else [vals])]
        elif core == "purpur":
            data = await self._get_json(self._src("purpur"))
            ids = sorted((str(v) for v in data.get("versions") or []), key=vkey, reverse=True)
        elif core == "vanilla":
            data = await self._get_json(self._src("mojang"))
            ids = [v["id"] for v in data.get("versions") or [] if v.get("type") == "release"]
        elif core == "fabric":
            data = await self._get_json(self._src("fabric") + "/versions/game")
            ids = [v["version"] for v in data if v.get("stable")]
        elif core == "forge":
            data = await self._get_json(self._src("forge_promos"))
            mcs = {k.rsplit("-", 1)[0] for k in (data.get("promos") or {})}
            ids = sorted(mcs, key=vkey, reverse=True)
        elif core == "neoforge":
            vers = await self._neo_versions()
            ids = sorted({neo_mc(v) for v in vers if neo_mc(v)}, key=vkey, reverse=True)
        elif core in ("youer", "mohist"):
            ids = await self._mohist_versions(core)
        elif core in GITHUB_REPOS:
            out = []
            for a in await self._gh_assets(core):
                vid = f"{a['mc']}|{a['loader']}" if a["loader"] else a["mc"]
                if vid not in [o["id"] for o in out]:
                    out.append({"id": vid, "label": a["mc"] + (f" · {a['loader'].capitalize().replace('forge', 'Forge').replace('Neoforge', 'NeoForge')}" if a["loader"] else "")})
            cache[key] = (time.time(), out)
            return out
        else:
            raise RuntimeError("неизвестное ядро")
        out = [{"id": v, "label": v} for v in ids if v]
        cache[key] = (time.time(), out)
        return out

    async def _neo_versions(self):
        try:
            d = await self._get_json(self._src("neo_maven") + "/api/maven/versions/releases/net/neoforged/neoforge")
            return [str(v) for v in d.get("versions") or []]
        except Exception:                                   # запасной путь — maven-metadata.xml
            async with ClientSession(timeout=ClientTimeout(total=20), headers={"User-Agent": self.ua}) as cs:
                async with cs.get(self._src("neo_maven") + "/releases/net/neoforged/neoforge/maven-metadata.xml") as r:
                    return re.findall(r"<version>([^<]+)</version>", await r.text())

    async def _mohist_versions(self, core):
        base = f"{self._src('mohist')}/project/{core}"
        for url in (base + "/versions", base):
            try:
                d = await self._get_json(url)
            except Exception:
                continue
            found = d if isinstance(d, list) else (d.get("versions") or d.get("data") or [])
            vers = [str(x.get("name") or x.get("version") or x.get("id")) if isinstance(x, dict) else str(x) for x in found]
            vers = [v for v in vers if re.match(r"^\d+(\.\d+)+$", v)]
            if vers:
                return sorted(set(vers), key=vkey, reverse=True)
        return MOHIST_FALLBACK[core]

    async def _gh_assets(self, core):
        """Сборки из релизов GitHub: [{mc, loader, url, sha256}] — новые сверху."""
        rels = await self._get_json(f"{self._src('github')}/repos/{GITHUB_REPOS[core]}/releases?per_page=40")
        out = []
        for rel in rels:
            if rel.get("draft"):
                continue
            for a in rel.get("assets") or []:
                n = str(a.get("name", ""))
                if not n.endswith(".jar"):
                    continue
                if core == "arclight":
                    m = re.match(r"arclight-(forge|neoforge|fabric)-(\d+(?:\.\d+)+)-", n)
                    if not m:
                        continue
                    loader, mc = m.group(1), m.group(2)
                else:
                    m = re.search(r"(\d+(?:\.\d+)+)", n)
                    if not m:
                        continue
                    loader, mc = "", m.group(1)
                dig = str(a.get("digest") or "")
                out.append({"mc": mc, "loader": loader, "url": a.get("browser_download_url"), "name": n,
                            "sha256": dig.split(":", 1)[1] if dig.startswith("sha256:") else ""})
        return out

    async def _resolve(self, s):
        """Где взять файл ядра: {url, file, sha256, sha1, install, build}."""
        core, mc, api = s["core"], s["version"], self._api()
        if core == "paper":
            builds = await self._get_json(f"{api}/projects/paper/versions/{mc}/builds")
            if isinstance(builds, dict):
                builds = builds.get("builds") or []
            stable = [b for b in builds if str(b.get("channel", "")).upper() in ("STABLE", "RECOMMENDED")]
            build = (stable or builds or [None])[0]
            if not build:
                raise RuntimeError(f"у Paper {mc} нет сборок")
            if not stable:
                self._push(s["id"], f"⚠ У {mc} нет стабильной сборки — взял {build.get('channel', '?')}")
            dl = (build.get("downloads") or {}).get("server:default") or {}
            if not dl.get("url"):
                raise RuntimeError("PaperMC не дал ссылку на скачивание")
            try:
                info = await self._get_json(f"{api}/projects/paper/versions/{mc}")
                s["java_min"] = _find_min_java(info) or s.get("java_min")
            except Exception:
                pass
            return {"url": dl["url"], "sha256": (dl.get("checksums") or {}).get("sha256"), "build": build.get("id")}
        if core == "purpur":
            return {"url": f"{self._src('purpur')}/{mc}/latest/download", "build": "latest"}
        if core == "vanilla":
            man = await self._get_json(self._src("mojang"))
            entry = next((v for v in man.get("versions") or [] if v.get("id") == mc), None)
            if not entry:
                raise RuntimeError(f"Mojang не знает версию {mc}")
            info = await self._get_json(entry["url"])
            srv = (info.get("downloads") or {}).get("server") or {}
            if not srv.get("url"):
                raise RuntimeError(f"у {mc} нет серверной версии")
            jv = (info.get("javaVersion") or {}).get("majorVersion")
            if jv:
                s["java_min"] = int(jv)
            return {"url": srv["url"], "sha1": srv.get("sha1"), "build": mc}
        if core == "fabric":
            fb = self._src("fabric")
            loader = next(v["version"] for v in await self._get_json(fb + "/versions/loader") if v.get("stable"))
            inst = next(v["version"] for v in await self._get_json(fb + "/versions/installer") if v.get("stable"))
            return {"url": f"{fb}/versions/loader/{mc}/{loader}/{inst}/server/jar", "build": f"loader {loader}"}
        if core == "forge":
            promos = (await self._get_json(self._src("forge_promos"))).get("promos") or {}
            fv = promos.get(f"{mc}-recommended") or promos.get(f"{mc}-latest")
            if not fv:
                raise RuntimeError(f"у Forge нет версии для {mc}")
            full = f"{mc}-{fv}"
            return {"url": f"{self._src('forge_maven')}/net/minecraftforge/forge/{full}/forge-{full}-installer.jar",
                    "file": "installer.jar", "install": True, "build": fv}
        if core == "neoforge":
            cands = [v for v in await self._neo_versions() if neo_mc(v) == mc]
            if not cands:
                raise RuntimeError(f"у NeoForge нет версии для {mc}")
            rel = [v for v in cands if "-" not in v]
            nv = sorted(rel or cands, key=vkey)[-1]
            if not rel:
                self._push(s["id"], f"⚠ Для {mc} у NeoForge только бета-версии — взял {nv}")
            return {"url": f"{self._src('neo_maven')}/releases/net/neoforged/neoforge/{nv}/neoforge-{nv}-installer.jar",
                    "file": "installer.jar", "install": True, "build": nv}
        if core in ("youer", "mohist"):
            base = f"{self._src('mohist')}/project/{core}/{mc}/builds"
            builds = await self._get_json(base)
            if isinstance(builds, dict):
                builds = builds.get("builds") or builds.get("data") or []
            if not builds:
                raise RuntimeError(f"у {CORES[core]['name']} нет сборок для {mc}")
            b = builds[0]
            bid = b.get("id") or b.get("number") or b.get("build")
            sha = b.get("fileSha256") or b.get("sha256") or ""
            return {"url": f"{base}/{bid}/download", "sha256": sha, "build": bid}
        if core in GITHUB_REPOS:
            a = next((x for x in await self._gh_assets(core)
                      if x["mc"] == mc and (not s.get("loader") or x["loader"] == s["loader"])), None)
            if not a:
                raise RuntimeError(f"у {CORES[core]['name']} нет сборки для {mc} {s.get('loader') or ''}".strip())
            return {"url": a["url"], "sha256": a["sha256"], "build": a["name"]}
        raise RuntimeError("неизвестное ядро")

    async def _create_job(self, s):
        sid, job = s["id"], self.jobs[s["id"]]
        folder = self._folder(s)
        core = CORES[s["core"]]
        try:
            jmin, jmax = guess_java(s["version"], s["core"])
            s.setdefault("java_min", jmin)
            s["java_max"] = jmax
            res = await self._resolve(s)
            s["java_min"] = int(s.get("java_min") or jmin)
            s["build"] = res.get("build")
            fname = res.get("file", "server.jar")

            def prog(p):
                job["progress"] = round(p, 3)
            sha256, sha1 = await self._download(res["url"], os.path.join(folder, fname), prog)
            if res.get("sha256") and res["sha256"].lower() != sha256:
                raise RuntimeError("файл ядра повреждён (не совпала контрольная сумма) — попробуй ещё раз")
            if res.get("sha1") and res["sha1"].lower() != sha1:
                raise RuntimeError("файл ядра повреждён (не совпала контрольная сумма) — попробуй ещё раз")
            s["installed"] = not res.get("install")
            s["launch"] = {"type": "jar", "jar": "server.jar"}
            self._write_props(s)
            with open(os.path.join(folder, "eula.txt"), "w", encoding="utf-8") as f:
                f.write("# Принято пользователем в программе TakyLive: https://aka.ms/MinecraftEULA\n"
                        "eula=true\n")
            for sub in (["mods"] if core["kind"] in ("mods", "hybrid") else []) + \
                       (["plugins"] if core["kind"] in ("plugins", "hybrid") else []):
                os.makedirs(os.path.join(folder, sub), exist_ok=True)
            job["state"], job["progress"] = "done", 1.0
            self._save()
            jmx = s.get("java_max")
            jtxt = f"Java {s['java_min']}" + ("" if jmx == s["java_min"] else f"–{jmx}" if jmx else "+")
            self._push(sid, f"✓ Сервер создан: {core['name']} {s['version']} ({s.get('build')}), нужна {jtxt}")
            if not s["installed"]:
                self._push(sid, "  Установщик скачан — установка пройдёт сама при первом запуске")
            hint = {"mods": "моды клади в папку mods", "plugins": "плагины клади в папку plugins",
                    "hybrid": "моды — в папку mods, плагины — в plugins"}.get(core["kind"])
            if hint:
                self._push(sid, f"  💡 {hint.capitalize()} (кнопка 📂 на карточке)")
            self.log("СЕРВЕРЫ", f"Создан сервер «{s['name']}» — {core['name']} {s['version']}")
        except Exception as e:
            job["state"], job["error"] = "error", str(e)
            self._push(sid, f"✗ Не удалось создать: {e}")
            self.log("ОШИБКА СЕРВЕРА", f"«{s['name']}»: {e}")

    async def _install(self, s, java):
        """Forge / NeoForge: запуск установщика (--installServer), вывод — в консоль."""
        sid, folder = s["id"], self._folder(s)
        self._push(sid, f"── установка {CORES[s['core']]['name']} {s['version']} (обычно 1–3 минуты) ──")
        proc = await asyncio.create_subprocess_exec(
            java["path"], "-jar", "installer.jar", "--installServer", cwd=folder,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **self._noconsole())
        self._rt(sid).update(proc=proc, status="installing")
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            text = ANSI.sub("", raw.decode("utf-8", "replace")).rstrip()
            if text:
                self._push(sid, text)
        code = await proc.wait()
        self._rt(sid).update(proc=None, status="offline")
        if code != 0:
            raise RuntimeError(f"установщик завершился с ошибкой (код {code}) — смотри консоль выше")
        args_name = "win_args.txt" if WIN else "unix_args.txt"
        found = None
        for root, _dirs, files in os.walk(os.path.join(folder, "libraries")):
            if args_name in files:
                found = os.path.relpath(os.path.join(root, args_name), folder).replace(os.sep, "/")
                break
        if found:
            args = (["@user_jvm_args.txt"] if os.path.exists(os.path.join(folder, "user_jvm_args.txt")) else []) + ["@" + found]
            s["launch"] = {"type": "args", "args": args}
        else:                                                 # старый Forge — обычный jar
            jars = [f for f in os.listdir(folder) if f.endswith(".jar") and f.startswith("forge-") and "installer" not in f]
            if not jars:
                raise RuntimeError("установщик не создал файлов запуска")
            s["launch"] = {"type": "jar", "jar": sorted(jars)[-1]}
        s["installed"] = True
        self._save()
        self._push(sid, "✓ Установка завершена")

    def _write_props(self, s):
        lines = ["# Создано программой TakyLive",
                 f"motd={s['name']}",
                 f"server-port={s['port']}",
                 "enable-rcon=true",
                 f"rcon.port={s['rcon_port']}",
                 f"rcon.password={s['rcon_password']}",
                 "broadcast-rcon-to-ops=false",
                 f"online-mode={'true' if s.get('online_mode', True) else 'false'}",
                 f"gamemode={s.get('gamemode', 'survival')}",
                 f"difficulty={s.get('difficulty', 'normal')}",
                 f"max-players={s.get('max_players', 20)}",
                 f"level-seed={s.get('seed', '')}",
                 "spawn-protection=0"]
        with open(os.path.join(self._folder(s), "server.properties"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ── запуск и остановка ────────────────────────────────────────────────
    @staticmethod
    def _noconsole():
        return {"creationflags": 0x08000000} if WIN else {}       # без чёрного окна на Windows

    async def start(self, s):
        if s.get("game", "minecraft") != "minecraft":
            return await self._steam_start(s)
        sid = s["id"]
        r = self._rt(sid)
        if r["proc"] is not None:
            return {"ok": False, "error": "сервер уже запущен"}
        if _port_busy(s["port"]):
            return {"ok": False, "error": f"порт {s['port']} занят — уже работает другой сервер или игра"}
        gmin, gmax = guess_java(s["version"], s.get("core", "paper"))
        need = int(s.get("java_min") or gmin)
        jmax = s.get("java_max", gmax)
        java = await self.pick_java(need, jmax)
        if not java:
            rng = f"Java {need}" + ("" if jmax else " или новее")
            return {"ok": False, "need_java": need, "error": f"нужна {rng} — нажми «Скачать Java {need}»"}
        if not s.get("installed", True):                  # Forge/NeoForge: сначала установка — в фоне
            asyncio.ensure_future(self._install_and_launch(s, java))
            return {"ok": True, "installing": True}
        return await self._launch(s, java)

    async def _install_and_launch(self, s, java):
        try:
            await self._install(s, java)
        except Exception as e:
            self._rt(s["id"]).update(proc=None, status="offline")
            self._push(s["id"], f"✗ {e}")
            return
        await self._launch(s, java)

    async def _launch(self, s, java):
        sid = s["id"]
        r = self._rt(sid)
        ram = max(1, min(32, int(s.get("ram", 3))))
        launch = s.get("launch") or {"type": "jar", "jar": "server.jar"}
        args = [java["path"], "-Xms1G", f"-Xmx{ram}G", "-Dfile.encoding=UTF-8",
                "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8"]
        args += launch["args"] if launch.get("type") == "args" else ["-jar", launch.get("jar", "server.jar")]
        args.append("nogui")
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=self._folder(s), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, **self._noconsole())
        except Exception as e:
            return {"ok": False, "error": f"не удалось запустить Java: {e}"}
        r.update(proc=proc, status="starting", players=set(), need_java=0)
        self._push(sid, f"── запуск: Java {java['version']}, память до {ram} ГБ, порт {s['port']} ──")
        asyncio.ensure_future(self._reader(s, proc))
        return {"ok": True}

    async def _reader(self, s, proc):
        sid = s["id"]
        r = self._rt(sid)
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            text = ANSI.sub("", raw.decode("utf-8", "replace")).rstrip("\r\n")
            if not text:
                continue
            self._push(sid, text)
            if r["status"] == "starting" and re.search(r"Done \(\d", text):
                r["status"] = "online"
                self.log("СЕРВЕРЫ", f"«{s['name']}» запущен — подключайся: localhost:{s['port']}")
            m = re.search(r"\]: (\S{2,16}) joined the game", text) or re.search(r"^(\S{2,16}) joined the game", text)
            if m:
                r["players"].add(m.group(1))
            m = re.search(r"\]: (\S{2,16}) left the game", text) or re.search(r"^(\S{2,16}) left the game", text)
            if m:
                r["players"].discard(m.group(1))
            m = re.search(r"class file version (\d+)", text)
            if m:
                r["need_java"] = CLASS_TO_JAVA.get(int(m.group(1)), 0)
            if "Stopping the server" in text or "Stopping server" in text:
                r["status"] = "stopping"
        code = await proc.wait()
        r.update(proc=None, status="offline", players=set())
        if r["need_java"]:
            s["java_min"] = max(int(s.get("java_min") or 0), r["need_java"])
            self._save()
            self._push(sid, f"✗ Этому ядру нужна Java {r['need_java']} — нажми «Скачать Java {r['need_java']}»")
        self._push(sid, f"── сервер остановлен (код {code}) ──")

    async def stop(self, s, wait=40):
        if s.get("game", "minecraft") != "minecraft":
            return await self._steam_stop(s)
        r = self._rt(s["id"])
        proc = r["proc"]
        if proc is None:
            if _port_busy(s["port"]):                      # запущен до перезапуска программы
                try:
                    await self.rcon_cmd("stop", "127.0.0.1", s["rcon_port"], s["rcon_password"])
                    self._push(s["id"], "── отправил stop через RCON ──")
                    return {"ok": True}
                except Exception as e:
                    return {"ok": False, "error": f"не достучался по RCON: {e}"}
            return {"ok": False, "error": "сервер не запущен"}
        if r["status"] == "installing":                       # установщику stop не скажешь — прерываем
            proc.kill()
            self._push(s["id"], "── установка прервана — при следующем запуске начнётся заново ──")
            return {"ok": True}
        r["status"] = "stopping"
        try:
            proc.stdin.write(b"stop\n")
            await proc.stdin.drain()
        except Exception:
            pass

        async def ensure_dead():
            try:
                await asyncio.wait_for(proc.wait(), wait)
            except asyncio.TimeoutError:
                self._push(s["id"], "── сервер не остановился сам — завершаю принудительно ──")
                proc.kill()
        asyncio.ensure_future(ensure_dead())
        return {"ok": True}

    async def command(self, s, cmd):
        cmd = str(cmd or "").strip().lstrip("/")
        if not cmd:
            return {"ok": False, "error": "пустая команда"}
        if s.get("game", "minecraft") != "minecraft":
            return await self._steam_command(s, cmd)
        r = self._rt(s["id"])
        if r["proc"] is not None:
            self._push(s["id"], "> " + cmd)
            r["proc"].stdin.write((cmd + "\n").encode("utf-8"))
            await r["proc"].stdin.drain()
            return {"ok": True}
        if _port_busy(s["port"]):
            self._push(s["id"], "> " + cmd + "   (через RCON)")
            try:
                out = await self.rcon_cmd(cmd, "127.0.0.1", s["rcon_port"], s["rcon_password"])
                for line in str(out or "").splitlines():
                    self._push(s["id"], line)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": f"RCON: {e}"}
        return {"ok": False, "error": "сервер не запущен"}

    async def shutdown(self, app=None):
        """Программу закрывают — аккуратно останавливаем свои серверы, чтобы не повредить мир."""
        for s in self.servers:
            r = self.run.get(s["id"])
            if s.get("game", "minecraft") != "minecraft" and r and r["proc"] is not None:
                try:
                    await self._steam_stop(s)
                except Exception:
                    pass
        procs = [(sid, r["proc"]) for sid, r in self.run.items() if r["proc"] is not None
                 and (self._get(sid) or {}).get("game", "minecraft") == "minecraft"]
        for _sid, p in procs:
            try:
                p.stdin.write(b"stop\n")
                await p.stdin.drain()
            except Exception:
                pass
        for _sid, p in procs:
            try:
                await asyncio.wait_for(p.wait(), 25)
            except Exception:
                p.kill()
        for sid, r in list(self.run.items()):              # Steam-игры сохраняются дольше
            p = r.get("proc")
            if p is not None:
                try:
                    await asyncio.wait_for(p.wait(), 40)
                except Exception:
                    p.kill()

    # ── HTTP ──────────────────────────────────────────────────────────────
    def routes(self, app):
        r = app.router
        r.add_get("/api/servers", self.h_list)
        r.add_get("/api/servers/versions", self.h_versions)
        r.add_post("/api/servers/create", self.h_create)
        r.add_post("/api/servers/java", self.h_java)
        r.add_get("/api/servers/{sid}/log", self.h_log)
        r.add_post("/api/servers/{sid}/{action}", self.h_action)
        app.on_shutdown.append(self.shutdown)

    async def h_list(self, request):
        javas = await self.javas()
        out = []
        for s in self.servers:
            r = self.run.get(s["id"]) or {}
            job = self.jobs.get(s["id"]) or {}
            game = s.get("game", "minecraft")
            core = CORES.get(s.get("core", "paper"), CORES["paper"])
            if game != "minecraft":
                g = STEAM_GAMES[game]
                core = {"name": g["name"], "kind": "game"}
            c = self.cfg()
            linked = (str(c.get(f"{game}_host")) in ("127.0.0.1", "localhost")
                      and int(c.get(f"{game}_port") or 0) == s["rcon_port"]) if game in GIFT_GAMES else None
            out.append({**{k: v for k, v in s.items() if k not in ("rcon_password",)},
                        "game": game, "gift_ok": game == "minecraft" or game in GIFT_GAMES,
                        "has_console": game == "minecraft" or bool(STEAM_GAMES.get(game, {}).get("rcon")),
                        "ram_hint": STEAM_GAMES.get(game, {}).get("ram", ""),
                        "core": s.get("core", "paper"), "core_name": core["name"], "kind": core["kind"],
                        "status": self.status(s), "players": sorted(r.get("players") or []),
                        "progress": job.get("progress") if job.get("state") == "downloading" else None,
                        "error": job.get("error") if job.get("state") == "error" else "",
                        "need_java": r.get("need_java") or 0,
                        "connected": linked if linked is not None else (
                            str(self.cfg().get("mc_transport")) == "rcon"
                            and str(self.cfg().get("servertap_host")) in ("127.0.0.1", "localhost")
                            and int(self.cfg().get("rcon_port") or 0) == s["rcon_port"])})
        return web.json_response({"servers": out, "javas": javas, "java_job": self.java_job,
                                  "cores": [{"id": k, **v} for k, v in CORES.items()],
                                  "games": [{"id": k, "name": v["name"], "disk": v["disk"], "ram": v["ram"],
                                             "port": v["port"], "players": v["players"], "console": bool(v["rcon"]),
                                             "gifts": k in GIFT_GAMES} for k, v in STEAM_GAMES.items()]})

    async def h_versions(self, request):
        core = request.query.get("core", "paper")
        if core not in CORES:
            return web.json_response({"ok": False, "error": "неизвестное ядро"})
        try:
            return web.json_response({"ok": True, "versions": await self.versions(core)})
        except Exception as e:
            return web.json_response({"ok": False, "error": f"не удалось получить версии {CORES[core]['name']}: {e}"})

    async def h_create(self, request):
        d = await request.json()
        used = set()
        for x in self.servers:
            used |= {x["port"], x["rcon_port"], x.get("rest_port") or 0}
        if str(d.get("game") or "minecraft") in STEAM_GAMES:
            try:
                s = self.steam_new(d, used)
            except (TypeError, ValueError):
                return web.json_response({"ok": False, "error": "порт и число игроков — числа"})
            if s["port"] in used:
                return web.json_response({"ok": False, "error": f"порт {s['port']} уже занят другим твоим сервером"})
            s.update(id=_slug(s["name"]), created=time.strftime("%Y-%m-%d %H:%M"))
            os.makedirs(self._folder(s), exist_ok=True)
            self.servers.append(s)
            self._save()
            self.jobs[s["id"]] = {"state": "downloading", "progress": 0.0, "error": ""}

            async def run():
                try:
                    await self._steam_install(s, self.jobs[s["id"]])
                    self.jobs[s["id"]]["state"] = "done"
                    self.log("СЕРВЕРЫ", f"Скачан сервер {STEAM_GAMES[s['game']]['name']} «{s['name']}»")
                except Exception as e:
                    self.jobs[s["id"]].update(state="error", error=str(e))
                    self._push(s["id"], f"✗ {e}")
                    self.log("ОШИБКА СЕРВЕРА", f"«{s['name']}»: {e}")
            asyncio.ensure_future(run())
            return web.json_response({"ok": True, "id": s["id"]})
        if not d.get("eula"):
            return web.json_response({"ok": False, "error": "нужно принять EULA Minecraft"})
        name = str(d.get("name") or "").strip()[:40]
        core = str(d.get("core") or "paper")
        if core not in CORES:
            return web.json_response({"ok": False, "error": "неизвестное ядро"})
        version, _, loader = str(d.get("version") or "").strip().partition("|")
        if not name or not version:
            return web.json_response({"ok": False, "error": "укажи название и версию"})
        try:
            port = int(d.get("port") or 25565)
            ram = max(1, min(32, int(d.get("ram") or 3)))
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "порт и память — числа"})
        used = {x["port"] for x in self.servers} | {x["rcon_port"] for x in self.servers}
        if port in used:
            return web.json_response({"ok": False, "error": f"порт {port} уже занят другим твоим сервером"})
        rcon_port = port + 10
        while rcon_port in used or rcon_port == port:
            rcon_port += 1
        s = {"id": _slug(name), "name": name, "core": core, "loader": loader, "version": version,
             "port": port, "rcon_port": rcon_port,
             "rcon_password": secrets.token_urlsafe(12), "ram": ram,
             "online_mode": bool(d.get("online_mode", True)), "gamemode": str(d.get("gamemode") or "survival"),
             "difficulty": str(d.get("difficulty") or "normal"), "seed": str(d.get("seed") or "")[:40],
             "created": time.strftime("%Y-%m-%d %H:%M")}
        os.makedirs(self._folder(s), exist_ok=True)
        self.servers.append(s)
        self._save()
        self.jobs[s["id"]] = {"state": "downloading", "progress": 0.0, "error": ""}
        self._push(s["id"], f"Скачиваю {CORES[core]['name']} {version}{' (' + loader + ')' if loader else ''}…")
        asyncio.ensure_future(self._create_job(s))
        return web.json_response({"ok": True, "id": s["id"]})

    async def h_java(self, request):
        d = await request.json()
        try:
            feature = int(d.get("feature") or 21)
        except (TypeError, ValueError):
            feature = 21
        if self.java_job and self.java_job["state"] in ("downloading", "extracting"):
            return web.json_response({"ok": False, "error": "Java уже скачивается"})
        self.java_job = {"state": "downloading", "progress": 0.0, "error": "", "feature": feature}
        asyncio.ensure_future(self._java_job(feature))
        return web.json_response({"ok": True})

    async def h_log(self, request):
        sid = request.match_info["sid"]
        s = self._get(sid)
        if not s:
            return web.json_response({"ok": False, "error": "нет такого сервера"}, status=404)
        try:
            since = int(request.query.get("since", "0"))
        except ValueError:
            since = 0
        r = self._rt(sid)
        lines = [[n, t] for n, t in r["lines"] if n > since]
        return web.json_response({"ok": True, "lines": lines, "last": r["seq"], "status": self.status(s),
                                  "players": sorted(r["players"])})

    async def h_action(self, request):
        sid, action = request.match_info["sid"], request.match_info["action"]
        s = self._get(sid)
        if not s:
            return web.json_response({"ok": False, "error": "нет такого сервера"}, status=404)
        if action == "start":
            return web.json_response(await self.start(s))
        if action == "stop":
            return web.json_response(await self.stop(s))
        if action == "kill":
            p = self._rt(sid)["proc"]
            if p is not None:
                p.kill()
            return web.json_response({"ok": True})
        if action == "command":
            d = await request.json()
            return web.json_response(await self.command(s, d.get("cmd")))
        if action == "update":
            if s.get("game", "minecraft") == "minecraft":
                return web.json_response({"ok": False, "error": "обновление — только для Steam-игр"})
            return web.json_response(await self._steam_update(s))
        if action == "connect" and s.get("game", "minecraft") != "minecraft":
            game = s["game"]
            if game not in GIFT_GAMES:
                return web.json_response({"ok": False, "error": f"для {STEAM_GAMES[game]['name']} подарки через сервер не работают — используй вкладку «⌨ Любая игра»"})
            c = self.cfg()
            c.update({f"{game}_host": "127.0.0.1", f"{game}_port": s["rcon_port"], f"{game}_password": s["rcon_password"]})
            if game == "palworld":
                c["palworld_rest_port"] = s.get("rest_port") or 8212
            self.save_cfg()
            self.log("СЕРВЕРЫ", f"Подарки {STEAM_GAMES[game]['name']} теперь идут на локальный сервер «{s['name']}»")
            return web.json_response({"ok": True})
        if action == "connect":
            c = self.cfg()
            c.update({"mc_transport": "rcon", "servertap_host": "127.0.0.1",
                      "rcon_port": s["rcon_port"], "rcon_password": s["rcon_password"]})
            self.save_cfg()
            self.log("СЕРВЕРЫ", f"Подарки теперь идут на локальный сервер «{s['name']}» (RCON :{s['rcon_port']})")
            return web.json_response({"ok": True})
        if action == "open_folder":
            sub = request.query.get("sub", "")
            path = self._folder(s)
            if sub in ("mods", "plugins", "world", "logs"):
                path = os.path.join(path, sub)
                os.makedirs(path, exist_ok=True)
            try:
                if WIN:
                    os.startfile(path)
                    return web.json_response({"ok": True})
            except Exception as e:
                return web.json_response({"ok": False, "error": str(e)})
            return web.json_response({"ok": False, "error": "открыть папку можно только на Windows", "path": path})
        if action == "delete":
            if self._rt(sid)["proc"] is not None or self.status(s) == "external":
                return web.json_response({"ok": False, "error": "сначала останови сервер"})
            await asyncio.get_event_loop().run_in_executor(None, shutil.rmtree, self._folder(s), True)
            self.servers = [x for x in self.servers if x["id"] != sid]
            self.run.pop(sid, None)
            self.jobs.pop(sid, None)
            self._save()
            self.log("СЕРВЕРЫ", f"Удалён сервер «{s['name']}»")
            return web.json_response({"ok": True})
        return web.json_response({"ok": False, "error": "неизвестное действие"}, status=400)
