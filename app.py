#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TakyLive — подарки TikTok управляют игрой
=========================
Программа-мост: ловит события TikTok Live (подарки, лайки, подписки, фолловы)
и выполняет цепочки команд на Minecraft-сервере через ServerTap (HTTP).

Запуск:  двойной клик по start.bat  (или: python app.py)
Затем открой в браузере:  http://localhost:8765

Автор: сделано для TakymiVG
"""

import asyncio
import io
import json
import os
import re
import shutil
import urllib.parse
import sys
import struct
import threading
import time
import zipfile
from datetime import datetime

for _s in (sys.stdout, sys.stderr):        # иначе в .exe с выводом в файл падает на «→» (cp1251)
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Автоустановка библиотек ──────────────────────────────────────────────────
# При запуске программа сама проверяет и ставит всё что нужно.
def _ensure_deps():
    if getattr(sys, "frozen", False):
        return  # в exe все библиотеки уже вшиты
    import importlib
    import subprocess
    checks = (
        ("aiohttp", "aiohttp"),        # веб-сервер
        ("TikTokLive", "TikTokLive"),  # события TikTok Live
        ("edge_tts", "edge-tts"),      # озвучка чата (нейроголоса)
        ("imageio_ffmpeg", "imageio-ffmpeg"),  # ffmpeg — чинит видео из Telegram, iPhone и т.п.
    )
    need = []
    for module, package in checks:
        try:
            importlib.import_module(module)
        except ImportError:
            need.append(package)
    # минимальные версии: старые перестают работать после изменений на стороне сервисов
    min_versions = {"edge-tts": (7, 3, 1)}
    try:
        from importlib.metadata import version as _ver
        for package, minimum in min_versions.items():
            if package in need:
                continue
            try:
                cur = tuple(int(x) for x in re.findall(r"\d+", _ver(package))[:3])
            except Exception:
                continue
            if cur < minimum:
                need.append(package + ">=" + ".".join(map(str, minimum)))
    except Exception:
        pass
    if not need:
        return
    print("=" * 60)
    print("  Устанавливаю или обновляю библиотеки...")
    print("  " + ", ".join(need))
    print("  (нужен интернет, обычно занимает меньше минуты)")
    print("=" * 60)
    for package in need:
        try:
            subprocess.call([sys.executable, "-m", "pip", "install", "-U", package])
        except Exception as e:
            print(f"  Не удалось установить {package}: {e}")
    print("=" * 60)
    print("  Установка завершена, запускаюсь...")
    print("=" * 60)


_ensure_deps()

# ── Проверка зависимостей ────────────────────────────────────────────────────
MISSING = []
try:
    from aiohttp import web
except ImportError:
    MISSING.append("aiohttp")
try:
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import (
        ConnectEvent, DisconnectEvent, GiftEvent, LikeEvent
    )
    try:
        from TikTokLive.events import CommentEvent
    except ImportError:
        CommentEvent = None
    # Эти события в некоторых версиях называются иначе — импортируем безопасно
    try:
        from TikTokLive.events import SubscribeEvent
    except ImportError:
        SubscribeEvent = None
    try:
        from TikTokLive.events import FollowEvent
    except ImportError:
        FollowEvent = None
    try:
        from TikTokLive.events import ShareEvent
    except ImportError:
        ShareEvent = None
except ImportError:
    MISSING.append("TikTokLive")
# RCON реализован через встроенный socket — доп. библиотека не нужна

if MISSING:
    print("=" * 60)
    print("  НЕ ХВАТАЕТ БИБЛИОТЕК! Установи их командой:")
    print()
    print("  pip install " + " ".join(MISSING))
    print("=" * 60)
    input("\nНажми Enter чтобы закрыть...")
    sys.exit(1)


# ── Пути к файлам конфигурации ───────────────────────────────────────────────
# В собранном exe (PyInstaller) рабочие папки лежат рядом с exe-файлом
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PROFILES_PATH = os.path.join(BASE_DIR, "profiles.json")
WEB_DIR = os.path.join(BASE_DIR, "web")
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(os.path.join(MEDIA_DIR, "tts"), exist_ok=True)
os.makedirs(os.path.join(MEDIA_DIR, "gifts"), exist_ok=True)
MODS_DIR = os.path.join(BASE_DIR, "mods")            # моды для игр (GTA 5 и др.)
os.makedirs(MODS_DIR, exist_ok=True)
MOD_FOLDERS = {"gta5": "GTA5"}

# Ссылки на официальные иконки подарков (CDN TikTok). Картинки не хранятся
# у нас — браузер грузит их напрямую с серверов TikTok, как в других тулзах.
GIFT_ICON_URLS = {}
try:
    with open(os.path.join(BASE_DIR, "gift_icons.json"), encoding="utf-8") as _f:
        GIFT_ICON_URLS = {k.lower(): v for k, v in json.load(_f).items()}
except Exception:
    GIFT_ICON_URLS = {}

# ID подарков (одинаковые на любом языке) — подставляются при выборе из библиотеки
GIFT_IDS = {}
try:
    with open(os.path.join(BASE_DIR, "gift_ids.json"), encoding="utf-8") as _f:
        GIFT_IDS = {k.lower(): str(v) for k, v in json.load(_f).items()}
except Exception:
    GIFT_IDS = {}

# Иконки, пойманные в живых эфирах (подарки, которых нет в справочнике)
LIVE_ICONS_PATH = os.path.join(BASE_DIR, "gift_icons_live.json")


GIFT_RU_FILE = os.path.join(BASE_DIR, "gift_names_ru.json")


def load_gift_names_ru():
    """Русские названия подарков {ID: название}. Пополняется при каждом подключении к эфиру."""
    try:
        with open(GIFT_RU_FILE, encoding="utf-8") as f:
            return {str(k): str(v) for k, v in json.load(f).items() if str(v).strip()}
    except Exception:
        return {}


def save_gift_names_ru():
    try:
        with open(GIFT_RU_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE.gift_names_ru, f, ensure_ascii=False, indent=0, sort_keys=True)
    except Exception as e:
        STATE.log("ОШИБКА", f"не сохранил русские названия подарков: {e}")


def norm_gift(name):
    """Сравнение названий без разницы в регистре, ё/е и лишних пробелах."""
    return " ".join(str(name or "").lower().replace("ё", "е").split())


def _walk_gifts(obj, out):
    """Находит в ответе TikTok все записи подарков (есть id, name и цена или картинка)."""
    if isinstance(obj, dict):
        if "id" in obj and isinstance(obj.get("name"), str) and ("diamond_count" in obj or "image" in obj):
            out[str(obj["id"])] = obj["name"].strip()
        for v in obj.values():
            _walk_gifts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_gifts(v, out)


async def fetch_room_gift_catalog(client):
    """Весь список подарков региона эфира — с ID и официальными картинками — в каталог."""
    try:
        from TikTokLive.client.web.web_settings import WebDefaults
        import giftcatalog as _gc
        params = {"app_language": "en", "webcast_language": "en"}
        room = getattr(client, "room_id", None)
        if room:
            params["room_id"] = str(room)
        r = await client.web.get(url=WebDefaults.tiktok_webcast_url + "/gift/list/", extra_params=params)
        found = {}
        _gc.walk_gifts(r.json().get("data") or {}, found)
        if found:
            new, total = STATE.gift_catalog.merge(found, "эфир")
            STATE.log("ПОДАРКИ", f"Подарки этого эфира: {total}, новых в каталоге — {new}")
    except Exception as e:
        STATE.log("ПОДАРКИ", f"не удалось скачать список подарков эфира: {e}")


async def fetch_ru_gift_names(client):
    """Спрашивает у TikTok список подарков на русском — тогда русские названия
    в карточках («Корги») срабатывают на английские из эфира («Corgi»)."""
    try:
        from TikTokLive.client.web.web_settings import WebDefaults
        params = {"app_language": "ru-RU", "browser_language": "ru-RU", "webcast_language": "ru", "language": "ru"}
        room = getattr(client, "room_id", None)
        if room:
            params["room_id"] = str(room)
        r = await client.web.get(url=WebDefaults.tiktok_webcast_url + "/gift/list/", extra_params=params)
        data = r.json().get("data") or {}
    except Exception as e:
        STATE.log("ПОДАРКИ", f"не удалось скачать русские названия подарков: {e}")
        return 0
    found = {}
    _walk_gifts(data, found)
    ru = {k: v for k, v in found.items() if re.search(r"[а-яё]", v, re.I)}
    if not ru:
        STATE.log("ПОДАРКИ", f"TikTok отдал список подарков ({len(found)} шт.), но не по-русски")
        return 0
    new = sum(1 for k, v in ru.items() if STATE.gift_names_ru.get(k) != v)
    STATE.gift_names_ru.update(ru)
    save_gift_names_ru()
    STATE.log("ПОДАРКИ", f"Русские названия подарков: {len(ru)} (новых {new}) — русские карточки теперь срабатывают")
    return len(ru)


# ── Картинки ccLeaf Vault (ccvaults.com): скачиваются при выборе и хранятся в media/vault ──
VAULT_BASE = "https://ccvaults.com"
import mimetypes as _mt
_mt.add_type("image/webp", ".webp")           # на некоторых Windows .webp не зарегистрирован
_VAULT = {"paths": None}


def vault_paths():
    if _VAULT["paths"] is None:
        try:
            with open(os.path.join(BASE_DIR, "vault_index.json"), encoding="utf-8") as f:
                cats = json.load(f).get("categories", {})
            _VAULT["paths"] = {p for c in cats.values() for p in c.get("paths", [])}
        except Exception:
            _VAULT["paths"] = set()
    return _VAULT["paths"]


async def h_vault_index(request):
    try:
        return web.FileResponse(os.path.join(BASE_DIR, "vault_index.json"))
    except Exception:
        return web.json_response({"categories": {}})


async def h_vault_media(request):
    """/media/vault/<путь>: есть у нас — отдаём; нет — один раз качаем с ccvaults.com."""
    tail = request.match_info["tail"]
    if ".." in tail or tail.startswith(("/", "\\")):
        return web.Response(status=400)
    local = os.path.join(MEDIA_DIR, "vault", *tail.split("/"))
    if not os.path.exists(local):
        if tail not in vault_paths():
            return web.Response(status=404, text="нет такой картинки в ccLeaf Vault")
        base = str(STATE.config.get("vault_base") or VAULT_BASE).rstrip("/")
        url = f"{base}/assets/" + urllib.parse.quote(tail, safe="/$")
        try:
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),
                                             headers={"User-Agent": f"TakyLive/{APP_VERSION}"}) as cs:
                async with cs.get(url) as r:
                    if r.status != 200:
                        return web.Response(status=502, text=f"ccvaults.com ответил {r.status}")
                    data = await r.read()
        except Exception as e:
            return web.Response(status=502, text=f"не удалось скачать: {e}")
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as f:
            f.write(data)
        STATE.log("КАРТИНКИ", f"Скачал из ccLeaf Vault: {tail.rsplit('/', 1)[-1]}")
    return web.FileResponse(local, headers={"Cache-Control": "max-age=86400"})


def load_live_icons():
    try:
        with open(LIVE_ICONS_PATH, encoding="utf-8") as f:
            return {k.lower(): v for k, v in json.load(f).items()}
    except Exception:
        return {}


def save_live_icons():
    try:
        with open(LIVE_ICONS_PATH, "w", encoding="utf-8") as f:
            json.dump(STATE.live_gift_icons, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


# ── Глобальное состояние ─────────────────────────────────────────────────────
class State:
    def __init__(self):
        self.config = {
            "tiktok_username": "",
            "servertap_host": "127.0.0.1",    # IP сервера
            "servertap_port": 4567,           # HTTP-порт ServerTap
            "servertap_key": "",              # ключ (config.yml → key)
            "use_tls": False,                 # https если TLS включён
            "mc_transport": "servertap",      # как слать команды: servertap | rcon
            "rcon_port": 25575,               # порт RCON (server.properties → rcon.port)
            "rcon_password": "",              # server.properties → rcon.password
            "ark_host": "", "ark_port": 27020, "ark_password": "", "ark_player": "",
            "rust_host": "", "rust_port": 28016, "rust_password": "", "rust_player": "",
            "palworld_host": "", "palworld_port": 25575, "palworld_password": "",
            "palworld_rest_port": 8212,
            "zomboid_host": "", "zomboid_port": 27015, "zomboid_password": "", "zomboid_player": "",
            "7dtd_host": "", "7dtd_port": 8081, "7dtd_password": "", "7dtd_player": "",
            "cs2_sensitivity": 2.0,           # чувствительность мыши в CS2 — для поворотов
            "tts_enabled": False,             # озвучка чата
            "tts_voice": "ru-RU-DmitryNeural",
            "tts_volume": 100,
            "tts_read_name": True,            # читать имя перед сообщением
            "tts_filter_mode": "all",         # all|list|gifters|likers|followers
            "tts_filter_list": "",            # ники через запятую (режим list)
            "tts_filter_coins": 1,            # мин. монет (режим gifters)
            "tts_filter_likes": 100,          # мин. лайков (режим likers)
            "tts_play_local": True,           # играть озвучку в окне программы
            "tts_guard": True,                # защита озвучки от спама и мата
            "tts_profanity": "beep",          # beep — заменить на «пип», skip — не читать, off — читать как есть
            "tts_bad_words": "",              # свои запрещённые слова через запятую
            "tts_skip_junk": True,            # растяжки, одни смайлы, ссылки
            "tts_user_cooldown": 8,           # секунд между сообщениями одного зрителя
            "tts_skip_dupes": True,           # одинаковые сообщения подряд
            "tts_max_queue": 5,               # больше в очереди — новые пропускаем
            "tts_block_list": "",             # ники, которых не озвучивать никогда
            "voice_cmds_on": True,            # зрители выбирают голос командой в чате
            "voice_cmds": [{"cmd": "!девочка", "label": "Девочка", "voice": "ru-RU-SvetlanaNeural"},
                           {"cmd": "!мальчик", "label": "Мальчик", "voice": "ru-RU-DmitryNeural"}],
            "voice_reset_cmd": "!сброс",       # вернуть обычный голос
            "voice_cmd_confirm": True,        # сказать зрителю, что голос сменился
            "role_voices": {"moderator": "", "superfan": "", "friend": "", "gifter": "", "follower": ""},
            "fish_api_key": "",               # ключ Fish Audio (fish.audio/app/api-keys)
            "fish_model": "s2.1-pro-free",    # модель Fish: бесплатная или платная
            "fish_voice_title": "",           # название выбранного голоса (для показа)
            "fish_base": "https://api.fish.audio",
            "timer_start_min": 30,            # таймер: стартовые минуты
            "timer_sec_per_coin": 5,          # таймер: +секунд за 1 монету подарка
            "timer_end_command": "",          # команда при истечении таймера
            "random_enabled": False,          # случайные события
            "random_interval_sec": 300,       # раз в сколько секунд
            "random_commands": "",            # (устарело) команды строками
            "random_items": [],               # события: [{command, media_file, media_kind, sound_file}]
            "random_on_gift": False,          # также срабатывать при любом подарке
            "showcase_anim": "grid",          # auto|none|scroll|grid|marquee
            "showcase_trans_grid": "pulse",   # fade|pulse|wave|flip|zoom|domino
            "showcase_trans_list": "scroll",  # scroll|step|up|glow|side|breathe
            "showcase_speed": 5,              # секунд на карточку / страницу
            "showcase_per_row": 7,            # карточек в ряд (режим grid)
            "showcase_rows": 3,               # максимум рядов (режим grid)
            "showcase_icon": 88,              # размер картинки подарка, px
            "showcase_transition": "pulse",   # fade|pulse|wave|slide|flip|zoom
            "showcase_badge": "br",           # br|bl|tr|tl|none — угол значка подарка
            "showcase_badge_size": 38,        # размер значка, % от картинки
            "showcase_types": ["gifts", "likes", "subs", "follows", "chatcmds"],
            "gift_icons_online": True,        # брать иконки подарков с серверов TikTok
            "minecraft_nick": "",
            "active_profile": "default",
        }
        # profiles = { "Выживание": {gifts:[], likes:[], subs:[], follows:[]}, ... }
        self.profiles = {}
        self.connected = False        # подключён ли TikTok
        self.tiktok_client = None
        self.tiktok_thread = None
        self.like_counter = 0         # накопитель лайков для порогов
        self.event_log = []           # последние события (для UI)
        self.loop = None
        self.stop_requested = False   # нажали «Отключиться» — события эфира больше не обрабатываем
        self.nick_warned = False
        self.gift_names_ru = {}       # {ID подарка: русское название}
        self.tts_epoch = 0            # «⏹ Остановить» — всё, что было до, не играем
        self.tts_skip = 0             # «⏭ Пропустить» — только текущее
        self.tts_pending = 0          # сколько сообщений сейчас генерируется
        self.tts_user_last = {}       # зритель → время последней озвучки
        self.tts_recent = []          # (время, зритель, текст) — для поиска повторов
        self.tts_guard_stats = {}     # причина → сколько отфильтровано
        self.viewer_voices = {}       # аккаунт → {nick, voice, label, …}
        self.media_meta_busy = False  # идёт ли фоновое создание превью
        self.recent_viewers = {}      # кто писал в чат — для выбора «особенных» зрителей
        self.web_loop = None          # event loop веб-сервера (для теста без TikTok)
        # ── Данные для оверлеев OBS ──
        self.overlay_events = []      # очередь алертов для popup-оверлея
        self.overlay_seq = 0          # счётчик событий (для отслеживания новых)
        self.recent_feed = []         # лента последних событий
        self.gifters = {}             # {user: total_diamonds} для топа
        self.total_likes = 0          # всего лайков за стрим
        self.seen_gifts = {}          # {name: {"id": ..., "count": N, "diamonds": D}}
        self.media_queue = []         # очередь медиа-алертов для media.html
        self.media_seq = 0            # счётчик медиа-событий
        self.seen_users = set()       # кто уже писал в чат (для первого сообщения)
        self.likers = {}              # {user: total_likes} для топа по лайкам
        self.tts_queue = []           # очередь озвучки для tts.html
        self.followers = set()        # кто зафолловил/подписался за стрим (lowercase)
        self.connected_at = 0.0       # время подключения к TikTok (для пропуска истории чата)
        self.follow_count = 0         # фолловов за стрим
        self.sub_count = 0            # подписок за стрим
        self.gifts_count = 0          # подарков за стрим
        self.goals_done = set()       # достигнутые цели: (профиль, индекс)
        self.cmd_last = {}            # кулдауны чат-команд: {(профиль, триггер): время}
        self.timer = {"running": False, "end": 0.0, "paused_left": 0.0, "fired": False}
        self.random_last = 0.0        # время последнего случайного события
        self.stream_started = datetime.now().strftime("%d.%m.%Y %H:%M")
        self.tts_seq = 0
        self.tts_last_error = ""
        self.last_gift = {"name": "", "seq": 0}   # для подсветки в витрине подарков
        self.live_gift_icons = {}     # {имя_подарка: ссылка} — из событий эфира (см. load_live_icons)
        self.last_uid = {}            # {красивое_имя: @юзернейм} — для {uniqueid}
        self.mod_queue = {}           # {игра: [{id, cmd, user}]} — команды для модов игр
        self.mod_seq = 0
        self.mod_seen = {}            # {игра: время последнего запроса мода}

    def register_seen_gift(self, name, gift_id, diamonds=0):
        """Запоминает уникальный подарок (название+ID) для каталога."""
        key = str(name)
        if key not in self.seen_gifts:
            self.seen_gifts[key] = {"id": str(gift_id or ""), "count": 0, "diamonds": diamonds}
        self.seen_gifts[key]["count"] += 1
        if gift_id and not self.seen_gifts[key]["id"]:
            self.seen_gifts[key]["id"] = str(gift_id)

    def push_overlay(self, etype, user, text, icon="🎁", color="#00d4ff", amount=0, media=None):
        """Добавляет событие в оверлеи (алерт + лента + топ + медиа).

        media = {"file": "имя_файла", "kind": "video|image|gif",
                 "sound": "звук.mp3", "volume": 100, "sound_volume": 100} или None
        """
        self.overlay_seq += 1
        ev = {
            "seq": self.overlay_seq, "type": etype, "user": user,
            "text": text, "icon": icon, "color": color, "amount": amount,
            "time": datetime.now().strftime("%H:%M:%S"),
            "media": media,
        }
        self.overlay_events.append(ev)
        if len(self.overlay_events) > 50:
            self.overlay_events = self.overlay_events[-50:]
        self.recent_feed.insert(0, ev)
        if len(self.recent_feed) > 30:
            self.recent_feed = self.recent_feed[:30]
        # Отдельная очередь медиа-алертов (для media.html оверлея).
        # Пропускаем и «только звук» — оверлей проиграет его без картинки.
        if media and (media.get("file") or media.get("sound")):
            self.media_seq += 1
            self.media_queue.append({
                "seq": self.media_seq, "user": user, "text": text,
                "media": media, "time": ev["time"],
            })
            if len(self.media_queue) > 30:
                self.media_queue = self.media_queue[-30:]
        # Копим донат в топ (по алмазам/монетам)
        if etype == "gift" and amount > 0:
            self.gifters[user] = self.gifters.get(user, 0) + amount

    def log(self, kind, text):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "kind": kind,
            "text": text,
        }
        self.event_log.append(entry)
        if len(self.event_log) > 200:
            self.event_log = self.event_log[-200:]
        print(f"[{entry['time']}] {kind}: {text}")


STATE = State()


# ── Загрузка / сохранение конфигов ───────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                STATE.config.update(json.load(f))
        except Exception as e:
            print("Ошибка чтения config.json:", e)
    if os.path.exists(PROFILES_PATH):
        try:
            with open(PROFILES_PATH, "r", encoding="utf-8") as f:
                STATE.profiles = json.load(f)
        except Exception as e:
            print("Ошибка чтения profiles.json:", e)
    # Вкладки создаются на стартовом экране. Пустую «Алмазный стрим», которую раньше
    # программа создавала сама при первом запуске, убираем; вкладку с событиями не трогаем.
    auto = STATE.profiles.get("Алмазный стрим")
    if isinstance(auto, dict) and not any(auto.get(k) for k in
                                          ("gifts", "likes", "subs", "follows", "welcome", "chatcmds", "goals", "panel")):
        del STATE.profiles["Алмазный стрим"]
    if STATE.config.get("active_profile") not in STATE.profiles:
        STATE.config["active_profile"] = next(iter(STATE.profiles), "")


def bootstrap_fish_key():
    """Если ключа Fish Audio в настройках нет — берём его из fish_key.txt рядом с программой."""
    if str(STATE.config.get("fish_api_key") or "").strip():
        return
    path = os.path.join(BASE_DIR, "fish_key.txt")
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
    except OSError:
        return
    if key and not key.startswith("#"):
        STATE.config["fish_api_key"] = key
        save_config()
        print("  Ключ Fish Audio подхвачен из fish_key.txt")


def save_config():
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(STATE.config, f, ensure_ascii=False, indent=2)


def save_profiles():
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(STATE.profiles, f, ensure_ascii=False, indent=2)


# ── ServerTap: отправка команды на сервер через HTTP ─────────────────────────
def _servertap_base():
    cfg = STATE.config
    scheme = "https" if cfg.get("use_tls") else "http"
    host = cfg.get("servertap_host", "127.0.0.1")
    port = int(cfg.get("servertap_port", 4567))
    return f"{scheme}://{host}:{port}"


async def rcon_send(command):
    """Отправляет команду на сервер выбранным способом: ServerTap или RCON."""
    if STATE.config.get("mc_transport") == "rcon":
        try:
            await RCON.command(command)
            return True
        except Exception as e:
            STATE.log("ОШИБКА RCON", f"{e} (команда: {command})")
            return False
    return await _servertap_send(command)


async def _servertap_send(command):
    """Выполняет команду через ServerTap REST API (POST /v1/server/exec, заголовок key)."""
    import aiohttp
    cfg = STATE.config
    url = f"{_servertap_base()}/v1/server/exec"
    headers = {}
    if cfg.get("servertap_key"):
        headers["key"] = cfg["servertap_key"]
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data={"command": command},
                                    headers=headers, ssl=False) as resp:
                if resp.status in (200, 201, 204):
                    return True
                text = await resp.text()
                STATE.log("ОШИБКА ServerTap",
                          f"HTTP {resp.status}: {text[:100]} (команда: {command})")
                return False
    except Exception as e:
        STATE.log("ОШИБКА ServerTap", f"{e} (команда: {command})")
        return False


# ── RCON: стандартный протокол Minecraft (TCP, пакеты Source RCON) ───────────
class _RconClient:
    """Постоянное подключение по RCON. Переподключается сам, если связь оборвалась."""
    AUTH, EXEC, AUTH_RESPONSE = 3, 2, 2

    def __init__(self):
        self.reader = self.writer = None
        self.key = None
        self.req = 0
        self.lock = None

    async def _close(self):
        if self.writer is not None:
            try:
                self.writer.close()
            except Exception:
                pass
        self.reader = self.writer = None
        self.key = None

    async def _send(self, typ, payload):
        data = str(payload).encode("utf-8")
        if len(data) > 1440:
            raise ValueError("команда слишком длинная для RCON (больше 1440 байт)")
        self.req = (self.req % 2_000_000_000) + 1
        pkt = struct.pack("<ii", self.req, typ) + data + b"\x00\x00"
        self.writer.write(struct.pack("<i", len(pkt)) + pkt)
        await self.writer.drain()
        return self.req

    async def _read(self):
        hdr = await asyncio.wait_for(self.reader.readexactly(4), 6)
        (ln,) = struct.unpack("<i", hdr)
        if ln < 10 or ln > 1 << 20:
            raise ConnectionError("битый пакет RCON")
        body = await asyncio.wait_for(self.reader.readexactly(ln), 6)
        rid, typ = struct.unpack("<ii", body[:8])
        return rid, typ, body[8:-2].decode("utf-8", "replace")

    async def _open(self, host, port, password):
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), 6)
        rid_sent = await self._send(self.AUTH, password)
        for _ in range(5):                       # некоторые серверы шлют пустой пакет до ответа
            rid, typ, _ = await self._read()
            if typ == self.AUTH_RESPONSE:
                if rid == -1:
                    raise PermissionError("неверный пароль RCON")
                if rid == rid_sent:
                    return
        raise ConnectionError("сервер не ответил на авторизацию RCON")

    async def command(self, cmd, host=None, port=None, pw=None):
        if self.lock is None:
            self.lock = asyncio.Lock()
        cfg = STATE.config
        if host is None:                        # по умолчанию — сервер Minecraft
            host = str(cfg.get("servertap_host") or "127.0.0.1").strip()
            port = int(cfg.get("rcon_port") or 25575)
            pw = str(cfg.get("rcon_password") or "")
        key = (host, port, pw)
        async with self.lock:
            for attempt in (1, 2):
                try:
                    if self.writer is None or self.key != key:
                        await self._close()
                        await self._open(host, port, pw)
                        self.key = key
                    rid = await self._send(self.EXEC, cmd)
                    for _ in range(30):          # пропускаем хвосты старых ответов
                        r, _t, out = await self._read()
                        if r == rid:
                            return out
                    raise ConnectionError("нет ответа на команду")
                except PermissionError:
                    await self._close()
                    raise
                except Exception:
                    await self._close()
                    if attempt == 2:
                        raise


RCON = _RconClient()


# ── Серверные игры: ARK, Rust, Palworld ──────────────────────────────────────
SERVER_GAMES = {"ark": "ARK", "rust": "Rust", "palworld": "Palworld", "zomboid": "Project Zomboid", "7dtd": "7 Days to Die"}
SERVER_PORTS = {"ark": 27020, "rust": 28016, "palworld": 25575, "zomboid": 27015, "7dtd": 8081}
GAME_RCON = {"ark": _RconClient(), "palworld": _RconClient(), "zomboid": _RconClient()}


class _WebRcon:
    """Rust WebRCON: WebSocket ws://IP:порт/пароль, команды — JSON с номером."""

    def __init__(self):
        self.session = self.ws = self.key = self.lock = None
        self.ident = 1000

    async def _close(self):
        for obj in (self.ws, self.session):
            try:
                if obj is not None:
                    await obj.close()
            except Exception:
                pass
        self.session = self.ws = self.key = None

    async def command(self, cmd, host, port, pw, wait=1.5):
        """Отправляет команду. wait — сколько ждать ответа (для проверки связи — дольше)."""
        import aiohttp
        from urllib.parse import quote
        if self.lock is None:
            self.lock = asyncio.Lock()
        key = (host, port, pw)
        async with self.lock:
            for attempt in (1, 2):
                try:
                    if self.ws is None or self.ws.closed or self.key != key:
                        await self._close()
                        self.session = aiohttp.ClientSession()
                        try:
                            self.ws = await self.session.ws_connect(
                                f"ws://{host}:{port}/{quote(pw, safe='')}", timeout=6, heartbeat=30)
                        except aiohttp.WSServerHandshakeError:
                            raise PermissionError("сервер Rust не пустил — проверь пароль rcon.password")
                        self.key = key
                    self.ident = self.ident % 2_000_000_000 + 1
                    ident = self.ident
                    await self.ws.send_str(json.dumps({"Identifier": ident, "Message": cmd, "Name": "TikTokBridge"}))
                    end = time.time() + wait
                    while time.time() < end:
                        try:
                            msg = await asyncio.wait_for(self.ws.receive(), timeout=max(0.05, end - time.time()))
                        except asyncio.TimeoutError:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                d = json.loads(msg.data)
                            except ValueError:
                                continue
                            if d.get("Identifier") == ident:
                                return str(d.get("Message", ""))
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                          aiohttp.WSMsgType.ERROR):
                            raise ConnectionError("сервер закрыл соединение")
                    return ""                    # команда ушла, ответа не дождались — это не ошибка
                except PermissionError:
                    await self._close()
                    raise
                except Exception:
                    await self._close()
                    if attempt == 2:
                        raise


