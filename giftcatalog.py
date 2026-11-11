"""Каталог подарков TikTok всех регионов: ID, название, цена, официальная картинка.

Источник — сам TikTok: запрос /webcast/gift/list/ с параметром региона
(region / priority_region). Каталог хранится в gift_catalog.json и
пополняется: по кнопке «🌍 Загрузить подарки региона», при подключении
к эфиру (список своего региона) и подарками, пришедшими в эфире.
"""
import json
import os
import time

# Регионы, где есть TikTok LIVE с подарками (как в каталоге Stream To Earn)
REGIONS = [
    ("RU", "Россия"), ("KZ", "Казахстан"), ("UZ", "Узбекистан"), ("BY", "Беларусь"), ("UA", "Украина"),
    ("KG", "Кыргызстан"), ("TJ", "Таджикистан"), ("AZ", "Азербайджан"),
    ("AM", "Армения"), ("GE", "Грузия"), ("MD", "Молдова"), ("TR", "Турция"), ("PL", "Польша"),
    ("DE", "Германия"), ("LT", "Литва"), ("LV", "Латвия"), ("EE", "Эстония"), ("US", "США"),
    ("GB", "Великобритания"), ("FR", "Франция"), ("IT", "Италия"), ("ES", "Испания"), ("PT", "Португалия"),
    ("NL", "Нидерланды"), ("BE", "Бельгия"), ("AT", "Австрия"), ("CH", "Швейцария"), ("CZ", "Чехия"),
    ("SK", "Словакия"), ("HU", "Венгрия"), ("RO", "Румыния"), ("BG", "Болгария"), ("RS", "Сербия"),
    ("HR", "Хорватия"), ("SI", "Словения"), ("BA", "Босния и Герцеговина"), ("MK", "Северная Македония"),
    ("XK", "Косово"), ("GR", "Греция"), ("CY", "Кипр"), ("FI", "Финляндия"), ("SE", "Швеция"), ("NO", "Норвегия"),
    ("DK", "Дания"), ("IE", "Ирландия"), ("IL", "Израиль"), ("AE", "ОАЭ"), ("SA", "Саудовская Аравия"),
    ("QA", "Катар"), ("KW", "Кувейт"), ("BH", "Бахрейн"), ("OM", "Оман"), ("JO", "Иордания"), ("LB", "Ливан"),
    ("IQ", "Ирак"), ("PS", "Палестина"), ("EG", "Египет"), ("MA", "Марокко"), ("DZ", "Алжир"), ("TN", "Тунис"),
    ("LY", "Ливия"), ("ZA", "ЮАР"), ("TZ", "Танзания"), ("IN", "Индия"), ("PK", "Пакистан"), ("NP", "Непал"),
    ("LK", "Шри-Ланка"), ("MV", "Мальдивы"), ("ID", "Индонезия"), ("MY", "Малайзия"), ("SG", "Сингапур"),
    ("TH", "Таиланд"), ("VN", "Вьетнам"), ("PH", "Филиппины"), ("JP", "Япония"), ("KR", "Южная Корея"),
    ("TW", "Тайвань"), ("HK", "Гонконг"), ("AU", "Австралия"), ("NZ", "Новая Зеландия"), ("CA", "Канада"),
    ("MX", "Мексика"), ("BR", "Бразилия"), ("AR", "Аргентина"), ("CL", "Чили"), ("CO", "Колумбия"),
    ("PE", "Перу"), ("EC", "Эквадор"), ("BO", "Боливия"), ("PY", "Парагвай"), ("UY", "Уругвай"),
    ("VE", "Венесуэла"), ("CR", "Коста-Рика"), ("PA", "Панама"), ("GT", "Гватемала"), ("HN", "Гондурас"),
    ("SV", "Сальвадор"), ("NI", "Никарагуа"), ("DO", "Доминикана"), ("PR", "Пуэрто-Рико"), ("JM", "Ямайка"),
    ("TT", "Тринидад и Тобаго"), ("SR", "Суринам"), ("LC", "Сент-Люсия"), ("MQ", "Мартиника"),
]


def walk_gifts(obj, out):
    """Находит в ответе TikTok все подарки: {id: {name, coins, icon}}."""
    if isinstance(obj, dict):
        gid, name = obj.get("id"), obj.get("name")
        if gid and isinstance(name, str) and name.strip() and ("diamond_count" in obj or "image" in obj or "icon" in obj):
            icon = ""
            for key in ("image", "icon"):
                im = obj.get(key) or {}
                urls = im.get("url_list") or im.get("urlList") or im.get("m_urls") or []
                if urls:
                    icon = str(urls[0])
                    break
            out[str(gid)] = {"name": name.strip(), "coins": int(obj.get("diamond_count") or 0), "icon": icon}
        for v in obj.values():
            walk_gifts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            walk_gifts(v, out)


class GiftCatalog:
    def __init__(self, path, log):
        self.path, self.log = path, log
        self.data = {"gifts": {}, "regions": {}}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data["gifts"].update(d.get("gifts") or {})
                self.data["regions"].update(d.get("regions") or {})
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:
            self.log("ОШИБКА", f"каталог подарков не сохранился: {e}")

    def merge(self, found, region=""):
        """Добавляет подарки → (сколько новых, сколько всего пришло)."""
        new = 0
        for gid, g in found.items():
            cur = self.data["gifts"].get(gid)
            if cur is None:
                cur = self.data["gifts"][gid] = {"name": g["name"], "coins": g.get("coins", 0), "icon": "", "regions": []}
                new += 1
            if g.get("icon"):
                cur["icon"] = g["icon"]
            if g.get("coins"):
                cur["coins"] = g["coins"]
            if region and region not in cur["regions"]:
                cur["regions"].append(region)
        if region:
            self.data["regions"][region] = {"count": len(found), "at": time.strftime("%Y-%m-%d %H:%M")}
        self.save()
        return new, len(found)

    def remember_live(self, gid, name, coins, icon):
        """Подарок пришёл в эфире — запоминаем его с картинкой."""
        if not gid or not name:
            return
        self.merge({str(gid): {"name": str(name), "coins": int(coins or 0), "icon": icon or ""}}, "эфир")

    async def fetch_region(self, region, web_get, gift_list_url):
        """Спрашивает у TikTok список подарков региона (без подключения к эфиру)."""
        params = {"app_language": "en", "webcast_language": "en"}
        if region != "ALL":                    # TikTok всё равно отдаёт список по IP — страну не передаём без нужды
            params.update(region=region, priority_region=region)
        r = await web_get(url=gift_list_url, extra_params=params)
        data = r.json() if hasattr(r, "json") else r
        found = {}
        walk_gifts(data.get("data", data) if isinstance(data, dict) else data, found)
        if not found:
            raise RuntimeError("TikTok не прислал список подарков — попробуй позже")
        new, total = self.merge(found, region)
        name = "Список TikTok" if region == "ALL" else dict(REGIONS).get(region, region)
        self.log("ПОДАРКИ", f"{name}: TikTok прислал {total} подарков, новых в каталоге — {new}")
        return {"region": region, "name": name, "total": total, "new": new}

    def public(self):
        return {"gifts": [{"id": k, **v} for k, v in self.data["gifts"].items()],
                "regions": self.data["regions"], "known": REGIONS}
