"""Защита озвучки от мата, троллинга и спама.

Мат и оскорбления ищутся по корням с учётом хитростей: латиница вместо кириллицы (x у й),
транслит (huy, blyat, ya gey), «красивые» шрифты (𝔥𝔲𝔦), цифры (3 → з, 6 → б), растянутые буквы
(хууууй), буквы через пробел или точку (х у й, х.у.й), слово, разорванное пробелом (х уй).
Корни привязаны к началу слова или к известным приставкам — поэтому «застрахуй», «рубля», «небо»,
«мандарин», «геймер», «уродился», «хулиган» не считаются плохими.

Троллинг — фразы, которые зрители пишут, чтобы озвучка сказала гадость голосом стримера:
«я гей», «ягей», «ты даун», «стример лох». Такие сообщения не читаются целиком.
"""
import difflib
import re
import unicodedata

# ── нормализация ─────────────────────────────────────────────────────────────
_LOOK = {"a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м", "o": "о", "p": "р",
         "t": "т", "x": "х", "y": "у", "u": "и", "i": "и", "ё": "е",
         # похожие буквы других алфавитов
         "і": "и", "ї": "и", "є": "е", "ґ": "г", "ў": "у", "ӏ": "л", "ѕ": "с",
         "α": "а", "ο": "о", "ρ": "р", "τ": "т", "χ": "х", "κ": "к", "ε": "е", "μ": "м", "β": "в"}
_LEET = {"0": "о", "3": "з", "4": "ч", "6": "б", "1": "и", "@": "а", "$": "с"}
_MAP = dict(_LOOK, **_LEET)
_LAT = str.maketrans(_MAP)
_LAT_U = str.maketrans(dict(_MAP, u="у"))           # латинская u бывает и «и», и «у»
_LOOK_T = str.maketrans(_LOOK)
_LOOK_U = str.maketrans(dict(_LOOK, u="у"))
_TR2 = [("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ch", "ч"), ("sh", "ш"), ("ts", "ц"),
        ("yu", "ю"), ("ju", "ю"), ("iu", "ю"), ("ya", "я"), ("ja", "я"), ("ia", "я"), ("yo", "е"), ("jo", "е"),
        ("ye", "е"), ("je", "е")]
_TR1 = {"a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "й",
        "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т",
        "u": "у", "v": "в", "w": "в", "x": "кс", "z": "з", "'": "ь"}
_VOW = set("аеёиоуыэюяaeiouy")


# маленькие заглавные (ʜᴜɪ) NFKC не трогает — переводим сами
_SMALL = str.maketrans("ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡʏᴢ", "abcdefghijklmnopqrstuvwyz")


def prep(text):
    """«Красивые» шрифты → обычные буквы, без невидимых символов и зачёркиваний, строчными."""
    t = unicodedata.normalize("NFKC", str(text or "")).translate(_SMALL)
    return "".join(ch for ch in t if unicodedata.category(ch) not in ("Mn", "Me", "Cf")).lower()


def _translit(word):
    """Транслит латиницей → кириллица: huy → хуй, blyat → блят, ya gey → я гей."""
    w = word
    for a, b in _TR2:
        w = w.replace(a, b)
    out = []
    for i, ch in enumerate(w):
        if ch == "y":                          # y после гласной — «й» (gey, huy), иначе «ы» (ty)
            out.append("й" if i and w[i - 1] in "аеиоуэюяaeiou" else "ы")
        else:
            out.append(_TR1.get(ch, ch))
    return "".join(out)


def _clean(w, keep=r"а-яa-z"):
    w = re.sub(r"[^%s]" % keep, "", w.replace("ё", "е"))
    return re.sub(r"(.)\1+", r"\1", w)                 # хууууй → хуй


def _variants(word):
    """Как слово могло быть написано: кириллицей, латиницей «под кириллицу» (u = и / у), транслитом."""
    low = prep(word)
    forms = [low.translate(_LAT), low.translate(_LAT_U), low]
    if re.search(r"[a-z]", low):
        forms.insert(2, _translit(low))
    out = []
    for w in forms:
        w = _clean(w)
        if w and w not in out:
            out.append(w)
    return out


