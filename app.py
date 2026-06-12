import streamlit as st
import requests
import pandas as pd
import plotly.express as px

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
def get_regio_key(table, pc):
    """Haal de exacte RegioS key op voor deze postcode (CBS gebruikt trailing spaces)."""
    regiolen = fetch(f"{BASE}/{table}/RegioS?$format=json")
    for r in regiolen:
        key = r.get("Key", "")
        title = r.get("Title", "")
        if key.strip() == f"PO{pc}" or title.strip() == pc:
            return key  # inclusief trailing spaces!
    return None

@st.cache_data(ttl=3600)
def get_plaatsnaam(pc):
    """Haal plaatsnaam op via gratis postcode API."""
    try:
        r = requests.get(f"https://api.postcodeapi.nu/v2/postcodes/{pc}00/", timeout=5)
        if r.status_code == 200:
            data = r.json()
            city = data.get("city", {}).get("label", "")
            muni = data.get("municipality", {}).get("label", "")
            if city:
                return city, muni
    except Exception:
        pass
    # Fallback: probeer een andere gratis bron
    try:
        r2 = requests.get(
            f"https://geodata.nationaalgeoregister.nl/locatieserver/v3/suggest?q={pc}&fq=type:postcode&rows=1",
            timeout=5
        )
        if r2.status_code == 200:
            docs = r2.json().get("response", {}).get("docs", [])
            if docs:
                weergavenaam = docs[0].get("weergavenaam", "")
                parts = weergavenaam.split(",")
                if len(parts) >= 2:
                    return parts[1].strip(), parts[-1].strip()
    except Exception:
        pass
    return None, None

@st.cache_data(ttl=3600)
def get_column_names(table):
    props = fetch(f"{BASE}/{table}/DataProperties?$format=json")
    return [p["Key"] for p in props if p.get("Key")]

@st.cache_data(ttl=3600)
def get_latest_period(table):
    perioden = fetch(f"{BASE}/{table}/Perioden?$format=json")
    return perioden[-1]["Key"].strip(), perioden[-1]["Title"].strip()

@st.cache_data(ttl=3600)
def get_leeftijd_data(pc):
    TABLE = "83502NED"
    periode_key, periode_title = get_latest_period(TABLE)

    # Correcte RegioS key ophalen (met eventuele trailing spaces)
    regio_key = get_regio_key(TABLE, pc)
    if not regio_key:
        return None, periode_title, f"Postcode {pc} niet gevonden in CBS-data."

    leeftijden_raw = fetch(f"{BASE}/{TABLE}/Leeftijd?$format=json")
    leeftijd_map = {l["Key"].strip(): l["Title"].strip() for l in leeftijden_raw}

    gewenste_titels = [
        "0 tot 5 jaar", "5 tot 10 jaar", "10 tot 15 jaar", "15 tot 20 jaar",
        "20 tot 25 jaar", "25 tot 30 jaar", "30 tot 35 jaar", "35 tot 40 jaar",
        "40 tot 45 jaar", "45 tot 50 jaar", "50 tot 55 jaar", "55 tot 60 jaar",
        "60 tot 65 jaar", "65 tot 70 jaar", "70 tot 75 jaar", "75 tot 80 jaar",
        "80 tot 85 jaar", "85 tot 90 jaar", "90 jaar of ouder",
    ]
    leeftijd_keys = [k for k, v in leeftijd_map.items() if v in gewenste_titels]

    geslachten_raw = fetch(f"{BASE}/{TABLE}/Geslacht?$format=json")
    totaal_g = next(g for g in geslachten_raw if "Totaal" in g["Title"])
    geslacht_key = totaal_g["Key"].strip()

    # Kolomnaam automatisch ontdekken
    cols = get_column_names(TABLE)
    bevolking_col = next((c for c in cols if "Bevolking" in c and "Januari" in c), None)
    if not bevolking_col:
        bevolking_col = next((c for c in cols if "Bevolking" in c), None)
    if not bevolking_col:
        raise ValueError(f"Bevolkingskolom niet gevonden. Beschikbare kolommen: {cols}")

    resultaten = []
    for lkey in leeftijd_keys:
        # Gebruik de exacte regio_key (met trailing spaces) in de filter
        obs = fetch(
            f"{BASE}/{TABLE}/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key}'"
            f" and Geslacht eq '{geslacht_key.strip()}'"
            f" and RegioS eq '{regio_key}'"
            f" and Leeftijd eq '{lkey}'"
            f"&$select=Leeftijd,{bevolking_col}"
        )
        for row in obs:
            ltitel = leeftijd_map.get(row.get("Leeftijd", "").strip(), "")
            aantal = row.get(bevolking_col) or 0
            if ltitel in gewenste_titels:
                resultaten.append({"titel": ltitel, "aantal": aantal})

    return resultaten, periode_title, None

