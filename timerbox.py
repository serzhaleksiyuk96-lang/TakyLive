"""⏱ Таймер-челлендж: подарки и события добавляют (или отнимают) время.

Состояние сохраняется в timer_state.json — перезапуск, вылет или обновление программы посреди
эфира не теряют набранные часы: после запуска таймер восстанавливается на паузе.
"""
import collections
import json
import time

import safeio


def fmt(sec):
    """Секунды → «+10 сек», «−1 мин», «+1 ч 5 мин» (со знаком)."""
    sign = "−" if sec < 0 else "+"
    s = int(round(abs(sec)))
    if s >= 3600:
        h, m = divmod(s // 60, 60)
        return f"{sign}{h} ч" + (f" {m} мин" if m else "")
    if s >= 60 and s % 60 == 0:
        return f"{sign}{s // 60} мин"
    if s >= 60:
        return f"{sign}{s // 60} мин {s % 60} сек"
    return f"{sign}{s} сек"


class TimerBox:
    def __init__(self, path, get_cfg, log):
        self.path, self.get_cfg, self.log = path, get_cfg, log
        self.running = False
        self.end = 0.0            # когда кончится (если идёт)
        self.left = 0.0           # сколько осталось (если на паузе)
        self.fired = False        # время вышло — финал уже был
        self.peak = 0.0           # максимум за этот заход — для полоски
        self.top = {}             # кто сколько добавил (секунды, только плюс)
        self.events = collections.deque(maxlen=30)   # для плашек на оверлее
        self.seq = 0
        self._saved_at = 0.0
        self.restored = None      # сколько было при запуске (для журнала)

    # ── состояние ──
    def remaining(self):
        if self.running:
            return max(0.0, self.end - time.time())
        return max(0.0, self.left)

    def _set(self, left):
        left = max(0.0, float(left))
        if self.running:
            self.end = time.time() + left
        else:
            self.left = left
        self.peak = max(self.peak, left)

    def start(self):
        left = self.remaining()
        if left <= 0:
            try:
                left = float(self.get_cfg().get("timer_start_min", 30)) * 60
            except (TypeError, ValueError):
                left = 1800
            self.peak, self.top = left, {}
            self.events.clear()
        self.running, self.fired = True, False
        self.end = time.time() + left
        self.peak = max(self.peak, left)
        self.save()
        return left

    def pause(self):
        self.left = self.remaining()
        self.running = False
        self.save()

    def reset(self):
        self.running, self.left, self.fired, self.peak = False, 0.0, False, 0.0
        self.top = {}
        self.events.clear()
        self.save()

    def add(self, sec, user="", what="", icon="", only_running=True):
        """Добавить (sec > 0) или отнять (sec < 0) время. → новое значение или None, если таймер стоит."""
        sec = float(sec or 0)
        if not sec or (only_running and not self.running):
            return None
        new = max(0.0, self.remaining() + sec)
        self._set(new)
        user = str(user or "").strip()
        if sec > 0 and user:
            self.top[user] = self.top.get(user, 0) + sec
        self.seq += 1
        self.events.append({"id": self.seq, "sec": round(sec, 1), "text": fmt(sec), "user": user,
                            "what": str(what or ""), "icon": str(icon or ""), "t": time.time()})
        self.save()
        return new

    def tick(self):
        """Раз в секунду. → True, если время только что вышло."""
        if self.running and time.time() >= self.end and not self.fired:
            self.running, self.fired, self.left = False, True, 0.0
            self.save(force=True)
            return True
        if self.running and time.time() - self._saved_at >= 15:
            self.save()                                   # раз в 15 с — на случай вылета
        return False

    def top_list(self, n=3):
        items = sorted(self.top.items(), key=lambda kv: -kv[1])[:max(0, int(n or 0))]
        return [{"user": u, "sec": round(s), "text": fmt(s)} for u, s in items]

    # ── диск ──
    def save(self, force=False):
        if not force and not self.get_cfg().get("timer_persist", True):
            return
        self._saved_at = time.time()
        data = {"left": round(self.remaining(), 1), "was_running": self.running, "fired": self.fired,
                "peak": round(self.peak, 1), "top": {u: round(s, 1) for u, s in self.top.items()},
                "saved": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            safeio.write_json(self.path, data)
        except Exception:
            pass

    def load(self):
        """После запуска: таймер на паузе с тем временем, что было. → оставшиеся секунды или None."""
        if not self.get_cfg().get("timer_persist", True):
            return None
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return None
        if not isinstance(d, dict):
            return None
        self.running = False
        self.left = max(0.0, float(d.get("left") or 0))
        self.fired = bool(d.get("fired")) and self.left <= 0
        self.peak = max(self.left, float(d.get("peak") or 0))
        self.top = {str(u): float(s) for u, s in (d.get("top") or {}).items() if isinstance(s, (int, float))}
        self.restored = self.left if self.left > 0 else None
        return self.restored
