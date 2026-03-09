"""
dashboard.py — Poseidon · Copernicus · EMBRAPA Diagnostic Dashboard

Usage:
streamlit run dashboard.py
Two modes:

• Pipeline (JSON) — loads output from main.py with real Poseidon + Copernicus data.
• Standalone (GeoJSON) — retrieves data via Open-Meteo + STAC/Sentinel-2 (no database).

Pipeline flow:
1. Run main.py normally → generates pipeline_*.json in the project folder
2. Open the dashboard → load the JSON in the sidebar
"""

import json
import math
import warnings
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

#importa constantes do projeto
try:
    from config import SOIL_WATER_PROPERTIES, SOIL_CODE_ALIASES
    _SOIL_WATER = SOIL_WATER_PROPERTIES
    _SOIL_ALIAS = SOIL_CODE_ALIASES
except ImportError:
    _SOIL_WATER = {}
    _SOIL_ALIAS = {}

try:
    import folium
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

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


#Page
st.set_page_config(
    page_title="Agricultural Diagnostics · Poseidon + Sentinel-2",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');
:root{--bg:#0d1117;--surface:#161b22;--surface2:#21262d;--border:#30363d;
     --text:#e6edf3;--muted:#8b949e;--chuva:#58a6ff;--seca:#f78166;
     --sim:#3fb950;--nao:#f85149;--parcial:#d29922;--accent:#bc8cff;}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
.stApp{background:var(--bg);color:var(--text);}
.stSidebar{background:var(--surface)!important;border-right:1px solid var(--border);}
h1,h2,h3{font-family:'Space Mono',monospace;}
.verdict-card{border-radius:12px;padding:24px 28px;margin-bottom:20px;border:1px solid var(--border);}
.verdict-sim{background:#0d2318;border-color:var(--sim);}
.verdict-nao{background:#2d0f0e;border-color:var(--nao);}
.verdict-parcial{background:#2b1d0e;border-color:var(--parcial);}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;
       font-weight:600;font-family:'Space Mono',monospace;}
.badge-chuva{background:#1c2d3f;color:var(--chuva);border:1px solid var(--chuva);}
.badge-seca{background:#2d1f1c;color:var(--seca);border:1px solid var(--seca);}
.info-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
           gap:12px;margin-bottom:20px;}
.info-cell{background:var(--surface);border:1px solid var(--border);
           border-radius:8px;padding:12px 14px;}
.info-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;}
.info-value{font-size:16px;font-weight:600;font-family:'Space Mono',monospace;margin-top:4px;}
div[data-testid="stTabs"] button{font-family:'Space Mono',monospace;font-size:13px;}
.side-title{font-size:11px;font-weight:700;font-family:'Space Mono',monospace;
    color:#bc8cff;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;}
</style>
""", unsafe_allow_html=True)



#constants
SOIL_WATER = _SOIL_WATER or {
    "Latossolo Vermelho-Amarelo": {"AWC": 110, "Ks": 28, "fc": 33, "wp": 14, "retention": "medium"},
    "default": {"AWC": 100, "Ks": 20, "fc": 30, "wp": 15, "retention": "medium"},
}
SOIL_ALIASES = _SOIL_ALIAS

BIOME_THRESHOLDS = {
    "Amazonia":       {"prcp_alta": 150, "prcp_baixa": 60,  "rh_alta": 80, "rh_baixa": 65},
    "Cerrado":        {"prcp_alta":  60, "prcp_baixa": 10,  "rh_alta": 70, "rh_baixa": 40},
    "Caatinga":       {"prcp_alta":  30, "prcp_baixa":  5,  "rh_alta": 60, "rh_baixa": 35},
    "Mata Atlantica": {"prcp_alta":  80, "prcp_baixa": 20,  "rh_alta": 78, "rh_baixa": 60},
    "Pampa":          {"prcp_alta":  50, "prcp_baixa": 15,  "rh_alta": 75, "rh_baixa": 55},
    "Pantanal":       {"prcp_alta": 100, "prcp_baixa": 20,  "rh_alta": 75, "rh_baixa": 50},
    "default":        {"prcp_alta":  40, "prcp_baixa": 10,  "rh_alta": 72, "rh_baixa": 50},
}
BIOME_ALIASES_MAP = {
    "amaz": "Amazonia", "cerr": "Cerrado", "caat": "Caatinga",
    "mata": "Mata Atlantica", "pamp": "Pampa", "pant": "Pantanal",
}

#indexes that copernicus.py collects (same list)
ALL_INDICES  = ["NDVI", "NDRE", "EVI", "NDWI", "NDMI", "BSI", "NBR", "PSRI", "CRI1"]
VEG_POSITIVE = ["NDVI", "NDRE", "EVI", "NDWI", "NDMI", "NBR"]

COLORS = {
    "NDVI": "#3fb950", "NDRE": "#58a6ff", "EVI":  "#a5f3fc", "NDWI": "#2dc8f0",
    "NDMI": "#bc8cff", "BSI":  "#d29922", "NBR":  "#f0a030", "PSRI": "#f78166",
    "CRI1": "#e879f9",
}
INDEX_META = {
    "NDVI": {"desc": "Indice geral de vegetacao",           "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "NDRE": {"desc": "Red Edge - vigor / estresse precoce", "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "EVI":  {"desc": "Enhanced Vegetation Index",           "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "NDWI": {"desc": "Agua na vegetacao (Gao)",             "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "NDMI": {"desc": "Umidade no dossel (SWIR)",            "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "BSI":  {"desc": "Solo exposto - falha de stand",       "invert": True,  "color_low": (30,180,60),  "color_high": (220,50,30)},
    "NBR":  {"desc": "Queimadas / dano severo",             "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "PSRI": {"desc": "Senescencia vegetal",                 "invert": True,  "color_low": (30,180,60),  "color_high": (220,50,30)},
    "CRI1": {"desc": "Carotenoides - envelhecimento",       "invert": True,  "color_low": (30,180,60),  "color_high": (220,50,30)},
}

STATUS_LABEL = {"sim": "CONFIRMED", "nao": "NOT CONFIRMED",
                "parcial": "INCONCLUSIVE", "nd": "N/A"}
STATUS_COLOR = {"sim": "#3fb950", "nao": "#f85149", "parcial": "#d29922", "nd": "#8b949e"}

_PLOT_BASE = dict(template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
                  font=dict(family="DM Sans", color="#e6edf3"))
_GRID      = dict(showgrid=True, gridcolor="#21262d")



#Utilities
def rgb_to_hex(c):
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"

def lerp_color(t, low, high):
    t = max(0.0, min(1.0, t))
    return (f"#{int(low[0]+(high[0]-low[0])*t):02x}"
            f"{int(low[1]+(high[1]-low[1])*t):02x}"
            f"{int(low[2]+(high[2]-low[2])*t):02x}")

def idx_color(val, series_vals, meta):
    lo, hi = float(np.nanmin(series_vals)), float(np.nanmax(series_vals))
    n = (val - lo) / (hi - lo + 1e-9) if (hi - lo) > 1e-9 else 0.5
    if meta.get("invert"): n = 1.0 - n
    return lerp_color(n, meta.get("color_low", (220,50,30)), meta.get("color_high", (30,180,60)))

def accent(complaint):
    return "#58a6ff" if str(complaint).lower() == "chuva" else "#f78166"

def info_cell(label, value, style=""):
    return (f"<div class='info-cell'><div class='info-label'>{label}</div>"
            f"<div class='info-value' style='{style}'>{value}</div></div>")

def brl(v):
    try:
        return "R$ {:,.2f}".format(float(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ -"



#conversion pipeline -> DataFrames
def cop_to_ts(cop_data: dict) -> pd.DataFrame:
    """
    Converte cop_data (saida de collect_all_indices) em DataFrame de serie temporal.
    Cada item de baseline_series / event_series tem chave 'from' com a data.
    """
    rows: dict = {}
    for idx_name, data in cop_data.items():
        if idx_name == "VHI" or not isinstance(data, dict):
            continue
        for series_key in ("baseline_series", "event_series"):
            for item in data.get(series_key) or []:
                if not isinstance(item, dict):
                    continue
                #the Statistics API returns {"from": "2023-01-01", "to": ..., "mean": ..., "stdev": ...}
                raw_dt = (item.get("from") or item.get("date")
                          or (item.get("interval") or {}).get("from"))
                if not raw_dt:
                    continue
                dt = pd.to_datetime(raw_dt, errors="coerce")
                if pd.isnull(dt):
                    continue
                key = dt.date()
                if key not in rows:
                    rows[key] = {"date": dt}
                mean_val = item.get("mean")
                std_val  = item.get("stdev") or item.get("std")
                if mean_val is not None and not (isinstance(mean_val, float) and math.isnan(mean_val)):
                    rows[key][f"{idx_name}_mean"] = float(mean_val)
                if std_val is not None and not (isinstance(std_val, float) and math.isnan(std_val)):
                    rows[key][f"{idx_name}_std"]  = float(std_val)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(sorted(rows.values(), key=lambda r: r["date"]))


def pos_daily_to_df(pos_daily: list) -> pd.DataFrame:
    """Converte pos_daily (lista de dicts) em DataFrame climatico do Poseidon."""
    if not pos_daily:
        return pd.DataFrame()
    df = pd.DataFrame(pos_daily)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    for col in ["prcp", "tmax", "tmin", "tavg", "rh_avg", "rh_min", "rh_max",
                "wspd_avg", "wspd_max", "wspd_min"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan
    return df.sort_values("date").reset_index(drop=True)


#open-Meteo (modo standalone)
def _parse_openmeteo(data, rename):
    df_d = pd.DataFrame(data["daily"]); df_d["time"] = pd.to_datetime(df_d["time"])
    df_h = pd.DataFrame(data["hourly"]); df_h["time"] = pd.to_datetime(df_h["time"]).dt.date
    rh   = df_h.groupby("time")["relative_humidity_2m"].mean().reset_index()
    rh["time"] = pd.to_datetime(rh["time"])
    return pd.merge(df_d, rh, on="time", how="left").rename(columns=rename)


@st.cache_data(show_spinner=False)
def fetch_openmeteo(lat, lon, start_dt, end_dt):
    if not HAS_REQUESTS:
        return pd.DataFrame()
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": (start_dt - pd.Timedelta(days=35)).strftime("%Y-%m-%d"),
        "end_date":   (end_dt   + pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
        "daily": ["precipitation_sum", "temperature_2m_max", "temperature_2m_min",
                  "temperature_2m_mean", "et0_fao_evapotranspiration"],
        "hourly": "relative_humidity_2m", "timezone": "auto",
    }
    try:
        r = requests.get("https://archive-api.open-meteo.com/v1/archive",
                         params=params, timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        return _parse_openmeteo(r.json(), {
            "time": "date", "precipitation_sum": "prcp",
            "temperature_2m_max": "tmax", "temperature_2m_min": "tmin",
            "temperature_2m_mean": "tavg",
            "et0_fao_evapotranspiration": "eto",
            "relative_humidity_2m": "rh_avg",
        })
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def fetch_openmeteo_hist(lat, lon, start_dt):
    if not HAS_REQUESTS:
        return pd.DataFrame()
    hist_end   = start_dt - pd.Timedelta(days=365)
    hist_start = hist_end - pd.Timedelta(days=10 * 365)
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": hist_start.strftime("%Y-%m-%d"),
        "end_date":   hist_end.strftime("%Y-%m-%d"),
        "daily": ["precipitation_sum", "temperature_2m_max"],
        "hourly": "relative_humidity_2m", "timezone": "auto",
    }
    try:
        r = requests.get("https://archive-api.open-meteo.com/v1/archive",
                         params=params, timeout=60)
        if r.status_code != 200:
            return pd.DataFrame()
        df = _parse_openmeteo(r.json(), {
            "time": "date", "precipitation_sum": "prcp",
            "temperature_2m_max": "tmax", "relative_humidity_2m": "rh_avg",
        })
        df["month"] = df["date"].dt.month
        return df.groupby("month").agg(
            prcp_hist_mean=("prcp", "mean"), prcp_hist_std=("prcp", "std"),
            tmax_hist_mean=("tmax", "mean"), tmax_hist_std=("tmax", "std"),
            rh_avg_hist_mean=("rh_avg", "mean"), rh_avg_hist_std=("rh_avg", "std"),
        ).reset_index()
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def fetch_stac(geojson_feature, start_date_str, end_date_str):
    if not HAS_STAC or not HAS_GEO:
        return pd.DataFrame()
    start_dt = pd.to_datetime(start_date_str) - pd.Timedelta(days=5)
    end_dt   = pd.to_datetime(end_date_str)   + pd.Timedelta(days=5)
    try:
        client = STACClient.open("https://earth-search.aws.element84.com/v1")
        geom   = shape(geojson_feature["geometry"])
        search = client.search(
            collections=["sentinel-2-l2a"], intersects=geom,
            datetime=f"{start_dt.strftime('%Y-%m-%d')}/{end_dt.strftime('%Y-%m-%d')}",
            query={"eo:cloud_cover": {"lt": 20}}, max_items=15)
        items = list(search.items())
        if not items:
            return pd.DataFrame()
        gdf  = gpd.GeoDataFrame(index=[0], crs="epsg:4326", geometry=[geom])
        rows = []
        for item in items:
            assets = item.assets
            try:
                bands = {"red": assets["red"].href, "nir": assets["nir"].href,
                         "rededge": assets["rededge1"].href, "swir": assets["swir16"].href}
                means = {}
                for b, url in bands.items():
                    rds     = rioxarray.open_rasterio(url)
                    gdf_p   = gdf.to_crs(rds.rio.crs)
                    clipped = rds.rio.clip(gdf_p.geometry, gdf_p.crs, drop=True)
                    arr     = np.where(clipped.values == 0, np.nan,
                                       clipped.values.astype(float))
                    means[b] = float(np.nanmean(arr))
                r, n, re, sw = means["red"], means["nir"], means["rededge"], means["swir"]
                rows.append({
                    "date":       pd.to_datetime(item.datetime.strftime("%Y-%m-%d")),
                    "NDVI_mean":  (n - r) / (n + r)                    if (n + r)  else np.nan,
                    "NDRE_mean":  (n - re) / (n + re)                  if (n + re) else np.nan,
                    "GNDVI_mean": (n - 0.5*(r+re)) / (n + 0.5*(r+re)) if n        else np.nan,
                    "MSI_mean":   sw / n                                if n        else np.nan,
                })
            except Exception:
                continue
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.groupby("date").mean(numeric_only=True).reset_index().sort_values("date")
        return df
    except Exception:
        return pd.DataFrame()



#Domain
def get_soil_props(soil_name: str) -> dict:
    return SOIL_WATER.get(soil_name, SOIL_WATER.get("default", {}))


def get_biome_thresholds(bioma_str: str) -> dict:
    vl = (bioma_str or "").lower()
    for key, canonical in BIOME_ALIASES_MAP.items():
        if key in vl:
            return {**BIOME_THRESHOLDS[canonical], "bioma": canonical}
    for canonical in BIOME_THRESHOLDS:
        if canonical != "default" and canonical.lower() in vl:
            return {**BIOME_THRESHOLDS[canonical], "bioma": canonical}
    return {**BIOME_THRESHOLDS["default"], "bioma": "default"}


def hargreaves_et0(tmin, tmax, lat_deg, doy):
    lat = math.radians(lat_deg)
    dr  = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws  = math.acos(max(-1.0, min(1.0, -math.tan(lat) * math.tan(dec))))
    Ra  = ((24 * 60 / math.pi) * 0.082 * dr *
           (ws * math.sin(lat) * math.sin(dec)
            + math.cos(lat) * math.cos(dec) * math.sin(ws)))
    return max(0.0023 * ((tmax + tmin) / 2 + 17.8) *
               (max(tmax - tmin, 0.0) ** 0.5) * (Ra * 0.408), 0.0)


def water_balance(clim: pd.DataFrame, lat_deg: float, soil: dict) -> pd.DataFrame:
    df = clim.copy().sort_values("date").reset_index(drop=True)
    df["doy"] = df["date"].dt.dayofyear
    df["eto"] = df.apply(
        lambda r: hargreaves_et0(
            float(r.get("tmin") or 0),
            float(r.get("tmax") or 30),
            lat_deg, int(r["doy"])), axis=1)
    df["balance_raw"] = df["prcp"].fillna(0) - df["eto"]
    awc = soil.get("AWC", 100); storage = awc * 0.5
    storages, runoffs, deficits = [], [], []
    for br in df["balance_raw"]:
        storage += br; runoff = deficit = 0.0
        if   storage > awc: runoff  = storage - awc; storage = awc
        elif storage < 0:   deficit = abs(storage);  storage = 0.0
        storages.append(round(storage, 2))
        runoffs.append(round(runoff, 2))
        deficits.append(round(deficit, 2))
    df["storage"]     = storages; df["runoff"] = runoffs; df["deficit"] = deficits
    df["storage_pct"] = (df["storage"] / awc * 100).round(1)
    df["balance_cum"] = df["balance_raw"].cumsum().round(2)
    return df


def compute_anomaly(clim_event: pd.DataFrame, hist: pd.DataFrame) -> dict:
    if clim_event.empty or hist.empty:
        return {}
    df = clim_event.copy(); df["month"] = df["date"].dt.month
    results = {}
    for var, label in [("prcp", "Precipitacao"), ("tmax", "Temp. max."), ("rh_avg", "Umidade rel.")]:
        if var not in df.columns:
            continue
        zs = []
        for _, row in df.iterrows():
            h = hist[hist["month"] == row["month"]]
            if h.empty: continue
            mu_col  = f"{var}_hist_mean"; sig_col = f"{var}_hist_std"
            if mu_col not in h.columns: continue
            mu  = h[mu_col].values[0]
            sig = h[sig_col].values[0] if sig_col in h.columns else None
            if sig is None or sig == 0 or pd.isna(sig): continue
            zs.append((row[var] - mu) / sig)
        if not zs: continue
        z   = float(np.mean(zs))
        cat = ("muito acima do normal" if z > 2 else "acima do normal" if z > 1
               else "dentro do normal" if z > -1 else "abaixo do normal" if z > -2
               else "muito abaixo do normal")
        results[var] = {"label": label, "z": round(z, 2), "categoria": cat}
    return results


def standalone_verdict(ts, clim, start, end, complaint, bioma):
    thr = get_biome_thresholds(bioma)
    score_map = {"sim": 1.0, "parcial": 0.5, "nao": 0.0, "nd": None}
    v_sat = "nd"
    if ts is not None and not ts.empty and len(ts) >= 2:
        ts_s  = ts.sort_values("date"); first, last = ts_s.iloc[0], ts_s.iloc[-1]
        avail = [i for i in VEG_POSITIVE if f"{i}_mean" in ts.columns]
        if avail:
            deltas = [last.get(f"{i}_mean", np.nan) - first.get(f"{i}_mean", np.nan)
                      for i in avail]
            mean_d = float(np.nanmean(deltas))
            good   = mean_d > 0.02 if complaint == "chuva" else mean_d < -0.02
            v_sat  = "sim" if good else "parcial" if abs(mean_d) > 0.01 else "nao"
    v_prcp = "nd"
    if clim is not None and not clim.empty:
        sub   = clim[(clim["date"] >= start) & (clim["date"] <= end)]
        total = sub["prcp"].fillna(0).sum()
        if complaint == "chuva":
            v_prcp = "sim" if total >= thr["prcp_alta"] else "parcial" if total >= 5 else "nao"
        else:
            v_prcp = "sim" if total <= thr["prcp_baixa"] else "parcial" if total <= 15 else "nao"
    v_clim = "nd"
    if clim is not None and not clim.empty:
        sub    = clim[(clim["date"] >= start) & (clim["date"] <= end)]
        avg_rh = sub["rh_avg"].mean(); avg_t = sub["tmax"].mean()
        if complaint == "chuva":
            v_clim = ("sim" if avg_rh >= thr["rh_alta"] else
                      "parcial" if avg_rh >= 60 else "nao")
        else:
            score  = ((1 if avg_rh <= thr["rh_baixa"] else 0)
                      + (1 if avg_t >= 28 else 0)) / 2
            v_clim = "sim" if score >= 1.0 else "parcial" if score >= 0.5 else "nao"
    sat_w = 0.0 if (ts is None or ts.empty) else (0.5 if len(ts) < 3 else 1.0)
    ws = tw = 0.0
    for status, w in [(v_sat, sat_w), (v_prcp, 1.0), (v_clim, 1.0)]:
        sc = score_map.get(status)
        if sc is not None and w > 0:
            ws += sc * w; tw += w
    if tw == 0:
        return "nd"
    return "sim" if ws / tw >= 0.70 else ("parcial" if ws / tw >= 0.35 else "nao")



#geometry
def _flatten(c, out):
    if not c: return
    if isinstance(c[0], (int, float)): out.append(c)
    else: [_flatten(x, out) for x in c]

def _ring_area(ring):
    R, n, area = 6371.0, len(ring), 0.0
    for i in range(n):
        j = (i + 1) % n
        lo1, la1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lo2, la2 = math.radians(ring[j][0]), math.radians(ring[j][1])
        area += (lo2 - lo1) * (2 + math.sin(la1) + math.sin(la2))
    return abs(area) * R * R / 2

def parse_geometry(geom):
    flat = []; _flatten(geom.get("coordinates", []), flat)
    gt, gc = geom.get("type", ""), geom.get("coordinates", [])
    rings, area = [], None
    if   gt == "Polygon"      and gc: area = _ring_area(gc[0]);                      rings = [gc[0]]
    elif gt == "MultiPolygon" and gc: area = sum(_ring_area(p[0]) for p in gc); rings = [p[0] for p in gc]
    if not flat: return [], [], None, 0.0, 0.0
    lon = sum(c[0] for c in flat) / len(flat)
    lat = sum(c[1] for c in flat) / len(flat)
    return flat, rings, area, lat, lon



#graphics
def chart_satellite(ts: pd.DataFrame, start, end):
    mean_cols = [c for c in ts.columns if c.endswith("_mean")]
    std_cols  = [c for c in ts.columns if c.endswith("_std")]
    use_std   = bool(std_cols)
    fig = make_subplots(
        rows=2 if use_std else 1, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35] if use_std else [1.0],
        vertical_spacing=0.06)
    for col in mean_cols:
        name = col.replace("_mean", "")
        fig.add_trace(go.Scatter(x=ts["date"], y=ts[col], name=name,
            line=dict(color=COLORS.get(name, "#aaa"), width=2.5),
            mode="lines+markers", marker=dict(size=7)), row=1, col=1)
    fig.add_vrect(x0=start, x1=end, fillcolor="rgba(255,255,255,0.04)",
        line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"), row=1, col=1)
    if use_std:
        for col in std_cols:
            name = col.replace("_std", "")
            fig.add_trace(go.Bar(x=ts["date"], y=ts[col], name=f"{name} sigma",
                marker_color=COLORS.get(name, "#aaa"), opacity=0.7,
                showlegend=False), row=2, col=1)
        fig.add_vrect(x0=start, x1=end, fillcolor="rgba(255,255,255,0.04)",
            line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"), row=2, col=1)
    fig.update_layout(**_PLOT_BASE,
        legend=dict(orientation="h", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=10, b=10), height=480, yaxis_title="Valor do indice")
    if use_std:
        fig.update_layout(yaxis2_title="Desvio padrao")
    fig.update_xaxes(**_GRID); fig.update_yaxes(**_GRID)
    return fig


def chart_clima(clim: pd.DataFrame, start, end, complaint):
    w_start = start - pd.Timedelta(days=5); w_end = end + pd.Timedelta(days=5)
    sub = clim[(clim["date"] >= w_start) & (clim["date"] <= w_end)].sort_values("date").copy()
    if sub.empty: return go.Figure()
    ac = accent(complaint); is_rain = (complaint == "chuva")
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.45, 0.30, 0.25],
        vertical_spacing=0.05,
        subplot_titles=("Precipitacao (mm)", "Temperatura (C)", "Umidade Relativa (%)"))
    bar_colors = [("#4a5568" if d < start else ac if d <= end else
                   ("#2d4a2e" if is_rain else "#4a2d1e")) for d in sub["date"]]
    fig.add_trace(go.Bar(x=sub["date"], y=sub["prcp"].fillna(0),
        name="Chuva diaria", marker_color=bar_colors, opacity=0.85), row=1, col=1)
    sub["prcp_cum"] = sub["prcp"].fillna(0).cumsum()
    fig.add_trace(go.Scatter(x=sub["date"], y=sub["prcp_cum"], name="Acumulado",
        line=dict(color=ac, width=2.5, dash="dot")), row=1, col=1)
    if "tmax" in sub.columns:
        fig.add_trace(go.Scatter(x=sub["date"], y=sub["tmax"], name="Tmax",
            line=dict(color="#f78166", width=2)), row=2, col=1)
    if "tmin" in sub.columns:
        fig.add_trace(go.Scatter(x=sub["date"], y=sub["tmin"], name="Tmin",
            line=dict(color="#58a6ff", width=2)), row=2, col=1)
    if "tavg" in sub.columns:
        fig.add_trace(go.Scatter(x=sub["date"], y=sub["tavg"], name="Tavg",
            line=dict(color="#d29922", width=1.5, dash="dash")), row=2, col=1)
    if "rh_avg" in sub.columns:
        fig.add_trace(go.Scatter(x=sub["date"], y=sub["rh_avg"], name="UR %",
            line=dict(color="#bc8cff", width=2), fill="tozeroy",
            fillcolor="rgba(188,140,255,0.08)"), row=3, col=1)
    evt_fill = "rgba(88,166,255,0.07)" if is_rain else "rgba(247,129,102,0.07)"
    for rn in [1, 2, 3]:
        fig.add_vrect(x0=start, x1=end, fillcolor=evt_fill,
            line=dict(color=ac, width=1.2, dash="dot"), row=rn, col=1)
    fig.add_annotation(x=start + (end - start) / 2, y=1, yref="paper",
        text=f"EVENTO ({(end - start).days + 1}d)", showarrow=False,
        font=dict(color=ac, size=11, family="Space Mono"), xanchor="center")
    fig.update_layout(**_PLOT_BASE,
        legend=dict(orientation="h", y=1.06, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=44, b=10), height=560, barmode="overlay")
    fig.update_xaxes(**_GRID); fig.update_yaxes(**_GRID)
    return fig


def chart_precip_cum(clim: pd.DataFrame, start, end, complaint):
    sub = clim[(clim["date"] >= start) & (clim["date"] <= end)].copy().sort_values("date")
    if sub.empty: return None
    sub["cumsum"] = sub["prcp"].fillna(0).cumsum()
    ac = accent(complaint)
    try:
        rgb = px.colors.hex_to_rgb(ac)
        fill_color = f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.12)"
    except Exception:
        fill_color = "rgba(88,166,255,0.12)"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sub["date"], y=sub["cumsum"], name="Acumulado (mm)",
        line=dict(color=ac, width=3), fill="tozeroy", fillcolor=fill_color))
    max_p = sub["prcp"].max() or 1
    fig.add_trace(go.Bar(x=sub["date"], y=sub["prcp"].fillna(0), name="Diario (mm)",
        marker_color=ac, opacity=0.4, yaxis="y2"))
    fig.update_layout(**_PLOT_BASE,
        yaxis=dict(title="Acumulado (mm)"),
        yaxis2=dict(title="Diario (mm)", overlaying="y", side="right",
                    showgrid=False, range=[0, max_p * 4]),
        legend=dict(orientation="h", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10), height=280,
        title=dict(text="Precipitacao acumulada no periodo do evento", font=dict(size=14)))
    return fig


def chart_water_balance(wb: pd.DataFrame, start, end, complaint):
    sub = wb[(wb["date"] >= start - pd.Timedelta(days=5)) &
             (wb["date"] <= end   + pd.Timedelta(days=5))]
    if sub.empty: return None
    ac  = accent(complaint)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        subplot_titles=("Armazenamento de Agua no Solo (%)",
                        "Deficit / Excedente (mm)"))
    fig.add_trace(go.Scatter(x=sub["date"], y=sub["storage_pct"],
        name="Armazenamento %", line=dict(color="#58a6ff", width=2.5),
        fill="tozeroy", fillcolor="rgba(88,166,255,0.08)"), row=1, col=1)
    fig.add_hline(y=50, line=dict(color="#8b949e", dash="dash", width=1), row=1, col=1)
    fig.add_trace(go.Bar(x=sub["date"], y=sub["deficit"], name="Deficit (mm)",
        marker_color="#f78166", opacity=0.8), row=2, col=1)
    fig.add_trace(go.Bar(x=sub["date"], y=sub["runoff"], name="Excedente (mm)",
        marker_color="#58a6ff", opacity=0.8), row=2, col=1)
    for rn in [1, 2]:
        fig.add_vrect(x0=start, x1=end, fillcolor="rgba(247,129,102,0.06)",
            line=dict(color=ac, width=1, dash="dot"), row=rn, col=1)
    fig.update_layout(**_PLOT_BASE, height=460, barmode="relative",
        legend=dict(orientation="h", y=1.06),
        margin=dict(l=10, r=10, t=44, b=10))
    fig.update_xaxes(**_GRID); fig.update_yaxes(**_GRID)
    return fig



#folium Map
def build_map(rings_plot, lat, lon, ts_df, sel_index, sel_date_str):
    if not HAS_FOLIUM or not rings_plot:
        return None
    m        = folium.Map(location=[lat, lon], zoom_start=13, tiles="CartoDB dark_matter")
    fill_hex = "#bc8cff"; fill_op = 0.25; val_label = None
    meta     = INDEX_META.get(sel_index or "", {})
    col_name = f"{sel_index}_mean" if sel_index else None
    if (col_name and ts_df is not None and not ts_df.empty
            and col_name in ts_df.columns and sel_date_str):
        row_data = ts_df[ts_df["date"].dt.strftime("%Y-%m-%d") == sel_date_str]
        if not row_data.empty:
            val       = float(row_data[col_name].iloc[0])
            all_vals  = ts_df[col_name].dropna().tolist()
            fill_hex  = idx_color(val, all_vals, meta)
            fill_op   = 0.60
            val_label = f"{sel_index} = {val:.4f}"
    poly_color = fill_hex
    for ring in rings_plot:
        folium.Polygon(locations=[(p[1], p[0]) for p in ring],
            color=poly_color, weight=2, fill=True,
            fill_color=fill_hex, fill_opacity=fill_op,
            tooltip=val_label or "Poligono do evento").add_to(m)
    folium.CircleMarker(location=[lat, lon], radius=7, color=poly_color,
        fill=True, fill_color=fill_hex, tooltip="Centroide").add_to(m)
    if val_label and meta:
        lo_hex = rgb_to_hex(meta.get("color_low", (220, 50, 30)))
        hi_hex = rgb_to_hex(meta.get("color_high", (30, 180, 60)))
        lo_lbl = "Baixo" if not meta.get("invert") else "Alto"
        hi_lbl = "Alto"  if not meta.get("invert") else "Baixo"
        legend = (f"<div style='position:fixed;bottom:30px;right:10px;z-index:9999;"
                  f"background:#161b22cc;border:1px solid #30363d;border-radius:8px;"
                  f"padding:10px 14px;font-family:monospace;font-size:12px;color:#e6edf3'>"
                  f"<div style='font-weight:700;margin-bottom:6px;color:#bc8cff'>{sel_index}</div>"
                  f"<div style='display:flex;align-items:center;gap:8px'>"
                  f"<span style='color:{lo_hex}'>{lo_lbl}</span>"
                  f"<div style='width:80px;height:10px;border-radius:4px;"
                  f"background:linear-gradient(to right,{lo_hex},{hi_hex})'></div>"
                  f"<span style='color:{hi_hex}'>{hi_lbl}</span></div>"
                  f"<div style='margin-top:6px;font-size:11px;color:#8b949e'>"
                  f"{meta.get('desc','')}</div></div>")
        m.get_root().html.add_child(folium.Element(legend))
    return m



#diagnostic panels


def panel_pipeline_diag(analysis: dict, cop_data: dict, pos_summ: dict, pos_vote: dict):
    verdict = analysis.get("verdict", "INCONCLUSIVO")
    v_key   = {"CONFIRMED": "sim", "NOT CONFIRMED": "nao",
               "INCONCLUSIVE": "parcial"}.get(verdict, "parcial")
    color   = STATUS_COLOR[v_key]
    conf    = analysis.get("confidence", 0)
    sev     = analysis.get("severity", "-")
    idw     = analysis.get("idw_score", 0)

    st.markdown(f"""
    <div class='verdict-card verdict-{v_key}'>
      <div style='font-size:13px;color:#8b949e;font-family:Space Mono,monospace;
           text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px'>
        Poseidon + Copernicus + EMBRAPA</div>
      <div style='font-size:32px;font-weight:700;font-family:Space Mono,monospace;color:{color}'>
        {'✅' if v_key=='sim' else '❌' if v_key=='nao' else '⚠️'} {STATUS_LABEL[v_key]}</div>
      <div style='display:flex;gap:24px;margin-top:10px;flex-wrap:wrap'>
        <span style='font-size:13px;color:#8b949e'>Confianca: <b style='color:{color}'>{conf:.0f}%</b></span>
        <span style='font-size:13px;color:#8b949e'>Severidade: <b style='color:{color}'>{sev}</b></span>
        <span style='font-size:13px;color:#8b949e'>IDW Score: <b style='color:{color}'>{idw:.0f}/100</b></span>
      </div>
    </div>""", unsafe_allow_html=True)

    checks = [c for c in (analysis.get("checks") or []) if c.get("weight", 0) > 0]
    if checks:
        st.markdown("#### Criterios de Validacao")
        c1, c2 = st.columns(2)
        for i, chk in enumerate(checks):
            ok  = chk.get("passed", False)
            col = c1 if i % 2 == 0 else c2
            clr = "#3fb950" if ok else "#f85149"
            col.markdown(f"""
            <div style='background:#161b22;border:1px solid {"#1a3a1a" if ok else "#3a1a1a"};
                 border-radius:8px;padding:10px 12px;margin-bottom:8px'>
              <div style='font-size:12px;color:#8b949e'>{"✅" if ok else "❌"} {chk.get("name","")}</div>
              <div style='font-size:11px;color:{clr};margin-top:3px'>{chk.get("value","")}</div>
            </div>""", unsafe_allow_html=True)
        sm = analysis.get("summary", {})
        if sm:
            st.caption(f"Score: **{sm.get('score_raw','—')}** "
                       f"({sm.get('pct_score','—')}) · "
                       f"Criterios: {sm.get('checks_passed',0)}/{sm.get('checks_total',0)}")

    if pos_summ:
        st.markdown("---"); st.markdown("#### Meteorologia Poseidon (IDW)")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Precipitacao",  f"{pos_summ.get('prcp_total_mm',0):.1f} mm")
        m2.metric("Temp. media",   f"{pos_summ.get('tavg_mean_c',0):.1f} C")
        m3.metric("Tmax absoluta", f"{pos_summ.get('tmax_abs_c',0):.1f} C")
        m4.metric("UR media",      f"{pos_summ.get('rh_avg_mean_pct',0):.0f}%")
        m5.metric("Vento max.",    f"{pos_summ.get('wspd_max_kmh',0):.0f} km/h")

    if pos_vote:
        ws = pos_vote.get("weighted_score", 0)
        sl = pos_vote.get("signal_level", "")
        ok = pos_vote.get("passed", False)
        vc = "#3fb950" if ok else "#f85149"
        st.markdown(f"""
        <div style='background:#161b22;border:1px solid {vc};border-radius:8px;
             padding:10px 14px;margin-top:8px'>
          <b style='color:{vc}'>IDW Score: {ws:.0f}/100 — signal {sl}</b>
          {"  ✅ APPROVED" if ok else "  ❌ REJECTED"}
        </div>""", unsafe_allow_html=True)

    vhi_data = cop_data.get("VHI") or {}
    vhi = vhi_data.get("event_mean")
    if vhi is not None:
        vci = vhi_data.get("vci", "N/D"); tci = vhi_data.get("tci", "N/D")
        vc  = "#f85149" if vhi < 35 else "#d29922" if vhi < 50 else "#3fb950"
        lbl = "Estresse Severo" if vhi < 35 else "Estresse Moderado" if vhi < 50 else "Saudavel"
        st.markdown(f"""
        <div style='background:#161b22;border:1px solid {vc};border-radius:8px;
             padding:12px 16px;margin-top:12px'>
          <div style='font-size:11px;color:#8b949e;text-transform:uppercase'>
            VHI — Vegetation Health Index</div>
          <div style='font-size:26px;font-weight:700;font-family:Space Mono,monospace;
               color:{vc};margin:4px 0'>{vhi:.1f} — {lbl}</div>
          <div style='font-size:12px;color:#8b949e'>
            VCI: {vci} &nbsp;|&nbsp; TCI: {tci}</div>
        </div>""", unsafe_allow_html=True)

    loss = analysis.get("loss_estimate") or {}
    if loss:
        st.markdown("---"); st.markdown("#### Estimativa de Perdas Economicas")
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Perda de Produtividade", f"{loss.get('yield_loss_pct',0):.1f}%")
        l2.metric("Sacas Perdidas",         f"{loss.get('yield_loss_total_sacas',0):,.0f}")
        l3.metric("Receita Esperada",       brl(loss.get("expected_revenue_brl", 0)))
        l4.metric("Perda Financeira",       brl(loss.get("financial_loss_brl", 0)))
        comp = loss.get("loss_frac_components", {})
        if comp:
            st.caption(
                f"Componentes: deficit climatico {comp.get('climate_loss',0):.0f}% | "
                f"anomalia NDVI {comp.get('ndvi_loss',0):.0f}% | "
                f"sensibilidade fenologica {comp.get('phase_sensitivity',0):.0f}% | "
                f"fator solo {comp.get('soil_amplifier',1.0):.2f}x")

    soil_chk = analysis.get("soil_check") or {}
    if soil_chk.get("available"):
        amp = soil_chk.get("amplifier", 1.0)
        ac2 = "#f85149" if amp > 1.0 else "#3fb950"
        act = "AMPLIFICA" if amp > 1.0 else "ATENUA"
        st.markdown(f"""
        <div style='background:#161b22;border:1px solid #30363d;border-radius:8px;
             padding:8px 12px;margin-top:8px;font-size:12px'>
          Solo <b>{soil_chk.get("soil_name","N/D")}</b>
          AWC={soil_chk.get("AWC","N/D")} mm/m · retention: {soil_chk.get("retention","N/D")}
          — <span style='color:{ac2}'><b>{act}</b> damage by {amp:.2f}x</span>
        </div>""", unsafe_allow_html=True)


def panel_standalone_diag(v_total, clim_event, hist_df):
    color = STATUS_COLOR.get(v_total, "#8b949e")
    cls   = f"verdict-{v_total if v_total != 'nd' else 'parcial'}"
    icon  = {"sim": "✅", "nao": "❌", "parcial": "⚠️"}.get(v_total, "—")
    st.markdown(f"""
    <div class='verdict-card {cls}'>
      <div style='font-size:13px;color:#8b949e;font-family:Space Mono,monospace;
           text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px'>
        Standalone Diagnostics · Open-Meteo + Sentinel-2</div>
      <div style='font-size:32px;font-weight:700;font-family:Space Mono,monospace;color:{color}'>
        {icon} {STATUS_LABEL.get(v_total,"—")}</div>
    </div>""", unsafe_allow_html=True)
    anomaly = compute_anomaly(clim_event, hist_df)
    if anomaly:
        st.markdown("---"); st.markdown("### Anomalia Climatica Historica")
        st.caption("Z-score vs 10-year baseline · Open-Meteo")
        color_cat = {
            "muito abaixo do normal": "#f85149", "abaixo do normal": "#f78166",
            "dentro do normal": "#8b949e", "acima do normal": "#58a6ff",
            "muito acima do normal": "#3fb950",
        }
        cols = st.columns(len(anomaly))
        for col, (var, info) in zip(cols, anomaly.items()):
            clr = color_cat.get(info["categoria"], "#8b949e")
            col.markdown(f"""
            <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;
                 padding:12px 14px;text-align:center">
              <div style="font-size:11px;color:#8b949e;text-transform:uppercase">{info['label']}</div>
              <div style="font-size:26px;font-weight:700;font-family:'Space Mono',monospace;
                   color:{clr};margin:6px 0">
                {info['z']:+.2f}<span style="font-size:12px">sigma</span></div>
              <div style="font-size:12px;color:{clr}">{info['categoria']}</div>
            </div>""", unsafe_allow_html=True)



#MAIN
def main():
    st.sidebar.markdown("## Agricultural Diagnostics")
    st.sidebar.markdown("---")

    mode = st.sidebar.radio(
        "Fonte de dados",
        ["Pipeline (JSON do main.py)", "Standalone (GeoJSON)"],
        help=("Pipeline: usa dados reais Poseidon + Copernicus exportados pelo main.py.\n"
              "Standalone: busca dados via Open-Meteo + STAC/Sentinel-2."),
    )
    pipeline_mode = mode.startswith("Pipeline")

    #UPLOAD FILE
    if pipeline_mode:
        uploaded = st.sidebar.file_uploader(
            "pipeline_*.json", type=["json"],
            help="Gerado automaticamente pelo main.py na pasta do projeto.")
        if not uploaded:
            st.markdown("""
            <div style="display:flex;flex-direction:column;align-items:center;
                        justify-content:center;margin-top:80px;gap:18px;text-align:center">
              <div style="font-size:58px">📦</div>
              <div style="font-size:22px;font-weight:700;font-family:'Space Mono',monospace">
                Modo Pipeline</div>
              <div style="font-size:14px;color:#8b949e;max-width:480px;line-height:1.8">
                Execute o <code style="color:#58a6ff">main.py</code> normalmente.<br>
                Um arquivo <code style="color:#58a6ff">pipeline_*.json</code> sera gerado
                automaticamente junto com o DOCX.<br><br>
                Carregue-o aqui para visualizar o diagnostico completo.
              </div>
            </div>""", unsafe_allow_html=True)
            return
        try:
            pipeline = json.loads(uploaded.read())
        except Exception as e:
            st.error(f"Erro ao ler JSON: {e}"); return

        meta       = pipeline.get("meta", {})
        farm_name  = meta.get("farm_name", "Propriedade Rural")
        complaint  = meta.get("event_type", "seca").lower()
        crop_type  = meta.get("crop_type", "").upper()
        start_dt   = pd.to_datetime(meta.get("start_date"))
        end_dt     = pd.to_datetime(meta.get("end_date"))
        area_ha    = float(meta.get("area_ha") or 0)
        centroid   = meta.get("centroid", {})
        lat        = float(centroid.get("lat", 0))
        lon        = float(centroid.get("lon", 0))
        geom       = pipeline.get("geometry", {})
        analysis   = pipeline.get("analysis", {})
        cop_data   = pipeline.get("copernicus", {})
        pos_summ   = pipeline.get("poseidon_summary", {})
        pos_vote   = pipeline.get("poseidon_vote", {})
        pos_daily  = pipeline.get("poseidon_daily", [])
        soil_data  = pipeline.get("soil_data") or {}

        _, rings_plot, area_km2, _, _ = parse_geometry(geom)
        if area_ha == 0 and area_km2:
            area_ha = area_km2 * 100

        ts   = cop_to_ts(cop_data)
        clim = pos_daily_to_df(pos_daily)

        soil_name  = ((soil_data.get("resolved_name") or soil_data.get("soil_name") or "default")
                      if soil_data else "default")
        soil_props = get_soil_props(soil_name)

        src_tag = ("<span style='background:#1a1f2e;color:#bc8cff;border:1px solid #bc8cff;"
                   "border-radius:12px;font-size:11px;padding:2px 8px;"
                   "font-family:Space Mono,monospace'>Poseidon + Copernicus + EMBRAPA</span>")
        #there is no history for pipeline mode (Poseidon already has its own baseline).
        hist_api  = pd.DataFrame()
        clim_event = clim[(clim["date"] >= start_dt) & (clim["date"] <= end_dt)].copy() if not clim.empty else pd.DataFrame()

    else:
        #STANDALONE
        uploaded = st.sidebar.file_uploader(
            "Caso (.geojson / .json)", type=["geojson", "json"],
            help="FeatureCollection com: evento, inicio, fim, solo, bioma, cultura.")
        if not uploaded:
            st.markdown("""
            <div style="display:flex;flex-direction:column;align-items:center;
                        justify-content:center;margin-top:80px;gap:18px;text-align:center">
              <div style="font-size:58px">🛰️</div>
              <div style="font-size:24px;font-weight:700;font-family:'Space Mono',monospace">
                Modo Standalone</div>
              <div style="font-size:14px;color:#8b949e;max-width:440px;line-height:1.8">
                Envie um <b style="color:#58a6ff">.geojson</b> com os campos:<br>
                <code>evento, inicio, fim, solo, bioma, cultura</code><br><br>
                Dados via <b>Open-Meteo</b> + <b>STAC / Sentinel-2</b>.
              </div>
            </div>""", unsafe_allow_html=True)
            return
        try:
            gj = json.loads(uploaded.read())
        except Exception as e:
            st.error(f"Erro ao ler GeoJSON: {e}"); return

        gtype = gj.get("type", "")
        if   gtype == "FeatureCollection": all_feat = gj.get("features", [])
        elif gtype == "Feature":           all_feat = [gj]
        else:                              all_feat = [{"type": "Feature", "geometry": gj, "properties": {}}]
        if not all_feat: st.error("GeoJSON sem features."); return

        if len(all_feat) > 1:
            labels = [f"#{f.get('properties',{}).get('id',i+1)} – "
                      f"{str(f.get('properties',{}).get('evento','?')).upper()}"
                      for i, f in enumerate(all_feat)]
            feat_idx = st.sidebar.selectbox("Caso", range(len(all_feat)),
                                            format_func=lambda i: labels[i])
        else:
            feat_idx = 0

        feat      = all_feat[feat_idx]
        props     = feat.get("properties", {}) or {}
        geom      = feat.get("geometry", {})   or {}
        farm_name = str(props.get("id", "-"))
        complaint = str(props.get("evento", "seca")).lower().strip()
        start_dt  = pd.to_datetime(props.get("inicio"), errors="coerce")
        end_dt    = pd.to_datetime(props.get("fim"),    errors="coerce")
        crop_type = str(props.get("cultura", "")).upper()
        bioma_str = str(props.get("bioma", ""))
        solo_str  = str(props.get("solo", "default"))

        if pd.isna(start_dt) or pd.isna(end_dt):
            st.error("Properties 'inicio' e 'fim' devem estar no formato YYYY-MM-DD."); return

        coords_flat, rings_plot, area_km2, lat, lon = parse_geometry(geom)
        if not coords_flat: st.error("Geometria sem coordenadas."); return
        area_ha = area_km2 * 100 if area_km2 else 0

        # Solo
        soil_name = "default"
        for alias, canonical in SOIL_ALIASES.items():
            if solo_str.lower().startswith(alias) or alias in solo_str.lower():
                soil_name = canonical; break
        soil_props = get_soil_props(soil_name)

        cop_data = {}; pos_summ = {}; pos_vote = {}
        analysis = {}; soil_data = {}

        with st.spinner("Buscando dados climaticos (Open-Meteo)..."):
            clim = fetch_openmeteo(float(lat), float(lon), start_dt, end_dt)
        if clim.empty:
            st.error("Nao foi possivel recuperar dados climaticos."); return

        ts = pd.DataFrame()
        if HAS_STAC and HAS_GEO:
            with st.spinner("Buscando imagens Sentinel-2 via STAC..."):
                ts = fetch_stac(feat, start_dt.strftime("%Y-%m-%d"),
                                end_dt.strftime("%Y-%m-%d"))

        with st.spinner("Buscando baseline historico (Open-Meteo)..."):
            hist_api = fetch_openmeteo_hist(float(lat), float(lon), start_dt)

        clim_event = clim[(clim["date"] >= start_dt) & (clim["date"] <= end_dt)].copy()
        v_total    = standalone_verdict(ts if not ts.empty else None,
                                        clim, start_dt, end_dt, complaint, bioma_str)

        src_tag = ("<span style='background:#1c2030;color:#58a6ff;border:1px solid #58a6ff;"
                   "border-radius:12px;font-size:11px;padding:2px 8px;"
                   "font-family:Space Mono,monospace'>Open-Meteo + STAC</span>")

    #HEADER
    evt_label = {"seca": "Seca / Deficit Hidrico", "chuva": "Excesso de Chuva",
                 "geada": "Geada", "granizo": "Granizo"}.get(complaint, complaint.upper())
    badge_cls = "badge-chuva" if complaint == "chuva" else "badge-seca"

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;flex-wrap:wrap">
      <h1 style="margin:0;font-size:26px">{farm_name}</h1>
      <span class="badge {badge_cls}">{complaint.upper()}</span>
      {src_tag}
    </div>
    <div style="color:#8b949e;font-size:14px;margin-bottom:18px">{evt_label}</div>
    """, unsafe_allow_html=True)

    n_sat = str(ts["date"].nunique()) if not ts.empty else "0"
    st.markdown(
        "<div class='info-grid'>"
        + info_cell("Inicio",  start_dt.strftime("%d/%m/%Y"))
        + info_cell("Fim",     end_dt.strftime("%d/%m/%Y"))
        + info_cell("Duracao", f"{(end_dt - start_dt).days + 1} dias")
        + info_cell("Area",    f"{area_ha:.1f} ha" if area_ha else "-")
        + info_cell("Imagens", n_sat)
        + (info_cell("Cultura", crop_type) if crop_type else "")
        + "</div>", unsafe_allow_html=True)

    st.sidebar.success(f"lat {lat:.4f} / lon {lon:.4f}")
    st.sidebar.caption(f"{farm_name} · {complaint.upper()}\n"
                       f"{start_dt.strftime('%d/%m/%Y')} - {end_dt.strftime('%d/%m/%Y')}")

    #TABS
    tab_diag, tab_sat, tab_clima, tab_bal, tab_map = st.tabs([
        "Diagnostics", "Satellite", "Climate", "Water Balance", "Location"])

    #diagnostic
    with tab_diag:
        if pipeline_mode:
            panel_pipeline_diag(analysis, cop_data, pos_summ, pos_vote)
        else:
            panel_standalone_diag(v_total, clim_event, hist_api)

    #satellite
    with tab_sat:
        if ts.empty:
            msg = ("Serie temporal Copernicus nao disponivel no pipeline JSON."
                   if pipeline_mode else
                   "Nenhuma imagem Sentinel-2 sem nuvens encontrada.")
            st.warning(msg)
            if not pipeline_mode and not HAS_STAC:
                st.info("Para usar STAC instale: pip install pystac-client rioxarray")
        else:
            src = "Copernicus/Sentinel-2 (Baseline + Evento)" if pipeline_mode else "STAC Element84/AWS"
            st.markdown("#### Serie Temporal dos Indices Espectrais")
            st.caption(f"*{ts['date'].nunique()} data(s) · {src}*")
            st.plotly_chart(chart_satellite(ts, start_dt, end_dt), use_container_width=True)

            if pipeline_mode and cop_data:
                st.markdown("#### Comparativo Baseline vs Evento")
                rows = []
                for idx_name, data in cop_data.items():
                    if idx_name == "VHI" or not isinstance(data, dict): continue
                    b = data.get("baseline_mean"); e = data.get("event_mean")
                    pct = data.get("anomaly_pct"); obs = data.get("observations", 0)
                    if e is None: continue
                    rows.append({
                        "Indice":   idx_name,
                        "Baseline": f"{b:.4f}" if b is not None else "N/D",
                        "Evento":   f"{e:.4f}",
                        "Delta%":   f"{pct:+.1f}%" if pct is not None else "N/D",
                        "Obs.":     obs,
                    })
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            with st.expander("Dados brutos"):
                st.dataframe(ts, use_container_width=True, height=300)

    #climate
    with tab_clima:
        if clim.empty:
            st.warning("Dados climaticos nao disponiveis.")
        else:
            src = "Poseidon IDW" if pipeline_mode else "Open-Meteo Archive API"
            st.caption(f"Source: **{src}** — lat {lat:.4f}, lon {lon:.4f}")
            ac   = accent(complaint)
            glow = "rgba(88,166,255,0.12)" if complaint == "chuva" else "rgba(247,129,102,0.12)"
            w_s  = start_dt - pd.Timedelta(days=5)
            w_e  = end_dt   + pd.Timedelta(days=5)

            def _card(title, df, hi=False):
                if df.empty:
                    return (f"<div style='background:#161b22;border:1px solid #30363d;"
                            f"border-radius:8px;padding:14px 16px'>"
                            f"<div style='font-size:11px;color:#8b949e'>{title}</div>"
                            f"<div style='color:#8b949e'>Sem dados</div></div>")
                bd = f"2px solid {ac}" if hi else "1px solid #30363d"
                sh = f"box-shadow:0 0 18px {glow};" if hi else ""
                tc = ac if hi else "#8b949e"
                return (f"<div style='background:#161b22;border:{bd};border-radius:8px;"
                        f"padding:14px 16px;{sh}'>"
                        f"<div style='font-size:11px;color:{tc};text-transform:uppercase;"
                        f"{'font-weight:700;' if hi else ''}margin-bottom:6px'>{title}</div>"
                        f"<div style='font-size:{'24' if hi else '22'}px;font-weight:700;"
                        f"font-family:Space Mono,monospace;color:{tc}'>"
                        f"{df['prcp'].fillna(0).sum():.1f} mm</div>"
                        f"<div style='font-size:12px;color:#8b949e;margin-top:4px'>"
                        f"Tmax {df['tmax'].mean():.1f}C · RH {df['rh_avg'].mean():.0f}%</div></div>")

            st.markdown(
                "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;"
                "gap:12px;margin-bottom:20px'>"
                + _card("5 dias antes",
                        clim[(clim["date"] >= w_s) & (clim["date"] < start_dt)])
                + _card(f"Evento ({(end_dt - start_dt).days + 1} dias)",
                        clim[(clim["date"] >= start_dt) & (clim["date"] <= end_dt)], hi=True)
                + _card("5 dias depois",
                        clim[(clim["date"] > end_dt) & (clim["date"] <= w_e)])
                + "</div>", unsafe_allow_html=True)

            st.plotly_chart(chart_clima(clim, start_dt, end_dt, complaint), use_container_width=True)
            fig_cum = chart_precip_cum(clim, start_dt, end_dt, complaint)
            if fig_cum:
                st.markdown("---")
                st.plotly_chart(fig_cum, use_container_width=True)

            with st.expander("Dados brutos (+-5 dias)"):
                win  = clim[(clim["date"] >= w_s) & (clim["date"] <= w_e)].copy()
                cols = [c for c in ["date","prcp","tmin","tmax","tavg","rh_avg","wspd_avg"]
                        if c in win.columns]
                st.dataframe(win[cols].sort_values("date").round(2),
                             use_container_width=True, height=300)

    #HYDRAULIC BALANCE
    with tab_bal:
        if clim.empty:
            st.warning("Dados climaticos nao disponiveis.")
        else:
            try:
                wb  = water_balance(clim, float(lat), soil_props)
                fig = chart_water_balance(wb, start_dt, end_dt, complaint)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                wb_evt = wb[(wb["date"] >= start_dt) & (wb["date"] <= end_dt)]
                awc    = soil_props.get("AWC", 100)
                ret    = soil_props.get("retention", "-")
                st.caption(
                    f"Soil: **{soil_name}** · AWC = {awc} mm/m · Retention: {ret} · "
                    f"Total event deficit: **{wb_evt['deficit'].sum():.1f} mm** · "
                    f"Excedente: **{wb_evt['runoff'].sum():.1f} mm**")
            except Exception as e:
                st.error(f"Erro no balanco hidrico: {e}")

    #MAPA
    with tab_map:
        if not HAS_FOLIUM:
            st.warning("Instale folium e streamlit-folium: "
                       "pip install folium streamlit-folium")
        else:
            available_indices = [k for k in ALL_INDICES
                                 if not ts.empty and f"{k}_mean" in ts.columns]
            available_dates   = (sorted(ts["date"].dt.strftime("%Y-%m-%d").unique())
                                 if not ts.empty else [])
            has_sat = bool(available_indices and available_dates)
            sel_idx  = None
            sel_date = available_dates[len(available_dates) // 2] if available_dates else None

            col_map, col_right = st.columns([3, 2])

            with col_right:
                st.markdown("<div class='side-title'>Indice Espectral</div>",
                            unsafe_allow_html=True)
                if not has_sat:
                    st.info("Nenhuma data de satelite disponivel.")
                else:
                    choice = st.radio("idx_radio",
                        options=["-- Nenhum --"] + available_indices, index=0,
                        label_visibility="collapsed",
                        format_func=lambda x: x if x == "-- Nenhum --"
                                              else f"{x} — {INDEX_META.get(x,{}).get('desc','')}")
                    sel_idx = None if choice == "-- Nenhum --" else choice
                    if sel_idx:
                        meta = INDEX_META[sel_idx]
                        lo_h = rgb_to_hex(meta["color_low"]); hi_h = rgb_to_hex(meta["color_high"])
                        lo_l = "Baixo" if not meta.get("invert") else "Alto"
                        hi_l = "Alto"  if not meta.get("invert") else "Baixo"
                        st.markdown(f"""
                        <div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;
                             padding:9px 11px;margin-top:10px">
                          <div style="font-size:11px;color:#8b949e;margin-bottom:5px">
                            {meta['desc']}</div>
                          <div style="display:flex;align-items:center;gap:6px;font-size:11px">
                            <span style="color:{lo_h}">{lo_l}</span>
                            <div style="flex:1;height:8px;border-radius:4px;
                                 background:linear-gradient(to right,{lo_h},{hi_h})"></div>
                            <span style="color:{hi_h}">{hi_l}</span>
                          </div>
                        </div>""", unsafe_allow_html=True)

                st.markdown("<hr style='border-color:#30363d;margin:16px 0 14px'>",
                            unsafe_allow_html=True)
                st.markdown("<div class='side-title'>Data Selecionada</div>",
                            unsafe_allow_html=True)
                if has_sat:
                    sel_date = st.selectbox("data_img", options=available_dates,
                        index=len(available_dates) // 2, label_visibility="collapsed")
                    if sel_idx and sel_date:
                        col_name = f"{sel_idx}_mean"
                        row_data = ts[ts["date"].dt.strftime("%Y-%m-%d") == sel_date]
                        if not row_data.empty and col_name in ts.columns:
                            val     = float(row_data[col_name].iloc[0])
                            meta    = INDEX_META.get(sel_idx, {})
                            all_v   = ts[col_name].dropna().tolist()
                            vc      = idx_color(val, all_v, meta)
                            col_min = float(ts[col_name].min())
                            col_max = float(ts[col_name].max())
                            st.markdown(f"""
                            <div style="background:#0d1117;border:1px solid {vc};border-radius:8px;
                                 padding:10px 14px;margin-top:10px">
                              <div style="font-size:11px;color:#8b949e">
                                {sel_idx} · {sel_date}</div>
                              <div style="font-size:28px;font-weight:700;
                                   font-family:'Space Mono',monospace;color:{vc};margin:4px 0">
                                {val:.4f}</div>
                              <div style="font-size:11px;color:#8b949e">
                                min {col_min:.3f} · max {col_max:.3f}</div>
                            </div>""", unsafe_allow_html=True)

                    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
                    for d in available_dates:
                        in_evt = start_dt <= pd.to_datetime(d) <= end_dt
                        dc     = "#3fb950" if in_evt else "#8b949e"
                        fw     = "font-weight:700;" if d == sel_date else ""
                        tag    = " evento" if in_evt else ""
                        st.markdown(
                            f"<div style='font-size:12px;font-family:Space Mono,monospace;"
                            f"color:{dc};padding:2px 0;{fw}'>● {d}{tag}</div>",
                            unsafe_allow_html=True)

            with col_map:
                m_folium = build_map(
                    rings_plot=rings_plot, lat=lat, lon=lon,
                    ts_df=ts if not ts.empty else None,
                    sel_index=sel_idx, sel_date_str=sel_date)
                if m_folium:
                    st_folium(m_folium, height=540, use_container_width=True)
                else:
                    st.info("Mapa nao disponivel.")

            with st.expander("Coordenadas da geometria"):
                flat, _, _, _, _ = parse_geometry(geom)
                st.dataframe(pd.DataFrame([{"lon": p[0], "lat": p[1]} for p in flat]),
                             use_container_width=True)


if __name__ == "__main__":
    main()
