import re
import streamlit as st
import requests
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Postcode Vergelijker", page_icon="📍", layout="wide")
st.title("📍 Postcode Demografische Vergelijker")
st.caption("Bron: CBS StatLine 83502NED — open data (CC BY 4.0)")

BASE    = "https://opendata.cbs.nl/ODataApi/OData/83502NED"
INK_BASE = "https://opendata.cbs.nl/ODataApi/OData/85064NED"

LABEL_MAP = {
    "0 tot 5 jaar":"0-5","5 tot 10 jaar":"5-10","10 tot 15 jaar":"10-15",
    "15 tot 20 jaar":"15-20","20 tot 25 jaar":"20-25","25 tot 30 jaar":"25-30",
    "30 tot 35 jaar":"30-35","35 tot 40 jaar":"35-40","40 tot 45 jaar":"40-45",
    "45 tot 50 jaar":"45-50","50 tot 55 jaar":"50-55","55 tot 60 jaar":"55-60",
    "60 tot 65 jaar":"60-65","65 tot 70 jaar":"65-70","70 tot 75 jaar":"70-75",
    "75 tot 80 jaar":"75-80","80 tot 85 jaar":"80-85","85 tot 90 jaar":"85-90",
    "90 jaar of ouder":"90+",
}
GEWENSTE        = list(LABEL_MAP.keys())
LABELS_VOLGORDE = list(LABEL_MAP.values())
GEWICHTEN = {
    "0-5":2.5,"5-10":7.5,"10-15":12.5,"15-20":17.5,"20-25":22.5,
    "25-30":27.5,"30-35":32.5,"35-40":37.5,"40-45":42.5,"45-50":47.5,
    "50-55":52.5,"55-60":57.5,"60-65":62.5,"65-70":67.5,"70-75":72.5,
    "75-80":77.5,"80-85":82.5,"85-90":87.5,"90+":92.5,
}

COLORS_PC  = ["#1D9E75","#534AB7","#D85A30","#378ADD","#993556"]
COLOR_STAD = "#185FA5"
COLOR_PROV = "#BA7517"
COLOR_NL   = "#888780"

# ── Postcode → provincie mapping (vaste ranges, geen API nodig) ────────────────
# Gebaseerd op officiële CBS/PostNL postcodegebieden per provincie
PROVINCIE_RANGES = {
    "Groningen":      [(9600, 9999)],
    "Friesland":      [(8400, 8599), (8700, 8999), (9200, 9299), (9300, 9399)],
    "Drenthe":        [(7800, 7999), (9300, 9399), (9400, 9599)],
    "Overijssel":     [(7400, 7799), (8000, 8099)],
    "Flevoland":      [(1300, 1399), (8200, 8259)],
    "Gelderland":     [(4000, 4099), (6500, 6599), (6600, 6699), (6700, 6799),
                       (6800, 6899), (6900, 6999), (7000, 7399)],
    "Utrecht":        [(3400, 3799)],
    "Noord-Holland":  [(1000, 1299), (1400, 1999), (2000, 2099)],
    "Zuid-Holland":   [(2200, 2999), (3000, 3399)],
    "Zeeland":        [(4300, 4599)],
    "Noord-Brabant":  [(4600, 4999), (5000, 5599)],
    "Limburg":        [(5900, 5999), (6000, 6499)],
}

def postcode_naar_provincie(pc: str) -> str:
    """Geef de provincie terug op basis van het 4-cijferig postcodegebied."""
    try:
        num = int(pc)
    except ValueError:
        return "Onbekend"
    for prov, ranges in PROVINCIE_RANGES.items():
        for lo, hi in ranges:
            if lo <= num <= hi:
                return prov
    return "Onbekend"

# ── CBS helpers ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch(url):
    rows, nxt = [], url
    while nxt:
        r = requests.get(nxt, timeout=30)
        r.raise_for_status()
        d = r.json()
        rows.extend(d.get("value", []))
        nxt = d.get("odata.nextLink")
    return rows

