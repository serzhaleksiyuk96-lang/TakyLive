"""Локальные серверы Steam-игр (Rust, Palworld, ARK, Valheim) через SteamCMD.

Подмешивается в LocalServers (servers.py): общий список, консоль и кнопки,
но установка через SteamCMD и запуск со своими параметрами у каждой игры.
"""
import asyncio
import os
import time
import re
import secrets
import signal
import sys
import zipfile

WIN = sys.platform == "win32"
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

# rcon: webrcon — Rust, rcon — обычный Source RCON, None — консоли нет
STEAM_GAMES = {
    "rust": {"name": "Rust", "appid": "258550", "disk": "≈12 ГБ", "ram": "8–12 ГБ",
             "exe": "RustDedicated.exe", "port": 28015, "rcon": "webrcon", "rcon_port": 28016, "players": 10,
             "log": "server.log", "ready": r"Server startup complete", "stop": ["quit"]},
    "palworld": {"name": "Palworld", "appid": "2394010", "disk": "≈4 ГБ", "ram": "8–16 ГБ",
                 "exe": "PalServer.exe", "port": 8211, "rcon": "rcon", "rcon_port": 25575, "rest_port": 8212,
                 "players": 16, "log": "", "ready": r"Running Palworld dedicated server",
                 "stop": ["Save", "Shutdown 1"]},
    "ark": {"name": "ARK: Survival Ascended", "appid": "2430930", "disk": "≈15 ГБ", "ram": "12–16 ГБ",
            "exe": "ShooterGame/Binaries/Win64/ArkAscendedServer.exe", "port": 7777, "rcon": "rcon",
            "rcon_port": 27020, "players": 10, "log": "ShooterGame/Saved/Logs/ShooterGame.log",
            "ready": r"has successfully started", "stop": ["SaveWorld", "DoExit"]},
    "valheim": {"name": "Valheim", "appid": "896660", "disk": "≈1.5 ГБ", "ram": "2–4 ГБ",
                "exe": "valheim_server.exe", "port": 2456, "rcon": None, "players": 10, "log": "server.log",
                "ready": r"Game server connected", "env": {"SteamAppId": "892970"}, "stop": []},
    "7dtd": {"name": "7 Days to Die", "appid": "294420", "disk": "≈15 ГБ", "ram": "8–12 ГБ",
             "exe": "7DaysToDieServer.exe", "port": 26900, "rcon": "telnet", "rcon_port": 8081, "players": 8,
             "log": "output_log.txt", "ready": r"StartGame done|GameServer\.LogOn successful",
             "ready_port": "rcon_port", "stop": ["saveworld", "shutdown"]},
    "satisfactory": {"name": "Satisfactory", "appid": "1690800", "disk": "≈8 ГБ", "ram": "12–16 ГБ",
                     "exe": "FactoryServer.exe", "port": 7777, "rcon": None, "rcon_port": 8888, "players": 4,
                     "log": "FactoryGame/Saved/Logs/FactoryGame.log", "ready": r"(?!)", "ready_port": "port",
                     "stop": []},
    "enshrouded": {"name": "Enshrouded", "appid": "2278520", "disk": "≈4 ГБ", "ram": "6–12 ГБ",
                   "exe": "enshrouded_server.exe", "port": 15637, "rcon": None, "players": 16,
                   "log": "logs/enshrouded_server.log", "ready": r"HostOnline' \(up\)", "stop": []},
    "zomboid": {"name": "Project Zomboid", "appid": "380870", "disk": "≈5 ГБ", "ram": "4–8 ГБ",
                "exe": "StartServer64.bat", "port": 16261, "rcon": "rcon", "rcon_port": 27015, "players": 16,
                "log": "", "ready": r"SERVER STARTED", "ready_port": "rcon_port", "stop": ["save", "quit"]},
}
for _g in STEAM_GAMES.values():                     # у кого есть RCON — готовность и по его порту
    if _g["rcon"] and "ready_port" not in _g:
        _g["ready_port"] = "rcon_port"
