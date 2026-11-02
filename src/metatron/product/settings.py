"""The broker's settings and data folder.

Everything the product writes lives in one folder per Windows user (METATRON_HOME, default
%LOCALAPPDATA%\\METATRON): settings.json, metatron.db, the WhatsApp link and logs. Uninstalling
the app leaves it in place, so reinstalling keeps clients and conversations.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
from pathlib import Path
from typing import Any

from metatron.config import Config, load_config

DEFAULTS: dict[str, Any] = {
    "setup_done": False,
    "broker_name": "",
    "wa_phone": "",             # typed in the installer; pre-fills the WhatsApp link step
    "office_name": "",
    "meeting_minutes": 45,
    # Honest by default: a client list is not a list of ads, so the message does not claim one.
    "message_template": ("שלום {שם}, כאן {חתימה}.\n"
                         "רציתי לבדוק אם {נכס} עדיין עומד למכירה. המשרד שלנו פעיל באזור, "
                         "ואשמח להכיר את הנכס.\n"
                         "אפשר לקבוע פגישה קצרה של חצי שעה?"),
    # The broker decides whether messages end with 'להסרה השיבו "הסר".' A reply of "הסר" is
    # honoured either way.
    "include_opt_out": True,
    # An optional picture sent with every first message (the text becomes its caption). The file
    # lives in <home>/media; the name is a content hash, so drafts keep the picture they were
    # approved with even after the broker replaces it.
    "outreach_image": "",
    "availability": {"weekdays": [6, 0, 1, 2, 3], "hours": [10, 13, 17], "days_ahead": 7},
    # Pacing for first messages. A linked device is not the official API, so the product keeps
    # cold outreach slow and human-looking; conversation replies are not capped.
    "limits": {"daily_new": 15, "start_hour": 9, "end_hour": 19, "min_gap_sec": 90,
               "max_gap_sec": 240, "send_on_weekend": False},
    "paused": False,
    "ai": {"proxy_url": "", "license_key": ""},
}


def home() -> Path:
    base = os.getenv("METATRON_HOME") or Path(os.getenv("LOCALAPPDATA", Path.home())) / "METATRON"
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Settings:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or home()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.file = self.folder / "settings.json"
        self.data = _merge(DEFAULTS, self._read())
        self._take_installer_answers()
        if "secret" not in self.data:  # shared by the app and the WhatsApp gateway
            self.data["secret"] = secrets.token_urlsafe(24)
            self.save()

    def _take_installer_answers(self) -> None:
        """The installer writes install.json (name, WhatsApp number); use it once, then delete."""
        f = self.folder / "install.json"
        if not f.exists():
            return
        try:
            answers = json.loads(f.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            answers = {}
        if not self.data["setup_done"]:
            for k in ("broker_name", "wa_phone"):
                if answers.get(k) and not self.data[k]:
                    self.data[k] = str(answers[k]).strip()
        f.unlink()
        self.save()

    def _read(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.file)

    def update(self, changes: dict) -> None:
        changes = {k: v for k, v in changes.items() if k in DEFAULTS}
        self.data = _merge(self.data, changes)
        self.save()

    @property
    def media_dir(self) -> Path:
        path = self.folder / "media"
        path.mkdir(exist_ok=True)
        return path

    def public(self) -> dict:
        """Settings the dashboard may see (no secret, license key masked)."""
        out = {k: copy.deepcopy(v) for k, v in self.data.items() if k != "secret"}
        key = out["ai"].get("license_key") or ""
        out["ai"]["license_key"] = f"…{key[-4:]}" if key else ""
        return out

    def config(self) -> Config:
        """The engine's Config, with this broker's values on top of the packaged defaults."""
        cfg = load_config()
        d = self.data
        cfg["outreach"].update(db_path=str(self.folder / "metatron.db"), channel="wa_web",
                               broker_name=d["broker_name"],
                               office_name=d["office_name"] or d["broker_name"],
                               template=d["message_template"],
                               include_opt_out=d["include_opt_out"])
        cfg["calendar"]["slots"].update(weekdays=d["availability"]["weekdays"],
                                        hours=d["availability"]["hours"],
                                        days_ahead=d["availability"]["days_ahead"],
                                        duration_minutes=d["meeting_minutes"])
        cfg["llm"]["proxy_url"] = d["ai"]["proxy_url"]
        cfg["llm"]["license_key"] = d["ai"]["license_key"]
        return cfg
