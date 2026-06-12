import re
import streamlit as st
import requests
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Postcode Vergelijker", page_icon="📍", layout="wide")
st.title("📍 Postcode Demografische Vergelijker")
st.caption("Bron: CBS StatLine — open data (CC BY 4.0)")

BASE     = "https://opendata.cbs.nl/ODataApi/OData/83502NED"
INK_BASE = "https://opendata.cbs.nl/ODataApi/OData/85064NED"
HH_BASE  = "https://opendata.cbs.nl/ODataApi/OData/83505NED"
HK_BASE  = "https://opendata.cbs.nl/ODataApi/OData/85640NED"

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
COLOR_NL   = "#888780"

# ── Generic fetch ──────────────────────────────────────────────────────────────
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

# ── Leeftijd meta + data ───────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_meta():
    perioden      = fetch(f"{BASE}/Perioden?$format=json")
    periode_key   = perioden[-1]["Key"]
    periode_title = perioden[-1]["Title"].strip()
    leeftijden    = fetch(f"{BASE}/Leeftijd?$format=json")
    leeftijd_map  = {l["Key"].strip(): l["Title"].strip() for l in leeftijden}
    leeftijd_keys = [k for k,v in leeftijd_map.items() if v in GEWENSTE]
    geslachten    = fetch(f"{BASE}/Geslacht?$format=json")
    geslacht_key  = next(g["Key"] for g in geslachten if "Totaal" in g["Title"])
    alle_pc       = fetch(f"{BASE}/Postcode?$format=json")
    pc_key_map    = {item["Title"].strip(): item["Key"] for item in alle_pc}
    return periode_key, periode_title, leeftijd_map, leeftijd_keys, geslacht_key, pc_key_map

@st.cache_data(ttl=3600)
def get_leeftijd_verd(pc_key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map):
    out = {}
    for lkey in leeftijd_keys:
        obs = fetch(
            f"{BASE}/TypedDataSet?$format=json"
            f"&$filter=Perioden eq '{periode_key}' and Geslacht eq '{geslacht_key}'"
            f" and Postcode eq '{pc_key}' and Leeftijd eq '{lkey}'"
            f"&$select=Leeftijd,Bevolking_1"
        )
        for row in obs:
            label = LABEL_MAP.get(leeftijd_map.get(row.get("Leeftijd","").strip(),""))
            if label:
                out[label] = out.get(label,0) + (row.get("Bevolking_1") or 0)
    return out

# ── Huishoudens ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_hh_meta():
    perioden  = fetch(f"{HH_BASE}/Perioden?$format=json")
    per_key   = perioden[-1]["Key"]
    per_title = perioden[-1]["Title"].strip()
    hh_typen  = fetch(f"{HH_BASE}/Huishoudenssamenstelling?$format=json")
    hh_map    = {h["Key"].strip(): h["Title"].strip() for h in hh_typen}
    alle_pc   = fetch(f"{HH_BASE}/Postcode?$format=json")
    pc_map    = {item["Title"].strip(): item["Key"] for item in alle_pc}
    return per_key, per_title, hh_map, pc_map

@st.cache_data(ttl=3600)
def get_hh_data(pc_key, periode_key):
    obs = fetch(
        f"{HH_BASE}/TypedDataSet?$format=json"
        f"&$filter=Perioden eq '{periode_key}' and Postcode eq '{pc_key}'"
        f"&$select=Huishoudenssamenstelling,ParticuliereHuishoudens_1,GemiddeldeHuishoudensgrootte_2"
    )
    return obs

# ── Herkomst ───────────────────────────────────────────────────────────────────
# Relevante herkomstland-categorieën (hoofdniveaus)
HK_GEWENST = {
    "Totaal": "Totaal",
    "Nederland": "Nederland",
    "Europa (exclusief Nederland)": "Europa (excl. NL)",
    "Buiten Europa": "Buiten Europa",
    "Afrika": "Afrika",
    "Amerika": "Amerika",
    "Azië": "Azië",
    "Turkije": "Turkije",
    "Marokko": "Marokko",
    "Suriname": "Suriname",
}

