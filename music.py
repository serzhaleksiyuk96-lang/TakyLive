# -*- coding: utf-8 -*-
"""🎵 Заказ музыки: зритель пишет в чат «!трек название» — трек встаёт в очередь и играет в эфире.

Источник выбирает стример (один из трёх):
  youtube — YouTube Music. Играет официальный встроенный плеер YouTube в оверлее (звук идёт в OBS).
            Поиск: свой ключ YouTube Data API или библиотека ytmusicapi (без ключа).
  spotify — Spotify стримера (нужен Premium). Трек добавляется в очередь его Spotify, звук — из приложения.
            Вход — официальный (OAuth PKCE), своё «приложение» в Spotify for Developers.
  yandex  — Яндекс Музыка, экспериментально: у сервиса нет открытого API, работает через неофициальную
            библиотеку yandex-music и токен аккаунта стримера. Играет в оверлее.
"""
import asyncio
import base64
import hashlib
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse

import aiohttp

YT_API = (os.environ.get("TAKY_YT_API") or "https://www.googleapis.com/youtube/v3").rstrip("/")
SP_API = (os.environ.get("TAKY_SPOTIFY_API") or "https://api.spotify.com/v1").rstrip("/")
SP_ACC = (os.environ.get("TAKY_SPOTIFY_ACCOUNTS") or "https://accounts.spotify.com").rstrip("/")
SP_SCOPES = "user-modify-playback-state user-read-playback-state user-read-currently-playing"
# Вход в Яндекс: настоящая страница входа Яндекса; программа представляется приложением Яндекс Музыки
# (другого способа получить доступ к Музыке Яндекс не даёт) и забирает токен из адреса после входа.
YA_LOGIN = os.environ.get("TAKY_YA_LOGIN_URL") or \
    "https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d"
SOURCES = {"youtube": "YouTube Music", "spotify": "Spotify", "yandex": "Яндекс Музыка"}

DEFAULTS = {
    "music_on": False,
    "music_source": "youtube",
    "music_cmd": "!трек",          # «!трек название песни»
    "music_cost": 0,               # цена заказа в очках (0 — без очков)
    "music_gift": "",              # подарок, который даёт право на заказ (пусто — не нужен)
    "music_gift_orders": 1,        # сколько заказов даёт один такой подарок
    "music_user_cd": 120,          # один зритель — не чаще раза в N секунд
    "music_max_min": 6,            # треки длиннее N минут не берём
    "music_queue_max": 15,
    "music_block": "",             # стоп-слова через запятую: трек с таким словом в названии не ставится
    "music_volume": 60,            # громкость в оверлее (YouTube, Яндекс), 0–100
    "music_yt_key": "",            # необязательно: свой ключ YouTube Data API
    "music_sp_client": "",         # Client ID приложения из developer.spotify.com
    "music_sp_refresh": "",        # выдаёт Spotify после входа (меняется только сервером)
    "music_ya_token": "",          # токен Яндекс Музыки
}
STOP = ("skip", "скип", "next", "дальше", "пропустить")