def _norm(word):
    v = _variants(word)
    return v[0] if v else ""


def words(text):
    return re.findall(r"\w+", prep(text), flags=re.U)


# ── мат, оскорбления, слуры ──────────────────────────────────────────────────
_PRE = r"(?:по|на|за|от|до|ни|об|о|раз|рас|вы|у|при|пере|про|под|с|съ|недо|долбо|дол[б]?о)?"
_EPRE = r"(?:вы|за|на|от|отъ|по|под|подъ|при|раз|разъ|рас|у|съ|изъ|объ|долбо|недо|об|въ)"
_MAT = [
    _PRE + r"ху[йеяюи]", r"хул[иеь]$", r"пизд", r"пезд", r"пiзд", r"пзд",
    _EPRE + r"?[её]б(?:а|у|е|л|н|т|и|ё|ыв|ырь)",
    _EPRE + r"[её]бо", r"(?:долбо|недо|за|у|вы)[её]б$",
    r"[её]б(?:ан|ат|уч|ну|ло|ли|ля)",
    r"бля(?:д|т|ть|)$", r"бляд", r"блят",
    r"сук(?:а|и|у|е|ой|ам|ами|ах|ин|ина|ины)$", r"сучк", r"сучар", r"сучь",
    r"муд(?:ак|ил|о|ня|озвон)", r"п[еи]д[оа]?р(?!о)", r"педераст", r"педик", r"г[ао]ндон", r"шлюх", r"залуп",
    r"манд(?:а|ой|у|ы|ец|авошк)$", r"дроч", r"(?:на|по|ни|за)?хер(?:ня|ни|ней|ов|ова|ово|н|а|у|ом|)$",
    r"fuck", r"shit", r"bitch", r"cunt", r"whore", r"slut", r"dick(?:head|s|)$", r"pussy", r"motherf",
]
# оскорбления — читать их голосом стримера тоже не надо
_INSULT = [
    r"дебил", r"дегенерат", r"даун(?:а|у|ом|е|ы|ов|ам|ами|ах|енок|ята|)$", r"ублюд",
    r"урод(?:ы|ов|а|у|ом|е|ина|ец|цы|ливый|ливая|ливое|ливые|ство|)$", r"чмо(?:шник|шница|шники|)$", r"чмыр",
    r"мраз(?:ь|и|ей|ота|)$", r"твар(?:ь|юка|юки|)$", r"выродо?к", r"гнид(?:а|ы|у|ой|ам|)$",
    r"падл(?:а|ы|у|ой|о|юка|юки|)$", r"сволоч", r"шавк", r"нищеброд", r"гомик", r"retard",
]
# слуры — за их озвучку банят стримы
_SLUR = [
    r"нигг?ер", r"нигга", r"негр(?:ы|ов|ам|у|а|ом|итос|иля|)$", r"хач(?:и|ей|ик|ом|ам|у|а|)$", r"чурк",
    r"жид(?:ы|ов|ам|ами|у|а|ом|е|ок|яра|яры|яр|овск\w*|овк\w*|)$",
    r"хох(?:ол|лы|лов|лам|ла|лу|лом|лушка|лушки|ляцк\w*|лятск\w*)$",
    r"кацап", r"москал(?:ь|и|ей|ям|я|ю|ями|ях|ик|ики|ский|ская|ские|)$", r"чучмек", r"узкоглаз", r"черножоп",
    r"пиндос", r"nigg", r"faggot",
]
_KINDS = [("мат", re.compile(r"^(?:" + "|".join(_MAT) + ")")),
          ("оскорбление", re.compile(r"^(?:" + "|".join(_INSULT + _SLUR) + ")"))]
# английские слова, которые в транслите похожи на мат: her → хер, hue → хуе, ebay → ебай
_OK_LATIN = {"her", "hers", "hue", "hues", "ebay", "manda", "huevo", "huevos"}
_URL = re.compile(r"(?:https?://|www\.|\b[\w-]+\.(?:ru|com|net|org|io|gg|me|tv|xyz|by|su|kz|ua)\b)", re.I)


