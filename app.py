import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Postcode Facts", page_icon="📍", layout="wide")

st.title("📍 Postcode Demografische Feiten")
st.caption("Bron: CBS StatLine — open data (CC BY 4.0)")

BASE = "https://opendata.cbs.nl/ODataApi/OData"

@st.cache_data(ttl=3600)
def fetch(url):
    rows, next_url = [], url
    while next_url:
        r = requests.get(next_url, timeout=30)
        r.raise_for_status()
        d = r.json()
        rows.extend(d.get("value", []))
        next_url = d.get("odata.nextLink")
    return rows

@st.cache_data(ttl=3600)
def get_latest_period(table):
    perioden = fetch(f"{BASE}/{table}/Perioden?$format=json")
    return perioden[-1]["Key"].strip(), perioden[-1]["Title"].strip()

# --- Input ---
col1, col2 = st.columns([1, 3])
with col1:
    postcode_input = st.text_input("Voer een postcode in", placeholder="bv. 1234", max_chars=4)

if not postcode_input:
    st.info("Voer een 4-cijferige postcode in om te beginnen.")
    st.stop()

if not postcode_input.isdigit() or len(postcode_input) != 4:
    st.error("Voer precies 4 cijfers in, zonder letters.")
    st.stop()

pc = postcode_input.strip()

# ── LEEFTIJDSOPBOUW (tabel 83502NED) ──────────────────────────────────────────
st.header(f"📊 Postcode {pc}")

LEEFTIJD_LABELS = {
    "0 tot 5 jaar": "0–5",   "5 tot 10 jaar": "5–10",
    "10 tot 15 jaar": "10–15", "15 tot 20 jaar": "15–20",
    "20 tot 25 jaar": "20–25", "25 tot 30 jaar": "25–30",
    "30 tot 35 jaar": "30–35", "35 tot 40 jaar": "35–40",
    "40 tot 45 jaar": "40–45", "45 tot 50 jaar": "45–50",
    "50 tot 55 jaar": "50–55", "55 tot 60 jaar": "55–60",
    "60 tot 65 jaar": "60–65", "65 tot 70 jaar": "65–70",
    "70 tot 75 jaar": "70–75", "75 tot 80 jaar": "75–80",
    "80 tot 85 jaar": "80–85", "85 tot 90 jaar": "85–90",
    "90 jaar of ouder": "90+",
}
GEWICHTEN = {
    "0–5": 2.5, "5–10": 7.5, "10–15": 12.5, "15–20": 17.5,
    "20–25": 22.5, "25–30": 27.5, "30–35": 32.5, "35–40": 37.5,
    "40–45": 42.5, "45–50": 47.5, "50–55": 52.5, "55–60": 57.5,
    "60–65": 62.5, "65–70": 67.5, "70–75": 72.5, "75–80": 77.5,
    "80–85": 82.5, "85–90": 87.5, "90+": 92.5,
}

with st.spinner("Leeftijdsdata ophalen..."):
    try:
        TABLE_L = "83502NED"
        periode_key, periode_title = get_latest_period(TABLE_L)

        leeftijden_raw = fetch(f"{BASE}/{TABLE_L}/Leeftijd?$format=json")
        leeftijd_map = {l["Key"].strip(): l["Title"].strip() for l in leeftijden_raw}

        geslachten_raw = fetch(f"{BASE}/{TABLE_L}/Geslacht?$format=json")
        totaal_g = next(g for g in geslachten_raw if "Totaal" in g["Title"])
        geslacht_key = totaal_g["Key"].strip()

        age_keys = [k for k, v in leeftijd_map.items() if v in LEEFTIJD_LABELS]
        age_filter = ",".join(f"'{k}'" for k in age_keys)

        obs = fetch(
            f"{BASE}/{TABLE_L}/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key}'"
            f" and Geslacht eq '{geslacht_key}'"
            f" and RegioS eq 'PO{pc}'"
            f" and Leeftijd in ({age_filter})"
            f"&$select=Leeftijd,BevolkingOp1Januari_1"
        )

        if not obs:
            st.warning(f"Geen leeftijdsdata gevonden voor postcode {pc}. Controleer of het een bestaande postcode is.")
        else:
            leeftijd_data = []
            for row in obs:
                lkey = row.get("Leeftijd", "").strip()
                ltitel = leeftijd_map.get(lkey, "")
                label = LEEFTIJD_LABELS.get(ltitel)
                if label:
                    leeftijd_data.append({"Leeftijdsgroep": label, "Aantal": row.get("BevolkingOp1Januari_1") or 0})

            df_l = pd.DataFrame(leeftijd_data)
            df_l = df_l[df_l["Aantal"] > 0]

            totaal_inwoners = df_l["Aantal"].sum()
            df_l["Percentage"] = (df_l["Aantal"] / totaal_inwoners * 100).round(1)

            gem_leeftijd = sum(GEWICHTEN[r["Leeftijdsgroep"]] * r["Aantal"] for _, r in df_l.iterrows()) / totaal_inwoners

            # Groepen
            jong = df_l[df_l["Leeftijdsgroep"].isin(["0–5","5–10","10–15","15–20","20–25"])]["Aantal"].sum()
            middel = df_l[df_l["Leeftijdsgroep"].isin(["25–30","30–35","35–40","40–45","45–50","50–55","55–60","60–65"])]["Aantal"].sum()
            oud = df_l[df_l["Leeftijdsgroep"].isin(["65–70","70–75","75–80","80–85","85–90","90+"])]["Aantal"].sum()

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Totaal inwoners", f"{totaal_inwoners:,}".replace(",", "."))
            m2.metric("Gem. leeftijd", f"{gem_leeftijd:.1f} jaar")
            m3.metric("Aandeel 65+", f"{oud/totaal_inwoners*100:.1f}%")
            m4.metric("Aandeel 0–25", f"{jong/totaal_inwoners*100:.1f}%")

            st.subheader(f"Leeftijdsopbouw — {periode_title}")
            fig = px.bar(
                df_l, x="Leeftijdsgroep", y="Percentage",
                labels={"Percentage": "% van inwoners", "Leeftijdsgroep": "Leeftijdsgroep"},
                color_discrete_sequence=["#1D9E75"],
                text="Percentage",
            )
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                yaxis=dict(showgrid=True, gridcolor="#eee"),
                xaxis=dict(tickangle=-45),
                margin=dict(t=20, b=60),
                height=380,
            )
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("Tabel: aantallen per leeftijdsgroep"):
                st.dataframe(df_l[["Leeftijdsgroep", "Aantal", "Percentage"]].reset_index(drop=True), use_container_width=True)

    except Exception as e:
        st.error(f"Kon leeftijdsdata niet ophalen: {e}")

