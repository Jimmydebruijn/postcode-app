import re
import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Postcode Vergelijker", page_icon="📍", layout="wide")
st.title("📍 Postcode Demografische Vergelijker")
st.caption("Bron: CBS StatLine — open data (CC BY 4.0)")

BASE     = "https://opendata.cbs.nl/ODataApi/OData"
BASE_OLD = "https://opendata.cbs.nl/ODataFeed/OData"

LABEL_MAP = {
    "0 tot 5 jaar":"0-5","5 tot 10 jaar":"5-10","10 tot 15 jaar":"10-15",
    "15 tot 20 jaar":"15-20","20 tot 25 jaar":"20-25","25 tot 30 jaar":"25-30",
    "30 tot 35 jaar":"30-35","35 tot 40 jaar":"35-40","40 tot 45 jaar":"40-45",
    "45 tot 50 jaar":"45-50","50 tot 55 jaar":"50-55","55 tot 60 jaar":"55-60",
    "60 tot 65 jaar":"60-65","65 tot 70 jaar":"65-70","70 tot 75 jaar":"70-75",
    "75 tot 80 jaar":"75-80","80 tot 85 jaar":"80-85","85 tot 90 jaar":"85-90",
    "90 jaar of ouder":"90+",
}
GEWENSTE = list(LABEL_MAP.keys())
GEWICHTEN = {
    "0-5":2.5,"5-10":7.5,"10-15":12.5,"15-20":17.5,"20-25":22.5,
    "25-30":27.5,"30-35":32.5,"35-40":37.5,"40-45":42.5,"45-50":47.5,
    "50-55":52.5,"55-60":57.5,"60-65":62.5,"65-70":67.5,"70-75":72.5,
    "75-80":77.5,"80-85":82.5,"85-90":87.5,"90+":92.5,
}
LABELS_VOLGORDE = list(LABEL_MAP.values())

# Kleurpalet: postcodes = groen/paars/oranje, stad = blauw, provincie = amber, NL = grijs
COLORS_PC   = ["#1D9E75","#534AB7","#D85A30","#378ADD","#993556"]
COLOR_STAD  = "#185FA5"
COLOR_PROV  = "#BA7517"
COLOR_NL    = "#888780"

# ── CBS helpers ────────────────────────────────────────────────────────────────
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
def get_cbs_meta():
    perioden      = fetch(f"{BASE}/83502NED/Perioden?$format=json")
    periode_key   = perioden[-1]["Key"]
    periode_title = perioden[-1]["Title"].strip()
    leeftijden_raw = fetch(f"{BASE}/83502NED/Leeftijd?$format=json")
    leeftijd_map   = {l["Key"].strip(): l["Title"].strip() for l in leeftijden_raw}
    leeftijd_keys  = [k for k, v in leeftijd_map.items() if v in GEWENSTE]
    geslachten_raw = fetch(f"{BASE}/83502NED/Geslacht?$format=json")
    geslacht_key   = next(g["Key"] for g in geslachten_raw if "Totaal" in g["Title"])
    alle_pc        = fetch(f"{BASE}/83502NED/Postcode?$format=json")
    pc_key_map     = {item["Title"].strip(): item["Key"] for item in alle_pc}
    return periode_key, periode_title, leeftijd_map, leeftijd_keys, geslacht_key, pc_key_map

@st.cache_data(ttl=3600)
def get_leeftijd_voor_pc(pc_key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map):
    resultaten = {}
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
            ltitel = leeftijd_map.get(row.get("Leeftijd","").strip(),"")
            label  = LABEL_MAP.get(ltitel)
            if label:
                resultaten[label] = resultaten.get(label, 0) + (row.get("Bevolking_1") or 0)
    return resultaten

