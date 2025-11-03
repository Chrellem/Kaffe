import io
import math
import re
import pandas as pd
import streamlit as st

# --------------------------- App Config ------------------------------------
st.set_page_config(page_title="Espresso Advisor", page_icon="☕", layout="wide")

# =========================== SIMPLE VERSION ================================
# MÅL: så simpelt som muligt
# - Manuel login med et alias (ikke nødvendigvis mail)
# - Opret bønne (brand + navn + proces + target ratio)
# - Vælg tidligere oprettet bønne
# - Log shots for valgt bønne
# - Se historik for valgt bønne
# - Gem alt i Google Sheets (to faner: beans, entries)

# --------------------------- Sheets backend (valgfrit) ----------------------
USE_SHEETS = False
try:
    if "gcp_service_account" in st.secrets and ("gsheet_id" in st.secrets or "gsheet_name" in st.secrets):
        USE_SHEETS = True
except Exception:
    USE_SHEETS = False

if USE_SHEETS:
# ---- Google Sheets: stabil åbning + caching + retry ----
import gspread
from google.oauth2.service_account import Credentials

@st.cache_resource(show_spinner=False)
def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    gc = gspread.authorize(creds)

    sheet_id = (st.secrets.get("gsheet_id") or "").strip()
    if not sheet_id:
        st.error("Mangler 'gsheet_id' i Secrets (kopiér ID mellem /d/ og /edit i URL'en).")
        st.stop()

    # simple retry på 429
    last_err = None
    for i in range(3):
        try:
            sh = gc.open_by_key(sheet_id)
            return gc, sh
        except gspread.exceptions.APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            last_err = (e, code)
            if code == 429 and i < 2:
                time.sleep(1 + i)  # backoff
                continue
            break

    e, code = last_err
    svc = st.secrets["gcp_service_account"].get("client_email", "(service-konto)")
    st.error(f"Kunne ikke åbne arket via ID (HTTP {code or 'ukendt'}). "
             f"Tjek at ID'et er korrekt, og at arket er delt som Editor med {svc}.")
    st.stop()

GC, SH = get_sheet()

def ws(name: str):
    try:
        w = SH.worksheet(name)
    except Exception:
        w = SH.add_worksheet(title=name, rows=1000, cols=20)
    if name == "beans" and len(w.get_all_values()) == 0:
        w.append_row(["user_id","bean_id","brand","name","process","target_ratio"])
    if name == "entries" and len(w.get_all_values()) == 0:
        w.append_row(["user_id","bean_id","date","type","grind","dose","yield",
                      "time","target_ratio","target_out","ratio","advice","notes"])
    return w

WS_BEANS = ws("beans")
WS_ENTRIES = ws("entries")


# --------------------------- Helpers ---------------------------------------
PROCESS_CHOICES = ["Washed","Natural","Honey","Anaerob","CM","Giling Basah","Wet-Hulled","Andet"]

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
    has_r = ratio is not None and ratio == ratio
    has_t = time_sec is not None and time_sec == time_sec
    if has_r and has_t and 1.8 <= ratio <= 2.2 and 25 <= time_sec <= 30:
        return "✅ God ekstraktion – behold indstillingerne.", "good"
    if (has_t and time_sec < 25) or (has_r and ratio > 2.2):
        return f"Underekstraheret → Mal finere (lavere tal) og/eller stop ved {round(target_out)} g.", "under"
    if (has_t and time_sec > 30) or (has_r and ratio < 1.8):
        return f"Overekstraheret → Mal grovere (højere tal). Hold dig til {round(target_out)} g.", "over"
    return f"Juster småt: sigt efter 25–30 sek og {round(target_out)} g.", "neutral"