GIFT_GAMES = {"rust", "palworld", "ark", "zomboid", "7dtd"}   # для них работает «🔌 Подарки сюда»


async def telnet_command(host, port, password, cmd):
    """Простой Telnet для 7 Days to Die: пароль → команда → ответ за ~1.5 секунды."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), 5)

    async def read_for(sec):
        out, end = b"", time.time() + sec
        while time.time() < end:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), max(0.05, end - time.time()))
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            out += chunk
        return out.decode("utf-8", "replace")
    try:
        hello = await read_for(1.5)
        if "password" in hello.lower():
            writer.write((password + "\r\n").encode())
            await writer.drain()
            if "incorrect" in (await read_for(1.0)).lower():
                raise RuntimeError("Telnet не принял пароль")
        writer.write((cmd + "\r\n").encode())
        await writer.drain()
        text = await read_for(1.5)
        writer.write(b"exit\r\n")
        await writer.drain()
    finally:
        writer.close()
    skip = ("Logon successful", "Press 'help'", "*** ", "Connected with", "Please enter password")
    return "\n".join(l for l in text.replace("\r", "").splitlines()
                     if l.strip() and not any(x in l for x in skip))


class SteamMixin:
    # ── SteamCMD ──────────────────────────────────────────────────────────
    def _steamcmd_path(self):
        custom = str(self.cfg().get("steamcmd_path") or "").strip()
        if custom:
            return custom
        return os.path.join(self.base, "steamcmd", "steamcmd.exe" if WIN else "steamcmd.sh")

    async def _ensure_steamcmd(self, sid):
        path = self._steamcmd_path()
        if os.path.exists(path):
            return path
        self._push(sid, "Скачиваю SteamCMD (консольный Steam от Valve, ≈3 МБ)…")
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        tmp = os.path.join(folder, "steamcmd.zip")
        await self._download(str(self.cfg().get("steamcmd_url") or STEAMCMD_URL), tmp, lambda p: None)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(folder)
        os.remove(tmp)
        if not WIN:
            os.chmod(path, 0o755)
        if not os.path.exists(path):
            raise RuntimeError("SteamCMD скачался, но не распаковался")
        return path

    async def _steam_install(self, s, job=None):
        """Скачивание / обновление сервера игры. Прогресс — в карточке и консоли."""
        sid, g = s["id"], STEAM_GAMES[s["game"]]
        folder = self._folder(s)
        cmd = await self._ensure_steamcmd(sid)
        self._push(sid, f"── SteamCMD: {g['name']} ({g['disk']}) — первый раз может занять 10–40 минут ──")
        proc = await asyncio.create_subprocess_exec(
            cmd, "+force_install_dir", os.path.abspath(folder), "+login", "anonymous",
            "+app_update", g["appid"], "validate", "+quit",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **self._noconsole())
        self._rt(sid).update(proc=proc, status="installing")
        ok, err, last_pct = False, "", -10.0
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            text = raw.decode("utf-8", "replace").strip()
            if not text:
                continue
            m = re.search(r"progress: ([\d.]+)", text)
            if m:
                pct = float(m.group(1))
                if job is not None:
                    job["progress"] = round(pct / 100, 3)
                if pct - last_pct < 5 and "verifying" not in text:   # не засоряем консоль каждой сотой
                    continue
                last_pct = pct
            self._push(sid, text)
            if re.search(r"Success! App '\d+' (fully installed|already up to date)", text) or "already up to date" in text:
                ok = True
            if text.startswith("ERROR!"):
                err = text
        await proc.wait()
        self._rt(sid).update(proc=None, status="offline")
        if not ok:
            if "No subscription" in err:
                raise RuntimeError(f"Steam не дал скачать {g['name']} анонимно — этому серверу нужен "
                                   "аккаунт Steam, где куплена игра")
            if "Disk" in err or "disk" in err:
                raise RuntimeError(f"не хватает места на диске — серверу {g['name']} нужно {g['disk']}")
            raise RuntimeError(err or "SteamCMD завершился без «Success» — смотри консоль")
        self._steam_configure(s)
        s["installed"] = True
        self._save()
        self._push(sid, f"✓ {g['name']}: сервер установлен")

    def _steam_configure(self, s):
        """Настройки, которые игра читает из файлов: RCON/Telnet, порты, имя."""
        if s["game"] == "7dtd":
            return self._cfg_7dtd(s)
        if s["game"] == "zomboid":
            return self._cfg_zomboid(s)
        if s["game"] != "palworld":
            return
        folder = self._folder(s)
        default = os.path.join(folder, "DefaultPalWorldSettings.ini")
        line = ""
        if os.path.exists(default):
            m = re.search(r"OptionSettings=\(.*\)", open(default, encoding="utf-8", errors="replace").read())
            line = m.group(0) if m else ""
        if not line:
            line = "OptionSettings=()"
        g = STEAM_GAMES["palworld"]
        want = {"ServerName": f'"{s["name"]}"', "AdminPassword": f'"{s["rcon_password"]}"',
                "PublicPort": str(s["port"]), "RCONEnabled": "True", "RCONPort": str(s["rcon_port"]),
                "RESTAPIEnabled": "True", "RESTAPIPort": str(s.get("rest_port") or g["rest_port"]),
                "ServerPlayerMaxNum": str(s.get("players", g["players"]))}
        body = line[len("OptionSettings=("):-1]
        for k, v in want.items():
            if re.search(rf"(^|,){k}=", body):
                body = re.sub(rf"((?:^|,){k}=)(\"[^\"]*\"|[^,]*)", lambda m: m.group(1) + v, body)
            else:
                body = (body + "," if body else "") + f"{k}={v}"
        cfgdir = os.path.join(folder, "Pal", "Saved", "Config", "WindowsServer" if WIN else "LinuxServer")
        os.makedirs(cfgdir, exist_ok=True)
        with open(os.path.join(cfgdir, "PalWorldSettings.ini"), "w", encoding="utf-8") as f:
            f.write("[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(" + body + ")\n")

    def _cfg_7dtd(self, s):
        """Свой файл настроек (stream_config.xml) — обновление сервера его не перезапишет."""
        folder = self._folder(s)
        src = os.path.join(folder, "serverconfig.xml")
        xml = open(src, encoding="utf-8", errors="replace").read() if os.path.exists(src) else \
            '<?xml version="1.0"?>\n<ServerSettings>\n</ServerSettings>\n'
        want = {"ServerName": s["name"], "ServerPort": str(s["port"]), "ServerMaxPlayerCount": str(s.get("players", 8)),
                "TelnetEnabled": "true", "TelnetPort": str(s["rcon_port"]), "TelnetPassword": s["rcon_password"],
                "ServerVisibility": "0"}
        for k, v in want.items():
            pat = re.compile(rf'(<property\s+name="{k}"\s+value=")[^"]*(")')
            if pat.search(xml):
                xml = pat.sub(lambda m: m.group(1) + v.replace('"', "") + m.group(2), xml)
            else:
                xml = xml.replace("</ServerSettings>", f'\t<property name="{k}" value="{v}"/>\n</ServerSettings>')
        with open(os.path.join(folder, "stream_config.xml"), "w", encoding="utf-8") as f:
            f.write(xml)

    def _zomboid_name(self, s):
        return re.sub(r"[^A-Za-z0-9_]", "", s["id"].replace("-", "_")) or "stream"

    def _cfg_zomboid(self, s):
        """Project Zomboid читает <папка>/Zomboid/Server/<имя>.ini — заранее включаем RCON."""
        d = os.path.join(self._folder(s), "Zomboid", "Server")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, self._zomboid_name(s) + ".ini")
        text = open(path, encoding="utf-8", errors="replace").read() if os.path.exists(path) else ""
        want = {"DefaultPort": str(s["port"]), "RCONPort": str(s["rcon_port"]), "RCONPassword": s["rcon_password"],
                "PublicName": s["name"], "MaxPlayers": str(s.get("players", 16)), "Public": "false"}
        for k, v in want.items():
            if re.search(rf"^{k}=", text, re.M):
                text = re.sub(rf"^{k}=.*$", lambda m: f"{k}={v}", text, flags=re.M)
            else:
                text += ("" if not text or text.endswith("\n") else "\n") + f"{k}={v}\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _steam_args(self, s):
        g, folder = STEAM_GAMES[s["game"]], self._folder(s)
        exe = os.path.join(folder, *g["exe"].split("/"))
        p, rp, pw, players = s["port"], s["rcon_port"], s["rcon_password"], s.get("players", g["players"])
        if s["game"] == "rust":
            return [exe, "-batchmode", "-nographics", "+server.port", str(p), "+server.queryport", str(p + 2),
                    "+server.level", "Procedural Map", "+server.seed", str(s.get("seed") or 12345),
                    "+server.worldsize", str(s.get("worldsize") or 2000), "+server.maxplayers", str(players),
                    "+server.hostname", s["name"], "+server.identity", s["id"],
                    "+rcon.port", str(rp), "+rcon.password", pw, "+rcon.web", "1", "-logfile", "server.log"]
        if s["game"] == "palworld":
            return [exe, f"-port={p}", f"-players={players}", "-useperfthreads", "-NoAsyncLoadingThread",
                    "-UseMultithreadForDS"]
        if s["game"] == "ark":
            q = (f"TheIsland_WP?listen?SessionName={s['name']}?Port={p}?RCONEnabled=True"
                 f"?RCONPort={rp}?ServerAdminPassword={pw}")
            return [exe, q, f"-WinLiveMaxPlayers={players}", "-NoBattlEye", "-log"]
        if s["game"] == "valheim":
            return [exe, "-nographics", "-batchmode", "-name", s["name"], "-port", str(p),
                    "-world", s.get("world") or "Stream", "-password", s.get("password") or pw[:8],
                    "-public", "0", "-savedir", os.path.join(folder, "saves"), "-logFile", "server.log"]
        if s["game"] == "7dtd":
            return [exe, "-logfile", "output_log.txt", "-quit", "-batchmode", "-nographics",
                    "-configfile=stream_config.xml", "-dedicated"]
        if s["game"] == "satisfactory":                      # порты — обязательно ДО -log -unattended
            return [exe, f"-Port={p}", f"-ReliablePort={rp}", "-log", "-unattended"]
        if s["game"] == "enshrouded":
            return [exe]
        if s["game"] == "zomboid":
            args = [exe, "-servername", self._zomboid_name(s), "-adminpassword", pw,
                    "-cachedir=" + os.path.join(folder, "Zomboid")]
            return (["cmd", "/c"] + args) if WIN else args
        raise RuntimeError("неизвестная игра")

    async def _steam_start(self, s):
        sid, g = s["id"], STEAM_GAMES[s["game"]]
        r = self._rt(sid)
        if r["proc"] is not None:
            return {"ok": False, "error": "сервер уже запущен или устанавливается"}
        from servers import _port_busy
        if _port_busy(s["rcon_port"] if g["rcon"] else s["port"]):
            return {"ok": False, "error": "порт занят — уже работает другой сервер или игра"}
        if not s.get("installed"):
            return {"ok": False, "error": "сервер ещё не скачан"}
        self._steam_configure(s)                            # настройки могли поменяться — применяем перед запуском
        args = self._steam_args(s)
        exe = args[2] if args[:2] == ["cmd", "/c"] else args[0]
        if not os.path.exists(exe):
            return {"ok": False, "error": f"не найден {os.path.basename(exe)} — нажми «⬆ Обновить», чтобы докачать"}
        env = dict(os.environ, **g.get("env", {}))
        flags = {"creationflags": 0x08000000 | 0x00000200} if WIN else {}   # без окна + своя группа (для Ctrl+Break)
        logpath = os.path.join(self._folder(s), *g["log"].split("/")) if g["log"] else ""
        start_at = os.path.getsize(logpath) if logpath and os.path.exists(logpath) else 0
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=os.path.dirname(exe), env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **flags)
        except Exception as e:
            return {"ok": False, "error": f"не удалось запустить: {e}"}
        r.update(proc=proc, status="starting", players=set(), need_java=0)
        self._push(sid, f"── запуск {g['name']}: порт {s['port']}"
                        + (f", RCON {s['rcon_port']}" if g["rcon"] else "") + f" · нужно {g['ram']} ОЗУ ──")
        asyncio.ensure_future(self._steam_reader(s, proc))
        if g.get("ready_port"):
            asyncio.ensure_future(self._steam_ready_watch(s, proc, s[g["ready_port"]]))
        if logpath:
            asyncio.ensure_future(self._steam_tail(s, proc, logpath, start_at))
        return {"ok": True}

    def _steam_line(self, s, text):
        g, r = STEAM_GAMES[s["game"]], self._rt(s["id"])
        recent = r.setdefault("recent", {})
        if time.time() - recent.pop(text.strip(), 0) > 3:     # ту же строку только что показал ответ RCON
            self._push(s["id"], text)
        if r["status"] == "starting" and re.search(g["ready"], text):
            r["status"] = "online"
            self.log("СЕРВЕРЫ", f"«{s['name']}» ({g['name']}) запущен — порт {s['port']}")

    async def _steam_ready_watch(self, s, proc, port):
        """Готов, когда открылся порт — надёжнее, чем ждать строку в логе."""
        from servers import _port_busy
        r, g = self._rt(s["id"]), STEAM_GAMES[s["game"]]
        while proc.returncode is None and r["status"] == "starting":
            await asyncio.sleep(2)
            if r["status"] == "starting" and _port_busy(port):
                r["status"] = "online"
                self._push(s["id"], f"── {g['name']}: сервер отвечает на порту {port} ──")
                self.log("СЕРВЕРЫ", f"«{s['name']}» ({g['name']}) запущен — порт {s['port']}")

    async def _steam_reader(self, s, proc):
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            text = raw.decode("utf-8", "replace").rstrip()
            if text:
                self._steam_line(s, text)
        code = await proc.wait()
        self._rt(s["id"]).update(proc=None, status="offline", players=set())
        self._push(s["id"], f"── сервер остановлен (код {code}) ──")

    async def _steam_tail(self, s, proc, path, pos):
        """Игры, пишущие лог в файл: читаем его по мере роста."""
        buf = b""
        while proc.returncode is None:
            await asyncio.sleep(0.5)
            try:
                size = os.path.getsize(path)
                if size < pos:
                    pos = 0
                if size > pos:
                    with open(path, "rb") as f:
                        f.seek(pos)
                        buf += f.read(size - pos)
                    pos = size
                    *lines, buf = buf.split(b"\n")
                    for ln in lines:
                        t = ln.decode("utf-8", "replace").rstrip()
                        if t:
                            self._steam_line(s, t)
            except OSError:
                pass

    async def _telnet(self, port, password, cmd):
        return await telnet_command("127.0.0.1", port, password, cmd)

    async def _steam_rcon(self, s, cmd):
        g = STEAM_GAMES[s["game"]]
        if g["rcon"] == "telnet":
            return await self._telnet(s["rcon_port"], s["rcon_password"], cmd)
        if g["rcon"] == "webrcon":
            return await self.game_rcon("rust", cmd, "127.0.0.1", s["rcon_port"], s["rcon_password"])
        if g["rcon"] == "rcon":
            return await self.rcon_cmd(cmd, "127.0.0.1", s["rcon_port"], s["rcon_password"])
        raise RuntimeError(f"у {g['name']} нет консоли команд — только лог")

    async def _steam_command(self, s, cmd):
        r = self._rt(s["id"])
        if r["status"] not in ("online", "starting"):
            return {"ok": False, "error": "сервер не запущен"}
        self._push(s["id"], "> " + cmd)
        try:
            out = await self._steam_rcon(s, cmd)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        recent = r.setdefault("recent", {})
        for line in str(out or "").splitlines():
            if line.strip():
                self._push(s["id"], line)
                recent[line.strip()] = time.time()
        return {"ok": True}

    async def _steam_stop(self, s):
        r, g = self._rt(s["id"]), STEAM_GAMES[s["game"]]
        proc = r["proc"]
        if proc is None:
            return {"ok": False, "error": "сервер не запущен"}
        if r["status"] == "installing":
            proc.kill()
            self._push(s["id"], "── скачивание прервано — продолжится при следующем «⬆ Обновить» ──")
            return {"ok": True}
        r["status"] = "stopping"
        sent = False
        for c in g["stop"]:                                  # аккуратно: сохранить и выйти
            try:
                await self._steam_rcon(s, c)
                sent = True
            except Exception:
                break
        if not sent:
            try:
                if WIN:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)     # Valheim сохраняет мир по Ctrl+Break
                else:
                    proc.send_signal(signal.SIGINT)
            except Exception:
                pass

        async def ensure_dead():
            try:
                await asyncio.wait_for(proc.wait(), 60)
            except asyncio.TimeoutError:
                self._push(s["id"], "── сервер не остановился сам — завершаю принудительно ──")
                proc.kill()
        asyncio.ensure_future(ensure_dead())
        return {"ok": True}

    async def _steam_update(self, s):
        if self._rt(s["id"])["proc"] is not None:
            return {"ok": False, "error": "сначала останови сервер"}
        self.jobs[s["id"]] = {"state": "downloading", "progress": 0.0, "error": ""}

        async def run():
            try:
                await self._steam_install(s, self.jobs[s["id"]])
                self.jobs[s["id"]]["state"] = "done"
            except Exception as e:
                self.jobs[s["id"]].update(state="error", error=str(e))
                self._push(s["id"], f"✗ {e}")
        asyncio.ensure_future(run())
        return {"ok": True}

    def steam_new(self, d, used):
        """Новый сервер Steam-игры: порты, пароль RCON, параметры."""
        game = str(d.get("game"))
        g = STEAM_GAMES[game]
        port = int(d.get("port") or g["port"])
        rport = int(g.get("rcon_port") or port + 1)
        while rport in used or rport == port:
            rport += 1
        s = {"game": game, "name": str(d.get("name") or g["name"])[:40], "port": port, "rcon_port": rport,
             "rcon_password": secrets.token_urlsafe(12), "players": int(d.get("players") or g["players"]),
             "installed": False, "core_name": g["name"]}
        if game == "palworld":
            s["rest_port"] = g["rest_port"] if g["rest_port"] not in used else rport + 1
        if game == "rust":
            s["worldsize"] = max(1000, min(4500, int(d.get("worldsize") or 2000)))
            s["seed"] = int(d.get("seed") or secrets.randbelow(2_000_000))
        if game == "valheim":
            pw = str(d.get("password") or "").strip()
            if len(pw) < 5 or pw.lower() in s["name"].lower():
                pw = "vh" + secrets.token_hex(3)                # Valheim требует пароль от 5 символов
            s["password"], s["world"] = pw, re.sub(r"[^\w-]", "", str(d.get("world") or "Stream")) or "Stream"
        return s
