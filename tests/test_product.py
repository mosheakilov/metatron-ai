"""The installed product: settings, client-list import, outbox pacing, inbound routing and API."""

import io
import random
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from metatron.outreach.store import normalize_phone
from metatron.product import contacts
from metatron.product.gateway import handle_inbound
from metatron.product.outbox import Outbox
from metatron.product.server import Ctx, create_app
from metatron.product.settings import Settings

MON_11 = datetime(2026, 11, 2, 11, 0)  # a Monday inside working hours


class FakeGateway:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.images: list[str | None] = []
        self.fail = False

    def status(self):
        return {"status": "open", "me": {"phone": "972500000000"}}

    def connected(self):
        return True

    def send(self, phone, text, typing_ms=0, image=None):
        if self.fail:
            raise RuntimeError("number is not on WhatsApp")
        self.sent.append((phone, text))
        self.images.append(image)
        return f"wa-{len(self.sent)}"


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_HOME", str(tmp_path))
    settings = Settings()
    settings.update({"broker_name": "דנה", "office_name": "נדל\"ן דנה", "setup_done": True})
    gw = FakeGateway()
    c = Ctx(settings, gw)
    c.outbox = Outbox(c.store, settings, gw, rng=random.Random(1))
    return c


@pytest.fixture()
def api(ctx):
    return TestClient(create_app(ctx))


def xlsx(rows):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


LIST = [["שם מלא", "נייד", "עיר", "כתובת", "חדרים", "מחיר מבוקש", "הערות"],
        ["יעל כהן", "050-1234567", "חיפה", "הנשיא 10", 4, "2,150,000 ₪", "מכרה בעבר"],
        ["רון לוי", "052 765 4321", "חיפה", "מוריה 5", 3.5, "", ""],
        ["כפול", "0501234567", "", "", "", "", ""],
        ["שגוי", "12345", "", "", "", "", ""]]


def import_list(api, rows=LIST, name="clients.xlsx"):
    pre = api.post("/api/contacts/preview", files={"file": (name, xlsx(rows))}).json()
    return pre, api.post("/api/contacts/import", json={"token": pre["token"],
                                                       "mapping": pre["mapping"]}).json()


# ---- settings -------------------------------------------------------------------------------
def test_settings_persist_and_hide_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_HOME", str(tmp_path))
    s = Settings()
    s.update({"ai": {"license_key": "LIC-123456789"}, "not_a_setting": 1})
    again = Settings()
    assert again.data["secret"] == s.data["secret"]
    assert again.public()["ai"]["license_key"] == "…6789"
    assert "secret" not in again.public() and "not_a_setting" not in again.data
    cfg = again.config()
    assert cfg["outreach"]["channel"] == "wa_web"
    assert cfg["outreach"]["db_path"].startswith(str(tmp_path))


# ---- client list ----------------------------------------------------------------------------
def test_hebrew_headers_are_mapped():
    m = contacts.guess_mapping(LIST[0])
    assert (m["name"], m["phone"], m["city"], m["address"], m["rooms"], m["asking_price"],
            m["notes"]) == (0, 1, 2, 3, 4, 5, 6)


def test_csv_in_windows_hebrew_encoding():
    data = "שם,טלפון\nיעל,0501234567\n".encode("cp1255")
    headers, rows = contacts.read_rows("list.csv", data)
    assert headers == ["שם", "טלפון"] and rows == [["יעל", "0501234567"]]


def test_import_reports_problems_and_saves_valid_rows(api, ctx):
    pre, res = import_list(api)
    assert pre["valid"] == 2 and {i["problem"] for i in pre["issues"]} == {"כפול בקובץ",
                                                                          "מספר טלפון לא תקין"}
    assert res["saved"] == 2 and res["new"] == 2
    yael = ctx.store.seller("c972501234567")
    assert yael["status"] == "new" and yael["asking_price"] == 2150000 and yael["rank"] == 1
    _, again = import_list(api)  # importing the same list twice does not duplicate
    assert again["new"] == 0 and api.get("/api/contacts").json()["total"] == 2


