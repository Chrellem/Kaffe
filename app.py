import io
import math
import re
import time
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

        # Simple retry på 429 (rate limit)
        last_err = None
        for i in range(3):
            try:
                sh = gc.open_by_key(sheet_id)
                return gc, sh
            except gspread.exceptions.APIError as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                last_err = (e, code)
                if code == 429 and i < 2:
                    time.sleep(1 + i)
                    continue
                break

        e, code = last_err
        svc = st.secrets["gcp_service_account"].get("client_email", "(service-konto)")
        st.error(
            f"Kunne ikke åbne arket via ID (HTTP {code or 'ukendt'}). Tjek ID og del arket som Editor med {svc}."
        )
        st.stop()

    GC, SH = get_sheet()

    def ws(name: str):
        """Hent eller opret worksheet og initier headers."""
        try:
            w = SH.worksheet(name)
        except Exception:
            w = SH.add_worksheet(title=name, rows=1000, cols=20)
        if name == "beans" and len(w.get_all_values()) == 0:
            w.append_row(["user_id","bean_id","brand","name","process","target_ratio"])
        if name == "entries" and len(w.get_all_values()) == 0:
            w.append_row([
                "user_id","bean_id","date","type","grind","dose","yield",
                "time","target_ratio","target_out","ratio","advice","notes"
            ])
        return w

    WS_BEANS = ws("beans")
    WS_ENTRIES = ws("entries")

# --------------------------- Helpers ---------------------------------------
PROCESS_CHOICES = [
    "Washed","Natural","Honey","Anaerob","CM","Giling Basah","Wet-Hulled","Andet"
]

def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "bean"