def bad_kind(word, extra=()):
    """Что за плохое слово: «мат», «оскорбление», «троллинг» (ягей), «запрещённое» (свои слова стримера) или None."""
    raw = re.sub(r"[^a-zа-яё]", "", prep(word))
    vs = [raw] if raw in _OK_LATIN else _variants(word)
    for w in vs:
        for kind, rx in _KINDS:
            if rx.search(w):
                return kind
        if w in _GLUED:
            return "троллинг"
        if any(x and w.startswith(x) for x in extra):
            return "запрещённое"
    return None


def is_bad_word(word, extra=()):
    return bad_kind(word, extra) is not None


def censor(text, extra_words=(), replace="пип", kinds=None):
    """→ (текст_с_заменой, нашлось_ли). Ловит и «х у й», «х.у.й» — буквы по одной, и «х уй» — разорванное слово.

    kinds — если передать множество, туда сложатся найденные виды («мат», «оскорбление», «троллинг», «запрещённое»)."""
    extra = [_norm(x) for x in extra_words if _norm(x)]
    tokens = re.findall(r"\w+|[^\w]+", prep(text), flags=re.U)
    orig = re.findall(r"\w+|[^\w]+", unicodedata.normalize("NFKC", str(text or "")), flags=re.U)
    out = list(orig) if len(orig) == len(tokens) else list(tokens)   # по возможности — как написал зритель
    found_kinds = kinds if kinds is not None else set()
    word_idx = [i for i, t in enumerate(tokens) if re.match(r"\w", t)]

    def hit(a, b, k):
        out[a] = replace
        for j in range(a + 1, b + 1):
            out[j] = ""
        found_kinds.add(k)

    for i in word_idx:
        k = bad_kind(tokens[i], extra)
        if k:
            hit(i, i, k)
    # буквы по одной: «х у й», «х.у.й», «я х у й»
    runs, run = [], []
    for i in word_idx:
        if len(tokens[i]) == 1 and (not run or i - run[-1] == 2):
            run.append(i)
        else:
            if len(run) >= 3:
                runs.append(run)
            run = [i] if len(tokens[i]) == 1 else []
    if len(run) >= 3:
        runs.append(run)
    for run in runs:
        run = run[:40]
        s = 0
        while s <= len(run) - 3:
            done = False
            for e in range(len(run), s + 2, -1):
                k = bad_kind("".join(tokens[j] for j in run[s:e]), extra)
                if k:
                    hit(run[s], run[e - 1], k)
                    s, done = e, True
                    break
            if not done:
                s += 1
    # разорванное слово: «х уй», «пи зда», «бл ять» — короткий кусок + соседнее слово
    for a, b in zip(word_idx, word_idx[1:]):
        if out[a] in (replace, "") or out[b] in (replace, ""):
            continue
        if min(len(tokens[a]), len(tokens[b])) > 2:
            continue
        k = bad_kind(tokens[a] + tokens[b], extra)
        if k:
            hit(a, b, k)
    found = any(o == replace for o in out) and bool(found_kinds)
    res = re.sub(r"\s{2,}", " ", "".join(out)).strip()
    return res, found


def plain_name(name):
    """Ник обычными буквами: 𝓓𝓪𝓻𝓲 → Dari, ʜᴜɪ → hui, без зачёркиваний и невидимых символов (регистр как был)."""
    n = unicodedata.normalize("NFKC", str(name or "")).translate(_SMALL)
    return "".join(ch for ch in n if unicodedata.category(ch) not in ("Mn", "Me", "Cf")).strip()


def safe_name(name, extra_words=()):
    """Ник для озвучки: «красивые» шрифты → обычные буквы; с матом, оскорблением или «ягей» — «зритель»."""
    n = plain_name(name)
    if not n:
        return "зритель"
    _, bad = censor(n, extra_words)
    if bad or troll_reason(n):
        return "зритель"
    return n


# ── троллинг: «я гей», «ты даун», «стример лох» ──────────────────────────────
_SUBJ = {"я", "йа", "ты", "ти", "он", "она", "мы", "вы", "они", "стример", "стримерша", "автор", "ведущий",
         "ведущая", "админ", "модер", "модератор", "бот", "тыже", "яже"}
