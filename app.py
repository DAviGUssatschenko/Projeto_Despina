"""Agricultural Loss Diagnostic Dashboard — Copernicus satellite indices + climate data."""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import json
import math
import re
import warnings
import folium
from streamlit_folium import st_folium

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
try:
    import geopandas as gpd
    from shapely.geometry import shape
    HAS_GEO = True
except ImportError:
    HAS_GEO = False
try:
    from pystac_client import Client as STACClient
    import rioxarray
    HAS_STAC = True
except ImportError:
    HAS_STAC = False
warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="Diagnóstico Agrícola · Satélite + Clima",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');
:root {
    --bg:#0d1117; --surface:#161b22; --surface2:#21262d;
    --border:#30363d; --text:#e6edf3; --muted:#8b949e;
    --chuva:#58a6ff; --seca:#f78166; --sim:#3fb950;
    --nao:#f85149; --parcial:#d29922; --accent:#bc8cff;
}
html,body,[class*="css"]{ font-family:'DM Sans',sans-serif; }
.stApp{ background:var(--bg); color:var(--text); }
.stSidebar{ background:var(--surface) !important; border-right:1px solid var(--border); }
h1,h2,h3{ font-family:'Space Mono',monospace; }
.verdict-card{ border-radius:12px; padding:24px 28px; margin-bottom:20px; border:1px solid var(--border); }
.verdict-sim    { background:#0d2318; border-color:var(--sim); }
.verdict-nao    { background:#2d0f0e; border-color:var(--nao); }
.verdict-parcial{ background:#2b1d0e; border-color:var(--parcial); }
.badge{ display:inline-block; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; font-family:'Space Mono',monospace; }
.badge-chuva  { background:#1c2d3f; color:var(--chuva);  border:1px solid var(--chuva); }
.badge-seca   { background:#2d1f1c; color:var(--seca);   border:1px solid var(--seca); }
.badge-sim    { background:#0d2318; color:var(--sim);    border:1px solid var(--sim); }
.badge-nao    { background:#2d0f0e; color:var(--nao);    border:1px solid var(--nao); }
.badge-parcial{ background:#2b1d0e; color:var(--parcial);border:1px solid var(--parcial); }
.info-grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; margin-bottom:20px; }
.info-cell{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px 14px; }
.info-label{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.info-value{ font-size:16px; font-weight:600; font-family:'Space Mono',monospace; margin-top:4px; }
div[data-testid="stTabs"] button{ font-family:'Space Mono',monospace; font-size:13px; }
.side-title{ font-size:11px; font-weight:700; font-family:'Space Mono',monospace;
    color:#bc8cff; text-transform:uppercase; letter-spacing:.08em; margin-bottom:10px; }
</style>
""", unsafe_allow_html=True)



#constants
SOIL_WATER = {
    "Latossolo Vermelho":         {"AWC":120,"Ks":30,"fc":35,"wp":15,"retencao":"média"},
    "Latossolo Amarelo":          {"AWC":100,"Ks":25,"fc":32,"wp":14,"retencao":"média"},
    "Latossolo Vermelho-Amarelo": {"AWC":110,"Ks":28,"fc":33,"wp":14,"retencao":"média"},
    "Argissolo Vermelho":         {"AWC": 80,"Ks": 8,"fc":30,"wp":18,"retencao":"alta"},
    "Argissolo Amarelo":          {"AWC": 90,"Ks":10,"fc":31,"wp":17,"retencao":"alta"},
    "Nitossolo Vermelho":         {"AWC":130,"Ks":15,"fc":38,"wp":18,"retencao":"alta"},
    "Cambissolo Húmico":          {"AWC": 70,"Ks":20,"fc":28,"wp":13,"retencao":"média-baixa"},
    "Cambissolo Háplico":         {"AWC": 60,"Ks":18,"fc":26,"wp":12,"retencao":"média-baixa"},
    "Neossolo Litólico":          {"AWC": 30,"Ks":50,"fc":20,"wp": 8,"retencao":"baixa"},
    "Neossolo Quartzarênico":     {"AWC": 40,"Ks":80,"fc":18,"wp": 5,"retencao":"muito baixa"},
    "Neossolo Flúvico":           {"AWC":100,"Ks":15,"fc":30,"wp":15,"retencao":"alta"},
    "Gleissolo Háplico":          {"AWC":150,"Ks": 2,"fc":45,"wp":25,"retencao":"muito alta"},
    "Gleissolo Melânico":         {"AWC":160,"Ks": 1,"fc":48,"wp":26,"retencao":"muito alta"},
    "Espodossolo":                {"AWC": 50,"Ks":40,"fc":22,"wp": 8,"retencao":"baixa"},
    "Planossolo Háplico":         {"AWC": 80,"Ks": 3,"fc":32,"wp":18,"retencao":"muito alta"},
    "Vertissolo":                 {"AWC":160,"Ks": 1,"fc":48,"wp":28,"retencao":"muito alta"},
    "Chernossolo":                {"AWC":140,"Ks":12,"fc":40,"wp":20,"retencao":"alta"},
    "Organossolo":                {"AWC":200,"Ks": 2,"fc":60,"wp":30,"retencao":"muito alta"},
    "default":                    {"AWC":100,"Ks":20,"fc":30,"wp":15,"retencao":"média"},
}

SOIL_ALIASES = {
    "lv":"Latossolo Vermelho","la":"Latossolo Amarelo","lva":"Latossolo Vermelho-Amarelo",
    "pv":"Argissolo Vermelho","pa":"Argissolo Amarelo","nv":"Nitossolo Vermelho",
    "cx":"Cambissolo Háplico","ch":"Cambissolo Húmico","rl":"Neossolo Litólico",
    "rq":"Neossolo Quartzarênico","ru":"Neossolo Flúvico","gx":"Gleissolo Háplico",
    "gm":"Gleissolo Melânico","es":"Espodossolo","sg":"Planossolo Háplico",
    "vx":"Vertissolo","mt":"Chernossolo","oj":"Organossolo",
    "latossolo verm":"Latossolo Vermelho","latossolo amar":"Latossolo Amarelo",
    "argissolo":"Argissolo Vermelho","nitossolo":"Nitossolo Vermelho",
    "cambissolo":"Cambissolo Háplico","neossolo lito":"Neossolo Litólico",
    "neossolo quartz":"Neossolo Quartzarênico","gleissolo":"Gleissolo Háplico",
    "planossolo":"Planossolo Háplico","vertissolo":"Vertissolo","organossolo":"Organossolo",
}

BIOME_CLIMATE_REF = {
    "Amazônia":       {"prcp_alta":150,"prcp_baixa":60, "rh_alta":80,"rh_baixa":65,"tmax_seca":32},
    "Cerrado":        {"prcp_alta": 60,"prcp_baixa":10, "rh_alta":70,"rh_baixa":40,"tmax_seca":35},
    "Caatinga":       {"prcp_alta": 30,"prcp_baixa": 5, "rh_alta":60,"rh_baixa":35,"tmax_seca":38},
    "Mata Atlântica": {"prcp_alta": 80,"prcp_baixa":20, "rh_alta":78,"rh_baixa":60,"tmax_seca":30},
    "Pampa":          {"prcp_alta": 50,"prcp_baixa":15, "rh_alta":75,"rh_baixa":55,"tmax_seca":30},
    "Pantanal":       {"prcp_alta":100,"prcp_baixa":20, "rh_alta":75,"rh_baixa":50,"tmax_seca":35},
    "default":        {"prcp_alta": 40,"prcp_baixa":10, "rh_alta":72,"rh_baixa":50,"tmax_seca":32},
}
BIOME_ALIASES = {
    "amaz":"Amazônia","amazon":"Amazônia","cerr":"Cerrado","caat":"Caatinga",
    "mata":"Mata Atlântica","atlan":"Mata Atlântica","pamp":"Pampa","pant":"Pantanal",
}

SHEET_TO_CULTURE = {
    "trigo":"TRIGO","wheat":"TRIGO","milho":"MILHO","corn":"MILHO","maiz":"MILHO",
    "soja":"SOJA","soy":"SOJA","soybean":"SOJA","algodão":"ALGODÃO","algodao":"ALGODÃO",
    "cotton":"ALGODÃO","arroz":"ARROZ","rice":"ARROZ","feijão":"FEIJÃO","feijao":"FEIJÃO","bean":"FEIJÃO",
}

VEG_INDICES  = ["NDRE","GNDVI","SAVI","NBR"]
STRESS_INDEX = "MSI"
ALL_INDICES  = ["NDVI","NDRE","GNDVI","SAVI","NBR","MSI"]

COLORS = {"NDRE":"#58a6ff","GNDVI":"#3fb950","SAVI":"#a5f3fc",
          "NBR":"#d29922","MSI":"#f78166","NDDI":"#bc8cff"}

STATUS_LABEL = {"sim":"✅ SIM","nao":"❌ NÃO","parcial":"⚠️ PARCIAL","nd":"— N/D"}
STATUS_COLOR = {"sim":"#3fb950","nao":"#f85149","parcial":"#d29922","nd":"#8b949e"}

INDEX_META = {
    "NDRE": {"label":"NDRE", "desc":"Red Edge — vigor da vegetação",      "invert":False,"color_low":(220,50,30), "color_high":(30,180,60)},
    "GNDVI":{"label":"GNDVI","desc":"Green NDVI — biomassa verde",        "invert":False,"color_low":(220,50,30), "color_high":(30,180,60)},
    "SAVI": {"label":"SAVI", "desc":"Soil Adjusted — veg. esparsa",       "invert":False,"color_low":(220,50,30), "color_high":(30,180,60)},
    "NBR":  {"label":"NBR",  "desc":"Queimadas / recuperação",             "invert":False,"color_low":(220,50,30), "color_high":(30,180,60)},
    "MSI":  {"label":"MSI",  "desc":"Moisture Stress — estresse hídrico", "invert":True, "color_low":(30,120,200),"color_high":(220,50,30)},
    "NDVI": {"label":"NDVI", "desc":"Índice geral de vegetação",          "invert":False,"color_low":(220,50,30), "color_high":(30,180,60)},
}

#shared plotly theme
_PLOT_BASE  = dict(template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
                   font=dict(family="DM Sans", color="#e6edf3"))
_GRID_STYLE = dict(showgrid=True, gridcolor="#21262d")



#small utilities
def rgb_to_hex(c):
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"

def lerp_color(t, low, high):
    t = max(0.0, min(1.0, t))
    return (f"#{int(low[0]+(high[0]-low[0])*t):02x}"
            f"{int(low[1]+(high[1]-low[1])*t):02x}"
            f"{int(low[2]+(high[2]-low[2])*t):02x}")

def index_color(val, ts, col_name, meta):
    """Interpolated hex color for a given spectral index value."""
    col_min, col_max = float(ts[col_name].min()), float(ts[col_name].max())
    n = (val - col_min) / (col_max - col_min + 1e-9) if (col_max - col_min) > 1e-9 else 0.5
    if meta.get("invert", False): n = 1.0 - n
    return lerp_color(n, meta.get("color_low", (220,50,30)), meta.get("color_high", (30,180,60)))

def accent_color(complaint):
    return "#58a6ff" if complaint.lower() == "chuva" else "#f78166"

def biome_label(regional):
    return regional["bioma"] if regional["bioma"] != "default" else "—"

def info_cell(label, value, extra_style=""):
    return (f"<div class='info-cell'><div class='info-label'>{label}</div>"
            f"<div class='info-value' style='{extra_style}'>{value}</div></div>")



#API helpers
def _parse_openmeteo(data, rename):
    """Merge daily + hourly RH from an Open-Meteo response and rename columns."""
    df_d = pd.DataFrame(data["daily"]); df_d["time"] = pd.to_datetime(df_d["time"])
    df_h = pd.DataFrame(data["hourly"]); df_h["time"] = pd.to_datetime(df_h["time"]).dt.date
    rh   = df_h.groupby("time")["relative_humidity_2m"].mean().reset_index()
    rh["time"] = pd.to_datetime(rh["time"])
    return pd.merge(df_d, rh, on="time", how="left").rename(columns=rename)


@st.cache_data(show_spinner=False)
def fetch_climate_api(lat, lon, start_date, end_date):
    if not HAS_REQUESTS: return pd.DataFrame()
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": (start_date - pd.Timedelta(days=35)).strftime("%Y-%m-%d"),
        "end_date":   (end_date   + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
        "daily": ["precipitation_sum","temperature_2m_max","temperature_2m_min",
                  "temperature_2m_mean","et0_fao_evapotranspiration"],
        "hourly": "relative_humidity_2m", "timezone": "auto",
    }
    try:
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=30)
        if r.status_code != 200: return pd.DataFrame()
        df = _parse_openmeteo(r.json(), {
            "time":"date","precipitation_sum":"prcp","temperature_2m_max":"tmax",
            "temperature_2m_min":"tmin","temperature_2m_mean":"tavg",
            "et0_fao_evapotranspiration":"eto","relative_humidity_2m":"rh_avg",
        })
        df["wspd_avg"] = 0.0; df["point_id"] = "api"
        df["centroid_lon"] = lon; df["centroid_lat"] = lat
        return df
    except Exception: return pd.DataFrame()


@st.cache_data(show_spinner=False)
def fetch_historical_baseline_api(lat, lon, start_date):
    if not HAS_REQUESTS: return pd.DataFrame()
    hist_end   = start_date - pd.Timedelta(days=365)
    hist_start = hist_end   - pd.Timedelta(days=10*365)
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": hist_start.strftime("%Y-%m-%d"),
        "end_date":   hist_end.strftime("%Y-%m-%d"),
        "daily": ["precipitation_sum","temperature_2m_max"],
        "hourly": "relative_humidity_2m", "timezone": "auto",
    }
    try:
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=60)
        if r.status_code != 200: return pd.DataFrame()
        df = _parse_openmeteo(r.json(), {
            "time":"date","precipitation_sum":"prcp",
            "temperature_2m_max":"tmax","relative_humidity_2m":"rh_avg",
        })
        df["month"] = df["date"].dt.month
        grp = df.groupby("month").agg(
            prcp_hist_mean=("prcp","mean"), prcp_hist_std=("prcp","std"),
            tmax_hist_mean=("tmax","mean"), tmax_hist_std=("tmax","std"),
            rh_avg_hist_mean=("rh_avg","mean"), rh_avg_hist_std=("rh_avg","std"),
        ).reset_index()
        grp["point_id"] = "api"
        return grp
    except Exception: return pd.DataFrame()


@st.cache_data(show_spinner=False)
def fetch_satellite_api(geojson_feature, start_date, end_date):
    if not HAS_STAC or not HAS_GEO: return pd.DataFrame()
    start_dt = pd.to_datetime(start_date) - pd.Timedelta(days=5)
    end_dt   = pd.to_datetime(end_date)   + pd.Timedelta(days=5)
    try:
        client   = STACClient.open("https://earth-search.aws.element84.com/v1")
        geom     = shape(geojson_feature["geometry"])
        search   = client.search(
            collections=["sentinel-2-l2a"], intersects=geom,
            datetime=f"{start_dt.strftime('%Y-%m-%d')}/{end_dt.strftime('%Y-%m-%d')}",
            query={"eo:cloud_cover":{"lt":20}}, max_items=15)
        items = list(search.items())
        if not items: return pd.DataFrame()
        gdf_poly = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[geom])
        results  = []
        for item in items:
            assets = item.assets
            try:
                band_urls = {"red":assets["red"].href,"nir":assets["nir"].href,
                             "rededge":assets["rededge1"].href,"swir":assets["swir16"].href}
                means = {}
                for b, url in band_urls.items():
                    rds      = rioxarray.open_rasterio(url)
                    gdf_p    = gdf_poly.to_crs(rds.rio.crs)
                    clipped  = rds.rio.clip(gdf_p.geometry, gdf_p.crs, drop=True)
                    arr      = np.where(clipped.values==0, np.nan, clipped.values.astype(float))
                    means[b] = float(np.nanmean(arr))
                red, nir, rededge, swir = means["red"], means["nir"], means["rededge"], means["swir"]
                results.append({
                    "date":       pd.to_datetime(item.datetime.strftime("%Y-%m-%d")),
                    "NDVI_mean":  (nir-red)/(nir+red)                            if (nir+red)     else np.nan,
                    "NDRE_mean":  (nir-rededge)/(nir+rededge)                    if (nir+rededge) else np.nan,
                    "GNDVI_mean": (nir-0.5*(red+rededge))/(nir+0.5*(red+rededge)) if nir          else np.nan,
                    "MSI_mean":   swir/nir                                        if nir           else np.nan,
                })
            except Exception: continue
        df_sat = pd.DataFrame(results)
        if not df_sat.empty:
            df_sat = df_sat.groupby("date").mean(numeric_only=True).reset_index().sort_values("date")
        return df_sat
    except Exception: return pd.DataFrame()


#domain functions
def get_soil_type(row):
    if not row: return "default", SOIL_WATER["default"]
    for val in row.values():
        vl = str(val).lower().strip()
        for alias, canonical in SOIL_ALIASES.items():
            if vl.startswith(alias) or alias in vl: return canonical, SOIL_WATER[canonical]
        for canonical in SOIL_WATER:
            if canonical != "default" and canonical.lower()[:8] in vl:
                return canonical, SOIL_WATER[canonical]
    return "default", SOIL_WATER["default"]


def get_regional_thresholds(bioma_str=""):
    fb = BIOME_CLIMATE_REF["default"].copy()
    fb.update({"bioma":"default","fonte":"fallback","all_fields":{}})
    vl = (bioma_str or "").strip().lower()
    if not vl: return fb
    for key, canonical in BIOME_ALIASES.items():
        if key in vl:
            ref = BIOME_CLIMATE_REF[canonical].copy()
            ref.update({"bioma":canonical,"fonte":f"GeoJSON (bioma={bioma_str})","all_fields":{}})
            return ref
    for canonical in BIOME_CLIMATE_REF:
        if canonical != "default" and canonical.lower() in vl:
            ref = BIOME_CLIMATE_REF[canonical].copy()
            ref.update({"bioma":canonical,"fonte":f"GeoJSON (bioma={bioma_str})","all_fields":{}})
            return ref
    return fb


def detect_culture(sheet):
    sl = sheet.lower()
    for key, val in SHEET_TO_CULTURE.items():
        if key in sl: return val
    return None


def hargreaves_et0(tmin, tmax, lat_deg, doy):
    lat = math.radians(lat_deg)
    dr  = 1 + 0.033*math.cos(2*math.pi*doy/365)
    dec = 0.409*math.sin(2*math.pi*doy/365-1.39)
    ws  = math.acos(-math.tan(lat)*math.tan(dec))
    Ra  = (24*60/math.pi)*0.082*dr*(ws*math.sin(lat)*math.sin(dec)+math.cos(lat)*math.cos(dec)*math.sin(ws))
    return max(0.0023*((tmax+tmin)/2+17.8)*(max(tmax-tmin,0.0)**0.5)*(Ra*0.408), 0.0)


def compute_water_balance(clim, lat_deg, soil):
    df = clim.copy().sort_values("date").reset_index(drop=True)
    df["doy"] = df["date"].dt.dayofyear
    df["eto"] = df.apply(lambda r: hargreaves_et0(r["tmin"],r["tmax"],lat_deg,r["doy"]), axis=1)
    df["kc"]  = 1.0; df["etc"] = df["eto"]; df["balance_raw"] = df["prcp"] - df["etc"]
    awc = soil.get("AWC",100); storage = awc*0.5
    storages, runoffs, deficits = [], [], []
    for _, row in df.iterrows():
        storage += row["balance_raw"]; runoff = deficit = 0.0
        if   storage > awc: runoff  = storage - awc; storage = awc
        elif storage < 0:   deficit = abs(storage);  storage = 0.0
        storages.append(round(storage,2)); runoffs.append(round(runoff,2)); deficits.append(round(deficit,2))
    df["storage"]     = storages; df["runoff"] = runoffs; df["deficit"] = deficits
    df["storage_pct"] = (df["storage"]/awc*100).round(1)
    df["balance_cum"] = df["balance_raw"].cumsum().round(2)
    return df


def compute_anomaly(clim_event, point_id, hist):
    if clim_event.empty or hist.empty or point_id is None: return {}
    clim_event = clim_event.copy(); clim_event["month"] = clim_event["date"].dt.month
    use_api = (str(point_id) == "api"); results = {}
    for var, label in [("prcp","Precipitação"),("tmax","Temperatura máx."),("rh_avg","Umidade relativa")]:
        if var not in clim_event.columns: continue
        zs = []
        for _, row in clim_event.iterrows():
            h = hist[hist["month"]==row["month"]] if use_api else \
                hist[(hist["point_id"]==point_id)&(hist["month"]==row["month"])]
            if h.empty: continue
            mu_col, sig_col = f"{var}_hist_mean", f"{var}_hist_std"
            if mu_col not in h.columns or sig_col not in h.columns: continue
            mu, sig = h[mu_col].values[0], h[sig_col].values[0]
            if sig is None or sig == 0 or pd.isna(sig): continue
            zs.append((row[var]-mu)/sig)
        if not zs: continue
        z   = float(np.mean(zs))
        cat = ("muito acima do normal" if z>2 else "acima do normal" if z>1 else
               "dentro do normal" if z>-1 else "abaixo do normal" if z>-2 else "muito abaixo do normal")
        results[var] = {"label":label,"z":round(z,2),"categoria":cat}
    return results


def satellite_confidence(n): return {0:0.0,1:0.2,2:0.5}.get(n, 1.0)


def assess_satellite(ts, complaint):
    if ts is None or len(ts) < 2: return "nd","Dados insuficientes (< 2 datas)",0.5
    ts = ts.sort_values("date"); first, last = ts.iloc[0], ts.iloc[-1]
    avail = [i for i in VEG_INDICES if f"{i}_mean" in ts.columns]
    if not avail: return "nd","Índices de vegetação não encontrados",0.5
    deltas  = {i: last[f"{i}_mean"]-first[f"{i}_mean"] for i in avail}
    mean_d  = np.mean(list(deltas.values()))
    msi_d   = last.get(f"{STRESS_INDEX}_mean",np.nan)-first.get(f"{STRESS_INDEX}_mean",np.nan)
    lines   = [f"{k} {'↑' if v>0 else '↓'} {v:+.3f}" for k,v in deltas.items()]
    if not np.isnan(msi_d): lines.append(f"MSI {'↑' if msi_d>0 else '↓'} {msi_d:+.3f}")
    desc    = (f"[{first['date'].strftime('%d/%m/%y')} → {last['date'].strftime('%d/%m/%y')}]  "
               f"{'  |  '.join(lines)}")
    is_rain = complaint.lower() == "chuva"
    score   = ((1 if mean_d>0.02  else 0) if is_rain else (1 if mean_d<-0.02 else 0))*0.7 + \
              ((1 if (not np.isnan(msi_d) and msi_d<0) else 0) if is_rain else
               (1 if (not np.isnan(msi_d) and msi_d>0) else 0))*0.3
    return ("sim" if score>=0.7 else "parcial" if score>=0.3 else "nao"), desc, score


def assess_precipitation(clim, start, end, complaint, prcp_high=20, prcp_low=5):
    if clim is None or clim.empty: return "nd","Sem dados climáticos",0.5
    if start is None or end is None or pd.isnull(start) or pd.isnull(end): return "nd","Datas não disponíveis",0.5
    sub = clim[(clim["date"]>=start)&(clim["date"]<=end)]
    if sub.empty: return "nd","Período fora do range",0.5
    total = sub["prcp"].sum()
    desc  = f"{total:.1f} mm acumulados em {len(sub)} dias ({total/len(sub):.1f} mm/dia)"
    if complaint.lower() == "chuva":
        return ("sim" if total>=prcp_high else "parcial" if total>=5 else "nao"), desc, min(1.0, total/prcp_high)
    return ("sim" if total<=prcp_low else "parcial" if total<=15 else "nao"), desc, max(0.0, 1-total/30)


def assess_climate_complement(clim, start, end, complaint, rh_high=75, rh_low=50):
    if clim is None or clim.empty: return "nd","Sem dados climáticos",0.5
    if start is None or end is None or pd.isnull(start) or pd.isnull(end): return "nd","Datas não disponíveis",0.5
    sub = clim[(clim["date"]>=start)&(clim["date"]<=end)]
    if sub.empty: return "nd","Período fora do range",0.5
    avg_rh, avg_tmax = sub["rh_avg"].mean(), sub["tmax"].mean()
    desc = f"Umidade média {avg_rh:.0f}%  |  Tmax média {avg_tmax:.1f}°C"
    if complaint.lower() == "chuva":
        return ("sim" if avg_rh>=rh_high else "parcial" if avg_rh>=60 else "nao"), desc, min(1.0, avg_rh/rh_high)
    score = ((1 if avg_rh<=rh_low else 0)+(1 if avg_tmax>=28 else 0))/2
    return ("sim" if score>=1.0 else "parcial" if score>=0.5 else "nao"), desc, score


def overall_verdict(s_sat, s_prcp, s_clim, n_sat_dates=3):
    score_map = {"sim":1.0,"parcial":0.5,"nao":0.0,"nd":None}
    sat_w = satellite_confidence(n_sat_dates); ws = tw = 0.0
    for status, w in [(s_sat,sat_w),(s_prcp,1.0),(s_clim,1.0)]:
        sc = score_map[status]
        if sc is not None and w > 0: ws += sc*w; tw += w
    if tw == 0: return "nd"
    return "sim" if ws/tw>=0.70 else ("parcial" if ws/tw>=0.35 else "nao")



#geometry helpers
def _flatten_coords(c, out):
    if not c: return
    if isinstance(c[0], (int, float)): out.append(c)
    else:
        for x in c: _flatten_coords(x, out)

def _ring_area_km2(ring):
    R, n, area = 6371.0, len(ring), 0.0
    for i in range(n):
        j = (i+1) % n
        lo1=math.radians(ring[i][0]); la1=math.radians(ring[i][1])
        lo2=math.radians(ring[j][0]); la2=math.radians(ring[j][1])
        area += (lo2-lo1)*(2+math.sin(la1)+math.sin(la2))
    return abs(area)*R*R/2

def parse_geometry(geom):
    """Return (coords_flat, rings_plot, area_km2, lat, lon)."""
    coords_flat = []; _flatten_coords(geom.get("coordinates",[]), coords_flat)
    gtype, gcoords = geom.get("type",""), geom.get("coordinates",[])
    area_km2, rings_plot = None, []
    if   gtype == "Polygon"      and gcoords: area_km2 = _ring_area_km2(gcoords[0]);                          rings_plot = [gcoords[0]]
    elif gtype == "MultiPolygon" and gcoords: area_km2 = sum(_ring_area_km2(p[0]) for p in gcoords); rings_plot = [p[0] for p in gcoords]
    lon = sum(c[0] for c in coords_flat)/len(coords_flat)
    lat = sum(c[1] for c in coords_flat)/len(coords_flat)
    return coords_flat, rings_plot, area_km2, lat, lon



#charts
def chart_satellite(ts, start, end):
    fig = make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[0.65,0.35],vertical_spacing=0.06)
    for col in [c for c in ts.columns if c.endswith("_mean")]:
        name = col.replace("_mean","")
        fig.add_trace(go.Scatter(x=ts["date"],y=ts[col],name=name,
            line=dict(color=COLORS.get(name,"#aaa"),width=2.5),
            mode="lines+markers",marker=dict(size=7)),row=1,col=1)
    for row in [1,2]:
        fig.add_vrect(x0=start,x1=end,fillcolor="rgba(255,255,255,0.04)",
            line=dict(color="rgba(255,255,255,0.2)",width=1,dash="dot"),row=row,col=1)
    for col in [c for c in ts.columns if c.endswith("_std")]:
        name = col.replace("_std","")
        fig.add_trace(go.Bar(x=ts["date"],y=ts[col],name=f"{name} σ",
            marker_color=COLORS.get(name,"#aaa"),opacity=0.7,showlegend=False),row=2,col=1)
    fig.update_layout(**_PLOT_BASE,
        legend=dict(orientation="h",y=1.02,x=0,bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10,r=10,t=10,b=10),height=480,
        xaxis2_title="Data",yaxis_title="Valor do índice",yaxis2_title="Desvio padrão")
    fig.update_xaxes(**_GRID_STYLE); fig.update_yaxes(**_GRID_STYLE)
    return fig


def chart_precip_cumsum(clim, start, end, complaint):
    sub = clim[(clim["date"]>=start)&(clim["date"]<=end)].copy().sort_values("date")
    if sub.empty: return None
    sub["cumsum"] = sub["prcp"].cumsum()
    ac = accent_color(complaint)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sub["date"],y=sub["cumsum"],name="Chuva acumulada",
        line=dict(color=ac,width=3),fill="tozeroy",
        fillcolor=f"rgba{tuple(list(px.colors.hex_to_rgb(ac))+[0.12])}"))
    fig.add_trace(go.Bar(x=sub["date"],y=sub["prcp"],name="Diário",marker_color=ac,opacity=0.4,yaxis="y2"))
    fig.update_layout(**_PLOT_BASE,
        yaxis=dict(title="Acumulado (mm)"),
        yaxis2=dict(title="Diário (mm)",overlaying="y",side="right",showgrid=False,range=[0,sub["prcp"].max()*4]),
        legend=dict(orientation="h",y=1.02),
        margin=dict(l=10,r=10,t=10,b=10),height=280,
        title=dict(text="Precipitação acumulada no período do evento",font=dict(size=14)))
    return fig


def chart_clima_evento(clim, start, end, complaint):
    w_start = start - pd.Timedelta(days=5); w_end = end + pd.Timedelta(days=5)
    sub = clim[(clim["date"]>=w_start)&(clim["date"]<=w_end)].sort_values("date").copy()
    if sub.empty: return go.Figure()
    ac = accent_color(complaint); is_rain = complaint.lower() == "chuva"
    fig = make_subplots(rows=3,cols=1,shared_xaxes=True,row_heights=[0.45,0.30,0.25],
        vertical_spacing=0.05,
        subplot_titles=("Precipitação (mm)","Temperatura (°C)","Umidade Relativa (%)"))
    bar_colors = [("#4a5568" if d<start else ac if d<=end else
                   ("#2d4a2e" if is_rain else "#4a2d1e")) for d in sub["date"]]
    fig.add_trace(go.Bar(x=sub["date"],y=sub["prcp"],name="Precipitação diária",
        marker_color=bar_colors,opacity=0.85,
        hovertemplate="%{x|%d/%m/%y}<br>%{y:.1f} mm<extra></extra>"),row=1,col=1)
    sub["prcp_cum"] = sub["prcp"].cumsum()
    fig.add_trace(go.Scatter(x=sub["date"],y=sub["prcp_cum"],name="Acumulado (mm)",
        line=dict(color=ac,width=2.5,dash="dot"),yaxis="y4",
        hovertemplate="%{x|%d/%m/%y}<br>Acum: %{y:.1f} mm<extra></extra>"),row=1,col=1)
    fig.add_trace(go.Scatter(x=sub["date"],y=sub["tmax"],name="Tmax",
        line=dict(color="#f78166",width=2),fill="tonexty",fillcolor="rgba(247,129,102,0.08)",
        hovertemplate="%{x|%d/%m/%y}<br>Tmax: %{y:.1f}°C<extra></extra>"),row=2,col=1)
    fig.add_trace(go.Scatter(x=sub["date"],y=sub["tmin"],name="Tmin",
        line=dict(color="#58a6ff",width=2),
        hovertemplate="%{x|%d/%m/%y}<br>Tmin: %{y:.1f}°C<extra></extra>"),row=2,col=1)
    if "tavg" in sub.columns:
        fig.add_trace(go.Scatter(x=sub["date"],y=sub["tavg"],name="Tavg",
            line=dict(color="#d29922",width=1.5,dash="dash"),
            hovertemplate="%{x|%d/%m/%y}<br>Tavg: %{y:.1f}°C<extra></extra>"),row=2,col=1)
    fig.add_trace(go.Scatter(x=sub["date"],y=sub["rh_avg"],name="UR %",
        line=dict(color="#bc8cff",width=2),fill="tozeroy",fillcolor="rgba(188,140,255,0.08)",
        hovertemplate="%{x|%d/%m/%y}<br>UR: %{y:.0f}%<extra></extra>"),row=3,col=1)
    evt_fill = "rgba(88,166,255,0.07)" if is_rain else "rgba(247,129,102,0.07)"
    for rn in [1,2,3]:
        if w_start < start: fig.add_vrect(x0=w_start,x1=start,fillcolor="rgba(100,100,100,0.05)",line_width=0,row=rn,col=1)
        fig.add_vrect(x0=start,x1=end,fillcolor=evt_fill,line=dict(color=ac,width=1.2,dash="dot"),row=rn,col=1)
        if end < w_end:    fig.add_vrect(x0=end,x1=w_end,fillcolor="rgba(63,185,80,0.04)",line_width=0,row=rn,col=1)
    for dt in [start,end]:
        for rn in [1,2,3]:
            fig.add_vline(x=dt.timestamp()*1000,line=dict(color=ac,width=1.2,dash="dash"),row=rn,col=1)
    fig.add_annotation(x=w_start+(start-w_start)/2,y=1,yref="paper",text="← antes",
        showarrow=False,font=dict(color="#8b949e",size=10),xanchor="center")
    fig.add_annotation(x=start+(end-start)/2,y=1,yref="paper",
        text=f"EVENTO ({(end-start).days+1}d)",showarrow=False,
        font=dict(color=ac,size=11,family="Space Mono"),xanchor="center")
    if end < w_end:
        fig.add_annotation(x=end+(w_end-end)/2,y=1,yref="paper",text="depois →",
            showarrow=False,font=dict(color="#8b949e",size=10),xanchor="center")
    fig.update_layout(**_PLOT_BASE,
        legend=dict(orientation="h",y=1.06,x=0,bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10,r=10,t=44,b=10),height=560,barmode="overlay")
    fig.update_xaxes(**_GRID_STYLE); fig.update_yaxes(**_GRID_STYLE)
    return fig



#map
def build_index_map(rings_plot, lat, lon, ts_df, selected_index, selected_date_str):
    m        = folium.Map(location=[lat,lon], zoom_start=12, tiles="CartoDB dark_matter")
    col_name = f"{selected_index}_mean" if selected_index else None
    meta     = INDEX_META.get(selected_index, {})
    fill_hex = "#bc8cff"; fill_op = 0.25; val_label = None

    if col_name and ts_df is not None and not ts_df.empty and col_name in ts_df.columns and selected_date_str:
        row_data = ts_df[ts_df["date"].dt.strftime("%Y-%m-%d") == selected_date_str]
        if not row_data.empty:
            val      = float(row_data[col_name].iloc[0])
            fill_hex = index_color(val, ts_df, col_name, meta)
            fill_op  = 0.60; val_label = f"{selected_index} = {val:.4f}"

    poly_color = "#bc8cff" if not val_label else fill_hex
    for ring in rings_plot:
        folium.Polygon(locations=[(p[1],p[0]) for p in ring],
            color=poly_color, weight=2, fill=True, fill_color=fill_hex, fill_opacity=fill_op,
            tooltip=val_label or "Polígono do evento").add_to(m)
    popup_html = (f"<div style='font-family:monospace;font-size:12px;min-width:160px'>"
                  f"<b>Centróide</b><br>lat:{lat:.5f}<br>lon:{lon:.5f}"
                  f"{f'<br><br><b>{val_label}</b>' if val_label else ''}</div>")
    folium.CircleMarker(location=[lat,lon], radius=7, color=poly_color, fill=True, fill_color=fill_hex,
        popup=folium.Popup(popup_html, max_width=200), tooltip="Centróide").add_to(m)

    if val_label and meta:
        lo_hex = rgb_to_hex(meta.get("color_low",(220,50,30)))
        hi_hex = rgb_to_hex(meta.get("color_high",(30,180,60)))
        lo_lbl = "Baixo" if not meta.get("invert") else "Alto"
        hi_lbl = "Alto"  if not meta.get("invert") else "Baixo"
        legend = (f"<div style='position:fixed;bottom:30px;right:10px;z-index:9999;"
                  f"background:#161b22cc;border:1px solid #30363d;border-radius:8px;"
                  f"padding:10px 14px;font-family:monospace;font-size:12px;color:#e6edf3'>"
                  f"<div style='font-weight:700;margin-bottom:6px;color:#bc8cff'>{selected_index}</div>"
                  f"<div style='display:flex;align-items:center;gap:8px'>"
                  f"<span style='color:{lo_hex}'>{lo_lbl}</span>"
                  f"<div style='width:80px;height:10px;border-radius:4px;"
                  f"background:linear-gradient(to right,{lo_hex},{hi_hex})'></div>"
                  f"<span style='color:{hi_hex}'>{hi_lbl}</span></div>"
                  f"<div style='margin-top:6px;font-size:11px;color:#8b949e'>{meta.get('desc','')}</div>"
                  f"</div>")
        m.get_root().html.add_child(folium.Element(legend))
    return m



#HTML snippets
def verdict_html(v):
    label = STATUS_LABEL[v]; cls = f"verdict-{v if v!='nd' else 'parcial'}"; color = STATUS_COLOR[v]
    return (f"<div class='verdict-card {cls}'>"
            f"<div style='font-size:13px;color:#8b949e;font-family:Space Mono,monospace;"
            f"text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px'>Diagnóstico Geral</div>"
            f"<div style='font-size:32px;font-weight:700;font-family:Space Mono,monospace;color:{color}'>{label}</div>"
            f"<div style='font-size:13px;color:#8b949e;margin-top:4px'>"
            f"O problema reportado é visível nos dados disponíveis</div></div>")



#MAIN
def main():
    st.sidebar.markdown("## 🛰️ Diagnóstico Agrícola")
    st.sidebar.markdown("---")
    geojson_file = st.sidebar.file_uploader(
        "📂 Enviar caso (.geojson)", type=["geojson","json"],
        help="FeatureCollection com properties: id, evento, inicio, fim, solo, cultura, bioma.")

    if not geojson_file:
        st.markdown("""
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
                    margin-top:100px;gap:18px;text-align:center">
          <div style="font-size:58px">🛰️</div>
          <div style="font-size:24px;font-weight:700;font-family:'Space Mono',monospace;color:#e6edf3">
            Diagnóstico Agrícola</div>
          <div style="font-size:15px;color:#8b949e;max-width:440px;line-height:1.7">
            Envie um arquivo <b style="color:#58a6ff">.geojson</b> na barra lateral.</div>
        </div>""", unsafe_allow_html=True)
        return

    try: geojson_data = json.loads(geojson_file.read())
    except Exception as e: st.error(f"Erro ao ler GeoJSON: {e}"); return

    #pipeline format support (key "meta" present)
    if "meta" in geojson_data and "geometry" in geojson_data:
        meta = geojson_data["meta"]
        geojson_data = {
            "type": "Feature",
            "geometry": geojson_data["geometry"],
            "properties": {
                "id":      meta.get("farm_name", "pipeline"),
                "evento":  meta.get("event_type", "seca"),
                "inicio":  meta.get("start_date"),
                "fim":     meta.get("end_date"),
                "cultura": meta.get("crop_type", ""),
                "solo":    meta.get("soil_type", "default"),
                "bioma":   meta.get("biome", ""),
            }
        }

    gtype = geojson_data.get("type")
    if   gtype == "FeatureCollection": all_features = geojson_data.get("features",[])
    elif gtype == "Feature":           all_features = [geojson_data]
    else:                              all_features = [{"type":"Feature","geometry":geojson_data,"properties":{}}]
    if not all_features: st.error("GeoJSON sem features."); return

    if len(all_features) > 1:
        feat_labels = [f"#{f.get('properties',{}).get('id',i+1)} – "
                       f"{str(f.get('properties',{}).get('evento','?')).upper()} – "
                       f"{f.get('properties',{}).get('cultura','?')}"
                       for i,f in enumerate(all_features)]
        idx = st.sidebar.selectbox("Selecionar caso", range(len(all_features)),
                                   format_func=lambda i: feat_labels[i])
    else: idx = 0

    feature   = all_features[idx]
    props     = feature.get("properties",{}) or {}
    geom      = feature.get("geometry",{})   or {}
    case_id   = str(props.get("id","—"))
    complaint = str(props.get("evento","chuva")).lower().strip()
    start_dt  = pd.to_datetime(props.get("inicio"), errors="coerce")
    end_dt    = pd.to_datetime(props.get("fim"),    errors="coerce")
    solo_str  = str(props.get("solo","default"))
    cultura   = str(props.get("cultura","")).upper().strip()
    bioma_str = str(props.get("bioma",""))

    if pd.isna(start_dt) or pd.isna(end_dt):
        st.error(f"Properties `inicio` e `fim` em formato YYYY-MM-DD. "
                 f"Recebido: '{props.get('inicio')}'/'{props.get('fim')}'")
        return

    coords_flat, rings_plot, area_km2, lat, lon = parse_geometry(geom)
    if not coords_flat: st.error("Geometria sem coordenadas."); return

    st.sidebar.success(f"📍 {lat:.4f}°, {lon:.4f}°")
    st.sidebar.caption(f"Caso #{case_id} · {complaint.upper()} · {cultura or '—'}\n"
                       f"{start_dt.strftime('%d/%m/%Y')} → {end_dt.strftime('%d/%m/%Y')}")

    regional  = get_regional_thresholds(bioma_str)
    prcp_high = int(regional["prcp_alta"]); prcp_low = int(regional["prcp_baixa"])
    rh_high   = int(regional["rh_alta"]);  rh_low   = int(regional["rh_baixa"])
    _, soil_props = get_soil_type({"solo": solo_str})

    with st.spinner("☁️ Buscando dados climáticos..."):
        clim = fetch_climate_api(float(lat), float(lon), start_dt, end_dt)
    if clim.empty: st.error("Não foi possível recuperar dados climáticos via Open-Meteo."); return

    ts = None; using_api_satellite = False
    if HAS_STAC and HAS_GEO:
        with st.spinner("🛰️ Buscando imagens Sentinel-2 via STAC..."):
            ts_result = fetch_satellite_api(feature, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
        if ts_result is not None and not ts_result.empty:
            ts = ts_result; using_api_satellite = True

    with st.spinner("📊 Buscando baseline histórico..."):
        hist_baseline = fetch_historical_baseline_api(float(lat), float(lon), start_dt)

    compute_water_balance(clim, float(lat), soil_props) #pre-computes wb (available for future extensions)

    clim_event  = clim[(clim["date"]>=start_dt)&(clim["date"]<=end_dt)].copy()
    anomaly     = compute_anomaly(clim_event, "api", hist_baseline)
    n_sat_dates = len(ts["date"].unique()) if ts is not None and not ts.empty else 0

    v_sat,  _, _ = assess_satellite(ts, complaint)
    v_prcp, _, _ = assess_precipitation(clim, start_dt, end_dt, complaint, prcp_high, prcp_low)
    v_clim, _, _ = assess_climate_complement(clim, start_dt, end_dt, complaint, rh_high, rh_low)
    v_total      = overall_verdict(v_sat, v_prcp, v_clim, n_sat_dates)

    #header
    badge_c   = "badge-chuva" if complaint == "chuva" else "badge-seca"
    badge_sat = (
        "<span style='background:#1c2030;color:#bc8cff;border:1px solid #bc8cff;"
        "border-radius:12px;font-size:11px;padding:2px 8px;font-family:Space Mono,monospace'>🛰️ STAC API</span>"
        if using_api_satellite else "")
    bio_lbl       = biome_label(regional)
    subtitle_bits = [cultura or "—"] + ([bio_lbl] if bio_lbl != "—" else [])

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;flex-wrap:wrap">
      <h1 style="margin:0;font-size:26px">Caso #{case_id}</h1>
      <span class="badge {badge_c}">{complaint.upper()}</span>{badge_sat}
    </div>
    <div style="color:#8b949e;font-size:14px;margin-bottom:18px">
      {" &nbsp;·&nbsp; ".join(subtitle_bits)}
    </div>""", unsafe_allow_html=True)

    area_ha_str = f"{area_km2*100:.2f} ha" if area_km2 else "—"
    st.markdown(
        "<div class='info-grid'>"
        + info_cell("Início",      start_dt.strftime('%d/%m/%Y'))
        + info_cell("Fim",         end_dt.strftime('%d/%m/%Y'))
        + info_cell("Duração",     f"{(end_dt-start_dt).days+1} dias")
        + info_cell("Bioma",       bio_lbl, "font-size:13px")
        + info_cell("Total de Ha", area_ha_str)
        + info_cell("Imagens",     str(n_sat_dates))
        + "</div>", unsafe_allow_html=True)

    #TABS
    tab_diag, tab_sat, tab_imgs, tab_clima, tab_map = st.tabs([
        "🎯 Diagnóstico","🛰️ Satélite","🖼️ Imagens","🌧️ Clima","🗺️ Localização"])

    #diagnostic
    with tab_diag:
        st.markdown(verdict_html(v_total), unsafe_allow_html=True)
        if anomaly:
            st.markdown("---")
            st.markdown("### Histórico da Região")
            st.caption("Z-score vs baseline de 10 anos via Open-Meteo")
            color_cat = {"muito abaixo do normal":"#f85149","abaixo do normal":"#f78166",
                         "dentro do normal":"#8b949e","acima do normal":"#58a6ff","muito acima do normal":"#3fb950"}
            for col, (var, info) in zip(st.columns(len(anomaly)), anomaly.items()):
                clr = color_cat.get(info["categoria"], "#8b949e")
                col.markdown(f"""
                <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 14px;text-align:center">
                  <div style="font-size:11px;color:#8b949e;text-transform:uppercase">{info['label']}</div>
                  <div style="font-size:26px;font-weight:700;font-family:'Space Mono',monospace;color:{clr};margin:6px 0">
                    {info['z']:+.2f}<span style="font-size:12px">σ</span></div>
                  <div style="font-size:12px;color:{clr}">{info['categoria']}</div>
                </div>""", unsafe_allow_html=True)

        with st.expander("🔍 Debug — valores vs thresholds"):
            rp = clim_event["prcp"].sum()    if not clim_event.empty else None
            rr = clim_event["rh_avg"].mean() if not clim_event.empty else None
            rt = clim_event["tmax"].mean()   if not clim_event.empty else None
            def _cmp(label, real, thr, hig):
                if real is None: return f"| {label} | — | {thr} | N/D |"
                return f"| {label} | **{real:.1f}** | {thr} | {'✅' if (real>=thr if hig else real<=thr) else '❌'} |"
            if complaint == "chuva":
                rows_d = [_cmp("Precipitação (mm)",rp,prcp_high,True), _cmp("Umidade relativa (%)",rr,rh_high,True)]
                note   = "Chuva: precip ≥ limiar e UR ≥ limiar para confirmar"
            else:
                rows_d = [_cmp("Precipitação (mm)",rp,prcp_low,False), _cmp("Umidade relativa (%)",rr,rh_low,False), _cmp("Tmax média (°C)",rt,28,True)]
                note   = "Seca: precip ≤ limiar e UR ≤ limiar (ou Tmax ≥ 28°C)"
            st.markdown(f"*{note}*")
            st.markdown("| Variável | Valor real | Limiar | Passa? |\n|---|---|---|---|")
            for r in rows_d: st.markdown(r)
            st.json({"bioma":regional["bioma"],"lat":round(lat,4),"lon":round(lon,4),
                     "satélite":{"status":v_sat,"n_datas":n_sat_dates},
                     "precipitação":{"status":v_prcp},"clima_complementar":{"status":v_clim},
                     "veredicto_final":v_total})

    #satellite
    with tab_sat:
        if ts is None or ts.empty:
            st.warning("Nenhuma imagem Sentinel-2 sem nuvens encontrada.")
            if not HAS_STAC: st.info("Instale: `pip install pystac-client rioxarray`")
        else:
            st.markdown("#### Série temporal dos índices espectrais")
            st.markdown(f"*{len(ts['date'].unique())} data(s) · caso #{case_id}*")
            st.plotly_chart(chart_satellite(ts, start_dt, end_dt), use_container_width=True)
            with st.expander("📊 Dados brutos"):
                st.dataframe(ts, use_container_width=True, height=300)

    #images
    with tab_imgs:
        if using_api_satellite:
            st.info("☁️ **Modo API:** STAC (Element84/AWS). Veja a série na aba **🛰️ Satélite**.")
        images_local = {"compiled":[], "individual":{}}
        try:
            from pathlib import Path as _Path
            from config import OUTPUT_INDICES_DIR
            folder = None
            for base in [OUTPUT_INDICES_DIR, _Path("/tmp/output_indices")]:
                for candidate in sorted(base.glob(f"case_{case_id}_*")): folder = candidate; break
                if folder: break
            if folder and folder.exists():
                for p in sorted(folder.glob("*.png")):
                    if not re.search(r"\d{4}", p.stem.upper()): images_local["compiled"].append((p.stem, p))
                for subdir in sorted(folder.iterdir()):
                    if not subdir.is_dir() or subdir.name.upper() == "TIF": continue
                    pngs = sorted(subdir.glob("*.png")) + sorted(subdir.glob("*.PNG"))
                    if not pngs: continue
                    entries = []
                    for p in pngs:
                        mr = re.search(r"(\d{4})[_\-](\d{2})[_\-](\d{2})", p.stem)
                        entries.append((f"{mr.group(1)}-{mr.group(2)}-{mr.group(3)}" if mr else p.stem, p))
                    images_local["individual"][subdir.name] = entries
        except Exception: pass
        if images_local["compiled"]:
            st.markdown("#### Painéis compilados")
            for n, p in images_local["compiled"]: st.markdown(f"**{n}**"); st.image(str(p), use_container_width=True)
        if images_local["individual"]:
            st.markdown("#### Imagens por data")
            for n, entries in sorted(images_local["individual"].items()):
                st.markdown(f"**{n}** — {len(entries)} data(s)")
                for col_i, (ds, p) in zip(st.columns(min(len(entries),4)), entries):
                    col_i.image(str(p), caption=ds, use_container_width=True)
        if not images_local["compiled"] and not images_local["individual"] and not using_api_satellite:
            st.warning("Nenhuma imagem local encontrada.")

    #climate
    with tab_clima:
        st.markdown("#### 🌧️ Clima do Evento")
        st.caption(f"Fonte: **Open-Meteo Archive API** — lat {lat:.4f}°, lon {lon:.4f}° · Bioma: **{regional['bioma']}**")
        w_start = start_dt - pd.Timedelta(days=5); w_end = end_dt + pd.Timedelta(days=5)
        antes   = clim[(clim["date"]>=w_start)&(clim["date"]<start_dt)]
        durante = clim_event
        depois  = clim[(clim["date"]>end_dt)&(clim["date"]<=w_end)]
        ac      = accent_color(complaint)
        glow    = "rgba(88,166,255,0.12)" if complaint == "chuva" else "rgba(247,129,102,0.12)"

        def _period_card(title, df, highlight=False):
            border = f"2px solid {ac}" if highlight else "1px solid #30363d"
            tc     = ac if highlight else "#8b949e"
            sz     = "24" if highlight else "22"
            fw     = "font-weight:700;" if highlight else ""
            shadow = f"box-shadow:0 0 18px {glow};" if highlight else ""
            return (f"<div style='background:#161b22;border:{border};border-radius:8px;"
                    f"padding:14px 16px;{shadow}'>"
                    f"<div style='font-size:11px;color:{tc};text-transform:uppercase;{fw}margin-bottom:6px'>{title}</div>"
                    f"<div style='font-size:{sz}px;font-weight:700;font-family:Space Mono,monospace;color:{tc}'>"
                    f"{df['prcp'].sum():.1f} mm</div>"
                    f"<div style='font-size:12px;color:#8b949e;margin-top:4px'>"
                    f"Tmax {df['tmax'].mean():.1f}°C · UR {df['rh_avg'].mean():.0f}%</div></div>")

        st.markdown(
            "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px'>"
            + _period_card("← 5 dias antes", antes)
            + _period_card(f"Evento · {(end_dt-start_dt).days+1} dias", durante, highlight=True)
            + _period_card("5 dias depois →", depois)
            + "</div>", unsafe_allow_html=True)

        st.plotly_chart(chart_clima_evento(clim, start_dt, end_dt, complaint), use_container_width=True)
        st.markdown("---")
        fig_cum = chart_precip_cumsum(clim, start_dt, end_dt, complaint)
        if fig_cum: st.plotly_chart(fig_cum, use_container_width=True)
        st.markdown("---")
        with st.expander("📊 Dados brutos da janela (±5 dias)"):
            win = clim[(clim["date"]>=w_start)&(clim["date"]<=w_end)].copy()
            cs  = [c for c in ["date","prcp","tmin","tmax","tavg","rh_avg","eto"] if c in win.columns]
            st.dataframe(win[cs].sort_values("date").round(2), use_container_width=True, height=300)

    #location
    with tab_map:
        st.subheader("Localização do Caso")

        available_indices = [k for k in ALL_INDICES
                             if ts is not None and not ts.empty and f"{k}_mean" in ts.columns]
        available_dates   = (sorted(ts["date"].dt.strftime("%Y-%m-%d").unique())
                             if ts is not None and not ts.empty else [])
        has_sat           = bool(available_indices and available_dates)

        selected_index    = None
        selected_date_str = available_dates[len(available_dates)//2] if available_dates else None

        col_map, col_right = st.columns([3, 2])

        #Right panel — widgets first so values feed into map
        with col_right:
            st.markdown("<div class='side-title'>🛰️ Índice Espectral</div>", unsafe_allow_html=True)
            if not has_sat:
                st.info("Nenhuma data de satélite disponível.")
            else:
                selected_label = st.radio(
                    "idx_radio", options=["— Nenhum —"] + available_indices, index=0,
                    label_visibility="collapsed",
                    format_func=lambda x: x if x=="— Nenhum —"
                                          else f"{x}  —  {INDEX_META.get(x,{}).get('desc','')}",
                )
                selected_index = None if selected_label == "— Nenhum —" else selected_label
                if selected_index:
                    meta   = INDEX_META[selected_index]
                    lo_hex = rgb_to_hex(meta["color_low"]); hi_hex = rgb_to_hex(meta["color_high"])
                    lo_lbl = "Baixo" if not meta.get("invert") else "Alto"
                    hi_lbl = "Alto"  if not meta.get("invert") else "Baixo"
                    st.markdown(f"""
                    <div style="margin-top:10px;background:#0d1117;border:1px solid #30363d;
                                border-radius:8px;padding:9px 11px">
                      <div style="font-size:11px;color:#8b949e;margin-bottom:5px">{meta['desc']}</div>
                      <div style="display:flex;align-items:center;gap:6px;font-size:11px">
                        <span style="color:{lo_hex}">{lo_lbl}</span>
                        <div style="flex:1;height:8px;border-radius:4px;
                                    background:linear-gradient(to right,{lo_hex},{hi_hex})"></div>
                        <span style="color:{hi_hex}">{hi_lbl}</span>
                      </div>
                    </div>""", unsafe_allow_html=True)

            st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)
            st.markdown("<hr style='border-color:#30363d;margin:0 0 14px'>", unsafe_allow_html=True)
            st.markdown("<div class='side-title'>📅 Período Selecionado</div>", unsafe_allow_html=True)

            if not has_sat:
                st.info("Nenhuma data de satélite disponível.")
            else:
                selected_date_str = st.selectbox(
                    "data_img", options=available_dates,
                    index=len(available_dates)//2,
                    key="map_date_selector", label_visibility="collapsed")

                if selected_index and selected_date_str:
                    col_name = f"{selected_index}_mean"
                    row_data = ts[ts["date"].dt.strftime("%Y-%m-%d") == selected_date_str]
                    if not row_data.empty and col_name in ts.columns:
                        val      = float(row_data[col_name].iloc[0])
                        meta     = INDEX_META.get(selected_index, {})
                        vc       = index_color(val, ts, col_name, meta)
                        col_min  = float(ts[col_name].min()); col_max = float(ts[col_name].max())
                        st.markdown(f"""
                        <div style="background:#0d1117;border:1px solid {vc};border-radius:8px;
                                    padding:10px 14px;margin-top:10px">
                          <div style="font-size:11px;color:#8b949e">{selected_index} · {selected_date_str}</div>
                          <div style="font-size:28px;font-weight:700;font-family:'Space Mono',monospace;
                                      color:{vc};margin:4px 0">{val:.4f}</div>
                          <div style="font-size:11px;color:#8b949e">
                            mín {col_min:.3f} &nbsp;·&nbsp; máx {col_max:.3f}</div>
                        </div>""", unsafe_allow_html=True)

                st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
                for d in available_dates:
                    in_evt = start_dt <= pd.to_datetime(d) <= end_dt
                    dc     = "#3fb950" if in_evt else "#8b949e"
                    fw     = "font-weight:700;" if d == selected_date_str else ""
                    tag    = " ← evento" if in_evt else ""
                    st.markdown(f"<div style='font-size:12px;font-family:Space Mono,monospace;"
                                f"color:{dc};padding:2px 0;{fw}'>● {d}{tag}</div>",
                                unsafe_allow_html=True)

        #Left panel — map + timeline slider
        with col_map:
            m_folium = build_index_map(
                rings_plot=rings_plot, lat=lat, lon=lon, ts_df=ts,
                selected_index=selected_index if available_indices else None,
                selected_date_str=selected_date_str)
            st_folium(m_folium, height=540, use_container_width=True)

            if available_dates and len(available_dates) > 1:
                st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
                st.markdown("<div style='font-size:12px;color:#8b949e;margin-bottom:4px'>"
                            "🕒 <b>Linha do tempo</b> — deslize para navegar entre as datas</div>",
                            unsafe_allow_html=True)
                slider_date = st.select_slider(
                    "timeline", options=available_dates,
                    value=selected_date_str or available_dates[0],
                    key="map_timeline_slider", label_visibility="collapsed")
                if slider_date != selected_date_str:
                    m_slider = build_index_map(
                        rings_plot=rings_plot, lat=lat, lon=lon, ts_df=ts,
                        selected_index=selected_index if available_indices else None,
                        selected_date_str=slider_date)
                    st_folium(m_slider, height=480, use_container_width=True, key="map_slider_view")

        with st.expander("📍 Pontos da geometria"):
            st.dataframe(
                pd.DataFrame([{"lon":p[0],"lat":p[1]} for ring in rings_plot for p in ring]),
                use_container_width=True)


if __name__ == "__main__":
    main()
