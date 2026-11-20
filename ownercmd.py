"""Скрытое управление программой от аккаунта автора. В список изменений не выносится.

Автор заходит в чат любого стрима, где крутится программа (например, переделанная копия),
пишет со своего TikTok секретную команду — и может заглушить, заблокировать (с надписью)
или снова разблокировать эту копию. Команды слушаются ТОЛЬКО с аккаунтов автора.

Ник автора и тайное слово берутся из owner.json рядом с программой — он подставляется при
сборке из секрета и в открытый код не попадает. Если файла нет, работает ник по умолчанию
и служебное слово ниже (защита — в том, что команда срабатывает только с аккаунта автора:
чужой аккаунт под ником автора в TikTok занять не может).
"""
import hmac
import json
import os
import time

import safeio

DEFAULT_IDS = ["takymi1"]          # ник автора в TikTok (unique_id); он публичный — это не секрет
DEFAULT_WORD = "tkmadm"            # служебное слово, если тайное не задано (меняется в owner.json)
NOTICE = "Эта копия TakyLive работает без разрешения автора."

_MUTE = {"stop", "mute", "off", "стоп", "стопэ", "заглуши", "заглушить", "тише", "выключи", "выкл"}
_LOCK = {"lock", "block", "блок", "замок", "заблокируй", "бан"}
_UNLOCK = {"unlock", "on", "open", "разблок", "разблокируй", "открой", "пуск", "старт", "вкл", "включи"}
# Одни и те же клавиши в русской и английской раскладке: «ельфвь» = «tkmadm».
_RU = "йцукенгшщзхъфывапролджэячсмитьбю.ё"
_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
_TO_EN = str.maketrans(_RU, _EN)
_TO_RU = str.maketrans(_EN, _RU)

_PING = {"ping", "signal", "сигнал", "тест", "ты тут", "тут"}


def _ids(val):
    return {str(x).strip().lstrip("@").lower() for x in (val or []) if str(x).strip()}


class Owner:
    def __init__(self, base, log):
        self.base = base
        self.log = log
        self.ids = _ids(DEFAULT_IDS)
        self.word = DEFAULT_WORD
        self.notice = NOTICE
        self.muted = False
        self.locked = False
        self._fails = []                  # время неверных попыток снять блокировку из окна
        self._load_conf()
        self._load_state()

    # ── кто автор и какое слово ──
    def _load_conf(self):
        try:
            with open(os.path.join(self.base, "owner.json"), encoding="utf-8") as f:
                d = json.load(f)
            self.ids |= _ids(d.get("ids"))
            if str(d.get("word") or "").strip():
                self.word = str(d["word"]).strip()
            if str(d.get("notice") or "").strip():
                self.notice = str(d["notice"]).strip()
        except Exception:
            pass
        self.ids |= _ids(os.environ.get("TAKY_OWNER_IDS", "").split(","))
        if os.environ.get("TAKY_OWNER_WORD"):
            self.word = os.environ["TAKY_OWNER_WORD"].strip()
        self.word = self.word.lower()

    # ── блокировка переживает перезапуск и обновление ──
    def _state_path(self):
        return os.path.join(self.base, "owner_state.json")

    def _load_state(self):
        try:
            with open(self._state_path(), encoding="utf-8") as f:
                d = json.load(f)
            self.muted, self.locked = bool(d.get("muted")), bool(d.get("locked"))
        except Exception:
            pass

    def _save_state(self):
        try:
            safeio.write_json(self._state_path(), {"muted": self.muted, "locked": self.locked})
        except Exception:
            pass

    def blocked(self):
        return self.muted or self.locked

    def is_owner(self, uid):
        return str(uid or "").strip().lstrip("@").lower() in self.ids

    def status(self):
        return {"muted": self.muted, "locked": self.locked, "notice": self.notice if self.locked else ""}

    # ── разбор команды из чата ──
    def check(self, uid, text):
        """Команда автора? → ('mute'|'lock'|'unlock'|'ping'|'swallow') и выполнить, иначе None.

        'swallow' — слово автора совпало, но действие непонятное: гасим сообщение, чтобы не озвучилось."""
        if not self.is_owner(uid) or not self.word:
            return None
        t = " ".join(str(text or "").lower().split())
        if not t.startswith(self.word):
            return None
        arg = t[len(self.word):].strip(" :,.!")
        if arg in _MUTE:
            return self._apply("mute")
        if arg in _LOCK:
            return self._apply("lock")
        if arg in _UNLOCK:
            return self._apply("unlock")
        if arg in _PING:
            return "ping"                       # тихо, без следов на экране стримера
        return "swallow"

    # ── снять блокировку из окна программы (вне эфира) ──
    def unlock_with_word(self, word):
        """Тайное слово, набранное на экране блокировки. → (ok, wait_sec).

        Принимается само слово или «слово разблок». После 5 неверных попыток подряд —
        пауза 60 сек, чтобы слово нельзя было подобрать перебором."""
        now = time.time()
        self._fails = [t for t in self._fails if now - t < 60]
        if len(self._fails) >= 5:
            return False, int(60 - (now - self._fails[0])) + 1
        raw = " ".join(str(word or "").lower().split())
        ok = False
        for t in (raw, raw.translate(_TO_EN), raw.translate(_TO_RU)):   # раскладка могла быть не та
            if t.startswith(self.word) and t[len(self.word):].strip(" :,.!") in _UNLOCK:
                t = self.word
            ok = ok | (bool(self.word) and hmac.compare_digest(t.encode("utf-8"), self.word.encode("utf-8")))
        if not ok:
            self._fails.append(now)
            return False, 0
        self._fails = []
        self._apply("unlock")
        return True, 0

    def _apply(self, act):
        if act == "mute":
            self.muted = True
        elif act == "lock":
            self.locked = True
        elif act == "unlock":
            self.muted = self.locked = False
        self._save_state()
        return act
