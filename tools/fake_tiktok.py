# -*- coding: utf-8 -*-
"""Поддельный TikTok для автопроверки (tools/smoke_test.py). Включается только в тестовом режиме:
TAKY_TEST=1 и TAKY_FAKE_TIKTOK=1. Ведёт себя как TikTokLive 7: connect() держит соединение, пока его
не закроют, disconnect() может «зависнуть» — как настоящий TikTok, который не отвечает на «пока».

Поведение задаётся ником:
  fake_ok     — подключается, отключается сразу
  fake_slow   — TikTok не отвечает на «пока» (disconnect висит) — программа должна отменить сама
  fake_stuck  — поток намертво занят (ничего не отменить) — программа должна бросить старое подключение
  fake_drop   — через секунду связь рвётся с ошибкой
  fake_off    — эфир не идёт
"""
import asyncio
import time

from pyee.asyncio import AsyncIOEventEmitter

from TikTokLive.events import ConnectEvent, DisconnectEvent

GIFTS_EN = {"9947": "Friendship Necklace", "5655": "Rose", "7777": "Test Dragon"}
GIFTS_RU = {"9947": "Кулон дружбы", "5655": "Роза", "7777": "Тестовый дракон"}


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _Web:
    """Список подарков: по-русски — только при webcast_language=ru-RU (так ведёт себя настоящий TikTok)."""
    def __init__(self):
        self.calls = []

    async def get(self, url="", extra_params=None, extra_headers=None, **kw):
        p = dict(extra_params or {})
        self.calls.append(p)
        names = GIFTS_RU if p.get("webcast_language") == "ru-RU" else GIFTS_EN
        return _Resp({"data": {"gifts": [{"id": int(i), "name": n, "diamond_count": 1,
                                          "image": {"url_list": []}} for i, n in names.items()]}})

    async def close(self):
        pass


class FakeTikTokClient(AsyncIOEventEmitter):
    def __init__(self, unique_id=""):
        super().__init__()
        self.unique_id = str(unique_id).lstrip("@")
        self.room_id = 424242
        self.web = self._web = _Web()
        self._closed = None
        self._task = None

    def on(self, event, f=None):                       # как в TikTokLive: событие задаётся классом
        return super().on(event.get_type() if hasattr(event, "get_type") else event, f)

    async def _run(self):
        mode = self.unique_id
        await asyncio.sleep(0.2)
        if mode == "fake_off":
            raise RuntimeError("The requested user is offline")
        self.emit(ConnectEvent.get_type(), ConnectEvent(unique_id=self.unique_id, room_id=self.room_id))
        if mode == "fake_drop":
            await asyncio.sleep(1)
            raise ConnectionError("no close frame received or sent")
        if mode == "fake_stuck":
            await asyncio.sleep(1.5)
            time.sleep(25)                             # поток занят намертво
        while not self._closed.is_set():
            await asyncio.sleep(0.05)
        if mode != "fake_slow":
            self.emit(DisconnectEvent.get_type(), DisconnectEvent())

    async def connect(self, *a, **kw):
        self._closed = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(self._run())
        try:
            await self._task
        except asyncio.CancelledError:                 # настоящая библиотека здесь падает именно так
            raise RuntimeError("This event loop is already running")

    async def disconnect(self, close_client=False):
        if self.unique_id == "fake_slow":
            await asyncio.sleep(60)                    # TikTok молчит
        if self._closed is not None:
            self._closed.set()
        if self._task is not None:
            try:
                await self._task
            except Exception:
                pass
