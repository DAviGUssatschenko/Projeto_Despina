"""
dashboard.py — Diagnóstico Agrícola · Poseidon + Copernicus/Sentinel-2

Entrada: arquivo .geojson no formato FeatureCollection com properties:
  id, evento, inicio, fim, solo, cultura, bioma

Fonte climática: Poseidon (PostgreSQL/IDW) — credenciais via .env / config.py.
Fonte satélite : STAC Element84 / Sentinel-2 (pystac-client + rioxarray).
"""

import os
import json
import math
import warnings
from pathlib import Path
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ── carrega .env automaticamente (python-dotenv) ─────────────────────────────
# Tenta todos os caminhos possíveis onde o .env pode estar.
# override=True garante que o .env sempre vence variáveis de ambiente herdadas.
# ─────────────────────────────────────────────────────────────────────────────
# .env loader — parse manual robusto, sem python-dotenv
# O .env é lido linha a linha; suporta aspas simples/duplas, BOM, CRLF, comentários.
# SEMPRE sobrescreve os.environ (override=True) para garantir que o .env vença.
# ─────────────────────────────────────────────────────────────────────────────
def _load_env_manual():
    import sys, os
    from pathlib import Path

    candidates = []
    # cwd e até 3 pais
    p = Path.cwd()
    for _ in range(4):
        candidates.append(p / ".env")
        p = p.parent
    # diretório do script invocado
    if sys.argv and sys.argv[0]:
        s = Path(sys.argv[0]).resolve().parent
        candidates += [s / ".env", s.parent / ".env"]
    # __file__
    try:
        f = Path(__file__).resolve().parent
        candidates += [f / ".env", f.parent / ".env"]
    except NameError:
        pass

    for env_path in candidates:
        if not (env_path.exists() and env_path.is_file()):
            continue
        try:
            raw = env_path.read_bytes()
            # remove BOM UTF-8
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            text = raw.decode("utf-8", errors="replace")
            loaded = []
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                # remove inline comments  VAR=valor  # comentário
                if " #" in val:
                    val = val[:val.index(" #")]
                val = val.strip()
                # remove aspas externas (simples ou duplas)
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                if key:
                    os.environ[key] = val   # override sempre
                    loaded.append(key)
            return str(env_path), loaded
        except Exception as e:
            continue
    return "", []

_ENV_FILE, _ENV_KEYS_LOADED = _load_env_manual()

# ── imports do projecto ───────────────────────────────────────────────────────
try:
    from config import (
        SOIL_WATER_PROPERTIES, SOIL_CODE_ALIASES,
        VALIDATION_THRESHOLDS, DB_URL,
    )
    _SOIL_WATER = SOIL_WATER_PROPERTIES
    _SOIL_ALIAS = SOIL_CODE_ALIASES
    _THRESH     = VALIDATION_THRESHOLDS
    _DB_URL     = DB_URL
except ImportError:
    _SOIL_WATER = {}
    _SOIL_ALIAS = {}
    _THRESH     = {}
    _DB_URL     = os.getenv("DATABASE_URL", os.getenv("DB_URL", ""))

try:
    import folium
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

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

# ─────────────────────────────────────────────────────────────────────────────
# Página
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Diagnóstico Agrícola · Poseidon + Sentinel-2",
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
.metric-box{background:#161b22;border:1px solid #30363d;border-radius:8px;
            padding:12px 16px;text-align:center;}
