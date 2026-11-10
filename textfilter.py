"""Защита озвучки от мата и спама.

Мат ищется по корням с учётом хитростей: латиница вместо кириллицы (x у й),
цифры (3 → з, 6 → б), растянутые буквы (хууууй), буквы через пробел или точку.
Корни привязаны к началу слова или к известным приставкам — поэтому «застрахуй»,
«рубля», «небо», «мандарин» не считаются матом.
"""
import re

_MAP = {"a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м", "o": "о", "p": "р",
        "t": "т", "x": "х", "y": "у", "u": "и", "i": "и", "ё": "е", "0": "о", "3": "з", "4": "ч", "6": "б",
        "1": "и", "@": "а", "$": "с"}
_LAT = str.maketrans(_MAP)
_LAT_U = str.maketrans(dict(_MAP, u="у"))           # латинская u бывает и «и», и «у»
_PRE = r"(?:по|на|за|от|до|ни|об|о|раз|рас|вы|у|при|пере|про|под|с|съ|недо|долбо|дол[б]?о)?"
# Корни: (приставка)? + корень от начала слова
_BAD = [
    _PRE + r"ху[йеяюи]", r"пизд", r"пезд", r"пiзд",
    r"(?:вы|за|на|от|по|под|при|раз|рас|у|съ|долбо|недо|об|въ)?[её]б(?:а|у|л|н|т|и|ё|ыв|ырь)",
    r"(?:вы|за|на|от|по|под|при|раз|рас|у|съ|долбо|недо)[её]бо",
    r"(?:долбо|недо|за|у|вы)[её]б$",
    r"[её]б(?:ан|ат|уч|ну|ло|ли|ля)",
    r"бля(?:д|т|ть|)$", r"бляд", r"блят",
    r"сук(?:а|и|у|е|ой|ам|ин)$", r"сучк", r"сучар",
    r"муд(?:ак|ил|о|ня|озвон)", r"п[еи]д(?:о|а)?р", r"педик", r"г[ао]ндон", r"шлюх", r"залуп",
    r"манд(?:а|ой|у|ы|ец)$", r"дроч", r"хер(?:ня|ов|н|)$",
    # слуры — за их озвучку банят стримы
    r"нигг?ер", r"ниггa", r"хач(?:и|ей|ик|ом|ам|у|а|)$", r"чурк", r"жид(?:ы|ов|ам|овск|яр|)$",
    r"fuck", r"shit", r"bitch", r"nigg", r"cunt", r"faggot",
]
_BAD_RE = re.compile(r"^(?:" + "|".join(_BAD) + ")")
_URL = re.compile(r"(?:https?://|www\.|\b[\w-]+\.(?:ru|com|net|org|io|gg|me|tv|xyz|by)\b)", re.I)


def _variants(word):
    """Как слово могло быть написано: кириллицей, латиницей «под кириллицу» (u = и / у) и как есть."""
    low = word.lower()
    out = []
    for w in (low.translate(_LAT), low.translate(_LAT_U), low):
        w = re.sub(r"[^а-яa-z]", "", w)
        w = re.sub(r"(.)\1+", r"\1", w)                # хууууй → хуй
        if w and w not in out:
            out.append(w)
    return out


def _norm(word):
    v = _variants(word)
    return v[0] if v else ""


def is_bad_word(word, extra=()):
    for w in _variants(word):
        if _BAD_RE.search(w) or any(x and w.startswith(x) for x in extra):
            return True
    return False


def censor(text, extra_words=(), replace="пип"):
    """→ (текст_с_заменой, нашёлся_ли_мат). Ловит и «х у й», «х.у.й» — буквы по одной."""
    extra = [_norm(x) for x in extra_words if _norm(x)]
    tokens = re.findall(r"\w+|[^\w]+", str(text), flags=re.U)
    found = False
    # слова целиком
    words = [i for i, t in enumerate(tokens) if re.match(r"\w", t)]
    for i in words:
        if is_bad_word(tokens[i], extra):
            tokens[i] = replace
            found = True
    # буквы по одной: «х у й», «х.у.й»
    run = []
    for i in words + [None]:
        if i is not None and len(tokens[i]) == 1 and (not run or i - run[-1] == 2):
            run.append(i)
            continue
        if len(run) >= 3 and is_bad_word("".join(tokens[j] for j in run), extra):
            tokens[run[0]] = replace
            for j in run[1:]:
                tokens[j] = ""
            for j in range(run[0] + 1, run[-1]):
                if not re.match(r"\w", tokens[j]):
                    tokens[j] = ""
            found = True
        run = [i] if (i is not None and len(tokens[i]) == 1) else []
    return re.sub(r"\s{2,}", " ", "".join(tokens)).strip(), found


def collapse(text, keep=2):
    """«дааааа» → «даа», «ахахахахах» → «ахах»: растяжки не мучают озвучку."""
    t = re.sub(r"(.)\1{%d,}" % keep, lambda m: m.group(1) * keep, str(text))
    return re.sub(r"(\w\w)\1{2,}", r"\1\1", t)


def junk_reason(text):
    """Почему сообщение — мусор (или None): растяжки, одни смайлы, ссылки."""
    t = str(text).strip()
    if not t:
        return "пусто"
    if _URL.search(t):
        return "ссылка"
    letters = re.findall(r"[^\W\d_]", t, flags=re.U)
    if len(letters) < 2:
        return "нет слов"
    if len(letters) / max(1, len(re.sub(r"\s", "", t))) < 0.4:
        return "одни символы"
    # растяжки: «аааааа нооооогггг» — больше половины букв в повторах по 4+
    stretched = sum(len(m.group(0)) for m in re.finditer(r"([^\W\d_])\1{3,}", t.lower(), flags=re.U))
    if stretched >= 4 and stretched / len(letters) >= 0.5:
        return "растяжка"
    # одна и та же «фраза» много раз: «лол лол лол лол»
    words = re.findall(r"\w+", t.lower())
    if len(words) >= 4 and len(set(words)) <= max(1, len(words) // 4):
        return "повтор слов"
    return None