# --------------------------- Sheets I/O ------------------------------------
if USE_SHEETS:
    def load_user_data(user_id: str):
        beans: dict[str, dict] = {}
        for row in WS_BEANS.get_all_records():
            if row.get("user_id") == user_id:
                bid = row["bean_id"]
                beans[bid] = {
                    "brand": row.get("brand",""),
                    "name": row.get("name",""),
                    "process": row.get("process",""),
                    "target_ratio": float(row.get("target_ratio", 2.0)),
                    "entries": [],
                }
        if beans:
            for row in WS_ENTRIES.get_all_records():
                if row.get("user_id") == user_id and row.get("bean_id") in beans:
                    beans[row["bean_id"]]["entries"].append({
                        "Dato": row.get("date",""),
                        "Type": row.get("type",""),
                        "Kværn": row.get("grind",""),
                        "Dosis (g)": row.get("dose",""),
                        "Udbytte (g)": row.get("yield",""),
                        "Tid (sek)": row.get("time",""),
                        "Target ratio": row.get("target_ratio",""),
                        "Mål ud (g)": row.get("target_out",""),
                        "Faktisk ratio": row.get("ratio",""),
                        "Anbefaling": row.get("advice",""),
                    })
        return beans

    def upsert_bean(user_id: str, bean_id: str, bean: dict):
        rows = WS_BEANS.get_all_values()
        if rows:
            for idx, r in enumerate(rows[1:], start=2):
                if len(r) >= 2 and r[0] == user_id and r[1] == bean_id:
                    WS_BEANS.update(f"A{idx}:F{idx}", [[user_id, bean_id, bean.get('brand',''), bean.get('name',''), bean.get('process',''), bean.get('target_ratio',2.0)]])
                    return
        WS_BEANS.append_row([user_id, bean_id, bean.get('brand',''), bean.get('name',''), bean.get('process',''), bean.get('target_ratio',2.0)])

    def append_entry(user_id: str, bean_id: str, entry: dict):
        WS_ENTRIES.append_row([
            user_id, bean_id, entry.get("Dato",""), entry.get("Type",""), entry.get("Kværn",""),
            entry.get("Dosis (g)",""), entry.get("Udbytte (g)",""), entry.get("Tid (sek)",""),
            entry.get("Target ratio",""), entry.get("Mål ud (g)",""), entry.get("Faktisk ratio",""), entry.get("Anbefaling",""),
        ])

# --------------------------- State -----------------------------------------
if "user_id" not in st.session_state:
    st.session_state.user_id = ""
if "beans" not in st.session_state:
    st.session_state.beans = {}
if "current_bean" not in st.session_state:
    st.session_state.current_bean = None

# --------------------------- Login -----------------------------------------
st.title("Espresso Advisor – simpel log")

if not st.session_state.user_id:
    st.markdown("### Log ind")
    st.caption("Skriv et brugernavn/alias. Dine bønner og shots gemmes under dette ID.")
    user_input = st.text_input("Bruger-ID", placeholder="fx jonas_home")
    if st.button("Log ind", type="primary"):
        uid = (user_input or "").strip()
        if uid:
            st.session_state.user_id = uid
            if USE_SHEETS:
                st.session_state.beans = load_user_data(uid)
            st.stop()
        else:
            st.warning("Indtast et Bruger-ID for at fortsætte.")
    st.stop()

USER_ID = st.session_state.user_id
beans = st.session_state.beans

# --------------------------- Bean vælger / opret ---------------------------
left, right = st.columns([1,1])
with left:
    if beans:
        labels = [f"{b['brand']} – {b['name']}" for b in beans.values()]
        options = ["(Vælg bønne)"] + labels

        # Forvælg aktuelt valg hvis muligt
        cur_label = "(Vælg bønne)"
        if st.session_state.current_bean in beans:
            bcur = beans[st.session_state.current_bean]
            cur_label = f"{bcur['brand']} – {bcur['name']}"
        idx = options.index(cur_label) if cur_label in options else 0

        sel = st.selectbox("Aktiv bønne", options, index=idx)
        if sel != "(Vælg bønne)":
            for bid, b in beans.items():
                if f"{b['brand']} – {b['name']}" == sel:
                    st.session_state.current_bean = bid
                    break
