"""Message channels: a simulator and the WhatsApp Cloud API.

Safety rules enforced here, for every channel:
- an opted-out number is never sent anything (checked by the caller AND here);
- the WhatsApp channel sends only to `outreach.allowed_numbers` (own numbers during the course).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from metatron.config import Config
from metatron.outreach.store import Store, normalize_phone

GRAPH = "https://graph.facebook.com/v21.0"


@dataclass
class SendResult:
    status: str                 # sent | blocked | failed
    external_id: str | None = None
    note: str | None = None


class SimulationChannel:
    name = "simulation"

    def __init__(self, cfg: Config, store: Store):
        self.cfg, self.store = cfg, store

    def send(self, phone: str, body: str, first_contact: bool = False,
             seller: dict | None = None) -> SendResult:
        if self.store.is_opted_out(phone):
            return SendResult("blocked", note="opted out")
        return SendResult("sent", external_id=f"sim-{datetime.now():%H%M%S%f}")


class WhatsAppChannel:
    """WhatsApp Cloud API. First contact outside the 24h window uses the approved template."""

    name = "whatsapp"

    def __init__(self, cfg: Config, store: Store, client: httpx.Client | None = None):
        self.cfg, self.store = cfg, store
        self.token = os.getenv("WA_TOKEN", "")
        self.phone_id = os.getenv("WA_PHONE_NUMBER_ID", "")
        self.allowed = {normalize_phone(p) for p in cfg["outreach"]["allowed_numbers"]}
        self.client = client or httpx.Client(timeout=15)

    def window_open(self, seller_id: str | None) -> bool:
        """True if the seller wrote to us in the last 24 hours (free-text messages allowed)."""
        if not seller_id:
            return False
        last_in = self.store.one(
            "SELECT created_at FROM messages WHERE seller_id=? AND direction='in' "
            "ORDER BY id DESC LIMIT 1", (seller_id,))
        return bool(last_in) and (
            datetime.now() - datetime.fromisoformat(last_in["created_at"]) < timedelta(hours=24))

    def _payload(self, to: str, body: str, use_template: bool, seller: dict | None) -> dict:
        if not use_template:
            return {"messaging_product": "whatsapp", "to": to, "type": "text",
                    "text": {"body": body, "preview_url": False}}
        o = self.cfg["outreach"]
        s = seller or {}
        params = [(s.get("name") or "").split(" ")[0] or "שלום",
                  f"{s.get('address', '')}, {s.get('city', '')}",
                  o.get("broker_name") or o["office_name"]]
        return {"messaging_product": "whatsapp", "to": to, "type": "template",
                "template": {"name": o["template_name"],
                             "language": {"code": o["template_language"]},
                             "components": [{"type": "body", "parameters": [
                                 {"type": "text", "text": p} for p in params]}]}}

    def send(self, phone: str, body: str, first_contact: bool = False,
             seller: dict | None = None) -> SendResult:
        to = normalize_phone(phone)
        if self.store.is_opted_out(phone):
            return SendResult("blocked", note="opted out")
        if to not in self.allowed:
            return SendResult("blocked", note="number not in outreach.allowed_numbers")
        if not (self.token and self.phone_id):
            return SendResult("failed", note="WA_TOKEN / WA_PHONE_NUMBER_ID not set")
        sid = (seller or {}).get("seller_id")
        use_template = first_contact and not self.window_open(sid)
        try:
            r = self.client.post(f"{GRAPH}/{self.phone_id}/messages",
                                 headers={"Authorization": f"Bearer {self.token}"},
                                 json=self._payload(to, body, use_template, seller))
            r.raise_for_status()
            wa_id = r.json()["messages"][0]["id"]
            return SendResult("sent", external_id=wa_id,
                              note="template" if use_template else "text")
        except Exception as e:  # network / API error: keep the message, show it in the UI
            return SendResult("failed", note=str(e)[:300])


class QueueChannel:
    """Product channel (linked WhatsApp device): messages wait in the outbox, which sends them
    with human pacing and daily limits (metatron.product.outbox)."""

    name = "wa_web"

    def __init__(self, cfg: Config, store: Store):
        self.cfg, self.store = cfg, store

    def send(self, phone: str, body: str, first_contact: bool = False,
             seller: dict | None = None) -> SendResult:
        if self.store.is_opted_out(phone):
            return SendResult("blocked", note="opted out")
        if not normalize_phone(phone):
            return SendResult("failed", note="no phone number")
        return SendResult("queued")


def get_channel(cfg: Config, store: Store):
    channel = cfg["outreach"]["channel"]
    if channel == "whatsapp":
        return WhatsAppChannel(cfg, store)
    if channel == "wa_web":
        return QueueChannel(cfg, store)
    return SimulationChannel(cfg, store)
