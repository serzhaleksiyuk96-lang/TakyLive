"""Пишет release_notes.md для страницы релиза из changelog.json (запись текущей версии)."""
import json, os, re
v = os.environ.get("TAKY_VERSION") or re.search(r'APP_VERSION = "([^"]+)"', open("app.py", encoding="utf-8").read()).group(1)
log = json.load(open("changelog.json", encoding="utf-8"))
entry = next((e for e in log if e.get("version") == v), None)
lines = [f"## Что нового в {v}", ""] + [f"- {x}" for x in (entry or {}).get("changes", ["Мелкие улучшения"])]
lines += ["", "**Установка:** скачай `TakyLive-Setup-" + v + ".exe` и запусти. Если Windows покажет «Windows защитила ваш компьютер» — "
          "«Подробнее» → «Выполнить в любом случае».", "",
          "**Уже стоит TakyLive?** Программа обновится сама: значок версии в шапке → «Обновить»."]
open("release_notes.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