WEBRCON = _WebRcon()


def _srv(game):
    cfg = STATE.config
    host = str(cfg.get(f"{game}_host") or "").strip()
    if not host:
        raise ValueError(f"не указан IP сервера {SERVER_GAMES[game]} (Настройки → Серверные игры)")
    try:
        port = int(cfg.get(f"{game}_port") or SERVER_PORTS[game])
    except (TypeError, ValueError):
        port = SERVER_PORTS[game]
    return host, port, str(cfg.get(f"{game}_password") or "")


async def palworld_rest(path, body=None, method="POST"):
    """Официальный REST API Palworld (вход: admin + AdminPassword)."""
    import aiohttp
    host, _p, pw = _srv("palworld")
    try:
        port = int(STATE.config.get("palworld_rest_port") or 8212)
    except (TypeError, ValueError):
        port = 8212
    url = f"http://{host}:{port}/v1/api/{path}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
        async with s.request(method, url, json=body if method == "POST" else None,
                             auth=aiohttp.BasicAuth("admin", pw)) as r:
            if r.status == 401:
                raise PermissionError("неверный AdminPassword Palworld")
            if r.status >= 400:
                raise RuntimeError(f"REST API Palworld ответил {r.status}")
            return await r.text()


async def sdtd_player_id(host, port, pw):
    """7 Days to Die призывает существ по ID игрока, а не по нику — узнаём ID через lp."""
    from steamservers import telnet_command
    out = await telnet_command(host, port, pw, "lp")
    nick = str(STATE.config.get("7dtd_player") or "").strip().lower()
    found = re.findall(r"id=(\d+),\s*([^,]+),", out)
    if not found:
        raise RuntimeError("на сервере 7 Days to Die нет игроков — некого атаковать")
    for pid, name in found:
        if nick and name.strip().lower() == nick:
            return pid
    return found[0][0]                                  # ник не указан — первый игрок


async def server_game_send(game, cmd):
    """Команда на сервер ARK / Rust / Palworld. Ответ сервера (если есть) — в лог."""
    name = SERVER_GAMES[game]
    try:
        host, port, pw = _srv(game)
        if game == "rust":
            out = await WEBRCON.command(cmd, host, port, pw)
        elif game == "7dtd":
            from steamservers import telnet_command
            if "{pid}" in cmd:
                cmd = cmd.replace("{pid}", await sdtd_player_id(host, port, pw))
            out = await telnet_command(host, port, pw, cmd)
        elif game == "palworld" and cmd.lower().startswith("announce "):
            await palworld_rest("announce", {"message": cmd[9:].strip()})
            out = ""
        else:
            out = await GAME_RCON[game].command(cmd, host, port, pw)
        out = " ".join(str(out or "").split())
        if out and "no response" not in out.lower():
            STATE.log(name.upper(), out[:200])
        return True
    except Exception as e:
        STATE.log(f"ОШИБКА {name.upper()}", f"{e} (команда: {cmd})")
        return False


async def game_ping(game):
    """Проверка связи с сервером игры — для кнопки «Проверить»."""
    if game == "minecraft":
        return await mc_ping()
    if game not in SERVER_GAMES:
        return False, "неизвестная игра"
    name = SERVER_GAMES[game]
    try:
        host, port, pw = _srv(game)
        if game == "rust":
            out = await WEBRCON.command("serverinfo", host, port, pw, wait=5)
            try:
                info = json.loads(out)
                return True, f"Связь с Rust есть! Сервер «{info.get('Hostname', '?')}», " \
                             f"игроков {info.get('Players', '?')}"
            except ValueError:
                return True, "Связь с Rust есть!"
        if game == "palworld" and str(STATE.config.get("palworld_rest_port") or "").strip():
            out = await palworld_rest("info", method="GET")
            try:
                return True, f"Связь с Palworld есть! {json.loads(out).get('servername', '')}".strip()
            except ValueError:
                return True, "Связь с Palworld есть (REST API)"
        if game == "7dtd":
            from steamservers import telnet_command
            out = await telnet_command(host, port, pw, "gettime")
            return True, "Связь с 7 Days to Die есть!" + (f" ({' '.join(out.split())[:60]})" if out.strip() else "")
        out = await GAME_RCON[game].command({"ark": "ListPlayers", "zomboid": "players"}.get(game, "Info"), host, port, pw)
        out = " ".join(str(out).split())[:80]
        return True, f"Связь с {name} есть!" + (f" ({out})" if out else "")
    except PermissionError as e:
        hint = {"ark": " (ServerAdminPassword)", "palworld": " (AdminPassword)", "zomboid": " (RCONPassword)",
                "7dtd": " (TelnetPassword)"}.get(game, "")
        return False, f"{e}{hint}" if "RCON" in str(e) else str(e)
    except ValueError as e:
        return False, str(e)
    except (ConnectionRefusedError, OSError, asyncio.TimeoutError):
        return False, f"{name} не отвечает — проверь IP, порт и что RCON включён на сервере"
    except Exception as e:
        return False, f"Ошибка {name}: {e}"


def player_name():
    """Твой персонаж в игре активной вкладки — подставляется в {nick} и {playername}."""
    game = active_profile().get("game") or "minecraft"
    if game in SERVER_GAMES:
        v = str(STATE.config.get(f"{game}_player") or "").strip()
        if v:
            return v
    nick = str(STATE.config.get("minecraft_nick", "") or "").strip()
    if not nick and game == "minecraft":
        if not STATE.nick_warned:
            STATE.nick_warned = True
            STATE.log("ВНИМАНИЕ", "не задан ник Minecraft — вместо {nick} подставляю @p "
                                  "(ближайший игрок). Впиши ник: Настройки → Minecraft")
        return "@p"
    return nick


async def mc_ping():
    """Проверка связи выбранным способом (для кнопки «Проверить»)."""
    if STATE.config.get("mc_transport") == "rcon":
        try:
            out = await RCON.command("list")
            out = " ".join(str(out).split())[:80]
            return True, "Связь по RCON есть!" + (f" ({out})" if out else "")
        except PermissionError as e:
            return False, f"{e} (rcon.password в server.properties)"
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
            return False, ("RCON не отвечает — проверь IP, порт и что в server.properties "
                           "стоит enable-rcon=true")
        except Exception as e:
            return False, f"Ошибка RCON: {e}"
    return await servertap_ping()


