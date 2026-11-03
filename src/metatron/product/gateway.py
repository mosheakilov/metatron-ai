"""Client for the local WhatsApp gateway (gateway/index.js) and handling of incoming messages."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from metatron.config import Config
from metatron.flows.outreach_flow import run_event
from metatron.outreach import replies
from metatron.outreach.store import Store

log = logging.getLogger("metatron.gateway")


class GatewayClient:
    def __init__(self, port: int, token: str, client: httpx.Client | None = None):
        self.base = f"http://127.0.0.1:{port}"
        self.client = client or httpx.Client(timeout=30, headers={"x-gateway-token": token})

    def status(self) -> dict:
        try:
            return self.client.get(f"{self.base}/status", timeout=3).json()
        except httpx.HTTPError:
            return {"status": "offline", "qr": None, "pairingCode": None, "me": None,
                    "error": "gateway not running"}

    def connected(self) -> bool:
        return self.status().get("status") == "open"

    def connect(self, mode: str, phone: str | None = None) -> dict:
        r = self.client.post(f"{self.base}/connect", json={"mode": mode, "phone": phone})
        if r.status_code >= 400:
            raise ValueError(r.json().get("error", r.text))
        return r.json()

    def logout(self) -> dict:
        return self.client.post(f"{self.base}/logout").json()

    def send(self, phone: str, text: str, typing_ms: int = 0, image: str | None = None) -> str | None:
        """Send text, or a picture with the text as its caption (image = a local file path)."""
        r = self.client.post(f"{self.base}/send", json={"to": phone, "text": text, "image": image,
                                                        "typing_ms": typing_ms}, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError(r.json().get("error", r.text))
        return r.json().get("id")


def cancel_pending_outreach(store: Store, seller_id: str) -> int:
    """The broker already talks to this seller, so the opening message waiting to go out (or
    waiting for approval) would arrive out of order: cancel it."""
    pending = store.q("SELECT id FROM messages WHERE seller_id=? AND kind='outreach' AND "
                      "status IN ('queued', 'draft')", (seller_id,))
    for m in pending:
        store.update_message(m["id"], status="cancelled", note="השיחה כבר התחילה")
    return len(pending)


ACTIVE = ("sent", "in_conversation", "slots_offered", "awaiting_approval", "booked",
          "not_interested", "broker_took_over")


def handle_inbound(store: Store, cfg: Config, msg: dict) -> str:
    """Route one message from the broker's WhatsApp. Returns what was done (for logs/tests).

    The broker's own WhatsApp also carries family and work chats, so only sellers that METATRON
    has already contacted are touched; any other message is dropped without being stored.
    """
    phone, text, ext = msg.get("phone", ""), (msg.get("text") or "").strip(), msg.get("id")
    if ext and store.one("SELECT 1 FROM messages WHERE external_id=?", (ext,)):
        return "duplicate"
    ts = msg.get("ts") or 0
    if ts and datetime.fromtimestamp(ts) < datetime.now() - timedelta(days=3):
        return "too_old"
    seller = store.seller_by_phone(phone)
    if not seller or seller["status"] not in ACTIVE + ("opted_out",):
        return "ignored"
    sid = seller["seller_id"]

    if msg.get("from_me"):
        echo = store.one("SELECT id FROM messages WHERE seller_id=? AND direction='out' AND body=? "
                         "AND COALESCE(sent_at, created_at) >= ?", (sid, text,
                                                 (datetime.now() - timedelta(minutes=30))
                                                 .isoformat(timespec="seconds")))
        if echo:  # a message METATRON itself sent
            return "duplicate"
        # The broker typed in WhatsApp themself: show it, and stop automatic replies for them.
        store.add_message(sid, "out", "manual", text, "sent", channel="wa_web", external_id=ext,
                          note="sent from the phone")
        cancel_pending_outreach(store, sid)
        if seller["status"] not in ("opted_out", "booked"):
            store.set_status(sid, "broker_took_over")
        return "manual"

    if seller["status"] == "opted_out":
        store.add_message(sid, "in", "reply", text, "received", external_id=ext)
        return "stored"
    if seller["status"] == "broker_took_over" and not replies.is_opt_out(text):
        store.add_message(sid, "in", "reply", text, "received", external_id=ext)
        return "stored"
    state = run_event(store, cfg, event="reply", seller_id=sid, text=text, external_id=ext)
    return state.label or state.result
