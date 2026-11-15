"""Интерактив для зрителей: 💎 очки, ⚔ битва команд, 🎡 колесо фортуны.

Здесь только логика и состояние. Команды в игру, оверлеи и озвучку запускает app.py —
этим классам передаются готовые функции (run, alert, say, log).
"""
import json
import os
import random
import re
import threading
import time


def _int(v, default=0, lo=None, hi=None):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def vkey(user):
    """Ключ зрителя: @юзернейм без @ и без регистра."""
    return str(user or "").strip().lstrip("@").lower()


def triggers(text):
    """«!красные, !к, !1» → ["!красные", "!к", "!1"]."""
    return [t.strip().lower() for t in re.split(r"[,;\n]", str(text or "")) if t.strip()]


def said(msg, trigs):
    """Сообщение — это команда: «!к» срабатывает на «!к» и «!к привет», но не на «!красные»."""
    m = str(msg or "").strip().lower()
    return any(m == t or m.startswith(t + " ") for t in trigs)


def commands_of(text):
    """Текст «по команде на строку» → цепочка для run_chain."""
    cmds = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    return {"commands": cmds, "delays": [0] * len(cmds)}


# ══ 💎 Очки зрителей ══════════════════════════════════════════════════════════
PTS_DEFAULTS = {
    "pts_on": False, "pts_name": "очки",
    "pts_coin": 10,          # за 1 монету подарка
    "pts_likes_n": 20,       # 1 очко за каждые N лайков
    "pts_msg": 2, "pts_msg_cd": 30,       # за сообщение в чат, не чаще раза в N секунд
    "pts_follow": 50, "pts_sub": 300, "pts_share": 10,
    "pts_active": 10,        # раз в 5 минут — тем, кто был активен последние 10 минут
    "pts_cmd_balance": "!очки, !баланс", "pts_cmd_top": "!топ",
    "pts_say": False,        # отвечать на !очки голосом
}


