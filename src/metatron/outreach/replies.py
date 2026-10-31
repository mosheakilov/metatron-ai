"""Classify a seller's WhatsApp reply.

Opt-out detection is deterministic and runs FIRST, before any LLM: "הסר" must never depend on a
model's mood. The LLM (or the keyword fallback) only splits the remaining replies into
interested / not_interested / question.
"""

from __future__ import annotations

import json
import re

OPT_OUT = "opt_out"
INTERESTED = "interested"
NOT_INTERESTED = "not_interested"
QUESTION = "question"
LABELS = [OPT_OUT, INTERESTED, NOT_INTERESTED, QUESTION]

_OPT_OUT_PATTERNS = [
    r"הס[י]?ר", r"להסיר", r"תסיר[וי]?", r"הסירו",
    r"תוריד[וי]? אותי", r"להוריד אותי", r"תמחק[וי]? (אותי|את המספר)",
    r"תפסיק[וי]?", r"להפסיק לשלוח", r"(?<!\w)די(?!\w)\s*(כבר|לשלוח|!|$)",
    r"(לא|אל) ל?(פנות|תפנו|להתקשר|תתקשרו|לשלוח|תשלחו)",
    r"\bstop\b", r"\bunsubscribe\b", r"\bremove\b",
]
_OPT_OUT_RE = re.compile("|".join(_OPT_OUT_PATTERNS), re.IGNORECASE)

_NOT_INTERESTED = ["לא מעוניין", "לא מעוניינת", "לא מעונינ", "לא תודה", "לא רלוונטי",
                   "כבר מכרתי", "כבר נמכר", "מוכר לבד", "בלי מתווכים", "לא צריך", "לא צריכה",
                   "אי אפשר"]
_INTERESTED = ["מעוניין", "מעוניינת", "מעונין", "כן", "בשמחה", "אשמח", "בטח", "אוקיי", "אוקי",
               "סבבה", "יאללה", "נקבע", "בוא נדבר", "אפשר", "מתי", "ok", "yes"]
_QUESTION_WORDS = ["כמה", "מה ", "איך", "למה", "מי ", "איפה", "עמלה", "האם"]


def is_opt_out(text: str) -> bool:
    return bool(_OPT_OUT_RE.search(text or ""))


def classify_keywords(text: str) -> str:
    t = (text or "").strip().lower()
    if is_opt_out(t):
        return OPT_OUT
    if any(k in t for k in _NOT_INTERESTED):
        return NOT_INTERESTED
    if "?" in t or any(t.startswith(w.strip()) or f" {w}" in f" {t}" for w in _QUESTION_WORDS):
        # "כן, כמה עמלה?" is still a question we must answer before booking
        return QUESTION
    if any(k in t for k in _INTERESTED):
        return INTERESTED
    return QUESTION  # unclear => a human-approved answer, never a silent guess


def classify(text: str, llm=None) -> str:
    if is_opt_out(text):
        return OPT_OUT
    if llm is None:
        return classify_keywords(text)
    prompt = (
        "You classify a Hebrew WhatsApp reply from a property seller who received a message "
        "from a real-estate broker asking for a short meeting.\n"
        'Return JSON only: {"label": one of ["opt_out","interested","not_interested","question"]}.\n'
        "opt_out = asks to stop / remove / not be contacted. question = asks something or is "
        "unclear.\n\n"
        f"Reply: {text}"
    )
    try:
        raw = llm.call(messages=[{"role": "user", "content": prompt}])
        label = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))["label"]
        return label if label in LABELS else classify_keywords(text)
    except Exception:
        return classify_keywords(text)


def parse_slot_choice(text: str, n_slots: int) -> int | None:
    """'2' / 'אפשרות 2' / 'השני' -> index 1. None if no clear choice."""
    words = {"ראשון": 1, "הראשון": 1, "ראשונה": 1, "שני": 2, "השני": 2, "שנייה": 2, "שניה": 2,
             "שלישי": 3, "השלישי": 3, "שלישית": 3}
    m = re.fullmatch(r"\D*([1-9])\D*", (text or "").strip())
    n = int(m.group(1)) if m else next((v for k, v in words.items() if k in (text or "")), None)
    return n - 1 if n and 1 <= n <= n_slots else None
