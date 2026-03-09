"""
config.py — Parameters, thresholds and system constants
"""

import os
from pathlib import Path

# Loads variables from the .env file if it exists (without requiring the dependency in prod)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv not installed — variables must come from the environment (Docker, CI, etc.)

# ─────────────────────────────────────────────
# POSEIDON — PostgreSQL database tables
# ─────────────────────────────────────────────
POSEIDON_TABLES = {
    "coordinates": "poseidon.points_coordinates",
    "weather":     "poseidon.weather_data_processed",
}

POSEIDON_GRID_STEP = 0.09009

# ─────────────────────────────────────────────
# DATABASE URL (Poseidon)
# ─────────────────────────────────────────────
# Accepts a full connection string OR individual POSEIDON_DB_* vars.
# Example: postgresql://user:pass@host:5432/dbname
DB_URL = os.getenv("DATABASE_URL", os.getenv("DB_URL", os.getenv("POSEIDON_DB_URL", "")))

# ─────────────────────────────────────────────
# COPERNICUS CREDENTIALS
# ─────────────────────────────────────────────
CDSE_CLIENT_ID     = os.getenv("CDSE_CLIENT_ID", "")
CDSE_CLIENT_SECRET = os.getenv("CDSE_CLIENT_SECRET", "")

CDSE_TOKEN_URL   = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_STATS_URL   = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
CDSE_CATALOG_URL = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0/search"

SENTINEL2_RESOLUTION  = 20
MAX_CLOUD_COVER       = 20
BASELINE_LOOKBACK_DAYS = 60

# ─────────────────────────────────────────────
# EMBRAPA — Soil data
# ─────────────────────────────────────────────
_BASE_DIR = Path(__file__).parent
EMBRAPA_SHAPEFILE = os.getenv(
    "EMBRAPA_SHAPEFILE",
    str(_BASE_DIR / "data" / "embrapa" / "aptagr_bra.shp"),
)

# Output directory for index images (used in appv25.py)
OUTPUT_INDICES_DIR = Path(
    os.getenv("OUTPUT_INDICES_DIR", str(_BASE_DIR / "output_indices"))
)

# EMBRAPA agricultural suitability classes
SOIL_APTITUDE_CLASSES = {
    1: {"label": "Good",               "suitable": True,  "description": "Land with good suitability for crops"},
    2: {"label": "Regular",            "suitable": True,  "description": "Land with regular suitability for crops"},
    3: {"label": "Restricted",         "suitable": True,  "description": "Land with restricted suitability for crops"},
    4: {"label": "Unsuitable (past)",  "suitable": False, "description": "Unsuitable for crops — recommended for pasture"},
    5: {"label": "Unsuitable (silv)",  "suitable": False, "description": "Unsuitable for crops — recommended for forestry"},
    6: {"label": "Preservation",       "suitable": False, "description": "Land recommended for environmental preservation"},
}

