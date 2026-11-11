"""Обновления TakyLive через GitHub Releases.

Адрес репозитория программа узнаёт сама: при сборке на GitHub рядом с exe
кладётся update_source.json с полем repo («ник/TakyLive»). Можно задать и
вручную — настройка update_repo.

Обновление: скачиваем TakyLive-<версия>-update.zip, сверяем SHA-256 с тем,
что показывает GitHub, распаковываем в _update/new, запускаем маленький
скрипт-установщик и закрываемся. Скрипт ждёт, пока программа выйдет,
копирует новые файлы поверх старых — кроме данных пользователя — и
запускает программу снова.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import zipfile

from aiohttp import ClientSession, ClientTimeout, web

API = "https://api.github.com"
# что никогда не трогаем при обновлении — это данные пользователя
KEEP_FILES = ["config.json", "profiles.json", "viewer_voices.json", "fish_key.txt", "gift_icons_live.json",
              "gift_names_ru.json", "gift_catalog.json"]
KEEP_DIRS = ["servers", "java", "steamcmd", "vault", "tts", "_thumbs", "_backup", "_update", "_проверка"]
WIN = sys.platform == "win32"


def vkey(v):
    nums = [int(x) for x in re.findall(r"\d+", str(v).lstrip("vV"))[:4]]
    return tuple(nums + [0] * (4 - len(nums)))


class Updater:
    def __init__(self, base_dir, version, log, cfg, is_live):
        self.base, self.version, self.log, self.cfg, self.is_live = base_dir, version, log, cfg, is_live
        self.info = None              # последняя найденная версия
        self.checked_at = 0.0
        self.job = None               # {state, progress, error}
        self.error = ""
        self.auto = None              # обратный отсчёт автообновления: {version, at}
        self.postpone_until = 0.0     # «Не сейчас» — не предлагать до этого времени
        self.ready = None             # заранее скачанная версия (режим «ставить при запуске»)

    def repo(self):
        r = str(self.cfg().get("update_repo") or "").strip()
        if r:
            return r
        try:
            with open(os.path.join(self.base, "update_source.json"), encoding="utf-8") as f:
                return str(json.load(f).get("repo") or "").strip()
        except Exception:
            return ""

    def api(self):
        return str(self.cfg().get("update_api") or API).rstrip("/")

    async def check(self, force=False):
        repo = self.repo()
        if not repo:
            self.error = "адрес обновлений не задан — эта копия собрана не на GitHub"
            return None
        if not force and self.info is not None and time.time() - self.checked_at < 1800:
            return self.info
        url = f"{self.api()}/repos/{repo}/releases/latest"
        reset = None
        try:
            async with ClientSession(timeout=ClientTimeout(total=15),
                                     headers={"User-Agent": f"TakyLive/{self.version}",
                                              "Accept": "application/vnd.github+json"}) as cs:
                async with cs.get(url) as r:
                    if r.status == 404:
                        self.error = "в репозитории ещё нет ни одного релиза"
                        self.info, self.checked_at = None, time.time()
                        return None
                    if r.status in (403, 429):
                        # API без входа — 60 запросов в час на IP, а у провайдеров с общим IP их
                        # съедают чужие запросы. Тогда идём обычными страницами github.com.
                        reset = r.headers.get("X-RateLimit-Reset")
                        d = None
                    elif r.status != 200:
                        raise RuntimeError(f"GitHub ответил {r.status}")
                    else:
                        d = await r.json(content_type=None)
            info = self._from_api(d) if d is not None else await self._from_web(repo)
        except Exception as e:
            self.error = f"не удалось проверить обновления: {e}"
            if reset:
                try:
                    mins = max(1, int((int(reset) - time.time()) / 60) + 1)
                    self.error = f"GitHub временно ограничил проверки обновлений — попробуй через {mins} мин"
                except ValueError:
                    pass
            return None
        self.info = info
        self.info["available"] = bool(self.info["url"]) and vkey(self.info["version"]) > vkey(self.version)
        self.error, self.checked_at = "", time.time()
        if self.info["available"] and getattr(self, "_announced", "") != self.info["version"]:
            self._announced = self.info["version"]
            self.log("ОБНОВЛЕНИЕ", f"Доступна новая версия TakyLive {self.info['version']} (сейчас {self.version})")
        return self.info

    @staticmethod
    def _from_api(d):
        tag = str(d.get("tag_name") or "")
        asset = next((a for a in d.get("assets") or [] if str(a.get("name", "")).endswith("-update.zip")), None)
        dig = str((asset or {}).get("digest") or "")
        return {"version": tag.lstrip("vV"), "tag": tag, "notes": str(d.get("body") or "")[:4000],
                "url": (asset or {}).get("browser_download_url", ""), "size": (asset or {}).get("size", 0),
                "sha256": dig.split(":", 1)[1] if dig.startswith("sha256:") else "",
                "page": d.get("html_url", ""), "date": str(d.get("published_at") or "")[:10]}

    async def _from_web(self, repo):
        """Последний релиз без API: github.com/<repo>/releases/latest переадресует на страницу метки,
        а файлы релиза лежат по постоянному адресу …/releases/download/<метка>/<файл>."""
        base = f"https://github.com/{repo}/releases"
        async with ClientSession(timeout=ClientTimeout(total=20),
                                 headers={"User-Agent": f"TakyLive/{self.version}"}) as cs:
            async with cs.get(f"{base}/latest", allow_redirects=False) as r:
                loc = r.headers.get("Location", "")
            m = re.search(r"/releases/tag/([^/?#]+)$", loc)
            if not m:
                raise RuntimeError("GitHub не показал последний релиз")
            tag = urllib.parse.unquote(m.group(1))
            ver = tag.lstrip("vV")
            dl = f"{base}/download/{tag}/TakyLive-{ver}-update.zip"
            url, size, sha = "", 0, ""
            async with cs.head(dl, allow_redirects=True) as r:
                if r.status == 200:
                    url, size = dl, int(r.headers.get("Content-Length") or 0)
            if url:
                async with cs.get(dl + ".sha256", allow_redirects=True) as r:
                    if r.status == 200:
                        m = re.search(r"\b[0-9a-fA-F]{64}\b", await r.text())
                        sha = m.group(0).lower() if m else ""
        return {"version": ver, "tag": tag, "notes": "", "url": url, "size": size, "sha256": sha,
                "page": f"{base}/tag/{tag}", "date": ""}

    async def _download(self, url, dest):
        h = hashlib.sha256()
        async with ClientSession(timeout=ClientTimeout(total=1800, sock_read=60),
                                 headers={"User-Agent": f"TakyLive/{self.version}"}) as cs:
            async with cs.get(url, allow_redirects=True) as r:
                if r.status != 200:
                    raise RuntimeError(f"GitHub ответил {r.status} на скачивание")
                total = int(r.headers.get("Content-Length") or 0) or int((self.info or {}).get("size") or 0)
                got = 0
                with open(dest, "wb") as f:
                    async for chunk in r.content.iter_chunked(256 * 1024):
                        f.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        if total:
                            self.job["progress"] = round(min(1.0, got / total) * 0.85, 3)
        return h.hexdigest()

    def _script(self, new_dir):
        """Скрипт, который заменит файлы после выхода программы и запустит её снова."""
        frozen = getattr(sys, "frozen", False)
        exe = os.path.join(self.base, "TakyLive.exe") if frozen else os.path.join(self.base, "start.bat")
        upd = os.path.join(self.base, "_update")
        if WIN:
            path = os.path.join(upd, "apply_update.bat")
            body = ("@echo off\r\nchcp 65001 >nul\r\n"
                    f"title TakyLive: обновление\r\necho Обновляю TakyLive до версии {self.info['version']}...\r\n"
                    ":wait\r\n"
                    f'tasklist /FI "PID eq {os.getpid()}" 2>nul | find "{os.getpid()}" >nul && '
                    "(timeout /t 1 /nobreak >nul & goto wait)\r\n"
                    f'robocopy "{new_dir}" "{self.base}" /E /R:3 /W:1 /NFL /NDL /NJH /NJS '
                    f'/XF {" ".join(KEEP_FILES)} /XD {" ".join(KEEP_DIRS)} >nul\r\n'
                    # данные пользователя не заменяем, но если такого файла ещё нет (например, общий
                    # ключ Fish или названия подарков) — кладём из обновления
                    + "".join(f'if not exist "{os.path.join(self.base, f)}" if exist "{os.path.join(new_dir, f)}" '
                              f'copy /Y "{os.path.join(new_dir, f)}" "{os.path.join(self.base, f)}" >nul\r\n'
                              for f in KEEP_FILES) +
                    f'start "" "{exe}"\r\n'
                    f'rmdir /S /Q "{os.path.join(upd, "new")}"\r\n'
                    f'del /Q "{os.path.join(upd, "update.zip")}"\r\n'
                    '(goto) 2>nul & del "%~f0"\r\n')                     # и сам скрипт — без хвостов
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(body)
            return ["cmd", "/c", path]
        # не Windows: тот же порядок на Python — ждём выхода, копируем с теми же исключениями, что robocopy
        path = os.path.join(upd, "apply_update.py")
        body = f"""import os, shutil, time
