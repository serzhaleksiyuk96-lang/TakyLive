"""Автопроверка TakyLive (версии 1.67–1.69 и всё общее).

Запуск из папки программы (там, где app.py):
    python tools/smoke_test.py              — всё, включая пульт с телефона
    python tools/smoke_test.py --no-remote  — без пульта (он слушает домашнюю сеть,
                                              Windows может спросить про брандмауэр)
    python tools/smoke_test.py --keep       — не удалять временную копию после проверки

Что делает:
  1. Копирует программу во временную папку БЕЗ данных стримера (config.json,
     profiles.json, очки, отчёты, серверы и ключи не копируются и не трогаются).
  2. Запускает копию в тестовом режиме: TAKY_TEST=1 (без окна и без автообновления)
     на свободном порту — установленной программе не мешает.
  3. Гоняет механики через API и /api/simulate: подарки, чат, очки, чат-команды за очки,
     битву команд, колесо фортуны, итоги эфира, пульт, защиту от чужих сайтов,
     ИИ-соведущего (на встроенном поддельном ИИ — денег не тратит, интернет не нужен).
  4. Печатает PASS/FAIL по каждому пункту. Код выхода 0 — всё прошло.

Нужен только Python 3.10+. Библиотеки ставит сама программа при первом запуске копии.
В TikTok, Telegram, Discord и платные ИИ-сервисы скрипт не ходит.
"""
import argparse
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# данные стримера — в копию не берём никогда
SKIP_NAMES = {".git", "__pycache__", "build", "dist", "reports", "servers", "backups", "_update",
              "config.json", "profiles.json", "viewer_voices.json", "viewer_points.json",
              "fish_key.txt", "gift_catalog.json", "live_gift_icons.json", "smoke_test_result.txt"}

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
    return bool(ok)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Api:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def req(self, path, data=None, headers=None, base=None, raw=False, timeout=30):
        url = (base or self.base) + path
        body = None
        h = dict(headers or {})
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        r = urllib.request.Request(url, data=body, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                status, text = resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode("utf-8", "replace")
        if raw:
            return status, text
        try:
            return status, json.loads(text)
        except ValueError:
            return status, text

    def get(self, path, **kw):
        return self.req(path, **kw)[1]

    def post(self, path, data=None, **kw):
        return self.req(path, data if data is not None else {}, **kw)[1]

    def log(self):
        return self.get("/api/log").get("log", [])

    def log_has(self, kind, pattern, since=0):
        rx = re.compile(pattern)
        return any(e["kind"] == kind and rx.search(e["text"]) for e in self.log()[since:])

    def balance(self, user):
        rows = self.get("/api/points?q=" + urllib.request.quote(user)).get("rows", [])
        for r in rows:
            if str(r.get("key", "")).lower() == user.lower() or str(r.get("user", "")).lower() == user.lower():
                return int(r.get("points", r.get("amount", r.get("p", 0))))
        return 0

    def sim(self, **kw):
        return self.post("/api/simulate", kw)

    def cfg(self, **kw):
        return self.post("/api/config", kw)


def wait_until(fn, timeout=15, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(step)
    return None


# ── поддельный ИИ в формате OpenAI ──────────────────────────────────────────────
MOCK_LOG = []


class MockAI(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        d = json.loads(self.rfile.read(n) or b"{}")
        if self.headers.get("Authorization") == "Bearer bad":
            return self._send(401, {"error": {"message": "Authentication Fails"}})
        if not self.path.endswith("/chat/completions"):
            return self._send(404, {"error": {"message": "not found"}})
        MOCK_LOG.append(d)
        now = (d.get("messages") or [{}])[-1].get("content", "").split("Сейчас:")[-1]   # без истории чата
        if "подарил" in now:
            ans = "<think>коротко</think>**Аня**, спасибо за «Galaxy»! 🌌 Вот это щедрость!"
        else:
            ans = "Всем привет, я Таки — ваш соведущий!"
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": ans}}]})

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def start_mock_ai():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# ── поддельная голосовая программа (deiteris/voice-changer) ────────────────────
MOCK_VC = {"settings": {"modelSlotIndex": 0, "passThrough": False, "serverAudioStated": 0}, "log": [],
           "slots": [{"slotIndex": 0, "voiceChangerType": "RVC", "name": "Девушка", "defaultTune": 12},
                     {"slotIndex": 1, "voiceChangerType": "RVC", "name": "Демон"},
                     {"slotIndex": 2, "voiceChangerType": None, "name": ""}],
           "uploads": [], "loaded": [],
           # звуковые устройства: номера меняются, когда подключают наушники — как в Windows
           "ins": [(1, "Микрофон (USB Mic)")], "outs": [(5, "Наушники (Realtek)"), (7, "CABLE Input (VB-Audio Virtual Cable)")],
           "stale": None,          # старый список, который программа отдаёт до первой неудачной попытки включить звук
           "broken": False,        # звук не включается совсем
           "logfile": ""}          # её журнал — туда пишется ошибка открытия устройства
MOCK_VC_PORT = 0
DEVSIG_FILE = ""                   # «отпечаток» звуковых устройств Windows — подделка для программы


def mock_vc_log(line):
    if MOCK_VC["logfile"]:
        os.makedirs(os.path.dirname(MOCK_VC["logfile"]), exist_ok=True)
        with open(MOCK_VC["logfile"], "a", encoding="utf-8") as f:
            f.write(line + "\n")


class MockVC(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/hello":
            return self._send({"result": "Index"})
        if self.path == "/info":
            dev = lambda i, n, inp: {"index": i, "name": n, "hostAPI": "Windows WASAPI",
                                      "maxInputChannels": 2 if inp else 0, "maxOutputChannels": 0 if inp else 2}
            on = MOCK_VC["settings"].get("serverAudioStated") == 1      # пока звук включён — списки пустые
            ins, outs = MOCK_VC["stale"] or (MOCK_VC["ins"], MOCK_VC["outs"])
            return self._send({**MOCK_VC["settings"], "modelSlots": MOCK_VC["slots"],
                               "gpus": [{"id": -1, "name": "CPU"}, {"id": 0, "name": "0: RTX 4060 (CUDA)"}],
                               "serverAudioInputDevices": [] if on else [dev(i, n, True) for i, n in ins],
                               "serverAudioOutputDevices": [] if on else [dev(i, n, False) for i, n in outs]})
        self._send({"detail": "Not Found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "")
        if self.path == "/update_settings":
            import urllib.parse as up
            if "multipart" in ctype:
                f = dict(re.findall(rb'name="(\w+)"\r\n\r\n([^\r]*)', body))
                f = {k.decode(): v.decode() for k, v in f.items()}
            else:
                f = {k: v[0] for k, v in up.parse_qs(body.decode()).items()}
            k, v = f.get("key"), f.get("val")
            MOCK_VC["log"].append((k, v))
            if k == "passThrough":
                v = v == "true"
            elif k in ("modelSlotIndex", "serverAudioStated", "serverInputDeviceId", "serverOutputDeviceId",
                       "serverMonitorDeviceId", "gpu", "tran", "serverReadChunkSize"):
                v = int(v)
            MOCK_VC["settings"][k] = v
            if k == "serverAudioStated" and v == 1:                     # открываем устройства по номерам
                st = MOCK_VC["settings"]
                good = st.get("serverInputDeviceId") in [i for i, _ in MOCK_VC["ins"]] and \
                    st.get("serverOutputDeviceId") in [i for i, _ in MOCK_VC["outs"]]
                if MOCK_VC["broken"] or not good:
                    mock_vc_log("2026-11-16 21:33:40 | ERROR | MMVC_Rest_Fileuploader | "
                                "'NoneType' object has no attribute 'maxInputChannels'")
                    MOCK_VC["stale"] = None                             # после неудачи список устройств свежий
            if k == "modelSlotIndex":                                   # как настоящая: высота — из настроек слота
                sl = next((x for x in MOCK_VC["slots"] if x["slotIndex"] == v), {})
                MOCK_VC["settings"]["tran"] = sl.get("defaultTune", 0)
            return self._send({"status": "OK"})
        if self.path == "/upload_file":
            m = re.search(rb'name="filename"\r\n\r\n([^\r]*)', body)
            MOCK_VC["uploads"].append((m.group(1).decode() if m else "?", len(body)))
            return self._send({"status": "OK"})
        if self.path == "/load_model":
            import urllib.parse as up
            if "multipart" in ctype:
                m = re.search(rb'name="params"\r\n\r\n(.*?)\r\n--', body, re.S)
                p = json.loads(m.group(1)) if m else {}
            else:                                   # aiohttp шлёт форму без файлов как urlencoded
                p = json.loads(up.parse_qs(body.decode()).get("params", ["{}"])[0])
            MOCK_VC["loaded"].append(p)
            name = (p.get("files") or [{}])[0].get("name", "x").rsplit(".", 1)[0]
            MOCK_VC["slots"] = [s for s in MOCK_VC["slots"] if s["slotIndex"] != p.get("slot")] + \
                               [{"slotIndex": p.get("slot"), "voiceChangerType": "RVC", "name": name}]
            return self._send({"status": "OK"})
        self._send({"detail": "Not Found"}, 404)


# поддельный MMVCServerSIO для проверки запуска: mode.txt — slow (2 раза «не докачал») / crash / ok
FAKE_VC_EXE = r'''#!/usr/bin/env python3
import http.server, json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
rd = lambda n, d="": open(os.path.join(here, n)).read().strip() if os.path.exists(os.path.join(here, n)) else d
n = int(rd("runs.txt", "0")) + 1
open(os.path.join(here, "runs.txt"), "w").write(str(n))
mode = rd("mode.txt", "ok")
if mode == "crash":
    print("2026-11-16 | ERROR | VoiceChangerV2 | CUDA is not available on this device", flush=True)
    sys.exit(3)
os.makedirs(os.path.join(here, "pretrain"), exist_ok=True)
with open(os.path.join(here, "pretrain", "rmvpe.onnx"), "ab") as f:
    f.write(b"x" * 200000)
if mode == "slow" and n < 3:
    print("2026-11-16 | ERROR | downloader | Failed to download or verify pretrain/rmvpe.onnx", flush=True)
    print("PretrainDownloadException: 'Failed to download pretrain models.'", flush=True)
    sys.exit(1)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = json.dumps({"result": "Index", "modelSlots": [], "gpus": []}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
http.server.HTTPServer(("127.0.0.1", __PORT__), H).serve_forever()
'''


# ── поддельный Hugging Face (библиотека голосов) ─────────────────────────────
def _zip_bytes(files):
    import io as _io
    import zipfile as _zf
    b = _io.BytesIO()
    with _zf.ZipFile(b, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    return b.getvalue()


MOCK_HF_FILES = {
    "tester/robot-rvc": {"robot.pth": b"PTH-ROBOT" * 100, "added_IVF256_robot.index": b"IDX" * 100,
                         "G_1000.pth": b"G" * 10, "README.md": b"# robot"},
    "tester/pack-rvc": {"voices.zip": _zip_bytes({"pack/demon.pth": b"PTH-DEMON" * 50,
                                                  "pack/added_demon.index": b"IDX" * 50, "pack/info.txt": b"hi"})},
}
MOCK_HF_FILES["tester/alien-voice-RVC"] = {"alien.pth": b"PTH-ALIEN" * 50}     # без тега rvc — только «RVC» в названии
MOCK_HF_FILES["tester/alien-coder-7b"] = {"model.safetensors": b"LLM"}          # мусор: не голос
MOCK_HF_TAGS = {"tester/alien-voice-RVC": [], "tester/alien-coder-7b": ["text-generation"]}
MOCK_HF_PORT = 0


class MockHF(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        import urllib.parse as up
        u = up.urlparse(self.path)
        q = up.parse_qs(u.query)
        if u.path == "/presets.json":
            return self._send({"voices": [
                {"name": "Робот", "emoji": "🤖", "desc": "металлический", "repo": "tester/robot-rvc", "model": "robot.pth",
                 "index": "added_IVF256_robot.index", "license": "mit", "size_mb": 1},
                {"name": "Авто", "emoji": "✨", "repo": "tester/pack-rvc", "auto": True, "license": "openrail"},
                {"name": "Плохой", "repo": "../evil", "model": "x.pth"},
                {"name": "Плохой2", "repo": "tester/robot-rvc", "model": "../../x.pth"}]})
        if u.path == "/api/models":
            words = (q.get("search") or [""])[0].lower().split()         # как на сайте: все слова — в названии
            need_tag = (q.get("filter") or [""])[0]
            items = [{"id": rid, "downloads": 100 - i, "likes": 5, "tags": MOCK_HF_TAGS.get(rid, ["rvc"])}
                     for i, rid in enumerate(MOCK_HF_FILES)
                     if all(w in rid.lower() for w in words) and (not need_tag or need_tag in MOCK_HF_TAGS.get(rid, ["rvc"]))
                     # как на сайте: по одному слову без тега в первых результатах — чужие популярные модели, не голоса
                     and not (not need_tag and "rvc" not in words and rid == "tester/alien-voice-RVC")]
            return self._send(items)
        m = re.match(r"^/api/models/([\w.\-]+/[\w.\-]+)$", u.path)
        if m and m.group(1) in MOCK_HF_FILES:
            files = MOCK_HF_FILES[m.group(1)]
            return self._send({"id": m.group(1), "cardData": {"license": "mit"}, "tags": ["rvc"],
                               "siblings": [{"rfilename": n, "size": len(b)} for n, b in files.items()]})
        m = re.match(r"^/([\w.\-]+/[\w.\-]+)/resolve/main/(.+)$", u.path)
        if m and m.group(1) in MOCK_HF_FILES and up.unquote(m.group(2)) in MOCK_HF_FILES[m.group(1)]:
            return self._send(None, raw=MOCK_HF_FILES[m.group(1)][up.unquote(m.group(2))])
        self._send({"error": "not found"}, 404)


def start_mock_hf():
    global MOCK_HF_PORT
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockHF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    MOCK_HF_PORT = srv.server_address[1]
    return srv


def start_mock_vc():
    global MOCK_VC_PORT
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockVC)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    MOCK_VC_PORT = srv.server_address[1]
    return srv


# ── подготовка копии ────────────────────────────────────────────────────────────
def make_copy(dst, remote_port):
    def ignore(dirpath, names):
        return [n for n in names if n in SKIP_NAMES or n.endswith((".pyc", ".log"))]
    shutil.copytree(ROOT, dst, ignore=ignore)
    profiles = {"Тест": {
        "game": "minecraft",
        "panel": [{"title": "💥 Тест-кнопка", "commands": ["say smoke"]}],
        "gifts": [{"name": "Rose", "gift_id": "5655", "title": "роза", "commands": ["say rose"]},
                  # эдит когда-то был .mov, программа перекодировала его в .mp4, а карточка осталась со старым именем
                  {"name": "Lion", "gift_id": "6369", "title": "лев", "commands": [], "media_file": "мой эдит.mov",
                   "media_kind": "video", "sound_file": "музыка.flac"},
                  {"name": "Кулон дружбы", "title": "кулон", "commands": []},          # по-русски, без ID
                  {"name": "Doughnut", "title": "пончик", "commands": []},             # из библиотеки, по-английски
                  {"name": "Тестовый дракон", "title": "дракон", "commands": []},      # узнаем только от TikTok (ru-RU)
                  {"name": "Загадочный подарок", "title": "загадка", "commands": []}],  # такого названия нет
        "chatcmds": [{"trigger": "!крипер", "title": "Крипер", "cooldown": 0, "points_cost": 30,
                      "commands": ["say creeper"]},
                     {"trigger": "!демон", "title": "Голос демона", "cooldown": 0,
                      "commands": ["voice:Демон:3"]}],
    }}
    config = {
        "active_profile": "Тест", "tiktok_username": "smoke_nick",
        # команды в игру уходят «в никуда» — порт 1 закрыт
        "mc_transport": "rcon", "rcon_port": 1, "servertap_port": 1,
        "tts_enabled": False, "random_enabled": False, "gift_icons_online": False,
        "pts_on": True, "pts_coin": 10, "pts_msg": 0, "pts_likes_n": 20, "pts_follow": 50,
        "wheel_on": True, "wheel_gift": "Rose", "wheel_secs": 3, "wheel_pts_cost": 40, "wheel_cmd": "!колесо",
        "battle_say": False, "battle_like_n": 0,
        "ai_on": False, "ai_speak": False,
        "ann_tg_on": False, "ann_dc_on": False,
        "remote_on": False, "remote_port": remote_port, "vc_port": MOCK_VC_PORT, "vc_autostart": False,
        # своя папка голосовой программы: иначе на Windows программа читала бы журнал настоящей (%LOCALAPPDATA%)
        "vc_dir": os.path.join(dst, "voice-changer"),
    }
    with open(os.path.join(dst, "media", "мой эдит.mp4"), "wb") as f:
        f.write(b"\x00" * 64)
    with open(os.path.join(dst, "media", "музыка.flac"), "wb") as f:
        f.write(b"fLaC" + b"\x00" * 64)
    with open(os.path.join(dst, "gift_names_ru.json"), "w", encoding="utf-8") as f:
        json.dump({"111": "Старый подарок"}, f, ensure_ascii=False)   # свой файл стримера; «Кулон дружбы» — из встроенного списка
    with open(os.path.join(dst, "profiles.json"), "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False)
    with open(os.path.join(dst, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)
    # сохранённый отчёт прошлого эфира — для страницы итогов
    sys.path.insert(0, dst)
    import streamstats
    s = streamstats.StreamStats(dst, lambda *a: None)
    s.on_connect("smoke_nick")
    s.viewers(57)
    s.gift("Аня", "Rose", 2, 10, "роза")
    s.gift("Kirill", "Galaxy", 1, 1000, "")
    s.like("Аня", 300)
    s.comment("Аня")
    s.follow()
    rep = s.end("тест")
    sys.path.remove(dst)
    return rep["id"] if rep else ""


# ── проверки ────────────────────────────────────────────────────────────────────
def run_checks(api, copy_dir, report_id, remote_port, with_remote):
    src = open(os.path.join(copy_dir, "app.py"), encoding="utf-8").read()
    want = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src).group(1)

    print("\n• Версия и страницы")
    v = api.get("/api/version")
    check("версия из /api/version совпадает с app.py", v.get("version") == want, f"{v.get('version')} ≠ {want}")
    log = v.get("changelog") or []
    check("в changelog.json есть запись этой версии", any(e.get("version") == want for e in log))
    st, html = api.req("/", raw=True)
    check("главное окно открывается", st == 200 and "interactive.js" in html and "live.js" in html, f"код {st}")
    for p in ("/web/overlays/battle.html", "/web/overlays/wheel.html", "/web/overlays/cohost.html",
              "/web/overlays/top.html", "/web/report.html", "/web/remote.html",
              "/web/live.js", "/web/interactive.js", "/web/editor.js"):
        st, _ = api.req(p, raw=True)
        check(f"файл {p} отдаётся", st == 200, f"код {st}")

    cat = api.get("/api/gift_catalog")
    check("библиотека подарков полная сразу (встроенный список)", len(cat.get("gifts", [])) >= 700,
          f"подарков: {len(cat.get('gifts', []))}")

    print("\n• Сохранность данных")
    # 1) два окна: сохраняет только самое новое
    api.post("/api/window/hello", {"id": "winA"}, headers={"X-Taky-Win": "winA"})
    good = api.get("/api/state")["profiles"]
    stc, r = api.req("/api/profiles", {"profiles": good}, headers={"X-Taky-Win": "winA"})
    check("главное окно сохраняет вкладки", stc == 200 and r.get("ok") is True, f"{stc} {r}")
    api.post("/api/window/hello", {"id": "winB"}, headers={"X-Taky-Win": "winB"})
    stc, r = api.req("/api/profiles", {"profiles": {"Старьё": {"gifts": []}}}, headers={"X-Taky-Win": "winA"})
    check("устаревшее окно не может затереть вкладки (409)", stc == 409 and r.get("stale_window") is True
          and list(api.get("/api/state")["profiles"]) == list(good), f"{stc} {r}")
    stc, r = api.req("/api/config", {"tiktok_username": "затёрли"}, headers={"X-Taky-Win": "winA"})
    check("устаревшее окно не может затереть настройки",
          stc == 409 and api.get("/api/state")["config"].get("tiktok_username") == "smoke_nick", f"{stc}")
    check("программа сообщает окнам, какое из них главное", api.get("/api/state").get("editor_win") == "winB")
    api.post("/api/window/hello", {"id": ""})
    # 2) мусор вместо вкладок не принимается
    stc, r = api.req("/api/profiles", {"profiles": ["не", "то"]})
    stc2, r2 = api.req("/api/profiles", {"profiles": {"Тест": "строка"}})
    check("мусор вместо вкладок не сохраняется", stc == 400 and stc2 == 400
          and list(api.get("/api/state")["profiles"]) == list(good), f"{stc} {stc2}")
    # 3) резервные копии
    bk = api.get("/api/backups").get("items", [])
    check("при запуске сделана резервная копия", len(bk) >= 1 and bk[0].get("tabs") == 1, str(bk)[:200])
    made = api.post("/api/backups/make")
    api.post("/api/profiles", {"profiles": {"Сломано": {"gifts": []}}})
    r = api.post("/api/backups/restore", {"id": made.get("id")})
    check("копия возвращает вкладки", r.get("ok") and list(api.get("/api/state")["profiles"]) == list(good), str(r))
    r = api.post("/api/backups/restore", {"id": "../../etc"})
    check("чужой путь вместо копии не принимается", r.get("ok") is False)
    # 4) повреждённый файл не затирается пустым, а поднимается из копии
    sys.path.insert(0, copy_dir)
    import safeio
    import tempfile as _tf
    d = _tf.mkdtemp(prefix="taky_safe_")
    safeio.write_json(os.path.join(d, "profiles.json"), {"Моя": {"gifts": [{"name": "Rose"}]}})
    safeio.write_json(os.path.join(d, "config.json"), {"a": 1})
    sn = safeio.Snapshots(d)
    check("копия создаётся и не дублируется без изменений", bool(sn.make("запуск")) and sn.make("запуск") == "")
    with open(os.path.join(d, "profiles.json"), "w", encoding="utf-8") as f:
        f.write('{"Моя": {"gifts": [{"na')                                  # оборванная запись
    notes = []
    got = safeio.load_json_safe(os.path.join(d, "profiles.json"), sn, dict, notes)
    check("оборванный profiles.json восстановлен из копии, обрывок отложен",
          got == {"Моя": {"gifts": [{"name": "Rose"}]}} and any(".broken-" in f for f in os.listdir(d)) and notes, str(notes))
    check("после восстановления файл на диске снова целый",
          safeio.read_json(os.path.join(d, "profiles.json")) == got)
    sys.path.remove(copy_dir)
    shutil.rmtree(d, ignore_errors=True)
    # 5) загрузка медиа
    def upload(name, data):
        bnd = "----tk" + str(time.time()).replace(".", "")
        body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + f"\r\n--{bnd}--\r\n".encode()
        rq = urllib.request.Request(api.base + "/api/media_upload", data=body, method="POST",
                                    headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
        return json.loads(urllib.request.urlopen(rq, timeout=30).read())
    r1 = upload("трек.mp3", b"AAAA" * 100)
    r2 = upload("трек.mp3", b"BBBB" * 100)
    r3 = upload("трек.mp3", b"AAAA" * 100)
    a_ok = open(os.path.join(copy_dir, "media", "трек.mp3"), "rb").read() == b"AAAA" * 100
    check("другой файл с тем же именем не затирает старый (кладётся рядом)",
          r1.get("name") == "трек.mp3" and r2.get("name") == "трек (2).mp3" and r3.get("name") == "трек.mp3" and a_ok,
          f"{r1} {r2} {r3}")
    r = upload("вирус.html", b"<script>alert(1)</script>")
    check("неподдерживаемый тип файла — понятный отказ", r.get("ok") is False and "не поддерживается" in r.get("error", "")
          and not os.path.exists(os.path.join(copy_dir, "media", "вирус.html")), str(r))
    check("после загрузок не осталось временных файлов",
          not [f for f in os.listdir(os.path.join(copy_dir, "media")) if f.startswith(".tmp_")])

    print("\n• Подарки по названиям")
    api.sim(kind="gift", name="Friendship Necklace", gift_id="9947", count=1, user="g1", diamonds=1)
    check("«Friendship Necklace» из эфира запускает карточку «Кулон дружбы»",
          wait_until(lambda: api.log_has("ПОДАРОК", r"«Friendship Necklace».*→ карточка «Кулон дружбы»"), 5))
    api.sim(kind="gift", name="Doughnut", gift_id="5879", count=1, user="g2", diamonds=30)
    check("карточка из библиотеки по-английски срабатывает по названию",
          wait_until(lambda: api.log_has("ПОДАРОК", r"«Doughnut».*→ карточка$"), 5))
    api.sim(kind="gift", name="Doughnut", gift_id="77777", count=1, user="g3", diamonds=30)
    check("тот же подарок с новым ID — всё равно срабатывает",
          wait_until(lambda: api.log_has("ПОДАРОК", r"«Doughnut».*\[ID: 77777\]  → карточка$"), 5))
    api.sim(kind="gift", name="Mystery Box", gift_id="424242", count=1, user="g4", diamonds=5)
    check("подарок без карточки — подсказка про непонятное русское название",
          wait_until(lambda: api.log_has("ПОДАРКИ", r"«Mystery Box».*«Загадочный подарок».*📚 Выбрать"), 5))

    print("\n• Медиа: эдиты и музыка")
    st_ = api.get("/api/state")
    lion = [g for g in (st_.get("profiles", {}).get("Тест", {}).get("gifts") or []) if g.get("name") == "Lion"]
    check("эдит, который стал .mp4, вернулся в карточку подарка (было «файл не найден»)",
          bool(lion) and lion[0].get("media_file") == "мой эдит.mp4", str(lion)[:200])
    ml = api.get("/api/media_list")
    check("музыка .flac видна в списке звуков",
          any(f["name"] == "музыка.flac" and f["kind"] == "sound" for f in ml.get("files", [])), str(ml.get("files"))[:200])
    check("карточка со звуком не потеряла музыку", bool(lion) and lion[0].get("sound_file") == "музыка.flac")

    print("\n• Защита от чужих сайтов")
    st, _ = api.req("/api/state", headers={"Host": "evil.example.com"}, raw=True)
    check("чужой Host (DNS rebinding) → 403", st == 403, f"код {st}")
    st, _ = api.req("/api/config", {"x": 1}, headers={"Origin": "http://evil.example.com"}, raw=True)
    check("POST с чужого Origin → 403", st == 403, f"код {st}")
    st, _ = api.req("/api/state", headers={"Sec-Fetch-Site": "cross-site"}, raw=True)
    check("GET /api с чужого сайта без Referer → 403", st == 403, f"код {st}")
    st, _ = api.req("/api/state", headers={"Sec-Fetch-Site": "cross-site",
                                            "Referer": "http://localhost:8765/web/overlays/top.html"}, raw=True)
    check("GET /api из своего оверлея (localhost ↔ 127.0.0.1) пускает", st == 200, f"код {st}")
    old_tok = api.get("/api/state")["config"].get("remote_token", "")
    api.cfg(remote_token="hacked_by_save", remote_on=True)
    c = api.get("/api/state")["config"]
    check("общее сохранение настроек не меняет ключ и вкл/выкл пульта",
          c.get("remote_token") != "hacked_by_save" and not c.get("remote_on"))

    print("\n• Очки зрителей")
    api.sim(kind="gift", name="Heart Me", gift_id="7934", count=2, user="viewer1", diamonds=5)
    b1 = wait_until(lambda: api.balance("viewer1"), 5)
    check("подарок 2×5 монет → 100 очков (10 за монету)", b1 == 100, f"баланс {b1}")
    api.sim(kind="follow", user="viewer1")
    b2 = wait_until(lambda: api.balance("viewer1") if api.balance("viewer1") != 100 else 0, 5)
    check("фоллов → +50 очков", b2 == 150, f"баланс {b2}")
    api.sim(kind="follow", user="viewer1")
    time.sleep(0.5)
    check("повторный фоллов того же зрителя очков не даёт", api.balance("viewer1") == 150,
          f"баланс {api.balance('viewer1')}")
    n0 = len(api.log())
    api.sim(kind="chat", user="viewer1", text="!очки")
    check("!очки отвечает балансом", wait_until(lambda: api.log_has("ОЧКИ", r"viewer1: 150", n0), 5))
    od = api.get("/api/overlay?since=0")
    check("оверлей получает топ по очкам", any(r.get("user") == "viewer1" for r in od.get("top_points", [])),
          str(od.get("top_points"))[:120])
    api.post("/api/points/set", {"key": "viewer1", "amount": 150})
    check("ручная правка баланса", api.balance("viewer1") == 150)

    print("\n• Чат-команда за очки (💎 Цена)")
    n0 = len(api.log())
    api.sim(kind="chat", user="viewer1", text="!крипер")
    ok = wait_until(lambda: api.log_has("ЧАТ-КОМАНДА", r"viewer1 → !крипер", n0), 5)
    check("команда сработала у зрителя с очками", ok)
    check("списано 30 очков", api.balance("viewer1") == 120, f"баланс {api.balance('viewer1')}")
    n0 = len(api.log())
    api.sim(kind="chat", user="nopoints", text="!крипер")
    time.sleep(0.8)
    check("без очков команда не срабатывает",
          not api.log_has("ЧАТ-КОМАНДА", r"nopoints", n0) and api.log_has("ОЧКИ", r"nopoints → !крипер: нужно 30", n0))

    print("\n• Битва команд")
    r = api.post("/api/battle/start", {"secs": 10})
    check("битва запускается", r.get("running") is True and r.get("left", 0) >= 8, str(r)[:160])
    api.sim(kind="chat", user="red1", text="!к")
    api.sim(kind="chat", user="blue1", text="!2 погнали")
    api.sim(kind="chat", user="fake", text="!красныеее")
    time.sleep(0.5)
    snap = api.get("/api/battle")
    check("зрители вступают командами (!к, «!2 погнали»), «!красныеее» не считается",
          [t["members"] for t in snap["teams"]] == [1, 1], str([t["members"] for t in snap["teams"]]))
    api.sim(kind="gift", name="Heart Me", gift_id="7934", count=1, user="red1", diamonds=50)
    api.sim(kind="gift", name="Heart Me", gift_id="7934", count=1, user="blue1", diamonds=5)
    api.sim(kind="gift", name="Heart Me", gift_id="7934", count=1, user="newbie", diamonds=1)
    time.sleep(0.5)
    snap = api.get("/api/battle")
    sc = [t["score"] for t in snap["teams"]]
    check("подарки идут в счёт своей команды, новичок — в отстающую", sc == [50, 6], str(sc))
    res = wait_until(lambda: api.get("/api/battle").get("result"), 15)
    check("по таймеру объявлен победитель «Красные», лучший — red1",
          bool(res) and res.get("winner") == 0 and res.get("mvp") == "red1", str(res))
    check("в журнале есть итог битвы", api.log_has("БИТВА", r"Победили «Красные» 50:6"))
    api.post("/api/battle/start", {"secs": 60})
    r = api.post("/api/battle/stop")
    check("«Стоп» останавливает без победителя", r.get("running") is False and not r.get("result"), str(r)[:160])

    print("\n• Колесо фортуны")
    w = api.get("/api/wheel")
    check("колесо по умолчанию — современное, 6 секторов", w.get("style") == "modern" and len(w.get("sectors", [])) == 6,
          str(w)[:160])
    n0 = len(api.log())
    r = api.post("/api/wheel/spin")
    check("кнопка «Крутить» ставит вращение", r.get("ok") is True, str(r))
    spin = wait_until(lambda: api.get("/api/wheel").get("spin"), 5)
    check("оверлей видит вращение (сектор, длительность)", bool(spin) and spin.get("secs") == 3, str(spin))
    check("через 3 сек выпал сектор", wait_until(lambda: api.log_has("КОЛЕСО", r"выпало «", n0), 8))
    n0 = len(api.log())
    api.sim(kind="gift", name="Rose", gift_id="5655", count=1, user="roseguy", diamonds=1)
    check("подарок «Rose» крутит колесо", wait_until(lambda: api.log_has("КОЛЕСО", r"roseguy крутит", n0), 12))
    bal = api.balance("viewer1")
    n0 = len(api.log())
    api.sim(kind="chat", user="viewer1", text="!колесо")
    time.sleep(0.6)
    check("!колесо за 40 очков списывает очки", api.balance("viewer1") == bal - 40 and
          api.log_has("ОЧКИ", r"viewer1 потратил 40 на колесо", n0), f"{bal} → {api.balance('viewer1')}")
    api.cfg(wheel_style="gold")
    check("вид колеса переключается на золотой", api.get("/api/wheel").get("style") == "gold")
    api.cfg(wheel_style="modern")
    saved = api.get("/api/state")["config"].get("wheel_sectors")
    api.cfg(wheel_sectors=[])
    r = api.post("/api/wheel/spin")
    check("без секторов «Крутить» отвечает понятной ошибкой", r.get("ok") is False and "сектор" in r.get("error", ""), str(r))
    api.cfg(wheel_sectors=saved)

    print("\n• Итоги эфира")
    cur = api.get("/api/stats/current")
    check("вне эфира текущего отчёта нет", cur.get("report") is None and "money_rate" in cur)
    items = api.get("/api/stats/list").get("items", [])
    check("сохранённый эфир есть в списке", any(i["id"] == report_id for i in items), str(items)[:160])
    rep = api.get("/api/stats/get?id=" + report_id)
    rep = rep.get("report", rep) if isinstance(rep, dict) else {}
    check("отчёт открывается: 1010 монет, 300 лайков, 57 зрителей",
          rep.get("totals", {}).get("coins") == 1010 and rep.get("totals", {}).get("likes") == 300
          and rep.get("viewers_max") == 57, str(rep.get("totals")))
    st, txt = api.req("/api/stats/text?id=" + report_id, raw=True)
    check("итоги скачиваются текстом (монеты, ≈ деньги, топ)",
          st == 200 and "1 010" in txt and "≈ $5,05" in txt and "Kirill" in txt, txt[:200])
    st, _ = api.req("/api/stats/text?id=../../config", raw=True)
    check("чужой путь вместо id → 404", st == 404, f"код {st}")
    st, _ = api.req("/web/report.html?id=" + report_id, raw=True)
    check("страница итогов открывается", st == 200)
    r = api.post("/api/announce/summary", {"id": report_id})
    check("«Итоги в чаты» без Telegram/Discord — понятная ошибка", r.get("ok") is False and "Telegram" in r.get("error", ""),
          str(r))
    r = api.post("/api/announce/test", {"ch": "tg"})
    check("проверка Telegram без токена не падает", r.get("ok") is False and r.get("error"), str(r))

    print("\n• Пульт с телефона")
    if not with_remote:
        print("  (пропущено: --no-remote)")
    else:
        stt = api.post("/api/remote/set", {"on": True})
        check("пульт включается", stt.get("running") is True, str(stt.get("error")))
        urls = stt.get("urls") or []
        check("есть ссылка и QR-код", bool(urls) and "<svg" in stt.get("qr", "") and "viewBox" in stt.get("qr", ""),
              str(urls))
        tok = urls[0].rstrip("/").rsplit("/", 1)[-1] if urls else "none"
        rb = f"http://127.0.0.1:{remote_port}"
        st, page = api.req(f"/r/{tok}/", base=rb, raw=True)
        check("страница пульта открывается по ссылке", st == 200 and "<html" in page.lower(), f"код {st}")
        st, _ = api.req("/r/wrongtoken123456/", base=rb, raw=True)
        check("неверный ключ в ссылке → 404", st == 404, f"код {st}")
        st, _ = api.req("/api/state", base=rb, raw=True)
        check("основное API через порт пульта недоступно", st == 404, f"код {st}")
        rs = api.get(f"/r/{tok}/api/state", base=rb)
        check("пульт видит кнопки эфирной вкладки", rs.get("buttons") == ["💥 Тест-кнопка"], str(rs)[:160])
        api.post(f"/r/{tok}/api/battle_start", {"secs": 30}, base=rb)
        check("битва запускается с пульта", api.get("/api/battle").get("running") is True)
        api.post(f"/r/{tok}/api/battle_stop", base=rb)
        r = api.post(f"/r/{tok}/api/wheel_spin", base=rb)
        check("колесо крутится с пульта", r.get("ok") is True, str(r))
        n0 = len(api.log())
        api.post(f"/r/{tok}/api/panel_fire", {"index": 0}, base=rb)
        check("кнопка панели нажимается с пульта", wait_until(lambda: api.log_has("ПАНЕЛЬ", r"Тест-кнопка", n0), 5))
        api.post("/api/remote/reset")
        st, _ = api.req(f"/r/{tok}/", base=rb, raw=True)
        check("после «Новая ссылка» старая не работает", st == 404, f"код {st}")
        stt = api.post("/api/remote/set", {"on": False})
        check("пульт выключается", stt.get("running") is False)

    print("\n• ИИ-соведущий (поддельный ИИ на этом ПК)")
    mock, mport = start_mock_ai()
    murl = f"http://127.0.0.1:{mport}/v1"
    pr = api.get("/api/ai/presets")
    check("список сервисов ИИ (DeepSeek, OpenRouter, Ollama)",
          all(k in json.dumps(pr) for k in ("deepseek", "openrouter", "ollama")))
    ai = {"ai_provider": "custom", "ai_url": murl, "ai_key": "good", "ai_model": "mock-1"}
    r = api.post("/api/ai/test", ai)
    check("🧪 Проверить: ответ получен", r.get("ok") is True and "Таки" in r.get("text", ""), str(r))
    check("в ИИ ушли правила и персонаж", bool(MOCK_LOG) and "соведущий" in MOCK_LOG[-1]["messages"][0]["content"])
    r = api.post("/api/ai/test", dict(ai, ai_key="bad"))
    check("неверный ключ → понятная ошибка", r.get("ok") is False and "ключ" in r.get("error", ""), str(r))
    r = api.post("/api/ai/test", dict(ai, ai_provider="ollama", ai_url=f"http://127.0.0.1:{free_port()}/v1", ai_key=""))
    check("Ollama не запущена → понятная ошибка", r.get("ok") is False and "Ollama" in r.get("error", ""), str(r))
    r = api.post("/api/ai/test", dict(ai, ai_model=""))
    check("пустая модель → «впиши модель»", r.get("ok") is False and "модель" in r.get("error", ""), str(r))

    api.cfg(ai_on=True, ai_cooldown=0, ai_user_cd=30, ai_gift_min=10, **ai)
    n_mock = len(MOCK_LOG)
    n0 = len(api.log())
    api.sim(kind="chat", user="fan1", text="таки, привет!")
    check("обращение «таки, …» → соведущий отвечает",
          wait_until(lambda: api.log_has("ИИ", r"🤖 Таки: ", n0), 10))
    n1 = len(MOCK_LOG)
    api.sim(kind="chat", user="fan2", text="притаким был стрим")
    api.sim(kind="chat", user="fan3", text="привет всем")
    time.sleep(1.5)
    check("«притаким» и обычные сообщения ИИ не зовут", len(MOCK_LOG) == n1, f"{n1} → {len(MOCK_LOG)}")
    n0 = len(api.log())
    api.sim(kind="chat", user="fan1", text="таки ещё раз")
    time.sleep(1.5)
    check("кулдаун на одного зрителя (30 сек) работает", not api.log_has("ИИ", r"fan1 обратился", n0))
    n0 = len(api.log())
    api.sim(kind="gift", name="Galaxy", gift_id="11046", count=1, user="Аня", diamonds=1000)
    got = wait_until(lambda: [e for e in api.log()[n0:] if e["kind"] == "ИИ" and "спасибо" in e["text"]], 10)
    check("большой подарок → благодарность, без <think> и звёздочек",
          bool(got) and "<think>" not in got[0]["text"] and "**" not in got[0]["text"], str(got)[:200])
    # подарок ловится по названию: TikTok сменил ID розы — карточка «роза» всё равно срабатывает,
    # а чужой подарок со старым ID розы её не трогает
    time.sleep(1.5)
    n1 = len(MOCK_LOG)
    api.sim(kind="gift", name="Rose", gift_id="99999", count=1, user="newid", diamonds=50)
    ok = wait_until(lambda: len(MOCK_LOG) > n1, 10)
    check("подарок с новым ID находит карточку по названию",
          bool(ok) and "«роза»" in MOCK_LOG[-1]["messages"][-1]["content"].split("Сейчас:")[-1])
    time.sleep(1.5)
    n1 = len(MOCK_LOG)
    api.sim(kind="gift", name="Lion", gift_id="5655", count=1, user="oldid", diamonds=50)
    ok = wait_until(lambda: len(MOCK_LOG) > n1, 10)
    check("чужой подарок со старым ID розы карточку «роза» не запускает",
          bool(ok) and "«роза»" not in MOCK_LOG[-1]["messages"][-1]["content"].split("Сейчас:")[-1])
    time.sleep(1.5)
    n1 = len(MOCK_LOG)
    api.sim(kind="gift", name="Rose", gift_id="5655", count=1, user="small", diamonds=1)
    time.sleep(1.5)
    check("мелкий подарок (меньше порога) ИИ не зовёт", len(MOCK_LOG) == n1)
    od = api.get("/api/overlay?since=0")
    check("реплики идут в оверлей соведущего", any(e.get("type") == "ai" for e in od.get("new_events", [])))

    # вопросы в чате, Телеграм/Дискорд, болтовня с чатом
    api.cfg(ai_tg="@taky_tg", ai_dc="discord.gg/takylive", ai_facts="Стримы каждый день в 19:00.",
            ai_on_questions=True, ai_chatty=0)
    time.sleep(1)
    n1 = len(MOCK_LOG)
    api.sim(kind="chat", user="q1", text="есть тг?")
    ok = wait_until(lambda: len(MOCK_LOG) > n1, 10)
    sys_prompt = MOCK_LOG[-1]["messages"][0]["content"] if ok else ""
    check("вопрос «есть тг?» без обращения → соведущий отвечает", bool(ok))
    check("ИИ знает Телеграм, Дискорд и факты о стриме",
          "@taky_tg" in sys_prompt and "discord.gg/takylive" in sys_prompt and "19:00" in sys_prompt, sys_prompt[-300:])
    time.sleep(1.5)
    n1 = len(MOCK_LOG)
    api.sim(kind="chat", user="q2", text="всем привет")
    api.sim(kind="chat", user="q3", text="!очки")
    time.sleep(2)
    check("обычные сообщения и !команды не считаются вопросами", len(MOCK_LOG) == n1, f"{n1} → {len(MOCK_LOG)}")
    api.cfg(ai_on_questions=False)
    api.sim(kind="chat", user="q4", text="что за игра?")
    time.sleep(2)
    check("«Отвечать на вопросы» выключено — молчит", len(MOCK_LOG) == n1)
    api.cfg(ai_chatty=10)
    n1 = len(MOCK_LOG)
    api.sim(kind="chat", user="chat1", text="я сегодня впервые на стриме")
    check("«Болтать с чатом» — сам отвечает кому-то из чата",
          wait_until(lambda: len(MOCK_LOG) > n1 and "впервые" in MOCK_LOG[-1]["messages"][-1]["content"], 15))
    api.cfg(ai_chatty=0, ai_on_questions=True)

    # своя картинка соведущего
    od = api.get("/api/overlay?since=0")
    check("оверлей знает имя соведущего и картинку по умолчанию",
          od.get("ai", {}).get("name") == "Таки" and od["ai"].get("avatar") == "", str(od.get("ai")))
    api.cfg(ai_avatar="ai_avatar_test.png", ai_avatar_shape="free")
    od = api.get("/api/overlay?since=0")
    check("своя картинка соведущего уходит в оверлей",
          od["ai"].get("avatar") == "/media/ai_avatar_test.png" and od["ai"].get("shape") == "free", str(od.get("ai")))
    api.cfg(ai_avatar="", ai_avatar_shape="circle")
    api.cfg(ai_on=False)
    mock.shutdown()

    print("\n• 🎙 ИИ-голос (поддельная голосовая программа)")
    st = api.get("/api/vc/status")
    check("TakyLive видит голосовую программу и её голоса",
          st.get("running") is True and [v["name"] for v in st.get("info", {}).get("slots", [])] == ["Девушка", "Демон"],
          str(st)[:200])
    check("VB-CABLE найден среди устройств", st.get("cable") is True)
    r = api.post("/api/vc/audio", {"vc_mic_name": "Микрофон (USB Mic)", "vc_out_name": "", "vc_monitor_name": ""})
    S = MOCK_VC["settings"]
    check("«Включить ИИ-голос»: микрофон → CABLE Input, видеокарта, rmvpe, свой голос по умолчанию",
          r.get("ok") and S.get("serverInputDeviceId") == 1 and S.get("serverOutputDeviceId") == 7 and S.get("gpu") == 0
          and S.get("f0Detector") == "rmvpe_onnx" and S.get("serverAudioStated") == 1 and S.get("passThrough") is True
          and str(S.get("enableServerAudio")) == "1", f"{r} {S}")
    check("задержка: вместо 0,5 с по умолчанию — ≈130 мс (Chunk 48)",
          S.get("serverReadChunkSize") == 48 and r.get("latency_ms") == 128, f"{S.get('serverReadChunkSize')} {r}")
    check("выбор микрофона сохранился в настройках", api.get("/api/state")["config"].get("vc_mic_name") == "Микрофон (USB Mic)")
    n0 = len(api.log())
    api.sim(kind="chat", user="hater", text="!демон")
    ok = wait_until(lambda: S.get("modelSlotIndex") == 1 and S.get("passThrough") is False, 5)
    check("чат-команда с voice:Демон:3 включает голос «Демон»", bool(ok), str(S))
    od = api.get("/api/overlay?since=0")
    check("оверлей видит «Демон» от hater с отсчётом",
          (od.get("voice") or {}).get("name") == "Демон" and od["voice"].get("user") == "hater", str(od.get("voice")))
    back = wait_until(lambda: S.get("passThrough") is True, 8)
    check("через 3 сек вернулся обычный голос", bool(back) and not api.get("/api/overlay?since=0").get("voice"))
    check("в журнале видно, кто и какой голос включил", api.log_has("ГОЛОС", r"hater: голос «Демон» на 3 сек"))
    r = api.post("/api/vc/voice", {"name": "нет такого", "secs": 5})
    check("несуществующий голос — понятная ошибка", r.get("ok") is False and "нет голоса" in r.get("error", ""), str(r))
    api.post("/api/vc/normal", {"name": "Девушка"})
    check("«Обычный голос» = ИИ-голос «Девушка»", S.get("modelSlotIndex") == 0 and S.get("passThrough") is False, str(S))
    api.post("/api/vc/normal", {"name": ""})
    check("«Обычный голос» = мой голос (без ИИ)", S.get("passThrough") is True)
    # загрузка своего голоса
    import uuid
    bnd = "----taky" + uuid.uuid4().hex
    parts = []
    for name, fn, data in (("slot", None, b"auto"), ("model", "Робот.pth", b"PTH" * 1000), ("index", "Робот.index", b"IDX" * 500)):
        disp = f'form-data; name="{name}"' + (f'; filename="{fn}"' if fn else "")
        parts.append(f"--{bnd}\r\nContent-Disposition: {disp}\r\n\r\n".encode("utf-8") + data + b"\r\n")
    body = b"".join(parts) + f"--{bnd}--\r\n".encode()
    req = urllib.request.Request(api.base + "/api/vc/upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    ld = MOCK_VC["loaded"][-1] if MOCK_VC["loaded"] else {}
    check("свой голос (.pth + .index) загружается в свободный слот 2",
          r.get("ok") and r.get("slot") == 2 and [f["kind"] for f in ld.get("files", [])] == ["rvcModel", "rvcIndex"]
          and len(MOCK_VC["uploads"]) == 2, f"{r} {ld}")
    st = api.get("/api/vc/status")
    check("новый голос появился в списке", "Робот" in [v["name"] for v in st.get("info", {}).get("slots", [])])
    st, _ = api.req("/api/vc/upload", None, raw=True)
    check("GET на загрузку не принимается", st in (404, 405), f"код {st}")
    # ⭐ рекомендуемые голоса
    pr = api.get("/api/vc/presets").get("voices", [])
    check("⭐ рекомендуемые приходят с GitHub, кривые записи отброшены",
          [v["name"] for v in pr] == ["Робот", "Авто"] and pr[0]["license"] == "mit" and pr[1]["auto"] is True, str(pr)[:300])
    # библиотека голосов (Hugging Face)
    r = api.get("/api/vc/hub/search?q=" + urllib.request.quote("robot"))
    check("поиск в библиотеке голосов находит модель", r.get("ok") and [m["id"] for m in r.get("items", [])] == ["tester/robot-rvc"],
          str(r)[:200])
    r = api.get("/api/vc/hub/search?q=" + urllib.request.quote("голос робота"))
    check("русский запрос «голос робота» ищет robot и находит модель",
          r.get("ok") and r.get("terms") == ["robot"] and [m["id"] for m in r.get("items", [])] == ["tester/robot-rvc"], str(r)[:200])
    r = api.get("/api/vc/hub/search?q=" + urllib.request.quote("абракадабра"))
    check("непонятное русское слово — просьба написать по-английски", r.get("ok") is False and "по-английски" in r.get("error", ""),
          str(r))
    r = api.get("/api/vc/hub/search?q=&sort=downloads")
    check("каталог без запроса — сразу все голоса, популярные сверху",
          r.get("ok") and r.get("browse") and [m["id"] for m in r.get("items", [])] == ["tester/robot-rvc", "tester/pack-rvc"],
          str(r)[:200])
    r = api.get("/api/vc/hub/search?q=x")
    check("слишком короткий запрос — подсказка", r.get("ok") is False and "впиши" in r.get("error", ""), str(r))
    f = api.get("/api/vc/hub/files?repo=tester/robot-rvc")
    c = f.get("candidates", [])
    check("в модели виден голос robot (.pth + .index), файлы обучения G_ скрыты, лицензия mit",
          f.get("license") == "mit" and [x["label"] for x in c] == ["robot"] and c[0]["index"] == "added_IVF256_robot.index",
          str(f)[:300])
    r = api.get("/api/vc/hub/files?repo=../../etc")
    check("чужой путь вместо модели не принимается", r.get("ok") is False)
    n_up = len(MOCK_VC["loaded"])
    r = api.post("/api/vc/hub/install", {"repo": "tester/robot-rvc", "model": c[0]["model"], "index": c[0]["index"],
                                         "name": "Робот 2000"})
    done = wait_until(lambda: len(MOCK_VC["loaded"]) > n_up and not api.get("/api/vc/status")["hub"]["running"], 15)
    ld = MOCK_VC["loaded"][-1] if MOCK_VC["loaded"] else {}
    check("«Поставить» качает .pth + .index и загружает голос под своим именем",
          bool(done) and [x["name"] for x in ld.get("files", [])] == ["Робот_2000.pth", "added_IVF256_robot.index"],
          f"{ld} {api.get('/api/vc/status')['hub']}")
    r = api.post("/api/vc/hub/install", {"repo": "tester/robot-rvc", "model": "../../secret.pth"})
    time.sleep(1)
    check("файл не из модели — отказ", "нет файла" in api.get("/api/vc/status")["hub"].get("error", ""),
          str(api.get("/api/vc/status")["hub"]))
    f = api.get("/api/vc/hub/files?repo=tester/pack-rvc")
    c = f.get("candidates", [])
    n_up = len(MOCK_VC["loaded"])
    api.post("/api/vc/hub/install", {"repo": "tester/pack-rvc", "zip": c[0]["zip"] if c else "", "name": "Демон"})
    done = wait_until(lambda: len(MOCK_VC["loaded"]) > n_up and not api.get("/api/vc/status")["hub"]["running"], 15)
    ld = MOCK_VC["loaded"][-1] if MOCK_VC["loaded"] else {}
    check("голос из .zip-архива распаковывается и ставится",
          bool(done) and [x["name"] for x in ld.get("files", [])] == ["Демон.pth", "added_demon.index"], str(ld))

    api.post("/api/vc/hub/install", {"repo": "tester/pack-rvc", "auto": True, "name": "Авто"})
    n_up = len(MOCK_VC["loaded"])
    done = wait_until(lambda: len(MOCK_VC["loaded"]) > n_up and not api.get("/api/vc/status")["hub"]["running"], 15)
    ld = MOCK_VC["loaded"][-1] if MOCK_VC["loaded"] else {}
    check("⭐ рекомендуемый голос без указания файла ставится сам (первый голос модели)",
          bool(done) and [x["name"] for x in ld.get("files", [])] == ["Авто.pth", "added_demon.index"], str(ld))
    r = api.get("/api/vc/hub/search?q=alien")
    check("голос без тега rvc находится («alien rvc»), не-голоса отброшены",
          r.get("ok") and [m["id"] for m in r.get("items", [])] == ["tester/alien-voice-RVC"], str(r)[:200])

    # высота голоса
    api.post("/api/vc/voice", {"name": "Девушка", "secs": 5})
    check("высота голоса по умолчанию — из модели (+12 у «Девушки»)", S.get("tran") == 12 and S.get("modelSlotIndex") == 0, str(S))
    r = api.post("/api/vc/tune", {"name": "Демон", "tune": -12})
    api.post("/api/vc/voice", {"name": "Демон", "secs": 5})
    check("своя высота (−12 у «Демона») применяется и сохраняется",
          r.get("ok") and S.get("tran") == -12 and api.get("/api/state")["config"].get("vc_tune") == {"Демон": -12}, f"{r} {S}")
    api.post("/api/vc/tune", {"name": "Демон", "tune": 5})
    check("высота меняется сразу у звучащего голоса", S.get("tran") == 5, str(S))
    stv = api.get("/api/vc/status")
    check("окно видит высоту каждого голоса", stv["info"]["tunes"].get("Демон") == 5 and stv["info"]["tunes"].get("Девушка") == 12,
          str(stv["info"].get("tunes")))
    check("пока звук включён, список устройств в окне не пустеет",
          len(stv["info"]["inputs"]) == 1 and len(stv["info"]["outputs"]) == 2, str(stv["info"]["inputs"]))
    api.post("/api/vc/voice", {"off": True})
    r = api.post("/api/vc/tune", {"name": "Демон", "tune": "abc"})
    check("кривая высота не принимается", r.get("ok") is False)

    # наушники подключили — Windows сменила номера устройств
    aud = {"vc_mic_name": "Микрофон (USB Mic)", "vc_out_name": "", "vc_monitor_name": ""}
    MOCK_VC["stale"] = (list(MOCK_VC["ins"]), list(MOCK_VC["outs"]))
    MOCK_VC["ins"] = [(29, "Микрофон (USB Mic)")]
    MOCK_VC["outs"] = [(22, "Наушники (Buds)"), (25, "Наушники (Realtek)"), (24, "CABLE Input (VB-Audio Virtual Cable)")]
    r = api.post("/api/vc/audio", aud)
    check("номера устройств сменились (подключили наушники) — ИИ-голос сам находит их по имени",
          r.get("ok") and S.get("serverInputDeviceId") == 29 and S.get("serverOutputDeviceId") == 24
          and S.get("serverAudioStated") == 1, f"{r} {S}")
    S["serverAudioStated"] = 0                                    # голосовую программу перезапускали — звук выключен
    api.post("/api/vc/voice", {"name": "Демон", "secs": 2})
    check("звук был выключен — голос из подарка включает его сам",
          S.get("serverAudioStated") == 1 and api.log_has("ГОЛОС", "был выключен — включаю заново"), str(S))
    api.post("/api/vc/voice", {"off": True})
    MOCK_VC["broken"] = True
    r = api.post("/api/vc/audio", aud)
    check("устройство не открылось — честная ошибка вместо «включён»",
          r.get("ok") is False and "не смогла открыть" in r.get("error", ""), str(r))
    MOCK_VC["broken"] = False
    keep_ins, MOCK_VC["ins"] = MOCK_VC["ins"], []
    r = api.post("/api/vc/audio", aud)
    check("микрофон отключён — понятная ошибка", r.get("ok") is False and "не вижу микрофон" in r.get("error", ""), str(r))
    MOCK_VC["ins"] = keep_ins
    r = api.post("/api/vc/audio", aud)
    check("после ошибок ИИ-голос включается снова", r.get("ok") and S.get("serverAudioStated") == 1, str(r))

    r = api.post("/api/vc/audio", dict(aud, vc_chunk=96))
    check("свою задержку можно выбрать (Chunk 96 ≈ 256 мс)", r.get("ok") and S.get("serverReadChunkSize") == 96
          and api.get("/api/state")["config"].get("vc_chunk") == 96, f"{S.get('serverReadChunkSize')} {r}")
    api.post("/api/vc/audio", dict(aud, vc_chunk=0))

    # наушники убрали в футляр: номера те же, ошибок в журнале нет, но звук в голосовой программе молча умер.
    # TakyLive видит, что список устройств Windows изменился, и включает звук заново — голос из подарка не сбивается
    api.post("/api/vc/voice", {"name": "Демон", "secs": 30})
    n_on = sum(1 for k, v in MOCK_VC["log"] if k == "serverAudioStated" and v == "1")
    with open(DEVSIG_FILE, "w", encoding="utf-8") as f:
        f.write("o:Динамики|i:Микрофон")                          # было: + наушники
    again = wait_until(lambda: sum(1 for k, v in MOCK_VC["log"] if k == "serverAudioStated" and v == "1") > n_on, 15)
    check("убрали наушники — ИИ-голос сам включается заново, голос из подарка остаётся",
          bool(again) and api.log_has("ГОЛОС", "Звуковые устройства Windows изменились")
          and wait_until(lambda: S.get("serverAudioStated") == 1 and S.get("modelSlotIndex") == 1 and S.get("passThrough") is False, 5)
          and (api.get("/api/overlay?since=0").get("voice") or {}).get("name") == "Демон", str(S))
    api.post("/api/vc/voice", {"off": True})

    r = api.post("/api/vc/audio", {"off": True})
    check("«Выключить» останавливает ИИ-голос", r.get("ok") and S.get("serverAudioStated") == 0)
    n_on = sum(1 for k, v in MOCK_VC["log"] if k == "serverAudioStated" and v == "1")
    with open(DEVSIG_FILE, "w", encoding="utf-8") as f:
        f.write("o:Динамики|o:Наушники|i:Микрофон")
    time.sleep(9)
    check("ИИ-голос выключен — смена устройств его не включает",
          sum(1 for k, v in MOCK_VC["log"] if k == "serverAudioStated" and v == "1") == n_on and S.get("serverAudioStated") == 0)

    if os.name != "nt":                                           # запуск голосовой программы: подделка-«exe»
        vdir = os.path.join(copy_dir, "voice-changer")
        p2 = free_port()
        with open(os.path.join(vdir, "MMVCServerSIO"), "w", encoding="utf-8") as f:
            f.write(FAKE_VC_EXE.replace("__PORT__", str(p2)))
        os.chmod(os.path.join(vdir, "MMVCServerSIO"), 0o755)

        def mode(m):
            with open(os.path.join(vdir, "mode.txt"), "w") as f:
                f.write(m)
            if os.path.exists(os.path.join(vdir, "runs.txt")):
                os.remove(os.path.join(vdir, "runs.txt"))
        api.cfg(vc_port=p2)
        mode("slow")                                              # дважды не успевает докачать свои файлы
        r = api.post("/api/vc/start")
        stv = api.get("/api/vc/status")
        check("голосовая программа запускается, окно видит «запускается»", r.get("ok") and stv.get("starting") is True, str(stv)[:200])
        up2 = wait_until(lambda: api.get("/api/vc/status").get("running"), 30, 0.5)
        runs = open(os.path.join(vdir, "runs.txt")).read()
        check("не успела скачать свои файлы — TakyLive сам запускает её снова, пока не докачает",
              bool(up2) and runs == "3" and api.log_has("ГОЛОС", r"докачка продолжится \(попытка 3\)")
              and wait_until(lambda: api.log_has("ГОЛОС", "Голосовая программа запустилась"), 6), f"запусков {runs}")
        api.post("/api/vc/stop")
        check("«Остановить» закрывает голосовую программу", not wait_until(lambda: api.get("/api/vc/status").get("running"), 2, 0.5))
        mode("crash")                                             # падает не из-за интернета
        api.post("/api/vc/start")
        err = wait_until(lambda: (api.get("/api/vc/status").get("start") or {}).get("error"), 10, 0.5) or ""
        check("не запустилась — причина из её журнала видна в окне и в журнале TakyLive",
              "CUDA" in err and open(os.path.join(vdir, "runs.txt")).read() == "1"
              and api.log_has("ОШИБКА", "ИИ-голос: не запустилась.*CUDA"), err)
        api.cfg(vc_port=MOCK_VC_PORT)
    st, _ = api.req("/web/overlays/voice.html", raw=True)
    check("оверлей voice.html отдаётся", st == 200)

    print("\n• Подключение к TikTok (поддельный TikTok)")

    def connected():
        return api.get("/api/state").get("connected")

    def errors(_=0):
        return [e["text"] for e in api.log() if e["kind"] == "ОШИБКА"
                and ("tiktok" in e["text"].lower() or "подключ" in e["text"].lower() or "отключ" in e["text"].lower())]

    def reconnect_ok(nick="fake_ok", timeout=6):
        api.cfg(tiktok_username=nick)
        r = api.post("/api/connect")
        return r.get("ok") is True and bool(wait_until(connected, timeout)), r

    api.sim(kind="gift", name="Test Dragon", gift_id="7777", count=1, user="Аня", diamonds=1)
    check("до подключения «Test Dragon» карточку не находит",
          wait_until(lambda: api.log_has("ПОДАРОК", r"«Test Dragon».*карточки нет"), 5))
    ok, r = reconnect_ok("fake_ok")
    check("подключение к эфиру", ok and api.log_has("СИСТЕМА", "✅ Подключено к @fake_ok"), str(r))
    check("русские названия TikTok отдаёт по ru-RU — программа их получает",
          wait_until(lambda: api.log_has("ПОДАРКИ", r"Русские названия подарков: 3 "), 5),
          str([e["text"] for e in api.log() if e["kind"] == "ПОДАРКИ"][-3:]))
    api.sim(kind="gift", name="Test Dragon", gift_id="7777", count=1, user="Аня", diamonds=1)
    check("после подключения «Test Dragon» запускает карточку «Тестовый дракон»",
          wait_until(lambda: api.log_has("ПОДАРОК", r"«Test Dragon».*→ карточка «Тестовый дракон»"), 5))
    api.sim(kind="gift", name="Friendship Necklace", gift_id="1", count=1, user="Аня", diamonds=10)
    check("TikTok сменил ID подарка — «Кулон дружбы» всё равно срабатывает по названию",
          wait_until(lambda: api.log_has("ПОДАРОК", r"«Friendship Necklace».*ID: 1\].*→ карточка «Кулон дружбы»"), 5),
          str([e["text"] for e in api.log() if e["kind"] == "ПОДАРОК"][-2:]))
    r = api.post("/api/connect")
    check("второе «Подключиться» при живом эфире — «Уже подключено»", r.get("ok") is False and "Уже подключено" in r.get("message", ""), str(r))
    t0 = time.time()
    api.post("/api/disconnect")
    dt = time.time() - t0
    check("«Отключиться» отключает сразу", dt < 3 and not connected()
          and api.log_has("СИСТЕМА", "❌ Отключено от TikTok"), f"{dt:.1f} с")
    ok, r = reconnect_ok("fake_ok")
    check("после «Отключиться» можно подключиться снова", ok, str(r))
    check("переподключение посреди эфира — тот же эфир: итоги не дробятся, «Я в эфире» второй раз не уходит",
          api.log_has("ИТОГИ", "Отключено. Не подключишься снова за 2 мин")
          and wait_until(lambda: api.log_has("ИТОГИ", "Связь вернулась — продолжаю считать тот же эфир"), 3)
          and not api.log_has("ИТОГИ", r"Эфир окончен \(отключился\)"))
    api.post("/api/disconnect")

    api.cfg(tiktok_username="fake_ok")                          # передумал, пока подключается
    api.post("/api/connect")
    api.post("/api/disconnect")
    ok, r = reconnect_ok("fake_ok")
    check("отмена во время подключения — потом подключается снова", ok, str(r))
    api.post("/api/disconnect")

    ok, r = reconnect_ok("fake_slow")                           # TikTok не отвечает на «пока»
    t0 = time.time()
    api.post("/api/disconnect")
    dt = time.time() - t0
    ok2, r2 = reconnect_ok("fake_ok")
    check("TikTok не отвечает на отключение — программа отключается сама (до 10 с) и подключается снова",
          ok and dt < 10 and ok2, f"{dt:.1f} с, {r2}")
    api.post("/api/disconnect")
    check("отключения и отмены не пишут в журнал ошибок", not errors(0), str(errors(0))[:300])

    ok, r = reconnect_ok("fake_stuck")                          # поток намертво занят
    time.sleep(2)
    t0 = time.time()
    api.post("/api/disconnect")
    dt = time.time() - t0
    ok2, r2 = reconnect_ok("fake_ok")
    check("зависшее подключение не мешает подключиться заново", ok and dt < 12 and ok2, f"{dt:.1f} с, {r2}")
    api.post("/api/disconnect")

    api.cfg(tiktok_username="fake_drop")
    api.post("/api/connect")
    check("обрыв связи — понятная запись, а не «не удалось подключиться»",
          wait_until(lambda: api.log_has("ОШИБКА", "Связь с TikTok оборвалась"), 6) and not connected())
    ok, r = reconnect_ok("fake_ok")
    check("после обрыва можно подключиться снова", ok, str(r))
    api.post("/api/disconnect")
    api.cfg(tiktok_username="fake_off")
    api.post("/api/connect")
    check("эфир не идёт — «Не удалось подключиться»",
          wait_until(lambda: api.log_has("ОШИБКА", "Не удалось подключиться: .*offline"), 6))
    wait_until(lambda: api.post("/api/connect").get("ok"), 5)
    api.post("/api/disconnect")
    api.cfg(tiktok_username="smoke_nick")

    print("\n• Журнал без ошибок программы")
    bad = [e for e in api.log() if e["kind"] in ("ОШИБКА",) and "RCON" not in e["text"]
           and "в модели нет файла ../../secret.pth" not in e["text"]                    # это проверяли нарочно
           and "ИИ-голос: не запустилась" not in e["text"] and "не включился звук" not in e["text"]
           and "Связь с TikTok оборвалась" not in e["text"] and "Не удалось подключиться" not in e["text"]
           and "Minecraft" not in e["text"] and "сервер" not in e["text"].lower()]
    check("в журнале нет неожиданных ошибок", not bad, json.dumps(bad[:5], ensure_ascii=False)[:400])


def main():
    ap = argparse.ArgumentParser(description="Автопроверка TakyLive")
    ap.add_argument("--no-remote", action="store_true", help="не проверять пульт с телефона")
    ap.add_argument("--keep", action="store_true", help="не удалять временную копию")
    args = ap.parse_args()
    if not os.path.exists(os.path.join(ROOT, "app.py")):
        print("Не нашёл app.py — запускай из папки программы: python tools/smoke_test.py")
        return 2

    tmp = tempfile.mkdtemp(prefix="takylive_smoke_")
    copy_dir = os.path.join(tmp, "TakyLive")
    port, rport = free_port(), free_port()
    print(f"Копия программы: {copy_dir}\nПорт копии: {port}, пульт: {rport}")
    start_mock_vc()
    start_mock_hf()
    report_id = make_copy(copy_dir, rport)
    MOCK_VC["logfile"] = os.path.join(copy_dir, "voice-changer", "voice_changer_log.txt")
    os.makedirs(os.path.dirname(MOCK_VC["logfile"]), exist_ok=True)
    global DEVSIG_FILE
    DEVSIG_FILE = os.path.join(tmp, "devsig.txt")
    with open(DEVSIG_FILE, "w", encoding="utf-8") as f:
        f.write("o:Динамики|o:Наушники|i:Микрофон")

    env = dict(os.environ, TAKY_TEST="1", TAKY_FAKE_TIKTOK="1", TAKY_VC_DEVSIG=DEVSIG_FILE, TAKY_PORT=str(port), PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               TAKY_HF_BASE=f"http://127.0.0.1:{MOCK_HF_PORT}",
               TAKY_PRESETS_URL=f"http://127.0.0.1:{MOCK_HF_PORT}/presets.json")
    out_path = os.path.join(tmp, "app_output.txt")
    out = open(out_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=copy_dir, env=env, stdout=out, stderr=subprocess.STDOUT)
    api = Api(port)
    print("Запускаю копию (первый раз может ставить библиотеки — до 5 минут)…")
    up = wait_until(lambda: api.get("/api/version", timeout=3), 300, 1)
    try:
        if not up:
            check("программа запустилась", False, f"не ответила за 5 минут — см. {out_path}")
        else:
            check("программа запустилась в тестовом режиме", True)
            try:
                run_checks(api, copy_dir, report_id, rport, not args.no_remote)
            except Exception as e:
                import traceback
                traceback.print_exc()
                check("проверка дошла до конца", False, f"{type(e).__name__}: {e}")
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
        out.close()

    failed = [r for r in RESULTS if not r[1]]
    lines = [f"TakyLive smoke test — {time.strftime('%Y-%m-%d %H:%M')}",
             f"Итого: {len(RESULTS) - len(failed)} PASS, {len(failed)} FAIL"]
    lines += [f"FAIL: {n} — {d}" for n, _, d in failed]
    res_path = os.path.join(ROOT, "smoke_test_result.txt")
    with open(res_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n" + "\n".join(f"[{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if not ok else "")
                                                     for n, ok, d in RESULTS) + "\n")
    print("\n" + "=" * 60)
    print("\n".join(lines))
    print(f"Результат записан: {res_path}")
    print(f"Вывод программы: {out_path}")
    if args.keep or failed:
        print(f"Временная копия оставлена: {copy_dir}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
