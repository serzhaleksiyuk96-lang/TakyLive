"""📱 Пульт с телефона: отдельный маленький сервер в домашней сети.

Основная программа слушает только этот компьютер (127.0.0.1:8765) — так и остаётся.
Пульт поднимается отдельно на порту 8766 для всей домашней сети, но пускает только
по секретной ссылке /r/<ключ>/ и умеет немногое: кнопки панели, озвучка, таймер,
случайное событие и лента событий. Ни настроек, ни ключей, ни нажатий клавиш по
произвольной команде через пульт не достать.
"""
import os
import re
import secrets
import socket

from aiohttp import web

DEFAULT_PORT = 8766


def lan_ips():
    """Адреса этого компьютера в домашней сети — основной первым."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))                 # пакет не уходит — так ОС называет основной адрес
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.append(info[4][0])
    except OSError:
        pass
    seen, res = set(), []
    for ip in out:
        if ip in seen or ip.startswith(("127.", "169.254.", "0.")):
            continue
        seen.add(ip)
        res.append(ip)
    private = [ip for ip in res if ip.startswith(("192.168.", "10.")) or
               (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)]
    return private + [ip for ip in res if ip not in private]


def qr_svg(text):
    try:
        import segno
    except ImportError:
        return ""
    svg = segno.make(text, error="m").svg_inline(scale=6, border=2, dark="#0a0c13", light="#ffffff")
    # viewBox — чтобы QR-код растягивался под размер блока, а не обрезался
    return re.sub(r'<svg width="(\d+)" height="(\d+)"', r'<svg viewBox="0 0 \1 \2" width="\1" height="\2"', svg, count=1)


class Remote:
    def __init__(self, web_dir, log, cfg, save_cfg, routes):
        """routes — {имя: обработчик aiohttp} из основной программы, доступные пульту."""
        self.web_dir, self.log, self.cfg, self.save_cfg = web_dir, log, cfg, save_cfg
        self.routes = routes
        self.runner = None
        self.error = ""

    def token(self):
        t = str(self.cfg().get("remote_token") or "")
        if len(t) < 12:
            t = secrets.token_urlsafe(12)
            self.cfg()["remote_token"] = t
            self.save_cfg()
        return t

    def port(self):
        try:
            return int(self.cfg().get("remote_port") or DEFAULT_PORT)
        except (TypeError, ValueError):
            return DEFAULT_PORT

    def urls(self):
        return [f"http://{ip}:{self.port()}/r/{self.token()}/" for ip in lan_ips()]

    # ── сервер ──
    def _app(self):
        app = web.Application()

        @web.middleware
        async def guard(request, handler):
            parts = request.path.split("/")
            if len(parts) < 3 or parts[1] != "r" or not secrets.compare_digest(parts[2], self.token()):
                return web.Response(status=404, text="Пульт TakyLive: ссылка устарела — открой новую по QR-коду в программе")
            resp = await handler(request)
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Referrer-Policy"] = "no-referrer"
            return resp

        async def page(request):
            with open(os.path.join(self.web_dir, "remote.html"), encoding="utf-8") as f:
                return web.Response(text=f.read(), content_type="text/html", charset="utf-8")

        async def slash(request):
            raise web.HTTPFound(f"/r/{request.match_info['tok']}/")

        app.middlewares.append(guard)
        app.router.add_get("/r/{tok}/", page)
        app.router.add_get("/r/{tok}", slash)
        for name, (method, handler) in self.routes.items():
            app.router.add_route(method, "/r/{tok}/api/" + name, handler)
        return app

    async def start(self):
        if self.runner:
            return True
        self.error = ""
        runner = web.AppRunner(self._app(), access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, "0.0.0.0", self.port()).start()
        except OSError as e:
            await runner.cleanup()
            self.error = f"порт {self.port()} занят другой программой" if getattr(e, "errno", 0) in (98, 10048) \
                else f"не удалось открыть пульт: {e}"
            self.log("ОШИБКА", "пульт с телефона: " + self.error)
            return False
        self.runner = runner
        self.log("ПУЛЬТ", f"Пульт с телефона включён: порт {self.port()}")
        return True

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            self.log("ПУЛЬТ", "Пульт с телефона выключен")

    async def restart(self):
        await self.stop()
        return await self.start()

    def status(self):
        urls = self.urls() if self.runner else []
        return {"on": bool(self.cfg().get("remote_on")), "running": bool(self.runner), "error": self.error,
                "urls": urls, "port": self.port(), "qr": qr_svg(urls[0]) if urls else ""}