@st.cache_data(ttl=3600)
def get_regio_leeftijd(regio_key, jaar="2025"):
    """
    Haal leeftijdsverdeling op uit tabel 03759ned (provincie/NL niveau).
    regio_key: bijv. 'NL01 ' of 'PV27 ' (inclusief trailing space zoals CBS ze opslaat)
    """
    # Meest recente periode ophalen
    perioden = fetch(f"{BASE_OLD}/03759ned/Perioden?$format=json")
    periode_key = perioden[-1]["Key"]

    # Leeftijdsklassen en geslacht ophalen
    leeftijden_raw = fetch(f"{BASE_OLD}/03759ned/Leeftijd?$format=json")
    leeftijd_map_r = {l["Key"].strip(): l["Title"].strip() for l in leeftijden_raw}
    leeftijd_keys_r = [k for k, v in leeftijd_map_r.items() if v in GEWENSTE]

    geslachten_raw = fetch(f"{BASE_OLD}/03759ned/Geslacht?$format=json")
    geslacht_key_r = next(g["Key"] for g in geslachten_raw if "Totaal" in g["Title"])

    # Kolomnaam ophalen
    props = fetch(f"{BASE_OLD}/03759ned/DataProperties?$format=json")
    bev_col = next((p["Key"] for p in props if p.get("Type") == "Topic" and "Bevolking" in p.get("Title","")), None)
    if not bev_col:
        bev_col = next((p["Key"] for p in props if p.get("Type") == "Topic"), None)

    resultaten = {}
    for lkey in leeftijd_keys_r:
        obs = fetch(
            f"{BASE_OLD}/03759ned/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key}'"
            f" and Geslacht eq '{geslacht_key_r}'"
            f" and RegioS eq '{regio_key}'"
            f" and Leeftijd eq '{lkey}'"
            f"&$select=Leeftijd,{bev_col}"
        )
        for row in obs:
            ltitel = leeftijd_map_r.get(row.get("Leeftijd","").strip(),"")
            label  = LABEL_MAP.get(ltitel)
            if label:
                resultaten[label] = resultaten.get(label, 0) + (row.get(bev_col) or 0)
    return resultaten

@st.cache_data(ttl=3600)
def get_alle_regios_03759():
    """Geef alle RegioS-keys terug zodat we provincie kunnen opzoeken op naam."""
    items = fetch(f"{BASE_OLD}/03759ned/RegioS?$format=json")
    return {item["Title"].strip(): item["Key"] for item in items}

# ── PDOK helpers ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_stad_info(pc):
    try:
        r = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
            params={"q": pc, "fq": "type:postcode", "rows": 1,
                    "fl": "woonplaatsnaam,gemeentenaam,provincienaam"},
            timeout=8
        )
        if r.status_code == 200:
            docs = r.json().get("response", {}).get("docs", [])
            if docs:
                return (docs[0].get("woonplaatsnaam",""),
                        docs[0].get("gemeentenaam",""),
                        docs[0].get("provincienaam",""))
    except Exception:
        pass
    return None, None, None

@st.cache_data(ttl=3600)
def get_alle_postcodes_van_stad(woonplaats):
    alle, start = [], 0
    while True:
        try:
            r = requests.get(
                "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
                params={"q": woonplaats, "fq": "type:postcode",
                        "fl": "weergavenaam,woonplaatsnaam", "rows": 100, "start": start},
                timeout=10
            )
            if r.status_code != 200:
                break
            data = r.json().get("response", {})
            docs = data.get("docs", [])
            if not docs:
                break
            for d in docs:
                if d.get("woonplaatsnaam","").lower() == woonplaats.lower():
                    match = re.search(r'\b(\d{4})[A-Z]{2}\b', d.get("weergavenaam",""))
                    if match:
                        alle.append(match.group(1))
            if start + 100 >= data.get("numFound", 0):
                break
            start += 100
        except Exception:
            break
    return sorted(set(alle))

# ── Hulpfuncties ───────────────────────────────────────────────────────────────
def bereken_stats(verd):
    if not verd:
        return None
    totaal = sum(verd.values())
    if totaal == 0:
        return None
    gem  = sum(GEWICHTEN[k] * v for k, v in verd.items()) / totaal
    jong = sum(v for k, v in verd.items() if k in ["0-5","5-10","10-15","15-20","20-25"])
    oud  = sum(v for k, v in verd.items() if k in ["65-70","70-75","75-80","80-85","85-90","90+"])
    return {"totaal": totaal, "gem_leeftijd": gem,
            "pct_65plus": oud/totaal*100, "pct_0_25": jong/totaal*100}

def combineer(verdelingen):
    totaal = {}
    for v in verdelingen:
        for k, a in v.items():
            totaal[k] = totaal.get(k, 0) + a
    return totaal

def pct_verd(verd):
    tot = sum(verd.values())
    if tot == 0:
        return {}
    return {k: v/tot*100 for k, v in verd.items()}

# ── UI ─────────────────────────────────────────────────────────────────────────
st.markdown("Voer één of meerdere 4-cijferige postcodes in, gescheiden door komma's.")
col_in, _ = st.columns([2, 2])
with col_in:
    invoer = st.text_input("Postcodes", placeholder="bijv. 2011, 2012, 2013",
                           label_visibility="collapsed")

if not invoer.strip():
    st.info("Voer minimaal één postcode in om te beginnen.")
    st.stop()

ingevoerde_pcs = [p.strip() for p in invoer.split(",")
                  if p.strip().isdigit() and len(p.strip()) == 4]
if not ingevoerde_pcs:
    st.error("Vul geldige 4-cijferige postcodes in, gescheiden door komma's.")
    st.stop()