class Points:
    ACTIVE_EVERY = 300
    ACTIVE_WINDOW = 600

    def __init__(self, path, log):
        self.path, self.log = path, log
        self.lock = threading.Lock()
        self.data = {}            # ключ → {"n": имя, "p": очки, "e": заработано, "s": потрачено, "t": когда был}
        self.dirty = False
        self.likes_buf, self.msg_at, self.share_at, self.active_at, self.reply_at = {}, {}, {}, {}, {}
        self.followed = set()
        self.next_bonus = time.time() + self.ACTIVE_EVERY
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data = {k: v for k, v in d.items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except Exception as e:
            log("ОШИБКА", f"не прочитал очки зрителей: {e}")

    def _rec(self, key, name):
        r = self.data.get(key)
        if r is None:
            r = self.data[key] = {"n": name or key, "p": 0, "e": 0, "s": 0, "t": 0}
        elif name:
            r["n"] = name
        return r

    def add(self, key, name, n):
        if not key or n == 0:
            return
        with self.lock:
            r = self._rec(key, name)
            r["p"] = max(0, r["p"] + int(n))
            if n > 0:
                r["e"] += int(n)
            r["t"] = int(time.time())
            self.active_at[key] = time.time()
            self.dirty = True

    def balance(self, key):
        r = self.data.get(key)
        return int(r["p"]) if r else 0

    def spend(self, key, name, n):
        """→ True, если хватило и списали."""
        with self.lock:
            r = self._rec(key, name)
            if r["p"] < n:
                return False
            r["p"] -= n
            r["s"] += n
            r["t"] = int(time.time())
            self.dirty = True
            return True

    # ── за что начисляем ──
    def on_gift(self, cfg, key, name, coins):
        self.add(key, name, coins * _int(cfg.get("pts_coin"), 10, 0))

    def on_like(self, cfg, key, name, n):
        per = _int(cfg.get("pts_likes_n"), 20, 0)
        self.active_at[key] = time.time()
        if per <= 0:
            return
        b = self.likes_buf.get(key, 0) + n
        self.likes_buf[key] = b % per
        if b // per:
            self.add(key, name, b // per)

    def on_msg(self, cfg, key, name):
        now = time.time()
        self.active_at[key] = now
        if now - self.msg_at.get(key, 0) < _int(cfg.get("pts_msg_cd"), 30, 0):
            return
        self.msg_at[key] = now
        self.add(key, name, _int(cfg.get("pts_msg"), 2, 0))

    def on_follow(self, cfg, key, name):
        if key in self.followed:              # отписался-подписался — второй раз не платим
            return
        self.followed.add(key)
        self.add(key, name, _int(cfg.get("pts_follow"), 50, 0))

    def on_sub(self, cfg, key, name):
        self.add(key, name, _int(cfg.get("pts_sub"), 300, 0))

    def on_share(self, cfg, key, name):
        now = time.time()
        if now - self.share_at.get(key, 0) < 300:
            return
        self.share_at[key] = now
        self.add(key, name, _int(cfg.get("pts_share"), 10, 0))

    def tick(self, cfg, live):
        """Раз в секунду: бонус за активность и сохранение."""
        now = time.time()
        if now >= self.next_bonus:
            self.next_bonus = now + self.ACTIVE_EVERY
            bonus = _int(cfg.get("pts_active"), 10, 0)
            if live and bonus:
                keys = [k for k, t in self.active_at.items() if now - t <= self.ACTIVE_WINDOW]
                for k in keys:
                    r = self.data.get(k)
                    self.add(k, r["n"] if r else k, bonus)
                if keys:
                    self.log("ОЧКИ", f"+{bonus} за активность — {len(keys)} зрителям")
        if self.dirty and int(now) % 15 == 0:
            self.save()

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            data = json.dumps(self.data, ensure_ascii=False)
            self.dirty = False
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, self.path)
        except Exception as e:
            self.log("ОШИБКА", f"не сохранил очки зрителей: {e}")

    def can_reply(self, key, sec=20):
        now = time.time()
        if now - self.reply_at.get(key, 0) < sec:
            return False
        self.reply_at[key] = now
        return True

    def top(self, n=10):
        rows = sorted(self.data.items(), key=lambda kv: -kv[1].get("p", 0))
        return [{"user": r.get("n", k), "amount": int(r.get("p", 0))}
                for k, r in rows[:n] if r.get("p", 0) > 0]

    def search(self, q, n=100):
        q = str(q or "").strip().lower()
        rows = sorted(self.data.items(), key=lambda kv: -kv[1].get("p", 0))
        if q:
            rows = [kv for kv in rows if q in kv[0] or q in str(kv[1].get("n", "")).lower()]
        return [{"key": k, "user": r.get("n", k), "amount": int(r.get("p", 0)),
                 "earned": int(r.get("e", 0)), "spent": int(r.get("s", 0)), "seen": r.get("t", 0)}
                for k, r in rows[:n]], len(self.data)

    def set(self, key, n):
        with self.lock:
            if key in self.data:
                self.data[key]["p"] = max(0, int(n))
                self.dirty = True

    def reset_all(self):
        with self.lock:
            self.data = {}
            self.likes_buf.clear()
            self.dirty = True
        self.save()


# ══ ⚔ Битва команд ════════════════════════════════════════════════════════════
BATTLE_DEFAULTS = {
    "battle_names": ["Красные", "Синие"],
    "battle_colors": ["#ef4444", "#3b82f6"],
    "battle_join": ["!красные, !к, !1", "!синие, !с, !2"],
    "battle_cmds": ["", ""],          # что запускает победившая команда (по команде на строку)
    "battle_secs": 180,
    "battle_like_n": 0,               # 0 — лайки не считаются; иначе 1 очко битвы за N лайков
    "battle_auto": True,              # подарил, не выбрав команду, — попадает в отстающую
    "battle_say": True,               # объявить победителя голосом (если озвучка включена)
}


class Battle:
    SHOW_RESULT = 12                  # сколько секунд оверлей показывает победителя

    def __init__(self, log):
        self.log = log
        self.lock = threading.Lock()
        self.round = 0
        self._reset()
        self.running = False
        self.result = None            # {"winner": 0|1|-1, "at": время, "mvp": имя}

    def _reset(self):
        self.score = [0, 0]
        self.members = {}             # ключ → 0/1
        self.contrib = [{}, {}]       # ключ → вклад
        self.names = {}
        self.like_buf = {}
        self.ends = 0
        self.started = 0

    def start(self, secs):
        with self.lock:
            self._reset()
            self.round += 1
            self.running = True
            self.result = None
            self.started = time.time()
            self.ends = self.started + max(10, secs)
        self.log("БИТВА", f"⚔ Раунд {self.round} начался на {_int(secs)} сек")

    def stop(self):
        """Остановить без победителя."""
        with self.lock:
            was = self.running
            self.running = False
            self.result = None
        if was:
            self.log("БИТВА", "Битва остановлена без победителя")
        return was

    def join(self, key, name, team):
        with self.lock:
            if not self.running:
                return None
            old = self.members.get(key)
            self.members[key] = team
            self.names[key] = name
            return old

    def _team_of(self, key, name, auto):
        t = self.members.get(key)
        if t is None and auto:
            n0 = sum(1 for v in self.members.values() if v == 0)
            n1 = len(self.members) - n0
            t = 0 if (n0, self.score[0]) <= (n1, self.score[1]) else 1
            self.members[key] = t
            self.names[key] = name
        return t

    def gift(self, cfg, key, name, coins):
        with self.lock:
            if not self.running or coins <= 0:
                return None
            t = self._team_of(key, name, cfg.get("battle_auto", True))
            if t is None:
                return None
            self.score[t] += coins
            self.contrib[t][key] = self.contrib[t].get(key, 0) + coins
            return t

    def like(self, cfg, key, n):
        per = _int(cfg.get("battle_like_n"), 0, 0)
        with self.lock:
            if not self.running or per <= 0:
                return
            t = self.members.get(key)
            if t is None:
                return
            b = self.like_buf.get(key, 0) + n
            self.like_buf[key] = b % per
            if b // per:
                self.score[t] += b // per
                self.contrib[t][key] = self.contrib[t].get(key, 0) + b // per

    def tick(self):
        """→ итог раунда, когда время вышло (иначе None)."""
        with self.lock:
            if not self.running or time.time() < self.ends:
                return None
            self.running = False
            s0, s1 = self.score
            w = 0 if s0 > s1 else 1 if s1 > s0 else -1
            mvp = ""
            if w >= 0 and self.contrib[w]:
                k = max(self.contrib[w], key=self.contrib[w].get)
                mvp = self.names.get(k, k)
            self.result = {"winner": w, "at": time.time(), "mvp": mvp, "score": [s0, s1]}
            return dict(self.result)

    def snapshot(self, cfg):
        names = (cfg.get("battle_names") or BATTLE_DEFAULTS["battle_names"]) + ["", ""]
        colors = (cfg.get("battle_colors") or BATTLE_DEFAULTS["battle_colors"]) + ["#ef4444", "#3b82f6"]
        joins = (cfg.get("battle_join") or BATTLE_DEFAULTS["battle_join"]) + ["", ""]
        now = time.time()
        res = self.result if self.result and now - self.result["at"] < self.SHOW_RESULT else None
        teams = []
        for t in (0, 1):
            top = sorted(self.contrib[t].items(), key=lambda kv: -kv[1])[:3]
            teams.append({"name": names[t] or ("Команда " + str(t + 1)), "color": colors[t],
                          "join": (triggers(joins[t]) or [""])[0], "score": self.score[t],
                          "members": sum(1 for v in self.members.values() if v == t),
                          "top": [{"user": self.names.get(k, k), "amount": a} for k, a in top]})
        return {"running": self.running, "round": self.round,
                "left": max(0, int(self.ends - now)) if self.running else 0,
                "teams": teams, "result": res, "visible": self.running or bool(res)}


# ══ 🎡 Колесо фортуны ═════════════════════════════════════════════════════════
WHEEL_COLORS = ["#6366f1", "#22d3ee", "#f59e0b", "#ef4444", "#10b981", "#ec4899", "#8b5cf6", "#14b8a6"]
WHEEL_DEFAULTS = {
    "wheel_on": False,
    "wheel_gift": "",            # название или ID подарка, который крутит колесо
    "wheel_min_coins": 0,        # или любой подарок от N монет (0 — выкл)
    "wheel_pts_cost": 0,         # или за очки по команде (0 — выкл)
    "wheel_cmd": "!колесо",
    "wheel_secs": 7,
    "wheel_style": "modern",     # вид колеса в оверлее: modern — неоновое, gold — золотое казино
    "wheel_sectors": [
        {"label": "Зомби", "weight": 3, "commands": ""},
        {"label": "Ничего 😅", "weight": 3, "commands": ""},
        {"label": "Взрыв", "weight": 2, "commands": ""},
        {"label": "Подарок", "weight": 2, "commands": ""},
        {"label": "Ночь", "weight": 2, "commands": ""},
        {"label": "Джекпот", "weight": 1, "commands": ""},
    ],
}


def wheel_sectors(cfg):
    out = []
    for i, s in enumerate(cfg.get("wheel_sectors") or []):
        if not isinstance(s, dict) or not str(s.get("label", "")).strip():
            continue
        out.append({"label": str(s["label"]).strip()[:24], "weight": max(0, _int(s.get("weight"), 1)),
                    "commands": str(s.get("commands", "")),
                    "color": s.get("color") or WHEEL_COLORS[len(out) % len(WHEEL_COLORS)]})
    return out


class Wheel:
    HOLD = 4                     # сколько секунд показываем результат перед следующим вращением
    MAX_QUEUE = 20

    def __init__(self, log):
        self.log = log
        self.lock = threading.Lock()
        self.queue = []
        self.current = None      # {"id", "user", "result", "sectors", "started", "secs", "fired"}
        self.seq = 0

    def request(self, user, reason):
        with self.lock:
            if len(self.queue) >= self.MAX_QUEUE:
                return -1
            self.queue.append({"user": user, "reason": reason})
            return len(self.queue) + (1 if self.current else 0)

    def tick(self, cfg):
        """→ (сектор, зритель), когда колесо остановилось — пора запускать команды."""
        now = time.time()
        with self.lock:
            c = self.current
            if c and not c["fired"] and now >= c["started"] + c["secs"]:
                c["fired"] = True
                return c["sectors"][c["result"]], c["user"]
            if c and c["fired"] and now >= c["started"] + c["secs"] + self.HOLD:
                self.current = c = None
            if c is None and self.queue:
                sectors = wheel_sectors(cfg)
                if not sectors:
                    self.queue.clear()
                    return None
                weights = [s["weight"] for s in sectors]
                idx = random.choices(range(len(sectors)), weights=weights if sum(weights) else None)[0]
                req = self.queue.pop(0)
                secs = _int(cfg.get("wheel_secs"), 7, 3, 20)
                self.seq += 1
                self.current = {"id": self.seq, "user": req["user"], "result": idx, "sectors": sectors,
                                "started": now, "secs": secs, "fired": False}
                self.log("КОЛЕСО", f"🎡 {req['user'] or 'стример'} крутит колесо ({req['reason']})")
        return None

    def snapshot(self, cfg):
        now = time.time()
        with self.lock:
            c = self.current
            secs = wheel_sectors(cfg)
            spin = None
            if c:
                spin = {"id": c["id"], "user": c["user"], "result": c["result"], "secs": c["secs"],
                        "ago": round(now - c["started"], 2), "done": c["fired"],
                        "label": c["sectors"][c["result"]]["label"]}
            return {"sectors": [{"label": s["label"], "color": s["color"]} for s in (c["sectors"] if c else secs)],
                    "spin": spin, "queue": len(self.queue), "visible": bool(c),
                    "style": "gold" if cfg.get("wheel_style") == "gold" else "modern"}
