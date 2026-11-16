"""🎙 ИИ-голос: связка с программой смены голоса deiteris/voice-changer (RVC).

TakyLive сам её скачивает и ставит, запускает в фоне, настраивает звук
(микрофон → ИИ → виртуальный кабель VB-CABLE → OBS / TikTok LIVE Studio),
загружает голоса и переключает их по подаркам командой в цепочке:

    voice:Демон:30   — голос «Демон» на 30 секунд (имя или номер слота)
    voice:Демон      — на время по умолчанию
    voice:off        — сразу вернуть обычный голос

Голосовая программа слушает только этот компьютер (127.0.0.1:18888); мы ходим к ней
по её же API (/info, /update_settings, /upload_file, /load_model).
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import zipfile

import aiohttp

IS_WIN = sys.platform == "win32"
RELEASES_API = "https://api.github.com/repos/deiteris/voice-changer/releases/latest"
CABLE_URLS = ("https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
              "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip")
CABLE_PAGE = "https://vb-audio.com/Cable/"
HF_BASE = (os.environ.get("TAKY_HF_BASE") or "https://huggingface.co").rstrip("/")   # для автопроверки — подмена
REPO_RE = re.compile(r"^(?![.\-])(?!.*\.\.)[\w.\-]{1,96}/(?![.\-])[\w.\-]{1,96}$")   # без «..» и «./»
MAX_HUB_FILE = 2 << 30

# Названия моделей на Hugging Face — латиницей. Частые русские слова переводим сами
# (ключ — начало слова, чтобы «робота», «девушки», «низкий» тоже находились).
RU_EN = [
    ("робот", "robot"), ("демон", "demon"), ("дьявол", "devil"), ("монстр", "monster"), ("зомби", "zombie"),
    ("орк", "orc"), ("гоблин", "goblin"), ("инопланет", "alien"), ("пришелец", "alien"), ("бурундук", "chipmunk"),
    ("кот", "cat"), ("кошк", "cat"), ("собак", "dog"), ("пёс", "dog"), ("пес", "dog"), ("дракон", "dragon"),
    ("девуш", "girl"), ("девоч", "girl"), ("женск", "female"), ("женщин", "woman"), ("мужск", "male"),
    ("мужик", "man"), ("мужчин", "man"), ("парен", "boy"), ("парн", "boy"), ("мальчик", "boy"), ("ребён", "kid"),
    ("ребен", "kid"), ("детск", "kid"), ("старик", "old"), ("стар", "old"), ("бабушк", "granny"),
    ("низк", "deep"), ("глубок", "deep"), ("бас", "bass"), ("высок", "high"), ("пискляв", "squeaky"),
    ("хрипл", "raspy"), ("груб", "rough"), ("мягк", "soft"), ("нежн", "soft"), ("мил", "cute"),
    ("аниме", "anime"), ("мульт", "cartoon"), ("злой", "evil"), ("зло", "evil"), ("страшн", "scary"),
    ("рассказчик", "narrator"), ("диктор", "announcer"), ("радио", "radio"), ("рэп", "rap"), ("певец", "singer"),
    ("певиц", "singer"), ("русск", "russian"), ("англ", "english"), ("японск", "japanese"),
]
# ⭐ Рекомендуемые голоса: в программе только ссылки (модель на Hugging Face + имена файлов),
# сами файлы каждый скачивает себе сам. Список лежит рядом с программой и обновляется
# с GitHub без нового релиза. Только открытые лицензии и не клоны реальных людей/персонажей.
PRESETS_FILE = "voice_presets.json"
PRESETS_URL = os.environ.get("TAKY_PRESETS_URL") or \
    "https://raw.githubusercontent.com/serzhaleksiyuk96-lang/TakyLive/main/voice_presets.json"
FILE_RE = re.compile(r"^(?!.*\.\.)[\w .,()\[\]\-/]{1,200}$")


def clean_presets(d):
    out = []
    for v in (d or {}).get("voices") or []:
        if not isinstance(v, dict):
            continue
        repo, model, index, zp = (str(v.get(k) or "").strip() for k in ("repo", "model", "index", "zip"))
        if not REPO_RE.match(repo) or not (model or zp):
            continue
        if any(f and not FILE_RE.match(f) for f in (model, index, zp)):
            continue
        out.append({"name": str(v.get("name") or "")[:40] or "Голос", "emoji": str(v.get("emoji") or "🎙")[:4],
                    "desc": str(v.get("desc") or "")[:160], "repo": repo, "model": model, "index": index, "zip": zp,
                    "license": str(v.get("license") or "")[:40], "size_mb": int(v.get("size_mb") or 0)})
    return out[:60]


STOP_WORDS = {"голос", "голоса", "голосом", "voice", "voices", "rvc", "model", "модель", "и", "а", "the"}


def hub_terms(q):
    """Запрос → слова для поиска: латиница как есть, русские частые слова — по-английски."""
    out, unknown = [], []
    for w in re.findall(r"[\w\-]+", str(q or "").lower()):
        if w in STOP_WORDS:
            continue
        if re.search(r"[а-яё]", w):
            en = next((e for ru, e in RU_EN if w.startswith(ru)), None)
            (out if en else unknown).append(en or w)
        else:
            out.append(w)
    seen, terms = set(), []
    for t in out:
        if t not in seen and len(t) >= 2:
            seen.add(t)
            terms.append(t)
    return terms[:3], unknown
EXE_NAME = "MMVCServerSIO.exe" if IS_WIN else "MMVCServerSIO"
MIN_DRIVER = (528, 33)

DEFAULTS = {
    "vc_dir": "",               # куда ставить голосовую программу (пусто — %LOCALAPPDATA%\TakyLive-Voice)
    "vc_port": 18888,
    "vc_autostart": False,      # запускать вместе с TakyLive
    "vc_mic_name": "",          # микрофон (по имени — номера устройств в Windows меняются)
    "vc_out_name": "",          # куда отдавать голос (пусто — CABLE Input)
    "vc_monitor_name": "",      # слышать себя (пусто — не слышать)
    "vc_normal": "",            # обычный голос: пусто — свой, иначе имя ИИ-голоса
    "vc_secs": 30,              # сколько держится голос из подарка по умолчанию
    "vc_say": True,             # писать в оверлей «Голос … от …»
}


def _ver(s):
    nums = [int(x) for x in re.findall(r"\d+", str(s))[:2]]
    return tuple(nums + [0] * (2 - len(nums)))


def parse_command(cmd):
    """«voice:Демон:30» → ("Демон", 30); «voice:off» → ("off", 0); «voice:2» → ("2", None)."""
    body = str(cmd or "").strip()[6:].strip()
    if not body:
        return None, None
    m = re.match(r"^(.*?)(?::\s*(\d{1,4})\s*(?:с|сек|s)?)?$", body, re.I)
    name = (m.group(1) if m else body).strip()
    secs = int(m.group(2)) if m and m.group(2) else None
    return name, secs


class VoiceChanger:
    def __init__(self, base_dir, log, get_cfg):
        self.base_dir = base_dir
        self.log = log
        self.get_cfg = get_cfg
        self.proc = None
        self.started_at = 0.0
        self.install_state = {"stage": "", "done": 0, "total": 0, "error": "", "running": False}
        self._cancel = False
        self.slots_cache = []
        self.active = None            # {"name", "slot", "user", "until"}
        self.lock = asyncio.Lock()
        self.nv = None
        self.hub_state = {"running": False, "stage": "", "done": 0, "total": 0, "error": "", "ok": ""}

    # ── где лежит ────────────────────────────────────────────────────────────
    def dir(self):
        d = str(self.get_cfg().get("vc_dir") or "").strip()
        if d:
            return d
        root = os.environ.get("LOCALAPPDATA") if IS_WIN else None
        return os.path.join(root, "TakyLive-Voice") if root else os.path.join(self.base_dir, "voice-changer")

    def exe(self):
        root = self.dir()
        if not os.path.isdir(root):
            return ""
        for cur, dirs, files in os.walk(root):
            if cur[len(root):].count(os.sep) > 3:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in ("_download", "model_dir", "pretrain", "_internal")]
            if EXE_NAME in files:
                return os.path.join(cur, EXE_NAME)
        return ""

    def url(self, path):
        try:
            port = int(self.get_cfg().get("vc_port") or 18888)
        except (TypeError, ValueError):
            port = 18888
        return f"http://127.0.0.1:{port}{path}"

    # ── API голосовой программы ─────────────────────────────────────────────
    async def _req(self, method, path, data=None, timeout=8):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.request(method, self.url(path), data=data) as r:
                if r.status != 200:
                    raise RuntimeError(f"голосовая программа ответила {r.status}")
                try:
                    return await r.json(content_type=None)
                except Exception:
                    return {}

    async def alive(self):
        try:
            await self._req("GET", "/api/hello", timeout=2)
            return True
        except Exception:
            return False

    async def set(self, key, val):
        return await self._req("POST", "/update_settings", data={"key": key, "val": str(val)}, timeout=20)

    async def info(self):
        d = await self._req("GET", "/info", timeout=15)
        slots = []
        for s in d.get("modelSlots") or []:
            if isinstance(s, dict) and s.get("voiceChangerType") and isinstance(s.get("slotIndex", 0), int):
                slots.append({"slot": int(s.get("slotIndex", len(slots))), "name": s.get("name") or f"Голос {len(slots)}",
                              "tune": s.get("defaultTune", 0)})
        self.slots_cache = slots

        def devs(key):
            out = []
            for x in d.get(key) or []:
                if isinstance(x, dict) and ("WASAPI" in str(x.get("hostAPI", "")) or not IS_WIN):
                    out.append({"index": x.get("index"), "name": x.get("name", "")})
            return out
        gpus = [g for g in d.get("gpus") or [] if isinstance(g, dict)]
        return {
            "slots": slots,
            "inputs": devs("serverAudioInputDevices"),
            "outputs": devs("serverAudioOutputDevices"),
            "gpus": [{"id": g.get("id"), "name": g.get("name")} for g in gpus],
            "settings": {k: d.get(k) for k in ("modelSlotIndex", "passThrough", "serverAudioStated", "gpu",
                                                "tran", "f0Detector", "serverReadChunkSize", "extraConvertSize",
                                                "crossFadeOverlapSize", "serverInputDeviceId",
                                                "serverOutputDeviceId", "serverMonitorDeviceId")},
            "perf": d.get("performance") or d.get("perf"),
        }

    # ── видеокарта ──────────────────────────────────────────────────────────
    async def nvidia(self):
        if self.nv is not None:
            return self.nv
        res = {"ok": False, "name": "", "driver": "", "driver_ok": False}
        exe = shutil.which("nvidia-smi")
        if not exe and IS_WIN:
            cand = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
            exe = cand if os.path.exists(cand) else None
        if exe:
            try:
                kw = {"creationflags": 0x08000000} if IS_WIN else {}
                p = await asyncio.create_subprocess_exec(
                    exe, "--query-gpu=name,driver_version", "--format=csv,noheader",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **kw)
                out, _ = await asyncio.wait_for(p.communicate(), 10)
                line = out.decode("utf-8", "replace").strip().splitlines()[0]
                name, drv = [x.strip() for x in line.split(",", 1)]
                res.update(ok=True, name=name, driver=drv, driver_ok=_ver(drv) >= MIN_DRIVER)
            except Exception:
                pass
        self.nv = res
        return res

    # ── установка ───────────────────────────────────────────────────────────
    def installing(self):
        return self.install_state.get("running")

    def cancel_install(self):
        self._cancel = True

    async def install(self, backend=None):
        """Скачивает последний релиз deiteris/voice-changer под Windows и распаковывает."""
        st = self.install_state
        if st.get("running"):
            return
        st.update(stage="Ищу последнюю версию…", done=0, total=0, error="", running=True)
        self._cancel = False
        root = self.dir()
        dl_dir = os.path.join(root, "_download")
        try:
            if not IS_WIN:
                raise RuntimeError("голосовая программа ставится только на Windows")
            if backend is None:
                backend = "cuda" if (await self.nvidia()).get("ok") else "dml"
            os.makedirs(dl_dir, exist_ok=True)
            hdr = {"User-Agent": "TakyLive", "Accept": "application/vnd.github+json"}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), headers=hdr) as s:
                async with s.get(RELEASES_API) as r:
                    if r.status != 200:
                        raise RuntimeError(f"GitHub ответил {r.status} — попробуй позже")
                    rel = await r.json()
            prefix = f"voice-changer-windows-amd64-{backend}.zip"
            assets = sorted([a for a in rel.get("assets") or [] if str(a.get("name", "")).startswith(prefix)],
                            key=lambda a: a["name"])
            if not assets:
                raise RuntimeError(f"в релизе {rel.get('tag_name')} нет файла {prefix}")
            total = sum(int(a.get("size") or 0) for a in assets)
            free = shutil.disk_usage(os.path.dirname(os.path.abspath(root)) or root).free
            if free < total * 2.3 + (1 << 30):
                raise RuntimeError(f"мало места на диске: нужно ≈{(total * 2.3) / 2**30 + 1:.0f} ГБ, "
                                   f"свободно {free / 2**30:.0f} ГБ")
            st.update(stage=f"Скачиваю {rel.get('tag_name')} ({backend.upper()})", total=total, done=0)
            parts = []
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=120),
                                             headers={"User-Agent": "TakyLive"}) as s:
                for a in assets:
                    path = os.path.join(dl_dir, a["name"])
                    parts.append(path)
                    if os.path.exists(path) and os.path.getsize(path) == int(a.get("size") or -1):
                        st["done"] += os.path.getsize(path)          # уже скачан раньше
                        continue
                    async with s.get(a["browser_download_url"]) as r:
                        if r.status != 200:
                            raise RuntimeError(f"не скачался {a['name']}: {r.status}")
                        with open(path + ".part", "wb") as f:
                            async for chunk in r.content.iter_chunked(1 << 20):
                                if self._cancel:
                                    raise RuntimeError("отменено")
                                f.write(chunk)
                                st["done"] += len(chunk)
                    os.replace(path + ".part", path)
            st.update(stage="Распаковываю (несколько минут)…", done=0, total=0)
            await asyncio.to_thread(self._extract, parts, root)
            shutil.rmtree(dl_dir, ignore_errors=True)
            if not self.exe():
                raise RuntimeError("после распаковки не нашёл MMVCServerSIO.exe")
            st.update(stage="Готово ✓", error="")
            self.log("ГОЛОС", f"🎙 Голосовая программа установлена: {self.dir()}")
        except Exception as e:
            st.update(stage="", error=str(e))
            self.log("ОШИБКА", f"ИИ-голос: установка — {e}")
        finally:
            st["running"] = False

    def _extract(self, parts, root):
        """Части .zip.001/.002 — это один zip, порезанный на куски: склеиваем и распаковываем."""
        if len(parts) == 1:
            src = parts[0]
        else:
            src = os.path.join(os.path.dirname(parts[0]), "voice-changer.zip")
            with open(src, "wb") as out:
                for p in parts:
                    with open(p, "rb") as f:
                        shutil.copyfileobj(f, out, 8 << 20)
                    os.remove(p)
        st = self.install_state
        with zipfile.ZipFile(src) as z:
            names = z.infolist()
            st["total"] = len(names)
            real_root = os.path.realpath(root)
            for i, info in enumerate(names):
                if self._cancel:
                    raise RuntimeError("отменено")
                dest = os.path.realpath(os.path.join(root, info.filename))
                if not dest.startswith(real_root + os.sep) and dest != real_root:
                    continue                                  # защита от «../» в архиве
                z.extract(info, root)
                st["done"] = i + 1
        os.remove(src)

    # ── запуск ───────────────────────────────────────────────────────────────
    def proc_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        exe = self.exe()
        if not exe:
            raise RuntimeError("голосовая программа не установлена")
        if self.proc_alive():
            return
        logf = open(os.path.join(self.dir(), "voice_changer_log.txt"), "a", encoding="utf-8", errors="replace")
        kw = {"creationflags": 0x08000000} if IS_WIN else {}       # без чёрного окна
        self.proc = subprocess.Popen([exe], cwd=os.path.dirname(exe), stdout=logf, stderr=subprocess.STDOUT, **kw)
        self.started_at = time.time()
        self.log("ГОЛОС", "🎙 Запускаю голосовую программу (первый раз она качает файлы — пару минут)")

    def stop(self):
        if self.proc_alive():
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except Exception:
                self.proc.kill()
            self.log("ГОЛОС", "🎙 Голосовая программа остановлена")
        self.proc = None
        self.active = None

    # ── VB-CABLE ─────────────────────────────────────────────────────────────
    async def install_cable(self):
        """Скачивает VB-CABLE с сайта VB-Audio и запускает установщик с правами администратора."""
        if not IS_WIN:
            raise RuntimeError("только для Windows")
        tmp = tempfile.mkdtemp(prefix="vbcable_")
        zpath = os.path.join(tmp, "cable.zip")
        last = ""
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120),
                                         headers={"User-Agent": "TakyLive"}) as s:
            for u in CABLE_URLS:
                try:
                    async with s.get(u) as r:
                        if r.status == 200:
                            with open(zpath, "wb") as f:
                                f.write(await r.read())
                            break
                        last = f"{r.status}"
                except Exception as e:
                    last = str(e)
            else:
                raise RuntimeError(f"не скачался VB-CABLE ({last}) — открой {CABLE_PAGE}")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        setup = os.path.join(tmp, "VBCABLE_Setup_x64.exe")
        if not os.path.exists(setup):
            raise RuntimeError("в архиве VB-CABLE нет установщика")
        ps = f"Start-Process -FilePath '{setup}' -WorkingDirectory '{tmp}' -Verb RunAs"
        subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000)
        self.log("ГОЛОС", "🔌 Запущена установка VB-CABLE: нажми «Да», потом Install Driver и перезагрузи ПК")

    # ── звук ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _find(devs, name, contains=None):
        name = str(name or "").strip().lower()
        if name:
            for d in devs:
                if d["name"].lower() == name:
                    return d
        if contains:
            for d in devs:
                if contains in d["name"].lower():
                    return d
        return None

    async def setup_audio(self, cfg):
        """Микрофон → ИИ → CABLE Input (+ «слышать себя»), видеокарта, rmvpe — и включаем."""
        inf = await self.info()
        mic = self._find(inf["inputs"], cfg.get("vc_mic_name"))
        out = self._find(inf["outputs"], cfg.get("vc_out_name"), contains="cable input")
        if not mic:
            raise RuntimeError("выбери микрофон")
        if not out:
            raise RuntimeError("не нашёл «CABLE Input» — поставь VB-CABLE и перезагрузи ПК")
        mon = self._find(inf["outputs"], cfg.get("vc_monitor_name")) if cfg.get("vc_monitor_name") else None
        gpu = next((g["id"] for g in inf["gpus"] if g.get("id", -1) >= 0), -1)
        await self.set("serverAudioStated", 0)
        for k, v in (("enableServerAudio", 1), ("serverAudioSampleRate", 48000), ("serverInputDeviceId", mic["index"]),
                     ("serverOutputDeviceId", out["index"]), ("serverMonitorDeviceId", mon["index"] if mon else -1),
                     ("gpu", gpu), ("f0Detector", "rmvpe_onnx")):
            await self.set(k, v)
        if inf["slots"] and (inf["settings"].get("modelSlotIndex") in (None, -1)):
            await self.set("modelSlotIndex", inf["slots"][0]["slot"])
        await self.apply_normal(cfg)
        await self.set("serverAudioStated", 1)
        self.log("ГОЛОС", f"🎙 ИИ-голос включён: {mic['name']} → {out['name']}" + (f", слышно в {mon['name']}" if mon else ""))
        return {"mic": mic["name"], "out": out["name"], "monitor": mon["name"] if mon else ""}

    async def audio_off(self):
        await self.set("serverAudioStated", 0)
        self.active = None

    # ── голоса ───────────────────────────────────────────────────────────────
    def find_slot(self, name):
        n = str(name or "").strip().lower()
        if not n:
            return None
        if n.isdigit():
            for s in self.slots_cache:
                if s["slot"] == int(n):
                    return s
            idx = int(n)
            return self.slots_cache[idx] if idx < len(self.slots_cache) else None
        for s in self.slots_cache:
            if s["name"].lower() == n:
                return s
        for s in self.slots_cache:
            if n in s["name"].lower():
                return s
        return None

    async def apply_normal(self, cfg):
        """Обычный голос: свой (без ИИ) или выбранный «основной» ИИ-голос."""
        normal = self.find_slot(cfg.get("vc_normal")) if cfg.get("vc_normal") else None
        if normal:
            await self.set("modelSlotIndex", normal["slot"])
            await self.set("passThrough", "false")
        else:
            await self.set("passThrough", "true")

    async def activate(self, name, secs, user=""):
        """Включает ИИ-голос по имени/номеру на secs секунд (новый подарок перебивает прошлый)."""
        cfg = self.get_cfg()
        async with self.lock:
            if not self.find_slot(name):
                await self.info()
            s = self.find_slot(name)
            if not s:
                raise RuntimeError(f"нет голоса «{name}» — загрузи его во вкладке 🎙")
            secs = int(secs or cfg.get("vc_secs") or 30)
            await self.set("modelSlotIndex", s["slot"])      # высоту голоса программа берёт из настроек слота
            await self.set("passThrough", "false")
            self.active = {"name": s["name"], "slot": s["slot"], "user": user or "", "until": time.time() + secs,
                           "secs": secs}
        self.log("ГОЛОС", f"🎙 {user + ': ' if user else ''}голос «{s['name']}» на {secs} сек")
        return self.active

    async def reset(self):
        async with self.lock:
            self.active = None
            await self.apply_normal(self.get_cfg())
        self.log("ГОЛОС", "🎙 Обычный голос")

    async def command(self, cmd, user=""):
        name, secs = parse_command(cmd)
        if not name:
            return False
        if name.lower() in ("off", "стоп", "выкл", "обычный", "normal"):
            await self.reset()
        else:
            await self.activate(name, secs, user)
        return True

    async def tick(self):
        a = self.active
        if a and time.time() >= a["until"]:
            try:
                await self.reset()
            except Exception as e:
                self.active = None
                self.log("ОШИБКА", f"ИИ-голос: не вернул обычный голос — {e}")

    def overlay(self):
        a = self.active
        if not a:
            return None
        return {"name": a["name"], "user": a["user"], "left": max(0, int(a["until"] - time.time() + 0.99)),
                "secs": a["secs"]}

    # ── свои голоса ──────────────────────────────────────────────────────────
    async def upload_model(self, slot, model_path, index_path=None):
        """Загружает .pth/.onnx (+ .index) в слот голосовой программы."""
        files = []
        timeout = aiohttp.ClientTimeout(total=None, sock_read=600)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for path, kind in ((model_path, "rvcModel"), (index_path, "rvcIndex")):
                if not path:
                    continue
                name = os.path.basename(path)
                form = aiohttp.FormData()
                form.add_field("filename", name)
                with open(path, "rb") as f:
                    form.add_field("file", f, filename=name, content_type="application/octet-stream")
                    async with s.post(self.url("/upload_file"), data=form) as r:
                        if r.status != 200:
                            raise RuntimeError(f"не загрузился {name}: {r.status}")
                files.append({"name": name, "kind": kind, "dir": ""})
            params = {"voiceChangerType": "RVC", "slot": int(slot), "isSampleMode": False, "sampleId": "",
                      "files": files, "params": {}}
            form = aiohttp.FormData()
            form.add_field("slot", str(int(slot)))
            form.add_field("isHalf", "false")
            form.add_field("params", json.dumps(params))
            async with s.post(self.url("/load_model"), data=form) as r:
                if r.status != 200:
                    raise RuntimeError(f"голосовая программа не приняла модель: {r.status}")
        await self.info()
        self.log("ГОЛОС", f"🎙 Голос загружен в слот {slot}: {os.path.basename(model_path)}")

    def free_slot(self):
        used = {s["slot"] for s in self.slots_cache}
        i = 0
        while i in used:
            i += 1
        return i

    # ── библиотека голосов: модели RVC на Hugging Face ──────────────────────
    async def _hf_json(self, path, params=None):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                                         headers={"User-Agent": "TakyLive"}) as s:
            async with s.get(HF_BASE + path, params=params) as r:
                if r.status != 200:
                    raise RuntimeError(f"Hugging Face ответил {r.status}")
                return await r.json(content_type=None)

    async def hub_search(self, q):
        """Ищет модели RVC на Hugging Face (по тегу rvc, самые скачиваемые сверху)."""
        q = str(q or "").strip()[:60]
        if len(q) < 2:
            raise RuntimeError("впиши, какой голос ищешь")
        terms, unknown = hub_terms(q)
        if not terms:
            raise RuntimeError("не понял «" + " ".join(unknown or [q]) + "» — напиши по-английски, например robot, "
                               "demon, girl, deep")
        base = {"sort": "downloads", "direction": "-1", "limit": "40"}
        found = {}

        def add(items):
            for m in items:
                rid = str(m.get("id") or m.get("modelId") or "")
                if REPO_RE.match(rid) and rid not in found:
                    found[rid] = {"id": rid, "downloads": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0)}
        add(await self._hf_json("/api/models", dict(base, filter="rvc", search=" ".join(terms))))
        if not found:                          # несколько слов — ищем каждое отдельно
            for t in terms:
                add(await self._hf_json("/api/models", dict(base, filter="rvc", search=t)))
        if not found:                          # без тега rvc — но с rvc в названии или тегах
            for t in terms:
                raw = await self._hf_json("/api/models", dict(base, search=t, limit="80"))
                add([m for m in raw if "rvc" in str(m.get("id", "")).lower()
                     or any("rvc" in str(x).lower() for x in m.get("tags") or [])])
        items = sorted(found.values(), key=lambda m: -m["downloads"])[:40]
        return {"items": items, "terms": terms, "unknown": unknown}

    @staticmethod
    def _is_voice_file(name):
        base = os.path.basename(name)
        low = base.lower()
        if not low.endswith((".pth", ".onnx", ".safetensors")):
            return False
        # файлы обучения (G_/D_), предобученные основы и чекпоинты — не голоса
        return not re.match(r"^(g_|d_|f0g|f0d|g\d|d\d)", low) and "pretrain" not in name.lower() \
            and "hubert" not in low and "rmvpe" not in low

    async def hub_files(self, repo):
        """Что можно поставить из репозитория: пары .pth (+ .index) и .zip-архивы."""
        if not REPO_RE.match(str(repo or "")):
            raise RuntimeError("неверное имя модели")
        d = await self._hf_json(f"/api/models/{repo}", {"blobs": "true"})
        files = {str(f.get("rfilename")): int(f.get("size") or 0) for f in d.get("siblings") or [] if f.get("rfilename")}
        card = d.get("cardData") or {}
        lic = card.get("license") or next((t[8:] for t in d.get("tags") or [] if str(t).startswith("license:")), "")
        indexes = [f for f in files if f.lower().endswith(".index")]
        cands = []
        for f in files:
            if self._is_voice_file(f):
                folder = os.path.dirname(f)
                same = [i for i in indexes if os.path.dirname(i) == folder]
                same.sort(key=lambda i: (not os.path.basename(i).lower().startswith("added"), len(i)))
                idx = same[0] if same else (indexes[0] if len(indexes) == 1 else "")
                cands.append({"label": os.path.splitext(os.path.basename(f))[0], "model": f, "index": idx,
                              "zip": "", "size": files[f] + (files.get(idx) or 0)})
            elif f.lower().endswith(".zip"):
                cands.append({"label": os.path.splitext(os.path.basename(f))[0], "model": "", "index": "",
                              "zip": f, "size": files[f]})
        cands.sort(key=lambda c: c["label"].lower())
        return {"repo": repo, "license": str(lic or ""), "url": f"{HF_BASE}/{repo}", "candidates": cands[:200],
                "files": len(files)}

    def hub_busy(self):
        return self.hub_state.get("running")

    async def hub_install(self, repo, model="", index="", zip_name="", slot=None, name=""):
        """Скачивает голос с Hugging Face и загружает его в свободный слот голосовой программы."""
        st = self.hub_state
        if st.get("running"):
            raise RuntimeError("уже ставлю другой голос — подожди")
        st.update(running=True, stage="Проверяю…", done=0, total=0, error="", ok="")
        tmp = tempfile.mkdtemp(prefix="taky_hf_")
        try:
            info = await self.hub_files(repo)
            valid = {c["model"] for c in info["candidates"]} | {c["index"] for c in info["candidates"]} | \
                    {c["zip"] for c in info["candidates"]}
            for f in (model, index, zip_name):
                if f and f not in valid:
                    raise RuntimeError(f"в модели нет файла {f}")
            if not (model or zip_name):
                raise RuntimeError("выбери голос")
            label = re.sub(r"[^\w\-]+", "_", str(name or os.path.splitext(os.path.basename(model or zip_name))[0]))
            label = label.strip("_")[:60] or "voice"
            todo = [f for f in (zip_name, model, index) if f]
            got = {}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=120),
                                             headers={"User-Agent": "TakyLive"}) as s:
                for f in todo:
                    url = f"{HF_BASE}/{repo}/resolve/main/" + "/".join(urllib.parse.quote(x) for x in f.split("/"))
                    st.update(stage=f"Скачиваю {os.path.basename(f)}", done=0, total=0)
                    path = os.path.join(tmp, re.sub(r"[^\w.\-]+", "_", os.path.basename(f)))
                    async with s.get(url) as r:
                        if r.status != 200:
                            raise RuntimeError(f"не скачался {os.path.basename(f)}: {r.status}")
                        st["total"] = int(r.headers.get("Content-Length") or 0)
                        with open(path, "wb") as out:
                            async for chunk in r.content.iter_chunked(1 << 20):
                                st["done"] += len(chunk)
                                if st["done"] > MAX_HUB_FILE:
                                    raise RuntimeError("файл больше 2 ГБ")
                                out.write(chunk)
                    got[f] = path
            if zip_name:
                st.update(stage="Распаковываю…", done=0, total=0)
                model_path, index_path = await asyncio.to_thread(self._from_zip, got[zip_name], tmp)
            else:
                model_path, index_path = got[model], got.get(index)
            ext = os.path.splitext(model_path)[1]
            nice = os.path.join(tmp, label + ext)                  # голос в программе называется по имени файла
            if os.path.abspath(nice) != os.path.abspath(model_path):
                os.replace(model_path, nice)
            st.update(stage="Загружаю в голосовую программу…", done=0, total=0)
            if slot in (None, "", "auto"):
                await self.info()
                slot = self.free_slot()
            await self.upload_model(int(slot), nice, index_path)
            st.update(stage="", ok=f"✓ Голос «{label}» добавлен (слот {slot})")
            self.log("ГОЛОС", f"🎙 Из библиотеки: {repo} → «{label}»")
            return {"slot": int(slot), "name": label}
        except Exception as e:
            st.update(stage="", error=str(e) or type(e).__name__)
            raise
        finally:
            st["running"] = False
            shutil.rmtree(tmp, ignore_errors=True)

    def _from_zip(self, zpath, tmp):
        out = os.path.join(tmp, "unz")
        real = os.path.realpath(out)
        model, index = None, None
        with zipfile.ZipFile(zpath) as z:
            for info in z.infolist():
                n = info.filename
                if info.is_dir() or info.file_size > MAX_HUB_FILE:
                    continue
                if not (self._is_voice_file(n) or n.lower().endswith(".index")):
                    continue
                dest = os.path.realpath(os.path.join(out, os.path.basename(n)))
                if not dest.startswith(real + os.sep):
                    continue
                os.makedirs(out, exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst, 8 << 20)
                if n.lower().endswith(".index"):
                    if index is None or os.path.basename(n).lower().startswith("added"):
                        index = dest
                elif model is None or os.path.getsize(dest) > os.path.getsize(model):
                    model = dest
        if not model:
            raise RuntimeError("в архиве нет голоса (.pth)")
        return model, index

    async def presets(self):
        """Список «⭐ Рекомендуемые»: свежий с GitHub (раз в час), иначе — тот, что пришёл с программой."""
        now = time.time()
        cache = getattr(self, "_presets_cache", None)
        if cache and now - cache[0] < 3600:
            return cache[1]
        local = []
        try:
            with open(os.path.join(self.base_dir, PRESETS_FILE), encoding="utf-8") as f:
                local = clean_presets(json.load(f))
        except Exception:
            pass
        remote = None
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6),
                                             headers={"User-Agent": "TakyLive"}) as s:
                async with s.get(PRESETS_URL) as r:
                    if r.status == 200:
                        remote = clean_presets(json.loads(await r.text()))
        except Exception:
            pass
        lst = remote if remote else local
        self._presets_cache = (now, lst)
        return lst

    # ── состояние для окна ───────────────────────────────────────────────────
    async def status(self):
        running = await self.alive()
        st = {
            "platform_ok": IS_WIN,
            "installed": bool(self.exe()),
            "dir": self.dir(),
            "running": running,
            "starting": (not running) and self.proc_alive(),
            "ours": self.proc_alive(),
            "install": dict(self.install_state),
            "hub": dict(self.hub_state),
            "nvidia": await self.nvidia(),
            "active": self.overlay(),
            "ui_url": self.url("/"),
        }
        if running:
            try:
                st["info"] = await self.info()
                outs = st["info"]["outputs"]
                st["cable"] = any("cable input" in d["name"].lower() for d in outs)
            except Exception as e:
                st["info_error"] = str(e)
        return st
