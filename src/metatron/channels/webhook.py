"""WhatsApp Cloud API webhook: inbound replies -> OutreachFlow("reply").

    uvicorn metatron.channels.webhook:app --port 8000
    cloudflared tunnel --url http://localhost:8000     # public HTTPS URL for Meta
"""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from metatron.config import load_config
from metatron.flows.outreach_flow import run_event
from metatron.outreach.store import Store

cfg = load_config()
store = Store(cfg.path(cfg["outreach"]["db_path"]))
app = FastAPI(title="METATRON WhatsApp webhook")


@app.get("/webhook")
def verify(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == os.getenv("WA_VERIFY_TOKEN"):
        return PlainTextResponse(p.get("hub.challenge", ""))
    raise HTTPException(403)


def _signature_ok(body: bytes, header: str | None) -> bool:
    secret = os.getenv("WA_APP_SECRET")
    if not secret:
        return True  # local development without an app secret
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(header) and hmac.compare_digest(expected, header)


def handle_payload(payload: dict) -> list[dict]:
    """Process every inbound text message in a webhook payload. Returns what was done."""
    done = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                text = (msg.get("text") or {}).get("body") or \
                       (msg.get("button") or {}).get("text") or ""
                seller = store.seller_by_phone(msg.get("from", ""))
                if not seller or not text:
                    store.log(None, "inbound_unmatched", f"{msg.get('from')}: {text[:100]}")
                    done.append({"from": msg.get("from"), "result": "unmatched"})
                    continue
                st = run_event(store, cfg, event="reply", seller_id=seller["seller_id"], text=text)
                done.append({"seller_id": seller["seller_id"], "label": st.label,
                             "result": st.result})
    return done


@app.post("/webhook")
async def receive(request: Request):
    body = await request.body()
    if not _signature_ok(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401)
    return {"handled": handle_payload(await request.json())}