.metric-label{font-size:11px;color:#8b949e;text-transform:uppercase;margin-bottom:4px;}
.metric-value{font-size:22px;font-weight:700;font-family:'Space Mono',monospace;}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────
SOIL_WATER  = _SOIL_WATER or {"default": {"AWC": 100, "Ks": 20, "fc": 30, "wp": 15, "retencao": "media"}}
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

ALL_INDICES  = ["NDVI", "NDRE", "EVI", "NDWI", "NDMI", "BSI", "NBR", "PSRI", "CRI1"]
VEG_POSITIVE = ["NDVI", "NDRE", "EVI", "NDWI", "NDMI", "NBR"]

COLORS = {
    "NDVI": "#3fb950", "NDRE": "#58a6ff", "EVI":  "#a5f3fc", "NDWI": "#2dc8f0",
    "NDMI": "#bc8cff", "BSI":  "#d29922", "NBR":  "#f0a030", "PSRI": "#f78166",
    "CRI1": "#e879f9", "GNDVI": "#3fb950", "MSI": "#f78166",
}
INDEX_META = {
    "NDVI": {"desc": "Índice geral de vegetação",           "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "NDRE": {"desc": "Red Edge — vigor / estresse precoce", "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "EVI":  {"desc": "Enhanced Vegetation Index",           "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "NDWI": {"desc": "Água na vegetação (Gao)",             "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "NDMI": {"desc": "Umidade no dossel (SWIR)",            "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "BSI":  {"desc": "Solo exposto — falha de stand",       "invert": True,  "color_low": (30,180,60),  "color_high": (220,50,30)},
    "NBR":  {"desc": "Queimadas / dano severo",             "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "PSRI": {"desc": "Senescência vegetal",                 "invert": True,  "color_low": (30,180,60),  "color_high": (220,50,30)},
    "CRI1": {"desc": "Carotenoides — envelhecimento",       "invert": True,  "color_low": (30,180,60),  "color_high": (220,50,30)},
    "GNDVI":{"desc": "Green NDVI — biomassa verde",         "invert": False, "color_low": (220,50,30),  "color_high": (30,180,60)},
    "MSI":  {"desc": "Moisture Stress Index",               "invert": True,  "color_low": (30,120,200), "color_high": (220,50,30)},
}

STATUS_LABEL = {"sim": "CONFIRMADO", "nao": "NÃO CONFIRMADO",
                "parcial": "INCONCLUSIVO", "nd": "N/D"}
STATUS_COLOR = {"sim": "#3fb950", "nao": "#f85149", "parcial": "#d29922", "nd": "#8b949e"}

_PLOT_BASE = dict(template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
                  font=dict(family="DM Sans", color="#e6edf3"))
_GRID      = dict(showgrid=True, gridcolor="#21262d")

# ─────────────────────────────────────────────────────────────────────────────
# Utilitários
# ─────────────────────────────────────────────────────────────────────────────
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
        return "R$ {:,.2f}".format(float(v)).replace(",","X").replace(".",",").replace("X",".")
    except Exception:
        return "R$ -"

# ─────────────────────────────────────────────────────────────────────────────
# Poseidon — conexão e busca de dados climáticos
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _get_poseidon_connector(db_url: str):
    """Retorna uma instância conectada do PoseidonConnector (cacheada por session)."""
    try:
        from modules.poseidon import PoseidonConnector
        conn = PoseidonConnector(db_url)
        conn.connect()
        return conn, None
    except Exception as e:
        return None, str(e)


def fetch_poseidon_climate(db_url: str, lat: float, lon: float,
                           start_dt: pd.Timestamp, end_dt: pd.Timestamp):
    """
    Busca dados climáticos via Poseidon IDW para o centróide da geometria.
    Retorna (clim_df, pos_summ, pos_vote, hist_baseline, error_msg).
    clim_df tem colunas: date, prcp, tmax, tmin, tavg, rh_avg, wspd_avg, wspd_max
    """
    connector, err = _get_poseidon_connector(db_url)
    if err or connector is None:
        return pd.DataFrame(), {}, {}, {}, f"Erro Poseidon: {err}"

    start_date = start_dt.date()
    end_date   = end_dt.date()

    try:
        nearest   = connector.find_nearest_point(lat, lon)
        neighbors = connector.find_cardinal_neighbors(lat, lon)

        thresholds = _THRESH.get("seca", {})  # usado internamente pelo vote_3of4

        # votação IDW
        pos_vote = connector.vote_3of4(
            neighbors, start_date, end_date,
            "seca",          # placeholder — o vote é usado só para diagnóstico
            thresholds,
            center_lat=lat,
            center_lon=lon,
        )

        # interpolação IDW → DataFrame diário
        idw_df  = connector.idw_interpolate(lat, lon, neighbors, start_date, end_date)
        pos_summ = connector.summarize_period(idw_df, start_date, end_date)
        hist_baseline = connector.get_historical_baseline(nearest, start_date, end_date)

        # normaliza para o schema esperado pelos charts
        clim = _idw_to_clim_df(idw_df)
        return clim, pos_summ, pos_vote, hist_baseline, None

    except Exception as e:
        return pd.DataFrame(), {}, {}, {}, f"Erro ao buscar dados Poseidon: {e}"


def _idw_to_clim_df(idw_df) -> pd.DataFrame:
    """
    Converte o DataFrame IDW do Poseidon para o schema de clima usado pelos charts.
    Garante as colunas: date, prcp, tmax, tmin, tavg, rh_avg, wspd_avg, wspd_max.
    """
    if idw_df is None or getattr(idw_df, "empty", True):
        return pd.DataFrame()
    df = idw_df.copy()
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    for col in ["prcp", "tmax", "tmin", "tavg", "rh_avg", "wspd_avg", "wspd_max"]:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # se tavg não existir, estima
    if df["tavg"].isna().all() and not df["tmax"].isna().all():
        df["tavg"] = (df["tmax"].fillna(0) + df["tmin"].fillna(0)) / 2
    return df.sort_values("date").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# STAC — Sentinel-2
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def fetch_stac(geojson_feature, start_date_str: str, end_date_str: str) -> pd.DataFrame:
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
                    arr     = np.where(clipped.values == 0, np.nan, clipped.values.astype(float))
                    means[b] = float(np.nanmean(arr))
                r, n, re, sw = means["red"], means["nir"], means["rededge"], means["swir"]
                rows.append({
                    "date":       pd.to_datetime(item.datetime.strftime("%Y-%m-%d")),
                    "NDVI_mean":  (n-r)/(n+r)                       if (n+r)  else np.nan,
                    "NDRE_mean":  (n-re)/(n+re)                     if (n+re) else np.nan,
                    "GNDVI_mean": (n-0.5*(r+re))/(n+0.5*(r+re))    if n      else np.nan,
                    "MSI_mean":   sw/n                               if n      else np.nan,
                })
            except Exception:
                continue
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.groupby("date").mean(numeric_only=True).reset_index().sort_values("date")
        return df
    except Exception:
        return pd.DataFrame()

# ─────────────────────────────────────────────────────────────────────────────
# Domínio
# ─────────────────────────────────────────────────────────────────────────────

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
    Ra  = ((24*60/math.pi)*0.082*dr*(ws*math.sin(lat)*math.sin(dec)+math.cos(lat)*math.cos(dec)*math.sin(ws)))
    return max(0.0023*((tmax+tmin)/2+17.8)*(max(tmax-tmin, 0.0)**0.5)*(Ra*0.408), 0.0)


def water_balance(clim: pd.DataFrame, lat_deg: float, soil: dict) -> pd.DataFrame:
    df = clim.copy().sort_values("date").reset_index(drop=True)
    df["doy"] = df["date"].dt.dayofyear
    df["eto"] = df.apply(lambda r: hargreaves_et0(
        float(r.get("tmin") or 0), float(r.get("tmax") or 30),
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


def compute_anomaly_poseidon(clim_event: pd.DataFrame, hist_baseline: dict) -> dict:
    """
    Calcula anomalia usando o hist_baseline retornado pelo Poseidon.
    hist_baseline esperado: {prcp_mean_mm, prcp_std_mm, tavg_mean_c, ...}
    Retorna dict com z-scores por variável.
    """
    if clim_event.empty or not hist_baseline:
        return {}
    results = {}
    mappings = [
        ("prcp",   "prcp_mean_mm",  "prcp_std_mm",  "Precipitação"),
        ("tmax",   "tmax_mean_c",   "tmax_std_c",   "Temperatura máx."),
        ("rh_avg", "rh_mean_pct",   "rh_std_pct",   "Umidade relativa"),
    ]
    # fallback: tenta nomes alternativos
    alt_keys = {
        "prcp_mean_mm":  ["prcp_mean_mm", "prcp_mean", "precip_mean_mm"],
        "prcp_std_mm":   ["prcp_std_mm",  "prcp_std",  "precip_std_mm"],
        "tmax_mean_c":   ["tmax_mean_c",  "tavg_mean_c", "tmax_mean"],
        "tmax_std_c":    ["tmax_std_c",   "tavg_std_c",  "tmax_std"],
        "rh_mean_pct":   ["rh_mean_pct",  "rh_avg_mean_pct", "rh_mean"],
        "rh_std_pct":    ["rh_std_pct",   "rh_avg_std_pct",  "rh_std"],
    }
    def _get(d, key):
        for k in alt_keys.get(key, [key]):
            if k in d and d[k] is not None:
                return float(d[k])
        return None

    color_cat = {
        "muito abaixo do normal": "#f85149", "abaixo do normal": "#f78166",
        "dentro do normal": "#8b949e", "acima do normal": "#58a6ff",
        "muito acima do normal": "#3fb950",
    }

    for col, mu_key, sig_key, label in mappings:
        if col not in clim_event.columns:
            continue
        mu  = _get(hist_baseline, mu_key)
        sig = _get(hist_baseline, sig_key)
        if mu is None:
            continue
        event_val = float(clim_event[col].mean()) if col != "prcp" else float(clim_event[col].sum())
        if sig and sig > 0:
            z   = (event_val - mu) / sig
            cat = ("muito acima do normal" if z>2 else "acima do normal" if z>1
                   else "dentro do normal" if z>-1 else "abaixo do normal" if z>-2
                   else "muito abaixo do normal")
        else:
            pct_diff = ((event_val - mu) / (abs(mu) + 1e-9)) * 100
            z        = pct_diff / 30.0  # normaliza grosseiro
            cat      = ("acima do normal" if pct_diff>20 else "dentro do normal"
                        if abs(pct_diff)<=20 else "abaixo do normal")
        results[col] = {"label": label, "z": round(z,2), "categoria": cat,
                        "event_val": round(event_val,2), "hist_val": round(mu,2),
                        "color": color_cat.get(cat, "#8b949e")}
    return results


def compute_verdict(ts, clim, start, end, complaint, bioma, pos_vote=None):
    """Veredicto combinado: satélite + clima Poseidon + votação IDW."""
    thr       = get_biome_thresholds(bioma)
    score_map = {"sim": 1.0, "parcial": 0.5, "nao": 0.0, "nd": None}

    # — satélite —
    v_sat = "nd"
    if ts is not None and not ts.empty and len(ts) >= 2:
        ts_s  = ts.sort_values("date")
        first, last = ts_s.iloc[0], ts_s.iloc[-1]
        avail = [i for i in VEG_POSITIVE if f"{i}_mean" in ts.columns]
        if avail:
            deltas = [last.get(f"{i}_mean", np.nan) - first.get(f"{i}_mean", np.nan) for i in avail]
            mean_d = float(np.nanmean(deltas))
            good   = mean_d > 0.02 if complaint == "chuva" else mean_d < -0.02
            v_sat  = "sim" if good else "parcial" if abs(mean_d) > 0.01 else "nao"

    # — precipitação —
    v_prcp = "nd"
    if clim is not None and not clim.empty:
        sub   = clim[(clim["date"] >= start) & (clim["date"] <= end)]
        total = sub["prcp"].fillna(0).sum()
        if complaint == "chuva":
            v_prcp = "sim" if total >= thr["prcp_alta"] else "parcial" if total >= 5 else "nao"
        else:
            v_prcp = "sim" if total <= thr["prcp_baixa"] else "parcial" if total <= 15 else "nao"

    # — clima complementar —
    v_clim = "nd"
    if clim is not None and not clim.empty:
        sub    = clim[(clim["date"] >= start) & (clim["date"] <= end)]
        avg_rh = sub["rh_avg"].mean()
        avg_t  = sub["tmax"].mean()
        if complaint == "chuva":
            v_clim = ("sim" if avg_rh >= thr["rh_alta"] else "parcial" if avg_rh >= 60 else "nao")
        else:
            score  = ((1 if avg_rh <= thr["rh_baixa"] else 0) + (1 if avg_t >= 28 else 0)) / 2
            v_clim = "sim" if score >= 1.0 else "parcial" if score >= 0.5 else "nao"

    # — votação Poseidon  —
    v_poseidon = "nd"
    if pos_vote and isinstance(pos_vote, dict):
        passed = pos_vote.get("passed")
        ws     = pos_vote.get("weighted_score", 0)
        if passed is True:
            v_poseidon = "sim" if ws >= 60 else "parcial"
        elif passed is False:
            v_poseidon = "nao"

    # — score ponderado —
    sat_w = 0.0 if (ts is None or ts.empty) else (0.5 if len(ts) < 3 else 1.0)
    pos_w = 1.5  # Poseidon tem peso maior (dados reais)
    ws_total = tw = 0.0
    for status, w in [(v_sat, sat_w), (v_prcp, 1.0), (v_clim, 1.0), (v_poseidon, pos_w)]:
        sc = score_map.get(status)
        if sc is not None and w > 0:
            ws_total += sc * w; tw += w
    if tw == 0:
        return "nd", v_sat, v_prcp, v_clim, v_poseidon
    final = ("sim" if ws_total/tw >= 0.70 else "parcial" if ws_total/tw >= 0.35 else "nao")
    return final, v_sat, v_prcp, v_clim, v_poseidon

# ─────────────────────────────────────────────────────────────────────────────
# Geometria
# ─────────────────────────────────────────────────────────────────────────────

def _flatten(c, out):
    if not c: return
    if isinstance(c[0], (int, float)): out.append(c)
    else: [_flatten(x, out) for x in c]

def _ring_area(ring):
    R, n, area = 6371.0, len(ring), 0.0
    for i in range(n):
        j = (i+1) % n
        lo1, la1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lo2, la2 = math.radians(ring[j][0]), math.radians(ring[j][1])
        area += (lo2-lo1) * (2 + math.sin(la1) + math.sin(la2))
    return abs(area) * R * R / 2

def parse_geometry(geom):
    flat = []; _flatten(geom.get("coordinates", []), flat)
    gt, gc = geom.get("type",""), geom.get("coordinates",[])
    rings, area = [], None
    if   gt == "Polygon"      and gc: area = _ring_area(gc[0]);                      rings = [gc[0]]
    elif gt == "MultiPolygon" and gc: area = sum(_ring_area(p[0]) for p in gc); rings = [p[0] for p in gc]
    if not flat: return [], [], None, 0.0, 0.0
    lon = sum(c[0] for c in flat) / len(flat)
    lat = sum(c[1] for c in flat) / len(flat)
    return flat, rings, area, lat, lon

# ─────────────────────────────────────────────────────────────────────────────
# Gráficos
# ─────────────────────────────────────────────────────────────────────────────

def chart_satellite(ts: pd.DataFrame, start, end):
    mean_cols = [c for c in ts.columns if c.endswith("_mean")]
    std_cols  = [c for c in ts.columns if c.endswith("_std")]
    use_std   = bool(std_cols)
    fig = make_subplots(
        rows=2 if use_std else 1, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35] if use_std else [1.0],
        vertical_spacing=0.06)
    for col in mean_cols:
        name = col.replace("_mean","")
        fig.add_trace(go.Scatter(x=ts["date"], y=ts[col], name=name,
            line=dict(color=COLORS.get(name,"#aaa"), width=2.5),
            mode="lines+markers", marker=dict(size=7)), row=1, col=1)
    fig.add_vrect(x0=start, x1=end, fillcolor="rgba(255,255,255,0.04)",
        line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"), row=1, col=1)
    if use_std:
        for col in std_cols:
            name = col.replace("_std","")
            fig.add_trace(go.Bar(x=ts["date"], y=ts[col], name=f"{name} σ",
                marker_color=COLORS.get(name,"#aaa"), opacity=0.7, showlegend=False), row=2, col=1)
        fig.add_vrect(x0=start, x1=end, fillcolor="rgba(255,255,255,0.04)",
            line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"), row=2, col=1)
    fig.update_layout(**_PLOT_BASE,
        legend=dict(orientation="h", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=10, b=10), height=480, yaxis_title="Valor do índice")
    if use_std:
        fig.update_layout(yaxis2_title="Desvio padrão")
    fig.update_xaxes(**_GRID); fig.update_yaxes(**_GRID)
    return fig


def chart_clima(clim: pd.DataFrame, start, end, complaint):
    w_start = start - pd.Timedelta(days=5); w_end = end + pd.Timedelta(days=5)
    sub = clim[(clim["date"] >= w_start) & (clim["date"] <= w_end)].sort_values("date").copy()
    if sub.empty: return go.Figure()
    ac = accent(complaint); is_rain = (complaint == "chuva")
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.45, 0.30, 0.25],
        vertical_spacing=0.05,
        subplot_titles=("Precipitação (mm)", "Temperatura (°C)", "Umidade Relativa (%)"))
    bar_colors = [("#4a5568" if d < start else ac if d <= end else
                   ("#2d4a2e" if is_rain else "#4a2d1e")) for d in sub["date"]]
    fig.add_trace(go.Bar(x=sub["date"], y=sub["prcp"].fillna(0),
        name="Chuva diária", marker_color=bar_colors, opacity=0.85), row=1, col=1)
    sub["prcp_cum"] = sub["prcp"].fillna(0).cumsum()
    fig.add_trace(go.Scatter(x=sub["date"], y=sub["prcp_cum"], name="Acumulado",
        line=dict(color=ac, width=2.5, dash="dot")), row=1, col=1)
    if "tmax" in sub.columns:
        fig.add_trace(go.Scatter(x=sub["date"], y=sub["tmax"], name="Tmax",
            line=dict(color="#f78166", width=2), fill="tonexty",
            fillcolor="rgba(247,129,102,0.08)"), row=2, col=1)
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
    fig.add_annotation(x=start + (end-start)/2, y=1, yref="paper",
        text=f"EVENTO ({(end-start).days+1}d)", showarrow=False,
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
    fig.add_trace(go.Bar(x=sub["date"], y=sub["prcp"].fillna(0), name="Diário (mm)",
        marker_color=ac, opacity=0.4, yaxis="y2"))
    fig.update_layout(**_PLOT_BASE,
        yaxis=dict(title="Acumulado (mm)"),
        yaxis2=dict(title="Diário (mm)", overlaying="y", side="right",
                    showgrid=False, range=[0, max_p*4]),
        legend=dict(orientation="h", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10), height=280,
        title=dict(text="Precipitação acumulada no período do evento", font=dict(size=14)))
    return fig


def chart_water_balance(wb: pd.DataFrame, start, end, complaint):
    sub = wb[(wb["date"] >= start - pd.Timedelta(days=5)) &
             (wb["date"] <= end   + pd.Timedelta(days=5))]
    if sub.empty: return None
    ac  = accent(complaint)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        subplot_titles=("Armazenamento de Água no Solo (%)", "Déficit / Excedente (mm)"))
    fig.add_trace(go.Scatter(x=sub["date"], y=sub["storage_pct"],
        name="Armazenamento %", line=dict(color="#58a6ff", width=2.5),
        fill="tozeroy", fillcolor="rgba(88,166,255,0.08)"), row=1, col=1)
    fig.add_hline(y=50, line=dict(color="#8b949e", dash="dash", width=1), row=1, col=1)
    fig.add_trace(go.Bar(x=sub["date"], y=sub["deficit"], name="Déficit (mm)",
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

# ─────────────────────────────────────────────────────────────────────────────
# Mapa Folium
# ─────────────────────────────────────────────────────────────────────────────

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
            val      = float(row_data[col_name].iloc[0])
            all_vals = ts_df[col_name].dropna().tolist()
            fill_hex = idx_color(val, all_vals, meta)
            fill_op  = 0.60
            val_label = f"{sel_index} = {val:.4f}"
    for ring in rings_plot:
        folium.Polygon(locations=[(p[1], p[0]) for p in ring],
            color=fill_hex, weight=2, fill=True,
            fill_color=fill_hex, fill_opacity=fill_op,
            tooltip=val_label or "Polígono do evento").add_to(m)
    folium.CircleMarker(location=[lat, lon], radius=7, color=fill_hex,
        fill=True, fill_color=fill_hex, tooltip="Centróide").add_to(m)
    if val_label and meta:
        lo_hex = rgb_to_hex(meta.get("color_low", (220,50,30)))
        hi_hex = rgb_to_hex(meta.get("color_high", (30,180,60)))
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

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.sidebar.markdown("## 🛰️ Diagnóstico Agrícola")
    st.sidebar.markdown("---")

    # ── Conexão Poseidon — carregada do .env / config.py ────────────────────────
    # Força re-leitura do .env a cada renderização do Streamlit para garantir
    # que as variáveis estejam disponíveis mesmo com cache do processo.
    _load_env_manual()  # garante re-leitura a cada render

    def _build_db_url() -> str:
        import urllib.parse
        # 1) connection string completa no config.py
        if _DB_URL and _DB_URL.strip():
            return _DB_URL.strip()
        # 2) connection string completa em variável de ambiente
        for key in ("DB_URL", "DATABASE_URL", "POSEIDON_DB_URL"):
            val = os.getenv(key, "").strip()
            if val:
                return val
        # 3) variáveis individuais POSEIDON_DB_*
        host     = os.environ.get("POSEIDON_DB_HOST", "").strip()
        port     = os.environ.get("POSEIDON_DB_PORT", "5432").strip()
        name     = os.environ.get("POSEIDON_DB_NAME", "").strip()
        user     = os.environ.get("POSEIDON_DB_USER", "").strip()
        password = os.environ.get("POSEIDON_DB_PASSWORD", "").strip()
        if host and name and user and password:
            pwd_enc = urllib.parse.quote_plus(password)
            return f"postgresql://{user}:{pwd_enc}@{host}:{port}/{name}"
        return ""

    db_url = _build_db_url()

    # indica na sidebar o estado da conexão (sem expor credenciais)
    _pos_host = os.getenv("POSEIDON_DB_HOST", "")
    _pos_name = os.getenv("POSEIDON_DB_NAME", "")
    _display  = f"{_pos_host}/{_pos_name}" if _pos_host else (
        db_url.split("@")[-1].split("?")[0] if "@" in db_url else "configurado"
    )
    if db_url:
        st.sidebar.markdown(
            f"<div style='background:#0d2318;border:1px solid #3fb950;border-radius:6px;"
            f"padding:6px 10px;font-size:11px;font-family:Space Mono,monospace;color:#3fb950;"
            f"margin-bottom:12px'>✅ Poseidon · {_display}</div>",
            unsafe_allow_html=True,
        )
    else:
        # lista quais variáveis individuais estão faltando para ajudar o diagnóstico
        _missing = [v for v in ("POSEIDON_DB_HOST","POSEIDON_DB_PORT","POSEIDON_DB_NAME",
                                "POSEIDON_DB_USER","POSEIDON_DB_PASSWORD")
                    if not os.getenv(v, "").strip()]
        _miss_str = ", ".join(_missing) if _missing else "nenhuma variável definida"
        st.sidebar.markdown(
            f"<div style='background:#2d0f0e;border:1px solid #f85149;border-radius:6px;"
            f"padding:6px 10px;font-size:11px;font-family:Space Mono,monospace;color:#f85149;"
            f"margin-bottom:12px'>❌ Poseidon não configurado<br>"
            f"<span style='font-size:10px'>Faltando: {_miss_str}</span></div>",
            unsafe_allow_html=True,
        )

    # ── Debug sidebar — mostra o que foi lido do .env ────────────────────────
    with st.sidebar.expander("🔧 Debug .env", expanded=not bool(db_url)):
        st.caption(f"`.env` carregado de: `{_ENV_FILE or 'NÃO ENCONTRADO'}`")
        st.caption(f"Variáveis lidas: `{', '.join(_ENV_KEYS_LOADED) or 'nenhuma'}`")
        _env_vars = {
            "POSEIDON_DB_HOST":     os.environ.get("POSEIDON_DB_HOST",     ""),
            "POSEIDON_DB_PORT":     os.environ.get("POSEIDON_DB_PORT",     ""),
            "POSEIDON_DB_NAME":     os.environ.get("POSEIDON_DB_NAME",     ""),
            "POSEIDON_DB_USER":     os.environ.get("POSEIDON_DB_USER",     ""),
            "POSEIDON_DB_PASSWORD": "***" if os.environ.get("POSEIDON_DB_PASSWORD","") else "",
            "DB_URL":               "***" if os.environ.get("DB_URL","") else "",
        }
        for k, v in _env_vars.items():
            color = "#3fb950" if v else "#f85149"
            icon  = "✅" if v else "❌"
            st.markdown(
                f"<div style='font-size:11px;font-family:Space Mono,monospace;"
                f"color:{color};padding:1px 0'>{icon} {k}: {v or 'vazio'}</div>",
                unsafe_allow_html=True)

    # ── Upload do GeoJSON ─────────────────────────────────────────────────────
    st.sidebar.markdown("<div class='side-title'>📂 Caso</div>", unsafe_allow_html=True)
    geojson_file = st.sidebar.file_uploader(
        "Arquivo .geojson (FeatureCollection)",
        type=["geojson", "json"],
        help=(
            "FeatureCollection com properties: id, evento, inicio, fim, solo, cultura, bioma.\n"
            "Geometria: Polygon ou MultiPolygon em coordenadas WGS-84."
        ),
    )

    if not geojson_file:
        if not db_url:
            _missing_vars = [v for v in ("POSEIDON_DB_HOST","POSEIDON_DB_PORT","POSEIDON_DB_NAME",
                                         "POSEIDON_DB_USER","POSEIDON_DB_PASSWORD")
                             if not os.getenv(v,"").strip()]
            _miss_list = "".join(
                f"<code style=\'color:#f85149;display:block;margin:1px 0\'>{v}=...</code>"
                for v in _missing_vars
            ) if _missing_vars else "<span style=\'color:#f78166\'>Nenhuma variavel definida</span>"
            _db_warn_html = (
                "<div style=\'background:#2d0f0e;border:1px solid #f85149;border-radius:8px;"
                "padding:12px 20px;max-width:480px;font-size:13px;color:#f78166;text-align:left\'>"
                "<b style=\'color:#f85149\'>Poseidon nao configurado</b><br>"
                "Preencha as variaveis abaixo no arquivo <code>.env</code>:<br>"
                + _miss_list +
                "</div>"
            )
        else:
            _db_warn_html = ""
        _welcome = (
            "<div style=\'display:flex;flex-direction:column;align-items:center;"
            "justify-content:center;margin-top:80px;gap:18px;text-align:center\'>"
            "<div style=\'font-size:58px\'>🛰️</div>"
            "<div style=\'font-size:24px;font-weight:700;font-family:Space Mono,monospace;color:#e6edf3\'>"
            "Diagnostico Agricola</div>"
            "<div style=\'font-size:15px;color:#8b949e;max-width:480px;line-height:1.8\'>"
            "Envie um arquivo <b style=\'color:#58a6ff\'>.geojson</b> (FeatureCollection) na barra lateral.<br>"
            "Fonte climatica: <b style=\'color:#bc8cff\'>Poseidon </b> · "
            "Satelite: <b style=\'color:#3fb950\'>Sentinel-2 STAC</b>"
            "</div>"
            + _db_warn_html
            + "<div style=\'font-size:13px;color:#8b949e;background:#161b22;border:1px solid #30363d;"
            "border-radius:8px;padding:12px 20px;max-width:420px;text-align:left\'>"
            "<b style=\'color:#bc8cff\'>Properties obrigatorias no GeoJSON:</b><br>"
            "<code style=\'color:#58a6ff\'>id</code> · "
            "<code style=\'color:#58a6ff\'>evento</code> (seca/chuva/geada/granizo) · "
            "<code style=\'color:#58a6ff\'>inicio</code> · "
            "<code style=\'color:#58a6ff\'>fim</code> (YYYY-MM-DD)<br>"
            "<code style=\'color:#58a6ff\'>solo</code> · "
            "<code style=\'color:#58a6ff\'>cultura</code> · "
            "<code style=\'color:#58a6ff\'>bioma</code>"
            "</div></div>"
        )
        st.markdown(_welcome, unsafe_allow_html=True)
        return

    # ── Parse GeoJSON ─────────────────────────────────────────────────────────
    try:
        gj = json.loads(geojson_file.read())
    except Exception as e:
        st.error(f"Erro ao ler GeoJSON: {e}"); return

    if gj.get("type") != "FeatureCollection":
        st.error(
            "❌ Formato inválido: o arquivo deve ser um **FeatureCollection**.\n\n"
            "Certifique-se de que o GeoJSON possui `\"type\": \"FeatureCollection\"` "
            "com um array `\"features\"` contendo as features com properties e geometry."
        )
        return

    all_feat = gj.get("features", [])
    if not all_feat:
        st.error("GeoJSON sem features."); return

    # seleção de caso (quando há múltiplas features)
    if len(all_feat) > 1:
        labels = [
            f"#{f.get('properties',{}).get('id',i+1)} — "
            f"{str(f.get('properties',{}).get('evento','?')).upper()} — "
            f"{f.get('properties',{}).get('cultura','?')}"
            for i, f in enumerate(all_feat)
        ]
        feat_idx = st.sidebar.selectbox("Selecionar caso", range(len(all_feat)),
                                        format_func=lambda i: labels[i])
    else:
        feat_idx = 0

    feat     = all_feat[feat_idx]
    props    = feat.get("properties", {}) or {}
    geom     = feat.get("geometry", {})   or {}

    # valida campos obrigatórios
    required_props = ["id", "evento", "inicio", "fim"]
    missing = [p for p in required_props if p not in props or not props[p]]
    if missing:
        st.error(f"Properties ausentes ou vazias no GeoJSON: **{', '.join(missing)}**"); return

    case_id   = str(props.get("id", "—"))
    complaint = str(props.get("evento", "seca")).lower().strip()
    start_dt  = pd.to_datetime(props.get("inicio"), errors="coerce")
    end_dt    = pd.to_datetime(props.get("fim"),    errors="coerce")
    crop_type = str(props.get("cultura", "")).upper().strip()
    bioma_str = str(props.get("bioma", ""))
    solo_str  = str(props.get("solo",  "default"))

    if pd.isna(start_dt) or pd.isna(end_dt):
        st.error(
            f"Properties `inicio` e `fim` devem estar no formato **YYYY-MM-DD**.\n"
            f"Recebido: '{props.get('inicio')}' / '{props.get('fim')}'"
        ); return

    if start_dt >= end_dt:
        st.error("`inicio` deve ser anterior a `fim`."); return

    # geometria
    coords_flat, rings_plot, area_km2, lat, lon = parse_geometry(geom)
    if not coords_flat:
        st.error("Geometria sem coordenadas válidas."); return

    area_ha = area_km2 * 100 if area_km2 else 0.0

    # solo
    soil_name = "default"
    for alias, canonical in SOIL_ALIASES.items():
        if solo_str.lower().startswith(alias) or alias in solo_str.lower():
            soil_name = canonical; break
    if soil_name == "default":
        for canonical in SOIL_WATER:
            if canonical != "default" and canonical.lower()[:8] in solo_str.lower():
                soil_name = canonical; break
    soil_props = get_soil_props(soil_name)
    thr        = get_biome_thresholds(bioma_str)

    st.sidebar.success(f"📍 lat {lat:.4f}° · lon {lon:.4f}°")
    st.sidebar.caption(
        f"Caso #{case_id} · {complaint.upper()} · {crop_type or '—'}\n"
        f"{start_dt.strftime('%d/%m/%Y')} → {end_dt.strftime('%d/%m/%Y')}"
    )

    # ── Busca de dados ────────────────────────────────────────────────────────
    if not db_url:
        st.error("Poseidon nao configurado. Adicione DB_URL ao arquivo .env na raiz do projeto e reinicie o Streamlit.")
        return

    with st.spinner("🌦️ Buscando dados climáticos via Poseidon ..."):
        clim, pos_summ, pos_vote, hist_baseline, clim_err = fetch_poseidon_climate(
            db_url, float(lat), float(lon), start_dt, end_dt
        )

    if clim_err or clim.empty:
        st.error(f"Não foi possível recuperar dados climáticos.\n\n{clim_err or 'DataFrame vazio.'}")
        return

    ts = pd.DataFrame()
    if HAS_STAC and HAS_GEO:
        with st.spinner("🛰️ Buscando imagens Sentinel-2 via STAC..."):
            ts = fetch_stac(feat, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))

    # eventos e cálculos
    clim_event = clim[(clim["date"] >= start_dt) & (clim["date"] <= end_dt)].copy()
    anomaly    = compute_anomaly_poseidon(clim_event, hist_baseline)
    v_total, v_sat, v_prcp, v_clim, v_poseidon = compute_verdict(
        ts if not ts.empty else None,
        clim, start_dt, end_dt, complaint, bioma_str, pos_vote
    )
    n_sat = ts["date"].nunique() if not ts.empty else 0

    # ── Cabeçalho ─────────────────────────────────────────────────────────────
    evt_label = {
        "seca": "Seca / Déficit Hídrico", "chuva": "Excesso de Chuva",
        "geada": "Geada", "granizo": "Granizo",
    }.get(complaint, complaint.upper())
    badge_cls = "badge-chuva" if complaint == "chuva" else "badge-seca"
    src_tag   = ("<span style='background:#1a1f2e;color:#bc8cff;border:1px solid #bc8cff;"
                 "border-radius:12px;font-size:11px;padding:2px 8px;"
                 "font-family:Space Mono,monospace'>Poseidon </span>")

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;flex-wrap:wrap">
      <h1 style="margin:0;font-size:26px">Caso #{case_id}</h1>
      <span class="badge {badge_cls}">{complaint.upper()}</span>
      {src_tag}
    </div>
    <div style="color:#8b949e;font-size:14px;margin-bottom:18px">{evt_label}</div>
    """, unsafe_allow_html=True)

    bio_lbl = thr.get("bioma","—").replace("Mata Atlantica","Mata Atlântica")
    st.markdown(
        "<div class='info-grid'>"
        + info_cell("Início",  start_dt.strftime("%d/%m/%Y"))
        + info_cell("Fim",     end_dt.strftime("%d/%m/%Y"))
        + info_cell("Duração", f"{(end_dt - start_dt).days + 1} dias")
        + info_cell("Bioma",   bio_lbl if bio_lbl != "default" else "—", "font-size:13px")
        + info_cell("Área",    f"{area_ha:.1f} ha" if area_ha else "—")
        + info_cell("Imagens", str(n_sat))
        + (info_cell("Cultura", crop_type) if crop_type else "")
        + (info_cell("Solo",    soil_name[:22], "font-size:12px") if soil_name != "default" else "")
        + "</div>", unsafe_allow_html=True
    )

    # ── Abas ──────────────────────────────────────────────────────────────────
    tab_diag, tab_sat, tab_clima, tab_bal, tab_map = st.tabs([
        "🎯 Diagnóstico", "🛰️ Satélite", "🌧️ Clima", "💧 Balanço Hídrico", "🗺️ Localização"
    ])

    # ═══════════════════ ABA DIAGNÓSTICO ══════════════════════════════════════
    with tab_diag:
        color = STATUS_COLOR.get(v_total, "#8b949e")
        cls   = f"verdict-{v_total if v_total != 'nd' else 'parcial'}"
        icon  = {"sim": "✅", "nao": "❌", "parcial": "⚠️"}.get(v_total, "—")

        st.markdown(f"""
        <div class='verdict-card {cls}'>
          <div style='font-size:13px;color:#8b949e;font-family:Space Mono,monospace;
               text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px'>
            Diagnóstico Geral · Poseidon + Sentinel-2</div>
          <div style='font-size:32px;font-weight:700;font-family:Space Mono,monospace;color:{color}'>
            {icon} {STATUS_LABEL.get(v_total, "—")}</div>
          <div style='font-size:13px;color:#8b949e;margin-top:6px'>
            O problema reportado é visível nos dados disponíveis</div>
        </div>""", unsafe_allow_html=True)

        # sub-veredictos
        st.markdown("#### Componentes do Diagnóstico")
        c1, c2, c3, c4 = st.columns(4)
        for col_ui, label, status, icon_key in [
            (c1, "Poseidon IDW",    v_poseidon, "🌡️"),
            (c2, "Precipitação",   v_prcp,     "🌧️"),
            (c3, "Clima compl.",   v_clim,     "💧"),
            (c4, "Satélite",       v_sat,      "🛰️"),
        ]:
            clr = STATUS_COLOR.get(status, "#8b949e")
            lbl = STATUS_LABEL.get(status, "N/D")
            col_ui.markdown(f"""
            <div style='background:#161b22;border:1px solid {clr}33;border-radius:8px;
                 padding:12px 14px;text-align:center;border-top:3px solid {clr}'>
              <div style='font-size:20px;margin-bottom:4px'>{icon_key}</div>
              <div style='font-size:11px;color:#8b949e;text-transform:uppercase;margin-bottom:4px'>
                {label}</div>
              <div style='font-size:14px;font-weight:700;font-family:Space Mono,monospace;color:{clr}'>
                {lbl}</div>
            </div>""", unsafe_allow_html=True)

        # Poseidon Summary
        if pos_summ:
            st.markdown("---"); st.markdown("#### Resumo Meteorológico · Poseidon ")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Precipitação total",  f"{pos_summ.get('prcp_total_mm',0):.1f} mm")
            m2.metric("Temperatura média",   f"{pos_summ.get('tavg_mean_c',0):.1f} °C")
            m3.metric("Tmax absoluta",       f"{pos_summ.get('tmax_abs_c',0):.1f} °C")
            m4.metric("Umidade rel. média",  f"{pos_summ.get('rh_avg_mean_pct',0):.0f}%")
            m5.metric("Vento máx.",          f"{pos_summ.get('wspd_max_kmh',0):.0f} km/h")

        # votação IDW
        if pos_vote:
            ws = pos_vote.get("weighted_score", 0)
            sl = pos_vote.get("signal_level", "")
            ok = pos_vote.get("passed", False)
            vc = "#3fb950" if ok else "#f85149"
            st.markdown(f"""
            <div style='background:#161b22;border:1px solid {vc};border-radius:8px;
                 padding:10px 14px;margin-top:8px'>
              <b style='color:{vc}'>Score IDW: {ws:.0f}/100 — sinal {sl}</b>
              {"  ✅ APROVADO" if ok else "  ❌ REPROVADO"}
            </div>""", unsafe_allow_html=True)
            votes = pos_vote.get("votes", {})
            if votes:
                st.markdown("<div style='display:grid;grid-template-columns:repeat(4,1fr);"
                            "gap:8px;margin-top:12px'>", unsafe_allow_html=True)
                for d, v in votes.items():
                    ok2 = v.get("confirmed", False)
                    vc2 = "#3fb950" if ok2 else "#f85149"
                    st.markdown(f"""
                    <div style='background:#0d1117;border:1px solid {vc2}44;border-radius:6px;
                         padding:8px 10px;font-size:11px;font-family:Space Mono,monospace'>
                      <b style='color:{vc2}'>{"✅" if ok2 else "❌"} {d}</b><br>
                      <span style='color:#8b949e'>{v.get("intensity",0)}/100</span>
                    </div>""", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        # anomalia histórica
        if anomaly:
            st.markdown("---"); st.markdown("#### Anomalia vs Histórico · Poseidon")
            acols = st.columns(len(anomaly))
            for col_ui, (var, info) in zip(acols, anomaly.items()):
                clr = info["color"]
                col_ui.markdown(f"""
                <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;
                     padding:12px 14px;text-align:center">
                  <div style="font-size:11px;color:#8b949e;text-transform:uppercase">{info['label']}</div>
                  <div style="font-size:24px;font-weight:700;font-family:'Space Mono',monospace;
                       color:{clr};margin:6px 0">
                    {info['z']:+.2f}<span style="font-size:11px">σ</span></div>
                  <div style="font-size:11px;color:{clr};margin-bottom:4px">{info['categoria']}</div>
                  <div style="font-size:10px;color:#8b949e">
                    Evento: {info['event_val']} · Histórico: {info['hist_val']}</div>
                </div>""", unsafe_allow_html=True)

        with st.expander("🔍 Debug — valores vs thresholds"):
            rp = float(clim_event["prcp"].sum())    if not clim_event.empty else None
            rr = float(clim_event["rh_avg"].mean()) if not clim_event.empty else None
            rt = float(clim_event["tmax"].mean())   if not clim_event.empty else None
            def _cmp(label, real, thr_v, hig):
                if real is None: return f"| {label} | — | {thr_v} | N/D |"
                ok = real >= thr_v if hig else real <= thr_v
                return f"| {label} | **{real:.1f}** | {thr_v} | {'✅' if ok else '❌'} |"
            if complaint == "chuva":
                rows_d = [_cmp("Precipitação (mm)", rp, thr["prcp_alta"], True),
                          _cmp("Umidade relativa (%)", rr, thr["rh_alta"], True)]
            else:
                rows_d = [_cmp("Precipitação (mm)", rp, thr["prcp_baixa"], False),
                          _cmp("Umidade relativa (%)", rr, thr["rh_baixa"], False),
                          _cmp("Tmax média (°C)", rt, 28, True)]
            st.markdown("| Variável | Valor | Limiar | Passa? |\n|---|---|---|---|")
            for r in rows_d: st.markdown(r)
            st.json({
                "bioma": thr.get("bioma","default"),
                "lat": round(lat,4), "lon": round(lon,4),
                "veredictos": {
                    "poseidon_idw": v_poseidon, "precipitação": v_prcp,
                    "clima_complementar": v_clim, "satélite": v_sat, "final": v_total,
                },
                "n_imagens_sat": n_sat,
                "pos_vote_score": pos_vote.get("weighted_score") if pos_vote else None,
            })

    # ═══════════════════ ABA SATÉLITE ═════════════════════════════════════════
    with tab_sat:
        if ts.empty:
            st.warning("Nenhuma imagem Sentinel-2 sem nuvens encontrada para o período.")
            if not HAS_STAC:
                st.info("Para habilitar, instale: `pip install pystac-client rioxarray`")
        else:
            st.markdown("#### Série Temporal dos Índices Espectrais")
            st.caption(f"*{n_sat} data(s) · Sentinel-2 via STAC Element84/AWS*")
            st.plotly_chart(chart_satellite(ts, start_dt, end_dt), use_container_width=True)
            with st.expander("📊 Dados brutos"):
                st.dataframe(ts, use_container_width=True, height=300)

    # ═══════════════════ ABA CLIMA ════════════════════════════════════════════
    with tab_clima:
        st.markdown("#### 🌧️ Clima do Evento · Poseidon ")
        st.caption(f"Fonte: **Poseidon IDW** — lat {lat:.4f}°, lon {lon:.4f}° · "
                   f"Solo: **{soil_name}** · Bioma: **{bio_lbl}**")
        w_s = start_dt - pd.Timedelta(days=5); w_e = end_dt + pd.Timedelta(days=5)
        ac   = accent(complaint)
        glow = "rgba(88,166,255,0.12)" if complaint == "chuva" else "rgba(247,129,102,0.12)"

        def _period_card(title, df, hi=False):
            if df.empty:
                return (f"<div style='background:#161b22;border:1px solid #30363d;"
                        f"border-radius:8px;padding:14px 16px'>"
                        f"<div style='font-size:11px;color:#8b949e'>{title}</div>"
                        f"<div style='color:#8b949e;font-size:14px'>Sem dados</div></div>")
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
                    f"Tmax {df['tmax'].mean():.1f}°C · UR {df['rh_avg'].mean():.0f}%</div></div>")

        st.markdown(
            "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px'>"
            + _period_card("← 5 dias antes",  clim[(clim["date"]>=w_s)&(clim["date"]<start_dt)])
            + _period_card(f"Evento ({(end_dt-start_dt).days+1} dias)", clim_event, hi=True)
            + _period_card("5 dias depois →",  clim[(clim["date"]>end_dt)&(clim["date"]<=w_e)])
            + "</div>", unsafe_allow_html=True
        )

        st.plotly_chart(chart_clima(clim, start_dt, end_dt, complaint), use_container_width=True)
        st.markdown("---")
        fig_cum = chart_precip_cum(clim, start_dt, end_dt, complaint)
        if fig_cum:
            st.plotly_chart(fig_cum, use_container_width=True)

        with st.expander("📊 Dados brutos (±5 dias)"):
            win  = clim[(clim["date"] >= w_s) & (clim["date"] <= w_e)].copy()
            cols_show = [c for c in ["date","prcp","tmin","tmax","tavg","rh_avg","wspd_avg","wspd_max"]
                         if c in win.columns]
            st.dataframe(win[cols_show].sort_values("date").round(2),
                         use_container_width=True, height=300)

    # ═══════════════════ ABA BALANÇO HÍDRICO ══════════════════════════════════
    with tab_bal:
        st.markdown("#### 💧 Balanço Hídrico do Solo · Poseidon ")
        if clim.empty:
            st.warning("Dados climáticos não disponíveis.")
        else:
            try:
                wb  = water_balance(clim, float(lat), soil_props)
                fig = chart_water_balance(wb, start_dt, end_dt, complaint)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                wb_evt   = wb[(wb["date"] >= start_dt) & (wb["date"] <= end_dt)]
                awc      = soil_props.get("AWC", 100)
                ret      = soil_props.get("retencao", "-")
                deficit  = wb_evt["deficit"].sum()
                excedent = wb_evt["runoff"].sum()
                st.caption(
                    f"Solo: **{soil_name}** · AWC = {awc} mm/m · Retenção: {ret} · "
                    f"Déficit total no evento: **{deficit:.1f} mm** · "
                    f"Excedente: **{excedent:.1f} mm**"
                )

                # mini-tabela de resumo
                col_b1, col_b2, col_b3 = st.columns(3)
                col_b1.metric("Déficit total",   f"{deficit:.1f} mm",
                              delta=f"{'crítico' if deficit>50 else 'moderado' if deficit>20 else 'baixo'}",
                              delta_color="inverse")
                col_b2.metric("Excedente total", f"{excedent:.1f} mm")
                avg_stor = wb_evt["storage_pct"].mean() if not wb_evt.empty else 0
                col_b3.metric("Armazenamento médio", f"{avg_stor:.0f}%",
                              delta=f"{'crítico' if avg_stor<25 else 'baixo' if avg_stor<50 else 'ok'}",
                              delta_color="inverse")
            except Exception as e:
                st.error(f"Erro no balanço hídrico: {e}")

    # ═══════════════════ ABA MAPA ══════════════════════════════════════════════
    with tab_map:
        st.subheader("Localização do Caso")
        if not HAS_FOLIUM:
            st.warning("Instale: `pip install folium streamlit-folium`")
        else:
            available_indices = [k for k in ALL_INDICES
                                 if not ts.empty and f"{k}_mean" in ts.columns]
            available_dates   = (sorted(ts["date"].dt.strftime("%Y-%m-%d").unique())
                                 if not ts.empty else [])
            has_sat = bool(available_indices and available_dates)
            sel_idx  = None
            sel_date = available_dates[len(available_dates)//2] if available_dates else None

            col_map, col_right = st.columns([3, 2])

            with col_right:
                st.markdown("<div class='side-title'>🛰️ Índice Espectral</div>",
                            unsafe_allow_html=True)
                if not has_sat:
                    st.info("Nenhuma data de satélite disponível.")
                else:
                    choice = st.radio("idx_radio",
                        options=["— Nenhum —"] + available_indices, index=0,
                        label_visibility="collapsed",
                        format_func=lambda x: x if x == "— Nenhum —"
                                              else f"{x} — {INDEX_META.get(x,{}).get('desc','')}")
                    sel_idx = None if choice == "— Nenhum —" else choice
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
                st.markdown("<div class='side-title'>📅 Data Selecionada</div>",
                            unsafe_allow_html=True)
                if has_sat:
                    sel_date = st.selectbox("data_img", options=available_dates,
                        index=len(available_dates)//2, label_visibility="collapsed")
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
                                mín {col_min:.3f} · máx {col_max:.3f}</div>
                            </div>""", unsafe_allow_html=True)

                    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
                    for d in available_dates:
                        in_evt = start_dt <= pd.to_datetime(d) <= end_dt
                        dc     = "#3fb950" if in_evt else "#8b949e"
                        fw     = "font-weight:700;" if d == sel_date else ""
                        tag    = " ← evento" if in_evt else ""
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
                    st.info("Mapa não disponível.")

                if available_dates and len(available_dates) > 1:
                    st.markdown("<div style='margin-top:12px;font-size:12px;color:#8b949e'>"
                                "🕒 <b>Linha do tempo</b></div>", unsafe_allow_html=True)
                    slider_date = st.select_slider(
                        "timeline", options=available_dates,
                        value=sel_date or available_dates[0],
                        key="map_timeline_slider", label_visibility="collapsed")
                    if slider_date != sel_date:
                        m2 = build_map(rings_plot, lat, lon,
                                       ts if not ts.empty else None,
                                       sel_idx, slider_date)
                        if m2:
                            st_folium(m2, height=480, use_container_width=True,
                                      key="map_slider_view")

            with st.expander("📍 Coordenadas da geometria"):
                st.dataframe(
                    pd.DataFrame([{"lon": p[0], "lat": p[1]} for ring in rings_plot for p in ring]),
                    use_container_width=True)


if __name__ == "__main__":
    main()
