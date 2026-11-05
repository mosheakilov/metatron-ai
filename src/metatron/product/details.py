"""Pull property details out of a free line the broker typed or pasted.

"חיפה, הנשיא 10, 4 חדרים, 95 מ"ר, 2.1 מיליון" -> city, address, rooms, area, price.
Rule based (no AI, works offline). Whatever is not recognised is kept as a note, so nothing
the broker wrote is lost, and the broker sees the result on screen before saving.
"""

from __future__ import annotations

import re

CITIES = """
אום אל פחם, אופקים, אור יהודה, אור עקיבא, אילת, אלעד, אריאל, אשדוד, אשקלון, באקה אל גרבייה,
באר יעקב, באר שבע, בית שאן, בית שמש, ביתר עילית, בני ברק, בת ים, גבעת שמואל, גבעתיים, גדרה,
גן יבנה, גני תקווה, דאלית אל כרמל, דימונה, הוד השרון, הרצליה, זכרון יעקב, חדרה, חולון, חיפה,
חריש, טבריה, טייבה, טירה, טירת כרמל, טמרה, יבנה, יהוד, יהוד מונוסון, יקנעם, יקנעם עילית,
ירוחם, ירושלים, כפר יונה, כפר סבא, כפר קאסם, כרמיאל, להבים, לוד, מבשרת ציון, מגדל העמק,
מודיעין, מודיעין מכבים רעות, מודיעין עילית, מזכרת בתיה, מעלה אדומים, מעלות תרשיחא, מצפה רמון,
נהריה, נס ציונה, נוף הגליל, נצרת, נצרת עילית, נשר, נתיבות, נתניה, סחנין, עכו, עפולה, עמנואל,
ערד, עתלית, פרדס חנה, פרדס חנה כרכור, פתח תקווה, פתח תקוה, צפת, קדימה, קדימה צורן, קיסריה,
קצרין, קריית אונו, קריית אתא, קריית ביאליק, קריית גת, קריית ים, קריית מוצקין, קריית מלאכי,
קריית שמונה, קרית אונו, קרית אתא, קרית ביאליק, קרית גת, קרית ים, קרית מוצקין, קרית מלאכי,
קרית שמונה, קרית טבעון, קריית טבעון, ראש העין, ראש פינה, ראשון לציון, רהט, רחובות, רמלה,
רמת גן, רמת השרון, רמת ישי, רעננה, שדרות, שוהם, שלומי, תל אביב, תל אביב יפו, יפו, תל מונד,
אבן יהודה, אזור, אליכין, בנימינה, גבעת זאב, גבעת עדה, גן נר, חצור הגלילית, כוכב יאיר, כפר ורדים,
כפר תבור, כרכור, מיתר, עומר, עין שמר, פרדסיה, צור יגאל, צור הדסה, קרני שומרון, קריית עקרון,
רמת ישי, שערי תקווה, תל אביב-יפו, ת"א, ראשל"צ, פ"ת, ב"ש, ק. אתא, ק. ביאליק, ק. מוצקין, ק. ים
"""
ALIASES = {'ת"א': "תל אביב", 'ראשל"צ': "ראשון לציון", 'פ"ת': "פתח תקווה", 'ב"ש': "באר שבע",
           "ק. אתא": "קריית אתא", "ק. ביאליק": "קריית ביאליק", "ק. מוצקין": "קריית מוצקין",
           "ק. ים": "קריית ים", "תל אביב-יפו": "תל אביב יפו"}
TOWN_PREFIX = re.compile(r"^(?:כפר|קרית|קריית|מושב|קיבוץ|גבעת|נווה|נוה|רמת|מעלה|אבן|נוף|עין|מצפה|"
                         r"שדה|אור|באר|ראש|הר|מבוא|יד|גני|בני|צור|כוכב|טל|מגדל|נחלת|תל)\s+[א-ת]")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("״", '"').replace("׳", "'").replace("-", " ")).strip()


_CITY_SET = {_norm(c): c.strip() for c in CITIES.replace("\n", " ").split(",") if c.strip()}
# longest first, so "קריית אתא" wins over a shorter match
_CITY_RE = re.compile(r"(?<![א-ת])(ב)?(" + "|".join(
    re.escape(c) for c in sorted(_CITY_SET, key=len, reverse=True)) + r")(?![א-ת])")

_NUM = r"\d+(?:[.,]\d+)?"
ROOMS = re.compile(rf"(?:({_NUM})\s*(?:חדרים|חדר|חד['׳]?)(?![א-ת])|חדרים\s*:?\s*({_NUM}))")
AREA = re.compile(r"(?:(\d{2,4})\s*(?:מ[\"״]ר|מטר(?:ים)?|מ['׳]ר|מר|sqm|m2)(?![א-ת])"
                  r"|שטח\s*:?\s*(\d{2,4}))")
PRICE = [
    (re.compile(rf"(?:מחיר\s*:?\s*)?({_NUM})\s*(?:מיליון|מליון|מיל['׳]?)(?:\s*(?:₪|ש[\"״]?ח))?"),
     1_000_000),
    (re.compile(rf"(?:מחיר\s*:?\s*)?({_NUM})\s*(?:אלף|K|k)(?![א-ת])(?:\s*(?:₪|ש[\"״]?ח))?"), 1000),
    (re.compile(r"(?:מחיר\s*:?\s*)?₪\s*(\d[\d,.]*)"), 1),
    (re.compile(r"(?:מחיר\s*:?\s*)?(\d[\d,.]*)\s*(?:₪|ש[\"״]?ח|שקל(?:ים)?)"), 1),
    (re.compile(r"מחיר\s*:?\s*(\d[\d,.]*)"), 1),
    (re.compile(r"(?<![\d.,])(\d{1,2}(?:,\d{3}){2}|\d{6,8})(?![\d.,])"), 1),  # bare 2,150,000
]
ADDRESS = re.compile(r"^(?:(?:רחוב|רח['׳]?|שד['׳]|שדרות|כתובת\s*:?)\s*)?"
                     r"[א-תA-Za-z][א-תA-Za-z\"'׳״.\- ]*?\s+\d{1,4}[א-ת]?"
                     r"(?:\s*(?:/|דירה|דירה\s*מס['׳]?)\s*\d{1,4})?$")
