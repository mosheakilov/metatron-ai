"""Local API for the dashboard. Listens on 127.0.0.1 only; the browser is the UI.

The same OutreachFlow as the course project does the work: drafting, approval, replies,
opt-out and booking. This module only wires it to settings, the outbox and the gateway.
"""

from __future__ import annotations

import hashlib
import io
import re
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from metatron.flows.outreach_flow import run_event
from metatron.llm import use_llm
from metatron.outreach.store import Store
from metatron.product import contacts
from metatron.product.gateway import GatewayClient, handle_inbound
from metatron.product.outbox import Outbox
from metatron.product.settings import Settings

WEB_DIR = Path(__file__).resolve().parent / "web"

STATUS_HE = {
    "new": "חדש", "awaiting_approval": "ממתין לאישור", "sent": "נשלחה פנייה",
    "in_conversation": "בשיחה", "slots_offered": "הוצעו מועדים", "booked": "נקבעה פגישה",
    "not_interested": "לא מעוניין", "opted_out": "הוסר", "rejected": "נדחה",
    "broker_took_over": "בטיפול אישי",
}


class Ctx:
    def __init__(self, settings: Settings, gateway: GatewayClient, outbox: Outbox | None = None):
        self.settings = settings
        self.store = Store(settings.config()["outreach"]["db_path"])
        self.gateway = gateway
        self.outbox = outbox or Outbox(self.store, settings, gateway)
        self.uploads: dict[str, dict] = {}

    @property
    def cfg(self):
        return self.settings.config()

    def event(self, **state):
        return run_event(self.store, self.cfg, **state)


class SettingsIn(BaseModel):
    broker_name: str | None = None
    office_name: str | None = None
    meeting_minutes: int | None = None
    message_template: str | None = None
    include_opt_out: bool | None = None
    availability: dict | None = None
    limits: dict | None = None
    paused: bool | None = None
    ai: dict | None = None
    setup_done: bool | None = None


class ConnectIn(BaseModel):
    mode: str = "qr"
    phone: str | None = None


class ImportIn(BaseModel):
    token: str
    mapping: dict[str, int | None]


class DraftIn(BaseModel):
    seller_ids: list[str]


class ApproveIn(BaseModel):
    body: str | None = None


class BulkIn(BaseModel):
    message_ids: list[int]


class SendIn(BaseModel):
    body: str


class PreviewIn(BaseModel):
    body: str
    include_opt_out: bool | None = None  # the unsaved checkbox in the settings screen


class MediaIn(BaseModel):
    attach: bool


MAX_IMAGE_MB = 15
MEDIA_NAME = re.compile(r"^[0-9a-f]{16}\.jpg$")


