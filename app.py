import io
import math
import re
import json
import pandas as pd
import streamlit as st

# --------------------------- App Config ------------------------------------
st.set_page_config(page_title="Espresso Advisor", page_icon="☕", layout="wide")

# --------------------------- Optional persistence backends -----------------
USE_SHEETS = False
try:
    if "gcp_service_account" in st.secrets and ("gsheet_id" in st.secrets or "gsheet_name" in st.secrets):
        USE_SHEETS = True
except Exception:
    USE_SHEETS = False

if USE_SHEETS:
    import gspread
    from google.oauth2.service_account import Credentials

    # Kun Sheets‑scope er nødvendigt når vi åbner via ID
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    CREDS = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    GC = gspread.authorize(CREDS)

    # Åbn arket via ID (stabilt). Fald tilbage til navn hvis ID ikke sat.
    if "gsheet_id" in st.secrets and st.secrets["gsheet_id"]:
        SH = GC.open_by_key(st.secrets["gsheet_id"])
    else:
        SH = GC.open(st.secrets["gsheet_name"])  # kræver Drive‑søgning i baggrunden

    def ws(name: str):
        """Hent eller opret worksheet + sørg for headers første gang."""
        try:
            w = SH.worksheet(name)
        except Exception:
            w = SH.add_worksheet(title=name, rows=1000, cols=20)
        # Opret headers hvis tomt
        if name == "beans" and len(w.get_all_values()) == 0:
            w.append_row(["user_id","bean_id","brand","name","process","target_ratio"])
        if name == "entries" and len(w.get_all_values()) == 0:
            w.append_row(["user_id","bean_id","date","type","grind","dose","yield","time","target_ratio","target_out","ratio","advice"])
        if name == "users" and len(w.get_all_values()) == 0:
            w.append_row(["user_id","last_active_bean_id"])  # enkel brugerprofil
        return w

    WS_BEANS = ws("beans")
    WS_ENTRIES = ws("entries")
    WS_USERS = ws("users")
    

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

# --------------------------- Sheets I/O ------------------------------------
if USE_SHEETS:
    def load_from_sheets(user_id: str):
        beans: dict[str, dict] = {}
        # indlæs bønner
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
        # indlæs entries
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

    def upsert_bean_to_sheets(user_id: str, bean_id: str, bean: dict):
        rows = WS_BEANS.get_all_values()
        if rows:
            for idx, r in enumerate(rows[1:], start=2):
                if len(r) >= 2 and r[0] == user_id and r[1] == bean_id:
                    WS_BEANS.update(f"A{idx}:F{idx}", [[user_id, bean_id, bean.get('brand',''), bean.get('name',''), bean.get('process',''), bean.get('target_ratio',2.0)]])
                    return
        WS_BEANS.append_row([user_id, bean_id, bean.get('brand',''), bean.get('name',''), bean.get('process',''), bean.get('target_ratio',2.0)])

    def append_entry_to_sheets(user_id: str, bean_id: str, entry: dict):
        WS_ENTRIES.append_row([
            user_id, bean_id, entry.get("Dato",""), entry.get("Type",""), entry.get("Kværn",""),
            entry.get("Dosis (g)",""), entry.get("Udbytte (g)",""), entry.get("Tid (sek)",""),
            entry.get("Target ratio",""), entry.get("Mål ud (g)",""), entry.get("Faktisk ratio",""), entry.get("Anbefaling",""),
        ])

    def get_user_profile(user_id: str):
        rows = WS_USERS.get_all_records()
        for r in rows:
            if r.get("user_id") == user_id:
                return r
        return None

    def upsert_user_profile(user_id: str, last_active_bean_id: str | None = None):
        rows = WS_USERS.get_all_values()
        if rows:
            for idx, r in enumerate(rows[1:], start=2):
                if len(r) >= 1 and r[0] == user_id:
                    if last_active_bean_id is None:
                        last_active_bean_id = rows[idx-1][1] if len(rows[idx-1])>1 else ""
                    WS_USERS.update(f"A{idx}:B{idx}", [[user_id, last_active_bean_id or ""]])
                    return
        WS_USERS.append_row([user_id, last_active_bean_id or ""]) 

# --------------------------- State ----------------------------------------- -----------------------------------------
if "beans" not in st.session_state:
    st.session_state.beans = {}
if "current_bean" not in st.session_state:
    st.session_state.current_bean = None

# --------------------------- Login (manuel) --------------------------------
st.title("Espresso Advisor – bønne‑mapper & log")

# Prøv at auto-logge ind via URL-parameter ?user=<id>
try:
    qp = st.query_params  # ny API
    user_from_url = qp.get("user", None)
except Exception:
    user_from_url = None
    try:
        user_from_url = st.experimental_get_query_params().get("user", [None])[0]
    except Exception:
        pass

if ("user_id" not in st.session_state or not st.session_state.user_id) and user_from_url:
    st.session_state.user_id = user_from_url
    if USE_SHEETS:
        st.session_state.beans = load_from_sheets(user_from_url)

