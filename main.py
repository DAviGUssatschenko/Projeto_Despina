import argparse
import json
import sys
import math
import os
from datetime import datetime, date
from typing import Dict, Optional

from rich.console import Console

console = Console()

DB_URL = ""


# ─────────────────────────────────────────────────────────────────────────────
# Arguments
# ─────────────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description="Agricultural Claims Validator — Poseidon + Copernicus + EMBRAPA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--geojson",   required=True,  help="GeoJSON farm archive")
    p.add_argument("--start",     required=True,  help="Event start date (YYYY-MM-DD)")
    p.add_argument("--end",       required=True,  help="Event Final Date (YYYY-MM-DD)")
    p.add_argument("--problem",   required=True,  choices=["drought", "rainfall", "frost", "hail"])
    p.add_argument("--crop",      required=True,  choices=["soybean", "wheat", "corn", "rice"])
    p.add_argument("--db",        default=DB_URL,  help="Connection string PostgreSQL")
    p.add_argument("--area-ha",   type=float, default=None)
    p.add_argument("--planting",  default=None,   help="Sowing date (YYYY-MM-DD)")
    p.add_argument("--farm-name", default="Rural Property")
    p.add_argument("--docx",      default=None,   help="Output .docx filename")
    p.add_argument("--dry-run",   action="store_true", help="Uses simulated data")
    p.add_argument("--fast",      action="store_true", help="Use the nearest Poseidon point (without IDW)")
    p.add_argument("--no-soil",   action="store_true", help="Embrapa soil analysis skips")
    p.add_argument("--soil-shp",  default=None,   help="Alternative path to EMBRAPA shapefile")
    p.add_argument("--pipeline",  default=None,   help="Path to the output pipeline_*.json file (default: pipeline_<name>_<date>_<event>.json)")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# GeoJSON
# ─────────────────────────────────────────────────────────────────────────────