@st.cache_data(ttl=3600)
def get_meta():
    perioden     = fetch(f"{BASE}/Perioden?$format=json")
    periode_key  = perioden[-1]["Key"]
    periode_title= perioden[-1]["Title"].strip()
    leeftijden   = fetch(f"{BASE}/Leeftijd?$format=json")
    leeftijd_map = {l["Key"].strip(): l["Title"].strip() for l in leeftijden}
    leeftijd_keys= [k for k,v in leeftijd_map.items() if v in GEWENSTE]
    geslachten   = fetch(f"{BASE}/Geslacht?$format=json")
    geslacht_key = next(g["Key"] for g in geslachten if "Totaal" in g["Title"])
    alle_pc      = fetch(f"{BASE}/Postcode?$format=json")
    pc_key_map   = {item["Title"].strip(): item["Key"] for item in alle_pc}
    return periode_key, periode_title, leeftijd_map, leeftijd_keys, geslacht_key, pc_key_map

@st.cache_data(ttl=3600)
def get_verd(pc_key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map):
    resultaten = {}
    for lkey in leeftijd_keys:
        obs = fetch(
            f"{BASE}/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key}'"
            f" and Geslacht eq '{geslacht_key}'"
            f" and Postcode eq '{pc_key}'"
            f" and Leeftijd eq '{lkey}'"
            f"&$select=Leeftijd,Bevolking_1"
        )
        for row in obs:
            label = LABEL_MAP.get(leeftijd_map.get(row.get("Leeftijd","").strip(),""))
            if label:
                resultaten[label] = resultaten.get(label,0) + (row.get("Bevolking_1") or 0)
    return resultaten

# ── PDOK — alleen voor stad (klein aantal postcodes) ──────────────────────────
@st.cache_data(ttl=3600)
def get_locatie(pc):
    try:
        r = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
            params={"q": pc, "fq": "type:postcode", "rows": 1,
                    "fl": "woonplaatsnaam,gemeentenaam"},
            timeout=8
        )
        if r.status_code == 200:
            docs = r.json().get("response",{}).get("docs",[])
            if docs:
                return docs[0].get("woonplaatsnaam",""), docs[0].get("gemeentenaam","")
    except Exception:
        pass
    return None, None

@st.cache_data(ttl=3600)
def get_postcodes_van_stad(woonplaats):
    alle, start = [], 0
    while True:
        try:
            r = requests.get(
                "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
                params={"q": woonplaats, "fq": "type:postcode",
                        "fl": "weergavenaam,woonplaatsnaam", "rows": 100, "start": start},
                timeout=10
            )
            if r.status_code != 200: break
            data = r.json().get("response",{})
            docs = data.get("docs",[])
            if not docs: break
            for d in docs:
                if d.get("woonplaatsnaam","").lower() == woonplaats.lower():
                    m = re.search(r'\b(\d{4})[A-Z]{2}\b', d.get("weergavenaam",""))
                    if m: alle.append(m.group(1))
            if start + 100 >= data.get("numFound",0): break
            start += 100
        except Exception:
            break
    return sorted(set(alle))

# ── Rekenhulpen ────────────────────────────────────────────────────────────────
def stats(verd):
    if not verd: return None
    tot = sum(verd.values())
    if tot == 0: return None
    gem  = sum(GEWICHTEN[k]*v for k,v in verd.items()) / tot
    jong = sum(v for k,v in verd.items() if k in ["0-5","5-10","10-15","15-20","20-25"])
    oud  = sum(v for k,v in verd.items() if k in ["65-70","70-75","75-80","80-85","85-90","90+"])
    return {"totaal":tot,"gem":gem,"p65":oud/tot*100,"p025":jong/tot*100}

def combineer(verds):
    out = {}
    for v in verds:
        for k,a in v.items(): out[k] = out.get(k,0)+a
    return out

def pct(verd):
    tot = sum(verd.values())
    return {k: v/tot*100 for k,v in verd.items()} if tot else {}

# ── UI ─────────────────────────────────────────────────────────────────────────
col_in, _ = st.columns([2,2])
with col_in:
    invoer = st.text_input("Postcodes (komma-gescheiden)",
                           placeholder="bijv. 2011, 2012, 2013",
                           label_visibility="collapsed")

if not invoer.strip():
    st.info("Voer minimaal één 4-cijferige postcode in.")
    st.stop()

pcs = [p.strip() for p in invoer.split(",") if p.strip().isdigit() and len(p.strip())==4]
if not pcs:
    st.error("Vul geldige 4-cijferige postcodes in, gescheiden door komma's.")
    st.stop()