@st.cache_data(ttl=3600)
def get_inkomen_data(pc):
    TABLE = "85064NED"
    periode_key, periode_title = get_latest_period(TABLE)

    regio_key = get_regio_key(TABLE, pc)
    if not regio_key:
        return None, periode_title, {}

    cols = get_column_names(TABLE)
    col_per_inw  = next((c for c in cols if "PerInwoner"          in c and "Gemiddeld" in c), None)
    col_per_ontv = next((c for c in cols if "PerInkomensontvanger" in c and "Gemiddeld" in c), None)
    col_mediaan  = next((c for c in cols if "Mediaan"             in c and "Inkomen"   in c), None)

    if not any([col_per_inw, col_per_ontv, col_mediaan]):
        return None, periode_title, {}

    select_cols = ",".join(c for c in [col_per_inw, col_per_ontv, col_mediaan] if c)
    obs = fetch(
        f"{BASE}/{TABLE}/TypedDataSet?$format=json"
        f"&$filter=Perioden eq '{periode_key}' and RegioS eq '{regio_key}'"
        f"&$select={select_cols}"
    )
    col_names = {"per_inw": col_per_inw, "per_ontv": col_per_ontv, "mediaan": col_mediaan}
    return (obs[0] if obs else None), periode_title, col_names


LABEL_MAP = {
    "0 tot 5 jaar": "0-5",     "5 tot 10 jaar": "5-10",   "10 tot 15 jaar": "10-15",
    "15 tot 20 jaar": "15-20", "20 tot 25 jaar": "20-25", "25 tot 30 jaar": "25-30",
    "30 tot 35 jaar": "30-35", "35 tot 40 jaar": "35-40", "40 tot 45 jaar": "40-45",
    "45 tot 50 jaar": "45-50", "50 tot 55 jaar": "50-55", "55 tot 60 jaar": "55-60",
    "60 tot 65 jaar": "60-65", "65 tot 70 jaar": "65-70", "70 tot 75 jaar": "70-75",
    "75 tot 80 jaar": "75-80", "80 tot 85 jaar": "80-85", "85 tot 90 jaar": "85-90",
    "90 jaar of ouder": "90+",
}
GEWICHTEN = {
    "0-5": 2.5,  "5-10": 7.5,  "10-15": 12.5, "15-20": 17.5, "20-25": 22.5,
    "25-30": 27.5, "30-35": 32.5, "35-40": 37.5, "40-45": 42.5, "45-50": 47.5,
    "50-55": 52.5, "55-60": 57.5, "60-65": 62.5, "65-70": 67.5, "70-75": 72.5,
    "75-80": 77.5, "80-85": 82.5, "85-90": 87.5, "90+": 92.5,
}

# ── Input ──────────────────────────────────────────────────────────────────────
col_in, _ = st.columns([1, 3])
with col_in:
    postcode_input = st.text_input("Voer een postcode in", placeholder="bijv. 2101", max_chars=4)

if not postcode_input:
    st.info("Voer een 4-cijferige postcode in om te beginnen.")
    st.stop()

if not postcode_input.isdigit() or len(postcode_input) != 4:
    st.error("Voer precies 4 cijfers in, zonder letters.")
    st.stop()