def to_jpeg(data: bytes) -> bytes:
    """Any picture the broker uploads becomes a WhatsApp-friendly JPEG (upright, max 1600px)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("הקובץ אינו תמונה. אפשר להעלות JPG, PNG או WEBP") from e
    if img.mode != "RGB":
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.convert("RGBA").split()[-1])
        img = bg
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def create_app(ctx: Ctx) -> FastAPI:
    app = FastAPI(title="METATRON", docs_url=None, redoc_url=None)
    store = ctx.store

    # ---- overview -----------------------------------------------------------------------
    @app.get("/api/state")
    def state():
        return {"settings": ctx.settings.public(), "whatsapp": ctx.gateway.status(),
                "ai": use_llm(ctx.cfg), "outbox": ctx.outbox.status(),
                "status_labels": STATUS_HE}

    @app.get("/api/stats")
    def stats():
        counts = {r["status"]: r["n"] for r in store.q(
            "SELECT status, COUNT(*) AS n FROM sellers GROUP BY status")}
        total = sum(counts.values())
        contacted = total - counts.get("new", 0) - counts.get("awaiting_approval", 0) \
            - counts.get("rejected", 0)
        replied = store.one("SELECT COUNT(DISTINCT seller_id) AS n FROM messages "
                            "WHERE direction='in'")["n"]
        upcoming = store.q("SELECT m.*, s.name, s.phone FROM meetings m JOIN sellers s "
                           "USING(seller_id) WHERE m.start >= ? ORDER BY m.start LIMIT 5",
                           (datetime.now().isoformat(timespec="minutes"),))
        activity = store.q(
            "SELECT m.id, m.seller_id, m.direction, m.kind, m.body, m.status, m.created_at, "
            "s.name FROM messages m JOIN sellers s USING(seller_id) "
            "WHERE m.status != 'draft' ORDER BY m.id DESC LIMIT 12")
        return {"total": total, "by_status": counts, "contacted": contacted,
                "replied": replied, "booked": counts.get("booked", 0),
                "opted_out": counts.get("opted_out", 0),
                "pending_approval": len(store.pending_drafts()),
                "upcoming": upcoming, "activity": activity}

    # ---- settings & setup ---------------------------------------------------------------
    @app.put("/api/settings")
    def put_settings(body: SettingsIn):
        changes = body.model_dump(exclude_none=True)
        if "ai" in changes and changes["ai"].get("license_key", "").startswith("…"):
            changes["ai"].pop("license_key")  # the masked value came back unchanged
        ctx.settings.update(changes)
        return ctx.settings.public()

    # ---- WhatsApp -----------------------------------------------------------------------
    @app.get("/api/whatsapp")
    def wa_status():
        return ctx.gateway.status()

    @app.post("/api/whatsapp/connect")
    def wa_connect(body: ConnectIn):
        try:
            return ctx.gateway.connect(body.mode, body.phone)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/whatsapp/logout")
    def wa_logout():
        return ctx.gateway.logout()

    @app.post("/internal/wa/inbound")
    def wa_inbound(msg: dict, x_gateway_token: str = Header(default="")):
        if not secrets.compare_digest(x_gateway_token, ctx.settings.data["secret"]):
            raise HTTPException(401, "bad token")
        return {"result": handle_inbound(store, ctx.cfg, msg)}

    # ---- contacts -----------------------------------------------------------------------
    @app.post("/api/contacts/preview")
    async def contacts_preview(file: UploadFile = File(...)):  # noqa: B008 (FastAPI idiom)
        try:
            headers, rows = contacts.read_rows(file.filename or "", await file.read())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return _preview(file.filename or "", headers, rows)

    @app.post("/api/contacts/paste")
    def contacts_paste(body: SendIn):
        try:
            headers, rows = contacts.read_pasted(body.body)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return _preview("טקסט מודבק", headers, rows)

    def _preview(filename: str, headers: list[str], rows: list[list[str]]) -> dict:
        token = secrets.token_urlsafe(8)
        ctx.uploads[token] = {"name": filename, "headers": headers, "rows": rows}
        mapping = contacts.guess_mapping(headers)
        prep = contacts.prepare(headers, rows, mapping, store)
        return {"token": token, "filename": filename, "headers": headers,
                "sample": rows[:5], "n_rows": len(rows), "mapping": mapping,
                "fields": list(contacts.FIELDS), "required": list(contacts.REQUIRED),
                **_summary(prep)}

    @app.post("/api/contacts/remap")
    def contacts_remap(body: ImportIn):
        up = _upload(body.token)
        return _summary(contacts.prepare(up["headers"], up["rows"], body.mapping, store))

    @app.post("/api/contacts/import")
    def contacts_import(body: ImportIn):
        up = _upload(body.token)
        prep = contacts.prepare(up["headers"], up["rows"], body.mapping, store)
        if not prep["ok"]:
            raise HTTPException(400, "חסרות עמודות חובה: " + ", ".join(prep["missing"]))
        result = contacts.save(prep["contacts"], store, up["name"])
        ctx.uploads.pop(body.token, None)
        return {**result, "issues": prep["issues"]}

    def _upload(token: str) -> dict:
        if token not in ctx.uploads:
            raise HTTPException(404, "הקובץ פג תוקף, העלו אותו שוב")
        return ctx.uploads[token]

    def _summary(prep: dict) -> dict:
        new = sum(1 for c in prep["contacts"] if not c["existing_status"])
        return {"ok": prep["ok"], "missing": prep["missing"], "valid": len(prep["contacts"]),
                "new": new, "existing": len(prep["contacts"]) - new, "issues": prep["issues"],
                "preview": prep["contacts"][:8]}

    @app.get("/api/contacts")
    def list_contacts(status: str | None = None, q: str | None = None, limit: int = 1000):
        sql, args = "SELECT * FROM sellers WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        if q:
            sql += " AND (name LIKE ? OR phone LIKE ? OR city LIKE ? OR address LIKE ?)"
            args += [f"%{q}%"] * 4
        rows = store.q(sql + " ORDER BY rank LIMIT ?", (*args, limit))
        return {"contacts": rows, "total": store.one("SELECT COUNT(*) AS n FROM sellers")["n"]}

    @app.delete("/api/contacts/{seller_id}")
    def delete_contact(seller_id: str):
        s = store.seller(seller_id)
        if not s:
            raise HTTPException(404, "not found")
        if s["status"] != "new":
            raise HTTPException(400, "אפשר למחוק רק איש קשר שעוד לא פנו אליו")
        store.x("DELETE FROM sellers WHERE seller_id=?", (seller_id,))
        return {"deleted": seller_id}

    # ---- approval queue -----------------------------------------------------------------
    @app.post("/api/drafts")
    def create_drafts(body: DraftIn):
        made, skipped = 0, 0
        for sid in body.seller_ids:
            s = store.seller(sid)
            if not s or s["status"] not in ("new", "rejected"):
                skipped += 1
                continue
            st = ctx.event(event="draft", seller_id=sid)
            if st.result == "drafted":
                made += 1
                if ctx.settings.data["outreach_image"]:
                    store.update_message(st.message_id, media=ctx.settings.data["outreach_image"])
        return {"drafted": made, "skipped": skipped}

    @app.post("/api/template/preview")
    def template_preview(body: PreviewIn):
        from metatron.outreach.drafting import render_template

        cfg = ctx.cfg
        if body.include_opt_out is not None:
            cfg["outreach"]["include_opt_out"] = body.include_opt_out
        sample = store.one("SELECT * FROM sellers WHERE status='new' ORDER BY rank LIMIT 1") \
            or {"name": "יעל כהן", "address": "הנשיא 10", "city": "חיפה"}
        return {"text": render_template(body.body, sample, cfg), "seller": sample.get("name")}

    # ---- the picture sent with first messages ---------------------------------------------
    @app.post("/api/media/outreach")
    async def upload_outreach_image(file: UploadFile = File(...)):  # noqa: B008 (FastAPI idiom)
        data = await file.read()
        if len(data) > MAX_IMAGE_MB * 1_000_000:
            raise HTTPException(400, f"התמונה גדולה מדי (עד {MAX_IMAGE_MB}MB)")
        try:
            jpeg = to_jpeg(data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        name = hashlib.sha256(jpeg).hexdigest()[:16] + ".jpg"
        (ctx.settings.media_dir / name).write_bytes(jpeg)
        ctx.settings.update({"outreach_image": name})
        return ctx.settings.public()

    @app.delete("/api/media/outreach")
    def remove_outreach_image():
        # the file stays: drafts already approved with it still need it
        ctx.settings.update({"outreach_image": ""})
        return ctx.settings.public()

    @app.get("/api/media/{name}")
    def media(name: str):
        f = ctx.settings.media_dir / name
        if not MEDIA_NAME.match(name) or not f.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(f, media_type="image/jpeg")

    @app.get("/api/queue")
    def queue():
        return {"drafts": store.pending_drafts()}

    @app.post("/api/queue/{message_id}/approve")
    def approve(message_id: int, body: ApproveIn):
        msg = store.message(message_id)
        edited = body.body if body.body and msg and body.body.strip() != msg["body"].strip() else None
        return {"result": ctx.event(event="approve", message_id=message_id,
                                    edited_body=edited).result}

    @app.post("/api/queue/approve")
    def approve_many(body: BulkIn):
        results = [ctx.event(event="approve", message_id=i).result for i in body.message_ids]
        return {"approved": sum(r in ("queued", "sent") for r in results), "results": results}

    @app.post("/api/queue/{message_id}/media")
    def draft_media(message_id: int, body: MediaIn):
        """Attach the current picture to one draft, or send that draft as text only."""
        msg = store.message(message_id)
        if not msg or msg["status"] != "draft" or msg["kind"] != "outreach":
            raise HTTPException(400, "אפשר לצרף תמונה רק להודעה ראשונה שממתינה לאישור")
        image = ctx.settings.data["outreach_image"]
        if body.attach and not image:
            raise HTTPException(400, "עוד לא הועלתה תמונה בהגדרות")
        store.update_message(message_id, media=image if body.attach else None)
        return {"media": image if body.attach else None}

    @app.post("/api/queue/{message_id}/reject")
    def reject(message_id: int):
        return {"result": ctx.event(event="reject", message_id=message_id).result}

    # ---- outbox -------------------------------------------------------------------------
    @app.get("/api/outbox")
    def outbox():
        return {**ctx.outbox.status(), "messages": ctx.outbox.queued(),
                "failed": store.q("SELECT m.*, s.name, s.phone FROM messages m JOIN sellers s "
                                  "USING(seller_id) WHERE m.status='failed' ORDER BY m.id DESC")}

    @app.post("/api/outbox/{message_id}/retry")
    def retry(message_id: int):
        ctx.outbox.retry(message_id)
        return ctx.outbox.status()

    # ---- conversations ------------------------------------------------------------------
    @app.get("/api/conversations")
    def conversations():
        return {"conversations": store.q(
            "SELECT s.*, m.body AS last_body, m.direction AS last_direction, "
            "m.created_at AS last_at, "
            "(SELECT COUNT(*) FROM messages i WHERE i.seller_id=s.seller_id AND i.direction='in')"
            " AS n_in "
            "FROM sellers s JOIN messages m ON m.id = (SELECT MAX(id) FROM messages x "
            "WHERE x.seller_id=s.seller_id AND x.status != 'draft') "
            "ORDER BY m.id DESC")}

    @app.get("/api/conversations/{seller_id}")
    def conversation(seller_id: str):
        s = store.seller(seller_id)
        if not s:
            raise HTTPException(404, "not found")
        return {"seller": s, "messages": store.messages(seller_id),
                "meetings": store.q("SELECT * FROM meetings WHERE seller_id=?", (seller_id,))}

    @app.post("/api/conversations/{seller_id}/send")
    def send_manual(seller_id: str, body: SendIn):
        s = store.seller(seller_id)
        if not s:
            raise HTTPException(404, "not found")
        if store.is_opted_out(s["phone"]):
            raise HTTPException(400, "המוכר ביקש להסיר, אי אפשר לשלוח לו")
        if s["status"] in ("new", "rejected", "awaiting_approval"):
            raise HTTPException(400, "הודעה ראשונה יוצאת רק דרך תור האישור")
        mid = store.add_message(seller_id, "out", "manual", body.body.strip(), "queued",
                                channel="wa_web", note="written in the dashboard")
        store.set_status(seller_id, "broker_took_over")
        return {"message_id": mid}

    @app.post("/api/conversations/{seller_id}/automation")
    def resume_automation(seller_id: str):
        s = store.seller(seller_id)
        if s and s["status"] == "broker_took_over":
            store.set_status(seller_id, "in_conversation")
        return {"status": store.seller(seller_id)["status"]}

    # ---- meetings -----------------------------------------------------------------------
    @app.get("/api/meetings")
    def meetings():
        return {"meetings": store.meetings()}

    # ---- the dashboard (built single-page app) ------------------------------------------
    if (WEB_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (WEB_DIR / path).resolve()
            inside = WEB_DIR.resolve() in f.parents
            return FileResponse(f if path and inside and f.is_file() else WEB_DIR / "index.html")

    return app