def test_import_requires_name_and_phone(api):
    pre = api.post("/api/contacts/preview",
                   files={"file": ("x.xlsx", xlsx([["עיר"], ["חיפה"]]))}).json()
    assert pre["ok"] is False and set(pre["missing"]) == {"name", "phone"}


def test_opted_out_number_is_not_imported_again(api, ctx):
    ctx.store.opt_out("0501234567", None, "הסר")
    pre, _ = import_list(api)
    assert any(i["problem"] == "ביקש בעבר להסיר" for i in pre["issues"])


# ---- approval -> outbox -> WhatsApp ---------------------------------------------------------
def approve_first(api, ctx):
    import_list(api)
    api.post("/api/drafts", json={"seller_ids": ["c972501234567"]})
    draft = api.get("/api/queue").json()["drafts"][0]
    assert "דנה" in draft["body"] and 'להסרה השיבו "הסר".' in draft["body"]
    assert api.post(f"/api/queue/{draft['message_id']}/approve", json={}).json()["result"] == "queued"
    return draft


def test_nothing_is_sent_without_approval(api, ctx):
    import_list(api)
    api.post("/api/drafts", json={"seller_ids": ["c972501234567", "c972527654321"]})
    assert ctx.outbox.send_one(MON_11) is None and ctx.gateway.sent == []


def test_approved_message_goes_out_through_the_outbox(api, ctx):
    approve_first(api, ctx)
    sent = ctx.outbox.send_one(MON_11)
    assert sent["status"] == "sent" and ctx.gateway.sent[0][0] == "972501234567"
    assert ctx.store.seller("c972501234567")["status"] == "sent"


def test_first_messages_are_paced_capped_and_kept_to_working_hours(ctx):
    ctx.settings.update({"limits": {"daily_new": 2, "min_gap_sec": 100, "max_gap_sec": 100}})
    for i in range(3):
        sid = f"s{i}"
        ctx.store.upsert_sellers([{"seller_id": sid, "name": "x", "phone": f"05000000{i}0"}], "sent")
        ctx.store.add_message(sid, "out", "outreach", "שלום", "queued")
    assert ctx.outbox.decide(MON_11.replace(hour=22)).wait_reason == "outside_hours"
    assert ctx.outbox.decide(datetime(2026, 11, 7, 11)).wait_reason == "outside_hours"  # Saturday
    assert ctx.outbox.send_one(MON_11)["status"] == "sent"
    assert ctx.outbox.decide(MON_11 + timedelta(seconds=30)).wait_reason == "pacing"
    assert ctx.outbox.send_one(MON_11 + timedelta(seconds=101))["status"] == "sent"
    d = ctx.outbox.decide(MON_11 + timedelta(seconds=500))
    assert d.wait_reason == "daily_cap" and d.next_at.startswith("2026-11-03T09")


def test_conversation_replies_skip_the_first_message_lane(ctx):
    ctx.settings.update({"limits": {"daily_new": 0}})
    ctx.store.upsert_sellers([{"seller_id": "a", "name": "x", "phone": "0501111111"}], "sent")
    ctx.store.add_message("a", "out", "outreach", "פנייה", "queued")
    ctx.store.add_message("a", "out", "slots", "מועדים", "queued")
    assert ctx.outbox.send_one(MON_11.replace(hour=23))["kind"] == "slots"


def test_message_waiting_in_outbox_is_dropped_after_opt_out(api, ctx):
    approve_first(api, ctx)
    ctx.store.opt_out("972501234567", "c972501234567", "הסר")
    assert ctx.outbox.send_one(MON_11)["status"] == "blocked" and ctx.gateway.sent == []


def test_failed_send_is_kept_for_retry(api, ctx):
    approve_first(api, ctx)
    ctx.gateway.fail = True
    msg = ctx.outbox.send_one(MON_11)
    assert msg["status"] == "failed" and "not on WhatsApp" in ctx.store.message(msg["id"])["note"]
    ctx.gateway.fail = False
    api.post(f"/api/outbox/{msg['id']}/retry")
    assert ctx.outbox.send_one(MON_11)["status"] == "sent"