def load_geojson(path: str) -> Dict:
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    if gj.get("type") == "FeatureCollection":
        geometry = gj["features"][0]["geometry"]
    elif gj.get("type") == "Feature":
        geometry = gj["geometry"]
    else:
        geometry = gj
    if geometry["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"Invalid geometry type: {geometry['type']}. Use Polygon or MultiPolygon.")
    return geometry


def compute_centroid(geometry: Dict) -> Dict:
    coords = []
    def _collect(obj):
        if isinstance(obj, list):
            if obj and isinstance(obj[0], (int, float)):
                coords.append(obj)
            else:
                for c in obj:
                    _collect(c)
    _collect(geometry["coordinates"])
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return {"lat": round(sum(lats) / len(lats), 6), "lon": round(sum(lons) / len(lons), 6)}


def compute_area_ha(geometry: Dict) -> float:
    try:
        from shapely.geometry import shape
        from pyproj import Geod
        geod    = Geod(ellps="WGS84")
        area_m2 = abs(geod.geometry_area_perimeter(shape(geometry))[0])
        return round(area_m2 / 10_000, 2)
    except Exception:
        coords = []
        def _c(o):
            if isinstance(o, list):
                if o and isinstance(o[0], (int, float)):
                    coords.append(o)
                else:
                    [_c(i) for i in o]
        _c(geometry["coordinates"])
        n    = len(coords)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += coords[i][0] * coords[j][1] - coords[j][0] * coords[i][1]
        lat_c = sum(c[1] for c in coords) / n
        m_lat = 111320.0
        m_lon = 111320.0 * abs(math.cos(math.radians(lat_c)))
        return round(abs(area / 2) * m_lat * m_lon / 10_000, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic data for dry-run
# ─────────────────────────────────────────────────────────────────────────────

def synthetic_copernicus(event_type: str) -> Dict:
    data = {
        "NDVI":  {"baseline_mean": 0.72, "event_mean": 0.41, "anomaly_abs": -0.31, "anomaly_pct": -43.1, "observations": 6},
        "NDRE":  {"baseline_mean": 0.48, "event_mean": 0.24, "anomaly_abs": -0.24, "anomaly_pct": -50.0, "observations": 6},
        "EVI":   {"baseline_mean": 0.55, "event_mean": 0.30, "anomaly_abs": -0.25, "anomaly_pct": -45.5, "observations": 6},
        "NDWI":  {"baseline_mean": 0.18, "event_mean": -0.14,"anomaly_abs": -0.32, "anomaly_pct":-177.8, "observations": 6},
        "NDMI":  {"baseline_mean": 0.25, "event_mean": -0.11,"anomaly_abs": -0.36, "anomaly_pct":-144.0, "observations": 6},
        "BSI":   {"baseline_mean":-0.12, "event_mean":  0.08,"anomaly_abs":  0.20, "anomaly_pct":-166.7, "observations": 6},
        "NBR":   {"baseline_mean": 0.35, "event_mean":  0.18,"anomaly_abs": -0.17, "anomaly_pct": -48.6, "observations": 6},
        "PSRI":  {"baseline_mean": 0.02, "event_mean":  0.09,"anomaly_abs":  0.07, "anomaly_pct": 350.0, "observations": 6},
        "CRI1":  {"baseline_mean": 0.30, "event_mean":  0.55,"anomaly_abs":  0.25, "anomaly_pct":  83.3, "observations": 6},
        "VHI":   {"vci": 32.5, "tci": 28.0, "event_mean": 30.2, "observations": 6},
    }
    if event_type == "rainfall":
        data["NDWI"]["event_mean"]  =  0.38
        data["NDWI"]["anomaly_pct"] =  111.1
    return data


def synthetic_poseidon_summary(event_type: str, start_date: date) -> Dict:
    from config import CLIMATE_NORMALS_RS
    nm  = CLIMATE_NORMALS_RS.get(start_date.month, {})
    np_ = nm.get("prcp_mm", 110)
    nt  = nm.get("tavg_c", 22)
    if event_type == "drought":
        prcp, tavg, rh = round(np_ * 0.28, 1), round(nt + 3.2, 2), 52.3
    elif event_type == "rainfall":
        prcp, tavg, rh = round(np_ * 2.4, 1),  round(nt - 1.5, 2), 92.1
    elif event_type == "frost":
        prcp, tavg, rh = round(np_ * 0.7, 1),  round(nt - 6.0, 2), 78.0
    else:
        prcp, tavg, rh = round(np_ * 1.8, 1),  nt, 85.0
    return {
        "period_days": 90, "prcp_total_mm": prcp, "prcp_max_day_mm": round(prcp * 0.12, 1),
        "prcp_days": 5 if event_type == "drought" else 12,
        "tavg_mean_c": tavg, "tmax_abs_c": round(tavg + 7.5, 2), "tmin_abs_c": round(tavg - 9.0, 2),
        "rh_avg_mean_pct": rh, "wspd_max_kmh": 32.4, "wspd_avg_kmh": 5.1,
    }


def synthetic_poseidon_vote(event_type: str) -> Dict:
    confirmed   = {"drought": 4, "rainfall": 3, "frost": 4, "hail": 3}.get(event_type, 3)
    w_score     = {"drought": 68.0, "rainfall": 55.0, "frost": 72.0, "hail": 50.0}.get(event_type, 55.0)
    dirs        = ["N", "S", "E", "W"]
    votes       = {}
    intensities = [75, 62, 70, 45] if confirmed == 4 else [72, 55, 40, 28]
    for i, d in enumerate(dirs):
        ok = i < confirmed
        votes[d] = {
            "confirmed": ok,
            "intensity": intensities[i],
            "point_id":  45729 + i,
            "lat": -33.498, "lon": -53.357, "direction": d,
            "reason": (
                f"Prcp 27% of the norm | Tmed +3.1°C | Intensity {intensities[i]}/100"
                if ok else
                f"No significant anomaly | Intensity {intensities[i]}/100"
            ),
        }
    signal_level = "strong" if w_score >= 60 else "moderate" if w_score >= 35 else "weak"
    return {
        "passed": w_score >= 35, "votes": votes,
        "score": confirmed, "total": 4,
        "weighted_score": w_score, "signal_level": signal_level,
        "description": (
            f"IDW Climate Score: {w_score:.0f}/100 — signal {signal_level} "
            f"({'✅ APPROVED' if w_score >= 35 else '❌ REJECTED'})"
        ),
    }


def synthetic_soil(event_type: str) -> Dict:
    """Synthetic soil data for dry-run."""
    return {
        "error":                        None,
        "dominant_class":               2,
        "soil_code":                    "LVd",
        "soil_name":                    "Latossolo Vermelho-Amarelo Distrófico",
        "resolved_name":                "Latossolo Vermelho-Amarelo",
        "suitable_for_agriculture":     True,
        "dominant_percentage":          78.4,
        "area_breakdown":               {2: 78.4, 3: 21.6},
        "soil_types": [
            {
                "code": "LVd", "name": "Latossolo Vermelho-Amarelo Distrófico",
                "resolved": "Latossolo Vermelho-Amarelo",
                "pct_area": 78.4, "apt_class": 2,
                "water_props": {"AWC": 110, "Ks": 28, "fc": 33, "wp": 14, "retention": "medium", "texture": "clayey"},
            },
            {
                "code": "CXbd", "name": "Cambissolo Háplico Tb Distrófico",
                "resolved": "Cambissolo Háplico",
                "pct_area": 21.6, "apt_class": 3,
                "water_props": {"AWC": 60, "Ks": 18, "fc": 26, "wp": 12, "retention": "medium-low", "texture": "medium"},
            },
        ],
        "water_props":                  {"AWC": 110, "Ks": 28, "fc": 33, "wp": 14, "retention": "medium", "texture": "clayey"},
        "aptitude_label":               "Regular",
        "aptitude_description":         "Land with regular suitability for crops",
        "classified_area_percentage":   100.0,
        "unclassified_area_percentage": 0.0,
    }



# ─────────────────────────────────────────────────────────────────────────────
# Pipeline JSON Export
# ─────────────────────────────────────────────────────────────────────────────

def _json_default(obj):
    """Serializer for non-native JSON types (date, datetime, etc.)."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        return float(obj)
    if hasattr(obj, "__int__"):
        return int(obj)
    return str(obj)


def _idw_daily_to_records(idw_df) -> list:
    """
    Converts the IDW-interpolated daily DataFrame to a list of dicts,
    ensuring 'date' is an ISO string and all numeric fields
    expected by dashboard.py are present.
    """
    if idw_df is None or getattr(idw_df, "empty", True):
        return []
    required = ["date", "prcp", "tmax", "tmin", "tavg", "rh_avg",
                "rh_min", "rh_max", "wspd_avg", "wspd_max", "wspd_min"]
    records = []
    for _, row in idw_df.iterrows():
        rec = {}
        for col in required:
            val = row.get(col)
            if hasattr(val, "isoformat"):          # Timestamp / date
                rec[col] = val.isoformat()[:10]
            elif val is None or (isinstance(val, float) and math.isnan(val)):
                rec[col] = None
            else:
                try:
                    rec[col] = round(float(val), 4)
                except Exception:
                    rec[col] = None
        records.append(rec)
    return records


def _cop_data_with_series(cop_data: dict, start_date: date, end_date: date) -> dict:
    """
    Ensures each index in cop_data has the keys that dashboard.py's
    cop_to_ts() needs: baseline_series and event_series, with items
    containing 'from', 'mean', 'stdev'.
    If cop_data already came from the Statistics API with nested series,
    keeps them. Otherwise rebuilds minimal lists.
    """
    out = {}
    for idx_name, data in cop_data.items():
        if not isinstance(data, dict):
            out[idx_name] = data
            continue

        entry = dict(data)

        # --- ensure baseline_series ---
        if not entry.get("baseline_series"):
            b_mean = entry.get("baseline_mean")
            if b_mean is not None:
                entry["baseline_series"] = [{
                    "from": datetime(
                        start_date.year - 1,
                        start_date.month,
                        start_date.day
                    ).date().isoformat(),
                    "mean":  b_mean,
                    "stdev": entry.get("baseline_std") or 0.0,
                }]
            else:
                entry["baseline_series"] = []

        # --- ensure event_series ---
        if not entry.get("event_series"):
            e_mean = entry.get("event_mean")
            if e_mean is not None:
                entry["event_series"] = [{
                    "from":  start_date.isoformat(),
                    "mean":  e_mean,
                    "stdev": entry.get("event_std") or 0.0,
                }]
            else:
                entry["event_series"] = []

        # normalise series items to expected schema
        for series_key in ("baseline_series", "event_series"):
            normalized = []
            for item in entry[series_key]:
                if not isinstance(item, dict):
                    continue
                dt_val = (item.get("from")
                          or item.get("date")
                          or (item.get("interval") or {}).get("from"))
                if not dt_val:
                    continue
                normalized.append({
                    "from":  str(dt_val)[:10],
                    "mean":  item.get("mean"),
                    "stdev": item.get("stdev") or item.get("std") or 0.0,
                })
            entry[series_key] = normalized

        out[idx_name] = entry
    return out


def save_enriched_geojson(
    *,
    farm_name: str,
    event_type: str,
    crop_type: str,
    start_date: date,
    end_date: date,
    area_ha: float,
    centroid: dict,
    geometry: dict,
    analysis: dict,
    cop_data: dict,
    pos_summ: dict,
    pos_vote: dict,
    soil_data: dict,
    hist_baseline: dict = None,
    idw_df=None,
    output_path: str = None,
) -> str:
    """
    Saves a valid FeatureCollection GeoJSON with all pipeline data embedded
    inside properties._pipeline. This is the single output file consumed by
    climate_dashboard.py.

    Standard GeoJSON properties (id, evento, inicio, fim, solo, cultura, bioma)
    are kept at the top level so the file remains a valid, human-readable GeoJSON.
    All pre-fetched Poseidon + Copernicus data lives under properties._pipeline.
    """
    _EVT_MAP  = {"drought": "seca", "rainfall": "chuva", "frost": "geada", "hail": "granizo"}
    _CROP_MAP = {"soybean": "SOJA", "corn": "MILHO", "wheat": "TRIGO", "rice": "ARROZ"}

    evento  = _EVT_MAP.get(event_type.lower(), event_type.lower())
    cultura = _CROP_MAP.get(crop_type.lower(), crop_type.upper())
    sd      = soil_data or {}
    solo    = sd.get("soil_code", "")
    bioma   = sd.get("biome", "")

    pipeline_block = {
        "meta": {
            "farm_name":  farm_name,
            "event_type": event_type,
            "crop_type":  crop_type,
            "start_date": start_date.isoformat(),
            "end_date":   end_date.isoformat(),
            "area_ha":    round(float(area_ha), 4) if area_ha else 0.0,
            "centroid": {
                "lat": round(float(centroid.get("lat", 0)), 6),
                "lon": round(float(centroid.get("lon", 0)), 6),
            },
        },
        "analysis":          analysis,
        "copernicus":        _cop_data_with_series(cop_data, start_date, end_date),
        "poseidon_summary":  pos_summ,
        "poseidon_vote":     pos_vote,
        "poseidon_daily":    _idw_daily_to_records(idw_df),
        "poseidon_baseline": hist_baseline or {},
        "soil_data":         sd,
    }

    feature = {
        "type": "Feature",
        "properties": {
            # ── Standard GeoJSON properties (human-readable, dashboard-compatible) ──
            "id":      farm_name,
            "evento":  evento,
            "inicio":  start_date.isoformat(),
            "fim":     end_date.isoformat(),
            "solo":    solo,
            "cultura": cultura,
            "bioma":   bioma,
            # ── All pre-fetched pipeline data ────────────────────────────────────
            "_pipeline": pipeline_block,
        },
        "geometry": geometry,
    }

    safe = farm_name.replace(" ", "_").replace("/", "-")
    if output_path is None:
        output_path = f"caso_{safe}_{start_date.isoformat()}_{evento}.geojson"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {"type": "FeatureCollection", "features": [feature]},
            f, ensure_ascii=False, indent=2, default=_json_default,
        )

    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = build_parser()
    args   = parser.parse_args()

    # Dates
    try:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
        end_date   = datetime.strptime(args.end,   "%Y-%m-%d").date()
    except ValueError as e:
        console.print(f"[red]Date error: {e}[/red]")
        return 1

    if start_date >= end_date:
        console.print("[red]--start must be earlier than --end[/red]")
        return 1

    planting_date: Optional[date] = None
    if args.planting:
        try:
            planting_date = datetime.strptime(args.planting, "%Y-%m-%d").date()
        except ValueError:
            console.print("[yellow]Invalid planting date — ignoring.[/yellow]")

    # GeoJSON
    console.print(f"\n[cyan]► Loading GeoJSON: {args.geojson}[/cyan]")
    try:
        geometry = load_geojson(args.geojson)
    except Exception as e:
        console.print(f"[red]Error loading GeoJSON: {e}[/red]")
        return 1

    centroid = compute_centroid(geometry)
    area_ha  = args.area_ha if args.area_ha else compute_area_ha(geometry)
    console.print(f"   Centroid  : lat={centroid['lat']}, lon={centroid['lon']}")
    console.print(f"   Area      : {area_ha:.1f} ha")

    from modules.analysis    import ValidationEngine
    from modules.storyteller import StoryTeller
    from config              import VALIDATION_THRESHOLDS

    # ── Dry-run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        console.print("[yellow]⚠  DRY-RUN: synthetic data.[/yellow]\n")
        cop_data      = synthetic_copernicus(args.problem)
        pos_summ      = synthetic_poseidon_summary(args.problem, start_date)
        pos_vote      = synthetic_poseidon_vote(args.problem)
        hist_baseline = {
            "prcp_mean_mm": 312.0, "prcp_std_mm": 45.0,
            "tavg_mean_c": 23.1, "years_used": [2022, 2021, 2020, 2019], "n_years": 4,
        }
        neighbors = {}
        soil_data = synthetic_soil(args.problem) if not args.no_soil else None
        idw_df    = None

    # ── Production ──────────────────────────────────────────────────────────────
    else:
        # Poseidon
        console.print("\n[cyan]► Connecting to Poseidon...[/cyan]")
        from modules.poseidon import PoseidonConnector
        poseidon = PoseidonConnector(args.db)
        try:
            poseidon.connect()
        except Exception as e:
            console.print(f"[red]Poseidon connection error: {e}[/red]")
            return 1

        nearest   = poseidon.find_nearest_point(centroid["lat"], centroid["lon"])
        neighbors = poseidon.find_cardinal_neighbors(centroid["lat"], centroid["lon"])
        console.print(f"   Nearest point: ID={nearest['point_id']}")
        console.print("   Neighbors: " + " | ".join(
            f"{d}={'✓' if v else '✗'}" for d, v in neighbors.items()
        ))

        thresholds = VALIDATION_THRESHOLDS.get(args.problem, {})
        console.print("\n[cyan]► IDW Voting...[/cyan]")
        pos_vote = poseidon.vote_3of4(
            neighbors, start_date, end_date, args.problem, thresholds,
            center_lat=centroid["lat"], center_lon=centroid["lon"],
        )
        console.print(f"   {pos_vote['description']}")

        console.print("\n[cyan]► IDW Interpolation...[/cyan]")
        if args.fast:
            console.print("   [yellow]Fast mode: using nearest point[/yellow]")
            pos_summ = poseidon.summarize_nearest(nearest, start_date, end_date)
        else:
            interp_df = poseidon.idw_interpolate(centroid["lat"], centroid["lon"], neighbors, start_date, end_date)
            pos_summ  = poseidon.summarize_period(interp_df, start_date, end_date)

        console.print("[cyan]   Collecting local history...[/cyan]")
        hist_baseline = poseidon.get_historical_baseline(nearest, start_date, end_date)
        idw_df        = interp_df if not args.fast else None
        if hist_baseline:
            console.print(f"   History: {hist_baseline['n_years']} years — "
                          f"avg prcp {hist_baseline['prcp_mean_mm']} mm")
        poseidon.close()

        # Copernicus
        console.print("\n[cyan]► Fetching Copernicus/Sentinel-2 data...[/cyan]")
        from modules.copernicus import CopernicusClient
        try:
            cop      = CopernicusClient()
            cop_data = cop.collect_all_indices(geometry, start_date, end_date)
        except Exception as e:
            console.print(f"[red]Copernicus error: {e}[/red]")
            return 1

        # EMBRAPA Soil
        soil_data = None
        if not args.no_soil:
            console.print("\n[cyan]► Analysing EMBRAPA soil data...[/cyan]")
            try:
                from modules.soilapt import check_soil_suitability
                soil_data = check_soil_suitability(
                    geojson_path=args.geojson,
                    soil_shapefile=args.soil_shp,  # None = usa config.py
                )
                if soil_data.get("error"):
                    console.print(f"   [yellow]⚠ Soil: {soil_data['error']}[/yellow]")
                else:
                    sol  = soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D")
                    cls  = soil_data.get("dominant_class", "N/D")
                    apt  = soil_data.get("aptitude_label", "N/D")
                    suit = "SUITABLE ✅" if soil_data.get("suitable_for_agriculture") else "UNSUITABLE ❌"
                    console.print(f"   Solo: {sol} | Classe {cls} ({apt}) | {suit}")
            except Exception as e:
                console.print(f"   [yellow]⚠ Soil analysis failed: {e}[/yellow]")
                soil_data = {"error": str(e)}

    # ── Analysis ───────────────────────────────────────────────────────────────
    console.print("\n[cyan]► Running analysis...[/cyan]")
    engine = ValidationEngine(
        event_type=args.problem, crop_type=args.crop,
        start_date=start_date,   end_date=end_date,
        area_ha=area_ha,         planting_date=planting_date,
    )
    analysis = engine.run(
        cop_data, pos_summ, pos_vote,
        hist_baseline=hist_baseline if "hist_baseline" in dir() else {},
        soil_data=soil_data,
    )

    # ── Terminal report ─────────────────────────────────────────────────
    story = StoryTeller(
        event_type=args.problem,  crop_type=args.crop,
        start_date=start_date,    end_date=end_date,
        area_ha=area_ha,          farm_name=args.farm_name,
        planting_date=planting_date, centroid=centroid,
    )
    story.generate(
        analysis, cop_data, pos_summ, pos_vote, neighbors,
        hist_baseline=hist_baseline if "hist_baseline" in dir() else {},
        soil_data=soil_data,
    )

    # ── Export Enriched GeoJSON ────────────────────────────────────────────────
    try:
        _idw = idw_df if "idw_df" in dir() else None
        geojson_path = save_enriched_geojson(
            farm_name=args.farm_name,
            event_type=args.problem,
            crop_type=args.crop,
            start_date=start_date,
            end_date=end_date,
            area_ha=area_ha,
            centroid=centroid,
            geometry=geometry,
            analysis=analysis,
            cop_data=cop_data,
            pos_summ=pos_summ,
            pos_vote=pos_vote,
            soil_data=soil_data,
            hist_baseline=hist_baseline if "hist_baseline" in dir() else {},
            idw_df=_idw,
            output_path=args.pipeline if args.pipeline else None,
        )
        console.print(f"\n[bold cyan]🗺️  Enriched GeoJSON saved: {geojson_path}[/bold cyan]")
    except Exception as e:
        console.print(f"[yellow]⚠ Error saving enriched GeoJSON: {e}[/yellow]")

    # ── Export DOCX ─────────────────────────────────────────────────────────
    try:
        from modules.docx_exporter import DocxExporter
        safe      = args.farm_name.replace(" ", "_").replace("/", "-")
        docx_path = args.docx if args.docx else f"report_{safe}_{args.start}_{args.problem}.docx"
        exp       = DocxExporter(
            event_type=args.problem,  crop_type=args.crop,
            start_date=start_date,    end_date=end_date,
            area_ha=area_ha,          farm_name=args.farm_name,
            planting_date=planting_date, centroid=centroid,
        )
        exp.export(
            analysis, cop_data, pos_summ, pos_vote, docx_path,
            hist_baseline=hist_baseline if "hist_baseline" in dir() else {},
            soil_data=soil_data,
        )
        console.print(f"\n[bold green]📄 DOCX report saved: {docx_path}[/bold green]\n")
    except ImportError:
        console.print("[yellow]⚠ python-docx not installed — run: pip install python-docx[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ Error generating DOCX: {e}[/yellow]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
