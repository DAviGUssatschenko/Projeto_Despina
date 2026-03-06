"""
modules/soilapt.py
Análise de aptidão agrícola do solo via shapefile EMBRAPA.
Retorna dados enriquecidos para uso no relatório de sinistro.
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
# Utilitários
# ─────────────────────────────────────────────────────────────────────────────

def _fix_encoding(value) -> str:
    """Corrige mojibake latin1→utf-8 em strings do shapefile EMBRAPA."""
    if pd.isna(value):
        return ""
    try:
        return str(value).encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        return str(value)


def _split_legend(legend_value: str):
    """
    Divide 'CXbd - Cambissolo Háplico Tb Distrófico' em (código, nome).
    Retorna (legend_value, legend_value) se não houver separador.
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
    Tenta resolver o nome completo do solo a partir do código EMBRAPA.
    Usa SOIL_CODE_ALIASES do config como fallback.
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
    """Retorna propriedades hídricas do solo, com fallback para 'default'."""
    resolved = _resolve_soil_name(soil_code, soil_name)
    return SOIL_WATER_PROPERTIES.get(resolved, SOIL_WATER_PROPERTIES["default"])


# ─────────────────────────────────────────────────────────────────────────────
# Função principal
# ─────────────────────────────────────────────────────────────────────────────

def check_soil_suitability(
    geojson_path: str,
    soil_shapefile: Optional[str] = None,
) -> Dict:
    """
    Analisa a aptidão agrícola do solo dentro de um talhão (GeoJSON),
    cruzando com o shapefile de aptidão da EMBRAPA.

    Retorna dict rico com:
      - dominant_class: classe dominante (int)
      - soil_code / soil_name: código e nome do solo dominante
      - suitable_for_agriculture: bool
      - dominant_percentage: % da área com a classe dominante
      - area_breakdown: distribuição por classe (%)
      - soil_types: lista de solos encontrados na área
      - water_props: propriedades hídricas do solo dominante
      - aptitude_label / aptitude_description: texto legível
      - classified_area_percentage / unclassified_area_percentage
      - error: str se algo deu errado (campo ausente = sem erro)
    """
    shp_path = soil_shapefile or EMBRAPA_SHAPEFILE

    # ── carrega talhão ────────────────────────────────────────────────────────
    try:
        field = gpd.read_file(geojson_path)
    except Exception as e:
        return {"error": f"Erro ao carregar GeoJSON: {e}"}

    if field.empty:
        return {"error": "GeoJSON vazio ou sem geometria válida."}

    # ── carrega shapefile EMBRAPA ─────────────────────────────────────────────
    try:
        # Carregamos apenas as colunas necessárias; legenda_ap é opcional
        soils = gpd.read_file(shp_path, encoding="latin1")
    except Exception as e:
        return {"error": f"Erro ao carregar shapefile EMBRAPA ({shp_path}): {e}"}

    if soils.empty:
        return {"error": "Shapefile EMBRAPA vazio."}

    # ── corrige encoding ──────────────────────────────────────────────────────
    for col in ["legenda", "legenda_ap"]:
        if col in soils.columns:
            soils[col] = soils[col].apply(_fix_encoding)

    # ── alinha CRS e faz clip ─────────────────────────────────────────────────
    soils = soils.to_crs(field.crs)
    minx, miny, maxx, maxy = field.total_bounds
    candidate_idx = list(soils.sindex.intersection((minx, miny, maxx, maxy)))
    candidates    = soils.iloc[candidate_idx].copy()

    if candidates.empty:
        return {"error": "Nenhum dado de solo encontrado para esta área."}

    clipped = gpd.clip(candidates, field)
    if clipped.empty:
        return {"error": "Área do talhão não intersecta com dados de solo EMBRAPA."}

    # ── calcula áreas em SIRGAS 2000 Cônica (EPSG:5880) ──────────────────────
    clipped = clipped.to_crs(5880)
    clipped["_area_m2"] = clipped.geometry.area
    total_area = clipped["_area_m2"].sum()

    if total_area == 0:
        return {"error": "Área resultante é zero após reprojeção."}

    # ── aptidão ───────────────────────────────────────────────────────────────
    apt_col = "classe_apt" if "classe_apt" in clipped.columns else None
    if apt_col is None:
        return {"error": "Coluna 'classe_apt' não encontrada no shapefile."}

    clipped["_apt_num"] = pd.to_numeric(clipped[apt_col], errors="coerce")
    unclassified_area   = clipped.loc[clipped["_apt_num"].isna(), "_area_m2"].sum()
    classified          = clipped.dropna(subset=["_apt_num"]).copy()
    classified["_apt_num"] = classified["_apt_num"].astype(int)

    classified_pct   = round((total_area - unclassified_area) / total_area * 100, 1)
    unclassified_pct = round(unclassified_area / total_area * 100, 1)

    # Distribuição de área por classe (%)
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
            "aptitude_label":               "Não classificado",
            "aptitude_description":         "Sem classificação de aptidão EMBRAPA.",
            "classified_area_percentage":   classified_pct,
            "unclassified_area_percentage": unclassified_pct,
        }

    dominant_class = int(area_by_class.index[0])
    dominant_pct   = round(area_by_class.iloc[0] / total_area * 100, 1)

    # ── solo dominante ────────────────────────────────────────────────────────
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

    # ── lista de solos encontrados ────────────────────────────────────────────
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
        "soil_types":                   soil_types[:5],    # top-5 solos
        "water_props":                  water_props,
        "aptitude_label":               apt_info.get("label", "N/D"),
        "aptitude_description":         apt_info.get("description", ""),
        "classified_area_percentage":   classified_pct,
        "unclassified_area_percentage": unclassified_pct,
    }