pid, src, dst = {os.getpid()}, {new_dir!r}, {self.base!r}
KEEP_F, KEEP_D = {KEEP_FILES!r}, {KEEP_DIRS!r}
def alive(p):
    try:
        os.kill(p, 0); return True
    except OSError:
        return False
while alive(pid):
    time.sleep(0.3)
for root, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d not in KEEP_D]
    rel = os.path.relpath(root, src)
    os.makedirs(os.path.join(dst, rel), exist_ok=True)
    for fn in files:
        if fn not in KEEP_F:
            shutil.copy2(os.path.join(root, fn), os.path.join(dst, rel, fn))
for fn in KEEP_F:                     # своих данных нет — кладём из обновления, есть — не трогаем
    if not os.path.exists(os.path.join(dst, fn)) and os.path.exists(os.path.join(src, fn)):
        shutil.copy2(os.path.join(src, fn), os.path.join(dst, fn))
shutil.rmtree(src, ignore_errors=True)
open(os.path.join(dst, "_update", "applied.txt"), "w").write("done")
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return [sys.executable, path]

    async def install(self):
        if self.is_live():
            return {"ok": False, "error": "идёт эфир — обнови после стрима, чтобы не оборвать его"}
        if self.job and self.job["state"] in ("downloading", "extracting", "restarting"):
            return {"ok": False, "error": "обновление уже идёт"}
        # только что проверяли — не тратим ещё один запрос к GitHub (у API лимит 60 в час на IP)
        info = await self.check(force=time.time() - self.checked_at > 120)
        if not info or not info.get("available"):
            return {"ok": False, "error": self.error or "у тебя уже последняя версия"}
        self.job = {"state": "downloading", "progress": 0.0, "error": "", "version": info["version"]}
        asyncio.ensure_future(self._install_job())
        return {"ok": True, "version": info["version"]}

    async def _fetch(self):
        """Скачать, сверить контрольную сумму, распаковать в _update/new → путь к папке."""
        upd = os.path.join(self.base, "_update")
        shutil.rmtree(upd, ignore_errors=True)
        os.makedirs(upd, exist_ok=True)
        zpath = os.path.join(upd, "update.zip")
        digest = await self._download(self.info["url"], zpath)
        if self.info.get("sha256") and self.info["sha256"].lower() != digest:
            raise RuntimeError("файл обновления повреждён (не совпала контрольная сумма) — попробуй ещё раз")
        self.job.update(state="extracting", progress=0.9)
        new_dir = os.path.join(upd, "new")
        with zipfile.ZipFile(zpath) as z:
            for n in z.namelist():                         # защита от «../» в архиве
                if n.startswith("/") or ".." in n.replace("\\", "/").split("/"):
                    raise RuntimeError("подозрительный архив обновления")
            z.extractall(new_dir)
        need = "TakyLive.exe" if getattr(sys, "frozen", False) else "app.py"
        if not os.path.exists(os.path.join(new_dir, need)):
            raise RuntimeError(f"в обновлении нет {need} — архив не тот")
        return new_dir

    async def _install_job(self):
        try:
            new_dir = await self._fetch()
            upd = os.path.dirname(new_dir)                    # _update — из неё запускаем скрипт
            cmd = self._script(new_dir)
            self.job.update(state="restarting", progress=1.0)
            self.log("ОБНОВЛЕНИЕ", f"Ставлю версию {self.info['version']} — программа перезапустится")
            # CREATE_NEW_CONSOLE: своё окно «Обновляю…». Без консоли (DETACHED_PROCESS) cmd.exe
            # обрывает .bat на первом же echo — файлы не заменялись и программа не перезапускалась.
            kw = {"creationflags": 0x00000010 | 0x00000200} if WIN else {"start_new_session": True}
            subprocess.Popen(cmd, cwd=upd, close_fds=True, **kw)     # отдельно от программы
            await asyncio.sleep(1.2)                                  # даём окну получить ответ
            os._exit(0)
        except Exception as e:
            self.job.update(state="error", error=str(e))
            self.postpone_until = time.time() + 1800          # автоповтор — через 30 мин, а не каждые 40 с
            self.log("ОШИБКА", f"обновление: {e} — автоматически попробую через 30 минут")

    # ── Автообновление ──
    def mode(self):
        """auto — ставить само, когда нет эфира; on_start — скачать заранее, поставить при запуске; notify — только сообщать."""
        m = str(self.cfg().get("auto_update") or "auto")
        return m if m in ("auto", "on_start", "notify") else "auto"

    async def auto_loop(self):
        """Проверка раз в 30 минут; между проверками — следим, не закончился ли эфир."""
        await asyncio.sleep(8)
        while True:
            try:
                if self.repo() and self.cfg().get("auto_update_check", True):
                    await self.check(force=True)
            except Exception:
                pass
            for _ in range(120):                       # 120 × 15 с = 30 минут
                try:
                    await self._auto_step()
                except Exception as e:
                    self.log("ОШИБКА", f"автообновление: {e}")
                await asyncio.sleep(15)

    async def _auto_step(self):
        info = self.info
        busy = self.job and self.job.get("state") in ("downloading", "extracting", "restarting")
        if not info or not info.get("available") or busy:
            self.auto = None
            return
        m = self.mode()
        if m == "auto":
            if self.is_live() or time.time() < self.postpone_until:
                if self.auto:
                    self.log("ОБНОВЛЕНИЕ", "Автообновление отложено — " + ("идёт эфир" if self.is_live() else "ты нажал «Не сейчас»"))
                self.auto = None
                return
            if not self.auto or self.auto["version"] != info["version"]:
                self.auto = {"version": info["version"], "at": time.time() + 25}
                self.log("ОБНОВЛЕНИЕ", f"Через 25 секунд TakyLive обновится до {info['version']}")
                asyncio.ensure_future(self._fire(info["version"], self.auto["at"]))
        elif m == "on_start" and time.time() >= self.postpone_until and \
                (not self.ready or self.ready.get("version") != info["version"]):
            await self._prefetch()

    async def _fire(self, version, at):
        await asyncio.sleep(max(0, at - time.time()))
        a = self.auto
        if not a or a["version"] != version or a["at"] != at:        # отменили, отложили или пришла другая версия
            return
        if self.is_live():
            self.auto = None
            return
        self.auto = None
        await self.install()

    def postpone(self, hours=3):
        self.postpone_until = time.time() + hours * 3600
        self.auto = None
        self.log("ОБНОВЛЕНИЕ", f"Обновление отложено на {hours} ч")

    async def _prefetch(self):
        """Режим «ставить при запуске»: тихо скачать и проверить заранее."""
        self.job = {"state": "downloading", "progress": 0.0, "error": "", "version": self.info["version"], "prefetch": True}
        try:
            new_dir = await self._fetch()
            self.ready = {"version": self.info["version"]}
            with open(os.path.join(self.base, "_update", "ready.json"), "w", encoding="utf-8") as f:
                json.dump(self.ready, f)
            self.job = None
            self.log("ОБНОВЛЕНИЕ", f"Версия {self.info['version']} скачана — поставится при следующем запуске программы")
        except Exception as e:
            self.job = {"state": "error", "error": str(e), "version": self.info["version"]}
            self.postpone_until = time.time() + 1800          # не качать заново каждые 15 с
            self.log("ОШИБКА", f"не удалось заранее скачать обновление: {e} — попробую через 30 минут")

    def apply_ready(self):
        """При запуске: если заранее скачана новая версия — ставим её до старта программы."""
        try:
            with open(os.path.join(self.base, "_update", "ready.json"), encoding="utf-8") as f:
                ver = str(json.load(f).get("version") or "")
        except Exception:
            return False
        new_dir = os.path.join(self.base, "_update", "new")
        if vkey(ver) <= vkey(self.version) or not os.path.isdir(new_dir):
            shutil.rmtree(os.path.join(self.base, "_update"), ignore_errors=True)
            return False
        self.info = {"version": ver}
        cmd = self._script(new_dir)
        kw = {"creationflags": 0x00000010 | 0x00000200} if WIN else {"start_new_session": True}
        subprocess.Popen(cmd, cwd=os.path.join(self.base, "_update"), close_fds=True, **kw)
        return True

    # ── HTTP ──
    def routes(self, app):
        app.router.add_get("/api/update/status", self.h_status)
        app.router.add_post("/api/update/check", self.h_check)
        app.router.add_post("/api/update/install", self.h_install)
        app.router.add_post("/api/update/postpone", self.h_postpone)

    def status(self):
        auto = {"version": self.auto["version"], "left": max(0, round(self.auto["at"] - time.time()))} if self.auto else None
        return {"current": self.version, "repo": self.repo(), "info": self.info, "error": self.error, "job": self.job,
                "mode": self.mode(), "auto": auto, "ready": self.ready, "live": bool(self.is_live())}

    async def h_status(self, request):
        return web.json_response(self.status())

    async def h_check(self, request):
        await self.check(force=True)
        return web.json_response(self.status())

    async def h_install(self, request):
        self.auto = None
        return web.json_response(await self.install())

    async def h_postpone(self, request):
        self.postpone()
        return web.json_response({"ok": True})