# Meta + locatie
with st.spinner("CBS metadata laden..."):
    periode_key, periode_title, leeftijd_map, leeftijd_keys, geslacht_key, pc_key_map = get_meta()

with st.spinner("Locatie detecteren..."):
    woonplaats, gemeente = get_locatie(pcs[0])

# Provincie via lokale lookup — geen API nodig
provincie = postcode_naar_provincie(pcs[0])

titel = f"Analyse voor {woonplaats}" if woonplaats else f"Analyse voor {', '.join(pcs)}"
if gemeente and gemeente != woonplaats:
    titel += f" (gemeente {gemeente})"
st.subheader(titel)

# Stad-postcodes ophalen (PDOK, beperkt aantal)
stad_pcs = []
if woonplaats:
    with st.spinner(f"Postcodes van {woonplaats} ophalen..."):
        stad_pcs = get_postcodes_van_stad(woonplaats)

# Provincie-postcodes via lokale lookup — direct, geen API
prov_pcs = [pc for pc in pc_key_map.keys()
            if pc.isdigit() and len(pc) == 4
            and postcode_naar_provincie(pc) == provincie]

st.caption(
    f"Peiljaar: {periode_title} | "
    f"Stad ({woonplaats}): {len(stad_pcs)} postcodes | "
    f"Provincie ({provincie}): {len(prov_pcs)} postcodes | "
    f"Nederland: CBS totaalcijfer"
)

# Data ophalen — alleen unieke postcodes die we nog niet hebben
alle_nodig = list(set(pcs + stad_pcs))  # provincie & NL komen via aparte keys
verdelingen = {}
progress = st.progress(0, text="Postcode data ophalen...")
for i, pc in enumerate(alle_nodig):
    progress.progress((i+1)/len(alle_nodig), text=f"Postcode {pc}...")
    key = pc_key_map.get(pc)
    if not key: continue
    v = get_verd(key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map)
    if v: verdelingen[pc] = v

# Nederland via NL01 (één API-call)
nl_verd = {}
with st.spinner("Nederland ophalen..."):
    nl_key = pc_key_map.get("Nederland")
    if nl_key:
        nl_verd = get_verd(nl_key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map)

# Provincie: alle bekende postcodes combineren die al in CBS zitten
prov_verd = {}
with st.spinner(f"{provincie} berekenen..."):
    prov_verds = []
    for pc in prov_pcs:
        if pc in verdelingen:
            prov_verds.append(verdelingen[pc])
        else:
            key = pc_key_map.get(pc)
            if key:
                v = get_verd(key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map)
                if v:
                    verdelingen[pc] = v
                    prov_verds.append(v)
    prov_verd = combineer(prov_verds)

progress.empty()

gevonden = [pc for pc in pcs if pc in verdelingen]
if not gevonden:
    st.error("Geen data gevonden voor de ingevoerde postcodes.")
    st.stop()

stad_verd = combineer([verdelingen[pc] for pc in stad_pcs if pc in verdelingen])

# ── Benchmarks ─────────────────────────────────────────────────────────────────
benchmarks = []
for i, pc in enumerate(gevonden):
    benchmarks.append((f"Postcode {pc}", verdelingen[pc], COLORS_PC[i % len(COLORS_PC)]))
if stad_verd:
    benchmarks.append((f"⌀ {woonplaats}", stad_verd, COLOR_STAD))
if prov_verd:
    benchmarks.append((f"⌀ {provincie}", prov_verd, COLOR_PROV))
if nl_verd:
    benchmarks.append(("⌀ Nederland", nl_verd, COLOR_NL))

# ── Kerncijfers ────────────────────────────────────────────────────────────────
st.divider()
st.subheader(f"Kerncijfers — {periode_title}")
cols = st.columns(len(benchmarks))
for i, (label, verd, kleur) in enumerate(benchmarks):
    s = stats(verd)
    if s:
        with cols[i]:
            st.markdown(f"<span style='color:{kleur};font-weight:500'>{label}</span>",
                        unsafe_allow_html=True)
            st.metric("Inwoners",      f"{int(s['totaal']):,}".replace(",","."))
            st.metric("Gem. leeftijd", f"{s['gem']:.1f} jaar")
            st.metric("Aandeel 65+",  f"{s['p65']:.1f}%")
            st.metric("Aandeel 0-25", f"{s['p025']:.1f}%")

