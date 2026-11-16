"""Надёжное хранение данных стримера.

1. write_json / write_text — запись «по-взрослому»: сначала во временный файл рядом, потом
   мгновенная подмена. Если программу убьют посреди записи (обновление, выключение ПК,
   антивирус) — на диске остаётся либо старый целый файл, либо новый целый, но не обрывок.
2. Snapshots — резервные копии настроек и вкладок в _backup/auto/<дата>-<повод>/:
   при запуске, перед обновлением и перед восстановлением. Хранится 12 последних.
3. load_json_safe — если файл повреждён, не затираем его пустым, а откладываем в сторону
   («….broken-<дата>») и поднимаем данные из последней копии.
"""
import json
import os
import shutil
import threading
import time

USER_FILES = ["config.json", "profiles.json", "viewer_voices.json", "viewer_points.json", "gift_names_ru.json",
              os.path.join("servers", "servers.json")]
KEEP_SNAPSHOTS = 12


def write_text(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}_{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    last = None
    for i in range(6):                        # на Windows файл на миг может держать антивирус или OneDrive
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.05 * (i + 1))
    try:                                      # совсем не дали подменить — пишем напрямую, как раньше
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if last and not os.path.exists(path):
        raise last


def write_json(path, data, **kw):
    kw.setdefault("ensure_ascii", False)
    write_text(path, json.dumps(data, **kw))      # сначала целиком в строку: ошибка в данных не испортит файл


def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


class Snapshots:
    def __init__(self, base_dir, log=None):
        self.base = base_dir
        self.dir = os.path.join(base_dir, "_backup", "auto")
        self.log = log or (lambda *a: None)

    def _list_dirs(self):
        try:
            return sorted(d for d in os.listdir(self.dir) if os.path.isdir(os.path.join(self.dir, d)))
        except OSError:
            return []

    def _same_as_latest(self):
        dirs = self._list_dirs()
        if not dirs:
            return False
        last = os.path.join(self.dir, dirs[-1])
        for f in USER_FILES:
            a, b = os.path.join(self.base, f), os.path.join(last, f)
            if os.path.isfile(a) != os.path.isfile(b):
                return False
            if os.path.isfile(a):
                try:
                    with open(a, "rb") as fa, open(b, "rb") as fb:
                        if fa.read() != fb.read():
                            return False
                except OSError:
                    return False
        return True

    def make(self, reason, force=False):
        """Копия данных стримера. Возвращает имя копии или "" (нечего копировать / такая уже есть)."""
        try:
            if not any(os.path.isfile(os.path.join(self.base, f)) for f in USER_FILES[:2]):
                return ""
            if not force and self._same_as_latest():
                return ""
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(reason))[:40] or "copy"
            name = time.strftime("%Y%m%d-%H%M%S") + "-" + safe
            dst = os.path.join(self.dir, name)
            n = 2
            while os.path.exists(dst):
                dst = os.path.join(self.dir, f"{name}-{n}")
                n += 1
            os.makedirs(dst)
            for f in USER_FILES:
                src = os.path.join(self.base, f)
                if os.path.isfile(src):
                    os.makedirs(os.path.dirname(os.path.join(dst, f)), exist_ok=True)
                    shutil.copy2(src, os.path.join(dst, f))
            for old in self._list_dirs()[:-KEEP_SNAPSHOTS]:
                shutil.rmtree(os.path.join(self.dir, old), ignore_errors=True)
            return os.path.basename(dst)
        except Exception as e:
            self.log("ОШИБКА", f"резервная копия не создалась: {e}")
            return ""

    def list(self):
        out = []
        for d in reversed(self._list_dirs()):
            p = os.path.join(self.dir, d)
            tabs, events = None, 0
            try:
                prof = read_json(os.path.join(p, "profiles.json"))
                if isinstance(prof, dict):
                    tabs = len(prof)
                    events = sum(len(v) for t in prof.values() if isinstance(t, dict)
                                 for v in t.values() if isinstance(v, list))
            except Exception:
                pass
            reason = d[16:]
            try:
                when = time.strftime("%d.%m.%Y %H:%M", time.strptime(d[:15], "%Y%m%d-%H%M%S"))
            except ValueError:
                when = d
            out.append({"id": d, "when": when, "reason": reason.replace("_", " "), "tabs": tabs, "events": events})
        return out

    def path(self, sid):
        sid = os.path.basename(str(sid or ""))
        p = os.path.join(self.dir, sid)
        return p if sid and os.path.isdir(p) else ""

    def latest_with(self, fname):
        """Самая свежая копия, где файл fname читается как JSON → (данные, имя копии)."""
        for d in reversed(self._list_dirs()):
            try:
                return read_json(os.path.join(self.dir, d, fname)), d
            except Exception:
                continue
        return None, ""


def load_json_safe(path, snaps, expect, log_lines):
    """Читает JSON-файл данных. Повреждён → откладываем в сторону и берём из последней копии.
    Возвращает данные или None (файла нет / восстановить не из чего)."""
    if not os.path.exists(path):
        return None
    name = os.path.basename(path)
    try:
        data = read_json(path)
        if not isinstance(data, expect):
            raise ValueError("не тот формат")
        return data
    except Exception as e:
        broken = f"{path}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.copy2(path, broken)
        except OSError:
            broken = ""
        data, snap = snaps.latest_with(name) if snaps else (None, "")
        if isinstance(data, expect):
            log_lines.append(f"⚠ {name} был повреждён ({e}) — восстановил из резервной копии {snap}. "
                             f"Повреждённый файл сохранён: {os.path.basename(broken)}")
            try:
                write_json(path, data, indent=2)
            except Exception:
                pass
            return data
        log_lines.append(f"⚠ {name} повреждён ({e}), а резервной копии нет. Повреждённый файл сохранён: "
                         f"{os.path.basename(broken)} — пришли его разработчику, данные можно спасти")
        return None