# ---- incoming WhatsApp messages -------------------------------------------------------------
def inbound(api, ctx, text, phone="972501234567", **extra):
    return api.post("/internal/wa/inbound", headers={"x-gateway-token": ctx.settings.data["secret"]},
                    json={"id": extra.pop("id", f"in-{text}"), "phone": phone, "text": text,
                          **extra}).json()["result"]


def test_inbound_requires_the_gateway_token(api):
    assert api.post("/internal/wa/inbound", json={"phone": "1", "text": "x"}).status_code == 401


def test_private_chats_of_the_broker_are_ignored_and_not_stored(api, ctx):
    approve_first(api, ctx)
    assert inbound(api, ctx, "מה שלומך אבא?", phone="972541112233") == "ignored"
    assert ctx.store.one("SELECT COUNT(*) AS n FROM messages WHERE direction='in'")["n"] == 0


def test_reply_flow_to_booked_meeting(api, ctx):
    approve_first(api, ctx)
    ctx.outbox.send_one(MON_11)
    assert inbound(api, ctx, "כן, מעוניין") == "interested"
    ctx.outbox.send_one(MON_11)  # the slots message
    assert inbound(api, ctx, "2") == "slot_chosen"
    assert ctx.store.seller("c972501234567")["status"] == "booked"
    assert len(api.get("/api/meetings").json()["meetings"]) == 1
    assert inbound(api, ctx, "2") == "duplicate"  # same WhatsApp id delivered twice


def test_opt_out_reply_blocks_number(api, ctx):
    approve_first(api, ctx)
    ctx.outbox.send_one(MON_11)
    assert inbound(api, ctx, "תורידו אותי מהרשימה") == "opt_out"
    ctx.outbox.send_one(MON_11)  # the single confirmation still goes out
    assert "הוסרת" in ctx.gateway.sent[-1][1]
    assert ctx.store.is_opted_out("0501234567")


def test_broker_typing_on_the_phone_takes_over_the_conversation(api, ctx):
    approve_first(api, ctx)
    ctx.outbox.send_now(ctx.outbox.queued()[0]["id"])  # sent just now, so its echo is recent
    sent_body = ctx.gateway.sent[0][1]
    assert inbound(api, ctx, sent_body, from_me=True, id="echo") == "duplicate"
    assert inbound(api, ctx, "היי, זה דנה, אתקשר בערב", from_me=True) == "manual"
    assert ctx.store.seller("c972501234567")["status"] == "broker_took_over"
    assert inbound(api, ctx, "בסדר, תודה") == "stored"  # no automatic reply now
    assert inbound(api, ctx, "הסר") == "opt_out"        # but opt-out is always honoured


def test_manual_message_from_dashboard_needs_a_started_conversation(api, ctx):
    import_list(api)
    r = api.post("/api/conversations/c972501234567/send", json={"body": "שלום"})
    assert r.status_code == 400


def test_stats_and_state(api, ctx):
    approve_first(api, ctx)
    ctx.outbox.send_one(MON_11)
    st = api.get("/api/stats").json()
    assert st["total"] == 2 and st["contacted"] == 1
    state = api.get("/api/state").json()
    assert state["whatsapp"]["status"] == "open" and state["outbox"]["daily_cap"] == 15


def test_handle_inbound_ignores_old_history(ctx):
    old = (datetime.now() - timedelta(days=10)).timestamp()
    assert handle_inbound(ctx.store, ctx.cfg, {"phone": "1", "text": "x", "ts": old}) == "too_old"


def test_normalize_phone_matches_whatsapp_format():
    assert normalize_phone("+972-50-123-4567") == normalize_phone("050 1234567") == "972501234567"


# ---- opening message & installer handoff ----------------------------------------------------
def test_default_message_is_honest_and_signed(api, ctx):
    draft = approve_first(api, ctx)
    assert "ראיתי את המודעה" not in draft["body"]  # a client list is not a list of ads
    assert "הנכס בהנשיא 10, חיפה" in draft["body"] and "דנה, נדל\"ן דנה" in draft["body"]


