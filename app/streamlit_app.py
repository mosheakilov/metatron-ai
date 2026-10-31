"""METATRON broker console (Streamlit).

    streamlit run app/streamlit_app.py

Screens: data · model · approval queue · conversations · calendar.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from metatron.config import load_config
from metatron.flows.outreach_flow import run_event
from metatron.flows.training_flow import run_training
from metatron.llm import use_llm
from metatron.outreach.scoring import latest_run, score_file
from metatron.outreach.store import Store

st.set_page_config(page_title="METATRON", page_icon="🏠", layout="wide")

STATUS_HE = {
    "scored": "דורג", "awaiting_approval": "ממתין לאישור", "sent": "נשלח", "rejected": "נדחה",
    "in_conversation": "בשיחה", "slots_offered": "הוצעו מועדים", "booked": "נקבעה פגישה",
    "not_interested": "לא מעוניין", "opted_out": "הסר",
}

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;600;800&display=swap"
      rel="stylesheet">
<style>
  html, body, [class*="css"], .stMarkdown, .stTextArea textarea, .stButton button,
  .stTabs button, .stDataFrame, input, label { font-family: 'Heebo', sans-serif !important; }
  .main .block-container { direction: rtl; text-align: right; }
  .stTextArea textarea { direction: rtl; text-align: right; }
  h1, h2, h3 { font-weight: 800; color: #14213d; }
  .pill { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.8rem;
          font-weight:600; margin-inline-start:6px; }
  .ok { background:#e3f4ec; color:#1e7a50; } .bad { background:#fde8e8; color:#b42318; }
  .gold { background:#fbf3dc; color:#8a6a12; } .muted { background:#eef1f6; color:#4a5568; }
  .bubble { padding:8px 12px; border-radius:12px; margin:4px 0; max-width:75%;
            white-space:pre-wrap; line-height:1.5; }
  .out { background:#dcf8c6; margin-left:auto; } .in { background:#f1f3f6; margin-right:auto; }
  .meta { font-size:.72rem; color:#6b7280; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_cfg():
    return load_config()


@st.cache_resource
def get_store():
    cfg = get_cfg()
    return Store(cfg.path(cfg["outreach"]["db_path"]))


cfg, store = get_cfg(), get_store()


def pill(text: str, kind: str = "muted") -> str:
    return f'<span class="pill {kind}">{text}</span>'


def save_upload(upload) -> Path:
    suffix = Path(upload.name).suffix
    tmp = Path(tempfile.mkdtemp()) / f"upload{suffix}"
    tmp.write_bytes(upload.getvalue())
    return tmp


def runs_list() -> list[Path]:
    d = cfg.path(cfg["runs_dir"])
    return sorted([p for p in d.glob("*") if (p / "run.json").exists()], reverse=True) \
        if d.exists() else []


# ---- header -------------------------------------------------------------------------------
st.markdown("# METATRON " + pill("זרימת גיוס", "gold"), unsafe_allow_html=True)
with st.sidebar:
    st.markdown("### מצב מערכת")
    st.markdown("סוכנים: " + (pill("CrewAI + LLM", "ok") if use_llm(cfg)
                              else pill("Offline (דטרמיניסטי)", "muted")), unsafe_allow_html=True)
    ch = cfg["outreach"]["channel"]
    st.markdown("ערוץ: " + (pill("WhatsApp אמיתי", "gold") if ch == "whatsapp"
                            else pill("סימולציה", "muted")), unsafe_allow_html=True)
    st.markdown("יומן: " + pill(cfg["calendar"]["backend"]), unsafe_allow_html=True)
    if ch == "whatsapp":
        st.caption("שליחה רק למספרים ב-allowed_numbers: " +
                   ", ".join(cfg["outreach"]["allowed_numbers"]) or "—")
    st.divider()
    if st.button("איפוס נתוני הדגמה (פנייה)", help="מוחק מוכרים, הודעות ופגישות. לא נוגע במודלים."):
        for t in ["messages", "sellers", "opt_outs", "meetings", "outcomes", "events"]:
            store.x(f"DELETE FROM {t}")
        st.rerun()

tab_data, tab_model, tab_queue, tab_chat, tab_cal = st.tabs(
    ["1 · נתונים", "2 · מודל", "3 · תור אישור", "4 · שיחות", "5 · יומן"])

# ---- 1. data -------------------------------------------------------------------------------
with tab_data:
    st.subheader("ייבוא קובץ ואימון (TrainingFlow)")
    c1, c2 = st.columns([2, 1])
    with c1:
        upload = st.file_uploader("קובץ מוכרים עם תוצאות עבר (CSV / Excel)",
                                  type=["csv", "xlsx"], key="train_upload")
    with c2:
        st.caption("בלי קובץ: משתמשים בקובץ הסינתטי מ-config.yaml")
        go = st.button("▶ הרץ צוות נתונים + צוות מודל", type="primary")
    if go:
        path = save_upload(upload) if upload else cfg.path(cfg["data"]["raw_path"])
        with st.spinner("הסוכנים עובדים…"):
            state = run_training(path, cfg)
        st.session_state["last_run"] = state.run_dir
        if state.status == "trained":
            st.success(f"החוזה תקין ✓ · המודל אומן · נבחר {state.selected}")
        else:
            st.error("ה-Flow נעצר: הנתונים לא עומדים בחוזה. שום מודל לא אומן.")

    runs = runs_list()
    if runs:
        default = Path(st.session_state.get("last_run", runs[0]))
        idx = next((i for i, r in enumerate(runs) if r == default), 0)
        run = st.selectbox("הרצה", runs, index=idx, format_func=lambda p: p.name, key="data_run")
        info = json.loads((run / "run.json").read_text(encoding="utf-8"))
        rep_path = run / "validation_report.json"
        if rep_path.exists():
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            if rep["valid"]:
                st.markdown(f"### חוזה נתונים {pill(f'ירוק · {rep['n_checks']} בדיקות עברו', 'ok')}",
                            unsafe_allow_html=True)
            else:
                st.markdown(f"### חוזה נתונים {pill(f'אדום · {rep['n_failed']} נכשלו', 'bad')}",
                            unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(rep["errors"])[["check", "detail", "fix"]]
                             .rename(columns={"check": "בדיקה", "detail": "מה נמצא",
                                              "fix": "איך מתקנים"}),
                             width="stretch", hide_index=True)
        st.caption(f"קובץ: {Path(info['input_file']).name} · SHA-256 {info['input_sha256'][:12]}… · "
                   f"seed {info['seed']} · סטטוס {info.get('status', '?')}")
        if (run / "cleaning_log.json").exists():
            log = json.loads((run / "cleaning_log.json").read_text(encoding="utf-8"))
            with st.expander(f"לוג ניקוי · {log['rows_in']:,} → {log['rows_out']:,} שורות"):
                st.dataframe(pd.DataFrame(log["steps"]).astype("string").fillna(""), hide_index=True,
                             width="stretch")
        if (run / "insights.md").exists():
            st.markdown((run / "insights.md").read_text(encoding="utf-8"))
        charts = sorted((run / "eda").glob("*.png")) if (run / "eda").exists() else []
        cols = st.columns(2)
        for i, c in enumerate(charts):
            cols[i % 2].image(str(c), width="stretch")
    else:
        st.info("עוד אין הרצות. לחצו על הכפתור כדי להריץ את ה-TrainingFlow.")

# ---- 2. model ------------------------------------------------------------------------------
with tab_model:
    trained = [r for r in runs_list() if (r / "metrics.json").exists()]
    if not trained:
        st.info("עוד אין מודל מאומן.")
    else:
        run = st.selectbox("הרצה", trained, format_func=lambda p: p.name, key="model_run")
        m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
        sel = m["selected"]
        st.markdown(f"### השוואת גרסאות {pill(f'נבחר: {sel}', 'ok')}", unsafe_allow_html=True)
        rows = []
        for v, x in m["versions"].items():
            p_key = next(k for k in x if k.startswith("precision_at_"))
            rows.append({"גרסה": v, "מודל": x["kind"], "ROC-AUC": x["roc_auc"], "PR-AUC": x["pr_auc"],
                         f"Precision@{p_key.split('_')[-1]}%": x[p_key], "Lift": x["lift_at_top"],
                         "Brier": x["brier"],
                         "CV ROC-AUC": f"{x['cv_roc_auc_mean']} ± {x['cv_roc_auc_std']}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        x = m["versions"][sel]
        p_key = next(k for k in x if k.startswith("precision_at_"))
        c1, c2, c3 = st.columns(3)
        c1.metric("פונים ל-20% העליונים: מסכימים", f"{x[p_key] * 100:.0f}%")
        c2.metric("פנייה אקראית: מסכימים", f"{x['base_rate'] * 100:.0f}%")
        c3.metric("פי כמה יותר טוב", f"×{x['lift_at_top']}")
        cal = pd.DataFrame(x["calibration"])
        st.markdown("**כיול (חזוי מול בפועל)**")
        st.line_chart(cal.set_index("predicted")[["actual"]], height=220)
        if (run / "MODEL_CARD.md").exists():
            with st.expander("Model Card", expanded=True):
                st.markdown((run / "MODEL_CARD.md").read_text(encoding="utf-8"))

# ---- 3. approval queue ---------------------------------------------------------------------
with tab_queue:
    st.subheader("דירוג מוכרים חדשים ואישור הודעות")
    c1, c2 = st.columns([2, 1])
    with c1:
        new = st.file_uploader("קובץ מוכרים חדשים לדירוג (בלי תוצאות)", type=["csv", "xlsx"],
                               key="score_upload")
    with c2:
        st.caption("בלי קובץ: data/raw/new_sellers.csv")
        if st.button("דרג עם המודל הנבחר"):
            try:
                path = save_upload(new) if new else cfg.path("data/raw/new_sellers.csv")
                res = score_file(path, cfg, store, latest_run(cfg))
                st.success(f"דורגו {res['n']} מוכרים · מודל {res['model_version']} · "
                           f"הרצה {res['run_id']}")
            except FileNotFoundError as e:
                st.error(str(e))

    scored = store.sellers("scored", limit=50)
    if scored:
        st.markdown("**מוכרים מדורגים שעוד לא פנינו אליהם**")
        df = pd.DataFrame(scored)[["rank", "seller_id", "name", "city", "address", "rooms",
                                   "asking_price", "days_on_market", "price_drops", "score"]]
        st.dataframe(df, hide_index=True, width="stretch", height=240)
        c1, c2 = st.columns([1, 3])
        n = c1.number_input("כמה מהעליונים לנסח", 1, 20, 3)
        if c2.button(f"✍ נסח הודעות ל-{n} המוכרים העליונים"):
            with st.spinner("סוכן הניסוח כותב…"):
                for s in scored[:n]:
                    run_event(store, cfg, event="draft", seller_id=s["seller_id"])
            st.rerun()

    drafts = store.pending_drafts()
    st.markdown(f"### ממתינות לאישור {pill(str(len(drafts)), 'gold')}", unsafe_allow_html=True)
    if not drafts:
        st.caption("אין הודעות שממתינות. שום הודעה לא יוצאת בלי אישור שלך.")
    for d in drafts:
        with st.container(border=True):
            kind = "פנייה ראשונה" if d["kind"] == "outreach" else "תשובה לשאלה"
            st.markdown(f"**#{d['rank']} · {d['name']}** · {d['city']}, {d['address']} · "
                        f"{d['rooms']:g} חד' · ₪{d['asking_price']:,} "
                        f"{pill(f'ציון {d['score']:.2f}', 'ok')}{pill(kind)}",
                        unsafe_allow_html=True)
            body = st.text_area("ההודעה (אפשר לערוך)", d["body"], key=f"body_{d['message_id']}",
                                height=130)
            c1, c2, c3 = st.columns([1, 1, 3])
            if cfg["outreach"]["channel"] == "whatsapp":
                phone = c3.text_input("טלפון (להדגמה: מספר שלך)", d["phone"],
                                      key=f"phone_{d['message_id']}")
                if phone != d["phone"]:
                    store.set_phone(d["seller_id"], phone)
            if c1.button("✅ אשר ושלח", key=f"ok_{d['message_id']}", type="primary"):
                st_ = run_event(store, cfg, event="approve", seller_id=d["seller_id"],
                                message_id=d["message_id"],
                                edited_body=body if body != d["body"] else None)
                (st.toast if st_.result == "sent" else st.warning)(f"תוצאה: {st_.result}")
                st.rerun()
            if c2.button("✖ דחה", key=f"no_{d['message_id']}"):
                run_event(store, cfg, event="reject", seller_id=d["seller_id"],
                          message_id=d["message_id"])
                st.rerun()

# ---- 4. conversations ----------------------------------------------------------------------
with tab_chat:
    active = store.q("SELECT * FROM sellers WHERE status NOT IN ('scored') ORDER BY updated_at DESC")
    left, right = st.columns([1, 2])
    with left:
        st.markdown("**שיחות**")
        if not active:
            st.caption("עוד אין שיחות.")
        sid = st.radio("מוכר", [s["seller_id"] for s in active], label_visibility="collapsed",
                       format_func=lambda i: next(f"{s['name']} · {STATUS_HE.get(s['status'], s['status'])}"
                                                  for s in active if s["seller_id"] == i)) \
            if active else None
        st.markdown(f"**רשימת \"הסר\"** {pill(str(len(store.opt_outs())), 'bad')}",
                    unsafe_allow_html=True)
        oo = store.opt_outs()
        if oo:
            st.dataframe(pd.DataFrame(oo)[["phone", "text", "created_at"]], hide_index=True,
                         width="stretch")
    with right:
        if sid:
            s = store.seller(sid)
            st.markdown(f"### {s['name']} {pill(STATUS_HE.get(s['status'], s['status']))}",
                        unsafe_allow_html=True)
            for msg in store.messages(sid):
                if msg["status"] in ("draft", "rejected"):
                    continue
                side = "out" if msg["direction"] == "out" else "in"
                meta = f"{msg['created_at'][11:16]} · {msg['status']}" + \
                       (f" · {msg['note']}" if msg["note"] else "")
                st.markdown(f'<div class="bubble {side}">{msg["body"]}'
                            f'<div class="meta">{meta}</div></div>', unsafe_allow_html=True)
            if cfg["outreach"]["channel"] == "simulation" and s["status"] not in ("opted_out",
                                                                                   "scored"):
                with st.form(f"sim_{sid}", clear_on_submit=True):
                    text = st.text_input("סימולטור: השב בתור המוכר",
                                         placeholder='למשל: "כן, מעוניין" / "2" / "הסר"')
                    if st.form_submit_button("שלח תשובה") and text:
                        r = run_event(store, cfg, event="reply", seller_id=sid, text=text)
                        st.toast(f"סווג: {r.label} → {r.result}")
                        st.rerun()

# ---- 5. calendar ---------------------------------------------------------------------------
with tab_cal:
    meetings = store.meetings()
    st.markdown(f"### פגישות גיוס {pill(str(len(meetings)), 'ok')}", unsafe_allow_html=True)
    if not meetings:
        st.caption("עוד לא נקבעו פגישות.")
    else:
        df = pd.DataFrame(meetings)
        df["מתי"] = pd.to_datetime(df["start"]).dt.strftime("%a %d.%m %H:%M")
        st.dataframe(df[["מתי", "name", "phone", "address", "external_id"]]
                     .rename(columns={"name": "מוכר", "phone": "טלפון", "address": "כתובת",
                                      "external_id": "nadlan-pro"}),
                     hide_index=True, width="stretch")
    out = store.outcomes()
    if out:
        st.caption(f"תוצאות שנאספו לאימון v3 (log_outcome): {len(out)} · "
                   f"הסכימו {sum(o['agreed_to_meeting'] for o in out)}")