pc = postcode_input.strip()

# Plaatsnaam ophalen
stad, gemeente = get_plaatsnaam(pc)
if stad:
    locatie_label = f"{stad} ({gemeente})" if gemeente and gemeente != stad else stad
    st.header(f"Postcode {pc} — {locatie_label}")
else:
    st.header(f"Postcode {pc}")

# ── Leeftijdsopbouw ────────────────────────────────────────────────────────────
with st.spinner("Leeftijdsdata ophalen..."):
    try:
        result = get_leeftijd_data(pc)
        raw, periode_title, foutmelding = result

        if foutmelding:
            st.warning(foutmelding)
        elif not raw or all(r["aantal"] == 0 for r in raw):
            st.warning(f"Geen leeftijdsdata gevonden voor postcode {pc}.")
        else:
            df = pd.DataFrame([
                {"Leeftijdsgroep": LABEL_MAP[r["titel"]], "Aantal": r["aantal"]}
                for r in raw if r["aantal"] > 0
            ])
            totaal = df["Aantal"].sum()
            df["Percentage"] = (df["Aantal"] / totaal * 100).round(1)
            gem = sum(GEWICHTEN[row["Leeftijdsgroep"]] * row["Aantal"] for _, row in df.iterrows()) / totaal
            jong = df[df["Leeftijdsgroep"].isin(["0-5","5-10","10-15","15-20","20-25"])]["Aantal"].sum()
            oud  = df[df["Leeftijdsgroep"].isin(["65-70","70-75","75-80","80-85","85-90","90+"])]["Aantal"].sum()

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Inwoners",      f"{int(totaal):,}".replace(",", "."))
            m2.metric("Gem. leeftijd", f"{gem:.1f} jaar")
            m3.metric("Aandeel 65+",  f"{oud/totaal*100:.1f}%")
            m4.metric("Aandeel 0-25", f"{jong/totaal*100:.1f}%")

            st.subheader(f"Leeftijdsopbouw — {periode_title}")
            fig = px.bar(
                df, x="Leeftijdsgroep", y="Percentage",
                labels={"Percentage": "% van inwoners"},
                color_discrete_sequence=["#1D9E75"],
                text="Percentage",
            )
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                yaxis=dict(showgrid=True, gridcolor="#eee"),
                xaxis=dict(tickangle=-45),
                margin=dict(t=20, b=60), height=380,
            )
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("Tabel: aantallen per leeftijdsgroep"):
                st.dataframe(df[["Leeftijdsgroep","Aantal","Percentage"]].reset_index(drop=True), use_container_width=True)

    except Exception as e:
        st.error(f"Fout bij leeftijdsdata: {e}")

st.divider()

# ── Inkomen ────────────────────────────────────────────────────────────────────
with st.spinner("Inkomendata ophalen..."):
    try:
        row_i, periode_title_i, col_names = get_inkomen_data(pc)
        if row_i and col_names:
            st.subheader(f"Inkomen — {periode_title_i}")
            ic1, ic2, ic3 = st.columns(3)
            v1 = row_i.get(col_names["per_inw"])  if col_names.get("per_inw")  else None
            v2 = row_i.get(col_names["per_ontv"]) if col_names.get("per_ontv") else None
            v3 = row_i.get(col_names["mediaan"])  if col_names.get("mediaan")  else None
            if v1: ic1.metric("Gem. inkomen per inwoner",   f"€ {int(v1 * 1000):,}".replace(",","."))
            if v2: ic2.metric("Gem. inkomen per ontvanger", f"€ {int(v2 * 1000):,}".replace(",","."))
            if v3: ic3.metric("Mediaan inkomen",            f"€ {int(v3 * 1000):,}".replace(",","."))
        else:
            st.info("Geen inkomendata beschikbaar voor deze postcode.")
    except Exception as e:
        st.error(f"Fout bij inkomendata: {e}")

st.divider()
st.caption("Data: CBS StatLine open data — CC BY 4.0 | App gebouwd met Streamlit")