@st.cache_data(ttl=3600)
def get_hk_meta():
    perioden   = fetch(f"{HK_BASE}/Perioden?$format=json")
    per_key    = perioden[-1]["Key"]
    per_title  = perioden[-1]["Title"].strip()
    hk_landen  = fetch(f"{HK_BASE}/Herkomstland?$format=json")
    hk_map     = {h["Key"].strip(): h["Title"].strip() for h in hk_landen}
    gb_landen  = fetch(f"{HK_BASE}/Geboorteland?$format=json")
    # Gebruik "Totaal" geboorteland
    gb_totaal  = next((g["Key"] for g in gb_landen if "Totaal" in g["Title"]), None)
    geslachten = fetch(f"{HK_BASE}/Geslacht?$format=json")
    gsl_key    = next(g["Key"] for g in geslachten if "Totaal" in g["Title"])
    alle_pc    = fetch(f"{HK_BASE}/Postcode?$format=json")
    pc_map     = {item["Title"].strip(): item["Key"] for item in alle_pc}
    return per_key, per_title, hk_map, gb_totaal, gsl_key, pc_map

@st.cache_data(ttl=3600)
def get_hk_data(pc_key, periode_key, gb_totaal, gsl_key, hk_map):
    obs = fetch(
        f"{HK_BASE}/TypedDataSet?$format=json"
        f"&$filter=Perioden eq '{periode_key}'"
        f" and Geboorteland eq '{gb_totaal}'"
        f" and Geslacht eq '{gsl_key}'"
        f" and Postcode eq '{pc_key}'"
        f"&$select=Herkomstland,Bevolking_1"
    )
    result = {}
    for row in obs:
        hkey  = row.get("Herkomstland","").strip()
        titel = hk_map.get(hkey,"")
        if titel in HK_GEWENST:
            label = HK_GEWENST[titel]
            result[label] = (row.get("Bevolking_1") or 0)
    return result

# ── PDOK ───────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_locatie(pc):
    try:
        r = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
            params={"q": pc, "fq": "type:postcode", "rows": 1, "fl": "woonplaatsnaam,gemeentenaam"},
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

# ── INPUT ──────────────────────────────────────────────────────────────────────
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

titel = f"Analyse voor {woonplaats}" if woonplaats else f"Analyse voor {', '.join(pcs)}"
if gemeente and gemeente != woonplaats:
    titel += f" (gemeente {gemeente})"
st.subheader(titel)

stad_pcs = []
if woonplaats:
    with st.spinner(f"Postcodes van {woonplaats} ophalen..."):
        stad_pcs = get_postcodes_van_stad(woonplaats)

st.caption(f"Peiljaar: {periode_title} | {woonplaats}: {len(stad_pcs)} postcodes | Nederland: CBS totaalcijfer")

# Leeftijdsdata ophalen
alle_nodig = list(set(pcs + stad_pcs))
verdelingen = {}
progress = st.progress(0, text="Leeftijdsdata ophalen...")
for i, pc in enumerate(alle_nodig):
    progress.progress((i+1)/len(alle_nodig), text=f"Postcode {pc}...")
    key = pc_key_map.get(pc)
    if not key: continue
    v = get_leeftijd_verd(key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map)
    if v: verdelingen[pc] = v

nl_verd = {}
with st.spinner("Nederland ophalen..."):
    nl_key = pc_key_map.get("Nederland")
    if nl_key:
        nl_verd = get_leeftijd_verd(nl_key, periode_key, geslacht_key, leeftijd_keys, leeftijd_map)
progress.empty()

gevonden = [pc for pc in pcs if pc in verdelingen]
if not gevonden:
    st.error("Geen data gevonden voor de ingevoerde postcodes.")
    st.stop()

stad_verd = combineer([verdelingen[pc] for pc in stad_pcs if pc in verdelingen])

benchmarks = []
for i, pc in enumerate(gevonden):
    benchmarks.append((f"Postcode {pc}", verdelingen[pc], COLORS_PC[i % len(COLORS_PC)]))
if stad_verd:
    benchmarks.append((f"⌀ {woonplaats}", stad_verd, COLOR_STAD))
if nl_verd:
    benchmarks.append(("⌀ Nederland", nl_verd, COLOR_NL))

# ── TABS ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["👥 Leeftijd", "🏠 Huishoudens", "🌍 Herkomst", "💶 Inkomen"])

