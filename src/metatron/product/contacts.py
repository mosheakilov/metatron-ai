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

    rows, pending = [], ""
    for ln in lines:
        m = PHONE_IN_TEXT.search(ln)
        if not m:
            pending = f"{pending} {ln}".strip() if pending else ln
            continue
        before = ln[:m.start()].strip(" \t,;:-–|")
        after = ln[m.end():].strip(" \t,;:-–|")
        name = before or pending
        rows.append([name, m.group(), after])
        pending = ""
    if not rows:
        raise ValueError("לא נמצאו מספרי טלפון בטקסט")
    return ["שם", "טלפון", "הערות"], rows


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
    name_col = next((i for i in range(width) if i != phone_col and any(
        re.search(r"[^\W\d_]", r[i]) for r in table)), None)
    if name_col is not None:
        headers[name_col] = "שם"
    return headers, table


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