async def servertap_ping():
    """Проверка связи с сервером через ServerTap."""
    import aiohttp
    cfg = STATE.config
    url = f"{_servertap_base()}/v1/server"
    headers = {}
    if cfg.get("servertap_key"):
        headers["key"] = cfg["servertap_key"]
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, ssl=False) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        name = (data.get("name", "Minecraft") + " " +
                                data.get("version", "")).strip()
                    except Exception:
                        name = "Minecraft"
                    return True, "Связь с сервером есть! (" + name + ")"
                elif resp.status == 401:
                    return False, "Неверный ключ авторизации (key)"
                else:
                    return False, f"Сервер ответил HTTP {resp.status}"
    except Exception as e:
        return False, f"Не удалось подключиться: {e}"


# ── Подстановка переменных в команду ─────────────────────────────────────────
def _resolve_funcs(text):
    """Считает функции: {random:X Y}, {random:['a','b']}, {random:N X Y},
    {mult:X Y}, {plus:X Y}. Работает изнутри наружу, поэтому можно вкладывать."""
    import random as _rnd
    import re as _re

    def num(s):
        try:
            f = float(s)
            return int(f) if f == int(f) else f
        except Exception:
            return 0

    def do_random(m):
        body = m.group(1).strip()
        # список вариантов: {random:['a','b','c']}
        if body.startswith("[") and body.endswith("]"):
            parts = [p.strip().strip("'\"") for p in body[1:-1].split(",") if p.strip()]
            return str(_rnd.choice(parts)) if parts else ""
        nums = body.split()
        try:
            if len(nums) == 2:                       # {random:X Y}
                a, b = num(nums[0]), num(nums[1])
                lo, hi = min(a, b), max(a, b)
                return str(_rnd.randint(int(lo), int(hi)))
            if len(nums) == 3:                       # {random:N X Y}
                base, a, b = num(nums[0]), num(nums[1]), num(nums[2])
                lo, hi = min(a, b), max(a, b)
                return str(base + _rnd.randint(int(lo), int(hi)))
        except Exception:
            pass
        return m.group(0)

    def do_math(op):
        def f(m):
            parts = m.group(1).split()
            if len(parts) != 2:
                return m.group(0)
            a, b = num(parts[0]), num(parts[1])
            r = a * b if op == "mult" else a + b
            return str(int(r) if float(r) == int(r) else r)
        return f

    # Несколько проходов — чтобы отработали вложенные вызовы
    for _ in range(5):
        before = text
        text = _re.sub(r"\{random:([^{}]*)\}", do_random, text)
        text = _re.sub(r"\{mult:([^{}]*)\}", do_math("mult"), text)
        text = _re.sub(r"\{plus:([^{}]*)\}", do_math("plus"), text)
        if text == before:
            break
    return text


def fill_vars(command, nick=None, count=1, user="", ctx=None):
    """Подставляет переменные в команду.

    Основные: {nick}/{playername} — твой ник в игре, {user}/{nickname} — имя зрителя,
    {count}/{giftcount} — сколько подарков, {uniqueid}, {giftname}, {coins},
    {comment}, {index}, {repetition}, {picture}.
    Плюс функции: {random:...}, {mult:X Y}, {plus:X Y}.
    """
    nick = nick or player_name()
    c = dict(ctx or {})
    vals = {
        "nick": nick, "playername": nick,
        "user": user, "nickname": user,
        "count": count, "giftcount": count,
        "uniqueid": c.get("uniqueid", ""),
        "giftname": c.get("giftname", ""),
        "coins": c.get("coins", 0),
        "comment": c.get("comment", ""),
        "picture": c.get("picture", ""),
        "index": c.get("index", 1),
        "repetition": c.get("repetition", 1),
        "repeatcount": c.get("repetition", 1),   # синоним из документации SE
    }
    out = command
    for k, v in vals.items():
        out = out.replace("{" + k + "}", str(v))
    return _resolve_funcs(out)


# ── Выполнение цепочки команд ────────────────────────────────────────────────
async def run_chain(action, count=1, user="", ctx=None):
    """
    Выполняет цепочку команд из action.
    action = {
        "commands": ["cmd1", "cmd2", ...],
        "delays":   [0, 0.5, ...],         # пауза ПЕРЕД каждой командой (сек)
        "random":   False                   # если True — выполнить ОДНУ случайную
    }
    """
    commands = action.get("commands", [])
    delays = action.get("delays", [])
    if not commands:
        return

    if action.get("random"):
        # Режим рулетки — одна случайная команда из цепочки
        import random
        idx = random.randrange(len(commands))
        cmd = fill_vars(commands[idx], count=count, user=user, ctx=ctx)
        await game_send(cmd, user)
        STATE.log("КОМАНДА", f"🎲 {cmd}")
        return

    for i, raw in enumerate(commands):
        delay = delays[i] if i < len(delays) else 0
        if delay and delay > 0:
            await asyncio.sleep(float(delay))
        cmd = fill_vars(raw, count=count, user=user, ctx=ctx)
        await game_send(cmd, user)
        STATE.log("КОМАНДА", cmd)


# ── Игры: куда отправлять команды ────────────────────────────────────────────
# minecraft — сервер (ServerTap/RCON), gta5 — наш мод в игре забирает команды
# из очереди, keyboard — любая игра через нажатия клавиш.
MOD_GAMES = {"gta5": "GTA 5"}
KB_PREFIXES = ("key:", "hold:", "type:", "click:", "turn:", "spin:", "release:")
MOUSE_BTNS = {"mouse1": "left", "lmb": "left", "mouse2": "right", "rmb": "right", "mouse3": "middle"}
RELEASE_KEYS = ("w", "a", "s", "d", "shift", "ctrl", "alt", "space", "e", "r", "f", "g")


async def game_send(cmd, user=""):
    """Отправляет одну команду туда, во что сейчас играем."""
    c = str(cmd or "").strip()
    if not c:
        return False
    if c.lower().startswith(KB_PREFIXES):          # клавиатура работает в любой игре
        return await keyboard_do(c)
    game = active_profile().get("game") or "minecraft"
    if game in MOD_GAMES:
        mod_push(game, c, user)
        return True
    if game in SERVER_GAMES:
        return await server_game_send(game, c)
    if game == "keyboard":                          # обычная строка = напечатать и Enter
        ok = await keyboard_do("type:" + c)
        return ok and await keyboard_do("key:enter")
    if game == "valheim":                           # обычная строка = команда в консоль Valheim (F5)
        if not await keyboard_do("key:f5"):
            return False
        await asyncio.sleep(0.2)
        ok = await keyboard_do("type:" + c) and await keyboard_do("key:enter")
        await asyncio.sleep(0.05)
        await keyboard_do("key:f5")
        return ok
    if game == "cs2":                               # обычная строка = команда в консоль CS2
        if not await keyboard_do("key:grave"):
            return False
        await asyncio.sleep(0.15)
        ok = await keyboard_do("type:" + c) and await keyboard_do("key:enter")
        await asyncio.sleep(0.05)
        await keyboard_do("key:grave")
        return ok
    return await rcon_send(c)


def mod_push(game, cmd, user=""):
    """Кладёт команду в очередь — мод игры заберёт её сам."""
    STATE.mod_seq += 1
    q = STATE.mod_queue.setdefault(game, [])
    q.append({"id": STATE.mod_seq, "cmd": str(cmd), "user": str(user or "")})
    if len(q) > 200:
        del q[:-200]


def mod_connected(game, within=4.0):
    return time.time() - STATE.mod_seen.get(game, 0) < within


# ── Клавиатура и мышь (Windows SendInput) ────────────────────────────────────
_VK = {"enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
       "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
       "ins": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
       "pagedown": 0x22, "pgdn": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
       "right": 0x27, "shift": 0xA0, "ctrl": 0xA2, "control": 0xA2, "alt": 0xA4,
       "win": 0x5B, "capslock": 0x14, "numlock": 0x90, "printscreen": 0x2C,
       "pause": 0x13, "grave": 0xC0, "tilde": 0xC0, "backtick": 0xC0, "`": 0xC0,
       "~": 0xC0, "minus": 0xBD, "-": 0xBD, "equals": 0xBB, "=": 0xBB, "plus": 0xBB,
       "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE, "comma": 0xBC, ",": 0xBC,
       "period": 0xBE, "dot": 0xBE, ".": 0xBE, "slash": 0xBF, "/": 0xBF,
       "backslash": 0xDC, "\\": 0xDC, "multiply": 0x6A, "add": 0x6B,
       "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F}
_VK.update({chr(c): ord(chr(c).upper()) for c in range(ord("a"), ord("z") + 1)})
_VK.update({str(d): 0x30 + d for d in range(10)})
_VK.update({f"f{n}": 0x6F + n for n in range(1, 25)})
_VK.update({f"num{d}": 0x60 + d for d in range(10)})
_VK_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0x90, 0x5B}


def kb_combo(spec):
    """«ctrl+shift+a» → список кодов клавиш. Неизвестная клавиша → ValueError."""
    keys = [k.strip().lower() for k in str(spec).split("+") if k.strip()]
    if not keys:
        raise ValueError("не указана клавиша")
    out = []
    for k in keys:
        if k not in _VK:
            raise ValueError(f"неизвестная клавиша «{k}»")
        out.append(_VK[k])
    return out


def kb_plan(spec):
    """Разбирает команду клавиатуры в план действий (без нажатий — удобно проверять)."""
    kind, _, arg = str(spec).partition(":")
    kind = kind.strip().lower()
    if kind == "key":
        vks = kb_combo(arg)
        return [("down", v) for v in vks] + [("up", v) for v in reversed(vks)]
    if kind == "hold":
        combo, _, secs = arg.rpartition(":")
        if not combo:
            combo, secs = arg, "1"
        try:
            sec = max(0.05, min(60.0, float(secs.replace(",", "."))))
        except ValueError:
            raise ValueError(f"не понял, сколько секунд держать: «{secs}»")
        btn = MOUSE_BTNS.get(combo.strip().lower())
        if btn:                                          # зажать кнопку мыши (стрелять)
            return [("mdown", btn), ("wait", sec), ("mup", btn)]
        vks = kb_combo(combo)
        return [("down", v) for v in vks] + [("wait", sec)] + [("up", v) for v in reversed(vks)]
    if kind == "type":
        return [("text", arg)]
    if kind == "turn":                                   # turn:180 · turn:-90 (влево) · turn:0:60 (вверх)
        parts = [p.strip() for p in arg.split(":") if p.strip()]
        try:
            yaw = float(parts[0].replace(",", ".")) if parts else 180.0
            pitch = float(parts[1].replace(",", ".")) if len(parts) > 1 else 0.0
        except ValueError:
            raise ValueError(f"поворот задаётся в градусах, например turn:180, а не «{arg}»")
        return [("turn", (max(-1080.0, min(1080.0, yaw)), max(-89.0, min(89.0, pitch))))]
    if kind == "spin":                                   # spin:3 — крутиться 3 секунды
        try:
            sec = max(0.2, min(15.0, float((arg or "3").replace(",", "."))))
        except ValueError:
            raise ValueError(f"не понял, сколько секунд крутиться: «{arg}»")
        return [("spin", sec)]
    if kind == "release":                                # отпустить всё, если что-то залипло
        return [("release", None)]
    if kind == "click":
        btn = (arg.strip().lower() or "left")
        if btn not in ("left", "right", "middle"):
            raise ValueError(f"кнопка мыши бывает left, right или middle, а не «{btn}»")
        return [("click", btn)]
    raise ValueError(f"неизвестная команда клавиатуры «{kind}»")


_USER32 = None


def _kb_send(events):
    """Низкоуровневая отправка через SendInput (сканкоды — так их видят игры)."""
    import ctypes
    global _USER32
    if _USER32 is None:
        _USER32 = ctypes.WinDLL("user32", use_last_error=True)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    inputs = []
    for kind, val in events:
        if kind in ("down", "up"):
            scan = _USER32.MapVirtualKeyW(val, 0)
            flags = 0x0008 | (0x0002 if kind == "up" else 0)       # SCANCODE | KEYUP
            if val in _VK_EXTENDED:
                flags |= 0x0001                                    # EXTENDEDKEY
            inputs.append(INPUT(1, _U(ki=KEYBDINPUT(val, scan, flags, 0, 0))))
        elif kind == "unicode":
            for up in (False, True):
                inputs.append(INPUT(1, _U(ki=KEYBDINPUT(0, val, 0x0004 | (0x0002 if up else 0), 0, 0))))
        elif kind in ("click", "mdown", "mup"):
            dn, upf = {"left": (0x02, 0x04), "right": (0x08, 0x10), "middle": (0x20, 0x40)}[val]
            if kind in ("click", "mdown"):
                inputs.append(INPUT(0, _U(mi=MOUSEINPUT(0, 0, 0, dn, 0, 0))))
            if kind in ("click", "mup"):
                inputs.append(INPUT(0, _U(mi=MOUSEINPUT(0, 0, 0, upf, 0, 0))))
        elif kind == "move":                             # относительное движение мыши
            dx, dy = val
            inputs.append(INPUT(0, _U(mi=MOUSEINPUT(int(dx), int(dy), 0, 0x0001, 0, 0))))
    if inputs:
        arr = (INPUT * len(inputs))(*inputs)
        _USER32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _release_pressed():
    """Отпускает только то, что сейчас зажато. Лишнее «отпустить Alt» Windows считает
    нажатием Alt и открывает меню окна — в игре это может свернуть её."""
    import ctypes
    global _USER32
    if _USER32 is None:
        _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    down = lambda vk: bool(_USER32.GetAsyncKeyState(vk) & 0x8000)
    ev = [("up", _VK[k]) for k in RELEASE_KEYS if down(_VK[k])]
    ev += [("mup", b) for b, vk in (("left", 0x01), ("right", 0x02)) if down(vk)]
    if ev:
        _kb_send(ev)
    return len(ev)


def mouse_counts(yaw, pitch):
    """Градусы → «шаги» мыши по формуле Source: градусы = шаги × 0.022 × чувствительность."""
    try:
        sens = float(STATE.config.get("cs2_sensitivity", 2.0) or 2.0)
    except (TypeError, ValueError):
        sens = 2.0
    k = 0.022 * max(0.05, sens)
    return round(yaw / k), round(-pitch / k)           # вверх — минус по Y


def _mouse_smooth(dx, dy, duration):
    """Плавно — как быстрый взмах рукой, а не мгновенный «флик» (его легко принять за чит)."""
    steps = max(1, int(duration / 0.01))
    sx = sy = 0
    for i in range(1, steps + 1):
        tx, ty = round(dx * i / steps), round(dy * i / steps)
        _kb_send([("move", (tx - sx, ty - sy))])
        sx, sy = tx, ty
        time.sleep(0.01)


def _mouse_spin(seconds, deg_per_sec=720):
    step_dx, _ = mouse_counts(deg_per_sec * 0.01, 0)
    end = time.time() + seconds
    while time.time() < end:
        _kb_send([("move", (step_dx, 0))])
        time.sleep(0.01)


async def keyboard_do(spec):
    """Выполняет key:/hold:/type:/click: в активном окне (в игре)."""
    try:
        plan = kb_plan(spec)
    except ValueError as e:
        STATE.log("ОШИБКА КЛАВИАТУРЫ", f"{e} (команда: {spec})")
        return False
    if sys.platform != "win32":
        STATE.log("ОШИБКА КЛАВИАТУРЫ", "нажатия клавиш работают только на Windows")
        return False
    loop = asyncio.get_event_loop()
    held = []                                          # что сейчас зажато — отпустим в finally
    try:
        for kind, val in plan:
            if kind in ("down", "mdown"):
                held.append(("up" if kind == "down" else "mup", val))
            elif kind in ("up", "mup") and (kind, val) in held:
                held.remove((kind, val))
            if kind == "wait":
                await asyncio.sleep(val)
            elif kind == "turn":
                dx, dy = mouse_counts(*val)
                await loop.run_in_executor(None, _mouse_smooth, dx, dy, 0.22)
            elif kind == "spin":
                await loop.run_in_executor(None, _mouse_spin, val)
            elif kind == "release":
                await loop.run_in_executor(None, _release_pressed)
            elif kind == "text":
                for ch in str(val):                  # по символу с паузой — игры не теряют буквы
                    units = ch.encode("utf-16-le")
                    ev = [("unicode", int.from_bytes(units[i:i + 2], "little")) for i in range(0, len(units), 2)]
                    await loop.run_in_executor(None, _kb_send, ev)
                    await asyncio.sleep(0.012)
            else:
                await loop.run_in_executor(None, _kb_send, [(kind, val)])
                await asyncio.sleep(0.02)
        return True
    except Exception as e:
        STATE.log("ОШИБКА КЛАВИАТУРЫ", f"{e} (команда: {spec})")
        return False
    finally:
        if held:
            try:
                await loop.run_in_executor(None, _kb_send, held)
            except Exception:
                pass


# ── Поиск действия по событию в активном профиле ─────────────────────────────
def active_profile():
    name = STATE.config.get("active_profile")
    return STATE.profiles.get(name, {})


def _icon_key(name):
    """Ключ поиска иконки: без регистра, пробелов, дефисов и апострофов."""
    s = str(name or "").strip().lower().replace("\u2019", "'")
    return "".join(ch for ch in s if ch.isalnum())


_ICON_INDEX = {_icon_key(k): v for k, v in GIFT_ICON_URLS.items()}


def gift_icon_url(name):
    """Ссылка на официальную иконку подарка (из эфира или из справочника)."""
    if not STATE.config.get("gift_icons_online", True):
        return ""
    key = str(name or "").strip().lower()
    if key in STATE.live_gift_icons:
        return STATE.live_gift_icons[key]
    if key in GIFT_ICON_URLS:
        return GIFT_ICON_URLS[key]
    nk = _icon_key(name)
    for src in (STATE.live_gift_icons, {}):
        for k, v in src.items():
            if _icon_key(k) == nk:
                return v
    return _ICON_INDEX.get(nk, "")


def _is_enabled(action):
    """Триггер активен если поле enabled не False (по умолчанию включён)."""
    return action.get("enabled", True) is not False


