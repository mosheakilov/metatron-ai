"""OutreachFlow: one event per run, for one seller.

The broker's approval is a human step, so the flow does not block on it. Every action
(Streamlit button or WhatsApp webhook) starts the flow with an event, and the router sends it
down the matching branch:

    "draft"     ──► draft_message ──► (approval queue)
    "approve"   ──► send_approved ──► sent
    "reject"    ──► reject_draft
    "reply"     ──► handle_reply ──┬─ "opt_out"        ──► opt_out ──► END (number blocked forever)
                                   ├─ "not_interested" ──► close_lost ──► log_outcome(0)
                                   ├─ "question"       ──► draft_answer ──► (approval queue)
                                   ├─ "interested"     ──► propose_slots
                                   └─ "slot_chosen"    ──► book_meeting ──► log_outcome(1)
"""

from __future__ import annotations

import json
from datetime import datetime

from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, Field

from metatron.channels import calendar
from metatron.channels.whatsapp import get_channel
from metatron.config import Config, load_config
from metatron.llm import get_llm, use_llm
from metatron.outreach import drafting, replies, scheduling
from metatron.outreach.store import Store


class OutreachState(BaseModel):
    event: str = ""                  # draft | approve | reject | reply
    seller_id: str = ""
    message_id: int | None = None    # for approve / reject
    edited_body: str | None = None   # broker's edit before approving
    text: str = ""                   # inbound reply text
    external_id: str | None = None   # inbound WhatsApp message id (dedupe)
    result: str = ""                 # what happened, for the UI / tests
    label: str | None = None


