from datetime import datetime

import pytest

from metatron.channels.whatsapp import WhatsAppChannel
from metatron.config import load_config
from metatron.flows.outreach_flow import run_event
from metatron.outreach import replies, scheduling
from metatron.outreach.drafting import OPT_OUT_LINE
from metatron.outreach.store import Store, normalize_phone


@pytest.fixture()
def cfg():
    return load_config()


@pytest.fixture()
def store():
    s = Store(":memory:")
    s.upsert_sellers([
        {"seller_id": f"S{i}", "name": f"דנה כהן{i}", "phone": f"050-000000{i}", "city": "חולון",
         "address": f"הרצל {i}", "rooms": 4.0, "area_sqm": 95, "asking_price": 2_900_000,
         "days_on_market": 70, "price_drops": 2, "score": 0.9 - i / 10, "rank": i,
         "model_version": "v1", "run_id": "t"} for i in (1, 2, 3)])
    return s


def _approve_first_message(store, cfg, sid, edited=None):
    run_event(store, cfg, event="draft", seller_id=sid)
    draft = next(d for d in store.pending_drafts() if d["seller_id"] == sid)
    return run_event(store, cfg, event="approve", seller_id=sid,
                     message_id=draft["message_id"], edited_body=edited)


@pytest.mark.parametrize("text", ["הסר", "הסירו אותי", "תורידו אותי מהרשימה", "לא לפנות אליי",
                                  "די כבר!", "אל תשלחו לי יותר", "STOP", "תפסיקו"])
def test_opt_out_detected(text):
    assert replies.is_opt_out(text)
    assert replies.classify(text) == replies.OPT_OUT


@pytest.mark.parametrize("text,label", [
    ("כן, מעוניין", replies.INTERESTED), ("בשמחה", replies.INTERESTED),
    ("לא תודה", replies.NOT_INTERESTED), ("כבר מכרתי", replies.NOT_INTERESTED),
    ("כמה עמלה?", replies.QUESTION), ("על ידי מי?", replies.QUESTION),
])
def test_classify_keywords(text, label):
    assert replies.classify(text) == label


def test_nothing_is_sent_without_approval(store, cfg):
    run_event(store, cfg, event="draft", seller_id="S1")
    msgs = store.messages("S1")
    assert [m["status"] for m in msgs] == ["draft"]
    assert store.seller("S1")["status"] == "awaiting_approval"
    assert OPT_OUT_LINE in msgs[0]["body"]


def test_broker_edit_keeps_opt_out_line(store, cfg):
    _approve_first_message(store, cfg, "S1", edited="שלום, אפשר פגישה?")
    sent = store.messages("S1")[0]
    assert sent["status"] == "sent" and sent["body"].startswith("שלום, אפשר פגישה?")
    assert OPT_OUT_LINE in sent["body"] and "edited by broker" in sent["note"]


def test_interested_then_slot_books_meeting(store, cfg):
    _approve_first_message(store, cfg, "S1")
    st = run_event(store, cfg, event="reply", seller_id="S1", text="כן, מעוניין")
    assert st.result == "slots offered" and store.seller("S1")["status"] == "slots_offered"
    st = run_event(store, cfg, event="reply", seller_id="S1", text="2")
    assert st.result == "booked"
    meetings = store.meetings()
    assert len(meetings) == 1 and meetings[0]["seller_id"] == "S1"
    assert store.outcomes()[0]["agreed_to_meeting"] == 1


def test_question_needs_approval_again(store, cfg):
    _approve_first_message(store, cfg, "S1")
    st = run_event(store, cfg, event="reply", seller_id="S1", text="כמה עמלה אתה לוקח?")
    assert st.result == "answer drafted"
    assert store.messages("S1")[-1]["status"] == "draft"


def test_opt_out_blocks_everything_after(store, cfg):
    _approve_first_message(store, cfg, "S2")
    st = run_event(store, cfg, event="reply", seller_id="S2", text="הסר")
    assert st.result == "opted_out"
    msgs = store.messages("S2")
    assert msgs[-1]["kind"] == "optout_confirm" and msgs[-1]["status"] == "sent"
    assert store.is_opted_out("+972-50-0000002")         # any phone format
    st = run_event(store, cfg, event="draft", seller_id="S2")
    assert st.result.startswith("blocked")
    assert len(store.messages("S2")) == len(msgs)       # nothing new, not even a draft
    assert store.outcomes()[0]["reason"] == "opt_out"


def test_opt_out_blocks_pending_draft(store, cfg):
    _approve_first_message(store, cfg, "S3")
    run_event(store, cfg, event="reply", seller_id="S3", text="מה העמלה?")   # answer drafted
    draft = store.messages("S3")[-1]
    run_event(store, cfg, event="reply", seller_id="S3", text="בעצם תורידו אותי")
    assert store.message(draft["id"])["status"] == "blocked"
    st = run_event(store, cfg, event="approve", seller_id="S3", message_id=draft["id"])
    assert st.result == "not a pending draft"


def test_whatsapp_only_to_allowed_numbers(store, cfg):
    cfg["outreach"]["allowed_numbers"] = ["+972 50 000 0001"]
    ch = WhatsAppChannel(cfg, store)
    assert ch.send("050-0000002", "x").note == "number not in outreach.allowed_numbers"
    store.opt_out("050-0000001", "S1", "הסר")
    assert ch.send("050-0000001", "x").status == "blocked"


def test_slots_follow_rules(cfg):
    now = datetime(2026, 11, 4, 9, 0)  # Wednesday
    slots = scheduling.propose_slots(cfg, set(), now)
    assert len(slots) == 3
    assert all(s.weekday() in cfg["calendar"]["slots"]["weekdays"] for s in slots)
    taken = {slots[0].isoformat(timespec="minutes")}
    assert scheduling.propose_slots(cfg, taken, now)[0] != slots[0]
    assert replies.parse_slot_choice("אפשרות 3", 3) == 2
    assert replies.parse_slot_choice("השני", 3) == 1
    assert replies.parse_slot_choice("7", 3) is None


def test_normalize_phone():
    assert normalize_phone("050-123 4567") == normalize_phone("+972501234567") == "972501234567"
