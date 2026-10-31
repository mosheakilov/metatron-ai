"""Template writers for insights.md and MODEL_CARD.md in offline mode (no LLM).

In crew mode the Insights Writer and Model Card Writer agents write these files instead,
from the same JSON artifacts.
"""

from __future__ import annotations


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def insights_md(eda: dict, cleaning_log: dict) -> str:
    corr = eda["corr_with_target"]
    pos = [k for k, v in corr.items() if v > 0.05]
    neg = [k for k, v in corr.items() if v < -0.05]
    drops = eda["rate_by_price_drops"]
    src = sorted(eda["rate_by_source"].items(), key=lambda kv: -kv[1]["rate"])
    city = sorted(eda["rate_by_city"].items(), key=lambda kv: -kv[1]["rate"])
    removed = cleaning_log["rows_in"] - cleaning_log["rows_out"]
    lines = [
        "# תובנות מהנתונים",
        "",
        f"- נותחו **{eda['rows']:,}** מוכרים אחרי ניקוי "
        f"(הוסרו {removed:,} שורות מתוך {cleaning_log['rows_in']:,}).",
        f"- שיעור ההסכמה לפגישה הכללי: **{_pct(eda['target_rate'])}**.",
        f"- מאפיינים שקשורים להסכמה גבוהה יותר: {', '.join(pos) or 'אין'}.",
        f"- מאפיינים שקשורים להסכמה נמוכה יותר: {', '.join(neg) or 'אין'}.",
        f"- מוכר בלי הורדות מחיר מסכים ב-{_pct(drops.get('0', {}).get('rate', 0))}, "
        f"ומוכר עם 3 הורדות ב-{_pct(drops.get('3', {}).get('rate', 0))}.",
        f"- המקור עם השיעור הגבוה ביותר: **{src[0][0]}** ({_pct(src[0][1]['rate'])}); "
        f"הנמוך: {src[-1][0]} ({_pct(src[-1][1]['rate'])}).",
        f"- העיר עם השיעור הגבוה ביותר: **{city[0][0]}** ({_pct(city[0][1]['rate'])}).",
        "",
        "## מה זה אומר למתווך",
        "- כדאי לפנות קודם למוכרים שהמודעה שלהם באוויר זמן רב והורידו מחיר: הם מתוסכלים "
        "ופתוחים יותר לעזרה.",
        "- מוכר שמבקש מחיר גבוה מהחציון באזור מתקשה למכור לבד, ולכן פתוח יותר לפגישה.",
        "",
        "> הנתונים **סינתטיים** (אין עדיין תוצאות פנייה אמיתיות). התובנות מדגימות את "
        "התהליך, לא את השוק.",
    ]
    return "\n".join(lines) + "\n"


def model_card_md(metrics: dict, run_info: dict, contract: dict) -> str:
    sel = metrics["selected"]
    rows = []
    for v, m in metrics["versions"].items():
        p_key = next(k for k in m if k.startswith("precision_at_"))
        rows.append(f"| {v}{' ✅' if v == sel else ''} | {m['kind']} | {m['roc_auc']} | "
                    f"{m['pr_auc']} | {m[p_key]} | {m['lift_at_top']} | {m['brier']} | "
                    f"{m['cv_roc_auc_mean']} ± {m['cv_roc_auc_std']} |")
    p_key = next(k for k in metrics["versions"][sel] if k.startswith("precision_at_"))
    top = p_key.removeprefix("precision_at_")
    s = metrics["versions"][sel]
    return f"""# Model Card: Seller Lead Scoring

## What it predicts
`{contract['target']}`: will the seller agree to a recruitment meeting within 14 days of the
first message. Output: probability 0–1, used to **rank** the approval queue. It never sends a
message by itself; the broker approves every message.

## Data
- **Synthetic** dataset (`metatron.data.generate`, seed {run_info['seed']}). There are no real
  outreach outcomes yet. The label comes from a documented probability function plus noise.
- Input file SHA-256: `{run_info['input_sha256'][:16]}…`
- Validated against `data_contract.json` before training ({len(contract['columns'])} columns).

## Versions
| version | model | ROC-AUC | PR-AUC | P@{top}% | lift | Brier | CV ROC-AUC |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

Selected: **{sel}** by `{metrics['selected_by']}`. If the broker contacts only the top {top}%,
about **{s[p_key] * 100:.0f}%** agree to a meeting, versus {s['base_rate'] * 100:.0f}% at random
(lift ×{s['lift_at_top']}).

## Limitations
- Trained on synthetic data: the numbers show the method works, not how real sellers behave.
- Cities outside the training vocabulary fall back to the global median price.
- Not to be used to decide who is *excluded* from service; only to order the work queue.

## Fair use
- Features describe the **listing**, not the person (no age, gender, religion or origin).
- Every contacted seller can reply "הסר" and is never contacted again.

## Path to real data
Every outreach logs its outcome (`log_outcome`). Version 3 will be trained on those real labels
and compared with this card.

## Reproduce
`python -m metatron.train --config config.yaml` with the same input file gives the same metrics.
"""