_PRED = {"гей", "геи", "гея", "гею", "геем", "гомик", "гомики", "гомосек", "гомосеки", "лесби", "лесбиянка",
         "лесбуха", "лох", "лохи", "лошара", "лошары", "лошок", "даун", "дауны", "дебил", "дебилы", "дебилка",
         "дебик", "аутист", "аутисты", "аутистка", "чмо", "урод", "уроды", "клоун", "клоуны", "нищеброд",
         "дурак", "дура", "дураки", "тупой", "тупая", "тупые", "идиот", "идиотка", "идиоты", "лузер", "инцел",
         "скуф", "девственник", "пидор", "пидр", "педик", "шлюха", "сучка", "даунёнок", "олень", "лохушка"}
_FILL = {"тоже", "же", "такой", "такая", "такие", "просто", "реально", "вообще", "ваще", "правда", "конкретно",
         "полный", "полная", "полные", "натуральный", "настоящий", "конченый", "конченный", "главный", "самый",
         "короче", "кароче", "тут", "здесь", "еще", "уже", "это", "типа", "походу", "точно", "оказывается",
         "теперь", "сегодня", "опять", "снова", "всегда", "бро", "братан", "что", "чо", "че", "реальный"}
_SUBJ = {_clean(x) for x in _SUBJ}
_PRED = {_clean(x) for x in _PRED}
_FILL = {_clean(x) for x in _FILL}
# «ягей», «тылох» — склеенные слова; в обратном порядке не склеиваем: «гей»+«мы» = «геймы», «лох»+«мы» = «лохмы»
_GLUED = {_clean(s + p) for s in _SUBJ for p in _PRED} - _PRED - _SUBJ


def troll_reason(text):
    """«я гей», «ягей», «я г е й», «ya gey», «ты такой даун», «гей» одним словом → «троллинг», иначе None."""
    raw = words(text)[:60]
    ws = [v for v in (set(_variants(w)) for w in raw) if v]
    if not ws:
        return None
    # буквы по одной: «я г е й» → «ягей»
    letters = [w for w in raw if len(w) == 1]
    if len(letters) >= 3 and len(letters) >= len(raw) - 1:
        joined = set(_variants("".join(letters)))
        if joined & (_GLUED | _PRED):
            return "троллинг"

    def near(i, step, want):
        """Есть ли слово из want через 0–3 «пустых» слова (тоже, такой, реально…) от i."""
        j = i + step
        while 0 <= j < len(ws) and abs(j - i) <= 4 and ws[j] & _FILL and not ws[j] & want:
            j += step
        return 0 <= j < len(ws) and bool(ws[j] & want)

    for i, v in enumerate(ws):
        if v & _GLUED:
            return "троллинг"
        if v & _SUBJ and near(i, 1, _PRED):
            return "троллинг"                          # «я гей», «ты такой даун»
        if v & _PRED and len(ws) <= 5 and near(i, 1, _SUBJ):
            return "троллинг"                          # «гей я», «лох это ты»
    if len(ws) <= 2 and all(v & (_PRED | _FILL) for v in ws) and any(v & _PRED for v in ws):
        return "троллинг"                              # одно «гей» / «лох» / «даун»
    return None


# ── свои стоп-фразы стримера: ловятся без пробелов, с хитрыми буквами и транслитом ──
def _pforms(word):
    """5 написаний слова для стоп-фраз (цифры остаются цифрами: «67» — это «67»)."""
    low = prep(word)
    keep = r"а-яa-z0-9"
    look, look_u = _clean(low.translate(_LOOK_T), keep), _clean(low.translate(_LOOK_U), keep)
    tr = _clean(_translit(low), keep) if re.search(r"[a-z]", low) else look
    leet = _clean(low.translate(_LAT), keep) if re.search(r"[^\W\d_]", low) else look
    return [look, look_u, tr, _clean(low, keep), leet]


def _views(ws):
    forms = [_pforms(w) for w in ws]
    return {re.sub(r"(.)\1+", r"\1", "".join(f[k] for f in forms)) for k in range(5)} - {""}