# ════════════════════════════════════════════════════════════
with tab1:
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

    st.divider()
    st.subheader("Leeftijdsopbouw")
    kleurmap      = {lbl: klr for lbl,_,klr in benchmarks}
    reeksvolgorde = [lbl for lbl,_,_ in benchmarks]
    plot_data = []
    for label, verd, _ in benchmarks:
        p = pct(verd)
        for lbl in LABELS_VOLGORDE:
            plot_data.append({"Leeftijdsgroep":lbl,"Percentage":round(p.get(lbl,0),1),"Reeks":label})

    fig = px.bar(pd.DataFrame(plot_data), x="Leeftijdsgroep", y="Percentage",
                 color="Reeks", barmode="group", color_discrete_map=kleurmap,
                 category_orders={"Reeks":reeksvolgorde},
                 labels={"Percentage":"% van inwoners"}, height=420)
    fig.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                      yaxis=dict(showgrid=True, gridcolor="#eee"),
                      xaxis=dict(tickangle=-45),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02),
                      margin=dict(t=60, b=60))
    st.plotly_chart(fig, use_container_width=True)

    # Afwijking
    ref_opties = []
    if nl_verd:   ref_opties.append("⌀ Nederland")
    if stad_verd: ref_opties.append(f"⌀ {woonplaats}")
    if ref_opties:
        st.divider()
        ref_keuze = st.radio("Afwijking t.o.v.:", ref_opties, horizontal=True)
        ref_verd  = {"⌀ Nederland": nl_verd, f"⌀ {woonplaats}": stad_verd}.get(ref_keuze, nl_verd)
        st.caption("Positief = hogere concentratie dan referentie, negatief = lager")
        pct_ref  = pct(ref_verd)
        afw_data = []
        for pc in gevonden:
            p = pct(verdelingen[pc])
            for lbl in LABELS_VOLGORDE:
                afw_data.append({"Leeftijdsgroep": lbl,
                                 "Afwijking (%-punt)": round(p.get(lbl,0)-pct_ref.get(lbl,0),1),
                                 "Postcode": f"Postcode {pc}"})
        fig2 = px.bar(pd.DataFrame(afw_data), x="Leeftijdsgroep", y="Afwijking (%-punt)",
                      color="Postcode", barmode="group",
                      color_discrete_map={f"Postcode {pc}": COLORS_PC[i%len(COLORS_PC)]
                                          for i,pc in enumerate(gevonden)}, height=360)
        fig2.add_hline(y=0, line_color="#333", line_width=1)
        fig2.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                           yaxis=dict(showgrid=True, gridcolor="#eee", zeroline=False),
                           xaxis=dict(tickangle=-45),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02),
                           margin=dict(t=60, b=60))
        st.plotly_chart(fig2, use_container_width=True)

