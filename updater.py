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
import zipfile

from aiohttp import ClientSession, ClientTimeout, web

API = "https://api.github.com"
# что никогда не трогаем при обновлении — это данные пользователя
KEEP_FILES = ["config.json", "profiles.json", "viewer_voices.json", "fish_key.txt", "gift_icons_live.json",
              "gift_names_ru.json", "gift_catalog.json"]
KEEP_DIRS = ["servers", "java", "steamcmd", "vault", "tts", "_thumbs", "_update", "_проверка"]
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
        try:
            async with ClientSession(timeout=ClientTimeout(total=15),
                                     headers={"User-Agent": f"TakyLive/{self.version}",
                                              "Accept": "application/vnd.github+json"}) as cs:
                async with cs.get(url) as r:
                    if r.status == 404:
                        self.error = "в репозитории ещё нет ни одного релиза"
                        self.info, self.checked_at = None, time.time()
                        return None
                    if r.status != 200:
                        raise RuntimeError(f"GitHub ответил {r.status}")
                    d = await r.json(content_type=None)
        except Exception as e:
            self.error = f"не удалось проверить обновления: {e}"
            return None
        tag = str(d.get("tag_name") or "")
        asset = next((a for a in d.get("assets") or [] if str(a.get("name", "")).endswith("-update.zip")), None)
        dig = str((asset or {}).get("digest") or "")
        self.info = {"version": tag.lstrip("vV"), "tag": tag, "notes": str(d.get("body") or "")[:4000],
                     "url": (asset or {}).get("browser_download_url", ""), "size": (asset or {}).get("size", 0),
                     "sha256": dig.split(":", 1)[1] if dig.startswith("sha256:") else "",
                     "page": d.get("html_url", ""), "date": str(d.get("published_at") or "")[:10]}
        self.info["available"] = bool(self.info["url"]) and vkey(self.info["version"]) > vkey(self.version)
        self.error, self.checked_at = "", time.time()
        if self.info["available"] and getattr(self, "_announced", "") != self.info["version"]:
            self._announced = self.info["version"]
            self.log("ОБНОВЛЕНИЕ", f"Доступна новая версия TakyLive {self.info['version']} (сейчас {self.version})")
        return self.info

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
                    f'start "" "{exe}"\r\n'
                    f'rmdir /S /Q "{os.path.join(upd, "new")}"\r\n'
                    f'del /Q "{os.path.join(upd, "update.zip")}"\r\n')
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
        info = await self.check(force=True)
        if not info or not info.get("available"):
            return {"ok": False, "error": self.error or "у тебя уже последняя версия"}
        self.job = {"state": "downloading", "progress": 0.0, "error": "", "version": info["version"]}
        asyncio.ensure_future(self._install_job())
        return {"ok": True, "version": info["version"]}

    async def _install_job(self):
        upd = os.path.join(self.base, "_update")
        try:
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
            self.log("ОШИБКА", f"обновление: {e}")

    # ── HTTP ──
    def routes(self, app):
        app.router.add_get("/api/update/status", self.h_status)
        app.router.add_post("/api/update/check", self.h_check)
        app.router.add_post("/api/update/install", self.h_install)

    def status(self):
        return {"current": self.version, "repo": self.repo(), "info": self.info, "error": self.error, "job": self.job}

    async def h_status(self, request):
        return web.json_response(self.status())

    async def h_check(self, request):
        await self.check(force=True)
        return web.json_response(self.status())

    async def h_install(self, request):
        return web.json_response(await self.install())
