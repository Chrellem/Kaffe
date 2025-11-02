import io
import math
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Espresso Advisor", page_icon="☕", layout="wide")

# --- Helpers ---------------------------------------------------------------
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

# --- State -----------------------------------------------------------------
if "rows" not in st.session_state:
    st.session_state.rows = []
if "filter_bean" not in st.session_state:
    st.session_state.filter_bean = "Alle"
if "rows" not in st.session_state:
    st.session_state.rows = []

# --- UI --------------------------------------------------------------------
st.title("Espresso Advisor – Python/Streamlit")
st.caption("Single/Dobbel • ratio, tid og anbefaling • log og CSV‑export")

# Bean meta (mobile-friendly: two columns)
colB1, colB2 = st.columns(2)
with colB1:
    brand = st.text_input("Mærke / Risteri", placeholder="fx La Cabra")
with colB2:
    bean_name = st.text_input("Bønne / Navn", placeholder="fx Caballero #3")

colP1, colP2 = st.columns(2)
with colP1:
    process = st.selectbox("Proces", PROCESS_CHOICES, index=0)
with colP2:
    process_other = st.text_input("Proces (andet)", placeholder="Udfyld hvis valgt 'Andet'" if process=="Andet" else "", disabled=(process!="Andet"))

# Core inputs
col1, col2 = st.columns(2)
with col1:
    date = st.date_input("Dato")
with col2:
    shot_type = st.selectbox("Shot type", ["Double", "Single"], index=0)

c1, c2 = st.columns(2)
with c1:
    grind = st.text_input("Kværn (tal)", placeholder="fx 8")
with c2:
    dose = parse_float(st.text_input("Dosis (g ind)", value="", placeholder=str(rec_dose(shot_type) or "")))

c3, c4 = st.columns(2)
with c3:
    yield_out = parse_float(st.text_input("Udbytte (g ud)", value="", placeholder="fx 36"))
with c4:
    time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", value="", placeholder="fx 27"))

c5, c6 = st.columns(2)
with c5:
    target_ratio = parse_float(st.selectbox("Target ratio", [1.8, 1.9, 2.0, 2.1, 2.2], index=2))
with c6:
    recommended_dose = rec_dose(shot_type)
    st.metric(label="Anbefalet dosis (auto)", value=f"{recommended_dose:.0f} g")

col1, col2 = st.columns(2)
with col1:
    date = st.date_input("Dato")
with col2:
    shot_type = st.selectbox("Shot type", ["Double", "Single"], index=0)

c1, c2, c3 = st.columns(3)
with c1:
    grind = st.text_input("Kværn (tal)", placeholder="fx 8")
with c2:
    dose = parse_float(st.text_input("Dosis (g ind)", value="", placeholder=str(rec_dose(shot_type) or "")))
with c3:
    yield_out = parse_float(st.text_input("Udbytte (g ud)", value="", placeholder="fx 36"))

c4, c5, c6 = st.columns(3)
with c4:
    time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", value="", placeholder="fx 27"))
with c5:
    target_ratio = parse_float(st.selectbox("Target ratio", [1.8, 1.9, 2.0, 2.1, 2.2], index=2))
with c6:
    recommended_dose = rec_dose(shot_type)
    st.metric(label="Anbefalet dosis (auto)", value=f"{recommended_dose:.0f} g")

# Derived values
if dose is not None and target_ratio is not None:
    target_out = dose * target_ratio
elif recommended_dose is not None and target_ratio is not None:
    target_out = recommended_dose * target_ratio
else:
    target_out = None

ratio = (yield_out / dose) if (dose and yield_out) else None

rec_text, rec_kind = recommend(ratio, time_sec, target_out or 0)

colA, colB = st.columns(2)
with colA:
    st.metric("Mål udbytte (g)", value=(str(int(round(target_out))) if target_out else "—"))
with colB:
    st.metric("Faktisk ratio", value=(f"{ratio:.2f}" if ratio else "—"))

# Recommendation box
color = {
    "good": "#DCFCE7",   # green-100
    "under": "#FEF3C7",  # amber-100
    "over": "#FECACA",   # red-200
    "neutral": "#F5F5F4"  # stone-100
}.get(rec_kind, "#F5F5F4")

st.markdown(
    f"""
    <div style='border:1px solid #e5e7eb;background:{color};padding:12px;border-radius:12px;'>
      {rec_text}
    </div>
    """,
    unsafe_allow_html=True,
)(
    f"""
    <div style='border:1px solid #e5e7eb;background:{color};padding:12px;border-radius:12px;'>
      {rec_text}
    </div>
    """,
    unsafe_allow_html=True,
)

# Actions
colX, colY = st.columns([1,1])
with colX:
    if st.button("Gem i log"):
        row = {
            "Dato": str(date),
            "Mærke": brand,
            "Bønne": bean_name,
            "Proces": (process_other if process=="Andet" and process_other else process),
            "Type": shot_type,
            "Kværn": grind,
            "Dosis (g)": dose if dose is not None else "",
            "Udbytte (g)": yield_out if yield_out is not None else "",
            "Tid (sek)": time_sec if time_sec is not None else "",
            "Target ratio": target_ratio if target_ratio is not None else "",
            "Mål ud (g)": int(round(target_out)) if target_out is not None else "",
            "Faktisk ratio": round(ratio, 2) if ratio is not None else "",
            "Anbefaling": rec_text,
        }
        st.session_state.rows.insert(0, row)
        st.success("Gemt!")

with colY:
    if st.button("Ryd formular"):
        st.rerun()

st.divider()

# Log & filter
st.subheader("Log")
# Bean filter (mobile friendly)
beans = ["Alle"]
for r in st.session_state.rows:
    key = f"{r.get('Mærke','')} – {r.get('Bønne','')}".strip(" –")
    if key not in beans:
        beans.append(key)
sel = st.selectbox("Filtrér på bønne", beans, index=0)

if len(st.session_state.rows) == 0:
    st.info("Ingen poster endnu – udfyld felterne og klik ‘Gem i log’.")
else:
    df = pd.DataFrame(st.session_state.rows)
    if sel != "Alle":
        if " – " in sel:
            brand_sel, bean_sel = sel.split(" – ")
            df = df[(df["Mærke"]==brand_sel) & (df["Bønne"]==bean_sel)]
        else:
            df = df[df["Mærke"]==sel]
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Download CSV
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    st.download_button(
        label="Download CSV",
        data=csv_buf.getvalue().encode("utf-8-sig"),
        file_name=f"espresso-log-{pd.Timestamp.today().date()}.csv",
        mime="text/csv",
    )

st.caption("Tip: Single 9→18 g, Double 18→36 g, 25–30 sek fra første dråbe. Standard temp ca. 93 °C.")