STREET_WORD = re.compile(r"^(?:רחוב|רח['׳]|שד['׳]|שדרות)\s+[א-ת]")
NOT_ADDRESS = re.compile(r"^(?:קומה|קומת|דירה|דירת|בית|חדר|חדרי|מרפסת|מרפסות|חניה|חניות|חנייה|מחסן|"
                         r"שירותים|מקלחות|כיווני|מעלית|בן|בת|גיל|שנת|בניין|בנין)(?![א-ת])")
FILLER = {"דירה", "דירת", "נכס", "למכירה"}
LABEL = re.compile(r"^(?:עיר|ישוב|יישוב|כתובת|רחוב|הערות?|פרטים|נכס)\s*:\s*")
# label words left alone once their value was taken ("טלפון:", "ב-" before a price)
DROP = re.compile(r"^(?:טלפון|טל['׳]?|נייד|פלאפון|פל['׳]|מספר|וואטסאפ|שם|שם מלא|מחיר|חדרים|שטח|ב)"
                  r"\s*[:\-]?$")
STREET_ANY = re.compile(r"(?<![א-ת])ב?((?:רחוב|רח['׳]|שדרות|שד['׳])\s+[א-ת][א-ת\"'׳״\-]*"
                        r"(?:\s+[א-ת][א-ת\"'׳״\-]*){0,3}?\s+\d{1,4}[א-ת]?(?:\s*/\s*\d{1,4})?)(?!\d)")


def price_of(text: str) -> tuple[int | None, str]:
    for rx, mult in PRICE:
        m = rx.search(text)
        if not m:
            continue
        raw = m.group(1)
        if mult == 1:
            value = float(raw.replace(",", "").rstrip("."))
        else:
            value = float(raw.replace(",", ".")) * mult
        if value >= 10_000:
            return int(value), text[:m.start()] + " , " + text[m.end():]
    return None, text


def _num(raw: str) -> float:
    v = float(raw.replace(",", "."))
    return int(v) if v.is_integer() else v


def city_of(text: str) -> str | None:
    t = _norm(text)
    c = ALIASES.get(t) or _CITY_SET.get(t)
    if c:
        return ALIASES.get(c, c)
    if t.startswith("ב") and (c := _CITY_SET.get(t[1:])):
        return ALIASES.get(c, c)
    if TOWN_PREFIX.match(t) and not re.search(r"\d", t) and len(t.split()) <= 3:
        return t
    return None


def parse(text: str) -> dict:
    """Return {city, address, rooms, area_sqm, asking_price, notes}; missing parts are ""."""
    out = {"city": "", "address": "", "rooms": "", "area_sqm": "", "asking_price": "", "notes": ""}
    rest = text
    price, rest = price_of(rest)
    if price:
        out["asking_price"] = str(price)
    if m := ROOMS.search(rest):
        out["rooms"] = str(_num(m.group(1) or m.group(2)))
        rest = rest[:m.start()] + " , " + rest[m.end():]
    if m := AREA.search(rest):
        out["area_sqm"] = m.group(1) or m.group(2)
        rest = rest[:m.start()] + " , " + rest[m.end():]

    # "ברחוב הרצל 5" anywhere in a sentence
    if m := STREET_ANY.search(rest):
        out["address"] = m.group(1).strip()
        rest = rest[:m.start()] + " , " + rest[m.end():]
    # "בתל אביב" anywhere, but not "ירושלים 5" (a street called after a city)
    flat = rest.replace("-", " ").replace("״", '"').replace("׳", "'")
    for m in _CITY_RE.finditer(flat):
        if re.match(r"\s*\d", flat[m.end():]):
            continue
        out["city"] = ALIASES.get(_CITY_SET[m.group(2)], _CITY_SET[m.group(2)])
        rest = rest[:m.start()] + " , " + rest[m.end():]
        break

    notes = []
    for seg in re.split(r"\s*(?:[,;|\n]|\s[-–]\s)\s*", rest):
        seg = LABEL.sub("", seg.strip(" .-–"))
        if not seg:
            continue
        if not out["city"] and (c := city_of(seg)):
            out["city"] = c
            continue
        # "הנשיא 10 חיפה" or "חיפה הנשיא 10": a city glued to the address
        if not out["city"] and (m := _CITY_RE.search(_norm(seg))):
            other = (_norm(seg)[:m.start()] + " " + _norm(seg)[m.end():]).strip()
            if other and not NOT_ADDRESS.match(other) and (ADDRESS.match(other)
                                                           or STREET_WORD.match(other)):
                out["city"] = ALIASES.get(_CITY_SET[m.group(2)], _CITY_SET[m.group(2)])
                seg = other
        if seg in FILLER or DROP.match(seg):
            continue
        if not out["address"] and not NOT_ADDRESS.match(seg) and (ADDRESS.match(seg)
                                                                   or STREET_WORD.match(seg)):
            out["address"] = re.sub(r"^(?:כתובת\s*:?)\s*", "", seg)
            continue
        notes.append(seg)
    out["notes"] = ", ".join(notes)
    return out


def found_any(d: dict) -> bool:
    return any(d[k] for k in ("city", "address", "rooms", "area_sqm", "asking_price"))