# ════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Huishoudenssamenstelling")
    with st.spinner("Huishoudensdata ophalen..."):
        try:
            hh_per_key, hh_per_title, hh_map, hh_pc_map = get_hh_meta()

            hh_typen_gewenst = {
                "Eenpersoonshuishouden": "Alleenstaand",
                "Meerpersoonshuishouden met kinderen": "Gezin met kinderen",
                "Meerpersoonshuishouden zonder kinderen": "Stel/meerp. zonder kinderen",
            }

            def parse_hh_rows(rows, hh_map, hh_typen_gewenst):
                d = {}
                for row in rows:
                    hkey  = row.get("Huishoudenssamenstelling","").strip()
                    titel = hh_map.get(hkey,"")
                    if titel in hh_typen_gewenst:
                        d[hh_typen_gewenst[titel]] = row.get("ParticuliereHuishoudens_1") or 0
                    if titel == "Totaal particuliere huishoudens":
                        d["__totaal"]  = row.get("ParticuliereHuishoudens_1") or 0
                        d["__grootte"] = row.get("GemiddeldeHuishoudensgrootte_2") or 0
                return d

            # Postcodes ophalen
            hh_resultaten = {}
            for pc in gevonden:
                pc_key = hh_pc_map.get(pc)
                if not pc_key: continue
                rows = get_hh_data(pc_key, hh_per_key)
                if rows: hh_resultaten[pc] = parse_hh_rows(rows, hh_map, hh_typen_gewenst)

            # Nederland ophalen
            nl_hh = {}
            nl_hh_key = hh_pc_map.get("Nederland")
            if nl_hh_key:
                nl_rows = get_hh_data(nl_hh_key, hh_per_key)
                if nl_rows: nl_hh = parse_hh_rows(nl_rows, hh_map, hh_typen_gewenst)

            if hh_resultaten:
                # Kerncijfers — postcodes + NL naast elkaar
                alle_labels = list(gevonden) + (["⌀ Nederland"] if nl_hh else [])
                hh_cols = st.columns(len(alle_labels))
                for i, label in enumerate(alle_labels):
                    is_nl = label == "⌀ Nederland"
                    d = nl_hh if is_nl else hh_resultaten.get(label.replace("Postcode ","") if " " in label else label, {})
                    pc_i = label if is_nl else gevonden[i] if i < len(gevonden) else label
                    kleur = COLOR_NL if is_nl else COLORS_PC[i % len(COLORS_PC)]
                    with hh_cols[i]:
                        st.markdown(f"<span style='color:{kleur};font-weight:500'>{label if is_nl else f'Postcode {pc_i}'}</span>",
                                    unsafe_allow_html=True)
                        st.metric("Totaal huishoudens", f"{int(d.get('__totaal',0)):,}".replace(",","."))
                        st.metric("Gem. grootte", f"{d.get('__grootte',0):.1f} pers.")

                st.divider()
                # Staafgrafiek — postcodes + NL
                hh_plot = []
                reeksen = []
                kleurmap_hh = {}
                for i, pc in enumerate(gevonden):
                    if pc not in hh_resultaten: continue
                    d = hh_resultaten[pc]
                    tot = d.get("__totaal", 1) or 1
                    label = f"Postcode {pc}"
                    reeksen.append(label)
                    kleurmap_hh[label] = COLORS_PC[i % len(COLORS_PC)]
                    for typ in hh_typen_gewenst.values():
                        hh_plot.append({"Type": typ, "Percentage": round(d.get(typ,0)/tot*100,1), "Reeks": label})

                if nl_hh:
                    tot_nl = nl_hh.get("__totaal", 1) or 1
                    reeksen.append("⌀ Nederland")
                    kleurmap_hh["⌀ Nederland"] = COLOR_NL
                    for typ in hh_typen_gewenst.values():
                        hh_plot.append({"Type": typ, "Percentage": round(nl_hh.get(typ,0)/tot_nl*100,1), "Reeks": "⌀ Nederland"})

                fig_hh = px.bar(pd.DataFrame(hh_plot), x="Type", y="Percentage",
                                color="Reeks", barmode="group",
                                color_discrete_map=kleurmap_hh,
                                category_orders={"Reeks": reeksen},
                                labels={"Percentage":"% van huishoudens"}, height=400)
                fig_hh.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                                     yaxis=dict(showgrid=True, gridcolor="#eee"),
                                     legend=dict(orientation="h", yanchor="bottom", y=1.02),
                                     margin=dict(t=60, b=40))
                st.plotly_chart(fig_hh, use_container_width=True)

                # Taartdiagrammen per postcode (max 3)
                pie_targets = gevonden[:3]
                if pie_targets:
                    pie_cols = st.columns(len(pie_targets))
                    for i, pc in enumerate(pie_targets):
                        if pc not in hh_resultaten: continue
                        d = hh_resultaten[pc]
                        pie_data = {k: v for k,v in d.items() if not k.startswith("__")}
                        fig_pie = px.pie(names=list(pie_data.keys()), values=list(pie_data.values()),
                                         title=f"Postcode {pc}",
                                         color_discrete_sequence=["#1D9E75","#185FA5","#BA7517"],
                                         hole=0.4)
                        fig_pie.update_layout(margin=dict(t=40,b=20), height=280)
                        pie_cols[i].plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Geen huishoudensdata beschikbaar voor deze postcode(s).")
        except Exception as e:
            st.error(f"Fout bij huishoudensdata: {e}")

