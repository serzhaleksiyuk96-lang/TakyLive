"""Проверка фильтра озвучки: что ловится, что — нет.  python tools/textfilter_test.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import textfilter as tf  # noqa: E402

STOP = ["сиксевен", "сикс севен", "six seven", "67 летний", "парта левитирует"]

MAT = ["хуй", "х уй", "х у й", "х.у.й", "x.y.й", "𝔥𝔲𝔦", "ʜᴜɪ", "huy", "hui", "blyat", "pizda", "нахер", "пздц",
       "xyй", "хууууй", "пи зда", "бл ять", "сука", "ёб твою мать", "он ебет", "хули ты", "пидор", "педераст",
       "fuck you", "я х у й", "охуенно", "нихера себе", "х̶у̶й̶", "Х У Й", "пиzда", "пи3да", "ебaть", "suka"]
INSULT = ["ты даун", "дебил", "урод", "чмо", "мразь", "хохол", "хохлы", "негр", "жиды", "кацапы", "москали",
          "чурка", "нищеброд"]
TROLL = ["ягей", "я гей", "я г е й", "ya gey", "я гeй", "ты даун", "ты такой даун", "стример лох", "гей",
         "лох это ты", "Я ГЕЙ", "я_гей", "ягееей", "йа гей", "ты что дурак", "я тоже гей", "гей я", "ЯГЕЙ!!!",
         "я.г.е.й", "тылох", "ты реально клоун"]
STOPPED = ["сиксевен", "сикс севен", "six seven", "SIX SEVEN", "с и к с е в е н", "сиксевееен", "сикс-севен",
           "в класс заходит 67 летний учительница в велосепетках и спрашивает почему у вас парта левитирует"]
JUNK = ["даданетнетдабудетсвет", "фывапролдж", "ывпрлдж", "ааааааааа", "лол лол лол лол", "https://x.ru",
        "😂😂😂😂", "ЙЦУКЕН", "qwerty"]
CLEAN = ["геймер", "моя геймерская мышка", "уродился красивым", "дай рубля", "небо голубое", "хлеб", "себя",
         "сукно", "мандарин", "застрахуй машину", "оскорблять нельзя", "лохматый кот", "хулиган", "художник",
         "Педро", "хохолок", "жидкий", "хачапури", "Москаленко", "Херсон", "колебать", "чмок", "привет как дела",
         "достопримечательность", "даунхилл", "ахахаха", "я нищий студент", "ты лучший", "стример топ",
         "привет всем", "ало замуть типа спамит", "сикс", "67 рублей", "her name is anna", "ebay", "небу",
         "ребята", "Здравствуйте", "взгляд", "бодрствовать", "контрольная", "мне 67", "гейминг", "я играю в гейм",
         "хохлома", "ты молодец", "он клёвый", "мы тут", "негромко", "сучок", "урожай", "я не понял",
         "спасибо за стрим", "даня привет", "в класс заходит учительница", "дебют", "падение", "дурашка",
         "купил гемы", "лохмы торчат", "новые геймы", "гейты открылись", "я выиграл", "ты играешь", "он играет"]

fails = []


def check(name, cond, detail=""):
    if not cond:
        fails.append(f"{name} {detail}")


for s in MAT:
    k = set()
    clean, bad = tf.censor(s, kinds=k)
    check("мат не пойман:", bad and "мат" in k, f"{s!r} → {clean!r} {k}")
for s in INSULT:
    k = set()
    clean, bad = tf.censor(s, kinds=k)
    check("оскорбление не поймано:", bad and "оскорбление" in k, f"{s!r} → {clean!r} {k}")
for s in TROLL:
    check("троллинг не пойман:", tf.troll_reason(s) == "троллинг", repr(s))
for s in STOPPED:
    check("стоп-фраза не поймана:", tf.phrase_hit(s, STOP), repr(s))
for s in JUNK:
    check("мусор не пойман:", tf.junk_reason(s), repr(s))
for s in CLEAN:
    clean, bad = tf.censor(s)
    check("ложный мат:", not bad, f"{s!r} → {clean!r}")
    check("ложный троллинг:", not tf.troll_reason(s), repr(s))
    check("ложная стоп-фраза:", not tf.phrase_hit(s, STOP), f"{s!r} → {tf.phrase_hit(s, STOP)!r}")
    check("ложный мусор:", not tf.junk_reason(s), f"{s!r} → {tf.junk_reason(s)}")

# замена сохраняет остальной текст как есть
check("замена:", tf.censor("Привет, сука!")[0] == "Привет, пип!", repr(tf.censor("Привет, сука!")))
check("замена х у й:", tf.censor("ну х у й, ладно")[0] == "ну пип, ладно", repr(tf.censor("ну х у й, ладно")))
check("замена х уй:", tf.censor("иди х уй")[0] == "иди пип", repr(tf.censor("иди х уй")))
check("свои слова:", tf.censor("ты кринж", ["кринж"])[1], "")
check("свои слова мимо:", not tf.censor("ты топ", ["кринж"])[1], "")
# ники
check("ник шрифтом:", tf.safe_name("𝓓𝓪𝓻𝓲") == "Dari", repr(tf.safe_name("𝓓𝓪𝓻𝓲")))
check("ник с матом:", tf.safe_name("хуесос228") == "зритель", "")
check("ник-тролль:", tf.safe_name("ягей") == "зритель", "")
check("обычный ник:", tf.safe_name("Педро") == "Педро", "")
check("пустой ник:", tf.safe_name("  ") == "зритель", "")
check("тролль в тексте:", tf.censor("спасибо ягей за подарок")[0] == "спасибо пип за подарок", repr(tf.censor("спасибо ягей за подарок")))
# повторы
sq = tf.squash
check("копия:", tf.similar(sq("ало замуть типа спамит"), sq("ало замуть типа спамит!!")), "")
check("почти копия:", tf.similar(sq("ало замуть типа спамит"), sq("ало замутьте типа спамит")), "")
check("копия латиницей:", tf.similar(sq("ягей"), sq("ЯГЕЕЕЙ")), "")
check("разные:", not tf.similar(sq("привет как дела"), sq("какая музыка играет")), "")
check("растяжки:", tf.collapse("дааааа ахахахахах!!!!!") == "даа ахах!!", repr(tf.collapse("дааааа ахахахахах!!!!!")))
check("числа целиком:", tf.collapse("1000 подписчиков, 121212") == "1000 подписчиков, 121212", repr(tf.collapse("1000 подписчиков, 121212")))
check("цифры различаются:", sq("привет 111") != sq("привет 117") and sq("счёт 1:0") != sq("счёт 2:0"), "")
# звёздочка — «начинается с»
check("стоп со звёздочкой:", tf.phrase_hit("парта левитирует", ["левитир*"]), "")
check("стоп без звёздочки:", not tf.phrase_hit("левитирует", ["левитир"]), "")
check("стоп 67:", tf.phrase_hit("6 7", ["67"]) and not tf.phrase_hit("1967", ["67"]), "")

# 👥 команда: запоминается на диск, узнаётся по @нику и по аккаунту, сменённый ник не дублируется
import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import team  # noqa: E402
d = tempfile.mkdtemp(prefix="taky_team_")
try:
    path = os.path.join(d, "team_members.json")
    t = team.Team(path)
    check("новый участник:", t.add("Milana_S", "Милана", "111", 7) is True and t.add("milana_s", "Милана", "111", 7) is False, "")
    check("по нику и по аккаунту:", t.has("@milana_s") and t.has("", "", "111") and not t.has("kostya"), "")
    t.add("artem", "Артём", "", 0, "подарок «Heart Me»")
    t2 = team.Team(path)
    check("после перезапуска на месте:", t2.has("artem") and t2.has("milana_s") and t2.public()["count"] == 2, str(t2.public()))
    t2.add("milana_new", "Милана", "111", 8)
    check("сменила @ник — одна запись, уровень вырос:", t2.public()["count"] == 2 and t2.has("milana_new")
          and not t2.has("milana_s") and team.Team(path).members["@milana_new"]["level"] == 8, str(t2.members))
    check("убрать и очистить:", t2.remove("artem") and t2.public()["count"] == 1 and t2.clear() == 1
          and json.load(open(path, encoding="utf-8")) == {"members": {}}, "")
    check("подарок вступления:", team.is_join_gift("Heart Me", "") and team.is_join_gift("", "7934")
          and team.is_join_gift("От всего сердца") and not team.is_join_gift("Rose", "5655"), "")
finally:
    shutil.rmtree(d, ignore_errors=True)
# значок команды — на настоящих объектах TikTokLive (если библиотека стоит)
try:
    import TikTokLive.proto as P  # noqa: E402
    have_tt = True
except Exception:
    have_tt = False
if have_tt:
    u = P.User(badge_list=[P.BadgeStruct(scene_type=P.BadgeSceneType.FANS, privilege_log_extra=P.PrivilegeLogExtra(level="5"))])
    sub = P.User(badge_list=[P.BadgeStruct(scene_type=P.BadgeSceneType.SUBSCRIBER, privilege_log_extra=P.PrivilegeLogExtra(level="9"))])
    club = P.User(fans_club=P.FansClubMember(data=P.FansClubData(level=2, user_fans_club_status=1, anchor_id=42)))
    check("значок команды (FANS) → уровень:", team.badge_level(u) == 5, str(team.describe_badges(u)))
    check("значок подписчика — не команда:", team.badge_level(sub) == 0, "")
    check("фан-клуб этого стримера — да, чужого — нет:", team.badge_level(club, 42) == 2 and team.badge_level(club, 7) == 0, "")
else:
    print("(TikTokLive не установлен — проверка значка на настоящих объектах пропущена)")

total = len(MAT) + len(INSULT) + len(TROLL) + len(STOPPED) + len(JUNK) + 4 * len(CLEAN) + 28 + (3 if have_tt else 0)
print(f"{total - len(fails)}/{total} PASS")
for f in fails:
    print("FAIL", f)
sys.exit(1 if fails else 0)