# ── Metadata & locatie ─────────────────────────────────────────────────────────
with st.spinner("CBS metadata laden..."):
    periode_key, periode_title, leeftijd_map, leeftijd_keys, geslacht_key, pc_key_map = get_cbs_meta()

with st.spinner(f"Locatie detecteren voor {ingevoerde_pcs[0]}..."):
    woonplaats, gemeente, provincie = get_stad_info(ingevoerde_pcs[0])

titel = f"Analyse voor {woonplaats}" if woonplaats else f"Analyse voor {', '.join(ingevoerde_pcs)}"
if gemeente and gemeente != woonplaats:
    titel += f" (gemeente {gemeente})"
st.subheader(titel)

# ── Alle data ophalen ──────────────────────────────────────────────────────────
stad_pcs = []
if woonplaats:
    with st.spinner(f"Alle postcodes van {woonplaats} ophalen..."):
        stad_pcs = get_alle_postcodes_van_stad(woonplaats)
    st.caption(f"Stadsgemiddelde: {len(stad_pcs)} postcodes in {woonplaats} | "
               f"Provincie: {provincie or '—'} | Peiljaar: {periode_title}")

alle_pcs_nodig = list(set(ingevoerde_pcs + stad_pcs))
verdelingen = {}
ontbrekend  = []

progress = st.progress(0, text="Postcode data ophalen...")
for i, pc in enumerate(alle_pcs_nodig):
    progress.progress((i+1)/len(alle_pcs_nodig), text=f"Postcode {pc}...")
    pc_key = pc_key_map.get(pc)
    if not pc_key:
        if pc in ingevoerde_pcs:
            ontbrekend.append(pc)
        continue
    verd = get_leeftijd_voor_pc(pc_key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map)
    if verd:
        verdelingen[pc] = verd
progress.empty()

# Provincie + NL data
prov_verd, nl_verd = {}, {}
regio_map = {}
with st.spinner("Provincie & landelijk gemiddelde ophalen..."):
    try:
        regio_map = get_alle_regios_03759()
        # Nederland
        nl_key = regio_map.get("Nederland")
        if nl_key:
            nl_verd = get_regio_leeftijd(nl_key)
        # Provincie
        if provincie:
            prov_key = regio_map.get(provincie)
            if prov_key:
                prov_verd = get_regio_leeftijd(prov_key)
    except Exception as e:
        st.warning(f"Provincie/NL data kon niet worden opgehaald: {e}")

if ontbrekend:
    st.warning(f"Niet gevonden in CBS: {', '.join(ontbrekend)}")

gevonden_pcs = [pc for pc in ingevoerde_pcs if pc in verdelingen]
if not gevonden_pcs:
    st.error("Geen data gevonden voor de ingevoerde postcodes.")
    st.stop()

stad_verd = combineer([verdelingen[pc] for pc in stad_pcs if pc in verdelingen]) if stad_pcs else {}

# ── KPI-kaarten ────────────────────────────────────────────────────────────────
st.divider()
st.subheader(f"Kerncijfers — {periode_title}")

# Bouw de benchmarks op
benchmarks = []
for pc in gevonden_pcs:
    benchmarks.append((f"Postcode {pc}", verdelingen[pc], COLORS_PC[gevonden_pcs.index(pc) % len(COLORS_PC)]))
if stad_verd:
    benchmarks.append((f"⌀ {woonplaats}", stad_verd, COLOR_STAD))
if prov_verd:
    benchmarks.append((f"⌀ {provincie}", prov_verd, COLOR_PROV))
if nl_verd:
    benchmarks.append(("⌀ Nederland", nl_verd, COLOR_NL))

cols = st.columns(len(benchmarks))
for i, (label, verd, kleur) in enumerate(benchmarks):
    stat = bereken_stats(verd)
    if stat:
        with cols[i]:
            st.markdown(f"<span style='color:{kleur};font-weight:500'>{label}</span>",
                        unsafe_allow_html=True)
            st.metric("Inwoners",      f"{int(stat['totaal']):,}".replace(",","."))
            st.metric("Gem. leeftijd", f"{stat['gem_leeftijd']:.1f} jaar")
            st.metric("Aandeel 65+",  f"{stat['pct_65plus']:.1f}%")
            st.metric("Aandeel 0-25", f"{stat['pct_0_25']:.1f}%")

# ── Leeftijdsopbouw vergelijking ───────────────────────────────────────────────
st.divider()
st.subheader("Leeftijdsopbouw vergelijking")

plot_data = []
for label, verd, _ in benchmarks:
    pct = pct_verd(verd)
    for lbl in LABELS_VOLGORDE:
        plot_data.append({"Leeftijdsgroep": lbl, "Percentage": round(pct.get(lbl,0),1), "Reeks": label})

