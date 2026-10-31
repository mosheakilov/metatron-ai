"""Propose meeting slots from the broker's availability rules in config.yaml."""

from __future__ import annotations

from datetime import datetime, timedelta

from metatron.config import Config

HE_DAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def propose_slots(cfg: Config, booked: set[str], now: datetime | None = None,
                  n: int = 3) -> list[datetime]:
    rules = cfg["calendar"]["slots"]
    now = now or datetime.now()
    out: list[datetime] = []
    for d in range(1, rules["days_ahead"] + 1):
        day = (now + timedelta(days=d)).replace(minute=0, second=0, microsecond=0)
        if day.weekday() not in rules["weekdays"]:
            continue
        for h in rules["hours"]:
            slot = day.replace(hour=h)
            if slot.isoformat(timespec="minutes") not in booked:
                out.append(slot)
                break  # one slot per day spreads the options
        if len(out) == n:
            break
    return out


def format_slot(slot: datetime) -> str:
    return f"יום {HE_DAYS[slot.weekday()]} {slot:%d.%m} בשעה {slot:%H:%M}"


def slots_message(slots: list[datetime]) -> str:
    lines = [f"{i}. {format_slot(s)}" for i, s in enumerate(slots, 1)]
    return "מעולה! אלה המועדים הפנויים:\n" + "\n".join(lines) + "\nהשיבו במספר האפשרות."
