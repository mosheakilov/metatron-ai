"""Import the broker's client list (Excel or CSV) into the seller table.

Brokers export lists from many places (Yad2 notes, Excel they keep by hand, nadlan-pro,
phone contacts), so columns are matched by name in Hebrew or English and the broker can fix
the mapping in the dashboard before anything is saved. Nothing is sent on import.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

from metatron.outreach.store import Store, normalize_phone
from metatron.product import details

# field -> header aliases (lower-case, compared after removing spaces, quotes and punctuation)
FIELDS: dict[str, list[str]] = {
    "name": ["שם", "שםמלא", "שםהלקוח", "שםהמוכר", "איששקשר", "לקוח", "מוכר", "name", "fullname",
             "contact", "firstname"],
    "phone": ["טלפון", "נייד", "פלאפון", "מספרטלפון", "טלפוןנייד", "וואטסאפ", "ווצאפ", "phone",
              "mobile", "cell", "whatsapp", "tel", "phonenumber"],
    "city": ["עיר", "ישוב", "יישוב", "city", "town"],
    "address": ["כתובת", "רחוב", "כתובתהנכס", "address", "street"],
    "rooms": ["חדרים", "מספרחדרים", "חדר", "rooms"],
    "area_sqm": ["מר", "שטח", "גודל", "מטרים", "area", "sqm", "size"],
    "asking_price": ["מחיר", "מחירמבוקש", "price", "askingprice"],
    "notes": ["הערות", "הערה", "פרטים", "notes", "note", "comments"],
    "deal_type": ["סוגעסקה", "עסקה", "deal", "dealtype"],
    "property_type": ["סוגנכס", "סוגהנכס", "סוג", "propertytype", "type"],
    "floor": ["קומה", "floor"],
    "floors_total": ["קומותבבניין", "מספרקומותבבניין", "מספרקומות", "סהכקומות", "מתוך", "קומות", "floors"],
    "neighborhood": ["שכונה", "אזור", "neighborhood", "area_name"],
    "listing_ref": ["מספרמודעה", "מודעה", "מזהה", "מסמודעה", "id", "listingid", "adid"],
    "listed_on": ["תאריך", "תאריךפרסום", "תאריךעדכון", "עדכוןמודעה", "עודכן", "date", "updated"],
}
REQUIRED = ("name", "phone")
NUMERIC = ("rooms", "area_sqm", "asking_price", "floor", "floors_total")


def _key(header: str) -> str:
    return re.sub(r"[\s\"'`׳״.\-_:/()]", "", str(header or "")).lower()


def read_rows(filename: str, content: bytes) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) as strings. Supports .xlsx and .csv (UTF-8 or Windows Hebrew)."""
    suffix = Path(filename).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(content), read_only=True, data_only=True).worksheets[0]
        table = [["" if v is None else _cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
    elif suffix in (".csv", ".txt"):
        for enc in ("utf-8-sig", "cp1255"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("לא הצלחתי לקרוא את הקובץ: קידוד לא מוכר")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
        table = list(csv.reader(io.StringIO(text), dialect))
    else:
        raise ValueError("סוג קובץ לא נתמך. שמרו כ-Excel (.xlsx) או CSV.")
    table = [r for r in table if any(str(c).strip() for c in r)]
    if not table:
        raise ValueError("הקובץ ריק")
    width = max(len(r) for r in table)
    table = [list(r) + [""] * (width - len(r)) for r in table]
    return [str(h).strip() for h in table[0]], [[str(c).strip() for c in r] for r in table[1:]]


PHONE_IN_TEXT = re.compile(r"(?<![\d+])(?:\+?972[\s\-]?|0)5\d(?:[\s\-]?\d){7}(?!\d)")


def read_pasted(text: str) -> tuple[list[str], list[list[str]]]:
    """Clients pasted as text. Three shapes are understood:

    - cells copied from Excel / Google Sheets (tab-separated), with or without a header row;
    - CSV with a header row (name and phone columns);
    - a list of ads copied from a listing site (Yad2 and the like): one field per line, every
      ad the same number of lines (deal, city, street, type, rooms, floor, price, phone, date,
      neighbourhood, m², floors, contact, ad number). The columns are told apart by content;
    - free lines, one client per line, e.g. "יעל כהן 050-1234567 חיפה, הנשיא 10": the phone is
      found anywhere in the line, the text before it is the name and the rest becomes a note.
      A name on its own line followed by a phone on the next line is joined.
    """
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        raise ValueError("לא הודבק טקסט")
    if any("\t" in ln for ln in lines):
        return _table([ln.split("\t") for ln in lines])
    if "," in lines[0] and _has_header(next(csv.reader([lines[0]]))):
        return _table(list(csv.reader(lines)))
    if records := _records(lines):
        return _table(records)

    keys = ("city", "address", "rooms", "area_sqm", "asking_price", "notes")
    rows: list[dict] = []
    pending, early = "", {}  # a name line, and details lines, still waiting for their phone
    for ln in lines:
        m = PHONE_IN_TEXT.search(ln)
        if not m:
            if NAME_LABEL.match(ln):  # "שם: משה כהן" starts a new client
                pending, early = NAME_LABEL.sub("", ln).strip(), {}
                continue
            d = details.parse(ln)
            if details.found_any(d) or details.LABEL.match(ln):
                if pending or not rows:
                    early = _merge(early or dict.fromkeys(d, ""), d)
                else:
                    _merge(rows[-1], d)  # a details line under the client's phone line
            else:
                pending = f"{pending} {ln}".strip() if pending else ln
            continue
        before = PHONE_LABEL.sub("", ln[:m.start()]).strip(" \t,;:-–|")
        after = ln[m.end():].strip(" \t,;:-–|")
        name, _, extra = before.partition(",")  # "יעל כהן, חיפה 050-..." -> name, details
        name = NAME_LABEL.sub("", name).strip() or pending
        if not name and after:  # "050-1234567 יעל כהן, חיפה"
            name, after = _leading_name(after)
        row = {"name": name, "phone": m.group()}
        row.update(details.parse(", ".join(x for x in (extra.strip(), after) if x)))
        if early:
            _merge(row, early)
        rows.append(row)
        pending, early = "", {}
    if not rows:
        raise ValueError("לא נמצאו מספרי טלפון בטקסט")
    return (["שם", "טלפון", "עיר", "כתובת", "חדרים", "שטח", "מחיר", "הערות"],
            [[r["name"], r["phone"], *(r[k] for k in keys)] for r in rows])


def _merge(row: dict, d: dict) -> dict:
    for k, v in d.items():
        if not v:
            continue
        if k == "notes":
            row[k] = ", ".join(x for x in (row[k], v) if x)
        elif not row[k]:
            row[k] = v
    return row


NAME_LABEL = re.compile(r"^\s*(?:שם(?:\s*מלא)?|שם הלקוח|לקוח|מוכר|איש קשר)\s*[:\-]\s*")
PHONE_LABEL = re.compile(r"(?:טלפון|טל['׳]?|נייד|פלאפון|פל['׳]|מספר|וואטסאפ)\s*[:\-]?\s*$")
STREET_START = re.compile(r"^ב?(?:רחוב|רח['׳]|שד['׳]|שדרות)$")


def _leading_name(text: str) -> tuple[str, str]:
    """Up to two plain words at the start, stopping where a city or street begins."""
    head, sep, tail = text.partition(",")
    words, take = head.split(), 0
    while take < min(2, len(words)):
        w, rest = words[take], " ".join(words[take:])
        if (not re.fullmatch(r"[א-תA-Za-z\"'׳״]+", w) or STREET_START.match(w)
                or details._CITY_RE.match(rest.replace("-", " "))):
            break
        take += 1
    rest = " ".join(words[take:]) + (sep + tail if sep else "")
    return " ".join(words[:take]), rest.strip(" ,")


def _has_header(cells: list[str]) -> bool:
    m = guess_mapping(cells)
    return m["name"] is not None and m["phone"] is not None and not any(
        PHONE_IN_TEXT.search(c) for c in cells)


def _table(table: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    width = max(len(r) for r in table)
    table = [[c.strip() for c in r] + [""] * (width - len(r)) for r in table]
    if _has_header(table[0]):
        return table[0], table[1:]
    return _guess_headers(table), table


DEAL = re.compile(r"^(?:למכירה|להשכרה|מכירה|השכרה|למסירה)$")
PROPERTY = re.compile(r"^(?:דירה|דירת גן|דירת גג|גג\s*/\s*פנטהאוז|פנטהאוז|מיני פנטהאוז|גג|דופלקס|"
                      r"טריפלקס|בית פרטי\s*/?\s*קוטג['׳]?|בית פרטי|קוטג['׳]?|דו משפחתי|דו-משפחתי|"
                      r"יחידת דיור|סטודיו|לופט|וילה|משק|נחלה|מגרש|בית|מרתף\s*/\s*פרטר|פרטר)$")
DATE = re.compile(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}$")
INT_OR_DASH = re.compile(r"^(?:\d+(?:[.,]\d+)?|-|—)$")
HEADER = {"deal_type": "סוג עסקה", "property_type": "סוג נכס", "listed_on": "תאריך פרסום",
          "asking_price": "מחיר", "listing_ref": "מספר מודעה", "city": "עיר", "address": "כתובת",
          "rooms": "חדרים", "floor": "קומה", "floors_total": "קומות בבניין", "area_sqm": "שטח",
          "name": "שם", "neighborhood": "שכונה", "notes": "הערות"}


def _cell_kind(c: str) -> str:
    if PHONE_IN_TEXT.fullmatch(c.replace(" ", "")):
        return "phone"
    if DATE.match(c):
        return "date"
    if DEAL.match(c):
        return "deal"
    if PROPERTY.match(re.sub(r"\s+", " ", c)):
        return "ptype"
    if re.search(r"₪|ש[\"״]?ח|מיליון|מליון|אלף", c) and details.price_of(c)[0]:
        return "price"
    if re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}", c):
        return "price"
    if INT_OR_DASH.match(c):
        return "num"
    if details._CITY_SET.get(details._norm(c)) or details.ALIASES.get(details._norm(c)):
        return "city"
    if details.ADDRESS.match(c) or details.STREET_WORD.match(c):
        return "address"
    if re.fullmatch(r"[^\d]+", c):
        return "text"
    return "other"


def _guess_headers(table: list[list[str]]) -> list[str]:
    """Name each column of a table without a header row by what most of its cells hold."""
    width = len(table[0])
    cols = [[r[i] for r in table if r[i]] for i in range(width)]
    kind = []
    for cells in cols:
        votes: dict[str, int] = {}
        for c in cells:
            k = _cell_kind(c)
            votes[k] = votes.get(k, 0) + 1
        best = max(votes, key=votes.get, default="")
        kind.append(best if best and votes[best] * 2 > len(cells) else "")
    headers = [f"עמודה {i + 1}" for i in range(width)]
    taken: set[str] = set()

    def put(i: int, field: str) -> None:
        if field not in taken and headers[i].startswith("עמודה"):
            headers[i] = "טלפון" if field == "phone" else HEADER[field]
            taken.add(field)

    def vals(i: int) -> list[float]:
        return [float(c.replace(",", "")) for c in cols[i] if re.fullmatch(r"[\d,.]+", c)
                and c.replace(",", "").replace(".", "", 1).isdigit()]

    simple = {"phone": "phone", "date": "listed_on", "deal": "deal_type", "ptype": "property_type",
              "price": "asking_price", "city": "city", "address": "address"}
    for i, k in enumerate(kind):
        if k in simple:
            put(i, simple[k])
    nums = [i for i, k in enumerate(kind) if k == "num" and vals(i)]
    # an ad number: long whole numbers, all different (a price would be round and in ₪)
    for i in list(nums):
        v = vals(i)
        if all(x.is_integer() and x >= 100_000 for x in v) and len(set(v)) == len(v):
            if "asking_price" not in taken and sum(x % 1000 == 0 for x in v) * 2 > len(v):
                put(i, "asking_price")
            else:
                put(i, "listing_ref")
            nums.remove(i)
    # m²: the biggest small numbers; rooms: halves (3.5) or else the first; then floor, floors
    if len(nums) >= 2 or (nums and max(vals(nums[0])) > 12):
        area = max(nums, key=lambda i: sorted(vals(i))[len(vals(i)) // 2])
        if sorted(vals(area))[len(vals(area)) // 2] >= 25:
            put(area, "area_sqm")
            nums.remove(area)
    if nums:
        rooms = next((i for i in nums if any(x % 1 for x in vals(i)) and max(vals(i)) <= 15),
                     next((i for i in nums if max(vals(i)) <= 15), None))
        if rooms is not None:
            put(rooms, "rooms")
            nums.remove(rooms)
    for i, field in zip(nums, ("floor", "floors_total"), strict=False):
        put(i, field)
    # words: a value repeated across the list is the neighbourhood, the first other one the name
    texts = [i for i, k in enumerate(kind) if k == "text" and headers[i].startswith("עמודה")]
    for i in texts:
        if len(cols[i]) >= 3 and len(set(cols[i])) * 2 <= len(cols[i]):
            put(i, "neighborhood")
    for i in texts:
        if headers[i].startswith("עמודה"):
            put(i, "name")
    rest = [i for i in range(width) if headers[i].startswith("עמודה")
            and any(re.search(r"[^\W\d_]", c) for c in cols[i])]
    if rest:
        put(rest[-1], "notes")
    return headers


def _records(lines: list[str]) -> list[list[str]] | None:
    """Ads pasted one field per line: find the record length from the phone lines."""
    at = [i for i, ln in enumerate(lines) if PHONE_IN_TEXT.fullmatch(ln.replace(" ", ""))]
    if len(at) < 2 or len(at) * 3 > len(lines) + 2:
        return None
    gaps = {b - a for a, b in zip(at, at[1:], strict=False)}
    if len(gaps) != 1 or (size := gaps.pop()) < 4:
        return None
    best, best_score = None, -1
    for start in range(size):
        recs = [lines[j:j + size] for j in range(start, len(lines) - size + 1, size)]
        if len(recs) < 2:
            continue
        score = sum(max(sum(_cell_kind(r[p]) == k for r in recs) for k in {_cell_kind(r[p]) for r in recs})
                    for p in range(size))
        if score > best_score:
            best, best_score = recs, score
    return best


def _cell(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def guess_mapping(headers: list[str]) -> dict[str, int | None]:
    keys = [_key(h) for h in headers]
    mapping: dict[str, int | None] = {}
    for field, aliases in FIELDS.items():
        exact = next((i for i, k in enumerate(keys) if k in aliases), None)
        loose = next((i for i, k in enumerate(keys) if k and any(a in k for a in aliases
                                                                  if len(a) > 2)), None)
        idx = exact if exact is not None else loose
        mapping[field] = idx if idx not in mapping.values() else None
    return mapping


def _number(text: str) -> float | None:
    m = re.search(r"\d[\d,]*\.?\d*", text.replace("₪", ""))
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def valid_phone(phone: str) -> bool:
    """Israeli mobile (9725XXXXXXXX) or any international number of 10-15 digits."""
    d = normalize_phone(phone)
    if d.startswith("972"):
        return bool(re.fullmatch(r"9725\d{8}", d))
    return 10 <= len(d) <= 15


def prepare(headers: list[str], rows: list[list[str]], mapping: dict[str, int | None],
            store: Store) -> dict:
    """Map rows to contacts and report problems, without saving anything."""
    missing = [f for f in REQUIRED if mapping.get(f) is None]
    if missing:
        return {"ok": False, "missing": missing, "contacts": [], "issues": [], "checks": []}
    seen: set[str] = set()
    contacts, issues, checks = [], [], []
    for n, row in enumerate(rows, start=2):  # row 1 is the header line
        rec = {f: (row[i] if i is not None and i < len(row) else "") for f, i in mapping.items()}
        phone = normalize_phone(rec["phone"])
        problem = None
        if not rec["name"] and not phone:
            continue
        if not valid_phone(rec["phone"]):
            problem = "מספר טלפון לא תקין"
        elif phone in seen:
            problem = "כפול בקובץ"
        elif store.is_opted_out(phone):
            problem = "ביקש בעבר להסיר"
        if problem:
            issues.append({"row": n, "name": rec["name"], "phone": rec["phone"], "problem": problem})
            continue
        seen.add(phone)
        existing = store.one("SELECT status FROM sellers WHERE phone_norm=?", (phone,))
        c = {
            "seller_id": f"c{phone}", "name": rec["name"] or "", "phone": phone,
            "city": rec.get("city") or None, "address": rec.get("address") or None,
            "notes": rec.get("notes") or None,
            **{f: _number(rec.get(f) or "") for f in NUMERIC},
            "asking_price": details.price_of(rec.get("asking_price") or "")[0]
            or _number(rec.get("asking_price") or ""),
            **{f: (rec.get(f) or "").strip() or None
               for f in ("deal_type", "property_type", "neighborhood", "listing_ref")},
            "listed_on": _date(rec.get("listed_on") or ""),
            "existing_status": existing["status"] if existing else None,
        }
        for f in ("floor", "floors_total"):
            if c[f] is not None:
                c[f] = int(c[f])
        if c["listed_on"]:
            c["days_on_market"] = max(0, (date.today() - date.fromisoformat(c["listed_on"])).days)
        if check := _suspicious(c):
            checks.append({"row": n, "name": c["name"], "phone": rec["phone"], "problem": check})
        contacts.append(c)
    return {"ok": True, "missing": [], "contacts": contacts, "issues": issues, "checks": checks}


def _date(text: str) -> str | None:
    """"09/11/2026" (Israeli day first) or "2026-11-09" -> "2026-11-09"."""
    text = text.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text):
            return date.fromisoformat(text[:10]).isoformat()
        if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", text):
            d, mo, y = (int(x) for x in m.groups())
            return date(y + 2000 if y < 100 else y, mo, d).isoformat()
    except ValueError:
        pass
    return None


def _suspicious(c: dict) -> str | None:
    """Values that look like a typo in the ad. The client is still imported, only flagged."""
    price, area = c.get("asking_price"), c.get("area_sqm")
    sale = (c.get("deal_type") or "למכירה") in ("למכירה", "מכירה")
    if price and sale and price < 200_000:
        return f"מחיר {price:,.0f} ₪ נראה נמוך מדי למכירה"
    if area and area > 1000 and "מגרש" not in (c.get("property_type") or ""):
        return f"שטח {area:,.0f} מ\"ר נראה גדול מדי"
    rooms = c.get("rooms")
    if rooms and area and area / rooms < 8:
        return f"{rooms:g} חדרים ב-{area:g} מ\"ר לא מסתדר"
    return None


def save(contacts: list[dict], store: Store, source: str) -> dict:
    """Save prepared contacts. Existing contacts keep their status and conversation."""
    start = (store.one("SELECT MAX(rank) AS r FROM sellers")["r"] or 0) + 1
    rows = []
    for i, c in enumerate(contacts):
        row = {k: v for k, v in c.items() if k != "existing_status"}
        if row.get("area_sqm") is not None:
            row["area_sqm"] = int(row["area_sqm"])
        if row.get("asking_price") is not None:
            row["asking_price"] = int(row["asking_price"])
        old = store.seller(row["seller_id"])
        row["rank"] = old["rank"] if old and old["rank"] else start + i  # the list's own order
        rows.append(row)
    store.upsert_sellers(rows, status="new")
    new = sum(1 for c in contacts if not c["existing_status"])
    store.log(None, "contacts_imported", f"{source}: {len(contacts)} contacts, {new} new")
    return {"saved": len(contacts), "new": new, "updated": len(contacts) - new}
