import io
import math
import re
import pandas as pd
import streamlit as st

# --------------------------- App Config ------------------------------------
st.set_page_config(page_title="Espresso Advisor", page_icon="☕", layout="wide")

# --------------------------- Helpers ---------------------------------------
def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "bean"

def parse_float(x):
    try:
        if x is None: return None
        if isinstance(x, (int, float)): return float(x)
        x = str(x).replace(",", ".").strip()
        return float(x) if x != "" else None
    except Exception:
        return None

def rec_dose(shot_type: str):
    return 9.0 if shot_type == "Single" else 18.0 if shot_type == "Double" else None

def recommend(ratio, time_sec, target_out):
    has_r = ratio is not None and math.isfinite(ratio)
    has_t = time_sec is not None and math.isfinite(time_sec)
    if has_r and has_t and 1.8 <= ratio <= 2.2 and 25 <= time_sec <= 30:
        return ("✅ God ekstraktion – behold indstillingerne.", "good")
    if (has_t and time_sec < 25) or (has_r and ratio > 2.2):
        return (f"Underekstraheret → Mal finere (lavere tal) og/eller stop ved {round(target_out)} g.", "under")
    if (has_t and time_sec > 30) or (has_r and ratio < 1.8):
        return (f"Overekstraheret → Mal grovere (højere tal). Hold dig til {round(target_out)} g.", "over")
    return (f"Juster småt: sigt efter 25–30 sek og {round(target_out)} g.", "neutral")

PROCESS_CHOICES = ["Washed","Natural","Honey","Anaerob","CM","Giling Basah","Wet-Hulled","Andet"]

# --------------------------- State -----------------------------------------
if "beans" not in st.session_state:
    st.session_state.beans = {}  # bean_id -> {brand,name,process,target_ratio,entries:[...]}
if "current_bean" not in st.session_state:
    st.session_state.current_bean = None

beans = st.session_state.beans

# --------------------------- UI: Header ------------------------------------
st.title("Espresso Advisor – bønne‑mapper & log")
st.caption("Mobilvenlig: vælg aktiv bønne, log dine shots og få anbefalinger.")

# --------------------------- UI: Bean selector / creator --------------------
left, right = st.columns([1,1])
with left:
    if beans:
        options = ["(Vælg bønne)"] + [f"{b['brand']} – {b['name']}" for b in beans.values()]
        sel = st.selectbox("Aktiv bønne", options, index=0, key="k_sel_bean")
        if sel != "(Vælg bønne)":
            # find bean_id by matching
            for bid, b in beans.items():
                if f"{b['brand']} – {b['name']}" == sel:
                    st.session_state.current_bean = bid
                    break
with right:
    with st.expander("➕ Ny bønne", expanded=(not beans)):
        n_brand = st.text_input("Mærke / Risteri", key="k_new_brand")
        n_name = st.text_input("Bønne / Navn", key="k_new_name")
        n_proc = st.selectbox("Proces", PROCESS_CHOICES, index=0, key="k_new_proc")
        n_proc_other = st.text_input("Proces (andet)", disabled=(n_proc!="Andet"), key="k_new_proc_other")
        n_ratio = st.selectbox("Standard target ratio", [1.8,1.9,2.0,2.1,2.2], index=2, key="k_new_ratio")
        if st.button("Opret bønne‑mappe", use_container_width=True, key="k_new_btn"):
            bid = slugify(f"{n_brand}-{n_name}")
            process_val = n_proc_other if (n_proc=="Andet" and n_proc_other) else n_proc
            beans[bid] = {
                "brand": n_brand.strip(),
                "name": n_name.strip(),
                "process": process_val,
                "target_ratio": float(n_ratio),
                "entries": [],
            }
            st.session_state.current_bean = bid
            st.success("Bønne oprettet – klar til log!")

if not st.session_state.current_bean:
    st.info("Vælg en eksisterende bønne i listen eller opret en ny i panelet ‘➕ Ny bønne’.")
    st.stop()

bean = beans[st.session_state.current_bean]
bean_id = st.session_state.current_bean

