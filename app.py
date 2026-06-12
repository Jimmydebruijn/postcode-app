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
def get_postcode_key(pc):
    """Zoek de exacte CBS-sleutel op voor een postcode (bijv. 'PC2011  ')."""
    alle = fetch(f"{BASE}/83502NED/Postcode?$format=json")
    for item in alle:
        if item.get("Title", "").strip() == pc:
            return item["Key"]  # inclusief trailing spaces
    return None

@st.cache_data(ttl=3600)
def get_plaatsnaam(pc):
    """Haal plaatsnaam op via de gratis PDOK Locatieserver."""
    try:
        r = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest",
            params={"q": pc, "fq": "type:postcode", "rows": 1},
            timeout=5
        )
        if r.status_code == 200:
            docs = r.json().get("response", {}).get("docs", [])
            if docs:
                naam = docs[0].get("weergavenaam", "")
                # Formaat: "1234, Plaatsnaam" of "1234AB Plaatsnaam, Gemeente"
                parts = [p.strip() for p in naam.split(",")]
                # Pak het tweede deel als plaatsnaam
                if len(parts) >= 2:
                    return parts[1].strip()
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600)
def get_leeftijd_data(pc_key, periode_key):
    """Haal leeftijdsdata op voor één postcode."""
    leeftijden_raw = fetch(f"{BASE}/83502NED/Leeftijd?$format=json")
    leeftijd_map = {l["Key"].strip(): l["Title"].strip() for l in leeftijden_raw}

    gewenste = [
        "0 tot 5 jaar","5 tot 10 jaar","10 tot 15 jaar","15 tot 20 jaar",
        "20 tot 25 jaar","25 tot 30 jaar","30 tot 35 jaar","35 tot 40 jaar",
        "40 tot 45 jaar","45 tot 50 jaar","50 tot 55 jaar","55 tot 60 jaar",
        "60 tot 65 jaar","65 tot 70 jaar","70 tot 75 jaar","75 tot 80 jaar",
        "80 tot 85 jaar","85 tot 90 jaar","90 jaar of ouder",
    ]
    leeftijd_keys = [k for k, v in leeftijd_map.items() if v in gewenste]

    geslachten_raw = fetch(f"{BASE}/83502NED/Geslacht?$format=json")
    totaal_g = next(g for g in geslachten_raw if "Totaal" in g["Title"])
    geslacht_key = totaal_g["Key"]  # bewaar trailing spaces

    resultaten = []
    for lkey in leeftijd_keys:
        obs = fetch(
            f"{BASE}/83502NED/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key}'"
            f" and Geslacht eq '{geslacht_key}'"
            f" and Postcode eq '{pc_key}'"
            f" and Leeftijd eq '{lkey}'"
            f"&$select=Leeftijd,Bevolking_1"
        )
        for row in obs:
            ltitel = leeftijd_map.get(row.get("Leeftijd", "").strip(), "")
            aantal = row.get("Bevolking_1") or 0
            if ltitel in gewenste:
                resultaten.append({"titel": ltitel, "aantal": aantal})

    return resultaten

@st.cache_data(ttl=3600)
def get_inkomen_data(pc, periode_key_i):
    """Haal inkomendata op. Tabel 85064NED gebruikt RegioS met 'PO'-prefix."""
    # Controleer beschikbare kolomnamen
    props = fetch(f"{BASE}/85064NED/DataProperties?$format=json")
    col_inw  = next((p["Key"] for p in props if "PerInwoner"          in p["Key"] and "Gemiddeld" in p.get("Title","")), None)
    col_ontv = next((p["Key"] for p in props if "PerInkomensontvanger" in p["Key"] and "Gemiddeld" in p.get("Title","")), None)
    col_med  = next((p["Key"] for p in props if "Mediaan"             in p["Key"]), None)

    if not any([col_inw, col_ontv, col_med]):
        return None, {}

    # Zoek de juiste RegioS-key in tabel 85064NED
    regio_items = fetch(f"{BASE}/85064NED/RegioS?$format=json")
    regio_key = next((r["Key"] for r in regio_items if r.get("Title","").strip() == pc), None)
    if not regio_key:
        # Probeer met PO-prefix
        regio_key = next((r["Key"] for r in regio_items if r.get("Key","").strip() == f"PO{pc}"), None)
    if not regio_key:
        return None, {}

    select = ",".join(c for c in [col_inw, col_ontv, col_med] if c)
    obs = fetch(
        f"{BASE}/85064NED/TypedDataSet?$format=json"
        f"&$filter=Perioden eq '{periode_key_i}' and RegioS eq '{regio_key}'"
        f"&$select={select}"
    )
    return (obs[0] if obs else None), {"inw": col_inw, "ontv": col_ontv, "med": col_med}


