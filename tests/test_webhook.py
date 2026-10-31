import hashlib
import hmac

from fastapi.testclient import TestClient

from metatron.channels import webhook
from metatron.outreach.store import Store


def _payload(phone: str, text: str) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": phone, "type": "text", "text": {"body": text}}]}}]}]}


def _store_with_sent_seller() -> Store:
    s = Store(":memory:")
    s.upsert_sellers([{"seller_id": "S1", "name": "דנה", "phone": "050-0000001", "city": "חולון",
                       "address": "הרצל 1", "rooms": 4.0, "score": .9, "rank": 1}])
    s.set_status("S1", "sent")
    return s


def test_verify_handshake(monkeypatch):
    monkeypatch.setenv("WA_VERIFY_TOKEN", "abc")
    c = TestClient(webhook.app)
    ok = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "abc",
                                   "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x"}
                 ).status_code == 403


def test_inbound_opt_out(monkeypatch):
    monkeypatch.delenv("WA_APP_SECRET", raising=False)
    store = _store_with_sent_seller()
    monkeypatch.setattr(webhook, "store", store)
    r = TestClient(webhook.app).post("/webhook", json=_payload("972500000001", "הסר"))
    assert r.json()["handled"][0]["result"] == "opted_out"
    assert store.is_opted_out("0500000001")


def test_unknown_number_is_logged_not_answered(monkeypatch):
    monkeypatch.delenv("WA_APP_SECRET", raising=False)
    store = _store_with_sent_seller()
    monkeypatch.setattr(webhook, "store", store)
    r = TestClient(webhook.app).post("/webhook", json=_payload("972599999999", "שלום"))
    assert r.json()["handled"][0]["result"] == "unmatched"
    assert store.messages("S1") == []


def test_bad_signature_rejected(monkeypatch):
    monkeypatch.setenv("WA_APP_SECRET", "secret")
    body = b'{"entry": []}'
    c = TestClient(webhook.app)
    assert c.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=bad"}
                  ).status_code == 401
    good = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert c.post("/webhook", content=body, headers={"X-Hub-Signature-256": good,
                                                     "Content-Type": "application/json"}
                  ).status_code == 200