def _lib(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _iso_dur(s):
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", str(s or ""))
    return (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else 0


def _int(v, d=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


class MusicBox:
    def __init__(self, log, get_cfg, save_cfg):
        self.log, self.get_cfg, self.save_cfg = log, get_cfg, save_cfg
        self.queue, self.cur = [], None
        self.n = self.seq = 0
        self.paused = False
        self.credits, self.user_at = {}, {}        # заказы за подарки; когда зритель заказывал в прошлый раз
        self.ov_seen = self.ov_hint = 0.0          # оверлей открыт? (он играет YouTube и Яндекс)
        self._sp_tok, self._pkce = ("", 0.0), {}
        self._sp_at = self._sp_err = 0.0
        self._sp_now = None
        self._ya = (None, "")
        self._src = None
        self.ya_login = {"running": False, "error": "", "ok": False}
        self.lock = asyncio.Lock()

    # ── общее ────────────────────────────────────────────────────────────────
    def _check_src(self):
        """Сменили сервис — старые заказы там не сыграть: очищаем очередь (до нового заказа, не после)."""
        src = self.src()
        if self._src is not None and src != self._src and (self.queue or self.cur):
            self.queue, self.cur = [], None
            self.log("МУЗЫКА", f"🎵 Сервис сменён на {SOURCES[src]} — очередь заказов очищена")
        self._src = src
        return src

    def src(self):
        s = str(self.get_cfg().get("music_source") or "youtube")
        return s if s in SOURCES else "youtube"

    def cooldown_left(self, key):
        cd = _int(self.get_cfg().get("music_user_cd"), 120)
        return max(0, int(self.user_at.get(key, 0) + cd - time.time() + 0.99)) if cd > 0 else 0

    def gift(self, key, count):
        n = max(1, _int(self.get_cfg().get("music_gift_orders"), 1)) * max(1, int(count or 1))
        self.credits[key] = min(50, self.credits.get(key, 0) + n)
        return self.credits[key]

    async def _http(self, method, url, **kw):
        timeout = aiohttp.ClientTimeout(total=kw.pop("timeout", 12))
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.request(method, url, **kw) as r:
                try:
                    d = await r.json(content_type=None)
                except Exception:
                    d = {}
                return r.status, d if isinstance(d, (dict, list)) else {}

    # ── поиск ────────────────────────────────────────────────────────────────
    async def search(self, q):
        """→ список кандидатов [{tid, title, artist, dur}] у выбранного сервиса."""
        return await getattr(self, "_search_" + self.src())(q)

    async def _search_youtube(self, q):
        key = str(self.get_cfg().get("music_yt_key") or "").strip()
        if key:                                    # официальный поиск YouTube: только музыка и только то, что можно встроить
            st, d = await self._http("GET", YT_API + "/search", params={
                "part": "snippet", "type": "video", "videoCategoryId": "10", "videoEmbeddable": "true",
                "maxResults": "5", "q": q, "key": key})
            if st != 200:
                msg = str(((d or {}).get("error") or {}).get("message") or "")[:120] if isinstance(d, dict) else ""
                raise RuntimeError("ключ YouTube не подошёл или кончился его дневной лимит" + (f" ({msg})" if msg else ""))
            items = [{"tid": i["id"]["videoId"], "title": i["snippet"].get("title", ""),
                      "artist": i["snippet"].get("channelTitle", ""), "dur": 0}
                     for i in d.get("items", []) if isinstance(i.get("id"), dict) and i["id"].get("videoId")]
            if items:
                st, d = await self._http("GET", YT_API + "/videos", params={
                    "part": "contentDetails", "id": ",".join(i["tid"] for i in items), "key": key})
                durs = {v["id"]: _iso_dur(v.get("contentDetails", {}).get("duration")) for v in (d or {}).get("items", [])} \
                    if st == 200 else {}
                for i in items:
                    i["dur"] = durs.get(i["tid"], 0)
                    i["artist"] = re.sub(r"\s*-\s*Topic$", "", i["artist"])
            return items
        if not _lib("ytmusicapi"):
            raise RuntimeError("для поиска на YouTube Music нужна библиотека ytmusicapi (pip install ytmusicapi) "
                               "или свой ключ YouTube в настройках заказа музыки")

        def go():
            from ytmusicapi import YTMusic
            yt, out = YTMusic(), []
            for flt in ("songs", "videos"):        # сначала песни; клипы — запасные (песню могут запретить встраивать)
                try:
                    res = yt.search(q, filter=flt, limit=4)
                except Exception:
                    res = []
                for r in res[:4]:
                    if r.get("videoId"):
                        out.append({"tid": r["videoId"], "title": r.get("title", ""), "dur": _int(r.get("duration_seconds")),
                                    "artist": ", ".join(a.get("name", "") for a in (r.get("artists") or [])[:2])})
            return out
        return await asyncio.to_thread(go)

    async def _search_spotify(self, q):
        d = await self._sp("GET", "/search", params={"q": q, "type": "track", "limit": "5"})
        return [{"tid": t["uri"], "title": t.get("name", ""), "dur": _int(t.get("duration_ms")) // 1000,
                 "artist": ", ".join(a.get("name", "") for a in (t.get("artists") or [])[:2])}
                for t in ((d.get("tracks") or {}).get("items") or []) if t and t.get("uri")]

    async def _ya_client(self):
        token = str(self.get_cfg().get("music_ya_token") or "").strip()
        if not token:
            raise RuntimeError("впиши токен Яндекс Музыки в настройках заказа музыки")
        if not _lib("yandex_music"):
            raise RuntimeError("для Яндекс Музыки нужна библиотека yandex-music (pip install yandex-music)")
        if self._ya[1] != token:
            from yandex_music import ClientAsync
            try:
                self._ya = (await ClientAsync(token, base_url=os.environ.get("TAKY_YANDEX_API") or None).init(), token)
            except Exception as e:
                raise RuntimeError(f"Яндекс Музыка не приняла токен ({type(e).__name__}) — получи его заново")
        return self._ya[0]

    @staticmethod
    def _browser():
        fake = os.environ.get("TAKY_YA_BROWSER")                   # для автопроверки
        if fake:
            return [sys.executable, fake]
        names = ("msedge", "chrome") if sys.platform == "win32" else ("google-chrome", "chromium", "microsoft-edge")
        for n in names:
            p = shutil.which(n)
            if p:
                return [p]
        if sys.platform == "win32":
            for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
                for sub in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                    p = os.path.join(root or "", sub)
                    if root and os.path.isfile(p):
                        return [p]
        return None

    async def yandex_login(self):
        """Открывает отдельное окно браузера со страницей входа Яндекса, ждёт входа и сама забирает токен."""
        if self.ya_login["running"]:
            return
        exe = self._browser()
        if not exe:
            raise RuntimeError("не нашёл браузер Edge или Chrome")
        with socket.socket() as so:
            so.bind(("127.0.0.1", 0))
            port = so.getsockname()[1]
        prof = tempfile.mkdtemp(prefix="taky_ya_")                 # чистый профиль: твой обычный браузер не трогаем
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        proc = subprocess.Popen(exe + [f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--no-first-run",
                                       "--no-default-browser-check", "--window-size=520,760", f"--app={YA_LOGIN}"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        self.ya_login = {"running": True, "error": "", "ok": False}
        asyncio.ensure_future(self._yandex_wait(proc, port, prof))

    async def _yandex_wait(self, proc, port, prof):
        st, token, end, seen = self.ya_login, "", time.time() + 600, False
        try:
            while time.time() < end and not token:
                await asyncio.sleep(1)
                try:
                    code, tabs = await self._http("GET", f"http://127.0.0.1:{port}/json/list", timeout=3)
                except Exception:
                    if proc.poll() is not None or seen:            # окно закрыли
                        break
                    continue
                seen = True
                for t in tabs if isinstance(tabs, list) else []:
                    m = re.search(r"[#&?]access_token=([^&\s]+)", str(t.get("url") or ""))
                    if m:
                        token = urllib.parse.unquote(m.group(1))
            if token:
                self.get_cfg()["music_ya_token"] = token
                self.save_cfg()
                self._ya = (None, "")
                st["ok"] = True
                self.log("МУЗЫКА", "🎵 Яндекс Музыка подключена")
            else:
                st["error"] = "вход не завершён — окно закрыто или прошло 10 минут"
        except Exception as e:
            st["error"] = str(e) or type(e).__name__
        finally:
            st["running"] = False
            try:
                proc.terminate()
            except Exception:
                pass
            await asyncio.sleep(1)
            shutil.rmtree(prof, ignore_errors=True)                # вход в Яндекс в этом окне не сохраняем

    async def _search_yandex(self, q):
        c = await self._ya_client()
        try:
            r = await c.search(q, type_="track")
        except Exception as e:
            raise RuntimeError(f"поиск в Яндекс Музыке не сработал: {str(e)[:120] or type(e).__name__}")
        res = (getattr(getattr(r, "tracks", None), "results", None) or [])[:5]
        return [{"tid": str(t.id), "title": t.title or "", "dur": _int(t.duration_ms) // 1000,
                 "artist": ", ".join(a.name or "" for a in (t.artists or [])[:2])}
                for t in res if getattr(t, "available", True)]

    async def stream_url(self, seq):
        """Прямая ссылка на звук текущего трека Яндекс Музыки (её открывает оверлей)."""
        cur = self.cur
        if not cur or cur["seq"] != seq or cur["src"] != "yandex":
            raise RuntimeError("трек уже сменился")
        c = await self._ya_client()
        infos = await c.tracks_download_info(cur["tid"])
        mp3 = sorted([i for i in infos or [] if getattr(i, "codec", "") == "mp3"],
                     key=lambda i: (bool(getattr(i, "preview", False)), -(getattr(i, "bitrate_in_kbps", 0) or 0)))
        if not mp3:
            raise RuntimeError("Яндекс не отдал трек (нужна подписка Плюс?)")
        return await mp3[0].get_direct_link_async()      # ссылка живёт около минуты — берём перед самым запуском

    # ── Spotify ──────────────────────────────────────────────────────────────
    def spotify_login_url(self, redirect):
        cid = str(self.get_cfg().get("music_sp_client") or "").strip()
        if not cid:
            raise RuntimeError("сначала впиши Client ID приложения Spotify")
        ver = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(16)
        self._pkce = {"ver": ver, "state": state, "redirect": redirect, "cid": cid}
        ch = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).decode().rstrip("=")
        return SP_ACC + "/authorize?" + urllib.parse.urlencode({
            "client_id": cid, "response_type": "code", "redirect_uri": redirect, "scope": SP_SCOPES,
            "code_challenge_method": "S256", "code_challenge": ch, "state": state})

    async def spotify_finish(self, code, state):
        p = self._pkce
        if not p or not code or state != p.get("state"):
            raise RuntimeError("вход устарел — нажми «Войти в Spotify» ещё раз")
        st, d = await self._http("POST", SP_ACC + "/api/token", data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": p["redirect"],
            "client_id": p["cid"], "code_verifier": p["ver"]})
        if st != 200 or not d.get("refresh_token"):
            raise RuntimeError(f"Spotify не выдал доступ: {d.get('error_description') or d.get('error') or st}")
        self._pkce = {}
        self._set_tokens(d)
        self.log("МУЗЫКА", "🎵 Spotify подключён")

    def _set_tokens(self, d):
        self._sp_tok = (d.get("access_token", ""), time.time() + _int(d.get("expires_in"), 3600) - 60)
        if d.get("refresh_token") and d["refresh_token"] != self.get_cfg().get("music_sp_refresh"):
            self.get_cfg()["music_sp_refresh"] = d["refresh_token"]
            self.save_cfg()

    async def _sp_token(self, force=False):
        if self._sp_tok[0] and time.time() < self._sp_tok[1] and not force:
            return self._sp_tok[0]
        cfg = self.get_cfg()
        ref, cid = str(cfg.get("music_sp_refresh") or ""), str(cfg.get("music_sp_client") or "").strip()
        if not ref or not cid:
            raise RuntimeError("Spotify не подключён — нажми «Войти в Spotify» в настройках заказа музыки")
        st, d = await self._http("POST", SP_ACC + "/api/token", data={
            "grant_type": "refresh_token", "refresh_token": ref, "client_id": cid})
        if st != 200 or not d.get("access_token"):
            if st in (400, 401):
                cfg["music_sp_refresh"] = ""
                self.save_cfg()
                raise RuntimeError("вход в Spotify устарел — нажми «Войти в Spotify» ещё раз")
            raise RuntimeError(f"Spotify не отвечает ({st})")
        self._set_tokens(d)
        return self._sp_tok[0]

    async def _sp(self, method, path, params=None, _retry=True):
        tok = await self._sp_token()
        st, d = await self._http(method, SP_API + path, params=params, headers={"Authorization": "Bearer " + tok})
        if st == 401 and _retry:
            await self._sp_token(force=True)
            return await self._sp(method, path, params, _retry=False)
        if st in (200, 201, 202, 204):
            return d if isinstance(d, dict) else {}
        err = (d.get("error") if isinstance(d, dict) else None) or {}
        reason, msg = (err.get("reason", ""), err.get("message", "")) if isinstance(err, dict) else ("", str(err))
        if reason == "PREMIUM_REQUIRED" or "premium" in str(msg).lower():
            raise RuntimeError("для заказов нужен Spotify Premium")
        if st == 404 or reason == "NO_ACTIVE_DEVICE":
            raise RuntimeError("Spotify молчит: открой Spotify на ПК и включи любой трек — заказы встанут в его очередь")
        if st == 403:
            raise RuntimeError("Spotify отказал (403): в приложении на developer.spotify.com добавь свой аккаунт в "
                               "User Management и войди ещё раз")
        if st == 429:
            raise RuntimeError("Spotify просит подождать — слишком много запросов")
        raise RuntimeError(f"Spotify: ошибка {st} {str(msg)[:100]}")

    # ── заказ ────────────────────────────────────────────────────────────────
    async def request(self, user, query):
        """Ищет трек и ставит в очередь. → {"ok", "msg", "item"} — msg понятен зрителю."""
        cfg = self.get_cfg()
        self._check_src()
        q = " ".join(str(query or "").split())[:80]
        if len(q) < 2:
            return {"ok": False, "msg": f"напиши название: {cfg.get('music_cmd') or '!трек'} исполнитель песня"}
        if len(self.queue) >= max(1, _int(cfg.get("music_queue_max"), 15)):
            return {"ok": False, "msg": "очередь заказов полная — попробуй позже"}
        block = [w.strip().lower() for w in str(cfg.get("music_block") or "").split(",") if w.strip()]
        bad = lambda s: any(w in s.lower() for w in block)
        if bad(q):
            return {"ok": False, "msg": "такой трек здесь не ставят"}
        try:
            cands = await self.search(q)
        except RuntimeError as e:
            self.log("ОШИБКА", f"заказ музыки: {e}")
            return {"ok": False, "msg": "заказ музыки сейчас не работает", "error": str(e)}
        except Exception as e:
            self.log("ОШИБКА", f"заказ музыки: поиск не сработал — {type(e).__name__}: {str(e)[:120]}")
            return {"ok": False, "msg": "заказ музыки сейчас не работает", "error": str(e)}
        mx = max(1, _int(cfg.get("music_max_min"), 6)) * 60
        ok = [c for c in cands if c.get("tid") and (not c["dur"] or c["dur"] <= mx) and not bad(c["title"] + " " + c["artist"])]
        if not ok:
            return {"ok": False, "msg": f"«{q[:40]}» — не нашёл" if not cands else
                    f"«{q[:40]}» — нашёл только длиннее {mx // 60} мин или из стоп-списка"}
        c = ok[0]
        if any(x["tid"] == c["tid"] for x in self.queue + ([self.cur] if self.cur else [])):
            return {"ok": False, "msg": f"«{c['title'][:40]}» уже в очереди"}
        src = self.src()
        async with self.lock:
            if src == "spotify":
                try:
                    await self._sp("POST", "/me/player/queue", params={"uri": c["tid"]})
                except RuntimeError as e:
                    self.log("ОШИБКА", f"заказ музыки: {e}")
                    return {"ok": False, "msg": "заказ музыки сейчас не работает", "error": str(e)}
            self.n += 1
            item = {"n": self.n, "src": src, "tid": c["tid"], "title": c["title"][:120], "artist": c["artist"][:80],
                    "dur": c["dur"], "user": str(user or "")[:40], "alts": [x["tid"] for x in ok[1:4]], "at": time.time()}
            self.queue.append(item)
        name = (item["artist"] + " — " if item["artist"] else "") + item["title"]
        self.log("МУЗЫКА", f"🎵 {user or 'Стример'} заказал(а): {name} (в очереди: {len(self.queue)})")
        return {"ok": True, "msg": f"в очереди: {name[:60]}", "item": item}

    # ── воспроизведение ──────────────────────────────────────────────────────
    def _start_next(self):
        self.cur = self.queue.pop(0)
        self.seq += 1
        self.cur.update(seq=self.seq, t0=time.time(), started=0.0)
        self.log("МУЗЫКА", f"🎵 Играет: {self.cur['artist']} — {self.cur['title']}" +
                 (f" · заказал(а) {self.cur['user']}" if self.cur["user"] else ""))

    async def tick(self):
        """Раз в секунду."""
        now = time.time()
        src = self._check_src()
        if not self.get_cfg().get("music_on"):
            return
        if src == "spotify":
            if (self.queue or self.cur) and now - self._sp_at >= 3:
                self._sp_at = now
                try:
                    await self._spotify_sync()
                except Exception as e:
                    if now - self._sp_err > 60:
                        self._sp_err = now
                        self.log("ОШИБКА", f"заказ музыки: {e}")
            return
        cur = self.cur
        if cur is None:
            if self.queue and not self.paused:
                self._start_next()
            return
        if now - self.ov_seen > 10:                              # играть некому: оверлей не открыт
            cur["t0"] = now
            if now - self.ov_hint > 90:
                self.ov_hint = now
                self.log("МУЗЫКА", "⚠ Музыка играет в оверлее «🎵 Заказ музыки» — добавь его в OBS (📺 Оверлеи OBS), "
                                   "иначе заказы не зазвучат")
        elif not cur["started"] and not self.paused and now - cur["t0"] > 25:
            self.event(cur["seq"], "error", "не запустился за 25 секунд")
        elif cur["started"] and cur["dur"] and not self.paused and now - cur["started"] > cur["dur"] + 30:
            self.cur = None                                      # оверлей не сообщил о конце — идём дальше

    async def _spotify_sync(self):
        d = await self._sp("GET", "/me/player/currently-playing")
        uri = ((d or {}).get("item") or {}).get("uri", "")
        self._sp_now = {"uri": uri, "pos": _int(d.get("progress_ms")) / 1000, "at": time.time(),
                        "playing": bool(d.get("is_playing"))} if uri else None
        if self.cur and self.cur["tid"] != uri:
            self.cur = None
        if not self.cur and uri:
            for i, it in enumerate(self.queue):
                if it["tid"] == uri:
                    del self.queue[:i]                           # всё, что стояло раньше, уже отыграло
                    self._start_next()
                    self.cur["started"] = time.time()
                    break
        self.queue = [it for it in self.queue if time.time() - it["at"] < 3 * 3600]

    def event(self, seq, kind, detail=""):
        """Оверлей сообщает: playing — заиграл, ended — доиграл, error — не играется."""
        cur = self.cur
        if not cur or cur.get("seq") != seq:
            return
        if kind == "playing":
            cur["started"] = cur["started"] or time.time()
        elif kind == "ended":
            self.cur = None
        elif kind == "error":
            if cur["alts"]:                                      # тот же трек в другом ролике
                cur["tid"] = cur["alts"].pop(0)
                self.seq += 1
                cur.update(seq=self.seq, t0=time.time(), started=0.0)
                self.log("МУЗЫКА", f"🎵 «{cur['title'][:50]}» не запустился ({detail or 'запрещено встраивание'}) — пробую другой вариант")
            else:
                self.log("МУЗЫКА", f"🎵 «{cur['title'][:50]}» не играется ({detail or 'владелец запретил встраивание'}) — пропускаю")
                self.cur = None

    async def control(self, do, n=None):
        spotify = self.src() == "spotify"
        if do == "skip":
            if spotify:
                await self._sp("POST", "/me/player/next")
            if self.cur:
                self.log("МУЗЫКА", f"🎵 Пропущен: {self.cur['title'][:60]}")
            self.cur = None
        elif do in ("pause", "resume"):
            if spotify:
                await self._sp("PUT", "/me/player/" + ("pause" if do == "pause" else "play"))
            self.paused = do == "pause"
        elif do == "clear":
            self.queue = []
            self.log("МУЗЫКА", "🎵 Очередь заказов очищена" + (" (в самом Spotify треки остались — пролистай их)" if spotify else ""))
        elif do == "remove":
            self.queue = [it for it in self.queue if it["n"] != _int(n, -1)]
        else:
            raise RuntimeError("не знаю такую команду музыки")

    async def command(self, cmd, user=""):
        """music:skip · music:pause · music:play · music:clear · music:название трека (заказ без оплаты)."""
        body = str(cmd or "").strip()[6:].strip()
        low = body.lower()
        if low in STOP:
            await self.control("skip")
        elif low in ("pause", "пауза", "стоп"):
            await self.control("pause")
        elif low in ("play", "resume", "играть"):
            await self.control("resume")
        elif low in ("clear", "очистить"):
            await self.control("clear")
        elif body:
            r = await self.request(user, body)
            if not r["ok"]:
                raise RuntimeError(r.get("error") or r["msg"])
        return True

    # ── состояние для оверлея и окна ─────────────────────────────────────────
    def public(self, overlay=False):
        cfg = self.get_cfg()
        if overlay:
            self.ov_seen = time.time()
        src, cur, now = self.src(), None, time.time()
        if self.cur:
            c = self.cur
            pos = (now - c["started"]) if c["started"] else 0
            if src == "spotify" and self._sp_now:
                pos = self._sp_now["pos"] + (now - self._sp_now["at"] if self._sp_now["playing"] else 0)
            cur = {"seq": c["seq"], "kind": {"youtube": "youtube", "yandex": "audio"}.get(c["src"], "external"),
                   "tid": c["tid"] if c["src"] == "youtube" else "", "title": c["title"], "artist": c["artist"],
                   "user": c["user"], "dur": c["dur"], "pos": round(max(0, pos), 1)}
        return {"on": bool(cfg.get("music_on")), "source": src, "source_name": SOURCES[src], "paused": self.paused,
                "volume": max(0, min(100, _int(cfg.get("music_volume"), 60))), "cmd": str(cfg.get("music_cmd") or "!трек"),
                "current": cur, "queue": [{k: it[k] for k in ("n", "title", "artist", "user", "dur")} for it in self.queue]}

    def status(self):
        cfg = self.get_cfg()
        st = self.public()
        st.update(sp_linked=bool(cfg.get("music_sp_refresh")), ov_open=time.time() - self.ov_seen < 10,
                  libs={"ytmusicapi": _lib("ytmusicapi"), "yandex_music": _lib("yandex_music")},
                  sources=SOURCES, credits=sum(self.credits.values()), ya_login=self.ya_login,
                  ya_linked=bool(str(cfg.get("music_ya_token") or "").strip()))
        return st