def find_gift_action(gift_name, gift_id):
    """Ищет настроенный подарок по имени или ID.

    Сначала пытаемся точно сопоставить по ID (если он задан),
    затем по имени. Пустые ID НЕ считаются совпадением.
    """
    prof = active_profile()
    gid = str(gift_id).strip()
    # 1) Точное совпадение по ID (только непустые)
    if gid:
        for g in prof.get("gifts", []):
            cfg_id = str(g.get("gift_id", "")).strip()
            if cfg_id and cfg_id == gid:
                return g
    # 2) По названию: как прислал TikTok (по-английски) или по-русски — как видно в приложении
    names = {norm_gift(gift_name)} - {""}
    if gid and STATE.gift_names_ru.get(gid):
        names.add(norm_gift(STATE.gift_names_ru[gid]))
    if names:
        for g in prof.get("gifts", []):
            if norm_gift(g.get("name", "")) in names:
                return g
    return None


# ── Обработчики событий TikTok ───────────────────────────────────────────────
def schedule(coro):
    """Запускает корутину в event loop (TikTok или веб-сервера)."""
    loop = STATE.loop
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, loop)
        return
    # Фолбэк: используем loop веб-сервера (для теста без подключения к TikTok)
    web_loop = STATE.web_loop
    if web_loop and web_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, web_loop)
    else:
        STATE.log("ОШИБКА", "Нет активного цикла для выполнения команды")


def _extract_media(cfg_obj):
    """Достаёт медиа-настройки из объекта (подарок/подписка/фоллов/привет).

    Ожидает поля: media_file, media_kind, sound_file, media_volume, sound_volume.
    Возвращает dict для оверлея или None если медиа не задано.
    """
    if not cfg_obj:
        return None
    mfile = cfg_obj.get("media_file", "")
    sfile = cfg_obj.get("sound_file", "")
    if not mfile and not sfile:
        return None
    return {
        "file": mfile,
        "kind": cfg_obj.get("media_kind", "") or "video",
        "sound": sfile,
        "volume": int(cfg_obj.get("media_volume", 100)),
        "sound_volume": int(cfg_obj.get("sound_volume", 100)),
        "show_seconds": float(cfg_obj.get("media_seconds", 5) or 5),   # сколько показывать картинку/гифку
    }


def fire_action(action, count=1, user="", ctx=None):
    """Запускает цепочку действия N раз (поле multiplier — количество активаций)."""
    try:
        times = int(action.get("multiplier", 1) or 1)
    except Exception:
        times = 1
    times = max(1, min(times, 100))  # разумный предел
    for i in range(times):
        c = dict(ctx or {})
        c["index"] = i + 1          # номер повтора: 1, 2, 3...
        c["repetition"] = times     # всего повторов
        schedule(run_chain(action, count=count, user=user, ctx=c))


def _goal_current(metric):
    """Текущее значение метрики для целей."""
    if metric == "likes":
        return STATE.total_likes
    if metric == "coins":
        return sum(STATE.gifters.values())
    if metric == "follows":
        return STATE.follow_count
    if metric == "subs":
        return STATE.sub_count
    if metric == "gifts":
        return STATE.gifts_count
    return 0


def check_goals():
    """Проверяет цели активного профиля, при достижении — команды + оверлей."""
    prof_name = STATE.config.get("active_profile", "")
    prof = active_profile()
    for i, g in enumerate(prof.get("goals", [])):
        if not _is_enabled(g):
            continue
        key = (prof_name, i)
        if key in STATE.goals_done:
            continue
        try:
            target = int(g.get("target", 0) or 0)
        except Exception:
            target = 0
        if target <= 0:
            continue
        if _goal_current(g.get("metric", "likes")) >= target:
            STATE.goals_done.add(key)
            title = g.get("title") or f"Цель {target}"
            STATE.log("ЦЕЛЬ", f"🎯 Достигнута: {title}")
            STATE.push_overlay("goal", "", f"🎯 ЦЕЛЬ ДОСТИГНУТА: {title}!",
                               icon="🎯", color="#fbbf24", media=_extract_media(g))
            fire_action(g, count=target, user="")


def handle_gift(gift_name, gift_id, count, user, diamonds=0):
    STATE.log("ПОДАРОК", f"{user} → «{gift_name}» x{count}  [ID: {gift_id}]")
    STATE.register_seen_gift(gift_name, gift_id, diamonds)
    STATE.gifts_count += count
    STATE.last_gift = {"name": str(gift_name or "").strip(),
                       "seq": STATE.last_gift["seq"] + 1}
    gctx = {"giftname": str(gift_name or ""), "coins": (diamonds or 0) * count,
            "uniqueid": STATE.last_uid.get(str(user), ""), "picture": ""}
    # Таймер-челлендж: подарок добавляет время
    if STATE.timer["running"]:
        try:
            per = float(STATE.config.get("timer_sec_per_coin", 0) or 0)
        except Exception:
            per = 0
        if per > 0:
            STATE.timer["end"] += (diamonds or 1) * count * per
    action = find_gift_action(gift_name, gift_id)
    # Оверлей: алерт + топ донатеров + медиа (если у подарка задано)
    media = _extract_media(action)
    STATE.push_overlay("gift", user,
        f"подарил {gift_name}" + (f" x{count}" if count > 1 else ""),
        icon="🎁", color="#00d4ff", amount=(diamonds or 1) * count, media=media)
    check_goals()
    # Случайное событие при любом подарке (если включено)
    if STATE.config.get("random_enabled") and STATE.config.get("random_on_gift"):
        schedule(fire_random_event("подарок"))
    if not action:
        return
    if not _is_enabled(action):
        return  # триггер выключен тумблером
    # Повтор по количеству подарков (combo) или один раз
    if action.get("repeat_by_count"):
        # защита сервера: комбо из сотен роз не должно отправить сотни цепочек разом
        try:
            cap = max(1, int(STATE.config.get("max_repeat", 30) or 30))
        except (TypeError, ValueError):
            cap = 30
        times = min(int(count or 1), cap)
        if times < count:
            STATE.log("ЗАЩИТА", f"«{gift_name}» x{count} → выполнено {times} раз (ограничение max_repeat={cap})")
        for _ in range(times):
            fire_action(action, count=count, user=user, ctx=gctx)
    else:
        fire_action(action, count=count, user=user, ctx=gctx)


def handle_like(like_count, user):
    """like_count — сколько лайков пришло в этом событии (может быть >1)."""
    if like_count < 1:
        like_count = 1
    STATE.total_likes += like_count
    STATE.likers[user] = STATE.likers.get(user, 0) + like_count
    prof = active_profile()
    like_actions = prof.get("likes", [])
    before = STATE.like_counter
    STATE.like_counter += like_count
    after = STATE.like_counter
    check_goals()
    for a in like_actions:
        if not _is_enabled(a):
            continue
        threshold = a.get("threshold", 100)
        if threshold <= 0:
            continue
        # Сколько раз порог пересечён этой пачкой лайков
        crossings = (after // threshold) - (before // threshold)
        for _ in range(crossings):
            STATE.log("ЛАЙКИ", f"Порог {threshold} достигнут (от {user})")
            STATE.push_overlay("like", user, f"{threshold} лайков!",
                               icon="❤", color="#f85149")
            fire_action(a, count=STATE.like_counter, user=user,
                        ctx={"uniqueid": STATE.last_uid.get(str(user), "")})


def handle_sub(user):
    STATE.log("ПОДПИСКА", f"{user} подписался!")
    STATE.sub_count += 1
    STATE.followers.add(str(user).strip().lstrip("@").lower())
    prof = active_profile()
    subs = [a for a in prof.get("subs", []) if _is_enabled(a)]
    media = _extract_media(subs[0]) if subs else None
    STATE.push_overlay("sub", user, "оформил подписку!", icon="⭐", color="#d29922", media=media)
    check_goals()
    for a in subs:
        fire_action(a, count=1, user=user)


def handle_follow(user):
    STATE.log("ФОЛЛОВ", f"{user} зафолловил!")
    STATE.follow_count += 1
    STATE.followers.add(str(user).strip().lstrip("@").lower())
    prof = active_profile()
    follows = [a for a in prof.get("follows", []) if _is_enabled(a)]
    media = _extract_media(follows[0]) if follows else None
    STATE.push_overlay("follow", user, "подписался на профиль!", icon="➕", color="#3fb950", media=media)
    check_goals()
    for a in follows:
        fire_action(a, count=1, user=user)


def tts_allowed(display, uid="", is_follower=False):
    """Проверка: озвучивать ли сообщение этого зрителя (фильтр озвучки)."""
    mode = STATE.config.get("tts_filter_mode", "all")
    if mode == "all":
        return True
    d = str(display).strip().lstrip("@").lower()
    u = str(uid).strip().lstrip("@").lower()
    if mode == "list":
        raw = str(STATE.config.get("tts_filter_list", ""))
        nicks = {n.strip().lstrip("@").lower()
                 for n in raw.replace("\n", ",").split(",") if n.strip()}
        return d in nicks or u in nicks
    if mode == "gifters":
        try:
            need = int(STATE.config.get("tts_filter_coins", 1) or 1)
        except Exception:
            need = 1
        total = sum(v for k, v in STATE.gifters.items()
                    if str(k).strip().lstrip("@").lower() in (d, u))
        return total >= need
    if mode == "likers":
        try:
            need = int(STATE.config.get("tts_filter_likes", 100) or 1)
        except Exception:
            need = 100
        total = sum(v for k, v in STATE.likers.items()
                    if str(k).strip().lstrip("@").lower() in (d, u))
        return total >= need
    if mode == "followers":
        return is_follower or d in STATE.followers or u in STATE.followers
    return True


# ── Локальный плеер озвучки (играет прямо из программы, как TikFinity) ──────
import queue as _queue
TTS_PLAY_QUEUE = _queue.Queue()


def _mci(cmd):
    """Отправляет команду мультимедиа-подсистеме Windows (winmm)."""
    import ctypes
    buf = ctypes.create_unicode_buffer(255)
    rc = ctypes.windll.winmm.mciSendStringW(cmd, buf, 254, 0)
    if rc != 0:
        err = ctypes.create_unicode_buffer(255)
        ctypes.windll.winmm.mciGetErrorStringW(rc, err, 254)
        raise RuntimeError(err.value or f"MCI код {rc}")
    return buf.value


def tts_player_worker():
    """Фоновый поток: проигрывает озвучку по очереди через звук Windows.
    Играет без «wait» и каждые 0.1 с проверяет кнопки «⏹ Остановить» и «⏭ Пропустить»."""
    n = 0
    while True:
        item = TTS_PLAY_QUEUE.get()
        if item is None:
            break
        path, volume, epoch = item if len(item) == 3 else (*item, STATE.tts_epoch)
        if epoch != STATE.tts_epoch or sys.platform != "win32":
            continue                     # остановлено — или не Windows
        n += 1
        alias = f"ttsclip{n}"
        try:
            _mci(f'open "{path}" type mpegvideo alias {alias}')
            vol = max(0, min(1000, int(volume) * 10))
            _mci(f"setaudio {alias} volume to {vol}")
            skip0 = STATE.tts_skip
            _mci(f"play {alias}")
            while True:
                time.sleep(0.1)
                if STATE.tts_epoch != epoch or STATE.tts_skip != skip0:
                    _mci(f"stop {alias}")
                    break
                if _mci(f"status {alias} mode") != "playing":
                    break
        except Exception as e:
            STATE.log("ОШИБКА TTS", f"воспроизведение: {e}")
        finally:
            try:
                _mci(f"close {alias}")
            except Exception:
                pass


# ── Fish Audio (облачная озвучка + библиотека голосов) ───────────────────────
_FISH_ERRORS = {
    401: "неверный API-ключ Fish Audio — проверь его в настройках озвучки",
    402: "на аккаунте Fish Audio закончились кредиты",
    403: "Fish Audio запретил запрос (возможно, голос приватный)",
    404: "голос не найден — выбери другой",
    429: "слишком частые запросы к Fish Audio — бесплатная модель упёрлась в лимит",
}


def _fish_headers(json_body=True):
    key = str(STATE.config.get("fish_api_key", "")).strip()
    h = {"User-Agent": "TakyLive"}
    if key:
        h["Authorization"] = "Bearer " + key
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _fish_base():
    return str(STATE.config.get("fish_base") or "https://api.fish.audio").rstrip("/")


async def _fish_tts(msg, voice_id, out_path):
    """Озвучка голосом из библиотеки Fish Audio (POST /v1/tts)."""
    import aiohttp
    if not str(STATE.config.get("fish_api_key", "")).strip():
        raise RuntimeError("не задан API-ключ Fish Audio (Настройки → Озвучка → Fish Audio)")
    headers = _fish_headers()
    headers["model"] = STATE.config.get("fish_model") or "s2.1-pro-free"
    body = {"text": msg[:500], "reference_id": voice_id, "format": "mp3"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(_fish_base() + "/v1/tts", json=body, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(_FISH_ERRORS.get(resp.status, f"Fish Audio HTTP {resp.status}"))
            data = await resp.read()
    if len(data) < 100:
        raise RuntimeError("Fish Audio вернул пустой звук")
    with open(out_path, "wb") as f:
        f.write(data)


def _abs_url(u):
    u = str(u or "")
    return u if u.startswith("http://") or u.startswith("https://") else ""


FISH_CDN_DEFAULT = "https://public-platform.r2.fish.audio"


def _fish_cdn():
    return str(STATE.config.get("fish_cdn") or FISH_CDN_DEFAULT).rstrip("/")


def _fish_asset(u):
    """Fish Audio отдаёт обложки и примеры коротким путём («coverimage/…») —
    дополняем адресом их файлового сервера. Полные ссылки оставляем как есть."""
    u = str(u or "").strip()
    if not u:
        return ""
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        return "https:" + u
    return _fish_cdn() + "/" + u.lstrip("/")


async def h_fish_search(request):
    """Поиск голосов в публичной библиотеке Fish Audio."""
    import aiohttp
    q = request.query.get("q", "").strip()
    lang = request.query.get("lang", "").strip()
    tag = request.query.get("tag", "").strip()
    sort = request.query.get("sort", "task_count").strip()
    if sort not in ("task_count", "created_at"):
        sort = "task_count"
    try:
        page = max(1, int(request.query.get("page", "1")))
        size = max(1, min(48, int(request.query.get("size", "24"))))
    except ValueError:
        page, size = 1, 24
    params = {"page_size": str(size), "page_number": str(page), "sort_by": sort}
    if q:
        params["title"] = q
    if lang:
        params["language"] = lang
    if tag:
        params["tag"] = tag
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_fish_base() + "/model", params=params,
                                   headers=_fish_headers(json_body=False)) as resp:
                if resp.status != 200:
                    return web.json_response({"ok": False,
                        "error": _FISH_ERRORS.get(resp.status, f"Fish Audio HTTP {resp.status}")})
                d = await resp.json(content_type=None)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"нет связи с Fish Audio: {e}"})
    items = []
    for m in (d.get("items") or [])[:size]:
        samples = m.get("samples") or []
        sample = next((_fish_asset(s.get("audio")) for s in samples
                       if isinstance(s, dict) and _fish_asset(s.get("audio"))), "")
        desc = str(m.get("description") or "").strip().replace("\n", " ")
        items.append({
            "id": str(m.get("_id") or m.get("id") or ""),
            "title": str(m.get("title") or "Без названия"),
            "description": desc[:140],
            "languages": [str(x) for x in (m.get("languages") or [])][:3],
            "cover": _fish_asset(m.get("cover_image")),
            "cover_alt": (_fish_cdn() + "/coverimage/" + str(m.get("_id") or m.get("id") or "")) if (m.get("_id") or m.get("id")) else "",
            "cover_raw": str(m.get("cover_image") or "")[:120],   # для диагностики, если адрес сменится
            "sample": sample,
            "likes": int(m.get("like_count") or 0),
            "uses": int(m.get("task_count") or 0),
        })
    items = [i for i in items if i["id"]]
    return web.json_response({"ok": True, "total": d.get("total", len(items)), "page": page, "items": items})


async def h_tts_preview(request):
    """Короткий пример голоса для кнопки ▶ (кэшируется на диске)."""
    import hashlib
    data = await request.json()
    voice = str(data.get("voice", "")).strip()
    text = str(data.get("text") or "Привет! Так я буду читать сообщения из чата.")[:160]
    if not voice:
        return web.json_response({"ok": False, "error": "голос не выбран"})
    name = "preview_" + hashlib.md5((voice + "|" + text).encode()).hexdigest()[:12] + ".mp3"
    path = os.path.join(MEDIA_DIR, "tts", name)
    if not os.path.isfile(path):
        try:
            await _tts_generate(text, voice, path)
        except Exception as e:
            try:
                os.remove(path)
            except Exception:
                pass
            return web.json_response({"ok": False, "error": str(e)})
    return web.json_response({"ok": True, "url": "/media/tts/" + name})


async def _tts_generate(msg, voice, out_path):
    """Генерирует mp3 выбранным движком.

    Голоса вида "se:Maxim" → StreamElements (простой HTTPS, как в TikFinity-подобных
    тулзах, надёжно проходит файрволы). Остальные → Edge TTS (Microsoft).
    """
    if voice.startswith("gt:"):
        # Google Translate TTS — открытый, простой, почти не блокируется
        import aiohttp
        from urllib.parse import quote
        lang = voice[3:]
        short = msg[:180]  # лимит Google на длину фразы
        url = (f"https://translate.google.com/translate_tts"
               f"?ie=UTF-8&client=tw-ob&tl={lang}&q={quote(short)}")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Google TTS HTTP {resp.status}")
                data = await resp.read()
                if len(data) < 500:
                    raise RuntimeError("Google TTS вернул пустой ответ")
                with open(out_path, "wb") as f:
                    f.write(data)
    elif voice.startswith("fish:"):
        await _fish_tts(msg, voice[5:], out_path)
    else:
        try:
            import edge_tts
        except ImportError:
            raise RuntimeError("Библиотека edge-tts не установлена. "
                               "Перезапусти start.bat или выполни: pip install edge-tts")
        await edge_tts.Communicate(msg, voice).save(out_path)


async def tts_speak(display, text, voice=None, read_name=None):
    """Генерирует озвучку сообщения и кладёт в очередь оверлея."""
    msg = str(text).strip()[:250]
    if not msg:
        return False
    if STATE.config.get("tts_read_name", True) if read_name is None else read_name:
        msg = f"{display}. {msg}"
    voice = voice or STATE.config.get("tts_voice", "ru-RU-DmitryNeural")
    epoch = STATE.tts_epoch
    STATE.tts_pending += 1
    try:
        return await _tts_speak_inner(msg, voice, epoch)
    finally:
        STATE.tts_pending -= 1