def parse_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
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
    @st.cache_data(ttl=60, show_spinner=False)
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
                        "Noter": row.get("notes", ""),
                    })
        return beans

    def upsert_bean(user_id: str, bean_id: str, bean: dict):
        rows = WS_BEANS.get_all_values()
        if rows:
            for idx, r in enumerate(rows[1:], start=2):
                if len(r) >= 2 and r[0] == user_id and r[1] == bean_id:
                    WS_BEANS.update(
                        f"A{idx}:F{idx}",
                        [[user_id, bean_id, bean.get('brand',''), bean.get('name',''), bean.get('process',''), bean.get('target_ratio',2.0)]]
                    )
                    return
        WS_BEANS.append_row([user_id, bean_id, bean.get('brand',''), bean.get('name',''), bean.get('process',''), bean.get('target_ratio',2.0)])

    def append_entry(user_id: str, bean_id: str, entry: dict):
        WS_ENTRIES.append_row([
            user_id, bean_id, entry.get("Dato",""), entry.get("Type",""), entry.get("Kværn",""),
            entry.get("Dosis (g)",""), entry.get("Udbytte (g)",""), entry.get("Tid (sek)",""),
            entry.get("Target ratio",""), entry.get("Mål ud (g)",""), entry.get("Faktisk ratio",""), entry.get("Anbefaling",""), entry.get("Noter",""),
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

# Deep-link auto-login: ?user=<alias>
try:
    qp = st.query_params
    user_from_url = qp.get("user", None)
except Exception:
    try:
        user_from_url = st.experimental_get_query_params().get("user", [None])[0]
    except Exception:
        user_from_url = None

if user_from_url and ("user_id" not in st.session_state or not st.session_state.user_id):
    st.session_state.user_id = user_from_url
    if USE_SHEETS:
        st.session_state.beans = load_user_data(user_from_url)
    st.rerun()

if not st.session_state.user_id:
    st.markdown("### Log ind")
    st.caption("Skriv et brugernavn/alias. Dine bønner og shots gemmes i Google Sheets under dette ID.")
    user_input = st.text_input("Bruger-ID", placeholder="fx jonas_home")

    # Hjælp: vælg et eksisterende alias fundet i arket
    if USE_SHEETS:
        @st.cache_data(ttl=60, show_spinner=False)
        def list_user_ids():
            try:
                vals = WS_BEANS.get_all_values()
                if not vals or len(vals) < 2:
                    return []
                # kolonne A antages at være 'user_id'
                return sorted(list({r[0] for r in vals[1:] if r and r[0]}))
            except Exception:
                return []
        existing_users = list_user_ids()
        if existing_users:
            picked = st.selectbox("Eller vælg en eksisterende bruger fra arket", ["(vælg)"] + existing_users)
            if picked != "(vælg)":
                user_input = picked

    colL, colR = st.columns([1,1])
    with colL:
        if st.button("Log ind", type="primary"):
            uid = (user_input or "").strip()
            if uid:
                st.session_state.user_id = uid
                if USE_SHEETS:
                    st.session_state.beans = load_user_data(uid)
                    # Skriv alias i URL så du kan bogmærke
                    try:
                        st.query_params["user"] = uid
                    except Exception:
                        st.experimental_set_query_params(user=uid)
                st.rerun()
            else:
                st.warning("Indtast et Bruger-ID for at fortsætte.")
    # Lille diagnose ved login hvis Sheets er aktivt
    if USE_SHEETS:
        with st.expander("🔧 Diagnose (Google Sheets)", expanded=False):
            try:
                sheet_title = SH.title
                st.write(f"Sheet: **{sheet_title}** (ID sløret)")
                st.write("Arbejdssheets:", [w.title for w in SH.worksheets()])
                beans_head = WS_BEANS.row_values(1)
                entries_head = WS_ENTRIES.row_values(1)
                st.write("beans header:", beans_head)
                st.write("entries header:", entries_head)
                st.write("Fundne brugere:", existing_users)
            except Exception as e:
                st.error(f"Kan ikke læse diagnose: {e}")
    st.stop()

# Hvis vi allerede er logget ind men ingen data i denne session → hent fra Sheets
if USE_SHEETS and st.session_state.user_id and not st.session_state.beans:
    st.session_state.beans = load_user_data(st.session_state.user_id)

USER_ID = st.session_state.user_id
beans = st.session_state.beans

# --------------------------- Bean vælger / opret ---------------------------
st.caption(f"Logget ind som **{st.session_state.user_id}** · delbart link: ?user={st.session_state.user_id}")

# Ekstra diagnose inde i appen
if USE_SHEETS:
    with st.expander("🔧 Diagnose / Reparer Sheets", expanded=False):
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            try:
                st.write("Sheets:", [w.title for w in SH.worksheets()])
                st.write("beans header:", WS_BEANS.row_values(1))
                st.write("entries header:", WS_ENTRIES.row_values(1))
                # antal rækker for denne bruger
                import itertools
                beans_rows = WS_BEANS.get_all_records()
                entries_rows = WS_ENTRIES.get_all_records()
                nb = sum(1 for r in beans_rows if r.get("user_id") == USER_ID)
                ne = sum(1 for r in entries_rows if r.get("user_id") == USER_ID)
                st.write(f"Rækker for {USER_ID}: beans={nb}, entries={ne}")
            except Exception as e:
                st.error(f"Diagnosefejl: {e}")
        with exp_col2:
            if st.button("🔁 Genindlæs fra Sheets nu"):
                try:
                    if 'load_user_data' in globals():
                        load_user_data.clear()
                except Exception:
                    pass
                st.session_state.beans = load_user_data(USER_ID)
                st.success("Genindlæst fra Sheets")
                st.rerun()

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
            base = slugify(f"{n_brand}-{n_name}")
            bid = base or "bean"
            i = 2
            while bid in beans:
                bid = f"{base}-{i}"
                i += 1

            beans[bid] = {
                "brand": (n_brand or "").strip(),
                "name": (n_name or "").strip(),
                "process": n_proc,
                "target_ratio": float(n_ratio),
                "entries": [],
            }
            # Sæt aktiv bønne og sørg for lokal state
            st.session_state.current_bean = bid
            st.session_state.beans[bid] = beans[bid]
            # Gem i Sheets hvis aktiveret (ingen reload af data her)
            if USE_SHEETS:
                upsert_bean(USER_ID, bid, beans[bid])
                try:
                    load_user_data.clear()
                except Exception:
                    pass
            st.success("Bønne oprettet! Klar til at logge shots.")
            st.rerun()

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
with st.form("shot_form"):
    c1, c2 = st.columns(2)
    with c1:
        shot_type = st.selectbox("Shot type", ["Double","Single"], index=0, key=f"type_{bean_id}")
        grind = st.text_input("Kværn (tal)", placeholder="fx 8", key=f"grind_{bean_id}")
        dose = parse_float(st.text_input("Dosis (g ind)", placeholder=str(rec_dose(shot_type) or ""), key=f"dose_{bean_id}"))
    with c2:
        yield_out = parse_float(st.text_input("Udbytte (g ud)", placeholder="fx 36", key=f"yield_{bean_id}"))
        time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", placeholder="fx 27", key=f"time_{bean_id}"))
        date_str = st.date_input("Dato", key=f"date_{bean_id}")
    note = st.text_input("Noter (valgfri)", placeholder="Smagsnoter, mælketekstur, vand…", key=f"note_{bean_id}")

    target_ratio = bean.get("target_ratio", 2.0)
    target_out = (dose * target_ratio) if dose is not None else (rec_dose(shot_type) or 0) * target_ratio
    ratio = (yield_out / dose) if (dose and yield_out) else None
    advice, kind = recommend(ratio, time_sec, target_out or 0)

    m1, m2 = st.columns(2)
    m1.metric("Mål udbytte (g)", value=(str(int(round(target_out))) if target_out else "—"))
    m2.metric("Faktisk ratio", value=(f"{ratio:.2f}" if ratio else "—"))

    bg = {"good":"#DCFCE7","under":"#FEF3C7","over":"#FECACA","neutral":"#F5F5F4"}.get(kind,"#F5F5F4")
    st.markdown(
        f"<div style='border:1px solid #e5e7eb;background:{bg};padding:12px;border-radius:12px'>{advice}</div>",
        unsafe_allow_html=True,
    )

    submitted = st.form_submit_button("Gem shot i aktiv bønne", use_container_width=True)

    if submitted:
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
        # Opdater KUN lokal state her — ingen fetch, så bønnen ikke forsvinder
        st.session_state.beans.setdefault(bean_id, bean)
        st.session_state.beans[bean_id].setdefault("entries", []).insert(0, entry)

        if USE_SHEETS:
            # Persistér men lad lokal state være "source of truth" for dette run
            upsert_bean(USER_ID, bean_id, st.session_state.beans[bean_id])
            append_entry(USER_ID, bean_id, entry)
            try:
                load_user_data.clear()
            except Exception:
                pass
        st.success("✅ Shot gemt!")
        # Bevar kontekst før rerun
        st.session_state.user_id = USER_ID
        st.session_state.current_bean = bean_id
        st.rerun()

# --------------------------- Historik --------------------------------------
st.subheader("Historik for valgt bønne")
entries = bean.get("entries", [])
# Vi undgår at overskrive lokal state her; Sheets læses først ved login/opstart

# Kontrolleret visning til mobil: kort eller tabel
if hasattr(st, 'segmented_control'):
    view = st.segmented_control("Visning", options=["Kort", "Tabel"], default="Kort")
else:
    view = st.radio("Visning", ["Kort","Tabel"], horizontal=True)
limit_opt = st.selectbox("Antal viste", [5,10,25,50,"Alle"], index=1)

# Nyeste først (entries er allerede indsat i toppen)
data = entries[:]
if limit_opt != "Alle":
    data = data[: int(limit_opt)]

if not data:
    st.info("Ingen shots endnu – gem et shot for at se historik.")
else:
    if view == "Tabel":
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        # Kortvisning – mobilvenlig
        for r in data:
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

st.caption("Simpel version: login → vælg/opret bønne → log shot → se historik. Ratio sweet spot 1.8–2.2 og 25–30 sek.")