# --------------------------- Active bean header ----------------------------
box = st.container()
with box:
    c1, c2, c3, c4 = st.columns([2,2,1,1])
    c1.markdown(f"**Mærke:** {bean['brand'] or '—'}")
    c2.markdown(f"**Bønne:** {bean['name'] or '—'}")
    c3.metric("Proces", bean.get("process") or "—")
    # allow per‑bean target ratio tweak
    new_tr = c4.selectbox("Target ratio", [1.8,1.9,2.0,2.1,2.2], index=[1.8,1.9,2.0,2.1,2.2].index(bean.get("target_ratio",2.0)), key=f"k_tr_{bean_id}")
    if new_tr != bean.get("target_ratio", 2.0):
        bean["target_ratio"] = float(new_tr)

st.divider()

# --------------------------- Shot form (mobile‑friendly) -------------------
colA, colB = st.columns(2)
with colA:
    shot_type = st.selectbox("Shot type", ["Double","Single"], index=0, key=f"k_type_{bean_id}")
    grind = st.text_input("Kværn (tal)", placeholder="fx 8", key=f"k_grind_{bean_id}")
    dose = parse_float(st.text_input("Dosis (g ind)", value="", placeholder=str(rec_dose(shot_type) or ""), key=f"k_dose_{bean_id}"))
with colB:
    yield_out = parse_float(st.text_input("Udbytte (g ud)", value="", placeholder="fx 36", key=f"k_yield_{bean_id}"))
    time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", value="", placeholder="fx 27", key=f"k_time_{bean_id}"))
    date_str = st.date_input("Dato", key=f"k_date_{bean_id}")

# Derived numbers
target_ratio = bean.get("target_ratio", 2.0)
if dose is not None:
    target_out = dose * target_ratio
else:
    target_out = (rec_dose(shot_type) or 0) * target_ratio
ratio = (yield_out / dose) if (dose and yield_out) else None
rec_text, rec_kind = recommend(ratio, time_sec, target_out or 0)

m1, m2 = st.columns(2)
with m1:
    st.metric("Mål udbytte (g)", value=(str(int(round(target_out))) if target_out else "—"))
with m2:
    st.metric("Faktisk ratio", value=(f"{ratio:.2f}" if ratio else "—"))

bg = {"good":"#DCFCE7","under":"#FEF3C7","over":"#FECACA","neutral":"#F5F5F4"}.get(rec_kind,"#F5F5F4")
st.markdown(f"<div style='border:1px solid #e5e7eb;background:{bg};padding:12px;border-radius:12px'>{rec_text}</div>", unsafe_allow_html=True)

cSave, cReset = st.columns(2)
with cSave:
    if st.button("Gem shot i aktiv bønne", use_container_width=True, key=f"k_save_{bean_id}"):
        entry = {
            "Dato": str(date_str),
            "Type": shot_type,
            "Kværn": grind,
            "Dosis (g)": dose if dose is not None else "",
            "Udbytte (g)": yield_out if yield_out is not None else "",
            "Tid (sek)": time_sec if time_sec is not None else "",
            "Target ratio": target_ratio,
            "Mål ud (g)": int(round(target_out)) if target_out else "",
            "Faktisk ratio": round(ratio,2) if ratio else "",
            "Anbefaling": rec_text,
        }
        bean["entries"].insert(0, entry)
        st.success("Shot gemt i bønne‑mappen!")
with cReset:
    if st.button("Nulstil felter", use_container_width=True, key=f"k_reset_{bean_id}"):
        for k in [f"k_type_{bean_id}", f"k_grind_{bean_id}", f"k_dose_{bean_id}", f"k_yield_{bean_id}", f"k_time_{bean_id}"]:
            if k in st.session_state: del st.session_state[k]
        st.experimental_rerun()

st.divider()

# --------------------------- Log for this bean ------------------------------
st.subheader("Log for aktiv bønne")
entries = bean.get("entries", [])
if not entries:
    st.info("Ingen shots endnu for denne bønne – udfyld felterne og tryk ‘Gem shot’.")
else:
    df = pd.DataFrame(entries)
    st.dataframe(df, use_container_width=True, hide_index=True)
    # CSV download (per bean)
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    st.download_button(
        label="Download CSV for denne bønne",
        data=csv_buf.getvalue().encode("utf-8-sig"),
        file_name=f"{slugify(bean['brand'])}-{slugify(bean['name'])}-log.csv",
        mime="text/csv",
        key=f"k_dl_{bean_id}"
    )

st.caption("Mobiltip: kolonner stakker automatisk. Sweet spot: ratio 1.8–2.2 og 25–30 sek fra første dråbe.")