def phrase_hit(text, phrases):
    """Есть ли в сообщении одна из фраз — целыми словами, но без учёта пробелов, повторов букв и шрифтов.
    «сиксевен» ловит «сикс севен», «six seven», «с и к с е в е н»; «я гей» ловит «ягей», «ya gey».
    Звёздочка в конце — «начинается с»: «левитир*» ловит «левитирует»."""
    keys = []
    for p in phrases:
        p = str(p).strip()
        pref = p.endswith("*")
        pw = words(p.rstrip("*"))
        if pw:
            keys.extend((k, pref) for k in _views(pw))
    if not keys:
        return None
    exact = {k for k, pref in keys if not pref}
    prefs = [k for k, pref in keys if pref]
    maxlen = max(len(k) for k, _ in keys)
    ws = words(text)[:80]
    forms = [_pforms(w) for w in ws]
    for i in range(len(ws)):
        acc = [""] * 5
        for j in range(i, min(len(ws), i + 12)):
            acc = [acc[k] + forms[j][k] for k in range(5)]
            vs = {re.sub(r"(.)\1+", r"\1", a) for a in acc} - {""}
            if vs & exact or any(v.startswith(k) for v in vs for k in prefs):
                return " ".join(ws[i:j + 1])
            if vs and min(len(v) for v in vs) > maxlen + 2:
                break
    return None


# ── мусор ────────────────────────────────────────────────────────────────────
def collapse(text, keep=2):
    """«дааааа» → «даа», «ахахахахах» → «ахах»: растяжки не мучают озвучку. Числа не трогаем: «1000» — это 1000."""
    t = re.sub(r"(\D)\1{%d,}" % keep, lambda m: m.group(1) * keep, str(text))
    return re.sub(r"([^\W\d_]{2})\1{2,}", r"\1\1", t)


_ROWS = ["йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
_MASH = {r[i:i + 5] for r in _ROWS + [r[::-1] for r in _ROWS] for i in range(len(r) - 4)}


def gibberish_reason(text):
    """Набор букв: «колбаса» без пробелов (даданетнетдабудетсвет), «фывапролдж», «ывпрлдж»."""
    for w in re.findall(r"[а-яёa-z]+", prep(collapse(text)), flags=re.U):
        w = re.sub(r"(.)\1+", r"\1", w.replace("ё", "е"))
        if len(w) >= 22 or (len(w) >= 14 and re.search(r"(\w{2,4})\1", w)):
            return "набор букв"
        if re.search(r"[^аеиоуыэюяaeiouy]{6,}", w) or (len(w) >= 7 and not (set(w) & _VOW)):
            return "набор букв"
        if len(w) >= 5 and any(w[i:i + 5] in _MASH for i in range(len(w) - 4)):
            return "набор букв"
    return None


def junk_reason(text):
    """Почему сообщение — мусор (или None): растяжки, одни смайлы, ссылки, набор букв."""
    t = prep(text).strip()
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
    stretched = sum(len(m.group(0)) for m in re.finditer(r"([^\W\d_])\1{3,}", t, flags=re.U))
    if stretched >= 4 and stretched / len(letters) >= 0.5:
        return "растяжка"
    # одна и та же «фраза» много раз: «лол лол лол лол»
    ws = re.findall(r"\w+", t)
    if len(ws) >= 4 and len(set(ws)) <= max(1, len(ws) // 4):
        return "повтор слов"
    return gibberish_reason(t)


# ── повторы ──────────────────────────────────────────────────────────────────
def squash(text):
    """Сообщение для сравнения повторов: буквы и цифры слитно, латиница-двойник → кириллица, «ааа» → «а».
    Цифры остаются цифрами: «счёт 1:0» и «счёт 2:0» — разные сообщения."""
    t = "".join(words(text)).translate(_LOOK_T).replace("ё", "е")
    t = re.sub(r"[^а-яa-z0-9]", "", t)
    return re.sub(r"([^\d])\1+", r"\1", t)


def similar(a, b, ratio=0.82):
    """Почти одно и то же: «ало замуть типа спамит» ~ «ало замутьте типа спамит» (a, b — после squash)."""
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < 6:
        return False
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sm.real_quick_ratio() >= ratio and sm.quick_ratio() >= ratio and sm.ratio() >= ratio
