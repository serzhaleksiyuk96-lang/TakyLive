"""Проверка связи с TikTok: что приходит из эфира и читается ли.

    python tools/tiktok_probe.py <ник> [секунд]      (по умолчанию 90 секунд)
    python tools/tiktok_probe.py <ник> --ru          русские названия подарков → gift_names_ru_full.json

Подключается к эфиру (только чтение, как зритель-невидимка), считает сообщения
от TikTok по видам и сколько из них библиотека TikTokLive смогла прочитать.
Заодно показывает, у кого в чате значок команды (фан-клуба) и что защита озвучки
не прочитала бы — чтобы проверить её на живом чате.
Ничего не запускает, не пишет в чат и не трогает настройки программы.
Бери ник любого идущего эфира с живым чатом (100+ зрителей).
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from TikTokLive import TikTokLiveClient                     # noqa: E402
from TikTokLive.events import ConnectEvent, CommentEvent, LikeEvent, GiftEvent, DisconnectEvent  # noqa: E402

import team as _team                                         # noqa: E402
import textfilter as _tf                                     # noqa: E402

STOP = ["сиксевен", "сикс севен", "six seven", "67 летний", "парта левитирует"]


def verdict(text):
    """Что сделала бы защита озвучки с настройками по умолчанию (None — прочитала бы как есть)."""
    if len(text.strip()) > 120:
        return "длинное"
    why = _tf.junk_reason(text) or _tf.troll_reason(text)
    if why:
        return why
    if _tf.phrase_hit(text, STOP):
        return "стоп-фраза"
    clean, bad = _tf.censor(text)
    return f"пип → «{clean}»" if bad else None


KINDS = {"WebcastChatMessage": "чат", "WebcastLikeMessage": "лайки", "WebcastGiftMessage": "подарки",
         "WebcastSocialMessage": "фолловы/репосты", "WebcastMemberMessage": "вход",
         "WebcastRoomUserSeqMessage": "зрители"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    nick = sys.argv[1].lstrip("@")
    if "--ru" in sys.argv:
        return ru_names(nick)
    secs = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 90
    try:
        from importlib.metadata import version
        tv = version("TikTokLive")
    except Exception:
        tv = "?"
    print(f"Python {sys.version.split()[0]}, TikTokLive {tv}. Эфир @{nick}, слушаю {secs} сек…")

    recv, done, other = {}, {"чат": 0, "лайки": 0, "подарки": 0}, {}
    samples = []
    team = {"msgs": 0, "users": {}, "badges": [], "joined": []}
    filt = {"reasons": {}, "samples": []}
    client = TikTokLiveClient(unique_id="@" + nick)
    orig = client._parse_webcast_response_message

    async def counted(*a, **kw):
        msg = kw.get("webcast_response_message", a[1] if len(a) > 1 else None)
        m = str(getattr(msg, "method", "?"))
        if m in KINDS:
            recv[KINDS[m]] = recv.get(KINDS[m], 0) + 1
        else:
            other[m] = other.get(m, 0) + 1
        return await orig(*a, **kw)
    client._parse_webcast_response_message = counted
    started = {}

    @client.on(ConnectEvent)
    async def on_connect(e):
        started["t"] = time.time()
        print(f"✅ Подключено (room {e.room_id})")

        async def stop_later():
            await asyncio.sleep(secs)
            started["stop"] = True
            try:                                   # TikTok часто не отвечает на «пока» — ждём недолго
                await asyncio.wait_for(client.disconnect(), 6)
            except BaseException:
                pass
        asyncio.ensure_future(stop_later())

    @client.on(CommentEvent)
    async def on_comment(e):
        done["чат"] += 1
        nick = getattr(e.user, 'nickname', '?')
        if len(samples) < 5:
            samples.append(f"{nick}: {e.comment}")
        try:
            lvl = _team.badge_level(e.user)
            if lvl:
                team["msgs"] += 1
                team["users"][nick] = lvl
            desc = _team.describe_badges(e.user)
            if desc and len(team["badges"]) < 10:
                team["badges"].append(f"{nick}: {', '.join(desc)}")
            v = verdict(e.comment or "")
            if v:
                key = v.split(" →")[0]
                filt["reasons"][key] = filt["reasons"].get(key, 0) + 1
                if len(filt["samples"]) < 25:
                    filt["samples"].append(f"[{v}] {nick}: {e.comment}")
        except Exception as ex:
            print(f"  (разбор сообщения: {type(ex).__name__}: {ex})")

    @client.on(LikeEvent)
    async def on_like(e):
        done["лайки"] += 1

    @client.on(GiftEvent)
    async def on_gift(e):
        done["подарки"] += 1
        try:
            g = e.gift
            name = getattr(g, "name", "") or ""
            gid = getattr(getattr(g, "info", None), "id", None) or getattr(g, "id", "")
            if _team.is_join_gift(name, gid):
                team["joined"].append(f"{getattr(e.user, 'nickname', '?')} — «{name}» (ID {gid})")
        except Exception:
            pass

    @client.on(DisconnectEvent)
    async def on_dc(e):
        print("Отключено.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(client.connect())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except Exception as e:
        if not started.get("stop"):
            print(f"❌ Не удалось подключиться: {type(e).__name__}: {e}")
            print("   Эфир идёт? Ник верный? TikTok иногда временно не пускает — попробуй через минуту.")
            return 1
    finally:                                       # закрываем всё сами — без пугающих ошибок при выходе
        try:
            loop.run_until_complete(asyncio.wait_for(client.web.close(), 3))
        except BaseException:
            pass
        try:
            pend = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pend:
                t.cancel()
            if pend:
                loop.run_until_complete(asyncio.wait(pend, timeout=3))
            loop.close()
        except BaseException:
            pass

    print("\nПришло от TikTok → прочитано:")
    for kind in ("чат", "лайки", "подарки", "фолловы/репосты", "вход", "зрители"):
        r = recv.get(kind, 0)
        d = f" → прочитано {done[kind]}" if kind in done else ""
        print(f"  {kind:16} {r}{d}")
    if other:
        top = sorted(other.items(), key=lambda kv: -kv[1])[:8]
        print("  другое: " + ", ".join(f"{k} {v}" for k, v in top))
    if samples:
        print("\nПримеры чата:\n  " + "\n  ".join(samples))
    if done["чат"]:
        users = ", ".join(f"{n} (ур. {lv})" for n, lv in list(team["users"].items())[:15]) or "—"
        print(f"\n👥 Команда: сообщений со значком команды {team['msgs']} из {done['чат']}; участники: {users}")
        if team["joined"]:
            print("   Вступили через подарок: " + "; ".join(team["joined"][:10]))
        if team["badges"]:
            print("   Значки, которые прислал TikTok (примеры):\n     " + "\n     ".join(team["badges"]))
        else:
            print("   Значков у зрителей не было ни одного.")
        n = sum(filt["reasons"].values())
        print(f"\n🧹 Защита озвучки (по умолчанию) не прочитала бы {n} из {done['чат']}: "
              + (", ".join(f"{k} — {v}" for k, v in sorted(filt["reasons"].items(), key=lambda kv: -kv[1])) or "—"))
        if filt["samples"]:
            print("   Примеры (проверь, нет ли нормальных сообщений):\n     " + "\n     ".join(filt["samples"]))
    bad = [k for k in done if recv.get(k, 0) >= 3 and done[k] == 0]
    if bad:
        print(f"\n⚠ ОШИБКА: {', '.join(bad)} приходят, но не читаются (проблема библиотеки или версии Python).")
        return 1
    if not recv.get("чат") and not recv.get("лайки"):
        print("\nЧат и лайки не пришли совсем. Если в эфире они точно были — TikTok их не прислал "
              "(бывает у эфиров с накрученными зрителями или ограничениями). Проверь другой эфир.")
    else:
        print("\n✅ Связь с TikTok в порядке.")
    return 0


def ru_names(nick):
    """Спрашивает у TikTok список подарков по-русски (разными способами) и сохраняет {ID: название}."""
    import json
    import os
    import re
    from TikTokLive.client.web.web_settings import WebDefaults
    client = TikTokLiveClient(unique_id="@" + nick)

    def walk(o, out):
        if isinstance(o, dict):
            if "id" in o and isinstance(o.get("name"), str) and ("diamond_count" in o or "image" in o):
                out[str(o["id"])] = o["name"].strip()
            for v in o.values():
                walk(v, out)
        elif isinstance(o, list):
            for v in o:
                walk(v, out)

    async def go():
        room = None
        try:
            room = await client.web.fetch_room_id_from_html(nick)
        except Exception as e:
            print(f"(ID эфира не узнал: {e} — пробую без него)")
        variants = [
            {"app_language": "ru-RU", "browser_language": "ru-RU", "webcast_language": "ru-RU", "language": "ru"},
            {"app_language": "ru-RU", "browser_language": "ru-RU", "webcast_language": "ru", "language": "ru"},
            {"app_language": "ru", "browser_language": "ru-RU", "webcast_language": "ru", "language": "ru",
             "locale": "ru-RU", "region": "RU", "priority_region": "RU"},
        ]
        best = {}
        for i, params in enumerate(variants, 1):
            if room:
                params["room_id"] = str(room)
            try:
                r = await client.web.get(url=WebDefaults.tiktok_webcast_url + "/gift/list/", extra_params=params,
                                         extra_headers={"Accept-Language": "ru-RU,ru;q=0.9"})
                found = {}
                walk(r.json().get("data") or {}, found)
            except Exception as e:
                print(f"  способ {i}: ошибка {type(e).__name__}: {e}")
                continue
            ru = {k: v for k, v in found.items() if re.search(r"[а-яё]", v, re.I)}
            print(f"  способ {i}: подарков {len(found)}, из них по-русски {len(ru)}")
            if len(ru) > len(best):
                best = ru
        if best:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gift_names_ru_full.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dict(sorted(best.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)),
                          f, ensure_ascii=False, indent=0)
            print(f"✅ Сохранил {len(best)} русских названий: {path}")
            hit = {k: v for k, v in best.items() if k == "9947"}
            print(f"   Friendship Necklace (9947): {hit.get('9947', 'нет в списке')}")
            return 0
        print("❌ TikTok не отдал русские названия ни одним способом")
        return 1

    async def go_and_close():
        try:
            return await go()
        finally:                                   # закрываем сессии сами — иначе при выходе сыплются ошибки
            try:
                await client.web.close()
            except Exception:
                pass
    return asyncio.run(go_and_close())


if __name__ == "__main__":
    sys.exit(main())