if "user_id" not in st.session_state or not st.session_state.user_id:
    st.markdown("### Log ind")
    st.caption("Skriv et brugernavn (alias). Alle dine bønner og logs gemmes under dette ID.")
    user_input = st.text_input("Bruger-ID", placeholder="fx kaffe_nord eller jonas_home", key="k_login_user")
    colL, colR = st.columns([1,1])
    with colL:
        if st.button("Log ind", type="primary"):
            uid = (user_input or "").strip()
            if uid:
                st.session_state.user_id = uid
                if USE_SHEETS:
                    st.session_state.beans = load_from_sheets(uid)
                    upsert_user_profile(uid)  # sørg for at bruger findes i users-arket
                # skriv bruger-id i URL så du kan åbne direkte næste gang
                try:
                    st.query_params["user"] = uid
                except Exception:
                    st.experimental_set_query_params(user=uid)
                st.stop()
            else:
                st.warning("Indtast et Bruger-ID for at fortsætte.")
    st.stop()

# efter login
USER_ID = st.session_state.user_id

# topbar med bruger + log ud
top_l, top_r = st.columns([3,1])
with top_l:
    st.caption(f"Logget ind som **{USER_ID}** · dine data synces til Google Sheets")
with top_r:
    if st.button("Log ud"):
        for k in list(st.session_state.keys()):
            if k not in ("beans",):
                del st.session_state[k]
        st.session_state.beans = {}
        st.experimental_rerun()

# indlæs ved login hvis tom lokal state
if USE_SHEETS and USER_ID and not st.session_state.beans:
    st.session_state.beans = load_from_sheets(USER_ID)

beans = st.session_state.beans

st.caption("Mobilvenlig: vælg aktiv bønne, log dine shots og få anbefalinger. Data gemmes pr. bruger.")

# --------------------------- Bean selector / creator ------------------------
left, right = st.columns([1,1])
with left:
    if beans:
        options = ["(Vælg bønne)"] + [f"{b['brand']} – {b['name']}" for b in beans.values()]
        sel = st.selectbox("Aktiv bønne", options, index=0, key="k_sel_bean")
        if sel != "(Vælg bønne)":
            for bid, b in beans.items():
                if f"{b['brand']} – {b['name']}" == sel:
                    st.session_state.current_bean = bid
                    if USE_SHEETS:
                        upsert_user_profile(USER_ID, last_active_bean_id=bid)
                    break
        # hvis ingen valgt men vi har en seneste aktiv i users-arket
        elif USE_SHEETS:
            prof = get_user_profile(USER_ID)
            if prof and prof.get("last_active_bean_id") in beans:
                st.session_state.current_bean = prof["last_active_bean_id"]
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
            if USE_SHEETS:
                upsert_bean_to_sheets(USER_ID, bid, beans[bid])
                upsert_user_profile(USER_ID, last_active_bean_id=bid)
            st.success("Bønne oprettet – klar til log!")

# Sikring: vælg en aktiv bønne hvis den mangler eller ikke længere findes
if (not st.session_state.current_bean) or (st.session_state.current_bean not in beans):
    fallback_id = None
    # 1) prøv users-arket for last_active_bean_id
    if USE_SHEETS:
        prof = get_user_profile(USER_ID)
        if prof and prof.get("last_active_bean_id") in beans:
            fallback_id = prof.get("last_active_bean_id")
    # 2) hvis ingen profil eller ugyldigt id: tag første bønne hvis der findes nogen
    if not fallback_id and beans:
        fallback_id = next(iter(beans.keys()))
    # 3) hvis vi fandt en kandidat, sæt den; ellers bed brugeren oprette/vælge
    if fallback_id:
        st.session_state.current_bean = fallback_id
        if USE_SHEETS:
            upsert_user_profile(USER_ID, last_active_bean_id=fallback_id)
    else:
        st.info("Vælg en eksisterende bønne i listen eller opret en ny i panelet ‘➕ Ny bønne’.")
        st.stop()

bean_id = st.session_state.current_bean
bean = beans.get(bean_id)
if bean is None:
    st.warning("Den senest valgte bønne findes ikke længere. Vælg en anden eller opret en ny.")
    st.session_state.current_bean = None
    st.stop()

# --------------------------- Active bean header ----------------------------
box = st.container()
with box:
    c1, c2, c3, c4 = st.columns([2,2,1,1])
    c1.markdown(f"**Mærke:** {bean['brand'] or '—'}")
    c2.markdown(f"**Bønne:** {bean['name'] or '—'}")
    c3.metric("Proces", bean.get("process") or "—")
    new_tr = c4.selectbox("Target ratio", [1.8,1.9,2.0,2.1,2.2], index=[1.8,1.9,2.0,2.1,2.2].index(bean.get("target_ratio",2.0)), key=f"k_tr_{bean_id}")
    if new_tr != bean.get("target_ratio", 2.0):
        bean["target_ratio"] = float(new_tr)
        if USE_SHEETS:
            upsert_bean_to_sheets(USER_ID, bean_id, bean)

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
        bean.setdefault("entries", []).insert(0, entry)
        if USE_SHEETS:
            # Sørg for at bønnen findes i beans‑arket først
            upsert_bean_to_sheets(USER_ID, bean_id, bean)
            append_entry_to_sheets(USER_ID, bean_id, entry)
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
if USE_SHEETS and USER_ID and not entries:
    # Reload fra Sheets (fx efter ny deploy)
    st.session_state.beans = load_from_sheets(USER_ID)
    bean = st.session_state.beans.get(bean_id, bean)
    entries = bean.get("entries", [])

if not entries:
    st.info("Ingen shots endnu for denne bønne – udfyld felterne og tryk ‘Gem shot’.")
else:
    df = pd.DataFrame(entries)
    st.dataframe(df, use_container_width=True, hide_index=True)
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
