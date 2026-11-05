"""Import the broker's client list (Excel or CSV) into the seller table.

Brokers export lists from many places (Yad2 notes, Excel they keep by hand, nadlan-pro,
phone contacts), so columns are matched by name in Hebrew or English and the broker can fix
the mapping in the dashboard before anything is saved. Nothing is sent on import.
"""

from __future__ import annotations

import csv
import io
import re
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
}
REQUIRED = ("name", "phone")
NUMERIC = ("rooms", "area_sqm", "asking_price")


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

    keys = ("city", "address", "rooms", "area_sqm", "asking_price", "notes")
    rows: list[dict] = []
    pending = ""
    for ln in lines:
        m = PHONE_IN_TEXT.search(ln)
        if not m:
            d = details.parse(ln)
            if rows and not pending and details.found_any(d):
                _merge(rows[-1], d)  # a details line under the client's phone line
            else:
                pending = f"{pending} {ln}".strip() if pending else ln
            continue
        before = ln[:m.start()].strip(" \t,;:-–|")
        after = ln[m.end():].strip(" \t,;:-–|")
        name, _, extra = before.partition(",")  # "יעל כהן, חיפה 050-..." -> name, details
        row = {"name": name.strip() or pending, "phone": m.group()}
        row.update(details.parse(", ".join(x for x in (extra.strip(), after) if x)))
        rows.append(row)
        pending = ""
    if not rows:
        raise ValueError("לא נמצאו מספרי טלפון בטקסט")
    return (["שם", "טלפון", "עיר", "כתובת", "חדרים", "שטח", "מחיר", "הערות"],
            [[r["name"], r["phone"], *(r[k] for k in keys)] for r in rows])


def _merge(row: dict, d: dict) -> None:
    for k, v in d.items():
        if not v:
            continue
        if k == "notes":
            row[k] = ", ".join(x for x in (row[k], v) if x)
        elif not row[k]:
            row[k] = v


def _has_header(cells: list[str]) -> bool:
    m = guess_mapping(cells)
    return m["name"] is not None and m["phone"] is not None and not any(
        PHONE_IN_TEXT.search(c) for c in cells)


def _table(table: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    width = max(len(r) for r in table)
    table = [[c.strip() for c in r] + [""] * (width - len(r)) for r in table]
    if _has_header(table[0]):
        return table[0], table[1:]
    # no header row: name the columns by what they hold, the broker can fix it on screen
    def phones(i):
        return sum(bool(PHONE_IN_TEXT.fullmatch(r[i].replace(" ", ""))) for r in table)
    phone_col = max(range(width), key=phones)
    headers = [f"עמודה {i + 1}" for i in range(width)]
    headers[phone_col] = "טלפון"
    kinds = {i: _column_kind([r[i] for r in table if r[i]]) for i in range(width) if i != phone_col}
    name_col = next((i for i in range(width) if i != phone_col and not kinds[i] and any(
        re.search(r"[^\W\d_]", r[i]) for r in table)), None)
    if name_col is not None:
        headers[name_col] = "שם"
    label = {"city": "עיר", "address": "כתובת", "rooms": "חדרים", "area_sqm": "שטח",
             "asking_price": "מחיר"}
    used = set()
    for i, kind in kinds.items():
        if kind and kind not in used and i != name_col:
            headers[i] = label[kind]
            used.add(kind)
    rest = [i for i in range(width) if headers[i].startswith("עמודה")
            and any(re.search(r"[^\W\d_]", r[i]) for r in table)]
    if rest:
        headers[rest[-1]] = "הערות"
    return headers, table


def _column_kind(cells: list[str]) -> str | None:
    """What a column without a header holds, judged by most of its cells."""
    if not cells:
        return None
    votes: dict[str, int] = {}
    for c in cells:
        kind = None
        if details.city_of(c):
            kind = "city"
        elif re.fullmatch(r"[\d,.\s₪]+", c):
            v = _number(c) or 0
            kind = "rooms" if 0 < v <= 12 else "area_sqm" if 15 <= v <= 2000 else (
                "asking_price" if v >= 50_000 else None)
        else:
            d = details.parse(c)
            kind = next((k for k in ("address", "rooms", "area_sqm", "asking_price")
                         if d[k] and not d["notes"]), None)
        if kind:
            votes[kind] = votes.get(kind, 0) + 1
    best = max(votes, key=votes.get, default=None)
    return best if best and votes[best] * 2 > len(cells) else None


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
        return {"ok": False, "missing": missing, "contacts": [], "issues": []}
    seen: set[str] = set()
    contacts, issues = [], []
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
        contacts.append({
            "seller_id": f"c{phone}", "name": rec["name"] or "", "phone": phone,
            "city": rec.get("city") or None, "address": rec.get("address") or None,
            "notes": rec.get("notes") or None,
            **{f: _number(rec.get(f) or "") for f in NUMERIC},
            "asking_price": details.price_of(rec.get("asking_price") or "")[0]
            or _number(rec.get("asking_price") or ""),
            "existing_status": existing["status"] if existing else None,
        })
    return {"ok": True, "missing": [], "contacts": contacts, "issues": issues}


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
