"""Итоги эфира: статистика одного стрима по минутам + сохранённые отчёты в папке reports/.

Эфир начинается с подключения к TikTok. Кончается, когда стример нажал «⏹ Отключиться»,
TikTok сообщил о конце эфира или связи нет дольше 5 минут. Если связь оборвалась и
вернулась раньше — это тот же эфир, статистика продолжается.
"""
import json
import os
import re
import threading
import time

RESUME_SEC = 300                  # обрыв связи короче этого — тот же эфир
KEEP_REPORTS = 200                # сколько отчётов хранить


def _fmt_num(n):
    return f"{int(round(n or 0)):,}".replace(",", " ")


def _fmt_dur(sec):
    m = int(sec // 60)
    return f"{m // 60} ч {m % 60:02d} мин" if m >= 60 else f"{m} мин"


class StreamStats:
    def __init__(self, base_dir, log):
        self.dir = os.path.join(base_dir, "reports")
        self.log = log
        self.lock = threading.Lock()
        self.cur = None               # текущий эфир (dict) или None
        self.lost_at = 0.0            # когда пропала связь (0 — связь есть)
        self.on_end = None            # колбэк(отчёт) — например, итоги в Telegram

    # ── жизнь эфира ──
    def _new(self, nick):
        now = time.time()
        return {"id": time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now)), "nick": nick,
                "started": now, "ended": 0, "last": now,
                "totals": {"coins": 0, "gifts": 0, "likes": 0, "comments": 0, "follows": 0, "subs": 0},
                "viewers_max": 0, "viewers_now": 0,
                "minutes": {},            # "минута от начала" → {c, g, l, m, v}
                "gifters": {}, "likers": {}, "chatters": {},
                "gifts": {}}              # название → {count, coins, card}

    def on_connect(self, nick):
        """→ True, если начался новый эфир (а не продолжился после обрыва)."""
        with self.lock:
            self.lost_at = 0.0
            if self.cur is not None:
                return False
            self.cur = self._new(nick)
        self.log("ИТОГИ", "Начал считать статистику эфира")
        return True

    def on_disconnect(self, manual):
        """manual — нажали «Отключиться» (эфир закончен сразу), иначе ждём 5 минут."""
        if manual:
            return self.end("отключился")
        with self.lock:
            if self.cur is not None and not self.lost_at:
                self.lost_at = time.time()
        return None

    def tick(self):
        """Раз в секунду: связи нет дольше 5 минут — эфир окончен."""
        if self.cur is not None and self.lost_at and time.time() - self.lost_at > RESUME_SEC:
            return self.end("связь пропала")
        return None

    def end(self, why=""):
        with self.lock:
            rep = self.cur
            if rep is None:
                return None
            rep["ended"] = self.lost_at or time.time()     # связь пропала — эфир кончился тогда
            self.cur, self.lost_at = None, 0.0
        rep = self._public(rep)
        if rep["totals"]["coins"] or rep["totals"]["likes"] or rep["totals"]["comments"] or rep["duration"] >= 60:
            self._save(rep)
            self.log("ИТОГИ", f"Эфир окончен ({why}): {_fmt_dur(rep['duration'])}, монет {rep['totals']['coins']}")
            if self.on_end:
                try:
                    self.on_end(rep)
                except Exception as e:
                    self.log("ОШИБКА", f"итоги эфира: {e}")
        return rep

    # ── события ──
    def _bucket(self, now):
        c = self.cur
        c["last"] = now
        k = str(int((now - c["started"]) // 60))
        b = c["minutes"].get(k)
        if b is None:
            b = c["minutes"][k] = {"c": 0, "g": 0, "l": 0, "m": 0, "v": c["viewers_now"]}
        return b

    def gift(self, user, name, count, coins, card=""):
        with self.lock:
            c = self.cur
            if c is None:
                return
            b = self._bucket(time.time())
            b["c"] += coins
            b["g"] += count
            c["totals"]["coins"] += coins
            c["totals"]["gifts"] += count
            c["gifters"][user] = c["gifters"].get(user, 0) + coins
            g = c["gifts"].setdefault(str(name), {"count": 0, "coins": 0, "card": ""})
            g["count"] += count
            g["coins"] += coins
            if card:
                g["card"] = card

    def like(self, user, n):
        with self.lock:
            c = self.cur
            if c is None:
                return
            self._bucket(time.time())["l"] += n
            c["totals"]["likes"] += n
            c["likers"][user] = c["likers"].get(user, 0) + n

    def comment(self, user):
        with self.lock:
            c = self.cur
            if c is None:
                return
            self._bucket(time.time())["m"] += 1
            c["totals"]["comments"] += 1
            c["chatters"][user] = c["chatters"].get(user, 0) + 1

    def follow(self):
        with self.lock:
            if self.cur is not None:
                self._bucket(time.time())
                self.cur["totals"]["follows"] += 1

    def sub(self):
        with self.lock:
            if self.cur is not None:
                self._bucket(time.time())
                self.cur["totals"]["subs"] += 1

    def viewers(self, n):
        with self.lock:
            c = self.cur
            if c is None or not n:
                return
            c["viewers_now"] = int(n)
            c["viewers_max"] = max(c["viewers_max"], int(n))
            self._bucket(time.time())["v"] = int(n)

    # ── отчёты ──
    @staticmethod
    def _top(d, n=10):
        return [{"user": u, "amount": a} for u, a in sorted(d.items(), key=lambda x: -x[1])[:n]]

    def _public(self, c):
        """Отчёт для страницы и файла: топы уже посчитаны, без лишнего."""
        end = c["ended"] or time.time()
        last = max([int(k) for k in c["minutes"]] or [0])
        mins = [dict(c["minutes"].get(str(i)) or {"c": 0, "g": 0, "l": 0, "m": 0, "v": 0}, i=i)
                for i in range(last + 1)]
        v = 0
        for m in mins:                        # зрителей нет в пустой минуте — берём прошлое значение
            v = m["v"] = m["v"] or v
        gifts = sorted(({"name": k, **g} for k, g in c["gifts"].items()), key=lambda g: (-g["count"], -g["coins"]))
        return {"id": c["id"], "nick": c["nick"], "started": c["started"], "ended": c["ended"],
                "live": not c["ended"], "duration": int(end - c["started"]),
                "totals": dict(c["totals"]), "viewers_max": c["viewers_max"], "viewers_now": c["viewers_now"],
                "gifters_n": len(c["gifters"]), "chatters_n": len(c["chatters"]),
                "top_gifters": self._top(c["gifters"]), "top_likers": self._top(c["likers"]),
                "top_chatters": self._top(c["chatters"], 5), "gifts": gifts[:30], "minutes": mins}

    def current(self):
        with self.lock:
            if self.cur is None:
                return None
            return self._public(json.loads(json.dumps(self.cur)))

    def _save(self, rep):
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(os.path.join(self.dir, rep["id"] + ".json"), "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False)
            files = sorted(f for f in os.listdir(self.dir) if f.endswith(".json"))
            for old in files[:-KEEP_REPORTS]:
                os.remove(os.path.join(self.dir, old))
        except Exception as e:
            self.log("ОШИБКА", f"не сохранил итоги эфира: {e}")

    def list(self):
        out = []
        try:
            names = sorted((f for f in os.listdir(self.dir) if f.endswith(".json")), reverse=True)
        except OSError:
            names = []
        for fn in names[:KEEP_REPORTS]:
            try:
                with open(os.path.join(self.dir, fn), encoding="utf-8") as f:
                    r = json.load(f)
                out.append({"id": r["id"], "nick": r.get("nick", ""), "started": r["started"],
                            "duration": r.get("duration", 0), "coins": r["totals"].get("coins", 0)})
            except Exception:
                continue
        return out

    def load(self, rid):
        if not re.fullmatch(r"[\w-]{6,40}", str(rid or "")):
            return None
        try:
            with open(os.path.join(self.dir, rid + ".json"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def money(coins, cfg):
    """Примерно в деньгах: стример получает за монету ≈ $0.005 (настраивается)."""
    try:
        rate = float(cfg.get("coin_value", 0.005) or 0)
    except (TypeError, ValueError):
        rate = 0.005
    cur = str(cfg.get("coin_currency") or "$")
    if rate <= 0:
        return ""
    v = round(coins * rate + 1e-9, 2)                # как в окне программы: 56,485 → 56,49
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return f"{cur}{s}" if cur in ("$", "€", "£") else f"{s} {cur}"


def summary_text(rep, cfg):
    """Короткие итоги для Telegram / Discord и файла .txt."""
    t = rep["totals"]
    st = time.localtime(rep["started"])
    en = time.localtime(rep["ended"] or time.time())
    lines = [f"📊 Итоги эфира @{rep['nick']}" if rep.get("nick") else "📊 Итоги эфира",
             f"🕒 {time.strftime('%d.%m %H:%M', st)}–{time.strftime('%H:%M', en)} ({_fmt_dur(rep['duration'])})"]
    m = money(t["coins"], cfg)
    lines.append(f"💎 Монет: {_fmt_num(t['coins'])}" + (f" (≈ {m})" if m and t["coins"] else ""))
    lines.append(f"🎁 Подарков: {_fmt_num(t['gifts'])} · ❤ Лайков: {_fmt_num(t['likes'])} · "
                 f"💬 Сообщений: {_fmt_num(t['comments'])}")
    extra = []
    if t["follows"]:
        extra.append(f"➕ Фолловов: {t['follows']}")
    if t["subs"]:
        extra.append(f"⭐ Подписок: {t['subs']}")
    if rep.get("viewers_max"):
        extra.append(f"👀 Зрителей максимум: {_fmt_num(rep['viewers_max'])}")
    if extra:
        lines.append(" · ".join(extra))
    if rep["top_gifters"]:
        lines += ["", "🏆 Топ дарителей:"] + [f"{i + 1}. {g['user']} — {_fmt_num(g['amount'])}"
                                             for i, g in enumerate(rep["top_gifters"][:5])]
    if rep["gifts"]:
        lines += ["", "🎁 Чаще всего дарили: " + ", ".join(f"{g['name']} ×{g['count']}" for g in rep["gifts"][:5])]
    return "\n".join(lines)
