"""
modules/soilapt.py
Soil agricultural suitability analysis using the EMBRAPA shapefile.
Returns enriched data for use in the loss report.
"""

import geopandas as gpd
import pandas as pd
from typing import Dict, Optional

from config import (
    EMBRAPA_SHAPEFILE,
    SOIL_APTITUDE_CLASSES,
    SOIL_WATER_PROPERTIES,
    SOIL_CODE_ALIASES,
)


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaries
# ─────────────────────────────────────────────────────────────────────────────

def _fix_encoding(value) -> str:
    """Fixes latin1→utf-8 mojibake in strings from the EMBRAPA shapefile."""
    if pd.isna(value):
        return ""
    try:
        return str(value).encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        return str(value)


def _split_legend(legend_value: str):
    """
    Splits 'CXbd - Cambissolo Háplico Tb Distrófico' into (code, name).
    Returns (legend_value, legend_value) if there is no separator.
    """
    if not legend_value or legend_value == "Unknown":
        return "Unknown", "Unknown"
    s = str(legend_value).strip()
    if " - " in s:
        code, name = s.split(" - ", 1)
        return code.strip(), name.strip()
    return s, s


def _resolve_soil_name(soil_code: str, soil_name: str) -> str:
    """
    Tries to resolve the full soil name from the EMBRAPA code.
    Uses SOIL_CODE_ALIASES from config as a fallback.
    """
    code_lower = soil_code.lower().strip()
    for alias, full_name in SOIL_CODE_ALIASES.items():
        if code_lower.startswith(alias):
            return full_name
    # Tenta pelo nome direto
    for key in SOIL_WATER_PROPERTIES:
        if key.lower() in soil_name.lower():
            return key
    return soil_name


def get_soil_water_props(soil_code: str, soil_name: str) -> Dict:
    """Returns soil water properties, with fallback to 'default'."""
    resolved = _resolve_soil_name(soil_code, soil_name)
    return SOIL_WATER_PROPERTIES.get(resolved, SOIL_WATER_PROPERTIES["default"])


# ─────────────────────────────────────────────────────────────────────────────
# Main function
# ─────────────────────────────────────────────────────────────────────────────

