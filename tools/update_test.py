"""Проверка обновления TakyLive «по-настоящему»: всё ли остаётся на месте.

    python tools/update_test.py            (из папки программы)

Что делает:
  1. Собирает во временной папке «старую» копию программы (версия 1.0) с данными стримера:
     настройки, вкладки с эдитами и музыкой, файлы в media, очки и голоса зрителей, отчёты,
     серверы с миром, картинки, озвучка, свой ключ Fish, голосовая программа.
  2. Поднимает поддельный GitHub с «новой» версией 99.0 (собрана из этой же папки).
  3. Запускает старую копию в тестовом режиме и жмёт «Обновить» — работает настоящий
     установщик обновления (на Windows — тот самый apply_update.bat с robocopy).
  4. Ждёт перезапуска и сверяет каждый файл данных побайтно, а ещё спрашивает у самой
     программы вкладки и настройки.

Интернет не нужен, установленную программу не трогает. Код выхода 0 — всё на месте.
На Windows после проверки может остаться окно «Press any key» — его можно закрыть.
"""
import hashlib
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
import urllib.request
import zipfile

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".git", "__pycache__", "build", "dist", "reports", "servers", "_backup", "_update", "voice-changer",
        "config.json", "profiles.json", "viewer_voices.json", "viewer_points.json", "fish_key.txt",
        "gift_catalog.json", "gift_icons_live.json", "smoke_test_result.txt", "gift_names_ru_full.json",
        "team_members.json", "music_state.json"}
RESULTS = []
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    return bool(ok)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def api(port, path, data=None, timeout=10):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body,
                                 headers={"Content-Type": "application/json"} if body is not None else {},
                                 method="POST" if body is not None else "GET")
    with OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait(fn, timeout, step=0.5):
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