st.divider()

# ── HUISHOUDENS (tabel 85318NED) ──────────────────────────────────────────────
with st.spinner("Huishoudensdata ophalen..."):
    try:
        TABLE_H = "85318NED"
        periode_key_h, periode_title_h = get_latest_period(TABLE_H)

        # Haal metadata op
        hh_typen_raw = fetch(f"{BASE}/{TABLE_H}/SoortHuishouden?$format=json")
        hh_map = {h["Key"].strip(): h["Title"].strip() for h in hh_typen_raw}

        obs_h = fetch(
            f"{BASE}/{TABLE_H}/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key_h}'"
            f" and RegioS eq 'PO{pc}'"
            f"&$select=SoortHuishouden,ParticuliereHuishoudens_1"
        )

        if obs_h:
            hh_data = []
            for row in obs_h:
                hkey = row.get("SoortHuishouden", "").strip()
                titel = hh_map.get(hkey, "")
                aantal = row.get("ParticuliereHuishoudens_1") or 0
                if titel and "Totaal" not in titel and aantal > 0:
                    hh_data.append({"Type": titel, "Huishoudens": aantal})

            if hh_data:
                df_h = pd.DataFrame(hh_data)
                st.subheader(f"🏠 Huishoudens — {periode_title_h}")
                col_a, col_b = st.columns([1, 1])
                with col_a:
                    fig_h = px.pie(
                        df_h, names="Type", values="Huishoudens",
                        color_discrete_sequence=px.colors.qualitative.Set2,
                        hole=0.4,
                    )
                    fig_h.update_layout(margin=dict(t=20, b=20), height=320)
                    st.plotly_chart(fig_h, use_container_width=True)
                with col_b:
                    st.dataframe(df_h.reset_index(drop=True), use_container_width=True, height=320)

    except Exception:
        pass  # Huishoudenstabel stille fallback

st.divider()

# ── INKOMEN (tabel 85064NED) ──────────────────────────────────────────────────
with st.spinner("Inkomendata ophalen..."):
    try:
        TABLE_I = "85064NED"
        periode_key_i, periode_title_i = get_latest_period(TABLE_I)

        obs_i = fetch(
            f"{BASE}/{TABLE_I}/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key_i}'"
            f" and RegioS eq 'PO{pc}'"
            f"&$select=GemiddeldInkomenPerInwoner_5,GemiddeldInkomenPerInkomensontvanger_6,MediaanInkomenPerInkomensontvanger_8"
        )

        if obs_i:
            row_i = obs_i[0]
            gem_per_inw = row_i.get("GemiddeldInkomenPerInwoner_5")
            gem_per_ontv = row_i.get("GemiddeldInkomenPerInkomensontvanger_6")
            mediaan = row_i.get("MediaanInkomenPerInkomensontvanger_8")

            st.subheader(f"💶 Inkomen — {periode_title_i}")
            ic1, ic2, ic3 = st.columns(3)
            if gem_per_inw:
                ic1.metric("Gem. inkomen per inwoner", f"€ {int(gem_per_inw * 1000):,}".replace(",", "."))
            if gem_per_ontv:
                ic2.metric("Gem. inkomen per ontvanger", f"€ {int(gem_per_ontv * 1000):,}".replace(",", "."))
            if mediaan:
                ic3.metric("Mediaan inkomen", f"€ {int(mediaan * 1000):,}".replace(",", "."))

    except Exception:
        pass

st.divider()
st.caption("Data: CBS StatLine open data — CC BY 4.0 | App gebouwd met Streamlit")