# Water properties by soil type
SOIL_WATER_PROPERTIES = {
    "Latossolo Vermelho":         {"AWC": 120, "Ks": 30, "fc": 35, "wp": 15, "retention": "medium",       "texture": "clayey"},
    "Latossolo Amarelo":          {"AWC": 100, "Ks": 25, "fc": 32, "wp": 14, "retention": "medium",       "texture": "clay-sandy"},
    "Latossolo Vermelho-Amarelo": {"AWC": 110, "Ks": 28, "fc": 33, "wp": 14, "retention": "medium",       "texture": "clayey"},
    "Argissolo Vermelho":         {"AWC":  80, "Ks":  8, "fc": 30, "wp": 18, "retention": "high",         "texture": "clayey"},
    "Argissolo Amarelo":          {"AWC":  90, "Ks": 10, "fc": 31, "wp": 17, "retention": "high",         "texture": "clay-sandy"},
    "Nitossolo Vermelho":         {"AWC": 130, "Ks": 15, "fc": 38, "wp": 18, "retention": "high",         "texture": "very clayey"},
    "Cambissolo Húmico":          {"AWC":  70, "Ks": 20, "fc": 28, "wp": 13, "retention": "medium-low",   "texture": "medium"},
    "Cambissolo Háplico":         {"AWC":  60, "Ks": 18, "fc": 26, "wp": 12, "retention": "medium-low",   "texture": "medium"},
    "Neossolo Litólico":          {"AWC":  30, "Ks": 50, "fc": 20, "wp":  8, "retention": "low",          "texture": "sandy"},
    "Neossolo Quartzarênico":     {"AWC":  40, "Ks": 80, "fc": 18, "wp":  5, "retention": "very low",     "texture": "sandy"},
    "Neossolo Flúvico":           {"AWC": 100, "Ks": 15, "fc": 30, "wp": 15, "retention": "high",         "texture": "medium"},
    "Gleissolo Háplico":          {"AWC": 150, "Ks":  2, "fc": 45, "wp": 25, "retention": "very high",    "texture": "very clayey"},
    "Gleissolo Melânico":         {"AWC": 160, "Ks":  1, "fc": 48, "wp": 26, "retention": "very high",    "texture": "very clayey"},
    "Espodossolo":                {"AWC":  50, "Ks": 40, "fc": 22, "wp":  8, "retention": "low",          "texture": "sandy"},
    "Planossolo Háplico":         {"AWC":  80, "Ks":  3, "fc": 32, "wp": 18, "retention": "very high",    "texture": "clayey"},
    "Vertissolo":                 {"AWC": 160, "Ks":  1, "fc": 48, "wp": 28, "retention": "very high",    "texture": "very clayey"},
    "Chernossolo":                {"AWC": 140, "Ks": 12, "fc": 40, "wp": 20, "retention": "high",         "texture": "clayey"},
    "Organossolo":                {"AWC": 200, "Ks":  2, "fc": 60, "wp": 30, "retention": "very high",    "texture": "organic"},
    "default":                    {"AWC": 100, "Ks": 20, "fc": 30, "wp": 15, "retention": "medium",       "texture": "medium"},
}

# Mapping from EMBRAPA code prefix → full name in SOIL_WATER_PROPERTIES
SOIL_CODE_ALIASES = {
    "lva":  "Latossolo Vermelho-Amarelo",
    "lv":   "Latossolo Vermelho",
    "la":   "Latossolo Amarelo",
    "pv":   "Argissolo Vermelho",
    "pa":   "Argissolo Amarelo",
    "nv":   "Nitossolo Vermelho",
    "ch":   "Cambissolo Húmico",
    "cx":   "Cambissolo Háplico",
    "rl":   "Neossolo Litólico",
    "rq":   "Neossolo Quartzarênico",
    "ru":   "Neossolo Flúvico",
    "gx":   "Gleissolo Háplico",
    "gm":   "Gleissolo Melânico",
    "es":   "Espodossolo",
    "sx":   "Planossolo Háplico",
    "vx":   "Vertissolo",
    "mk":   "Chernossolo",
    "oj":   "Organossolo",
}

# Damage amplification factor by soil type and event
SOIL_EVENT_AMPLIFIER = {
    "drought": {
        "very low": 1.35,
        "low":       1.20,
        "medium-low": 1.10,
        "medium":       1.00,
        "high":        0.90,
        "very high":  0.80,
    },
    "rainfall": {
        "very low": 0.75,
        "low":       0.80,
        "medium-low": 0.95,
        "medium":       1.00,
        "high":        1.15,
        "very high":  1.40,
    },
    "frost": {
        "very low": 1.05,
        "low":       1.02,
        "medium-low": 1.00,
        "medium":       1.00,
        "high":        0.98,
        "very high":  0.95,
    },
    "hail": {
        "very low": 1.10,
        "low":       1.05,
        "medium-low": 1.00,
        "medium":       1.00,
        "high":        1.00,
        "very high":  1.05,
    },
}

