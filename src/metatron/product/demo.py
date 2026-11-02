"""Fill a separate data folder with a realistic demo (no WhatsApp, no LLM needed).

    python -m metatron.product.demo --home var/demo-home
    set METATRON_HOME=var/demo-home && python -m metatron.product.launcher

The demo's phone numbers use the invalid 000 prefix, so nothing could reach a real person.
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from metatron.product import contacts
from metatron.product.gateway import handle_inbound
from metatron.product.outbox import Outbox
from metatron.product.server import Ctx
from metatron.product.settings import Settings

PEOPLE = [
    ("יעל כהן", "חיפה", "הנשיא 112", 4, 2_150_000), ("רון לוי", "חיפה", "מוריה 54", 3.5, 1_690_000),
    ("מיכל אברהם", "קריית ביאליק", "דרך עכו 23", 5, 2_480_000),
    ("אבי מזרחי", "נשר", "הדקלים 7", 4, 1_890_000), ("שירה פרץ", "חיפה", "חורב 18", 3, 1_420_000),
    ("דוד ביטון", "טירת כרמל", "הרצל 40", 4.5, 2_050_000),
    ("נועה דהן", "קריית מוצקין", "בן גוריון 9", 4, 1_980_000),
    ("יוסי אוחיון", "חיפה", "אבא חושי 101", 5, 2_900_000),
    ("תמר גבאי", "קריית אתא", "העצמאות 15", 3, 1_250_000),
    ("איתי שלום", "חיפה", "סטלה מאריס 6", 4, 2_650_000),
    ("רינה וקנין", "נשר", "גבעת עמוס 3", 4, 1_820_000),
    ("עומר חדד", "קריית ים", "ירושלים 12", 3.5, 1_390_000),
]


class _DemoGateway:
    def status(self):
        return {"status": "disconnected", "qr": None, "pairingCode": None, "me": None, "error": None}

    def connected(self):
        return True

    def send(self, phone, text, typing_ms=0, image=None):
        return f"demo-{random.randrange(10**9)}"


def seed(home: Path) -> None:
    os.environ["METATRON_HOME"] = str(home)
    os.environ.setdefault("METATRON_LLM_MODE", "offline")
    settings = Settings(home)
    settings.update({"setup_done": True, "broker_name": "דנה לוי", "office_name": 'לוי נדל"ן'})
    ctx = Ctx(settings, _DemoGateway())
    ctx.outbox = Outbox(ctx.store, settings, ctx.gateway, rng=random.Random(4))
    rows = [["שם", "טלפון", "עיר", "כתובת", "חדרים", "מחיר"]] + [
        [n, f"050-000{i:04d}", c, a, r, p] for i, (n, c, a, r, p) in enumerate(PEOPLE)]
    prep = contacts.prepare(rows[0], [[str(x) for x in r] for r in rows[1:]],
                            contacts.guess_mapping(rows[0]), ctx.store)
    contacts.save(prep["contacts"], ctx.store, "demo.xlsx")
    ids = [c["seller_id"] for c in prep["contacts"]]

    settings.update({"limits": {"daily_new": 50, "min_gap_sec": 1, "max_gap_sec": 1,
                                "send_on_weekend": True, "start_hour": 0, "end_hour": 24}})
    work = datetime.now().replace(hour=11, minute=0)
    for sid in ids[:7]:
        ctx.event(event="draft", seller_id=sid)
    for d in ctx.store.pending_drafts():
        ctx.event(event="approve", message_id=d["message_id"])
    for i in range(20):
        ctx.outbox.send_one(work + timedelta(minutes=5 * i))

    def reply(sid: str, text: str) -> None:
        handle_inbound(ctx.store, ctx.cfg, {"id": f"in-{sid}-{text}", "phone": sid[1:], "text": text})
        for _ in range(3):
            ctx.outbox.send_one(work + timedelta(hours=3))

    reply(ids[0], "היי, כן מעוניינת לשמוע")
    reply(ids[0], "2")
    reply(ids[1], "כמה אתם לוקחים עמלה?")
    reply(ids[2], "כן, בשמחה")
    reply(ids[3], "תורידו אותי בבקשה")
    reply(ids[4], "לא תודה, כבר מכרנו")
    for sid in ids[7:10]:
        ctx.event(event="draft", seller_id=sid)
    settings.update({"limits": {"daily_new": 15, "min_gap_sec": 90, "max_gap_sec": 240,
                                "send_on_weekend": False, "start_hour": 9, "end_hour": 19}})
    print(f"demo ready in {home}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default="var/demo-home")
    a = ap.parse_args()
    seed(Path(a.home).resolve())