with right:
    with st.expander("➕ Ny bønne", expanded=(not beans)):
        n_brand = st.text_input("Mærke / Risteri", key="k_new_brand")
        n_name = st.text_input("Bønne / Navn", key="k_new_name")
        n_proc = st.selectbox("Proces", PROCESS_CHOICES, index=0, key="k_new_proc")
        n_ratio = st.selectbox("Target ratio", [1.8,1.9,2.0,2.1,2.2], index=2, key="k_new_ratio")
        if st.button("Opret bønne", key="k_new_btn_create"):
            bid = slugify(f"{n_brand}-{n_name}")
            beans[bid] = {
                "brand": (n_brand or "").strip(),
                "name": (n_name or "").strip(),
                "process": n_proc,
                "target_ratio": float(n_ratio),
                "entries": [],
            }
            # Sæt aktiv bønne og sørg for lokal state
            st.session_state.current_bean = bid
            if "beans" not in st.session_state:
                st.session_state.beans = {}
            st.session_state.beans[bid] = beans[bid]
            # Gem i Sheets hvis aktiveret
            if USE_SHEETS:
                upsert_bean(USER_ID, bid, beans[bid])
            st.success("Bønne oprettet! Klar til at logge shots.")
st.session_state.user_id = USER_ID
st.session_state.current_bean = bid
# Re-render straks så formular og historik vises
try:
    st.rerun()
except Exception:
    st.experimental_rerun()

if not st.session_state.current_bean:
    st.info("Vælg en eksisterende bønne eller opret en ny.")
    st.stop()

bean_id = st.session_state.current_bean
bean = beans.get(bean_id)
if not bean:
    st.warning("Den valgte bønne findes ikke længere. Vælg en anden eller opret en ny.")
    st.session_state.current_bean = None
    st.stop()

# --------------------------- Aktiv bønne header ----------------------------
colA, colB, colC = st.columns([2,2,1])
colA.markdown(f"**Mærke:** {bean['brand'] or '—'}")
colB.markdown(f"**Bønne:** {bean['name'] or '—'}")
colC.metric("Proces", bean.get("process") or "—")

# --------------------------- Shot form -------------------------------------
form1 = st.container()
with form1:
    c1, c2 = st.columns(2)
    with c1:
        shot_type = st.selectbox("Shot type", ["Double","Single"], index=0)
        grind = st.text_input("Kværn (tal)", placeholder="fx 8")
        dose = parse_float(st.text_input("Dosis (g ind)", placeholder=str(rec_dose(shot_type) or "")))
    with c2:
        yield_out = parse_float(st.text_input("Udbytte (g ud)", placeholder="fx 36"))
        time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", placeholder="fx 27"))
        date_str = st.date_input("Dato")
    note = st.text_input("Noter (valgfri)", placeholder="Smagsnoter, mælketekstur, vand…")

    target_ratio = bean.get("target_ratio", 2.0)
    target_out = (dose * target_ratio) if dose is not None else (rec_dose(shot_type) or 0) * target_ratio
    ratio = (yield_out / dose) if (dose and yield_out) else None
    advice, kind = recommend(ratio, time_sec, target_out or 0)

    m1, m2 = st.columns(2)
    m1.metric("Mål udbytte (g)", value=(str(int(round(target_out))) if target_out else "—"))
    m2.metric("Faktisk ratio", value=(f"{ratio:.2f}" if ratio else "—"))

    bg = {"good":"#DCFCE7","under":"#FEF3C7","over":"#FECACA","neutral":"#F5F5F4"}.get(kind,"#F5F5F4")
    st.markdown(f"<div style='border:1px solid #e5e7eb;background:{bg};padding:12px;border-radius:12px'>{advice}</div>", unsafe_allow_html=True)

    colS, colR = st.columns(2)
    with colS:
        if st.button("Gem shot i aktiv bønne", use_container_width=True):
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
                "Anbefaling": advice,
                "Noter": note or "",
            }
            bean.setdefault("entries", []).insert(0, entry)
            if USE_SHEETS:
                upsert_bean(USER_ID, bean_id, bean)
                # Udvidet schema: tilføj "notes" som sidste kolonne
                try:
                    append_entry(USER_ID, bean_id, entry)
                except Exception:
                    pass
            st.success("✅ Shot gemt!")
