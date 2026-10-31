"""Calendar backends. Local (SQLite) by default; optionally also nadlan-pro's users/{uid}/tasks.

The nadlan-pro document mirrors its `Task` type (src/types/index.ts): id = Date.now(),
date YYYY-MM-DD, time HH:MM, type 'פגישה'. nadlan-pro's code is not changed.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from metatron.config import Config
from metatron.outreach.store import Store


def book(cfg: Config, store: Store, seller: dict, start: datetime) -> int:
    minutes = cfg["calendar"]["slots"]["duration_minutes"]
    end = start + timedelta(minutes=minutes)
    address = f"{seller.get('address', '')}, {seller.get('city', '')}"
    meeting_id = store.add_meeting(seller["seller_id"], start.isoformat(timespec="minutes"),
                                   end.isoformat(timespec="minutes"), address)
    if cfg["calendar"]["backend"] == "nadlan_pro":
        try:
            ext = write_nadlan_pro_task(cfg, seller, start, address)
            store.x("UPDATE meetings SET external_id=? WHERE id=?", (ext, meeting_id))
        except Exception as e:  # the local meeting stands; the sync error is visible in the log
            store.log(seller["seller_id"], "nadlan_pro_sync_failed", str(e)[:300])
    return meeting_id


def write_nadlan_pro_task(cfg: Config, seller: dict, start: datetime, address: str) -> str:
    import firebase_admin
    from firebase_admin import firestore

    uid = cfg["calendar"]["nadlan_pro_uid"]
    if not uid:
        raise RuntimeError("calendar.nadlan_pro_uid is empty")
    if not firebase_admin._apps:
        firebase_admin.initialize_app()  # GOOGLE_APPLICATION_CREDENTIALS
    task_id = int(time.time() * 1000)
    firestore.client().collection("users").document(uid).collection("tasks") \
        .document(str(task_id)).set({
            "title": f"פגישת גיוס: {seller.get('name', '')}",
            "date": f"{start:%Y-%m-%d}",
            "time": f"{start:%H:%M}",
            "type": "פגישה",
            "notes": f"{address} · {seller.get('phone', '')} · נקבע ע\"י METATRON",
            "completed": False,
            "created_at": datetime.now().isoformat(),
        })
    return str(task_id)
