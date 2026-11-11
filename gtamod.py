"""Мод TakyLive для GTA 5: поиск папки игры, проверка Script Hook V и .NET, установка одной кнопкой.

Ищем GTA 5 там, куда её ставят Steam, Epic Games и Rockstar Launcher (обычная и Enhanced).
Ставим только свой мод (scripts/TakyLive.3.cs) и убираем старый TikTokBridge.3.cs.
Script Hook V и Script Hook V .NET Enhanced раздавать нельзя — их авторы это запрещают,
поэтому проверяем, стоят ли они, и даём ссылки на официальные страницы.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import sys

WIN = sys.platform == "win32"
MOD_NAME = "TakyLive.3.cs"
OLD_MODS = ["TikTokBridge.3.cs", "TikTokBridge.cs", "TikTokBridge.dll"]
LINKS = {
    "shv": "http://www.dev-c.com/gtav/scripthookv/",
    "shvdn": "https://www.gta5-mods.com/tools/script-hook-v-net-enhanced",
}
GAME_DIRS = ["Grand Theft Auto V", "Grand Theft Auto V Enhanced", "GTAV", "GTA V", "GTA5"]


def edition(path):
    if os.path.isfile(os.path.join(path, "GTA5_Enhanced.exe")):
        return "enhanced"
    if os.path.isfile(os.path.join(path, "GTA5.exe")):
        return "legacy"
    return None


def _steam_libraries():
    libs = []
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam = winreg.QueryValueEx(k, "SteamPath")[0]
        libs.append(steam)
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            for p in re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="ignore").read()):
                libs.append(p.replace("\\\\", "\\"))
    except Exception:
        pass
    return libs


def _registry_folders():
    out = []
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (r"SOFTWARE\WOW6432Node\Rockstar Games\Grand Theft Auto V",
                        r"SOFTWARE\WOW6432Node\Rockstar Games\GTA V Enhanced",
                        r"SOFTWARE\Rockstar Games\Grand Theft Auto V"):
                try:
                    k = winreg.OpenKey(root, key)
                    out.append(winreg.QueryValueEx(k, "InstallFolder")[0])
                except OSError:
                    continue
    except Exception:
        pass
    return out


def _epic_folders():
    out = []
    for f in glob.glob(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item"):
        try:
            d = json.load(open(f, encoding="utf-8"))
            if "grand theft auto v" in str(d.get("DisplayName", "")).lower():
                out.append(d.get("InstallLocation", ""))
        except Exception:
            continue
    return out


def find_games(extra=()):
    """Все найденные папки GTA 5 (без повторов), сначала — те, что указал пользователь."""
    cand = [p for p in extra if p]
    if WIN:
        for lib in _steam_libraries():
            for g in GAME_DIRS[:2]:
                cand.append(os.path.join(lib, "steamapps", "common", g))
        cand += _registry_folders() + _epic_folders()
        for drive in "CDEFGHIJ":
            for rel in (r"Program Files\Rockstar Games", r"Program Files\Epic Games", r"Program Files (x86)\Steam\steamapps\common",
                        r"SteamLibrary\steamapps\common", r"Steam\steamapps\common", r"Games", r"Игры"):
                for g in GAME_DIRS:
                    cand.append(os.path.join(f"{drive}:\\", rel, g))
    seen, out = set(), []
    for p in cand:
        try:
            key = os.path.normcase(os.path.abspath(p))
        except Exception:
            continue
        if key in seen or not os.path.isdir(p) or not edition(p):
            continue
        seen.add(key)
        out.append(os.path.abspath(p))
    return out


def _sha(path):
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except Exception:
        return ""


def status(path, bundled):
    ex = lambda f: os.path.isfile(os.path.join(path, f))
    mod = os.path.join(path, "scripts", MOD_NAME)
    return {
        "path": path, "edition": edition(path),
        "shv": ex("ScriptHookV.dll") and ex("dinput8.dll"),
        "shvdn": ex("ScriptHookVDotNet.asi") and ex("ScriptHookVDotNet3.dll"),
        "mod": os.path.isfile(mod),
        "mod_current": os.path.isfile(mod) and _sha(mod) == _sha(bundled),
        "old": [f for f in OLD_MODS if os.path.isfile(os.path.join(path, "scripts", f))],
    }


def install(path, bundled):
    if not edition(path):
        raise RuntimeError("в этой папке нет GTA5.exe — это не папка игры")
    scripts = os.path.join(path, "scripts")
    os.makedirs(scripts, exist_ok=True)
    shutil.copy2(bundled, os.path.join(scripts, MOD_NAME))
    removed = []
    for f in OLD_MODS:                       # старый мод слушал бы те же команды — подарки сработали бы дважды
        p = os.path.join(scripts, f)
        if os.path.isfile(p):
            os.remove(p)
            removed.append(f)
    return removed