async def _tts_speak_inner(msg, voice, epoch):
    # Генерируем во временный файл; номер присваиваем ПОСЛЕ генерации,
    # чтобы плеер не «перепрыгнул» ещё не готовое сообщение.
    import uuid
    tmp_rel = f"tts/tmp_{uuid.uuid4().hex}.mp3"
    tmp_path = os.path.join(MEDIA_DIR, tmp_rel)
    try:
        await _tts_generate(msg, voice, tmp_path)
    except Exception as e:
        STATE.tts_last_error = f"Не удалось сгенерировать озвучку: {e}"
        STATE.log("ОШИБКА TTS", f"{e}")
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False
    if epoch != STATE.tts_epoch:                      # пока генерировалось, нажали «⏹ Остановить»
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False
    STATE.tts_seq += 1
    seq = STATE.tts_seq
    rel = f"tts/tts_{seq}.mp3"
    path = os.path.join(MEDIA_DIR, rel)
    try:
        os.replace(tmp_path, path)
    except Exception:
        rel = tmp_rel
    STATE.tts_queue.append({
        "seq": seq, "file": rel,
        "volume": int(STATE.config.get("tts_volume", 100)),
    })
    # Играем НАПРЯМУЮ из программы (как TikFinity) — надёжно, без браузера
    if STATE.config.get("tts_play_local", True):
        TTS_PLAY_QUEUE.put((path, STATE.config.get("tts_volume", 100), epoch))
    # Чистим старое: очередь и файлы
    if len(STATE.tts_queue) > 30:
        STATE.tts_queue = STATE.tts_queue[-30:]
    try:
        keep = {item["file"].split("/")[-1] for item in STATE.tts_queue}
        tts_dir = os.path.join(MEDIA_DIR, "tts")
        for fn in os.listdir(tts_dir):
            if fn.startswith("tmp_") or fn.startswith("preview_"):
                continue  # генерация в процессе или кэш примеров голосов
            if fn not in keep:
                os.remove(os.path.join(tts_dir, fn))
    except Exception:
        pass
    return True


def check_chat_command(text, display):
    """Если сообщение — настроенная чат-команда (!моб), выполняет её с кулдауном."""
    msg = str(text).strip().lower()
    if not msg:
        return
    prof_name = STATE.config.get("active_profile", "")
    prof = active_profile()
    for cc in prof.get("chatcmds", []):
        if not _is_enabled(cc):
            continue
        trig = str(cc.get("trigger", "")).strip().lower()
        if not trig or not msg.startswith(trig):
            continue
        try:
            cooldown = float(cc.get("cooldown", 10) or 0)
        except Exception:
            cooldown = 10
        key = (prof_name, trig)
        now = time.time()
        if now - STATE.cmd_last.get(key, 0) < cooldown:
            return  # на кулдауне — молча пропускаем
        STATE.cmd_last[key] = now
        STATE.log("ЧАТ-КОМАНДА", f"{display} → {trig}")
        STATE.push_overlay("chatcmd", display, f"использовал {trig}",
                           icon="💬", color="#22d3ee", media=_extract_media(cc))
        comment = str(text)
        if STATE.config.get("tts_guard", True) and STATE.config.get("tts_profanity", "beep") != "off":
            import textfilter as _tf
            comment = _tf.censor(comment, [w for w in str(STATE.config.get("tts_bad_words", "")).split(",") if w.strip()])[0]
        fire_action(cc, count=1, user=display, ctx={"comment": comment})
        return


VIEWER_VOICES_FILE = os.path.join(BASE_DIR, "viewer_voices.json")


def load_viewer_voices():
    try:
        with open(VIEWER_VOICES_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_viewer_voices():
    try:
        with open(VIEWER_VOICES_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE.viewer_voices, f, ensure_ascii=False, indent=1)
    except Exception as e:
        STATE.log("ОШИБКА", f"не сохранил голоса зрителей: {e}")


def _guard_skip(reason):
    STATE.tts_guard_stats[reason] = STATE.tts_guard_stats.get(reason, 0) + 1
    return False, reason


def tts_guard(display, user, text):
    """Пускать ли сообщение в озвучку → (True, текст_для_чтения) или (False, причина)."""
    import textfilter as tf
    cfg = STATE.config
    if not cfg.get("tts_guard", True):
        return True, text
    nicks = {n.strip().lstrip("@").lower() for n in str(cfg.get("tts_block_list", "")).replace("\n", ",").split(",") if n.strip()}
    if nicks and ({str(display).lstrip("@").lower(), str(user).lstrip("@").lower()} & nicks):
        return _guard_skip("в чёрном списке")
    if cfg.get("tts_skip_junk", True):
        why = tf.junk_reason(text)
        if why:
            return _guard_skip(why)
    mode = cfg.get("tts_profanity", "beep")
    if mode != "off":
        extra = [w for w in str(cfg.get("tts_bad_words", "")).replace("\n", ",").split(",") if w.strip()]
        clean, bad = tf.censor(text, extra)
        if bad:
            if mode == "skip":
                return _guard_skip("мат")
            STATE.tts_guard_stats["мат заменён"] = STATE.tts_guard_stats.get("мат заменён", 0) + 1
            text = clean
    now = time.time()
    key = str(user).lower()
    try:
        cd = float(cfg.get("tts_user_cooldown", 8) or 0)
    except (TypeError, ValueError):
        cd = 8
    if cd and now - STATE.tts_user_last.get(key, 0) < cd:
        return _guard_skip("слишком часто")
    norm = " ".join(tf.collapse(text).lower().split())
    STATE.tts_recent = [r for r in STATE.tts_recent if now - r[0] < 60]
    if cfg.get("tts_skip_dupes", True) and any(r[2] == norm and (r[1] == key or now - r[0] < 10) for r in STATE.tts_recent):
        return _guard_skip("повтор")
    try:
        cap = int(cfg.get("tts_max_queue", 5) or 0)
    except (TypeError, ValueError):
        cap = 5
    if cap and STATE.tts_pending + TTS_PLAY_QUEUE.qsize() >= cap:
        return _guard_skip("очередь полна")
    STATE.tts_user_last[key] = now
    STATE.tts_recent.append((now, key, norm))
    return True, tf.collapse(text)


def voice_command(text):
    """Команда выбора голоса в начале сообщения → ("set", настройка) / ("reset", None) / None."""
    cfg = STATE.config
    if not cfg.get("voice_cmds_on", True):
        return None
    first = str(text).strip().split(maxsplit=1)[0].lower() if str(text).strip() else ""
    if not first.startswith("!"):
        return None
    if first == str(cfg.get("voice_reset_cmd", "!сброс")).strip().lower():
        return ("reset", None)
    for vc in cfg.get("voice_cmds") or []:
        if str(vc.get("cmd", "")).strip().lower() == first and vc.get("voice"):
            return ("set", vc)
    return None


ROLE_ORDER = ("moderator", "superfan", "friend", "gifter", "follower")


def viewer_voice(user, acc=None, roles=()):
    """Личный голос (свой или назначенный стримером) → голос роли → None (обычный)."""
    v = STATE.viewer_voices.get(str(acc or "")) or STATE.viewer_voices.get("@" + str(user).lstrip("@").lower())
    if v and v.get("voice"):
        return v["voice"]
    rv = STATE.config.get("role_voices") or {}
    for r in ROLE_ORDER:
        if r in (roles or ()) and rv.get(r):
            return rv[r]
    return None


def _remember_viewer(user, display, acc):
    """Запоминаем, кто писал (для выбора «особенных») и переносим голос с @ника на ID аккаунта."""
    nick_key = "@" + str(user).lstrip("@").lower()
    key = str(acc) if acc else nick_key
    STATE.recent_viewers.pop(key, None)
    STATE.recent_viewers[key] = {"key": key, "nick": str(display), "user": str(user), "acc": str(acc or ""),
                                 "seen": time.strftime("%H:%M")}
    if len(STATE.recent_viewers) > 300:
        STATE.recent_viewers.pop(next(iter(STATE.recent_viewers)))
    if acc and nick_key in STATE.viewer_voices and str(acc) not in STATE.viewer_voices:
        v = STATE.viewer_voices.pop(nick_key)
        v.update(acc=str(acc), nick=str(display))
        STATE.viewer_voices[str(acc)] = v
        save_viewer_voices()


def handle_comment(user, text, display=None, is_follower=False, acc=None, roles=None):
    """Первое сообщение зрителя → персональное приветствие по нику.

    user — юзернейм (unique_id, напр. takymi1), display — красивое имя (Takymi).
    Совпадение ищется и по юзернейму, и по красивому имени; на экране — красивое.
    """
    display = display or user
    # Первые секунды после подключения TikTok присылает СТАРЫЕ сообщения
    # (историю чата) — их не озвучиваем и команды не выполняем, только новые.
    fresh = (STATE.connected_at == 0) or (time.time() - STATE.connected_at > 3.0)
    roles = list(roles or []) + (["follower"] if is_follower and "follower" not in (roles or []) else [])
    if fresh:
        _remember_viewer(user, display, acc)
    vc = voice_command(text) if fresh else None
    key = str(acc) if acc else "@" + str(user).lstrip("@").lower()
    if vc and (STATE.viewer_voices.get(key) or {}).get("pinned"):
        STATE.log("ГОЛОС", f"{display} пытался сменить голос, но он закреплён стримером")
    elif vc:                                     # !девочка / !мальчик / !сброс — выбор голоса
        if vc[0] == "reset":
            STATE.viewer_voices.pop(key, None)
            STATE.log("ГОЛОС", f"{display} вернул обычный голос")
            label, voice = "обычный", None
        else:
            label, voice = vc[1].get("label") or vc[1].get("cmd"), vc[1]["voice"]
            STATE.viewer_voices[key] = {"nick": str(display), "user": str(user), "acc": str(acc or ""),
                                        "voice": voice, "label": label, "cmd": vc[1].get("cmd"),
                                        "at": time.strftime("%Y-%m-%d %H:%M")}
            STATE.log("ГОЛОС", f"{display} выбрал голос «{label}»")
        save_viewer_voices()
        if STATE.config.get("tts_enabled") and STATE.config.get("voice_cmd_confirm", True):
            schedule(tts_speak(display, f"{display}, теперь у тебя голос: {label}", voice=voice, read_name=False))
    elif (fresh and STATE.config.get("tts_enabled") and str(text).strip()
            and tts_allowed(display, user, is_follower)):
        ok, say = tts_guard(display, user, text)
        if ok:
            schedule(tts_speak(display, say, voice=viewer_voice(user, acc, roles)))
    # Чат-команды зрителей (!моб, !дроп и т.д.) — работают для каждого сообщения
    if fresh and not vc:
        check_chat_command(text, display)
    if user in STATE.seen_users:
        return
    STATE.seen_users.add(user)
    STATE.log("ЧАТ", f"{display} написал первое сообщение")
    prof = active_profile()
    welcomes = prof.get("welcome", [])
    if not welcomes:
        return
    # Ищем приветствие с совпадающим ником (без учёта регистра и @)
    uname = str(user).strip().lstrip("@").lower()
    dname = str(display).strip().lstrip("@").lower()
    matched = None
    for w in welcomes:
        if not _is_enabled(w):
            continue
        target = str(w.get("nick", "")).strip().lstrip("@").lower()
        if target and (target == uname or target == dname):
            matched = w
            break
    if not matched:
        return  # для этого зрителя приветствие не настроено
    # Надпись (своя или дефолт) — показываем КРАСИВОЕ имя
    caption = matched.get("caption", "").strip() or "впервые в чате! 👋"
    caption = (caption.replace("{user}", str(display))
                      .replace("{nick}", STATE.config.get("minecraft_nick", "")))
    media = _extract_media(matched)
    STATE.log("ПРИВЕТСТВИЕ", f"Сработало для {display}")
    STATE.push_overlay("welcome", display, caption,
                       icon="👋", color="#a371f7", media=media)
    fire_action(matched, count=1, user=display,
                ctx={"comment": str(text), "uniqueid": str(user)})


# ── Подключение к TikTok (в отдельном потоке) ────────────────────────────────
def tiktok_worker():
    username = STATE.config.get("tiktok_username", "").strip().lstrip("@")
    if not username:
        STATE.log("ОШИБКА", "Не указан ник TikTok")
        STATE.connected = False
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    STATE.loop = loop

    client = TikTokLiveClient(unique_id=f"@{username}")
    STATE.tiktok_client = client

    @client.on(ConnectEvent)
    async def on_connect(event):
        STATE.connected = True
        STATE.connected_at = time.time()
        STATE.log("СИСТЕМА", f"✅ Подключено к @{username}")
        asyncio.ensure_future(fetch_ru_gift_names(client))     # русские названия — в фоне
        asyncio.ensure_future(fetch_room_gift_catalog(client))  # все подарки региона — в каталог

    @client.on(DisconnectEvent)
    async def on_disconnect(event):
        STATE.connected = False
        STATE.log("СИСТЕМА", "❌ Отключено от TikTok")

    def _names(event):
        """Возвращает (uid, красивое_имя) из события TikTok."""
        u = getattr(event, "user", None)
        uid = getattr(u, "unique_id", None) or "?"
        display = (getattr(u, "nickname", None)
                   or getattr(u, "nick_name", None)
                   or getattr(u, "display_name", None)
                   or uid)
        # запоминаем связку «красивое имя → @юзернейм» для переменной {uniqueid}
        if display and uid and uid != "?":
            STATE.last_uid[str(display)] = "@" + str(uid).lstrip("@")
            if len(STATE.last_uid) > 500:
                STATE.last_uid.clear()
        return uid, display

    @client.on(GiftEvent)
    async def on_gift(event):
        if STATE.stop_requested:
            return
        try:
            # Стрик-подарки (type 1): реагируем только в конце серии
            g = event.gift
            uid, display = _names(event)
            name = g.name if hasattr(g, "name") else str(g)
            gid = getattr(getattr(g, "info", None), "id", None) or getattr(g, "id", "")
            # repeat_count — сколько в серии
            count = getattr(event, "repeat_count", 1) or 1
            # Стоимость подарка в алмазах (для топа донатеров)
            diamonds = getattr(getattr(g, "info", None), "diamond_count", 0) or \
                       getattr(g, "diamond_count", 0) or 0
            # Запоминаем ссылку на иконку из самого события — она всегда актуальна
            try:
                for holder in (getattr(g, "image", None), getattr(g, "icon", None),
                               getattr(getattr(g, "info", None), "image", None)):
                    urls = (getattr(holder, "m_urls", None) or getattr(holder, "url_list", None)
                            or (holder.get("url_list") if isinstance(holder, dict) else None))
                    if urls:
                        key = str(name).strip().lower()
                        if STATE.live_gift_icons.get(key) != urls[0]:
                            STATE.live_gift_icons[key] = urls[0]
                            save_live_icons()
                            STATE.log("ИКОНКА", f"Запомнил иконку подарка «{name}»")
                        if gid and str(gid) not in STATE.gift_catalog.data["gifts"]:
                            STATE.gift_catalog.remember_live(gid, name, diamonds, urls[0])
                        break
            except Exception:
                pass
            streakable = getattr(g, "streakable", False) or (getattr(getattr(g, "info", None), "type", 0) == 1)
            if streakable:
                # Ждём конца серии
                if not getattr(event, "repeat_end", 1):
                    return
            handle_gift(name, gid, count, display, diamonds)
        except Exception as e:
            STATE.log("ОШИБКА", f"gift: {e}")

    @client.on(LikeEvent)
    async def on_like(event):
        if STATE.stop_requested:
            return
        try:
            uid, display = _names(event)
            # Сколько лайков пришло в ЭТОМ событии (TikTok шлёт пачками)
            # В разных версиях поле называется count / likeCount / likes
            n = (getattr(event, "count", None)
                 or getattr(event, "like_count", None)
                 or getattr(event, "likeCount", None)
                 or 1)
            handle_like(int(n), display)
        except Exception as e:
            STATE.log("ОШИБКА", f"like: {e}")

    if CommentEvent is not None:
        @client.on(CommentEvent)
        async def on_comment(event):
            if STATE.stop_requested:
                return
            try:
                uid, display = _names(event)
                text = getattr(event, "comment", "") or ""
                u = getattr(event, "user", None)
                fi = getattr(u, "follow_info", None)
                st = (getattr(fi, "follow_status", 0) or
                      getattr(u, "follow_status", 0) or 0)
                acc = getattr(u, "id", None) or getattr(u, "user_id", None)
                ident = getattr(event, "user_identity", None)
                roles = [r for r, a in (("moderator", "is_moderator_of_anchor"), ("superfan", "is_subscriber_of_anchor"),
                                        ("friend", "is_mutual_following_with_anchor"), ("gifter", "is_gift_giver_of_anchor"),
                                        ("follower", "is_follower_of_anchor")) if getattr(ident, a, False)]
                if (st or 0) >= 1 and "follower" not in roles:
                    roles.append("follower")
                handle_comment(uid, text, display, is_follower=(st or 0) >= 1, acc=acc, roles=roles)
            except Exception as e:
                STATE.log("ОШИБКА", f"comment: {e}")

    if SubscribeEvent is not None:
        @client.on(SubscribeEvent)
        async def on_sub(event):
            if STATE.stop_requested:
                return
            try:
                uid, display = _names(event)
                handle_sub(display)
            except Exception as e:
                STATE.log("ОШИБКА", f"sub: {e}")

    if FollowEvent is not None:
        @client.on(FollowEvent)
        async def on_follow(event):
            if STATE.stop_requested:
                return
            try:
                uid, display = _names(event)
                handle_follow(display)
            except Exception as e:
                STATE.log("ОШИБКА", f"follow: {e}")

    try:
        STATE.log("СИСТЕМА", f"Подключаюсь к @{username}...")
        client.run()
    except Exception as e:
        STATE.connected = False
        STATE.log("ОШИБКА", f"Не удалось подключиться: {e}")


def start_tiktok():
    if STATE.tiktok_thread and STATE.tiktok_thread.is_alive():
        return False, "Уже подключено"
    STATE.stop_requested = False
    STATE.tiktok_thread = threading.Thread(target=tiktok_worker, daemon=True)
    STATE.tiktok_thread.start()
    return True, "Запуск подключения..."


async def stop_tiktok():
    """Отключение от эфира. Сразу ставим флаг — события после этого игнорируются,
    даже если библиотека ещё не успела закрыть соединение."""
    STATE.stop_requested = True
    c, loop = STATE.tiktok_client, STATE.loop
    if c is not None and loop is not None and loop.is_running():
        try:
            if hasattr(c, "disconnect"):                       # TikTokLive 6.x
                fut = asyncio.run_coroutine_threadsafe(c.disconnect(close_client=True), loop)
                await asyncio.wait_for(asyncio.wrap_future(fut), timeout=8)
            elif hasattr(c, "stop"):                           # старые версии
                c.stop()
        except Exception as e:
            STATE.log("ОШИБКА", f"отключение от TikTok: {e}")
    th = STATE.tiktok_thread
    for _ in range(30):                                        # ждём, пока поток закроется
        if not (th and th.is_alive()):
            break
        await asyncio.sleep(0.1)
    if th and th.is_alive() and loop is not None:              # не закрылся — останавливаем цикл силой
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
    STATE.connected = False
    STATE.log("СИСТЕМА", "Остановлено")


# ── Веб-сервер (API + отдача редактора) ──────────────────────────────────────
async def h_index(request):
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read().replace("__VERSION__", APP_VERSION)
    return web.Response(text=html, content_type="text/html", charset="utf-8",
                        headers={"Cache-Control": "no-store"})


async def h_get_state(request):
    return web.json_response({
        "config": STATE.config,
        "profiles": STATE.profiles,
        "connected": STATE.connected,
        "like_counter": STATE.like_counter,
    })


async def h_get_log(request):
    # Каталог замеченных подарков (название, ID, сколько раз)
    gifts = [
        {"name": n, "id": info["id"], "count": info["count"], "diamonds": info["diamonds"]}
        for n, info in sorted(STATE.seen_gifts.items(), key=lambda x: -x[1]["count"])
    ]
    return web.json_response({"log": STATE.event_log[-80:], "seen_gifts": gifts})


async def h_save_config(request):
    data = await request.json()
    STATE.config.update(data)
    save_config()
    return web.json_response({"ok": True})


async def h_save_profiles(request):
    data = await request.json()
    STATE.profiles = data.get("profiles", STATE.profiles)
    save_profiles()
    return web.json_response({"ok": True})


async def h_connect(request):
    save_config()
    ok, msg = start_tiktok()
    return web.json_response({"ok": ok, "message": msg})


async def h_disconnect(request):
    await stop_tiktok()
    return web.json_response({"ok": True})


async def h_test_rcon(request):
    """Проверка связи с Minecraft (ServerTap или RCON — что выбрано)."""
    data = await request.json()
    STATE.config.update(data)
    save_config()
    ok, msg = await mc_ping()
    return web.json_response({"ok": ok, "message": msg})


async def h_test_action(request):
    """Тест-режим: выполнить действие + показать медиа на оверлее."""
    data = await request.json()
    action = data.get("action", {})
    count = data.get("count", 1)
    user = data.get("user", "ТестЗритель")
    STATE.log("ТЕСТ", f"Симуляция действия (x{count})")
    # Показываем медиа на оверлее (если у действия задано)
    media = _extract_media(action)
    if media:
        STATE.push_overlay("test", user, "тест медиа",
                           icon="🧪", color="#00d4ff", media=media)
    # Выполняем команды
    await run_chain(action, count=count, user=user)
    return web.json_response({"ok": True})


async def h_simulate(request):
    """Симулировать событие целиком (подарок/лайк/etc) для теста."""
    data = await request.json()
    kind = data.get("kind")
    user = data.get("user", "ТестЗритель")
    if kind == "gift":
        handle_gift(data.get("name", ""), data.get("gift_id", ""),
                    data.get("count", 1), user, data.get("diamonds", 10))
    elif kind == "like":
        # Симулируем пачку лайков — сбрасываем счётчик и шлём нужное количество
        target = data.get("count", 100)
        STATE.like_counter = 0
        handle_like(target, user)
    elif kind == "sub":
        handle_sub(user)
    elif kind == "follow":
        handle_follow(user)
    elif kind == "chat":
        handle_comment(user, data.get("text", "тест"), data.get("display"),
                       is_follower=bool(data.get("is_follower")))
    elif kind == "welcome":
        # Для теста разрешаем повторно (убираем из seen)
        STATE.seen_users.discard(user)
        handle_comment(user, "тест")
    return web.json_response({"ok": True})


async def h_overlay_data(request):
    """Данные для OBS-оверлеев: новые события, лента, топ, счётчики."""
    since = int(request.query.get("since", 0))
    # Только новые алерты (seq > since)
    new_events = [e for e in STATE.overlay_events if e["seq"] > since]
    # Топ донатеров (сортировка по алмазам)
    top = sorted(STATE.gifters.items(), key=lambda x: -x[1])[:10]
    top_list = [{"user": u, "amount": a} for u, a in top]
    # Топ по лайкам
    top_likes = sorted(STATE.likers.items(), key=lambda x: -x[1])[:10]
    top_likes_list = [{"user": u, "amount": a} for u, a in top_likes]
    return web.json_response({
        "seq": STATE.overlay_seq,
        "new_events": new_events,
        "feed": STATE.recent_feed[:15],
        "top": top_list,
        "top_likes": top_likes_list,
        "total_likes": STATE.total_likes,
        "connected": STATE.connected,
        "goals": [
            {"title": g.get("title") or f"Цель {g.get('target', 0)}",
             "metric": g.get("metric", "likes"),
             "target": int(g.get("target", 0) or 0),
             "current": _goal_current(g.get("metric", "likes")),
             "reached": (STATE.config.get("active_profile", ""), i) in STATE.goals_done}
            for i, g in enumerate(active_profile().get("goals", []))
            if _is_enabled(g) and int(g.get("target", 0) or 0) > 0
        ],
        "timer": {"running": STATE.timer["running"],
                  "remaining": int(_timer_remaining())},
    })


async def h_media_queue(request):
    """Очередь медиа-алертов для media.html оверлея."""
    since = int(request.query.get("since", 0))
    new_media = [m for m in STATE.media_queue if m["seq"] > since]
    return web.json_response({"seq": STATE.media_seq, "new_media": new_media})


# ── Медиа: длительность, превью и «починка» видео (mediaproc.py) ──
THUMBS_DIR = os.path.join(MEDIA_DIR, "_thumbs")
META_PATH = os.path.join(MEDIA_DIR, "_thumbs", "meta.json")
MEDIA_META = {}
MEDIA_JOBS = {}          # имя → {state: processing/error, progress, mode, error}


def _load_media_meta():
    try:
        with open(META_PATH, encoding="utf-8") as f:
            MEDIA_META.update(json.load(f))
    except Exception:
        pass


def _save_media_meta():
    try:
        os.makedirs(THUMBS_DIR, exist_ok=True)
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(MEDIA_META, f, ensure_ascii=False)
    except Exception:
        pass


def _thumb_name(name):
    return re.sub(r"[^\w.-]", "_", name) + ".jpg"


async def media_meta(name, force=False):
    """Длительность, размер кадра и превью; для видео — нужна ли «починка»."""
    import mediaproc as mp
    path = os.path.join(MEDIA_DIR, *name.split("/"))
    try:
        st = os.stat(path)
    except OSError:
        return None
    cur = MEDIA_META.get(name)
    if cur and not force and cur.get("mtime") == int(st.st_mtime) and cur.get("size") == st.st_size:
        return cur
    kind = _media_kind(name)
    meta = {"mtime": int(st.st_mtime), "size": st.st_size, "duration": 0, "w": 0, "h": 0, "thumb": "", "fix": ""}
    if kind in ("video", "sound") and mp.ffmpeg_exe():
        try:
            info = await mp.probe(path)
            meta.update(duration=round(info["duration"], 2), w=info["w"], h=info["h"])
            if kind == "video":
                mode = mp.plan(info, path)
                meta["fix"] = "" if mode == "ok" else mode
                os.makedirs(THUMBS_DIR, exist_ok=True)
                tn = _thumb_name(name)
                if await mp.thumbnail(path, os.path.join(THUMBS_DIR, tn), info["duration"]):
                    meta["thumb"] = "_thumbs/" + tn
        except Exception:
            pass
    MEDIA_META[name] = meta
    _save_media_meta()
    return meta


async def fix_video(name):
    """Делает видео гарантированно играющим в OBS: переупаковка или перекодирование."""
    import mediaproc as mp
    src = os.path.join(MEDIA_DIR, name)
    job = MEDIA_JOBS[name] = {"state": "processing", "progress": 0.0, "mode": "", "error": ""}
    try:
        if not mp.ffmpeg_exe():
            raise RuntimeError("нет ffmpeg — переустанови программу или запусти через start.bat")
        info = await mp.probe(src)
        mode = mp.plan(info, src)
        job["mode"] = mode
        if mode != "ok":
            base = name.rsplit(".", 1)[0]
            final = base + ".mp4"
            tmp = os.path.join(MEDIA_DIR, f".tmp_{base}.mp4")
            await mp.convert(src, tmp, mode, info["duration"], lambda p: job.update(progress=round(p, 3)))
            dst = os.path.join(MEDIA_DIR, final)
            os.replace(tmp, dst)
            if final != name:
                try:
                    os.remove(src)
                except OSError:
                    pass
                MEDIA_META.pop(name, None)
                MEDIA_JOBS[final] = job
            name = final
            STATE.log("МЕДИА", f"Видео «{final}» подготовлено для OBS ({ {'remux': 'переупаковано', 'audio': 'перекодирован звук', 'transcode': 'перекодировано'}[mode] })")
        await media_meta(name, force=True)
        job.update(state="done", progress=1.0, final=name)
    except Exception as e:
        job.update(state="error", error=str(e))
        STATE.log("ОШИБКА", f"видео «{name}»: {e}")


async def h_media_fix(request):
    d = await request.json()
    name = os.path.basename(str(d.get("name", "")))
    if not os.path.isfile(os.path.join(MEDIA_DIR, name)) or _media_kind(name) != "video":
        return web.json_response({"ok": False, "error": "нет такого видео"})
    if (MEDIA_JOBS.get(name) or {}).get("state") == "processing":
        return web.json_response({"ok": False, "error": "уже обрабатывается"})
    asyncio.ensure_future(fix_video(name))
    return web.json_response({"ok": True})


async def h_media_list(request):
    """Список загруженных медиафайлов."""
    files = []
    # Корень media/ плюс папки с готовыми картинками (mobs, demo_gifts).
    # tts/ и gifts/ не показываем — это служебные.
    def scan(folder, prefix=""):
        try:
            for fn in sorted(os.listdir(folder)):
                path = os.path.join(folder, fn)
                if os.path.isfile(path) and not fn.startswith("."):
                    kind = _media_kind(fn)
                    if kind != "other":
                        files.append({"name": prefix + fn, "kind": kind})
        except Exception:
            pass

    scan(MEDIA_DIR)
    for sub in ("mobs", "demo_gifts"):
        scan(os.path.join(MEDIA_DIR, sub), sub + "/")
    if not MEDIA_META:
        _load_media_meta()
    missing = []
    for f in files:
        f.update({k: v for k, v in (MEDIA_META.get(f["name"]) or {}).items() if k != "mtime"})
        job = MEDIA_JOBS.get(f["name"])
        if job and job.get("state") in ("processing", "error"):
            f["job"] = job
        if f["name"] not in MEDIA_META and f["kind"] in ("video", "sound", "image", "gif") and not f["name"].startswith(".tmp_"):
            missing.append(f["name"])
    files = [f for f in files if not f["name"].startswith(".tmp_")]
    if missing and not STATE.media_meta_busy:                     # превью и длительность — в фоне
        async def fill():
            STATE.media_meta_busy = True
            try:
                for n in missing[:40]:
                    await media_meta(n)
            finally:
                STATE.media_meta_busy = False
        asyncio.ensure_future(fill())
    return web.json_response({"files": files, "busy": bool(missing)})


def _media_kind(filename):
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("mp4", "webm", "mov", "mkv"):
        return "video"
    if ext == "gif":
        return "gif"
    if ext in ("png", "jpg", "jpeg", "webp", "bmp"):
        return "image"
    if ext in ("mp3", "wav", "ogg", "m4a"):
        return "sound"
    return "other"


async def h_media_upload(request):
    """Загрузка медиафайла с ПК в папку media/."""
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"ok": False, "error": "no file"}, status=400)
    filename = os.path.basename(field.filename or "file")
    # Безопасное имя
    filename = "".join(c for c in filename if c.isalnum() or c in "._- ()").strip()
    if not filename:
        filename = "media"
    dest = os.path.join(MEDIA_DIR, filename)
    size = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)
    kind = _media_kind(filename)
    if kind == "video":                       # любое видео → гарантированно играющее в OBS
        MEDIA_JOBS[filename] = {"state": "processing", "progress": 0.0, "mode": "", "error": ""}
        asyncio.ensure_future(fix_video(filename))
    else:
        asyncio.ensure_future(media_meta(filename, force=True))
    return web.json_response({"ok": True, "name": filename, "kind": kind, "size": size,
                              "processing": kind == "video"})


