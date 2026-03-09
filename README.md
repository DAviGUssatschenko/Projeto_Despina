# 🌾 Project Despina

> **Poseidon · Copernicus · EMBRAPA** — Automated rural insurance claim validation using satellite imagery, weather station data, and soil analysis.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.x-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [How It Works](#how-it-works)
- [Data Sources](#data-sources)
- [Contributing](#contributing)

---

## Overview

This system validates rural insurance claims by crossing three independent data sources:

| Source | What it provides |
|---|---|
| **Poseidon** (PostgreSQL) | Interpolated weather data from nearby grid stations (IDW) |
| **Copernicus / Sentinel-2** | Satellite spectral indices: NDVI, EVI, NDWI, NDMI, BSI, NBR, NDRE, PSRI, CRI1 |
| **EMBRAPA** | National soil suitability shapefile — soil type, hydraulic properties, agricultural aptitude |

Supported claim event types: `drought`, `rainfall`, `frost`, `hail`.  
Supported crops: `soybean`, `corn`, `wheat`, `rice`.

---

## Architecture

```
                          ┌─────────────────────────────┐
  fazenda.geojson  ──────►│          main.py             │
  CLI arguments    ──────►│      (validation pipeline)   │
                          └──────────────┬──────────────┘
                                         │
               ┌─────────────────────────┼──────────────────────┐
               ▼                         ▼                       ▼
    ┌─────────────────┐      ┌──────────────────┐    ┌────────────────────┐
    │  poseidon.py    │      │  copernicus.py   │    │   soilapt.py       │
    │  PostgreSQL DB  │      │  Sentinel Hub    │    │   EMBRAPA .shp     │
    │  IDW interp.    │      │  Statistics API  │    │   soil suitability │
    └────────┬────────┘      └────────┬─────────┘    └─────────┬──────────┘
             └──────────────────────┬─┘                        │
                                    ▼                          ▼
                          ┌──────────────────────────────────────┐
                          │           analysis.py                │
                          │   ValidationEngine → score + verdict │
                          └──────────┬───────────────────────────┘
                                     │
                    ┌────────────────┴──────────────────┐
                    ▼                                   ▼
         ┌────────────────────┐             ┌─────────────────────┐
         │   storyteller.py   │             │   docx_exporter.py  │
         │  terminal report   │             │   Word document      │
         └────────────────────┘             └─────────────────────┘
                                                        │
                                            pipeline_*.json
                                                        │
                                                        ▼
                                          ┌─────────────────────┐
                                          │    dashboard.py      │
                                          │  Streamlit UI        │
                                          └─────────────────────┘
```

> `main.py` and `dashboard.py` are **two separate processes**. Run `main.py` first to generate the pipeline JSON, then load it in the dashboard.

---

## Project Structure

```
agricultural-claims-validator/
│
├── main.py                    # CLI entry point — run the full validation pipeline
├── config.py                  # All constants, thresholds, env vars (single source of truth)
├── dashboard.py               # Streamlit dashboard — loads pipeline JSON, visualizes results
├── app.py                     # Streamlit standalone app — GeoJSON only, no DB required
│
├── modules/                   # Core business logic
│   ├── __init__.py
│   ├── analysis.py            # ValidationEngine: crosses all data sources → verdict + score
│   ├── poseidon.py            # PostgreSQL connector, spatial queries, IDW interpolation
│   ├── copernicus.py          # Sentinel Hub / CDSE client, spectral index time series + cache
│   ├── soilapt.py             # EMBRAPA shapefile intersection → soil type, aptitude, AWC
│   ├── storyteller.py         # Rich terminal report generator
│   └── docx_exporter.py       # Professional Word (.docx) report exporter
│
├── data/
│   └── embrapa/
│       ├── aptagr_bra.shp     # EMBRAPA national agricultural suitability shapefile
│       ├── aptagr_bra.dbf     # Attribute table (required)
│       ├── aptagr_bra.prj     # Coordinate system definition (required)
│       └── aptagr_bra.shx     # Spatial index (required)
│
├── output_indices/            # Runtime output — spectral index PNGs (git-ignored)
│   └── .gitkeep
│
├── .env                       # ❌ Your real credentials — NEVER commit
├── .env.example               # ✅ Template — safe to commit
├── .gitignore
├── requirements.txt
├── Dockerfile
└── README.md
```

---

> ⚠️ **Important:** `analysis.py`, `poseidon.py`, `copernicus.py`, `soilapt.py`, `storyteller.py`, and `docx_exporter.py` must be placed inside the `modules/` subfolder. `main.py`, `config.py`, `dashboard.py`, and `app.py` stay in the project root.

---

## Prerequisites

- Python **3.10** or higher
- Access to a **Poseidon PostgreSQL** instance (for full pipeline mode)
- A **Copernicus Data Space** account with OAuth2 client credentials
- EMBRAPA shapefile (`aptagr_bra.*`) placed in `data/embrapa/`

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/DAviGUssatschenko/Project_Despina.git
cd Project_Despina

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up your environment variables
cp .env.example .env
# Edit .env with your real credentials (see Configuration section)
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```dotenv
# ─────────────────────────────────────────────────────────────────────────────
# .env — Project Credentials
# Fill in the values ​​and place this file in the project ROOT (next to config.py).
# ─────────────────────────────────────────────────────────────────────────────

# ── DataBase Poseidon (PostgreSQL) ───────────────────────────────────────────────
POSEIDON_DB_HOST=''
POSEIDON_DB_PORT=''
POSEIDON_DB_NAME=''
POSEIDON_DB_PASSWORD=''
POSEIDON_DB_USER=''

# ── Copernicus / Sentinel Hub ─────────────────────────────────────────────────
CDSE_CLIENT_ID= 'YOUR_ID'
CDSE_CLIENT_SECRET= 'YOUR_SECRET_ID'

# ── Alternatives paths ─────────────────
# EMBRAPA_SHAPEFILE= ~/alternative/path/aptagr_bra.shp
# OUTPUT_INDICES_DIR= ~/alternative/path/output_indices
```

> **Never commit `.env`** — it is already listed in `.gitignore`.  
> Get your Copernicus credentials at [dataspace.copernicus.eu](https://dataspace.copernicus.eu).

---

## Usage

### Step 1 — Run the validation pipeline (CLI)

```bash
ALL OF THIS ARE EXEMPLES

python main.py \
  --geojson  farm.geojson \
  --start    2024-01-01 \
  --end      2024-03-31 \
  --problem  drought \
  --crop     soybean \
  --db       "postgresql://user:password@host:port/db_name" \
  --planting 2023-10-20 \
  --farm-name "Fazenda São João"
```

This generates two outputs in the project root:
- `report_Fazenda_Sao_Joao_2024-01-01_drought.docx` — formatted Word report
- `pipeline_*.json` — full data payload for the dashboard

#### All CLI flags

| Flag | Required | Description |
|---|---|---|
| `--geojson` | ✅ | Path to the farm polygon GeoJSON |
| `--start` | ✅ | Event start date `YYYY-MM-DD` |
| `--end` | ✅ | Event end date `YYYY-MM-DD` |
| `--problem` | ✅ | Event type: `drought` `rainfall` `frost` `hail` |
| `--crop` | ✅ | Crop type: `soybean` `corn` `wheat` `rice` |
| `--db` | | PostgreSQL connection string |
| `--area-ha` | | Farm area in hectares (auto-calculated if omitted) |
| `--planting` | | Planting date `YYYY-MM-DD` |
| `--farm-name` | | Farm name for the report |
| `--docx` | | Custom output filename for the Word report |
| `--dry-run` | | Use synthetic data — no DB or internet required |
| `--fast` | | Use nearest Poseidon point only, skip IDW |
| `--no-soil` | | Skip EMBRAPA soil analysis |
| `--soil-shp` | | Path to an alternative EMBRAPA shapefile |
| `--pipeline` | | Custom output path for the pipeline JSON |

#### Quick test (no database or API needed)

```bash
python main.py \
  --geojson my_farm.geojson \
  --start 2024-01-01 \
  --end 2024-03-31 \
  --problem drought \
  --crop soybean \
  --dry-run
```

---

### Step 2 — Open the dashboard (Streamlit)

```bash
streamlit run dashboard.py
```

Then open [http://localhost:8501](http://localhost:8501) in your browser, and upload the `pipeline_*.json` file generated in Step 1 via the sidebar.

> **The dashboard does not open automatically when you run `main.py`.** They are independent processes. Always run `main.py` first, then `streamlit run dashboard.py`.

#### Standalone mode (no pipeline JSON)

```bash
streamlit run app.py
```

This mode accepts a GeoJSON directly in the browser and fetches weather data from Open-Meteo and Sentinel-2 imagery via AWS STAC — no Poseidon database connection required.

---

## How It Works

### Validation logic

The `ValidationEngine` in `analysis.py` evaluates each data source independently and combines them into a final confidence score:

```
Score = (Poseidon weather score × 0.4)
      + (Sentinel-2 spectral anomaly score × 0.4)
      + (Soil amplification factor × 0.2)
```

| Score | Verdict |
|---|---|
| ≥ 65 | ✅ CONFIRMED |
| 35 – 64 | ⚠️ INCONCLUSIVE |
| < 35 | ❌ NOT CONFIRMED |

### Poseidon IDW voting

Four cardinal neighbor stations (N, S, E, W) vote on the event. At least 3 of 4 must confirm the anomaly for the weather signal to pass. The final score is inverse-distance-weighted from the farm centroid.

### Sentinel-2 spectral indices

Each index is compared against a historical baseline (default: 60 days prior to the event). Anomaly percentage and absolute delta are used as features in the scoring model.

| Index | Measures |
|---|---|
| NDVI | Vegetation greenness |
| NDRE | Chlorophyll content |
| EVI | Enhanced vegetation |
| NDWI | Surface water |
| NDMI | Canopy moisture |
| BSI | Bare soil exposure |
| NBR | Burn / damage ratio |
| PSRI | Senescence / stress |
| CRI1 | Anthocyanin content |
| VHI | Vegetation Health Index (derived) |

---

## Data Sources

| Source | Description | Access |
|---|---|---|
| Poseidon | Internal PostgreSQL weather grid | Private — connection string required |
| Copernicus CDSE | Sentinel-2 L2A via Statistics API | [dataspace.copernicus.eu](https://dataspace.copernicus.eu) |
| EMBRAPA | National soil suitability map (1:5,000,000) | [geoinfo.cnps.embrapa.br](https://geoinfo.cnps.embrapa.br) |
| Open-Meteo | Free weather API (standalone mode only) | [open-meteo.com](https://open-meteo.com) |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit your changes: `git commit -m "feat: add your feature"`
4. Push to the branch: `git push origin feat/your-feature`
5. Open a Pull Request

Please keep credentials out of commits. Run `git status` before every push.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