def copy_program(dst, version):
    def ignore(d, names):
        return [n for n in names if n in SKIP or n.endswith((".pyc", ".log")) or ".broken-" in n]
    shutil.copytree(ROOT, dst, ignore=ignore)
    p = os.path.join(dst, "app.py")
    s = open(p, encoding="utf-8").read()
    s, n = re.subn(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{version}"', s, count=1)
    assert n == 1
    open(p, "w", encoding="utf-8").write(s)


def W(base, rel, data):
    p = os.path.join(base, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(p, mode, **({} if isinstance(data, bytes) else {"encoding": "utf-8", "newline": ""})) as f:
        f.write(data)


def make_user_data(base, api_port):
    J = lambda o: json.dumps(o, ensure_ascii=False, indent=1)
    profiles = {"Мой стрим": {
        "game": "minecraft",
        "gifts": [{"name": "Rose", "title": "эдит на розу", "commands": ["say hi"], "media_file": "мой эдит.mp4",
                   "media_kind": "video", "sound_file": "моя музыка.mp3", "media_volume": 80, "sound_volume": 60},
                  {"name": "Кулон дружбы", "title": "кулон", "commands": [], "media_file": "смешной кот.gif",
                   "media_kind": "gif"}],
        "panel": [{"title": "🎵 Музыка", "commands": [], "sound_file": "моя музыка.mp3"}],
        "chatcmds": [{"trigger": "!эдит", "title": "Эдит", "cooldown": 5, "commands": [], "media_file": "мой эдит.mp4"}]},
        "Вторая вкладка": {"game": "gta5", "gifts": [{"name": "Lion", "commands": ["chaos"]}]}}
    config = {"active_profile": "Мой стрим", "tiktok_username": "my_nick", "tts_enabled": True, "tts_voice": "ru-RU-DmitryNeural",
              "fish_api_key": "MY-OWN-FISH-KEY", "ai_on": True, "ai_key": "MY-AI-KEY", "ai_tg": "@my_tg", "ai_avatar": "ai_avatar_я.png",
              "pts_on": True, "wheel_on": True, "ann_tg_token": "123:ABC", "vc_mic_name": "Мой микрофон",
              "music_on": True, "music_source": "spotify", "music_gift": "Rose", "music_cost": 70, "music_sp_client": "my-client-id",
              "music_sp_refresh": "MY-SPOTIFY-LOGIN", "music_ya_token": "MY-YANDEX-LOGIN", "wheel_gift": "Lion", "vc_normal": "Демон",
              "random_items": [{"command": "say rnd", "media_file": "мой эдит.mp4", "sound_file": "моя музыка.mp3"}],
              "auto_update": "notify", "update_repo": "test/TakyLive", "update_api": f"http://127.0.0.1:{api_port}"}
    files = {
        "config.json": J(config),
        "profiles.json": J(profiles),
        "viewer_voices.json": J({"anya_1": {"voice": "ru-RU-SvetlanaNeural", "name": "Аня"}}),
        "viewer_points.json": J({"anya_1": {"n": "Аня", "p": 1500, "e": 2000, "s": 500, "t": 1}}),
        "gift_names_ru.json": J({"9947": "Кулон дружбы", "5655": "Роза", "777": "Мой перевод"}),
        "gift_icons_live.json": J({"rose": "https://example.com/rose.png"}),
        "gift_catalog.json": J({"gifts": {"424242": {"name": "My Local Gift", "coins": 7, "icon": "", "regions": ["BY"]}},
                                "regions": {"BY": {"count": 1, "at": "2026-01-01"}}}),
        "fish_key.txt": "MY-FISH-KEY-FILE",
        "team_members.json": J({"members": {"@anya_1": {"nick": "Аня", "user": "anya_1", "acc": "111", "level": 3,
                                                         "since": "2026-11-01 20:00", "seen": "2026-11-01 20:00", "via": "значок"}}}),
        "media/мой эдит.mp4": os.urandom(40000),
        "media/моя музыка.mp3": os.urandom(30000),
        "media/смешной кот.gif": b"GIF89a" + os.urandom(5000),
        "media/ai_avatar_я.png": b"\x89PNG" + os.urandom(3000),
        "media/mobs/мой моб.png": b"\x89PNG" + os.urandom(2000),
        "media/_thumbs/meta.json": J({"мой эдит.mp4": {"duration": 12.5, "w": 1080, "h": 1920, "size": 40000}}),
        "media/_thumbs/t1.jpg": os.urandom(800),
        "media/tts/preview_abc.mp3": os.urandom(900),
        "media/vault/15.$ Mobs/x.webp": os.urandom(700),
        "reports/20260101-200000.json": J({"id": "20260101-200000", "nick": "my_nick", "started": 1767286800, "ended": 1767290400,
                                             "duration": 3600, "totals": {"coins": 5, "likes": 10}}),
        "servers/servers.json": J([{"id": "s1", "name": "Мой сервер", "kind": "minecraft"}]),
        "servers/s1/world/level.dat": os.urandom(4000),
        "servers/s1/server.properties": "motd=Мой сервер\n",
        "voice-changer/MMVCServerSIO/model_dir/0/Демон.pth": os.urandom(6000),
        "_backup/20260101-120000/config.json": "{}",
        "мои заметки.txt": "не трогать",
    }
    for rel, data in files.items():
        W(base, rel, data)
    return files, profiles, config


def build_update_zip(src_dir, zpath):
    W(src_dir, "new_feature.txt", "привет из 99.0")
    W(src_dir, "fish_key.txt", "SHIPPED-COMMON-KEY")                       # в сборке лежит общий ключ
    W(src_dir, "gift_names_ru.json", json.dumps({"5655": "Роза (из сборки)"}, ensure_ascii=False))
    W(src_dir, "config.json", "{\"hacked\": true}")                        # такого в сборке не бывает — но не должен пройти
    W(src_dir, "media/tts/shipped.mp3", "x")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for r, d, fs in os.walk(src_dir):
            d[:] = [x for x in d if x != "__pycache__"]
            for f in fs:
                p = os.path.join(r, f)
                z.write(p, os.path.relpath(p, src_dir))
    return hashlib.sha256(open(zpath, "rb").read()).hexdigest()


def serve_fake_github(zpath, sha):
    port = free_port()
    size = os.path.getsize(zpath)

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/repos/test/TakyLive/releases/latest"):
                b = json.dumps({"tag_name": "v99.0", "body": "Тестовое обновление", "html_url": "http://x/",
                                "published_at": "2026-11-16T00:00:00Z",
                                "assets": [{"name": "TakyLive-99.0-update.zip", "size": size, "digest": "sha256:" + sha,
                                            "browser_download_url": f"http://127.0.0.1:{port}/dl/update.zip"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            elif self.path == "/dl/update.zip":
                b = open(zpath, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
            else:
                b = b"{}"
                self.send_response(404)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port


def start_app(folder, port, out):
    env = dict(os.environ, TAKY_TEST="1", TAKY_PORT=str(port), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.Popen([sys.executable, "app.py"], cwd=folder, env=env, stdout=out, stderr=subprocess.STDOUT)


def main():
    if not os.path.exists(os.path.join(ROOT, "app.py")):
        print("Запускай из папки программы: python tools/update_test.py")
        return 2
    tmp = tempfile.mkdtemp(prefix="takylive_updtest_")
    old, new_src = os.path.join(tmp, "Моя папка TakyLive"), os.path.join(tmp, "new_src")   # пробел и кириллица в пути
    zpath = os.path.join(tmp, "TakyLive-99.0-update.zip")
    print(f"Временная папка: {tmp}")
    copy_program(old, "1.0")
    copy_program(new_src, "99.0")
    sha = build_update_zip(new_src, zpath)
    gh_port = serve_fake_github(zpath, sha)
    files, profiles, config = make_user_data(old, gh_port)
    port = free_port()
    out = open(os.path.join(tmp, "app_output.txt"), "w", encoding="utf-8", errors="replace")
    proc = start_app(old, port, out)
    print("Запускаю старую версию (первый раз может ставить библиотеки)…")
    try:
        v = wait(lambda: api(port, "/api/version", timeout=3), 300, 1)
        if not check("старая версия 1.0 запустилась", v and v.get("version") == "1.0", str(v)):
            return 1
        st = api(port, "/api/state")
        check("до обновления программа видит обе вкладки", list(st["profiles"]) == list(profiles), str(list(st["profiles"])))
        api(port, "/api/simulate", {"kind": "gift", "name": "Rose", "gift_id": "5655", "count": 3, "user": "Аня", "diamonds": 1})
        time.sleep(1)
        chk = api(port, "/api/update/check", {})
        check("программа видит новую версию 99.0", (chk.get("info") or {}).get("version") == "99.0"
              and (chk.get("info") or {}).get("available"), str(chk)[:300])
        r = api(port, "/api/update/install", {})
        check("обновление запустилось", r.get("ok") is True, str(r))

        print("Жду, пока обновление поставится и программа перезапустится…")
        applied = os.path.join(old, "_update", "applied.txt")
        ver = lambda: ver_safe(lambda: api(port, "/api/version", timeout=2).get("version"))
        got = wait(lambda: (proc.poll() is not None and os.path.exists(applied)) or ver() == "99.0", 180, 1)
        if got and ver() != "99.0":                               # не Windows: скрипт не перезапускает — запускаем сами
            proc = start_app(old, port, out)
        up = wait(lambda: ver() == "99.0", 180, 1)
        if not check("после обновления запустилась версия 99.0", bool(up),
                     "программа не поднялась — см. app_output.txt и _update/"):
            return 1

        print("\n• Файлы данных — побайтно")
        skip_exact = {"config.json", "profiles.json", "viewer_points.json"}       # их программа вправе пересохранить
        for rel, data in files.items():
            p = os.path.join(old, *rel.split("/"))
            if rel in skip_exact:
                check(f"{rel} на месте", os.path.isfile(p))
                continue
            want = data if isinstance(data, bytes) else data.encode("utf-8")
            have = open(p, "rb").read() if os.path.isfile(p) else None
            check(f"{rel} не изменился", have == want, "файла нет" if have is None else "содержимое другое")

        print("\n• Что видит сама программа")
        st = api(port, "/api/state")
        check("вкладки те же, с эдитами и музыкой в карточках", st["profiles"] == profiles,
              json.dumps(st["profiles"], ensure_ascii=False)[:300])
        lost = {k: (v, st["config"].get(k)) for k, v in config.items() if st["config"].get(k) != v}
        check("настройки те же (ключи, ник, соведущий, ИИ-голос…)", not lost, str(lost)[:300])
        ml = api(port, "/api/media_list")
        names = {f["name"] for f in ml.get("files", [])}
        check("эдит, музыка и гифка видны в списке медиа", {"мой эдит.mp4", "моя музыка.mp3", "смешной кот.gif"} <= names,
              str(sorted(names))[:300])
        pts = api(port, "/api/points?q=" + urllib.request.quote("Аня"))
        check("очки зрителей на месте", any(r.get("key") == "anya_1" and int(r.get("amount", 0)) == 1500 for r in pts.get("rows", [])), str(pts)[:200])
        cat = api(port, "/api/gift_catalog")
        check("свой каталог подарков на месте (+ встроенный)", any(g.get("name") == "My Local Gift" for g in cat.get("gifts", []))
              and len(cat.get("gifts", [])) > 700, f"подарков: {len(cat.get('gifts', []))}")
        team = api(port, "/api/team")
        check("команда (кто вступил через «Heart Me») на месте", team.get("count") == 1
              and (team.get("recent") or [{}])[0].get("nick") == "Аня", str(team)[:200])
        reps = api(port, "/api/stats/list")
        check("отчёты эфиров на месте", any(i.get("id") == "20260101-200000" for i in reps.get("items", [])), str(reps)[:200])

        print("\n• Само обновление")
        check("новые файлы программы пришли", os.path.isfile(os.path.join(old, "new_feature.txt")))
        check("свой ключ Fish не заменён общим", open(os.path.join(old, "fish_key.txt"), encoding="utf-8").read() == "MY-FISH-KEY-FILE")
        check("config.json из архива не подменил настройки", "hacked" not in open(os.path.join(old, "config.json"), encoding="utf-8").read())
        bk = api(port, "/api/backups").get("items", [])
        check("перед обновлением сделана резервная копия", any("99.0" in b["id"] for b in bk), str([b["id"] for b in bk]))
        check("временные файлы обновления убраны", not os.path.isdir(os.path.join(old, "_update", "new")))
        log = api(port, "/api/log").get("log", [])
        bad = [e for e in log if e["kind"] == "ОШИБКА"]
        check("после обновления в журнале нет ошибок", not bad, json.dumps(bad[:3], ensure_ascii=False)[:300])

        print("\n• Восстановление из копии")
        api(port, "/api/profiles", {"profiles": {"Пусто": {"gifts": []}}})                # «всё сломалось»
        first = next((b for b in bk if "99.0" in b["id"]), None)
        r = api(port, "/api/backups/restore", {"id": first["id"]}) if first else {"ok": False}
        st = api(port, "/api/state")
        check("«↩ Вернуть» возвращает вкладки из копии", r.get("ok") and st["profiles"] == profiles, str(r))
    finally:
        try:
            api(port, "/api/test/quit", {}, timeout=3)
        except Exception:
            pass
        time.sleep(1)
        try:
            proc.terminate()
        except Exception:
            pass
        out.close()

    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 60)
    print(f"Обновление: {len(RESULTS) - len(failed)} PASS, {len(failed)} FAIL")
    for n, _, d in failed:
        print(f"FAIL: {n} — {d}")
    if failed:
        print(f"Папка оставлена для разбора: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


def ver_safe(fn):
    try:
        return fn()
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