df_plot   = pd.DataFrame(plot_data)
kleurmap  = {label: kleur for label, _, kleur in benchmarks}
reeksvolgorde = [b[0] for b in benchmarks]

fig = px.bar(df_plot, x="Leeftijdsgroep", y="Percentage", color="Reeks",
             barmode="group", color_discrete_map=kleurmap,
             category_orders={"Reeks": reeksvolgorde},
             labels={"Percentage":"% van inwoners"}, height=440)
fig.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    yaxis=dict(showgrid=True, gridcolor="#eee"),
    xaxis=dict(tickangle=-45),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(t=60, b=60),
)
st.plotly_chart(fig, use_container_width=True)

# ── Afwijking t.o.v. Nederland ─────────────────────────────────────────────────
if nl_verd:
    st.divider()

    # Kies referentie voor afwijkingsgrafiek
    referentie_opties = []
    if nl_verd:   referentie_opties.append("⌀ Nederland")
    if prov_verd: referentie_opties.append(f"⌀ {provincie}")
    if stad_verd: referentie_opties.append(f"⌀ {woonplaats}")

    ref_keuze = st.radio("Afwijking t.o.v.:", referentie_opties, horizontal=True)
    ref_verd  = {"⌀ Nederland": nl_verd,
                 f"⌀ {provincie}": prov_verd,
                 f"⌀ {woonplaats}": stad_verd}.get(ref_keuze, nl_verd)

    st.caption("Positief = hogere concentratie dan referentie, negatief = lager")
    pct_ref = pct_verd(ref_verd)
    afw_data = []
    for pc in gevonden_pcs:
        pct_pc = pct_verd(verdelingen[pc])
        for lbl in LABELS_VOLGORDE:
            afw_data.append({
                "Leeftijdsgroep": lbl,
                "Afwijking (%-punt)": round(pct_pc.get(lbl,0) - pct_ref.get(lbl,0), 1),
                "Postcode": f"Postcode {pc}",
            })

    df_afw   = pd.DataFrame(afw_data)
    kleur_afw = {f"Postcode {pc}": COLORS_PC[i % len(COLORS_PC)]
                 for i, pc in enumerate(gevonden_pcs)}

    fig2 = px.bar(df_afw, x="Leeftijdsgroep", y="Afwijking (%-punt)", color="Postcode",
                  barmode="group", color_discrete_map=kleur_afw, height=380)
    fig2.add_hline(y=0, line_color="#333", line_width=1)
    fig2.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(showgrid=True, gridcolor="#eee", zeroline=False),
        xaxis=dict(tickangle=-45),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=60),
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── Inkomen ────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Inkomen")

@st.cache_data(ttl=3600)
def get_inkomen(pc):
    props = fetch(f"{BASE}/85064NED/DataProperties?$format=json")
    col_inw  = next((p["Key"] for p in props if "PerInwoner"          in p["Key"] and "Gemiddeld" in p.get("Title","")), None)
    col_ontv = next((p["Key"] for p in props if "PerInkomensontvanger" in p["Key"] and "Gemiddeld" in p.get("Title","")), None)
    col_med  = next((p["Key"] for p in props if "Mediaan"             in p["Key"]), None)
    if not any([col_inw, col_ontv, col_med]):
        return None, {}
    perioden_i    = fetch(f"{BASE}/85064NED/Perioden?$format=json")
    periode_key_i = perioden_i[-1]["Key"]
    regio_items   = fetch(f"{BASE}/85064NED/RegioS?$format=json")
    regio_key     = next((r["Key"] for r in regio_items if r.get("Title","").strip() == pc), None)
    if not regio_key:
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

ink_cols = st.columns(len(gevonden_pcs))
for i, pc in enumerate(gevonden_pcs):
    with ink_cols[i]:
        with st.spinner(f"Inkomen {pc}..."):
            row_i, cols_i = get_inkomen(pc)
        st.markdown(f"**Postcode {pc}**")
        if row_i:
            v1 = row_i.get(cols_i["inw"])  if cols_i.get("inw")  else None
            v2 = row_i.get(cols_i["ontv"]) if cols_i.get("ontv") else None
            v3 = row_i.get(cols_i["med"])  if cols_i.get("med")  else None
            if v1: st.metric("Gem. per inwoner",   f"€ {int(v1*1000):,}".replace(",","."))
            if v2: st.metric("Gem. per ontvanger", f"€ {int(v2*1000):,}".replace(",","."))
            if v3: st.metric("Mediaan",            f"€ {int(v3*1000):,}".replace(",","."))
        else:
            st.info("Geen data")

st.divider()
st.caption("Data: CBS StatLine (CC BY 4.0) | Geodata: PDOK Locatieserver | App gebouwd met Streamlit")
