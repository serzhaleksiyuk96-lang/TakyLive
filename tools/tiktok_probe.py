"""Проверка связи с TikTok: что приходит из эфира и читается ли.

    python tools/tiktok_probe.py <ник> [секунд]      (по умолчанию 90 секунд)

Подключается к эфиру (только чтение, как зритель-невидимка), считает сообщения
от TikTok по видам и сколько из них библиотека TikTokLive смогла прочитать.
Ничего не запускает, не пишет в чат и не трогает настройки программы.
Бери ник любого идущего эфира с живым чатом (100+ зрителей).
"""
import asyncio
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from TikTokLive import TikTokLiveClient                     # noqa: E402
from TikTokLive.events import ConnectEvent, CommentEvent, LikeEvent, GiftEvent, DisconnectEvent  # noqa: E402

KINDS = {"WebcastChatMessage": "чат", "WebcastLikeMessage": "лайки", "WebcastGiftMessage": "подарки",
         "WebcastSocialMessage": "фолловы/репосты", "WebcastMemberMessage": "вход",
         "WebcastRoomUserSeqMessage": "зрители"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    nick = sys.argv[1].lstrip("@")
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    try:
        from importlib.metadata import version
        tv = version("TikTokLive")
    except Exception:
        tv = "?"
    print(f"Python {sys.version.split()[0]}, TikTokLive {tv}. Эфир @{nick}, слушаю {secs} сек…")

    recv, done, other = {}, {"чат": 0, "лайки": 0, "подарки": 0}, {}
    samples = []
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
            await client.disconnect(close_client=True)
        asyncio.ensure_future(stop_later())

    @client.on(CommentEvent)
    async def on_comment(e):
        done["чат"] += 1
        if len(samples) < 5:
            samples.append(f"{getattr(e.user, 'nickname', '?')}: {e.comment}")

    @client.on(LikeEvent)
    async def on_like(e):
        done["лайки"] += 1

    @client.on(GiftEvent)
    async def on_gift(e):
        done["подарки"] += 1

    @client.on(DisconnectEvent)
    async def on_dc(e):
        print("Отключено.")

    try:
        client.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Не удалось подключиться: {type(e).__name__}: {e}")
        print("   Эфир идёт? Ник верный? TikTok иногда временно не пускает — попробуй через минуту.")
        return 1

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


if __name__ == "__main__":
    sys.exit(main())
