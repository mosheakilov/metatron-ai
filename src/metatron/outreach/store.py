"""SQLite store for the outreach side: sellers, messages, opt-outs, meetings and outcomes."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    seller_id TEXT PRIMARY KEY,
    name TEXT, phone TEXT, city TEXT, address TEXT,
    rooms REAL, area_sqm INTEGER, asking_price INTEGER,
    days_on_market INTEGER, price_drops INTEGER,
    score REAL, rank INTEGER, model_version TEXT, run_id TEXT,
    status TEXT NOT NULL DEFAULT 'scored',
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT NOT NULL,
    direction TEXT NOT NULL,          -- out | in
    kind TEXT NOT NULL,               -- outreach | answer | optout_confirm | slots | booking | reply
    body TEXT NOT NULL,
    status TEXT NOT NULL,             -- draft | approved | rejected | sent | blocked | received
    channel TEXT, external_id TEXT, note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opt_outs (
    phone TEXT PRIMARY KEY,
    seller_id TEXT, text TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    address TEXT, external_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
    seller_id TEXT PRIMARY KEY,
    agreed_to_meeting INTEGER NOT NULL, reason TEXT, decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT, event TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
"""


# details of the seller's listing (ad lists from Yad2 and the like)
LISTING_COLUMNS = [("property_type", "TEXT"), ("floor", "INTEGER"), ("floors_total", "INTEGER"),
                   ("neighborhood", "TEXT"), ("deal_type", "TEXT"), ("listing_ref", "TEXT"),
                   ("listed_on", "TEXT")]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_phone(phone: str) -> str:
    """Keep digits only, Israeli local 05x -> 9725x, so opt-out matching is format-proof."""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    return digits


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()  # the product's API threads and outbox share one connection
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Columns added after the first release; old databases get them in place."""
        for table, col, ddl in [("sellers", "phone_norm", "TEXT"), ("sellers", "notes", "TEXT"),
                                ("messages", "sent_at", "TEXT"), ("messages", "media", "TEXT"),
                                *(("sellers", c, t) for c, t in LISTING_COLUMNS)]:
            if col not in {r["name"] for r in self.q(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        for r in self.q("SELECT seller_id, phone FROM sellers WHERE phone_norm IS NULL"):
            self.db.execute("UPDATE sellers SET phone_norm=? WHERE seller_id=?",
                            (normalize_phone(r["phone"]), r["seller_id"]))
        self.db.execute("UPDATE sellers SET deal_type = CASE WHEN deal_type LIKE '%השכר%' "
                        "OR deal_type='rent' THEN 'rent' ELSE 'sale' END "
                        "WHERE deal_type IS NULL OR deal_type NOT IN ('sale', 'rent')")
        self.db.execute("CREATE INDEX IF NOT EXISTS sellers_phone ON sellers(phone_norm)")
        self.db.commit()

    # ---- generic ---------------------------------------------------------------------
    def q(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

    def one(self, sql: str, args: Iterable[Any] = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self.lock:
            cur = self.db.execute(sql, tuple(args))
            self.db.commit()
            return cur.lastrowid

    def log(self, seller_id: str | None, event: str, detail: str = "") -> None:
        self.x("INSERT INTO events(seller_id, event, detail, created_at) VALUES (?,?,?,?)",
               (seller_id, event, detail, now()))

    # ---- sellers ---------------------------------------------------------------------
    def upsert_sellers(self, rows: list[dict], status: str = "scored") -> None:
        """Insert or refresh sellers. The status of an existing seller is never reset."""
        cols = ["seller_id", "name", "phone", "city", "address", "rooms", "area_sqm",
                "asking_price", "days_on_market", "price_drops", "score", "rank",
                "model_version", "run_id", "notes", "phone_norm", *(c for c, _ in LISTING_COLUMNS)]
        sql = (f"INSERT INTO sellers({','.join(cols)}, status, updated_at) "
               f"VALUES ({','.join('?' * len(cols))}, ?, ?) "
               "ON CONFLICT(seller_id) DO UPDATE SET "
               + ", ".join(f"{c}=excluded.{c}" for c in cols[1:]) + ", updated_at=excluded.updated_at")
        rows = [{**r, "phone_norm": normalize_phone(r.get("phone") or ""),
                 "deal_type": r.get("deal_type") or "sale"} for r in rows]
        with self.lock:
            self.db.executemany(sql, [tuple(r.get(c) for c in cols) + (status, now()) for r in rows])
            self.db.commit()

    def seller(self, seller_id: str) -> dict | None:
        return self.one("SELECT * FROM sellers WHERE seller_id=?", (seller_id,))

    def delete_seller(self, seller_id: str) -> bool:
        """Remove a client with their conversation, meetings and outcome. The opt-out list is
        kept on purpose: a number that asked to be removed stays blocked even if re-imported."""
        if not self.seller(seller_id):
            return False
        with self.lock:
            for table in ("messages", "meetings", "outcomes", "sellers"):
                self.db.execute(f"DELETE FROM {table} WHERE seller_id=?", (seller_id,))
            self.db.commit()
        self.log(None, "contact_deleted", seller_id)
        return True

    def seller_by_phone(self, phone: str) -> dict | None:
        """A seller we have contacted (not one that was only scored or imported)."""
        return self.one("SELECT * FROM sellers WHERE phone_norm=? AND status NOT IN ('scored', 'new')"
                        " ORDER BY updated_at DESC LIMIT 1", (normalize_phone(phone),))

    def set_status(self, seller_id: str, status: str) -> None:
        self.x("UPDATE sellers SET status=?, updated_at=? WHERE seller_id=?",
               (status, now(), seller_id))
        self.log(seller_id, "status", status)

    def set_phone(self, seller_id: str, phone: str) -> None:
        self.x("UPDATE sellers SET phone=?, phone_norm=?, updated_at=? WHERE seller_id=?",
               (phone, normalize_phone(phone), now(), seller_id))

    def sellers(self, status: str | None = None, limit: int = 500) -> list[dict]:
        if status:
            return self.q("SELECT * FROM sellers WHERE status=? ORDER BY rank LIMIT ?",
                          (status, limit))
        return self.q("SELECT * FROM sellers ORDER BY rank LIMIT ?", (limit,))

    # ---- messages --------------------------------------------------------------------
    def add_message(self, seller_id: str, direction: str, kind: str, body: str, status: str,
                    channel: str | None = None, external_id: str | None = None,
                    note: str | None = None) -> int:
        return self.x(
            "INSERT INTO messages(seller_id, direction, kind, body, status, channel, external_id,"
            " note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (seller_id, direction, kind, body, status, channel, external_id, note, now()))

    def message(self, message_id: int) -> dict | None:
        return self.one("SELECT * FROM messages WHERE id=?", (message_id,))

    def update_message(self, message_id: int, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE messages SET {sets} WHERE id=?", (*fields.values(), message_id))

    def messages(self, seller_id: str) -> list[dict]:
        return self.q("SELECT * FROM messages WHERE seller_id=? ORDER BY id", (seller_id,))

    def pending_drafts(self) -> list[dict]:
        return self.q(
            "SELECT m.id AS message_id, m.kind, m.body, m.media, s.* FROM messages m "
            "JOIN sellers s USING(seller_id) WHERE m.status='draft' ORDER BY s.rank, m.id")

    # ---- opt-out ---------------------------------------------------------------------
    def opt_out(self, phone: str, seller_id: str | None, text: str) -> None:
        self.x("INSERT OR IGNORE INTO opt_outs(phone, seller_id, text, created_at) "
               "VALUES (?,?,?,?)", (normalize_phone(phone), seller_id, text, now()))

    def is_opted_out(self, phone: str) -> bool:
        return self.one("SELECT 1 FROM opt_outs WHERE phone=?", (normalize_phone(phone),)) is not None

    def opt_outs(self) -> list[dict]:
        return self.q("SELECT * FROM opt_outs ORDER BY created_at DESC")

    # ---- meetings / outcomes ---------------------------------------------------------
    def add_meeting(self, seller_id: str, start: str, end: str, address: str) -> int:
        return self.x("INSERT INTO meetings(seller_id, start, end, address, created_at) "
                      "VALUES (?,?,?,?,?)", (seller_id, start, end, address, now()))

    def meetings(self) -> list[dict]:
        return self.q("SELECT m.*, s.name, s.phone, s.city FROM meetings m "
                      "JOIN sellers s USING(seller_id) ORDER BY m.start")

    def booked_starts(self) -> set[str]:
        return {r["start"] for r in self.q("SELECT start FROM meetings")}

    def log_outcome(self, seller_id: str, agreed: bool, reason: str) -> None:
        self.x("INSERT INTO outcomes(seller_id, agreed_to_meeting, reason, decided_at) "
               "VALUES (?,?,?,?) ON CONFLICT(seller_id) DO UPDATE SET "
               "agreed_to_meeting=excluded.agreed_to_meeting, reason=excluded.reason, "
               "decided_at=excluded.decided_at", (seller_id, int(agreed), reason, now()))

    def outcomes(self) -> list[dict]:
        return self.q("SELECT * FROM outcomes ORDER BY decided_at")