LABEL_MAP = {
    "0 tot 5 jaar":"0-5","5 tot 10 jaar":"5-10","10 tot 15 jaar":"10-15",
    "15 tot 20 jaar":"15-20","20 tot 25 jaar":"20-25","25 tot 30 jaar":"25-30",
    "30 tot 35 jaar":"30-35","35 tot 40 jaar":"35-40","40 tot 45 jaar":"40-45",
    "45 tot 50 jaar":"45-50","50 tot 55 jaar":"50-55","55 tot 60 jaar":"55-60",
    "60 tot 65 jaar":"60-65","65 tot 70 jaar":"65-70","70 tot 75 jaar":"70-75",
    "75 tot 80 jaar":"75-80","80 tot 85 jaar":"80-85","85 tot 90 jaar":"85-90",
    "90 jaar of ouder":"90+",
}
GEWICHTEN = {
    "0-5":2.5,"5-10":7.5,"10-15":12.5,"15-20":17.5,"20-25":22.5,
    "25-30":27.5,"30-35":32.5,"35-40":37.5,"40-45":42.5,"45-50":47.5,
    "50-55":52.5,"55-60":57.5,"60-65":62.5,"65-70":67.5,"70-75":72.5,
    "75-80":77.5,"80-85":82.5,"85-90":87.5,"90+":92.5,
}

# ── Input ──────────────────────────────────────────────────────────────────────
col_in, _ = st.columns([1, 3])
with col_in:
    postcode_input = st.text_input("Voer een postcode in", placeholder="bijv. 2011", max_chars=4)

if not postcode_input:
    st.info("Voer een 4-cijferige postcode in om te beginnen.")
    st.stop()

if not postcode_input.isdigit() or len(postcode_input) != 4:
    st.error("Voer precies 4 cijfers in, zonder letters.")
    st.stop()

pc = postcode_input.strip()

# Plaatsnaam + header
plaatsnaam = get_plaatsnaam(pc)
st.header(f"Postcode {pc}" + (f" — {plaatsnaam}" if plaatsnaam else ""))

# Meest recente periode ophalen
perioden = fetch(f"{BASE}/83502NED/Perioden?$format=json")
periode_key   = perioden[-1]["Key"]
periode_title = perioden[-1]["Title"].strip()

# Postcode-sleutel ophalen
with st.spinner("Postcode opzoeken..."):
    pc_key = get_postcode_key(pc)

if not pc_key:
    st.error(f"Postcode {pc} niet gevonden in CBS-data. Controleer of het een bestaande Nederlandse postcode is.")
    st.stop()

# ── Leeftijdsopbouw ────────────────────────────────────────────────────────────
with st.spinner("Leeftijdsdata ophalen..."):
    try:
        raw = get_leeftijd_data(pc_key, periode_key)

        if not raw or all(r["aantal"] == 0 for r in raw):
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
            m1.metric("Inwoners",      f"{int(totaal):,}".replace(",","."))
            m2.metric("Gem. leeftijd", f"{gem:.1f} jaar")
            m3.metric("Aandeel 65+",  f"{oud/totaal*100:.1f}%")
            m4.metric("Aandeel 0-25", f"{jong/totaal*100:.1f}%")

            st.subheader(f"Leeftijdsopbouw — {periode_title}")
            fig = px.bar(df, x="Leeftijdsgroep", y="Percentage",
                         color_discrete_sequence=["#1D9E75"], text="Percentage",
                         labels={"Percentage":"% van inwoners"})
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                              yaxis=dict(showgrid=True, gridcolor="#eee"),
                              xaxis=dict(tickangle=-45),
                              margin=dict(t=20, b=60), height=380)
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("Tabel: aantallen per leeftijdsgroep"):
                st.dataframe(df[["Leeftijdsgroep","Aantal","Percentage"]].reset_index(drop=True),
                             use_container_width=True)

    except Exception as e:
        st.error(f"Fout bij leeftijdsdata: {e}")

st.divider()

# ── Inkomen ────────────────────────────────────────────────────────────────────
with st.spinner("Inkomendata ophalen..."):
    try:
        perioden_i   = fetch(f"{BASE}/85064NED/Perioden?$format=json")
        periode_key_i   = perioden_i[-1]["Key"]
        periode_title_i = perioden_i[-1]["Title"].strip()

        row_i, cols = get_inkomen_data(pc, periode_key_i)
        if row_i:
            st.subheader(f"Inkomen — {periode_title_i}")
            ic1, ic2, ic3 = st.columns(3)
            v1 = row_i.get(cols["inw"])  if cols.get("inw")  else None
            v2 = row_i.get(cols["ontv"]) if cols.get("ontv") else None
            v3 = row_i.get(cols["med"])  if cols.get("med")  else None
            if v1: ic1.metric("Gem. inkomen per inwoner",   f"€ {int(v1*1000):,}".replace(",","."))
            if v2: ic2.metric("Gem. inkomen per ontvanger", f"€ {int(v2*1000):,}".replace(",","."))
            if v3: ic3.metric("Mediaan inkomen",            f"€ {int(v3*1000):,}".replace(",","."))
        else:
            st.info("Geen inkomendata beschikbaar voor deze postcode.")
    except Exception as e:
        st.error(f"Fout bij inkomendata: {e}")

st.divider()
st.caption("Data: CBS StatLine open data — CC BY 4.0 | App gebouwd met Streamlit")