async def h_media_delete(request):
    """Удаление медиафайла."""
    data = await request.json()
    name = os.path.basename(data.get("name", ""))
    path = os.path.join(MEDIA_DIR, name)
    try:
        if os.path.isfile(path):
            os.remove(path)
        meta = MEDIA_META.pop(name, None)
        if meta and meta.get("thumb"):
            try:
                os.remove(os.path.join(MEDIA_DIR, meta["thumb"]))
            except OSError:
                pass
        _save_media_meta()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})


def _timer_remaining():
    t = STATE.timer
    if t["running"]:
        return max(0, t["end"] - time.time())
    return max(0, t.get("paused_left", 0))


async def fire_random_event(reason="таймер"):
    """Выбирает случайное событие и запускает: медиа на оверлей + команда разом."""
    import random as _rnd
    items = [i for i in (STATE.config.get("random_items") or []) if isinstance(i, dict)]
    if not items:
        # обратная совместимость со старым текстовым списком команд
        cmds = [l.strip() for l in str(STATE.config.get("random_commands", "")).splitlines()
                if l.strip()]
        items = [{"command": cmd} for cmd in cmds]
    # событие валидно если есть хоть что-то: команда, видео или звук
    items = [i for i in items
             if str(i.get("command", "")).strip() or i.get("media_file") or i.get("sound_file")]
    if not items:
        return False
    it = _rnd.choice(items)
    what = str(it.get("command", "")).strip() or it.get("media_file") or it.get("sound_file")
    STATE.log("СЛУЧАЙНОЕ", f"🎰 ({reason}) {what}")
    media = _extract_media(it)
    STATE.push_overlay("random", "", "🎰 Случайное событие!",
                       icon="🎰", color="#a78bfa", media=media)
    cmd = str(it.get("command", "")).strip()
    if cmd:
        await run_chain({"commands": [cmd], "delays": [0]}, count=1,
                        user=STATE.config.get("minecraft_nick", ""))
    return True


async def h_random_fire(request):
    """Тест-кнопка: запустить случайное событие прямо сейчас."""
    ok = await fire_random_event("тест")
    return web.json_response({"ok": ok,
                              "message": "Запущено!" if ok else "Нет ни одного события — добавь хотя бы команду, видео или звук"})


async def h_timer(request):
    """GET — статус; POST — управление таймером (start/pause/reset/add)."""
    if request.method == "GET":
        return web.json_response({"running": STATE.timer["running"],
                                  "remaining": int(_timer_remaining())})
    data = await request.json()
    # Сохраняем настройки таймера если пришли
    for k in ("timer_start_min", "timer_sec_per_coin", "timer_end_command"):
        if k in data:
            STATE.config[k] = data[k]
    save_config()
    act = data.get("action", "")
    t = STATE.timer
    if act == "start":
        left = _timer_remaining()
        if left <= 0:
            try:
                left = float(STATE.config.get("timer_start_min", 30)) * 60
            except Exception:
                left = 1800
        t["end"] = time.time() + left
        t["running"] = True
        t["fired"] = False
        STATE.log("ТАЙМЕР", f"▶ Запущен ({int(left)} сек)")
    elif act == "pause":
        t["paused_left"] = _timer_remaining()
        t["running"] = False
        STATE.log("ТАЙМЕР", "⏸ Пауза")
    elif act == "reset":
        t["running"] = False
        t["paused_left"] = 0
        t["fired"] = False
        STATE.log("ТАЙМЕР", "⟲ Сброшен")
    elif act == "add":
        try:
            sec = float(data.get("seconds", 60))
        except Exception:
            sec = 60
        if t["running"]:
            t["end"] += sec
        else:
            t["paused_left"] = _timer_remaining() + sec
    return web.json_response({"running": t["running"],
                              "remaining": int(_timer_remaining())})


async def h_panel_fire(request):
    """Кнопка панели стримера: выполнить действие."""
    data = await request.json()
    idx = int(data.get("index", -1))
    prof = active_profile()
    panel = prof.get("panel", [])
    if idx < 0 or idx >= len(panel):
        return web.json_response({"ok": False, "error": "кнопка не найдена"})
    a = panel[idx]
    title = a.get("title") or f"Кнопка {idx+1}"
    STATE.log("ПАНЕЛЬ", f"🎛 {title}")
    media = _extract_media(a)
    if media:
        STATE.push_overlay("panel", "", title, icon="🎛", color="#a78bfa", media=media)
    await run_chain(a, count=1, user=STATE.config.get("minecraft_nick", ""))
    return web.json_response({"ok": True})


