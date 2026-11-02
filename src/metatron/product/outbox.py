"""The outbox: approved messages wait here and go out one at a time, at a human pace.

Two lanes:
- conversation messages (answers, meeting slots, booking, opt-out confirmation) go first, after
  a short "typing" pause;
- first messages to new sellers go only inside working hours, with a random gap between them
  and a daily cap. This is what keeps a linked WhatsApp device from looking like a bulk sender.

An opted-out number is checked again right before sending: if the seller wrote "הסר" while a
message was waiting, it is never sent. The single opt-out confirmation is the only exception.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from metatron.outreach.store import Store, now
from metatron.product.settings import Settings

log = logging.getLogger("metatron.outbox")


@dataclass
class Decision:
    message: dict | None
    wait_reason: str | None = None
    next_at: str | None = None


class Outbox:
    def __init__(self, store: Store, settings: Settings, gateway, rng: random.Random | None = None):
        self.store, self.settings, self.gateway = store, settings, gateway
        self.rng = rng or random.Random()
        last = store.one("SELECT MAX(sent_at) AS t FROM messages WHERE kind='outreach' AND status='sent'")
        # after a restart, keep the gap from the last first message instead of sending at once
        self.next_first_at: datetime | None = (
            datetime.fromisoformat(last["t"]) + timedelta(seconds=settings.data["limits"]["min_gap_sec"])
            if last and last["t"] else None)
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---- policy -------------------------------------------------------------------------
    def sent_today(self, at: datetime) -> int:
        row = self.store.one("SELECT COUNT(*) AS n FROM messages WHERE kind='outreach' AND "
                             "status='sent' AND substr(sent_at, 1, 10)=?", (f"{at:%Y-%m-%d}",))
        return row["n"]

    def queued(self) -> list[dict]:
        return self.store.q(
            "SELECT m.*, s.name, s.phone FROM messages m JOIN sellers s USING(seller_id) "
            "WHERE m.status='queued' ORDER BY CASE WHEN m.kind='outreach' THEN 1 ELSE 0 END, m.id")

    def in_hours(self, at: datetime) -> bool:
        lim = self.settings.data["limits"]
        weekend = at.weekday() in (4, 5)  # Friday, Saturday
        return lim["start_hour"] <= at.hour < lim["end_hour"] and (lim["send_on_weekend"]
                                                                    or not weekend)

    def decide(self, at: datetime | None = None) -> Decision:
        """Which message to send now, or why nothing is sent."""
        at = at or datetime.now()
        queue = self.queued()
        if not queue:
            return Decision(None, "empty")
        if self.settings.data["paused"]:
            return Decision(None, "paused")
        convo = [m for m in queue if m["kind"] != "outreach"]
        if convo:
            return Decision(convo[0])
        lim = self.settings.data["limits"]
        if self.sent_today(at) >= lim["daily_new"]:
            return Decision(None, "daily_cap", self._next_window(at + timedelta(days=1), True))
        if not self.in_hours(at):
            return Decision(None, "outside_hours", self._next_window(at))
        if self.next_first_at and at < self.next_first_at:
            return Decision(None, "pacing", self.next_first_at.isoformat(timespec="seconds"))
        return Decision(queue[0])

    def _next_window(self, at: datetime, day_start: bool = False) -> str:
        lim = self.settings.data["limits"]
        t = at.replace(hour=lim["start_hour"], minute=0, second=0, microsecond=0) if day_start else at
        for _ in range(8 * 24):
            if self.in_hours(t):
                return t.isoformat(timespec="seconds")
            t = (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        return t.isoformat(timespec="seconds")

    # ---- delivery -----------------------------------------------------------------------
    def send_one(self, at: datetime | None = None) -> dict | None:
        """Send the next due message. Returns the message row (with its new status) or None."""
        with self._lock:
            at = at or datetime.now()
            msg = self.decide(at).message
            if not msg:
                return None
            if msg["kind"] != "optout_confirm" and self.store.is_opted_out(msg["phone"]):
                self.store.update_message(msg["id"], status="blocked", note="seller opted out")
                return {**msg, "status": "blocked"}
            typing = min(12000, 1500 + 45 * len(msg["body"])) if msg["kind"] != "outreach" else 4000
            try:
                ext = self.gateway.send(msg["phone"], msg["body"], typing_ms=typing)
                status, note = "sent", msg["note"]
            except Exception as e:  # stays visible in the dashboard; the broker can retry
                ext, status, note = None, "failed", str(e)[:300]
            self.store.update_message(msg["id"], status=status, external_id=ext, note=note,
                                      sent_at=now() if status == "sent" else None)
            if msg["kind"] == "outreach" and status == "sent":
                lim = self.settings.data["limits"]
                gap = self.rng.randint(lim["min_gap_sec"], max(lim["min_gap_sec"], lim["max_gap_sec"]))
                self.next_first_at = at + timedelta(seconds=gap)
            if status == "failed":
                self.store.log(msg["seller_id"], "send_failed", note or "")
            return {**msg, "status": status, "external_id": ext}

    def retry(self, message_id: int) -> None:
        msg = self.store.message(message_id)
        if msg and msg["status"] == "failed":
            self.store.update_message(message_id, status="queued", note="retry")

    def status(self) -> dict:
        d = self.decide()
        lim = self.settings.data["limits"]
        return {"queued": len(self.queued()), "sent_today": self.sent_today(datetime.now()),
                "daily_cap": lim["daily_new"], "paused": self.settings.data["paused"],
                "waiting": d.wait_reason, "next_at": d.next_at}

    # ---- background loop ----------------------------------------------------------------
    def run_forever(self, interval: float = 3.0) -> None:
        while not self._stop.is_set():
            try:
                if self.gateway.connected():
                    self.send_one()
            except Exception:
                log.exception("outbox tick failed")
            self._stop.wait(interval)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name="outbox", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
