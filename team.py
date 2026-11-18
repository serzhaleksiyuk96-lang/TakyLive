"""👥 Команда стримера (фан-клуб TikTok).

Зритель вступает в команду, подарив «Heart Me» («От всего сердца», 1 монета). Программа узнаёт
участников двумя путями и запоминает их в team_members.json (файл переживает обновления):
  • по значку команды рядом с ником в чате (TikTok присылает его в каждом сообщении);
  • по самому подарку «Heart Me» и «Браслету команды».
"""
import json
import threading
import time

import safeio

JOIN_GIFT_IDS = {"7934", "9139"}                        # Heart Me, Team Bracelet
JOIN_GIFT_NAMES = {"heart me", "от всего сердца", "team bracelet", "браслет команды"}


def is_join_gift(name="", gid=""):
    return str(gid or "").strip() in JOIN_GIFT_IDS or str(name or "").strip().lower() in JOIN_GIFT_NAMES


def _int(v):
    try:
        return int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _val(v):
    """Число из перечисления TikTok (BadgeSceneType.FANS → 10) или из строки."""
    if isinstance(v, int):
        return int(v)
    return _int(getattr(v, "value", v))


def badge_level(user, anchor_id=None):
    """Уровень зрителя в команде стримера по данным из сообщения чата (0 — не в команде).

    TikTokLive 7 сам этого не умеет: его has_badge() ищет поля старой версии и всегда отвечает «нет»."""
    if user is None:
        return 0
    lvl = 0
    try:
        for b in getattr(user, "badge_list", None) or []:
            st = getattr(b, "scene_type", None)
            name = str(getattr(st, "name", "") or "").upper()
            if _val(st) == 10 or name.endswith("FANS"):
                ple = getattr(b, "privilege_log_extra", None)
                lvl = max(lvl, _int(getattr(ple, "level", 0)) or 1)
    except Exception:
        pass
    try:
        fc = getattr(getattr(user, "fans_club", None), "data", None)
        if fc is not None:
            level = _int(getattr(fc, "level", 0))
            status = _val(getattr(fc, "user_fans_club_status", 0))
            aid = str(getattr(fc, "anchor_id", "") or "")
            same = not anchor_id or aid in ("", "0") or aid == str(anchor_id)
            if level > 0 and status in (1, 2) and same:
                lvl = max(lvl, level)
    except Exception:
        pass
    return lvl


def describe_badges(user):
    """Для проверки на живом эфире (tools/tiktok_probe.py): какие значки пришли у зрителя."""
    out = []
    for b in getattr(user, "badge_list", None) or []:
        st = getattr(b, "scene_type", None)
        ple = getattr(b, "privilege_log_extra", None)
        out.append(f"{getattr(st, 'name', st)}:{getattr(ple, 'level', '')}")
    fc = getattr(getattr(user, "fans_club", None), "data", None)
    if fc is not None and (getattr(fc, "level", 0) or getattr(fc, "club_name", "")):
        out.append(f"fans_club:{getattr(fc, 'club_name', '')}/lvl{getattr(fc, 'level', 0)}"
                   f"/status{_val(getattr(fc, 'user_fans_club_status', 0))}/anchor{getattr(fc, 'anchor_id', '')}")
    return out


class Team:
    """Участники команды: {"@ник": {"nick", "user", "acc", "level", "since", "seen", "via"}}."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.members = {}
        self.by_acc = {}
        self._saved_at = 0.0
        self._dirty = False
        self.load()

    @staticmethod
    def key(user):
        return "@" + str(user or "").strip().lstrip("@").lower()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            m = d.get("members") if isinstance(d, dict) else None
            self.members = {k: v for k, v in (m or {}).items() if isinstance(v, dict) and k.startswith("@")}
        except Exception:
            self.members = {}
        self.by_acc = {str(v.get("acc")): k for k, v in self.members.items() if v.get("acc")}

    def save(self, force=False):
        with self.lock:
            if not force and not self._dirty:
                return
            data = {"members": dict(self.members)}
            self._dirty = False
            self._saved_at = time.time()
        try:
            safeio.write_json(self.path, data, indent=1)
        except Exception:
            self._dirty = True

    def add(self, user, display="", acc="", level=0, via="значок"):
        """Запомнить участника. → True, если он новый (или вернулся после очистки)."""
        k = self.key(user)
        if k == "@":
            return False
        now = time.strftime("%Y-%m-%d %H:%M")
        with self.lock:
            m, moved = self.members.get(k), False
            if m is None and acc and self.by_acc.get(str(acc)) in self.members:
                m, moved = self.members.pop(self.by_acc[str(acc)]), True     # сменил @ник — тот же аккаунт
            new = m is None
            if new:
                m = {"since": now, "via": via}
            changed = new or moved or (level and int(level) > int(m.get("level") or 0)) or (acc and not m.get("acc"))
            m.update(nick=str(display or m.get("nick") or user), user=str(user).lstrip("@"), seen=now)
            if acc:
                m["acc"] = str(acc)
                self.by_acc[str(acc)] = k
            if level:
                m["level"] = max(int(level), int(m.get("level") or 0))
            self.members[k] = m
            if changed:
                self._dirty = True
        if changed:
            self.save()
        return new

    def has(self, user="", display="", acc=""):
        if acc and str(acc) in self.by_acc:
            return True
        return any(self.key(x) in self.members for x in (user, display) if str(x or "").strip())

    def remove(self, user):
        k = self.key(user)
        with self.lock:
            m = self.members.pop(k, None)
            if m and m.get("acc"):
                self.by_acc.pop(str(m["acc"]), None)
            self._dirty = bool(m)
        self.save()
        return bool(m)

    def clear(self):
        with self.lock:
            n = len(self.members)
            self.members, self.by_acc, self._dirty = {}, {}, True
        self.save(force=True)
        return n

    def public(self, limit=30):
        items = sorted(self.members.values(), key=lambda m: m.get("seen") or m.get("since") or "", reverse=True)
        return {"count": len(self.members),
                "recent": [{"nick": m.get("nick"), "user": m.get("user"), "level": m.get("level") or 0,
                            "since": m.get("since"), "via": m.get("via")} for m in items[:limit]]}