class OutreachFlow(Flow[OutreachState]):
    cfg: Config = Field(default_factory=load_config, exclude=True)
    store: Store | None = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}
    # Each run is one event; state lives in SQLite, so CrewAI's vector memory is not needed.
    _skip_auto_memory: bool = True

    def _llm(self, tier: str):
        return get_llm(self.cfg, tier) if use_llm(self.cfg) else None

    def _seller(self) -> dict:
        s = self.store.seller(self.state.seller_id)
        if not s:
            raise ValueError(f"unknown seller {self.state.seller_id}")
        return s

    def _send(self, seller: dict, kind: str, body: str, first_contact: bool = False) -> str:
        """Send now (only for system messages that follow an approved conversation)."""
        res = get_channel(self.cfg, self.store).send(seller["phone"], body, first_contact, seller)
        self.store.add_message(seller["seller_id"], "out", kind, body, res.status,
                               channel=self.cfg["outreach"]["channel"],
                               external_id=res.external_id, note=res.note)
        return res.status

    @start()
    def route_event(self):
        return self.state.event

    @router(route_event)
    def dispatch(self):
        return self.state.event

    # ---- first message -----------------------------------------------------------------
    @listen("draft")
    def draft_message(self):
        seller = self._seller()
        if self.store.is_opted_out(seller["phone"]):
            self.store.set_status(seller["seller_id"], "opted_out")
            self.state.result = "blocked: opted out"
            return
        body = drafting.draft_outreach(seller, self.cfg, self._llm("smart"))
        self.state.message_id = self.store.add_message(seller["seller_id"], "out", "outreach",
                                                       body, "draft")
        self.store.set_status(seller["seller_id"], "awaiting_approval")
        self.state.result = "drafted"

    # ---- broker decisions --------------------------------------------------------------
    @listen("approve")
    def send_approved(self):
        msg = self.store.message(self.state.message_id)
        if not msg or msg["status"] != "draft":
            self.state.result = "not a pending draft"
            return
        seller = self.store.seller(msg["seller_id"])
        body = self.state.edited_body.strip() if self.state.edited_body else msg["body"]
        if msg["kind"] in ("outreach", "answer"):
            # with the opt-out line on, an edit cannot remove it; the broker can turn it off in settings
            body = drafting._ensure_opt_out(body, self.cfg)
        res = get_channel(self.cfg, self.store).send(seller["phone"], body,
                                                     msg["kind"] == "outreach", seller)
        self.store.update_message(msg["id"], body=body, status=res.status,
                                  channel=self.cfg["outreach"]["channel"],
                                  external_id=res.external_id,
                                  note=("edited by broker; " if self.state.edited_body else "")
                                  + (res.note or ""))
        if res.status in ("sent", "queued"):  # queued: the product's outbox sends it soon
            self.store.set_status(seller["seller_id"], "sent" if msg["kind"] == "outreach"
                                  else "in_conversation")
        elif res.status == "blocked" and res.note == "opted out":
            self.store.set_status(seller["seller_id"], "opted_out")
        self.state.result = res.status

    @listen("reject")
    def reject_draft(self):
        msg = self.store.message(self.state.message_id)
        if msg and msg["status"] == "draft":
            self.store.update_message(msg["id"], status="rejected")
            self.store.set_status(msg["seller_id"], "rejected")
        self.state.result = "rejected"

    # ---- inbound reply -----------------------------------------------------------------
    @listen("reply")
    def store_reply(self):
        seller = self._seller()
        self.store.add_message(seller["seller_id"], "in", "reply", self.state.text, "received",
                               external_id=self.state.external_id)

    @router(store_reply)
    def handle_reply(self):
        seller = self._seller()
        text = self.state.text
        if replies.is_opt_out(text):            # always first, never via the LLM
            label = replies.OPT_OUT
        elif seller["status"] == "slots_offered" and self._chosen_slot() is not None:
            label = "slot_chosen"
        else:
            label = replies.classify(text, self._llm("fast"))
        self.state.label = label
        return label

    def _offered(self) -> list[str]:
        ev = self.store.one("SELECT detail FROM events WHERE seller_id=? AND event='slots_offered'"
                            " ORDER BY id DESC LIMIT 1", (self.state.seller_id,))
        return json.loads(ev["detail"]) if ev else []

    def _chosen_slot(self) -> int | None:
        return replies.parse_slot_choice(self.state.text, len(self._offered()))

    @listen(replies.OPT_OUT)
    def handle_opt_out(self):
        seller = self._seller()
        # One confirmation, sent before the block; afterwards nothing is ever sent again.
        self._send(seller, "optout_confirm",
                   "הוסרת מרשימת התפוצה ולא נפנה אליך שוב. סליחה על ההפרעה.")
        self.store.opt_out(seller["phone"], seller["seller_id"], self.state.text)
        for m in self.store.q("SELECT id FROM messages WHERE seller_id=? AND status='draft'",
                              (seller["seller_id"],)):
            self.store.update_message(m["id"], status="blocked", note="seller opted out")
        self.store.set_status(seller["seller_id"], "opted_out")
        self.store.log_outcome(seller["seller_id"], False, "opt_out")
        self.state.result = "opted_out"

    @listen(replies.NOT_INTERESTED)
    def close_lost(self):
        seller = self._seller()
        self.store.set_status(seller["seller_id"], "not_interested")
        self.store.log_outcome(seller["seller_id"], False, "not_interested")
        self.state.result = "closed"

    @listen(replies.QUESTION)
    def draft_answer(self):
        seller = self._seller()
        body = drafting.draft_answer(self.state.text, self.store.messages(seller["seller_id"]),
                                     self.cfg, self._llm("smart"))
        self.state.message_id = self.store.add_message(seller["seller_id"], "out", "answer",
                                                       body, "draft")
        self.store.set_status(seller["seller_id"], "awaiting_approval")
        self.state.result = "answer drafted"

    @listen(replies.INTERESTED)
    def propose_slots(self):
        seller = self._seller()
        slots = scheduling.propose_slots(self.cfg, self.store.booked_starts())
        self.store.log(seller["seller_id"], "slots_offered",
                       json.dumps([s.isoformat(timespec="minutes") for s in slots]))
        self._send(seller, "slots", scheduling.slots_message(slots))
        self.store.set_status(seller["seller_id"], "slots_offered")
        self.state.result = "slots offered"

    @listen("slot_chosen")
    def book_meeting(self):
        seller = self._seller()
        start_at = datetime.fromisoformat(self._offered()[self._chosen_slot()])
        if start_at.isoformat(timespec="minutes") in self.store.booked_starts():
            self.state.label = replies.INTERESTED
            self.propose_slots()  # taken meanwhile: offer fresh slots
            return
        calendar.book(self.cfg, self.store, seller, start_at)
        self._send(seller, "booking",
                   f"נקבע! נתראה {scheduling.format_slot(start_at)} ב{seller['address']}. "
                   "תודה רבה.")
        self.store.set_status(seller["seller_id"], "booked")
        self.store.log_outcome(seller["seller_id"], True, "meeting_booked")
        self.state.result = "booked"


def run_event(store: Store, cfg: Config | None = None, **state) -> OutreachState:
    flow = OutreachFlow(cfg=cfg or load_config(), store=store, suppress_flow_events=True)
    flow.kickoff(inputs=state)
    return flow.state