def check_soil_suitability(
    geojson_path: str,
    soil_shapefile: Optional[str] = None,
) -> Dict:
    """
    Analyzes soil agricultural suitability within a field (GeoJSON),
    intersecting it with the EMBRAPA suitability shapefile.

    Returns a rich dict with:
      - dominant_class: dominant class (int)
      - soil_code / soil_name: code and name of the dominant soil
      - suitable_for_agriculture: bool
      - dominant_percentage: % of area with the dominant class
      - area_breakdown: distribution by class (%)
      - soil_types: list of soils found in the area
      - water_props: water properties of the dominant soil
      - aptitude_label / aptitude_description: readable text
      - classified_area_percentage / unclassified_area_percentage
      - error: str if something went wrong (missing field = no error)
    """
    shp_path = soil_shapefile or EMBRAPA_SHAPEFILE

    # ── load field ────────────────────────────────────────────────────────
    try:
        field = gpd.read_file(geojson_path)
    except Exception as e:
        return {"error": f"Error loading GeoJSON: {e}"}

    if field.empty:
        return {"error": "GeoJSON empty or without valid geometry."}

    # ── load EMBRAPA shapefile ─────────────────────────────────────────────
    try:
        # Load only necessary columns; legenda_ap is optional
        soils = gpd.read_file(shp_path, encoding="latin1")
    except Exception as e:
        return {"error": f"Error loading EMBRAPA shapefile ({shp_path}): {e}"}

    if soils.empty:
        return {"error": "Empty EMBRAPA shapefile."}

    # ── fix encoding ──────────────────────────────────────────────────────
    for col in ["legenda", "legenda_ap"]:
        if col in soils.columns:
            soils[col] = soils[col].apply(_fix_encoding)

    # ── align CRS and clip ─────────────────────────────────────────────────
    soils = soils.to_crs(field.crs)
    minx, miny, maxx, maxy = field.total_bounds
    candidate_idx = list(soils.sindex.intersection((minx, miny, maxx, maxy)))
    candidates    = soils.iloc[candidate_idx].copy()

    if candidates.empty:
        return {"error": "No soil data found for this area."}

    clipped = gpd.clip(candidates, field)
    if clipped.empty:
        return {"error": "Field area does not intersect with EMBRAPA soil data."}

    # ── calculate areas in SIRGAS 2000 Conic (EPSG:5880) ──────────────────────
    clipped = clipped.to_crs(5880)
    clipped["_area_m2"] = clipped.geometry.area
    total_area = clipped["_area_m2"].sum()

    if total_area == 0:
        return {"error": "Resulting area is zero after reprojection."}

    # ── suitability ───────────────────────────────────────────────────────────────
    apt_col = "classe_apt" if "classe_apt" in clipped.columns else None
    if apt_col is None:
        return {"error": "Column 'classe_apt' not found in the shapefile."}

    clipped["_apt_num"] = pd.to_numeric(clipped[apt_col], errors="coerce")
    unclassified_area   = clipped.loc[clipped["_apt_num"].isna(), "_area_m2"].sum()
    classified          = clipped.dropna(subset=["_apt_num"]).copy()
    classified["_apt_num"] = classified["_apt_num"].astype(int)

    classified_pct   = round((total_area - unclassified_area) / total_area * 100, 1)
    unclassified_pct = round(unclassified_area / total_area * 100, 1)

    # Area distribution by class (%)
    area_by_class = (
        classified
        .groupby("_apt_num")["_area_m2"]
        .sum()
        .sort_values(ascending=False)
    )
    area_breakdown = {
        int(cls): round(area / total_area * 100, 1)
        for cls, area in area_by_class.items()
    }

    if area_by_class.empty:
        return {
            "error":                        None,
            "dominant_class":               None,
            "soil_code":                    "N/D",
            "soil_name":                    "N/D",
            "suitable_for_agriculture":     False,
            "dominant_percentage":          0.0,
            "area_breakdown":               {},
            "soil_types":                   [],
            "water_props":                  SOIL_WATER_PROPERTIES["default"],
            "aptitude_label":               "Unclassified",
            "aptitude_description":         "No EMBRAPA suitability classification.",
            "classified_area_percentage":   classified_pct,
            "unclassified_area_percentage": unclassified_pct,
        }

    dominant_class = int(area_by_class.index[0])
    dominant_pct   = round(area_by_class.iloc[0] / total_area * 100, 1)

    # ── dominant soil ────────────────────────────────────────────────────────
    dom_rows = classified[classified["_apt_num"] == dominant_class].copy()

    leg_col = "legenda" if "legenda" in dom_rows.columns else None
    if leg_col and not dom_rows[leg_col].dropna().empty:
        dominant_legend = dom_rows[leg_col].dropna().mode().iloc[0]
    else:
        dominant_legend = "Unknown"

    soil_code, soil_name = _split_legend(dominant_legend)
    resolved_name        = _resolve_soil_name(soil_code, soil_name)
    water_props          = SOIL_WATER_PROPERTIES.get(resolved_name, SOIL_WATER_PROPERTIES["default"])
    apt_info             = SOIL_APTITUDE_CLASSES.get(dominant_class, {})

    # ── List of soils found ────────────────────────────────────────────
    soil_types = []
    if leg_col:
        for leg_val, grp in classified.groupby(leg_col):
            if pd.isna(leg_val) or not str(leg_val).strip():
                continue
            sc, sn = _split_legend(str(leg_val))
            rn     = _resolve_soil_name(sc, sn)
            pct    = round(grp["_area_m2"].sum() / total_area * 100, 1)
            apt_n  = grp["_apt_num"].mode().iloc[0] if not grp["_apt_num"].empty else None
            soil_types.append({
                "code":        sc,
                "name":        sn,
                "resolved":    rn,
                "pct_area":    pct,
                "apt_class":   int(apt_n) if apt_n is not None else None,
                "water_props": SOIL_WATER_PROPERTIES.get(rn, SOIL_WATER_PROPERTIES["default"]),
            })
        soil_types.sort(key=lambda x: x["pct_area"], reverse=True)

    return {
        "error":                        None,
        "dominant_class":               dominant_class,
        "soil_code":                    soil_code,
        "soil_name":                    soil_name,
        "resolved_name":                resolved_name,
        "suitable_for_agriculture":     apt_info.get("suitable", False),
        "dominant_percentage":          dominant_pct,
        "area_breakdown":               area_breakdown,
        "soil_types":                   soil_types[:5],    # top-5 soils
        "water_props":                  water_props,
        "aptitude_label":               apt_info.get("label", "N/D"),
        "aptitude_description":         apt_info.get("description", ""),
        "classified_area_percentage":   classified_pct,
        "unclassified_area_percentage": unclassified_pct,
    }