# ════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Herkomst bevolking")
    with st.spinner("Herkomstdata ophalen..."):
        try:
            hk_per_key, hk_per_title, hk_map, gb_totaal, gsl_key, hk_pc_map = get_hk_meta()
            cat_order = ["Nederland", "Europa (excl. NL)", "Turkije", "Marokko",
                         "Suriname", "Afrika", "Amerika", "Azië"]

            hk_resultaten = {}
            for pc in gevonden:
                pc_key = hk_pc_map.get(pc)
                if not pc_key: continue
                rows = get_hk_data(pc_key, hk_per_key, gb_totaal, gsl_key, hk_map)
                if rows: hk_resultaten[pc] = rows

            # Nederland ophalen
            nl_hk = {}
            nl_hk_key = hk_pc_map.get("Nederland")
            if nl_hk_key:
                nl_hk = get_hk_data(nl_hk_key, hk_per_key, gb_totaal, gsl_key, hk_map)

            if hk_resultaten:
                # Kerncijfers — postcodes + NL
                alle_hk_labels = list(gevonden) + (["⌀ Nederland"] if nl_hk else [])
                hk_cols = st.columns(len(alle_hk_labels))
                for i, label in enumerate(alle_hk_labels):
                    is_nl = label == "⌀ Nederland"
                    d = nl_hk if is_nl else hk_resultaten.get(label, {})
                    kleur = COLOR_NL if is_nl else COLORS_PC[i % len(COLORS_PC)]
                    totaal = d.get("Totaal", 1) or 1
                    pct_nl_herkomst = d.get("Nederland",0)/totaal*100
                    pct_buiten = 100 - pct_nl_herkomst
                    with hk_cols[i]:
                        naam = "⌀ Nederland" if is_nl else f"Postcode {label}"
                        st.markdown(f"<span style='color:{kleur};font-weight:500'>{naam}</span>",
                                    unsafe_allow_html=True)
                        # Delta alleen voor postcodes t.o.v. NL
                        nl_pct_ref = nl_hk.get("Nederland",0)/(nl_hk.get("Totaal",1) or 1)*100 if nl_hk and not is_nl else None
                        delta_str = f"{pct_nl_herkomst - nl_pct_ref:+.1f}%-pt vs NL" if nl_pct_ref is not None else None
                        st.metric("Herkomst Nederland", f"{pct_nl_herkomst:.1f}%", delta=delta_str)
                        st.metric("Herkomst buiten NL", f"{pct_buiten:.1f}%")

                st.divider()
                # Gestapelde staafgrafiek — postcodes + NL
                hk_plot = []
                stacked_labels = []
                for pc in gevonden:
                    if pc not in hk_resultaten: continue
                    d = hk_resultaten[pc]
                    totaal = d.get("Totaal", 1) or 1
                    lbl = f"Postcode {pc}"
                    stacked_labels.append(lbl)
                    for cat in cat_order:
                        hk_plot.append({"Herkomst": cat, "Percentage": round(d.get(cat,0)/totaal*100,1), "Gebied": lbl})

                if nl_hk:
                    totaal_nl = nl_hk.get("Totaal", 1) or 1
                    stacked_labels.append("⌀ Nederland")
                    for cat in cat_order:
                        hk_plot.append({"Herkomst": cat, "Percentage": round(nl_hk.get(cat,0)/totaal_nl*100,1), "Gebied": "⌀ Nederland"})

                fig_hk = px.bar(pd.DataFrame(hk_plot), x="Gebied", y="Percentage",
                                color="Herkomst", barmode="stack",
                                category_orders={"Herkomst": cat_order, "Gebied": stacked_labels},
                                color_discrete_sequence=px.colors.qualitative.Safe,
                                labels={"Percentage":"% van inwoners"}, height=420)
                fig_hk.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                                     yaxis=dict(showgrid=True, gridcolor="#eee"),
                                     legend=dict(orientation="h", yanchor="bottom", y=1.02),
                                     margin=dict(t=60, b=40))
                st.plotly_chart(fig_hk, use_container_width=True)

                # Detailtabel
                with st.expander("Tabel: percentages per herkomstcategorie"):
                    tabel_rows = []
                    for pc in gevonden:
                        if pc not in hk_resultaten: continue
                        d = hk_resultaten[pc]
                        tot = d.get("Totaal",1) or 1
                        for cat in cat_order:
                            row = {"Gebied": f"Postcode {pc}", "Herkomst": cat,
                                   "Aantal": d.get(cat,0), "%": round(d.get(cat,0)/tot*100,1)}
                            tabel_rows.append(row)
                    if nl_hk:
                        tot_nl = nl_hk.get("Totaal",1) or 1
                        for cat in cat_order:
                            tabel_rows.append({"Gebied": "⌀ Nederland", "Herkomst": cat,
                                               "Aantal": nl_hk.get(cat,0), "%": round(nl_hk.get(cat,0)/tot_nl*100,1)})
                    st.dataframe(pd.DataFrame(tabel_rows), use_container_width=True)
            else:
                st.info("Geen herkomstdata beschikbaar voor deze postcode(s).")
        except Exception as e:
            st.error(f"Fout bij herkomstdata: {e}")

# ════════════════════════════════════════════════════════════
with tab4:
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
            st.markdown(f"<span style='color:{COLORS_PC[i%len(COLORS_PC)]};font-weight:500'>Postcode {pc}</span>",
                        unsafe_allow_html=True)
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