# ─────────────────────────────────────────────
# SENTINEL-2 INDEX — Evalscripts
# ─────────────────────────────────────────────
EVALSCRIPTS = {
    "NDVI": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04","B08","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [(s.B08 - s.B04) / (s.B08 + s.B04 + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "NDRE": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B05","B08","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [(s.B08 - s.B05) / (s.B08 + s.B05 + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "EVI": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02","B04","B08","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [2.5 * (s.B08 - s.B04) / (s.B08 + 6*s.B04 - 7.5*s.B02 + 1 + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "NDWI": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B03","B08","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [(s.B03 - s.B08) / (s.B03 + s.B08 + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "NDMI": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B08","B11","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [(s.B08 - s.B11) / (s.B08 + s.B11 + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "BSI": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02","B04","B08","B11","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [((s.B11 + s.B04) - (s.B08 + s.B02)) / ((s.B11 + s.B04) + (s.B08 + s.B02) + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "NBR": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B08","B12","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [(s.B08 - s.B12) / (s.B08 + s.B12 + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "PSRI": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02","B04","B06","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  return {
    default:  [(s.B04 - s.B02) / (s.B06 + 1e-10)],
    dataMask: [s.dataMask]
  };
}""",

    "CRI1": """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02","B03","dataMask"] }],
    output: [
      { id: "default",  bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let v = (1/(s.B02 + 1e-10)) - (1/(s.B03 + 1e-10));
  return {
    default:  [Math.min(Math.max(v, -1), 1)],
    dataMask: [s.dataMask]
  };
}""",
}

# ─────────────────────────────────────────────
# VALIDATION THRESHOLDS
# ─────────────────────────────────────────────
VALIDATION_THRESHOLDS = {
    # ── English keys (used by main.py / internal pipeline) ────────────────
    "drought": {
        "poseidon": {
            "prcp_deficit_pct": 40,
            "tavg_anomaly_c":    2.0,
            "rh_avg_max":       60.0,
        },
        "satellite": {
            "ndvi_drop_pct":    25,
            "ndwi_threshold":  -0.05,
            "ndmi_threshold":  -0.10,
            "bsi_increase":     0.05,
            "vhi_critical":    40.0,
        }
    },
    "rainfall": {
        "poseidon": {
            "prcp_excess_pct":      150,
            "wspd_max_threshold":    30.0,
            "rh_avg_min":            85.0,
        },
        "satellite": {
            "ndwi_threshold":   0.20,
            "ndvi_drop_pct":    15,
            "bsi_increase":     0.10,
        }
    },
    "frost": {
        "poseidon": {
            "tmin_threshold":   2.0,
            "consecutive_days": 2,
        },
        "satellite": {
            "ndvi_drop_pct":   30,
            "psri_increase":    0.05,
            "ndre_drop_pct":   35,
        }
    },
    "hail": {
        "poseidon": {
            "wspd_max_threshold": 40.0,
            "prcp_daily_max":     30.0,
        },
        "satellite": {
            "ndvi_drop_pct":    20,
            "nbr_drop_pct":     15,
            "bsi_increase":     0.08,
        }
    },
}

# ── Portuguese aliases — GeoJSON evento field uses pt-BR ──────────────────
# seca=drought, chuva=rainfall, geada=frost, granizo=hail
VALIDATION_THRESHOLDS["seca"]    = VALIDATION_THRESHOLDS["drought"]
VALIDATION_THRESHOLDS["chuva"]   = VALIDATION_THRESHOLDS["rainfall"]
VALIDATION_THRESHOLDS["geada"]   = VALIDATION_THRESHOLDS["frost"]
VALIDATION_THRESHOLDS["granizo"] = VALIDATION_THRESHOLDS["hail"]

# ─────────────────────────────────────────────
# AGRONOMIC PARAMETERS
# ─────────────────────────────────────────────
CROP_PARAMS = {
    "soybean": {
        "name_en":              "Soybean",
        "yield_min_bags_ha":    40,
        "yield_avg_bags_ha":    52,
        "yield_max_bags_ha":    65,
        "price_brl_bag":        145.0,
        "bag_kg":               60,
        "cycle_days":           120,
        "critical_phases": {
            "germination":      (0,   15),
            "vegetative":       (15,  55),
            "flowering":        (55,  75),
            "grain_filling":    (75, 100),
            "maturation":       (100, 120),
        },
        "yield_loss_factor": {
            "germination":      0.40,
            "vegetative":       0.50,
            "flowering":        0.85,
            "grain_filling":    0.90,
            "maturation":       0.30,
        },
        "ndvi_healthy_min": 0.60,
        "ndvi_critical":    0.35,
    },
    "corn": {
        "name_en":              "Corn",
        "yield_min_bags_ha":    100,
        "yield_avg_bags_ha":    140,
        "yield_max_bags_ha":    180,
        "price_brl_bag":        58.0,
        "bag_kg":               60,
        "cycle_days":           130,
        "critical_phases": {
            "germination":      (0,   10),
            "vegetative":       (10,  60),
            "tasseling":        (60,  75),
            "silking":          (75,  90),
            "grain_filling":    (90, 120),
            "maturation":       (120, 130),
        },
        "yield_loss_factor": {
            "germination":      0.30,
            "vegetative":       0.55,
            "tasseling":        0.80,
            "silking":          0.95,
            "grain_filling":    0.85,
            "maturation":       0.25,
        },
        "ndvi_healthy_min": 0.65,
        "ndvi_critical":    0.38,
    },
    "wheat": {
        "name_en":              "Wheat",
        "yield_min_bags_ha":    40,
        "yield_avg_bags_ha":    55,
        "yield_max_bags_ha":    70,
        "price_brl_bag":        90.0,
        "bag_kg":               60,
        "cycle_days":           110,
        "critical_phases": {
            "germination":      (0,   15),
            "tillering":        (15,  40),
            "heading":          (40,  60),
            "grain_development": (60, 90),
            "maturation":       (90, 110),
        },
        "yield_loss_factor": {
            "germination":      0.45,
            "tillering":        0.60,
            "heading":          0.90,
            "grain_development": 0.80,
            "maturation":       0.20,
        },
        "ndvi_healthy_min": 0.55,
        "ndvi_critical":    0.30,
    },
    "rice": {
        "name_en":              "Rice",
        "yield_min_bags_ha":    130,
        "yield_avg_bags_ha":    170,
        "yield_max_bags_ha":    210,
        "price_brl_bag":        55.0,
        "bag_kg":               50,
        "cycle_days":           120,
        "critical_phases": {
            "germination":      (0,   15),
            "vegetative":       (15,  60),
            "flowering":        (60,  80),
            "grain_development": (80, 105),
            "maturation":       (105, 120),
        },
        "yield_loss_factor": {
            "germination":      0.35,
            "vegetative":       0.60,
            "flowering":        0.92,
            "grain_development": 0.85,
            "maturation":       0.15,
        },
        "ndvi_healthy_min": 0.60,
        "ndvi_critical":    0.35,
    },
}

# ─────────────────────────────────────────────
# CLIMATE NORMALS — Rio Grande do Sul
# ─────────────────────────────────────────────
CLIMATE_NORMALS_RS = {
    1:  {"prcp_mm": 130, "tavg_c": 24.5},
    2:  {"prcp_mm": 115, "tavg_c": 24.2},
    3:  {"prcp_mm": 105, "tavg_c": 22.8},
    4:  {"prcp_mm":  90, "tavg_c": 19.5},
    5:  {"prcp_mm": 100, "tavg_c": 16.0},
    6:  {"prcp_mm": 130, "tavg_c": 13.5},
    7:  {"prcp_mm": 120, "tavg_c": 13.0},
    8:  {"prcp_mm":  95, "tavg_c": 14.5},
    9:  {"prcp_mm": 115, "tavg_c": 16.5},
    10: {"prcp_mm": 145, "tavg_c": 19.5},
    11: {"prcp_mm": 120, "tavg_c": 22.0},
    12: {"prcp_mm": 135, "tavg_c": 24.0},
}
