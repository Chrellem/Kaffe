diff --git a/app.py b/app.py
index c9b194ecd8a55e1013891f3088d26b51e83ae129..5bc78fe19e5d6660335b8be7ad22d63ae7e22889 100644
--- a/app.py
+++ b/app.py
@@ -1,216 +1,259 @@
 import io
 import math
+from datetime import date as date_cls
+from typing import Dict, List, Optional
+
 import pandas as pd
 import streamlit as st
 
 st.set_page_config(page_title="Espresso Advisor", page_icon="☕", layout="wide")
 
+
 # --- Helpers ---------------------------------------------------------------
 def parse_float(x):
     try:
-        if x is None: return None
-        if isinstance(x, (int, float)): return float(x)
+        if x is None:
+            return None
+        if isinstance(x, (int, float)):
+            return float(x)
         x = str(x).replace(",", ".").strip()
         return float(x) if x != "" else None
     except Exception:
         return None
 
-def rec_dose(shot_type: str):
+
+def rec_dose(shot_type: str) -> Optional[float]:
     return 9.0 if shot_type == "Single" else 18.0 if shot_type == "Double" else None
 
-def recommend(ratio, time_sec, target_out):
+
+def recommend(ratio: Optional[float], time_sec: Optional[float], target_out: Optional[float], target_ratio: Optional[float]):
     has_r = ratio is not None and math.isfinite(ratio)
     has_t = time_sec is not None and math.isfinite(time_sec)
+    has_target_r = target_ratio is not None and math.isfinite(target_ratio)
+    target_text = f"{round(target_out)} g" if (target_out is not None and math.isfinite(target_out)) else "måludbyttet"
+
     if has_r and has_t and 1.8 <= ratio <= 2.2 and 25 <= time_sec <= 30:
         return ("✅ God ekstraktion – behold indstillingerne.", "good")
+
+    ratio_hint = ""
+    if has_r and has_target_r:
+        diff = ratio - target_ratio
+        if diff > 0.15:
+            ratio_hint = f"Din ratio ({ratio:.2f}) er høj i forhold til mål på {target_ratio:.2f}. Prøv finere kværn eller lavere udbytte."
+        elif diff < -0.15:
+            ratio_hint = f"Din ratio ({ratio:.2f}) er lav i forhold til mål på {target_ratio:.2f}. Prøv grovere kværn eller længere løbetid."
+
     if (has_t and time_sec < 25) or (has_r and ratio > 2.2):
-        return (f"Underekstraheret → Mal finere (lavere tal) og/eller stop ved {round(target_out)} g.", "under")
+        return (
+            (f"Underekstraheret → Mal finere (lavere tal) og/eller stop ved {target_text}." + (f" {ratio_hint}" if ratio_hint else "")).strip(),
+            "under",
+        )
     if (has_t and time_sec > 30) or (has_r and ratio < 1.8):
-        return (f"Overekstraheret → Mal grovere (højere tal). Hold dig til {round(target_out)} g.", "over")
-    return (f"Juster småt: sigt efter 25–30 sek og {round(target_out)} g.", "neutral")
+        return (
+            (f"Overekstraheret → Mal grovere (højere tal). Hold dig til {target_text}." + (f" {ratio_hint}" if ratio_hint else "")).strip(),
+            "over",
+        )
+    if ratio_hint:
+        return (ratio_hint, "neutral")
+    return (f"Juster småt: sigt efter 25–30 sek og {target_text}.", "neutral")
+
+
+PROCESS_CHOICES = ["Washed", "Natural", "Honey", "Anaerob", "CM", "Giling Basah", "Wet-Hulled", "Andet"]
 
-PROCESS_CHOICES = ["Washed","Natural","Honey","Anaerob","CM","Giling Basah","Wet-Hulled","Andet"]
 
 # --- State -----------------------------------------------------------------
 if "rows" not in st.session_state:
-    st.session_state.rows = []
-if "filter_bean" not in st.session_state:
-    st.session_state.filter_bean = "Alle" 
-if "rows" not in st.session_state:
-    st.session_state.rows = []
+    st.session_state.rows: List[Dict] = []
+if "beans" not in st.session_state:
+    st.session_state.beans: List[Dict] = []
+if "active_bean_id" not in st.session_state:
+    st.session_state.active_bean_id: Optional[int] = None
+
+
+def _bean_label(bean: Dict) -> str:
+    parts = [bean.get("brand", "").strip(), bean.get("name", "").strip()]
+    label = " – ".join([p for p in parts if p])
+    return label or "Uden navn"
+
+
+def _bean_process(bean: Dict) -> str:
+    process = bean.get("process", "")
+    other = bean.get("process_other", "")
+    if process == "Andet" and other:
+        return other
+    return process
+
 
 # --- UI --------------------------------------------------------------------
 st.title("Espresso Advisor – Python/Streamlit")