# ── Leeftijdsopbouw ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Leeftijdsopbouw vergelijking")
kleurmap      = {lbl: klr for lbl,_,klr in benchmarks}
reeksvolgorde = [lbl for lbl,_,_ in benchmarks]
plot_data = []
for label, verd, _ in benchmarks:
    p = pct(verd)
    for lbl in LABELS_VOLGORDE:
        plot_data.append({"Leeftijdsgroep":lbl,"Percentage":round(p.get(lbl,0),1),"Reeks":label})

fig = px.bar(pd.DataFrame(plot_data), x="Leeftijdsgroep", y="Percentage",
             color="Reeks", barmode="group",
             color_discrete_map=kleurmap,
             category_orders={"Reeks":reeksvolgorde},
             labels={"Percentage":"% van inwoners"}, height=440)
fig.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    yaxis=dict(showgrid=True, gridcolor="#eee"),
    xaxis=dict(tickangle=-45),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(t=60, b=60),
)
st.plotly_chart(fig, use_container_width=True)

# ── Afwijkingsgrafiek ──────────────────────────────────────────────────────────
ref_opties = []
if nl_verd:   ref_opties.append("⌀ Nederland")
if prov_verd: ref_opties.append(f"⌀ {provincie}")
if stad_verd: ref_opties.append(f"⌀ {woonplaats}")

if ref_opties:
    st.divider()
    ref_keuze = st.radio("Afwijking t.o.v.:", ref_opties, horizontal=True)
    ref_verd  = {"⌀ Nederland": nl_verd,
                 f"⌀ {provincie}": prov_verd,
                 f"⌀ {woonplaats}": stad_verd}.get(ref_keuze, nl_verd)
    st.caption("Positief = hogere concentratie dan referentie, negatief = lager")

    pct_ref  = pct(ref_verd)
    afw_data = []
    for pc in gevonden:
        p = pct(verdelingen[pc])
        for lbl in LABELS_VOLGORDE:
            afw_data.append({
                "Leeftijdsgroep": lbl,
                "Afwijking (%-punt)": round(p.get(lbl,0) - pct_ref.get(lbl,0), 1),
                "Postcode": f"Postcode {pc}",
            })

    fig2 = px.bar(pd.DataFrame(afw_data), x="Leeftijdsgroep", y="Afwijking (%-punt)",
                  color="Postcode", barmode="group",
                  color_discrete_map={f"Postcode {pc}": COLORS_PC[i%len(COLORS_PC)]
                                      for i,pc in enumerate(gevonden)},
                  height=380)
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
    props    = fetch(f"{INK_BASE}/DataProperties?$format=json")
    col_inw  = next((p["Key"] for p in props if "PerInwoner"          in p["Key"] and "Gemiddeld" in p.get("Title","")), None)
    col_ontv = next((p["Key"] for p in props if "PerInkomensontvanger" in p["Key"] and "Gemiddeld" in p.get("Title","")), None)
    col_med  = next((p["Key"] for p in props if "Mediaan"             in p["Key"]), None)
    if not any([col_inw, col_ontv, col_med]): return None, {}
    perioden_i    = fetch(f"{INK_BASE}/Perioden?$format=json")
    periode_key_i = perioden_i[-1]["Key"]
    regio_items   = fetch(f"{INK_BASE}/RegioS?$format=json")
    regio_key     = next((r["Key"] for r in regio_items if r.get("Title","").strip() == pc), None)
    if not regio_key:
        regio_key = next((r["Key"] for r in regio_items if r.get("Key","").strip() == f"PO{pc}"), None)
    if not regio_key: return None, {}
    select = ",".join(c for c in [col_inw, col_ontv, col_med] if c)
    obs = fetch(f"{INK_BASE}/TypedDataSet?$format=json"
                f"&$filter=Perioden eq '{periode_key_i}' and RegioS eq '{regio_key}'"
                f"&$select={select}")
    return (obs[0] if obs else None), {"inw":col_inw,"ontv":col_ontv,"med":col_med}

ink_cols = st.columns(len(gevonden))
for i, pc in enumerate(gevonden):
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