async def h_stream_report(request):
    """Итоги стрима — скачиваемый текстовый отчёт."""
    top_g = sorted(STATE.gifters.items(), key=lambda x: -x[1])[:10]
    top_l = sorted(STATE.likers.items(), key=lambda x: -x[1])[:10]
    lines = [
        "═" * 46,
        "  ИТОГИ СТРИМА",
        f"  Начало: {STATE.stream_started}",
        f"  Отчёт:  {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "═" * 46, "",
        f"❤ Всего лайков: {STATE.total_likes}",
        f"🎁 Подарков: {STATE.gifts_count} (на {sum(STATE.gifters.values())} монет)",
        f"➕ Новых фолловеров: {STATE.follow_count}",
        f"⭐ Подписок: {STATE.sub_count}",
        f"👋 Писало в чат: {len(STATE.seen_users)} человек", "",
        "─── ТОП ДОНАТЕРОВ ───",
    ]
    lines += [f"  {i+1}. {u} — {a} 💎" for i, (u, a) in enumerate(top_g)] or ["  (никто)"]
    lines += ["", "─── ТОП ПО ЛАЙКАМ ───"]
    lines += [f"  {i+1}. {u} — {a} ❤" for i, (u, a) in enumerate(top_l)] or ["  (никто)"]
    lines += ["", "─── ДОСТИГНУТЫЕ ЦЕЛИ ───"]
    prof = active_profile()
    goals = prof.get("goals", [])
    done = [g.get("title") or f"Цель {g.get('target')}" for i, g in enumerate(goals)
            if (STATE.config.get("active_profile", ""), i) in STATE.goals_done]
    lines += [f"  🎯 {t}" for t in done] or ["  (нет)"]
    text = "\n".join(lines)
    fname = "итоги_стрима.txt"
    from urllib.parse import quote
    return web.Response(text=text, content_type="text/plain", charset="utf-8",
                        headers={"Content-Disposition":
                                 f"attachment; filename*=UTF-8''{quote(fname)}"})


async def h_gift_showcase(request):
    """Данные для витрины: подарки, лайки, подписки, фолловы, чат-команды."""
    # иконки из media/gifts (имя_подарка.png)
    icons = {}
    gdir = os.path.join(MEDIA_DIR, "gifts")
    try:
        for fn in os.listdir(gdir):
            base, dot, ext = fn.rpartition(".")
            if ext.lower() in ("png", "jpg", "jpeg", "webp", "gif"):
                icons[base.strip().lower()] = "gifts/" + fn
    except Exception:
        pass

    prof = active_profile()
    show = STATE.config.get("showcase_types") or ["gifts"]
    EMOJI = {"gifts": "🎁", "likes": "❤", "subs": "⭐",
             "follows": "➕", "chatcmds": "💬", "welcome": "👋"}
    items = []

    def add(section, a, name, badge=""):
        if a.get("showcase") is False:
            return   # кнопка «🎁 На витрине» выключена
        img = ""
        if a.get("icon_file"):
            img = a["icon_file"]
        elif a.get("media_file") and a.get("media_kind") in ("image", "gif"):
            img = a["media_file"]
        elif section == "gifts" and icons.get(name.lower()):
            img = icons[name.lower()]
        elif section == "gifts":
            img = gift_icon_url(name)
        if badge == img:
            badge = ""
        try:
            mult = int(a.get("multiplier", 1) or 1)
        except Exception:
            mult = 1
        items.append({
            "name": name, "image": img, "badge": badge, "count": mult,
            "label": str(a.get("title", "")).strip(),
            "kind": section, "emoji": EMOJI.get(section, "🎁"),
        })

    for a in prof.get("gifts", []) if "gifts" in show else []:
        if not _is_enabled(a):
            continue
        nm = str(a.get("name", "")).strip()
        if nm:
            add("gifts", a, nm, icons.get(nm.lower(), "") or gift_icon_url(nm))

    for a in prof.get("likes", []) if "likes" in show else []:
        if not _is_enabled(a):
            continue
        try:
            th = int(a.get("threshold", 100) or 100)
        except Exception:
            th = 100
        add("likes", a, f"{th} лайков")

    for a in prof.get("subs", []) if "subs" in show else []:
        if _is_enabled(a):
            add("subs", a, "Подписка")

    for a in prof.get("follows", []) if "follows" in show else []:
        if _is_enabled(a):
            add("follows", a, "Фоллов")

    for a in prof.get("chatcmds", []) if "chatcmds" in show else []:
        if not _is_enabled(a):
            continue
        trig = str(a.get("trigger", "")).strip()
        if trig:
            add("chatcmds", a, trig)

    return web.json_response({
        "items": items, "last": STATE.last_gift,
        "anim": STATE.config.get("showcase_anim", "grid"),
        "speed": STATE.config.get("showcase_speed", 5),
        "per_row": STATE.config.get("showcase_per_row", 7),
        "rows": STATE.config.get("showcase_rows", 3),
        "icon": STATE.config.get("showcase_icon", 88),
        "trans_grid": STATE.config.get("showcase_trans_grid", "pulse"),
        "trans_list": STATE.config.get("showcase_trans_list", "scroll"),
        # новая схема: движение и эффект отдельно (старые настройки переводятся сами)
        "motion": STATE.config.get("showcase_motion")
                  or ("step" if STATE.config.get("showcase_trans_list") == "step" else "smooth"),
        "effect": STATE.config.get("showcase_effect")
                  or (STATE.config.get("showcase_trans_list")
                      if STATE.config.get("showcase_trans_list") in ("glow", "breathe") else "none"),
        "badge": STATE.config.get("showcase_badge", "br"),
        "badge_size": STATE.config.get("showcase_badge_size", 38),
    })


async def h_gift_catalog(request):
    return web.json_response(STATE.gift_catalog.public())


async def h_gift_catalog_fetch(request):
    """🌍 Загрузить подарки региона — прямо у TikTok, без подключения к эфиру."""
    d = await request.json()
    region = str(d.get("region") or "").upper().strip()
    if not re.fullmatch(r"[A-Z]{2}", region):
        return web.json_response({"ok": False, "error": "выбери регион"})
    try:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.client.web.web_settings import WebDefaults
        cl = TikTokLiveClient(unique_id="tiktok")
        try:
            res = await STATE.gift_catalog.fetch_region(region, cl.web.get, WebDefaults.tiktok_webcast_url + "/gift/list/")
        finally:
            try:
                await cl.web.close()
            except Exception:
                pass
        return web.json_response({"ok": True, **res})
    except Exception as e:
        return web.json_response({"ok": False, "error": f"TikTok не ответил: {e}"})


async def h_gift_icons(request):
    """Список картинок подарков из media/gifts (кладёт сам пользователь)."""
    icons = {}
    gdir = os.path.join(MEDIA_DIR, "gifts")
    try:
        for fn in os.listdir(gdir):
            base, dot, ext = fn.rpartition(".")
            if ext.lower() in ("png", "jpg", "jpeg", "webp", "gif"):
                icons[base.strip().lower()] = "gifts/" + fn
    except Exception:
        pass
    online = {}
    if STATE.config.get("gift_icons_online", True):
        online = dict(GIFT_ICON_URLS)
        online.update(STATE.live_gift_icons)
    return web.json_response({"icons": icons, "online": online, "ids": GIFT_IDS, "ru": STATE.gift_names_ru})


# ── Версия программы — меняется при каждой новой сборке ─────────────────────
APP_VERSION = "1.65.3"
APP_DATE = "2026-11-07"


def load_changelog():
    try:
        with open(os.path.join(BASE_DIR, "changelog.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


async def h_version(request):
    return web.json_response({"version": APP_VERSION, "date": APP_DATE, "changelog": load_changelog()})


# ── Мосты для модов игр ──────────────────────────────────────────────────────
async def h_mod_poll(request):
    """Мод игры забирает новые команды. fmt=text — простой текст для C#/Lua."""
    game = request.query.get("game", "")
    if game not in MOD_GAMES:
        return web.json_response({"ok": False, "error": "неизвестная игра"}, status=404)
    STATE.mod_seen[game] = time.time()
    try:
        since = int(request.query.get("since", "-1"))
    except ValueError:
        since = -1
    q = STATE.mod_queue.get(game, [])
    if since < 0:
        items = []                                   # первое подключение — старое не шлём
    elif since > STATE.mod_seq:
        items = list(q)                              # программу перезапускали — шлём всё новое
    else:
        items = [x for x in q if x["id"] > since]
    if request.query.get("fmt") == "text":
        clean = lambda s: str(s).replace("|", "/").replace("\r", " ").replace("\n", " ")
        lines = [f"last={STATE.mod_seq}"] + \
                [f'{x["id"]}|{clean(x["user"])}|{str(x["cmd"]).replace(chr(13), " ").replace(chr(10), " ")}'
                 for x in items]
        return web.Response(text="\n".join(lines) + "\n", content_type="text/plain", charset="utf-8")
    return web.json_response({"last": STATE.mod_seq, "commands": items})


async def h_game_try(request):
    """Попробовать одну команду прямо сейчас — в игре активной вкладки.
    delay — пауза перед выполнением (успеть переключиться в окно игры для клавиатуры)."""
    data = await request.json()
    cmd = str(data.get("cmd", "")).strip()
    if not cmd:
        return web.json_response({"ok": False, "error": "пустая команда"})
    try:
        delay = max(0.0, min(10.0, float(data.get("delay", 0) or 0)))
    except (TypeError, ValueError):
        delay = 0.0
    if cmd.lower().startswith(KB_PREFIXES):
        try:
            kb_plan(cmd)
        except ValueError as e:
            return web.json_response({"ok": False, "error": str(e)})

    async def go():
        if delay:
            await asyncio.sleep(delay)
        c = fill_vars(cmd, count=1, user="Тест",
                      ctx={"giftname": "Rose", "coins": 1, "comment": "тест", "index": 1, "repetition": 1})
        STATE.log("ПРОБА", c)
        await game_send(c, "Тест")

    schedule(go())
    return web.json_response({"ok": True, "game": active_profile().get("game") or "minecraft", "delay": delay})


async def h_game_ping(request):
    data = await request.json()
    game = str(data.get("game", ""))
    cfg_part = {k: v for k, v in data.items() if k != "game"}
    if cfg_part:
        STATE.config.update(cfg_part)
        save_config()
    ok, msg = await game_ping(game)
    return web.json_response({"ok": ok, "message": msg})


async def h_templates(request):
    """Готовые шаблоны вкладок из папки templates/ (можно добавлять свои)."""
    order = ["minecraft", "gta5", "cs2", "ark", "rust", "palworld", "zomboid", "7dtd", "valheim", "keyboard"]
    out = []
    tdir = os.path.join(BASE_DIR, "templates")
    try:
        names = sorted(os.listdir(tdir))
    except Exception:
        names = []
    for fn in names:
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(tdir, fn), encoding="utf-8") as f:
                t = json.load(f)
            prof = t.get("profile") or {}
            counts = {k: len(prof.get(k, [])) for k in
                      ("gifts", "likes", "subs", "follows", "chatcmds", "goals", "panel") if prof.get(k)}
            out.append({"id": fn[:-5], "title": t.get("title", fn[:-5]), "game": t.get("game", "minecraft"),
                        "icon": t.get("icon", "📦"), "description": t.get("description", ""),
                        "counts": counts, "profile": prof})
        except Exception as e:
            STATE.log("ОШИБКА ШАБЛОНА", f"{fn}: {e}")
    out.sort(key=lambda t: (order.index(t["game"]) if t["game"] in order else 99, t["title"]))
    return web.json_response({"templates": out})


async def h_mod_log(request):
    """Мод сообщает об ошибке или событии — попадает в «Лог событий»."""
    try:
        data = dict(await request.post())
        if not data:
            data = await request.json()
    except Exception:
        data = {}
    game = str(data.get("game", ""))
    text = str(data.get("text", "")).strip()[:300]
    if text:
        STATE.log(f"МОД {MOD_GAMES.get(game, game).upper()}", text)
    return web.json_response({"ok": True})


async def h_mod_status(request):
    now = time.time()
    games = {}
    for g, name in MOD_GAMES.items():
        seen = STATE.mod_seen.get(g)
        games[g] = {"name": name, "connected": mod_connected(g),
                    "ago": round(now - seen, 1) if seen else None,
                    "file": f"/mods/{MOD_FOLDERS.get(g, g)}/"}
    return web.json_response({"games": games, "keyboard": sys.platform == "win32"})


async def h_mod_open_folder(request):
    """Открыть папку с модом в проводнике (чтобы скопировать файл в игру)."""
    data = await request.json()
    path = os.path.join(MODS_DIR, MOD_FOLDERS.get(str(data.get("game", "")), ""))
    if not os.path.isdir(path):
        return web.json_response({"ok": False, "error": "папка мода не найдена: " + path})
    try:
        if sys.platform == "win32":
            os.startfile(path)
            return web.json_response({"ok": True, "path": path})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e), "path": path})
    return web.json_response({"ok": False, "error": "открыть папку можно только на Windows", "path": path})


async def h_tts_stop(request):
    """⏹ — останавливает текущее и выкидывает очередь (и в программе, и в оверлее OBS)."""
    STATE.tts_epoch += 1
    STATE.tts_queue.clear()
    dropped = 0
    while True:
        try:
            TTS_PLAY_QUEUE.get_nowait()
            dropped += 1
        except _queue.Empty:
            break
    STATE.log("ОЗВУЧКА", "Остановлено" + (f", из очереди убрано: {dropped}" if dropped else ""))
    return web.json_response({"ok": True, "dropped": dropped})


async def h_tts_skip(request):
    """⏭ — пропустить только то, что звучит сейчас."""
    STATE.tts_skip += 1
    return web.json_response({"ok": True})


# ── Перенос данных из старой папки программы (портативная версия → установленная) ──
MIGRATE_FILES = ["config.json", "profiles.json", "viewer_voices.json", "fish_key.txt", "gift_icons_live.json",
                 "gift_names_ru.json", "gift_catalog.json"]
MIGRATE_DIRS = ["servers", "java", "steamcmd"]


def _is_app_folder(path):
    return (os.path.isfile(os.path.join(path, "profiles.json")) or os.path.isfile(os.path.join(path, "config.json"))) \
        and (os.path.isfile(os.path.join(path, "app.py")) or any(f.endswith(".exe") for f in os.listdir(path)))


async def h_migrate_find(request):
    """Ищет старые папки программы на рабочем столе, в загрузках и документах."""
    home = os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in ("Desktop", "Рабочий стол", "Downloads", "Загрузки", "Documents", "Документы")]
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for d1 in [root] + [os.path.join(root, x) for x in os.listdir(root) if os.path.isdir(os.path.join(root, x))]:
            try:
                if os.path.abspath(d1) != os.path.abspath(BASE_DIR) and _is_app_folder(d1):
                    n = 0
                    try:
                        with open(os.path.join(d1, "profiles.json"), encoding="utf-8") as f:
                            n = len(json.load(f))
                    except Exception:
                        pass
                    found.append({"path": d1, "tabs": n})
            except OSError:
                continue
    return web.json_response({"items": found[:10]})


async def h_migrate(request):
    """Копирует настройки, вкладки, голоса зрителей, серверы и медиа из старой папки."""
    d = await request.json()
    src = os.path.abspath(str(d.get("path") or "").strip().strip('"'))
    if not os.path.isdir(src) or not _is_app_folder(src):
        return web.json_response({"ok": False, "error": "в этой папке нет данных программы (config.json / profiles.json)"})
    if src == os.path.abspath(BASE_DIR):
        return web.json_response({"ok": False, "error": "это и есть текущая папка программы"})
    copied = []
    loop = asyncio.get_event_loop()

    def work():
        for f in MIGRATE_FILES:
            if os.path.isfile(os.path.join(src, f)):
                shutil.copy2(os.path.join(src, f), os.path.join(BASE_DIR, f))
                copied.append(f)
        for dn in MIGRATE_DIRS:
            if os.path.isdir(os.path.join(src, dn)):
                shutil.copytree(os.path.join(src, dn), os.path.join(BASE_DIR, dn), dirs_exist_ok=True)
                copied.append(dn + "/")
        msrc = os.path.join(src, "media")
        if os.path.isdir(msrc):                        # свои картинки и звуки — без замены программных
            n = 0
            for root, _dirs, files in os.walk(msrc):
                rel = os.path.relpath(root, msrc)
                if rel.split(os.sep)[0] in ("tts",):
                    continue
                for fn in files:
                    dst = os.path.join(MEDIA_DIR, rel, fn)
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(os.path.join(root, fn), dst)
                        n += 1
            if n:
                copied.append(f"media ({n} файлов)")
    await loop.run_in_executor(None, work)
    load_config()
    STATE.viewer_voices.clear()
    STATE.viewer_voices.update(load_viewer_voices())
    STATE.gift_names_ru.update(load_gift_names_ru())
    STATE.log("ПЕРЕНОС", f"Из {src} перенесено: {', '.join(copied) or 'ничего'}")
    return web.json_response({"ok": True, "copied": copied, "tabs": len(STATE.profiles)})


async def h_tts_check(request):
    """«🧪 Проверить фразу» в настройках: что сделает защита с этим сообщением."""
    import textfilter as tf
    d = await request.json()
    text = str(d.get("text", ""))
    cfg = STATE.config
    why = tf.junk_reason(text) if cfg.get("tts_skip_junk", True) else None
    extra = [w for w in str(cfg.get("tts_bad_words", "")).replace("\n", ",").split(",") if w.strip()]
    clean, bad = tf.censor(text, extra)
    mode = cfg.get("tts_profanity", "beep")
    if why:
        return web.json_response({"ok": False, "verdict": f"не прочитаю: {why}"})
    if bad and mode == "skip":
        return web.json_response({"ok": False, "verdict": "не прочитаю: мат"})
    say = tf.collapse(clean if bad and mode == "beep" else text)
    return web.json_response({"ok": True, "verdict": f"прочитаю: «{say}»", "bad": bad})


async def h_viewer_voices(request):
    items = [{"key": k, **v} for k, v in STATE.viewer_voices.items()]
    items.sort(key=lambda x: x.get("at", ""), reverse=True)
    return web.json_response({"items": items, "stats": STATE.tts_guard_stats})


async def h_viewer_voices_remove(request):
    d = await request.json()
    STATE.viewer_voices.pop(str(d.get("key", "")), None)
    save_viewer_voices()
    return web.json_response({"ok": True, "left": len(STATE.viewer_voices)})