-st.caption("Single/Dobbel • ratio, tid og anbefaling • log og CSV‑export")
-
-# Bean meta (mobile-friendly: two columns)
-colB1, colB2 = st.columns(2)
-with colB1:
-    brand = st.text_input("Mærke / Risteri", placeholder="fx La Cabra", key="k_brand")
-with colB2:
-    bean_name = st.text_input("Bønne / Navn", placeholder="fx Caballero #3", key="k_bean")
-
-colP1, colP2 = st.columns(2)
-with colP1:
-    process = st.selectbox("Proces", PROCESS_CHOICES, index=0, key="k_process")
-with colP2:
-    process_other = st.text_input(
-    "Proces (andet)",
-    placeholder=("Udfyld hvis valgt 'Andet'" if process=="Andet" else ""),
-    disabled=(process!="Andet"),
-    key="k_process_other"
-)
-
-
-# Core inputs
-col1, col2 = st.columns(2)
-with col1:
-    date = st.date_input("Dato", key="k_input_date")
-with col2:
-    shot_type = st.selectbox("Shot type", ["Double", "Single"], index=0, key="k_input_type")
-
-c1, c2 = st.columns(2)
-with c1:
-    grind = st.text_input("Kværn (tal)", placeholder="fx 8", key="k_grind")
-with c2:
-    dose = parse_float(st.text_input("Dosis (g ind)", key="k_dose", value="", placeholder=str(rec_dose(shot_type) or "")))
-
-c3, c4 = st.columns(2)
-with c3:
-    yield_out = parse_float(st.text_input("Udbytte (g ud)", key="k_yield", value="", placeholder="fx 36"))
-with c4:
-    time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", key="k_time", value="", placeholder="fx 27"))
-
-c5, c6 = st.columns(2)
-with c5:
-    target_ratio = parse_float(st.selectbox("Target ratio", [1.8, 1.9, 2.0, 2.1, 2.2], index=2, key="k_ratio"))
-with c6:
-    recommended_dose = rec_dose(shot_type)
-    st.metric(label="Anbefalet dosis (auto)", value=f"{recommended_dose:.0f} g")
-
-col1, col2 = st.columns(2)
-with col1:
-    date = st.date_input("Dato", key="k_input_date")
-with col2:
-    shot_type = st.selectbox("Shot type", ["Double", "Single"], index=0, key="k_input_type")
-
-c1, c2, c3 = st.columns(3)
-with c1:
-    grind = st.text_input("Kværn (tal)", placeholder="fx 8", key="k_grind")
-with c2:
-    dose = parse_float(st.text_input("Dosis (g ind)", key="k_dose", value="", placeholder=str(rec_dose(shot_type) or "")))
-with c3:
-    yield_out = parse_float(st.text_input("Udbytte (g ud)", key="k_yield", value="", placeholder="fx 36"))
-
-c4, c5, c6 = st.columns(3)
-with c4:
-    time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", key="k_time", value="", placeholder="fx 27"))
-with c5:
-    target_ratio = parse_float(st.selectbox("Target ratio", [1.8, 1.9, 2.0, 2.1, 2.2], index=2, key="k_ratio"))
-with c6:
-    recommended_dose = rec_dose(shot_type)
-    st.metric(label="Anbefalet dosis (auto)", value=f"{recommended_dose:.0f} g")
+st.caption("Opret bønner, log espresso skud og få feedback på ratio og tid.")
+
+st.subheader("Bønnestyring")
+
+if st.session_state.beans:
+    bean_ids = [None] + list(range(len(st.session_state.beans)))
 
-# Derived values
-if dose is not None and target_ratio is not None:
-    target_out = dose * target_ratio
-elif recommended_dose is not None and target_ratio is not None:
-    target_out = recommended_dose * target_ratio
+    def _bean_option_label(bean_id: Optional[int]) -> str:
+        if bean_id is None:
+            return "Vælg bønne"
+        bean = st.session_state.beans[bean_id]
+        return f"#{bean_id + 1} {_bean_label(bean)}"
+
+    default_idx = bean_ids.index(st.session_state.active_bean_id) if st.session_state.active_bean_id in bean_ids else 0
+    selected_id = st.selectbox("Aktiv bønne", bean_ids, index=default_idx, format_func=_bean_option_label)
+    st.session_state.active_bean_id = selected_id
 else:
-    target_out = None
-
-ratio = (yield_out / dose) if (dose and yield_out) else None
-
-rec_text, rec_kind = recommend(ratio, time_sec, target_out or 0)
-
-colA, colB = st.columns(2)
-with colA:
-    st.metric("Mål udbytte (g)", value=(str(int(round(target_out))) if target_out else "—"))
-with colB:
-    st.metric("Faktisk ratio", value=(f"{ratio:.2f}" if ratio else "—"))
-
-# Recommendation box
-color = {
-    "good": "#DCFCE7",   # green-100
-    "under": "#FEF3C7",  # amber-100
-    "over": "#FECACA",   # red-200
-    "neutral": "#F5F5F4"  # stone-100
-}.get(rec_kind, "#F5F5F4")
-
-st.markdown(
-    f"""
-    <div style='border:1px solid #e5e7eb;background:{color};padding:12px;border-radius:12px;'>
-      {rec_text}
-    </div>
-    """,
-    unsafe_allow_html=True,
-)(
-    f"""
-    <div style='border:1px solid #e5e7eb;background:{color};padding:12px;border-radius:12px;'>
-      {rec_text}
-    </div>
-    """,
-    unsafe_allow_html=True,
-)
-
-# Actions
-colX, colY = st.columns([1,1])
-with colX:
-    if st.button("Gem i log"):
+    st.info("Tilføj din første bønne for at starte en log.")
+
+with st.expander("Tilføj eller opdater bønne", expanded=not st.session_state.beans):
+    with st.form("bean_form"):
+        brand = st.text_input("Mærke / Risteri", placeholder="fx La Cabra")
+        bean_name = st.text_input("Bønne / Navn", placeholder="fx Caballero #3")
+        process = st.selectbox("Proces", PROCESS_CHOICES, index=0)
+        process_other = st.text_input("Proces (andet)", placeholder="Udfyld hvis valgt 'Andet'", disabled=(process != "Andet"))
+        notes = st.text_area("Noter", placeholder="Fx ristningsdato, anbefalinger fra risteriet…", height=80)
+        submitted = st.form_submit_button("Gem bønne")
+
+    if submitted:
+        if not brand and not bean_name:
+            st.warning("Angiv mindst mærke eller navn på bønnen.")
+        else:
+            bean_data = {
+                "brand": brand.strip(),
+                "name": bean_name.strip(),
+                "process": process,
+                "process_other": process_other.strip(),
+                "notes": notes.strip(),
+            }
+            st.session_state.beans.append(bean_data)
+            st.session_state.active_bean_id = len(st.session_state.beans) - 1
+            st.success("Bønne gemt og valgt som aktiv.")
+
+if st.session_state.active_bean_id is not None:
+    active_bean = st.session_state.beans[st.session_state.active_bean_id]
+    st.markdown(
+        f"**Aktiv bønne:** {_bean_label(active_bean)} · {_bean_process(active_bean)}"
+        + (f"<br/>{active_bean['notes']}" if active_bean.get("notes") else ""),
+        unsafe_allow_html=True,
+    )
+
+st.divider()
+
+st.subheader("Log espresso skud")
+
+if st.session_state.active_bean_id is None:
+    st.info("Vælg eller opret en bønne for at logge dine espresso skud.")
+else:
+    with st.form("shot_form"):
+        col1, col2 = st.columns(2)
+        with col1:
+            brew_date = st.date_input("Dato", value=date_cls.today())
+        with col2:
+            shot_type = st.selectbox("Shot type", ["Double", "Single"], index=0)
+
+        grind = st.text_input("Kværn (tal)", placeholder="fx 8")
+
+        col3, col4 = st.columns(2)
+        with col3:
+            dose = parse_float(st.text_input("Dosis (g ind)", value="", placeholder=str(rec_dose(shot_type) or "")))
+        with col4:
+            yield_out = parse_float(st.text_input("Udbytte (g ud)", value="", placeholder="fx 36"))
+
+        col5, col6 = st.columns(2)
+        with col5:
+            time_sec = parse_float(st.text_input("Tid (sek, fra første dråbe)", value="", placeholder="fx 27"))
+        with col6:
+            target_ratio = parse_float(st.selectbox("Target ratio", [1.8, 1.9, 2.0, 2.1, 2.2], index=2))
+
+        submitted_shot = st.form_submit_button("Gem skud i log")
+
+    recommended_dose = rec_dose(shot_type)
+    if dose is not None and target_ratio is not None:
+        target_out = dose * target_ratio
+    elif recommended_dose is not None and target_ratio is not None:
+        target_out = recommended_dose * target_ratio
+    else:
+        target_out = None
+
+    ratio = (yield_out / dose) if (dose not in (None, 0) and yield_out is not None) else None
+
+    rec_text, rec_kind = recommend(ratio, time_sec, target_out, target_ratio)
+
+    colA, colB, colC = st.columns(3)
+    with colA:
+        st.metric("Mål udbytte (g)", value=(str(int(round(target_out))) if target_out else "—"))
+    with colB:
+        st.metric("Faktisk ratio", value=(f"{ratio:.2f}" if ratio else "—"))
+    with colC:
+        st.metric("Anbefalet dosis (g)", value=(f"{recommended_dose:.0f}" if recommended_dose else "—"))
+
+    color = {
+        "good": "#DCFCE7",
+        "under": "#FEF3C7",
+        "over": "#FECACA",
+        "neutral": "#F5F5F4",
+    }.get(rec_kind, "#F5F5F4")
+
+    st.markdown(
+        f"""
+        <div style='border:1px solid #e5e7eb;background:{color};padding:12px;border-radius:12px;'>
+          {rec_text}
+        </div>
+        """,
+        unsafe_allow_html=True,
+    )
+
+    if submitted_shot:
         row = {
-            "Dato": str(date),
-            "Mærke": brand,
-            "Bønne": bean_name,
-            "Proces": (process_other if process=="Andet" and process_other else process),
+            "Dato": str(brew_date),
+            "Mærke": active_bean.get("brand", ""),
+            "Bønne": active_bean.get("name", ""),
+            "Proces": _bean_process(active_bean),
             "Type": shot_type,
             "Kværn": grind,
             "Dosis (g)": dose if dose is not None else "",
             "Udbytte (g)": yield_out if yield_out is not None else "",
             "Tid (sek)": time_sec if time_sec is not None else "",
             "Target ratio": target_ratio if target_ratio is not None else "",
             "Mål ud (g)": int(round(target_out)) if target_out is not None else "",
             "Faktisk ratio": round(ratio, 2) if ratio is not None else "",
             "Anbefaling": rec_text,
+            "bean_id": st.session_state.active_bean_id,
         }
         st.session_state.rows.insert(0, row)
