"""Анонсы эфира в Telegram и Discord: «Я в эфире!» при подключении и итоги после.

Telegram — бот от @BotFather: токен + куда писать (@канал, где бот — админ, или номер чата).
Discord — вебхук канала (Настройки канала → Интеграции → Вебхуки → Копировать URL).
"""
import re

import asyncio

from aiohttp import ClientError, ClientSession, ClientTimeout

TG_API = "https://api.telegram.org"
DEFAULT_START = "🔴 Я в эфире на TikTok! Заходи: {link}"


def _net(service, e):
    """Сетевая ошибка → понятный текст."""
    if isinstance(e, (ClientError, asyncio.TimeoutError, OSError)):
        return RuntimeError(f"нет связи с {service} — проверь интернет; если {service} заблокирован у провайдера, нужен VPN")
    return e


def live_link(nick):
    nick = str(nick or "").strip().lstrip("@")
    return f"https://www.tiktok.com/@{nick}/live" if nick else "https://www.tiktok.com/live"


def start_text(cfg):
    nick = str(cfg.get("tiktok_username") or "").strip().lstrip("@")
    tpl = str(cfg.get("ann_start_text") or "").strip() or DEFAULT_START
    return tpl.replace("{link}", live_link(nick)).replace("{nick}", nick)


def _tg_chat(chat):
    chat = str(chat or "").strip()
    m = re.search(r"t\.me/([A-Za-z0-9_]{4,})", chat)        # вставили ссылку на канал
    if m:
        return "@" + m.group(1)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", chat):     # написали имя канала без @
        return "@" + chat
    return chat


async def tg_send(token, chat, text):
    token, chat = str(token or "").strip(), _tg_chat(chat)
    if not token or not chat:
        raise ValueError("впиши токен бота и куда писать")
    try:
        async with ClientSession(timeout=ClientTimeout(total=15)) as cs:
            async with cs.post(f"{TG_API}/bot{token}/sendMessage",
                               json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": False}) as r:
                d = await r.json(content_type=None)
    except Exception as e:
        raise _net("Telegram", e)
    if not d.get("ok"):
        desc = str(d.get("description") or f"HTTP {r.status}")
        if r.status == 401 or "Unauthorized" in desc:
            raise RuntimeError("Telegram не принял токен бота — скопируй его из @BotFather заново")
        if "chat not found" in desc:
            raise RuntimeError("чат не найден — добавь бота в канал админом или напиши боту /start")
        if "not enough rights" in desc or "administrator" in desc:
            raise RuntimeError("у бота нет права писать в канал — сделай его админом")
        raise RuntimeError(f"Telegram: {desc}")
    return True


async def tg_chats(token):
    """Кому бот может написать: чаты из последних сообщений боту и постов каналов, где он админ."""
    token = str(token or "").strip()
    if not token:
        raise ValueError("сначала впиши токен бота")
    try:
        async with ClientSession(timeout=ClientTimeout(total=15)) as cs:
            async with cs.get(f"{TG_API}/bot{token}/getUpdates", params={"limit": "100"}) as r:
                d = await r.json(content_type=None)
    except Exception as e:
        raise _net("Telegram", e)
    if not d.get("ok"):
        raise RuntimeError("Telegram не принял токен бота — скопируй его из @BotFather заново")
    seen = {}
    for u in d.get("result") or []:
        for key in ("message", "channel_post", "my_chat_member", "edited_message"):
            ch = (u.get(key) or {}).get("chat")
            if ch and ch.get("id") is not None:
                title = ch.get("title") or " ".join(x for x in (ch.get("first_name"), ch.get("last_name")) if x) \
                    or ch.get("username") or str(ch["id"])
                kind = {"private": "личка", "channel": "канал", "group": "группа", "supergroup": "группа"}.get(ch.get("type"), "")
                seen[ch["id"]] = {"id": str(ch["id"]), "title": title, "kind": kind}
    return list(seen.values())


async def dc_send(webhook, text):
    url = str(webhook or "").strip()
    if not re.match(r"https://(?:\w+\.)?(?:discord|discordapp)\.com/api/webhooks/", url):
        raise ValueError("это не ссылка вебхука Discord — она начинается с https://discord.com/api/webhooks/")
    try:
        async with ClientSession(timeout=ClientTimeout(total=15)) as cs:
            async with cs.post(url, json={"content": text[:1990], "username": "TakyLive"}) as r:
                if r.status in (200, 204):
                    return True
                body = (await r.text())[:120]
    except Exception as e:
        raise _net("Discord", e)
    if r.status in (401, 404):
        raise RuntimeError("Discord не нашёл вебхук — создай его заново и вставь ссылку")
    raise RuntimeError(f"Discord ответил {r.status}: {body}")


async def send(cfg, text, log, only=None):
    """Во все включённые каналы (или в один: only = "tg" / "dc"). → [(канал, ok, текст ошибки)]."""
    out = []
    if (only or "tg") == "tg" and (only == "tg" or cfg.get("ann_tg_on")):
        try:
            await tg_send(cfg.get("ann_tg_token"), cfg.get("ann_tg_chat"), text)
            out.append(("Telegram", True, ""))
        except Exception as e:
            out.append(("Telegram", False, str(e)))
    if (only or "dc") == "dc" and (only == "dc" or cfg.get("ann_dc_on")):
        try:
            await dc_send(cfg.get("ann_dc_webhook"), text)
            out.append(("Discord", True, ""))
        except Exception as e:
            out.append(("Discord", False, str(e)))
    for name, ok, err in out:
        log("АНОНС" if ok else "ОШИБКА АНОНСА", f"{name}: " + ("отправлено" if ok else err))
    return out