async def h_viewer_voices_set(request):
    """⭐ Голос «особенному» зрителю вручную. key — из списка недавних, иначе по нику."""
    d = await request.json()
    key = str(d.get("key") or "").strip()
    if not key:
        nick = str(d.get("nick") or "").strip().lstrip("@")
        if not nick:
            return web.json_response({"ok": False, "error": "впиши ник зрителя"})
        hit = next((v for v in STATE.recent_viewers.values()
                    if nick.lower() in (v["nick"].lower(), v["user"].lower())), None)
        key = hit["key"] if hit else "@" + nick.lower()
    old = STATE.viewer_voices.get(key, {})
    rv = STATE.recent_viewers.get(key, {})
    entry = {**old,
             "nick": old.get("nick") or rv.get("nick") or str(d.get("nick") or key).lstrip("@"),
             "user": old.get("user") or rv.get("user") or key.lstrip("@"),
             "acc": old.get("acc") or rv.get("acc", ""),
             "at": time.strftime("%Y-%m-%d %H:%M")}
    if "voice" in d:
        entry["voice"] = str(d["voice"])
        entry["label"] = str(d.get("label") or "").strip() or "особый"
        entry["cmd"] = "вручную"
    if "pinned" in d:
        entry["pinned"] = bool(d["pinned"])
    if not entry.get("voice"):
        return web.json_response({"ok": False, "error": "выбери голос"})
    STATE.viewer_voices[key] = entry
    save_viewer_voices()
    STATE.log("ГОЛОС", f"Стример назначил {entry['nick']} голос «{entry['label']}»" + (" 📌" if entry.get("pinned") else ""))
    return web.json_response({"ok": True, "key": key})


async def h_viewers_recent(request):
    items = list(STATE.recent_viewers.values())[::-1]
    return web.json_response({"items": items})


async def h_viewer_voices_clear(request):
    d = await request.json() if request.can_read_body else {}
    keep = {k: v for k, v in STATE.viewer_voices.items() if v.get("pinned") and not d.get("all")}
    n = len(STATE.viewer_voices) - len(keep)
    STATE.viewer_voices.clear()
    STATE.viewer_voices.update(keep)
    save_viewer_voices()
    STATE.log("ГОЛОС", f"Голоса зрителей очищены ({n})" + (f", закреплённые оставлены ({len(keep)})" if keep else ""))
    return web.json_response({"ok": True, "removed": n, "kept": len(keep)})


async def h_tts_queue(request):
    """Очередь озвучки для tts.html оверлея."""
    since = int(request.query.get("since", 0))
    new_items = [t for t in STATE.tts_queue if t["seq"] > since]
    return web.json_response({"seq": STATE.tts_seq, "new_tts": new_items,
                              "epoch": STATE.tts_epoch, "skip": STATE.tts_skip})


async def h_tts_diag(request):
    """Пошаговая диагностика озвучки: библиотека → генерация → звук."""
    report = []
    # Шаг 1: движок
    voice_sel = STATE.config.get("tts_voice", "ru-RU-DmitryNeural")
    if voice_sel.startswith("fish:"):
        has_key = bool(str(STATE.config.get("fish_api_key", "")).strip())
        report.append({"ok": has_key, "step": "1. Движок Fish Audio",
                       "detail": ("ключ задан, модель " + str(STATE.config.get("fish_model")))
                                 if has_key else "НЕ ЗАДАН API-КЛЮЧ — получи на fish.audio/app/api-keys"})
        if not has_key:
            return web.json_response({"report": report})
    elif voice_sel.startswith("gt:"):
        report.append({"ok": True, "step": "1. Движок Google TTS",
                       "detail": "библиотеки не нужны, работает через обычный HTTPS"})
    else:
        try:
            import edge_tts
            ver = getattr(edge_tts, "__version__", "?")
            report.append({"ok": True, "step": "1. Библиотека edge-tts",
                           "detail": f"установлена (версия {ver})"})
        except ImportError:
            report.append({"ok": False, "step": "1. Библиотека edge-tts",
                           "detail": "НЕ УСТАНОВЛЕНА! Выбери голос Google (⚡ вверху списка) — он работает без библиотеки. Или выполни: pip install edge-tts"})
            return web.json_response({"report": report})
    # Шаг 2: генерация (интернет к сервису Microsoft)
    import time as _t
    path = os.path.join(MEDIA_DIR, "tts", "diag.mp3")
    t0 = _t.time()
    try:
        voice = STATE.config.get("tts_voice", "ru-RU-DmitryNeural")
        await asyncio.wait_for(
            _tts_generate("Проверка озвучки чата. Раз, два, три.", voice, path),
            timeout=20)
        size = os.path.getsize(path)
        ok = size > 1000
        report.append({"ok": ok, "step": "2. Генерация голоса (интернет)",
                       "detail": f"файл {size} байт за {_t.time()-t0:.1f} сек, голос {voice}"})
        if not ok:
            return web.json_response({"report": report})
    except Exception as e:
        report.append({"ok": False, "step": "2. Генерация голоса (интернет)",
                       "detail": (f"ошибка: {e}. Устарела библиотека edge-tts — перезапусти программу, "
                                  "она обновит её сама (или в консоли: pip install -U edge-tts)")
                                 if "403" in str(e) else
                                 f"ошибка: {e}. Проверь интернет / антивирус / файрвол"})
        return web.json_response({"report": report})
    # Шаг 3: воспроизведение через Windows
    if sys.platform != "win32":
        report.append({"ok": False, "step": "3. Воспроизведение",
                       "detail": "работает только на Windows"})
    else:
        def _play():
            _mci(f'open "{path}" type mpegvideo alias diagclip')
            try:
                _mci("setaudio diagclip volume to 1000")
                _mci("play diagclip wait")
            finally:
                try:
                    _mci("close diagclip")
                except Exception:
                    pass
        try:
            await asyncio.get_event_loop().run_in_executor(None, _play)
            report.append({"ok": True, "step": "3. Воспроизведение",
                           "detail": "проиграно! Ты должен был УСЛЫШАТЬ голос только что. Если тишина — проверь громкость Windows и устройство вывода звука"})
        except Exception as e:
            report.append({"ok": False, "step": "3. Воспроизведение",
                           "detail": f"ошибка Windows: {e}"})
    return web.json_response({"report": report})


async def h_tts_test(request):
    """Тест голоса: озвучить фразу с текущими настройками."""
    data = await request.json()
    STATE.config.update({k: v for k, v in data.items() if k.startswith("tts_")})
    save_config()
    text = data.get("text") or "Привет! Это проверка озвучки чата."
    ok = await tts_speak(data.get("user", "Стример"), text)
    msg = ("Готово! Открой оверлей озвучки и слушай "
           "(в браузере нажми «Включить звук» если появится кнопка)"
           if ok else STATE.tts_last_error or "Ошибка генерации")
    return web.json_response({"ok": bool(ok), "message": msg})


def _collect_profile_media(profile):
    """Собирает имена всех медиафайлов, используемых в профиле."""
    files = set()
    for section in ("gifts", "likes", "subs", "follows", "welcome", "chatcmds", "goals", "panel"):
        for action in profile.get(section, []):
            for key in ("media_file", "sound_file", "icon_file"):
                fn = action.get(key)
                if fn:
                    files.add(fn)
    return files


async def h_export_zip(request):
    """Экспорт профиля в ZIP: profile.json + все медиафайлы."""
    if request.method == "POST":
        data = await request.json()
        name = data.get("name", "")
    else:
        name = request.query.get("name", "")
    profile = STATE.profiles.get(name)
    if profile is None:
        return web.json_response({"ok": False, "error": "профиль не найден"}, status=404)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Сам профиль
        z.writestr("profile.json", json.dumps(
            {"name": name, "profile": profile}, ensure_ascii=False, indent=2))
        # Медиафайлы в подпапку media/
        for fn in _collect_profile_media(profile):
            src = os.path.join(MEDIA_DIR, fn)
            if os.path.isfile(src):
                z.write(src, arcname="media/" + fn)
    buf.seek(0)

    safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "profile"
    return web.Response(
        body=buf.read(),
        headers={
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
        },
    )


async def h_import_zip(request):
    """Импорт профиля из ZIP: распаковывает медиа и добавляет профиль."""
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"ok": False, "error": "нет файла"}, status=400)

    # Читаем zip в память
    data = b""
    while True:
        chunk = await field.read_chunk()
        if not chunk:
            break
        data += chunk

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            # Профиль
            with z.open("profile.json") as pf:
                pdata = json.loads(pf.read().decode("utf-8"))
            name = pdata.get("name", "Импорт")
            profile = pdata.get("profile", {})
            # Распаковываем медиа в папку media/
            extracted = 0
            for item in z.namelist():
                if item.startswith("media/") and not item.endswith("/"):
                    # сохраняем подпапки (mobs/, gifts/…), но не даём выйти за пределы media/
                    rel = os.path.normpath(item[len("media/"):]).replace("\\", "/")
                    if not rel or rel.startswith("..") or os.path.isabs(rel) or ":" in rel:
                        continue
                    dst_path = os.path.join(MEDIA_DIR, rel)
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    with z.open(item) as src:
                        with open(dst_path, "wb") as dst:
                            dst.write(src.read())
                    extracted += 1
    except Exception as e:
        return web.json_response({"ok": False, "error": f"не удалось прочитать ZIP: {e}"})

    # Уникальное имя профиля
    final = name
    n = 2
    while final in STATE.profiles:
        final = f"{name} {n}"
        n += 1
    STATE.profiles[final] = {k: profile.get(k, []) for k in
                             ("gifts", "likes", "subs", "follows", "welcome", "chatcmds", "goals", "panel")}
    if profile.get("game"):
        STATE.profiles[final]["game"] = profile["game"]
    save_profiles()
    return web.json_response({"ok": True, "name": final, "media_count": extracted})


def make_app():
    app = web.Application()

    async def _on_startup(app):
        STATE.web_loop = asyncio.get_event_loop()

        async def _background():
            import random as _rnd
            while True:
                await asyncio.sleep(1)
                try:
                    # Таймер-челлендж: время вышло
                    t = STATE.timer
                    if t["running"] and time.time() >= t["end"] and not t["fired"]:
                        t["running"] = False
                        t["fired"] = True
                        t["paused_left"] = 0
                        STATE.log("ТАЙМЕР", "⏰ ВРЕМЯ ВЫШЛО!")
                        STATE.push_overlay("timer", "", "⏰ ВРЕМЯ ВЫШЛО!",
                                           icon="⏰", color="#f87171")
                        cmd = str(STATE.config.get("timer_end_command", "")).strip()
                        if cmd:
                            await run_chain({"commands": [cmd], "delays": [0]},
                                            count=1,
                                            user=STATE.config.get("minecraft_nick", ""))
                    # Случайные события
                    if (STATE.config.get("random_enabled") and STATE.connected):
                        try:
                            interval = float(STATE.config.get("random_interval_sec", 300) or 300)
                        except Exception:
                            interval = 300
                        if time.time() - STATE.random_last >= interval:
                            STATE.random_last = time.time()
                            await fire_random_event("таймер")
                except Exception as e:
                    STATE.log("ОШИБКА", f"фоновая задача: {e}")

        asyncio.get_event_loop().create_task(_background())

    app.on_startup.append(_on_startup)

    # Middleware: запрещаем браузеру кешировать страницу и скрипты редактора,
    # чтобы после обновления программы всегда грузилась свежая версия.
    @web.middleware
    async def no_cache(request, handler):
        resp = await handler(request)
        path = request.path
        if path == "/" or path.startswith("/web/") or path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        return resp

    app.middlewares.append(no_cache)
    app.router.add_get("/", h_index)
    app.router.add_get("/api/state", h_get_state)
    app.router.add_get("/api/log", h_get_log)
    app.router.add_get("/api/overlay", h_overlay_data)
    app.router.add_post("/api/config", h_save_config)
    app.router.add_post("/api/profiles", h_save_profiles)
    app.router.add_post("/api/connect", h_connect)
    app.router.add_post("/api/disconnect", h_disconnect)
    app.router.add_post("/api/test_rcon", h_test_rcon)
    app.router.add_post("/api/test_action", h_test_action)
    app.router.add_post("/api/simulate", h_simulate)
    app.router.add_get("/api/media_queue", h_media_queue)
    app.router.add_get("/api/media_list", h_media_list)
    app.router.add_post("/api/media_upload", h_media_upload)
    app.router.add_post("/api/media/fix", h_media_fix)
    app.router.add_post("/api/media_delete", h_media_delete)
    app.router.add_get("/api/export_zip", h_export_zip)
    app.router.add_post("/api/export_zip", h_export_zip)
    app.router.add_post("/api/import_zip", h_import_zip)
    app.router.add_get("/api/gift_icons", h_gift_icons)
    app.router.add_get("/api/gift_showcase", h_gift_showcase)
    app.router.add_get("/api/tts_queue", h_tts_queue)
    app.router.add_post("/api/tts/stop", h_tts_stop)
    app.router.add_post("/api/tts/skip", h_tts_skip)
    app.router.add_post("/api/tts/check", h_tts_check)
    app.router.add_get("/api/viewer_voices", h_viewer_voices)
    app.router.add_post("/api/viewer_voices/remove", h_viewer_voices_remove)
    app.router.add_post("/api/viewer_voices/clear", h_viewer_voices_clear)
    app.router.add_post("/api/viewer_voices/set", h_viewer_voices_set)
    app.router.add_get("/api/viewers/recent", h_viewers_recent)
    app.router.add_post("/api/tts_test", h_tts_test)
    app.router.add_get("/api/tts_diag", h_tts_diag)
    app.router.add_get("/api/fish_search", h_fish_search)
    app.router.add_get("/api/mod/poll", h_mod_poll)
    app.router.add_post("/api/game/try", h_game_try)
    app.router.add_post("/api/game/ping", h_game_ping)
    app.router.add_get("/api/templates", h_templates)
    app.router.add_get("/api/version", h_version)
    # ── Локальные серверы Minecraft (servers.py) ──
    import servers as _servers
    local_rcon = _RconClient()

    async def _srv_rcon(cmd, host, port, pw):
        return await local_rcon.command(cmd, host, port, pw)
    local_web = _WebRcon()

    async def _srv_game_rcon(game, cmd, host, port, pw):        # Rust — свой WebRCON
        return await local_web.command(cmd, host, port, pw, wait=3)
    STATE.local_servers = _servers.LocalServers(BASE_DIR, STATE.log, lambda: STATE.config, save_config,
                                                _srv_rcon, f"TakyLive/{APP_VERSION}",
                                                game_rcon=_srv_game_rcon)
    STATE.local_servers.routes(app)
    # ── Обновления через GitHub (updater.py) ──
    import updater as _updater
    STATE.updater = _updater.Updater(BASE_DIR, APP_VERSION, STATE.log, lambda: STATE.config, lambda: STATE.connected)
    STATE.updater.routes(app)
    app.router.add_get("/api/migrate/find", h_migrate_find)
    app.router.add_post("/api/migrate", h_migrate)

    async def _first_update_check(app_):
        async def later():
            await asyncio.sleep(6)
            if STATE.config.get("auto_update_check", True) and STATE.updater.repo():
                await STATE.updater.check()
        asyncio.ensure_future(later())
    app.on_startup.append(_first_update_check)
    app.router.add_post("/api/mod/log", h_mod_log)
    app.router.add_get("/api/mod/status", h_mod_status)
    app.router.add_post("/api/mod/open_folder", h_mod_open_folder)
    app.router.add_static("/mods/", MODS_DIR)
    app.router.add_post("/api/tts_preview", h_tts_preview)
    app.router.add_get("/api/timer", h_timer)
    app.router.add_post("/api/timer", h_timer)
    app.router.add_post("/api/panel_fire", h_panel_fire)
    app.router.add_post("/api/random_fire", h_random_fire)
    app.router.add_get("/api/stream_report", h_stream_report)
    app.router.add_get("/media/vault/{tail:.+}", h_vault_media)      # раньше общей /media/ — иначе её перехватит
    app.router.add_get("/api/vault/index", h_vault_index)
    app.router.add_get("/api/gift_catalog", h_gift_catalog)
    app.router.add_post("/api/gift_catalog/fetch", h_gift_catalog_fetch)
    app.router.add_static("/media/", MEDIA_DIR)
    app.router.add_static("/web/", WEB_DIR)
    return app


def open_app_window():
    """Открывает редактор как отдельное окно-приложение (без браузерных кнопок).

    Использует Edge в режиме --app (есть в каждом Windows 10/11).
    Если Edge не найден — пробует Chrome, иначе обычный браузер.
    """
    import subprocess
    import time
    import webbrowser
    time.sleep(1.2)  # даём серверу подняться
    url = "http://localhost:8765"
    if sys.platform == "win32":
        for browser in ("msedge", "chrome"):
            try:
                subprocess.Popen(
                    ["cmd", "/c", "start", "", browser,
                     "--app=" + url, "--window-size=1200,850",
                     "--autoplay-policy=no-user-gesture-required"],
                    creationflags=0x08000000)  # CREATE_NO_WINDOW
                return
            except Exception:
                continue
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    load_config()
    bootstrap_fish_key()
    STATE.gift_names_ru.update(load_gift_names_ru())
    import giftcatalog as _gc
    STATE.gift_catalog = _gc.GiftCatalog(os.path.join(BASE_DIR, "gift_catalog.json"), STATE.log)
    STATE.viewer_voices.update(load_viewer_voices())
    STATE.live_gift_icons.update(load_live_icons())
    if STATE.live_gift_icons:
        print(f"  Иконок подарков из прошлых эфиров: {len(STATE.live_gift_icons)}")
    print("=" * 60)
    print(f"  TakyLive v{APP_VERSION} запущен!")
    print()
    print("  Окно приложения откроется само через пару секунд.")
    print("  Если не открылось — зайди на http://localhost:8765")
    print()
    print("  (не закрывай это окно пока стримишь)")
    print("=" * 60)
    threading.Thread(target=open_app_window, daemon=True).start()
    threading.Thread(target=tts_player_worker, daemon=True).start()
    app = make_app()
    # Слушаем IPv4 всегда; IPv6 (::1) добавляем только если он есть в системе.
    # Встроенный браузер TikTok Live Studio / OBS может резолвить localhost
    # в любой из них — покрываем оба, чтобы оверлеи не «слетали».
    hosts = ["127.0.0.1"]
    try:
        import socket
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        probe.bind(("::1", 0))
        probe.close()
        hosts.append("::1")
    except Exception:
        pass
    web.run_app(app, host=hosts, port=8765, print=None)


if __name__ == "__main__":
    main()