-        st.success("Gemt!")
-
-with colY:
-    if st.button("Ryd formular"):
-        st.rerun()
+        st.success("Skud gemt i loggen.")
 
 st.divider()
 
-# Log & filter
 st.subheader("Log")
-# Bean filter (mobile friendly)
-beans = ["Alle"]
-for r in st.session_state.rows:
-    key = f"{r.get('Mærke','')} – {r.get('Bønne','')}".strip(" –")
-    if key not in beans:
-        beans.append(key)
-sel = st.selectbox("Filtrér på bønne", beans, index=0, key="k_filter")
 
 if len(st.session_state.rows) == 0:
-    st.info("Ingen poster endnu – udfyld felterne og klik ‘Gem i log’.")
+    st.info("Ingen poster endnu – log et skud for at se historik.")
 else:
+    filter_ids = [None] + list(range(len(st.session_state.beans)))
+
+    def _filter_option_label(bean_id: Optional[int]) -> str:
+        if bean_id is None:
+            return "Alle bønner"
+        return _bean_label(st.session_state.beans[bean_id])
+
+    default_index = filter_ids.index(st.session_state.active_bean_id) if st.session_state.active_bean_id in filter_ids else 0
+    selected_id = st.selectbox("Filtrér på bønne", filter_ids, index=default_index, format_func=_filter_option_label)
+
     df = pd.DataFrame(st.session_state.rows)
-    if sel != "Alle":
-        if " – " in sel:
-            brand_sel, bean_sel = sel.split(" – ")
-            df = df[(df["Mærke"]==brand_sel) & (df["Bønne"]==bean_sel)]
-        else:
-            df = df[df["Mærke"]==sel]
-    st.dataframe(df, use_container_width=True, hide_index=True)
+    if selected_id is not None:
+        df = df[df["bean_id"] == selected_id]
+
+    display_cols = [c for c in df.columns if c != "bean_id"]
+    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
 
-    # Download CSV
     csv_buf = io.StringIO()
-    df.to_csv(csv_buf, index=False)
+    df[display_cols].to_csv(csv_buf, index=False)
     st.download_button(
         label="Download CSV",
         data=csv_buf.getvalue().encode("utf-8-sig"),
         file_name=f"espresso-log-{pd.Timestamp.today().date()}.csv",
         mime="text/csv",
     )
 
 st.caption("Tip: Single 9→18 g, Double 18→36 g, 25–30 sek fra første dråbe. Standard temp ca. 93 °C.")
