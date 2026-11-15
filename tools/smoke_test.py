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


# ── подготовка копии ────────────────────────────────────────────────────────────
def make_copy(dst, remote_port):
    def ignore(dirpath, names):
        return [n for n in names if n in SKIP_NAMES or n.endswith((".pyc", ".log"))]
    shutil.copytree(ROOT, dst, ignore=ignore)
    profiles = {"Тест": {
        "game": "minecraft",
        "panel": [{"title": "💥 Тест-кнопка", "commands": ["say smoke"]}],
        "gifts": [{"name": "Rose", "gift_id": "5655", "title": "роза", "commands": ["say rose"]}],
        "chatcmds": [{"trigger": "!крипер", "title": "Крипер", "cooldown": 0, "points_cost": 30,
                      "commands": ["say creeper"]}],
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
        "remote_on": False, "remote_port": remote_port,
    }
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
    n1 = len(MOCK_LOG)
    api.sim(kind="gift", name="Rose", gift_id="5655", count=1, user="small", diamonds=1)
    time.sleep(1.5)
    check("мелкий подарок (меньше порога) ИИ не зовёт", len(MOCK_LOG) == n1)
    od = api.get("/api/overlay?since=0")
    check("реплики идут в оверлей соведущего", any(e.get("type") == "ai" for e in od.get("new_events", [])))
    api.cfg(ai_on=False)
    mock.shutdown()

    print("\n• Журнал без ошибок программы")
    bad = [e for e in api.log() if e["kind"] in ("ОШИБКА",) and "RCON" not in e["text"]
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
    report_id = make_copy(copy_dir, rport)

    env = dict(os.environ, TAKY_TEST="1", TAKY_PORT=str(port), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
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