# Bevar kontekst og re-render, så loggen opdateres
st.session_state.user_id = USER_ID
st.session_state.current_bean = bean_id
try:
    st.rerun()
except Exception:
    st.experimental_rerun()
    with colR:
        if st.button("Nulstil felter", use_container_width=True):
            st.stop()

# --------------------------- Historik --------------------------------------
st.subheader("Historik for valgt bønne")
entries = bean.get("entries", [])
if USE_SHEETS and USER_ID and not entries:
    # hent igen fra Sheets (fx efter ny deploy)
    st.session_state.beans = load_user_data(USER_ID)
    bean = st.session_state.beans.get(bean_id, bean)
    entries = bean.get("entries", [])

# Kontrolleret visning til mobil: kort eller tabel
view = st.segmented_control("Visning", options=["Kort", "Tabel"], default="Kort") if hasattr(st, 'segmented_control') else st.radio("Visning", ["Kort","Tabel"], horizontal=True)
limit_opt = st.selectbox("Antal viste", [5,10,25,50,"Alle"], index=1)

# Sortér nyeste først (Dato er string; stoler på kronologi fra input) – alternativt kunne man parse
data = entries[:]

if limit_opt != "Alle":
    data = data[: int(limit_opt)]

if not data:
    st.info("Ingen shots endnu – gem et shot for at se historik.")
else:
    if view == "Tabel":
        import pandas as pd
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        # Kortvisning – mobilvenlig
        for i, r in enumerate(data):
            st.markdown(
                f"""
                <div style='border:1px solid #e5e7eb;border-radius:12px;padding:12px;margin-bottom:8px'>
                  <div style='display:flex;justify-content:space-between;gap:12px;'>
                    <b>{r.get('Dato','')}</b>
                    <span>{r.get('Type','')} • kværn {r.get('Kværn','')}</span>
                  </div>
                  <div style='margin-top:6px;display:flex;flex-wrap:wrap;gap:12px;'>
                    <span>Ind: <b>{r.get('Dosis (g)','')}</b> g</span>
                    <span>Ud: <b>{r.get('Udbytte (g)','')}</b> g</span>
                    <span>Tid: <b>{r.get('Tid (sek)','')}</b> s</span>
                    <span>Ratio: <b>{r.get('Faktisk ratio','')}</b></span>
                  </div>
                  <div style='margin-top:6px;'>
                    <i>{r.get('Anbefaling','')}</i>
                  </div>
                  {('<div style="margin-top:6px;color:#374151;">📝 ' + r.get('Noter','') + '</div>') if r.get('Noter') else ''}
                </div>
                """,
                unsafe_allow_html=True,
            )
st.subheader("Historik for valgt bønne")
entries = bean.get("entries", [])
if USE_SHEETS and USER_ID and not entries:
    # hent igen fra Sheets (fx efter ny deploy)
    st.session_state.beans = load_user_data(USER_ID)
    bean = st.session_state.beans.get(bean_id, bean)
    entries = bean.get("entries", [])

if not entries:
    st.info("Ingen shots endnu – gem et shot for at se historik.")
else:
    df = pd.DataFrame(entries)
    st.dataframe(df, use_container_width=True, hide_index=True)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(
        label="Download CSV",
        data=buf.getvalue().encode("utf-8-sig"),
        file_name=f"{bean['brand']}-{bean['name']}-log.csv",
        mime="text/csv",
    )

st.caption("Simpel version: login → vælg/opret bønne → log shot → se historik. Ratio sweet spot 1.8–2.2 og 25–30 sek.")