def test_broker_template_with_missing_address(ctx):
    from metatron.outreach.drafting import render_template

    text = render_template("שלום {שם}, האם {נכס} עדיין למכירה?", {"name": "יעל כהן"}, ctx.cfg)
    assert text.startswith("שלום יעל, האם הנכס שלך עדיין למכירה?")
    assert text.endswith('להסרה השיבו "הסר".')


def test_template_preview_endpoint(api):
    r = api.post("/api/template/preview", json={"body": "היי {שם} מ{עיר}"}).json()
    assert r["text"].startswith("היי יעל מחיפה")


def test_installer_answers_prefill_settings_once(tmp_path):
    (tmp_path / "install.json").write_text('{"broker_name": "דנה", "wa_phone": "050-1234567"}',
                                           encoding="utf-8-sig")
    s = Settings(tmp_path)
    assert (s.data["broker_name"], s.data["wa_phone"]) == ("דנה", "050-1234567")
    assert not (tmp_path / "install.json").exists()


# ---- opt-out line is the broker's choice ----------------------------------------------------
OPT_OUT = 'להסרה השיבו "הסר".'


def test_opt_out_line_can_be_turned_off(api, ctx):
    assert api.put("/api/settings", json={"include_opt_out": False}).json()["include_opt_out"] is False
    import_list(api)
    api.post("/api/drafts", json={"seller_ids": ["c972501234567"]})
    draft = api.get("/api/queue").json()["drafts"][0]
    assert OPT_OUT not in draft["body"]
    api.post(f"/api/queue/{draft['message_id']}/approve", json={"body": draft["body"] + " תודה"})
    ctx.outbox.send_one(MON_11)
    assert OPT_OUT not in ctx.gateway.sent[-1][1]  # not appended on approval either
    # a seller who still writes "הסר" is blocked for good
    assert inbound(api, ctx, "הסר") == "opt_out"
    assert ctx.store.is_opted_out("0501234567")


def test_opt_out_line_on_by_default_and_kept_on_edit(api, ctx):
    approve_first(api, ctx)
    ctx.outbox.send_one(MON_11)
    assert ctx.gateway.sent[-1][1].endswith(OPT_OUT)


def test_template_preview_follows_unsaved_checkbox(api):
    on = api.post("/api/template/preview", json={"body": "היי {שם}"}).json()["text"]
    off = api.post("/api/template/preview", json={"body": "היי {שם}",
                                                  "include_opt_out": False}).json()["text"]
    assert on.endswith(OPT_OUT) and OPT_OUT not in off


