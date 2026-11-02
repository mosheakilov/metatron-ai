"""Outreach Writer agent: drafts the first message and answers to questions.

Every draft goes to the broker's approval queue. Nothing here sends a message.
"""

from __future__ import annotations

from metatron.config import Config

OPT_OUT_LINE = 'להסרה השיבו "הסר".'

SYSTEM = (
    "You are the Outreach Writer of a solo Israeli real-estate broker. Write short, warm, "
    "honest WhatsApp messages in Hebrew to private sellers. Goal: ask for a 30-minute meeting at "
    "the property. Never promise a price or a sale time. Never pretend to be a buyer. Mention one "
    "concrete detail of the listing. At most 3 short sentences plus the sign-off. "
    f'Always end with the exact line: {OPT_OUT_LINE}'
)
NO_OPT_OUT = ("Do not add any opt-out or unsubscribe line; the broker chose to send the message "
              "without one.")


def opt_out_enabled(cfg: Config | None) -> bool:
    """The broker decides whether messages carry the opt-out line (default: yes).

    "הסר" in a reply is honoured either way: the number is blocked for good.
    """
    return cfg is None or bool(cfg["outreach"].get("include_opt_out", True))


def _system(cfg: Config) -> str:
    return SYSTEM if opt_out_enabled(cfg) else SYSTEM.split("Always end with")[0] + NO_OPT_OUT


def _signature(cfg: Config) -> str:
    o = cfg["outreach"]
    name = o.get("broker_name")
    return f"{name}, {o['office_name']}" if name else o["office_name"]


def _ensure_opt_out(text: str, cfg: Config | None = None) -> str:
    text = text.strip()
    if not opt_out_enabled(cfg):
        return text
    return text if OPT_OUT_LINE in text else f"{text}\n{OPT_OUT_LINE}"


def render_template(template: str, seller: dict, cfg: Config) -> str:
    """The broker's own opening message. Placeholders: {שם} {חתימה} {נכס} {עיר}."""
    first = (seller.get("name") or "").split(" ")[0]
    place = ", ".join(x for x in (seller.get("address"), seller.get("city")) if x)
    values = {"שם": first, "חתימה": _signature(cfg), "עיר": seller.get("city") or "",
              "נכס": f"הנכס ב{place}" if place else "הנכס שלך"}
    text = template
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return _ensure_opt_out(text.replace("שלום ,", "שלום,").replace("  ", " "), cfg)


def template_outreach(seller: dict, cfg: Config) -> str:
    if cfg["outreach"].get("template"):
        return render_template(cfg["outreach"]["template"], seller, cfg)
    first = (seller.get("name") or "").split(" ")[0]
    rooms = seller.get("rooms")
    rooms_txt = f"{rooms:g} חדרים" if isinstance(rooms, int | float) else "הדירה"
    days = seller.get("days_on_market") or 0
    hook = ("המודעה כבר זמן מה באוויר, ויש לי כמה רעיונות שיכולים לקדם אותה."
            if days >= 45 else "המשרד שלנו פעיל באזור, ואשמח להכיר את הנכס.")
    return _ensure_opt_out(
        f"שלום {first}, כאן {_signature(cfg)}.\n"
        f"ראיתי את המודעה על {rooms_txt} ב{seller.get('address', '')}, {seller.get('city', '')}. "
        f"{hook}\n"
        "אפשר לקבוע פגישה קצרה של חצי שעה בנכס?", cfg
    )


def template_answer(question: str, cfg: Config) -> str:
    return _ensure_opt_out(
        "שאלה טובה, תודה. את כל הפרטים (כולל תנאי העבודה והעמלה) אשמח לפרט בפגישה קצרה בנכס, "
        "בלי שום התחייבות. מתאים לך שאציע כמה מועדים?\n"
        f"{_signature(cfg)}", cfg
    )


def draft_outreach(seller: dict, cfg: Config, llm=None) -> str:
    if llm is None:
        return template_outreach(seller, cfg)
    facts = {k: seller.get(k) for k in ("name", "city", "address", "rooms", "asking_price",
                                         "days_on_market", "price_drops")}
    guide = cfg["outreach"].get("template")
    style = (f"The broker's own template (keep its intent and facts, personalise it, and never "
             f"claim you saw an ad unless the notes say so):\n{render_template(guide, seller, cfg)}\n"
             if guide else "")
    prompt = (f"{_system(cfg)}\n\nSeller facts: {facts}\nBroker notes: {seller.get('notes') or '-'}\n"
              f"{style}Sign the message as: {_signature(cfg)}\nReturn only the message text.")
    try:
        return _ensure_opt_out(llm.call(messages=[{"role": "user", "content": prompt}]), cfg)
    except Exception:
        return template_outreach(seller, cfg)


def draft_answer(question: str, history: list[dict], cfg: Config, llm=None) -> str:
    if llm is None:
        return template_answer(question, cfg)
    convo = "\n".join(f"{'Seller' if m['direction'] == 'in' else 'Broker'}: {m['body']}"
                      for m in history[-8:])
    prompt = (f"{_system(cfg)}\n\nConversation so far:\n{convo}\n\nThe seller asked: {question}\n"
              "Answer briefly and honestly. If it is about commission or price, say the broker "
              "will explain at the meeting. Offer to propose meeting times.\n"
              f"Sign as: {_signature(cfg)}\nReturn only the message text.")
    try:
        return _ensure_opt_out(llm.call(messages=[{"role": "user", "content": prompt}]), cfg)
    except Exception:
        return template_answer(question, cfg)