# ---- a picture with the first message -------------------------------------------------------
def png_bytes(color="red", size=(2400, 1200), mode="RGB"):
    from PIL import Image

    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def test_first_message_goes_out_with_the_picture(api, ctx):
    s = api.post("/api/media/outreach", files={"file": ("house.png", png_bytes())}).json()
    name = s["outreach_image"]
    assert name.endswith(".jpg")
    img = api.get(f"/api/media/{name}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    from PIL import Image

    assert max(Image.open(io.BytesIO(img.content)).size) == 1600  # resized for WhatsApp

    draft = approve_first(api, ctx)
    assert draft["media"] == name
    ctx.outbox.send_one(MON_11)
    assert ctx.gateway.images[-1] == str(ctx.settings.media_dir / name)
    assert "דנה" in ctx.gateway.sent[-1][1]  # the text is the picture's caption


def test_picture_can_be_dropped_from_one_draft_and_replaced_later(api, ctx):
    first = api.post("/api/media/outreach", files={"file": ("a.png", png_bytes())}).json()
    import_list(api)
    api.post("/api/drafts", json={"seller_ids": ["c972501234567", "c972527654321"]})
    a, b = api.get("/api/queue").json()["drafts"]
    assert api.post(f"/api/queue/{a['message_id']}/media", json={"attach": False}).json() == {
        "media": None}
    # a new picture does not change drafts made with the old one
    api.post("/api/media/outreach", files={"file": ("b.png", png_bytes("blue", mode="RGBA"))})
    for d in (a, b):
        api.post(f"/api/queue/{d['message_id']}/approve", json={})
    ctx.outbox.send_one(MON_11)
    ctx.outbox.send_one(MON_11 + timedelta(hours=1))
    assert ctx.gateway.images == [None, str(ctx.settings.media_dir / first["outreach_image"])]


def test_bad_uploads_and_media_names_are_refused(api):
    assert api.post("/api/media/outreach", files={"file": ("x.png", b"not an image")}).status_code == 400
    assert api.get("/api/media/settings.json").status_code == 404
    assert api.delete("/api/media/outreach").json()["outreach_image"] == ""


def test_missing_picture_fails_visibly(api, ctx):
    name = api.post("/api/media/outreach", files={"file": ("a.png", png_bytes())}).json()[
        "outreach_image"]
    approve_first(api, ctx)
    (ctx.settings.media_dir / name).unlink()
    assert ctx.outbox.send_one(MON_11)["status"] == "failed" and not ctx.gateway.sent


# ---- clients pasted as text -----------------------------------------------------------------
def paste(api, text):
    pre = api.post("/api/contacts/paste", json={"body": text}).json()
    return pre, {c["phone"]: c for c in pre["preview"]}


def test_paste_free_lines(api):
    pre, got = paste(api, "יעל כהן 050-1234567 חיפה, הנשיא 10\n"
                          "רון לוי - +972 52 765 4321\n"
                          "מיכל\n0541112233\n"
                          "סתם שורה בלי טלפון בסוף")
    assert pre["ok"] and pre["valid"] == 3
    assert got["972501234567"]["name"] == "יעל כהן"
    assert (got["972501234567"]["city"], got["972501234567"]["address"]) == ("חיפה", "הנשיא 10")
    assert got["972527654321"]["name"] == "רון לוי"
    assert got["972541112233"]["name"] == "מיכל"  # name line, then phone line


def test_paste_free_lines_pick_up_property_details(api):
    pre, got = paste(api, "רון לוי 052-7654321 הרצל 5 תל אביב 3.5 חד' 1,850,000 ₪ קומה 2\n"
                          "מיכל\n0541112233\n"
                          'רחוב ביאליק 12, רמת גן, 5 חדרים, 140 מ"ר, 3.2 מיליון\n'
                          "דני, באר שבע 053-3334444 דירת גן 950 אלף")
    assert {k: v for k, v in got["972527654321"].items() if k in (
        "city", "address", "rooms", "asking_price", "notes")} == {
        "city": "תל אביב", "address": "הרצל 5", "rooms": 3.5, "asking_price": 1850000,
        "notes": "קומה 2"}
    m = got["972541112233"]  # the details line under the phone line belongs to מיכל
    assert (m["city"], m["address"], m["rooms"], m["area_sqm"], m["asking_price"]) == (
        "רמת גן", "רחוב ביאליק 12", 5, 140, 3200000)
    d = got["972533334444"]
    assert (d["name"], d["city"], d["asking_price"], d["notes"]) == ("דני", "באר שבע", 950000,
                                                                    "דירת גן")


def test_paste_from_excel_with_and_without_header(api):
    pre, got = paste(api, "שם\tנייד\tעיר\nיעל כהן\t050-1234567\tחיפה\n")
    assert got["972501234567"]["city"] == "חיפה"
    pre, got = paste(api, "יעל כהן\t050-1234567\tחיפה\nרון\t0527654321\tטירה\n")
    assert pre["headers"][:2] == ["שם", "טלפון"] and pre["valid"] == 2


def test_paste_csv_with_header_and_import(api, ctx):
    pre, _ = paste(api, "name,phone,city\nYael,0501234567,Haifa\n")
    res = api.post("/api/contacts/import", json={"token": pre["token"], "mapping": pre["mapping"]})
    assert res.json()["saved"] == 1 and ctx.store.seller("c972501234567")["city"] == "Haifa"


def test_paste_without_phones_is_explained(api):
    r = api.post("/api/contacts/paste", json={"body": "רק שמות\nבלי מספרים"})
    assert r.status_code == 400 and "טלפון" in r.json()["detail"]


# ---- send now, and no opening message after the conversation has started --------------------
SUNDAY_NIGHT = datetime(2026, 11, 1, 23, 50)


def test_send_now_skips_working_hours(api, ctx):
    approve_first(api, ctx)
    assert ctx.outbox.send_one(SUNDAY_NIGHT) is None          # waits for working hours
    mid = ctx.outbox.queued()[0]["id"]
    assert api.post(f"/api/outbox/{mid}/send-now").json() == {"status": "sent"}
    assert len(ctx.gateway.sent) == 1 and not ctx.outbox.queued()
    assert api.post(f"/api/outbox/{mid}/send-now").status_code == 404  # not twice


def test_send_now_still_respects_opt_out(api, ctx):
    approve_first(api, ctx)
    ctx.store.opt_out("0501234567", None, "הסר")
    mid = ctx.outbox.queued()[0]["id"]
    assert api.post(f"/api/outbox/{mid}/send-now").status_code == 400 and not ctx.gateway.sent


def test_manual_message_cancels_waiting_opening_message(api, ctx):
    approve_first(api, ctx)
    api.post("/api/conversations/c972501234567/send", json={"body": "היי, מדבר איתך עכשיו"})
    ctx.outbox.send_one(MON_11)
    ctx.outbox.send_one(MON_11 + timedelta(hours=1))
    assert [t for _, t in ctx.gateway.sent] == ["היי, מדבר איתך עכשיו"]
    kinds = {m["kind"]: m["status"] for m in ctx.store.messages("c972501234567")}
    assert kinds["outreach"] == "cancelled"


def test_typing_on_the_phone_cancels_waiting_opening_message(api, ctx):
    approve_first(api, ctx)
    assert inbound(api, ctx, "שלום, אני מתקשר אליך עוד מעט", from_me=True) == "manual"
    assert ctx.outbox.send_one(MON_11) is None


# ---- deleting clients -----------------------------------------------------------------------
def test_delete_clients_any_status_with_their_conversation(api, ctx):
    approve_first(api, ctx)  # יעל: an approved opening message waits in the outbox
    assert ctx.store.seller("c972501234567")["status"] != "new"
    r = api.post("/api/contacts/delete", json={"seller_ids": ["c972501234567", "c972527654321", "nope"]})
    assert r.json() == {"deleted": 2}
    assert api.get("/api/contacts").json()["total"] == 0
    assert ctx.store.q("SELECT * FROM messages") == []
    assert ctx.outbox.send_one(MON_11) is None and ctx.gateway.sent == []
    assert api.delete("/api/contacts/c972501234567").status_code == 404


def test_deleted_client_who_opted_out_stays_blocked(api, ctx):
    import_list(api)
    ctx.store.opt_out("050-1234567", "c972501234567", "הסר")
    api.delete("/api/contacts/c972501234567")
    pre, _ = import_list(api)
    assert any(i["problem"] == "ביקש בעבר להסיר" for i in pre["issues"])


def test_paste_excel_cells_without_header_maps_property_columns(api):
    pre, got = paste(api, "יעל כהן\t050-1234567\tחיפה\tהנשיא 10\t4\t95\t2.1 מיליון\tקומה 3\n"
                          "רון לוי\t052-7654321\tתל אביב\tהרצל 5\t3.5\t80\t1,850,000\t\n")
    assert pre["headers"] == ["שם", "טלפון", "עיר", "כתובת", "חדרים", "שטח", "מחיר", "הערות"]
    assert all(v is not None for v in pre["mapping"].values())
    y = got["972501234567"]
    assert (y["city"], y["address"], y["rooms"], y["area_sqm"], y["asking_price"], y["notes"]) == (
        "חיפה", "הנשיא 10", 4, 95, 2100000, "קומה 3")
