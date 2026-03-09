"""
modules/analysis.py
Validation engine: cross-references Copernicus + Poseidon + EMBRAPA Soil data
and calculates a confidence score + final verdict.
"""

from __future__ import annotations
from datetime import date
from typing import Dict, List, Optional

import numpy as np

from config import (
    VALIDATION_THRESHOLDS,
    CROP_PARAMS,
    CLIMATE_NORMALS_RS,
    SOIL_APTITUDE_CLASSES,
    SOIL_WATER_PROPERTIES,
    SOIL_EVENT_AMPLIFIER,
)


class ValidationEngine:

    def __init__(
        self,
        event_type:    str,
        crop_type:     str,
        start_date:    date,
        end_date:      date,
        area_ha:       float,
        planting_date: Optional[date] = None,
    ):
        self.event_type    = event_type
        self.crop_type     = crop_type
        self.start_date    = start_date
        self.end_date      = end_date
        self.area_ha       = area_ha
        self.planting_date = planting_date
        self.thresholds    = VALIDATION_THRESHOLDS.get(event_type, {})
        self.crop_params   = CROP_PARAMS.get(crop_type, CROP_PARAMS["soja"])
        self._checks: List[Dict] = []

    #entry point
    def run(
        self,
        copernicus_data:  Dict,
        poseidon_summary: Dict,
        poseidon_vote:    Dict,
        hist_baseline:    Dict = None,
        soil_data:        Dict = None,
    ) -> Dict:
        self._checks = []

        #satellite
        self._check_satellite(copernicus_data)
        #poseidon — IDW voting
        self._check_poseidon_vote(poseidon_vote)
        #poseidon — weather summary
        self._check_poseidon_summary(poseidon_summary)
        #cross-consistency satellite ↔ station
        self._check_cross_consistency(copernicus_data, poseidon_summary)
        #phenological phase
        phase_info = self._check_crop_phase()
        #EMBRAPA soil (if available)
        soil_check = self._check_soil(soil_data) if soil_data and not soil_data.get("error") else None

        total_weight = sum(c["weight"] for c in self._checks)
        achieved     = sum(c["weight"] for c in self._checks if c["passed"])
        pct_passed   = (achieved / total_weight * 100) if total_weight else 0

        #uncertainty penalty due to lack of cloud-free images.
        obs_total = sum(
            copernicus_data.get(idx, {}).get("observations", 0)
            for idx in ["NDVI", "NDWI", "NDMI"]
        )
        uncertainty_penalty = max(0, (6 - obs_total) * 3)
        confidence = round(min(pct_passed - uncertainty_penalty, 92), 1)
        confidence = max(confidence, 0)

        #IDW score → severity
        idw_score = poseidon_vote.get("weighted_score", 0)
        if   idw_score >= 70: severity = "muito severo"
        elif idw_score >= 50: severity = "severo"
        elif idw_score >= 35: severity = "moderado"
        elif idw_score >= 20: severity = "fraco"
        else:                 severity = "ausente / inconclusivo"

        #loss estimate (now using soil)
        loss_estimate = self._estimate_yield_loss(
            copernicus_data,
            poseidon_summary,
            phase_info,
            hist_baseline or {},
            soil_data or {},
        )

        verdict = (
            "CONFIRMADO"    if confidence >= 65 else
            "INCONCLUSIVO"  if confidence >= 40 else
            "NÃO CONFIRMADO"
        )

        checks_passed = sum(1 for c in self._checks if c.get("weight", 0) > 0 and c["passed"])
        checks_total  = sum(1 for c in self._checks if c.get("weight", 0) > 0)
        pct_criteria  = round(checks_passed / checks_total * 100) if checks_total else 0

        return {
            "verdict":       verdict,
            "confidence":    confidence,
            "severity":      severity,
            "idw_score":     idw_score,
            "checks":        self._checks,
            "phase_info":    phase_info,
            "soil_check":    soil_check,
            "loss_estimate": loss_estimate,
            "summary": {
                "checks_passed": checks_passed,
                "checks_total":  checks_total,
                "pct_criteria":  pct_criteria,
                "score_raw":     f"{achieved:.1f}/{total_weight:.1f}",
                "pct_score":     f"{pct_passed:.0f}%",
            },
        }

    #satellite checks
    def _check_satellite(self, cop: Dict) -> None:
        sat_thresh = self.thresholds.get("satellite", {})

        if "NDVI" in cop and "anomaly_pct" in cop["NDVI"] and cop["NDVI"]["anomaly_pct"] is not None:
            drop = -cop["NDVI"]["anomaly_pct"]
            req  = sat_thresh.get("ndvi_drop_pct", 25)
            self._checks.append({
                "name":   "NDVI — queda de vigor vegetativo",
                "passed": drop >= req,
                "weight": 3.0,
                "value":  f"Queda de {drop:.1f}% (mínimo esperado: {req}%)",
                "detail": f"Baseline: {cop['NDVI'].get('baseline_mean','N/A')} → Evento: {cop['NDVI'].get('event_mean','N/A')}",
            })

        if "NDWI" in cop and cop["NDWI"].get("event_mean") is not None:
            val  = cop["NDWI"]["event_mean"]
            req  = sat_thresh.get("ndwi_threshold", -0.05 if self.event_type == "seca" else 0.20)
            cond = val < req if self.event_type == "seca" else val > req
            self._checks.append({
                "name":   "NDWI — status hídrico da vegetação",
                "passed": cond,
                "weight": 2.5,
                "value":  f"NDWI evento: {val:.4f} (limiar: {req})",
                "detail": f"Baseline: {cop['NDWI'].get('baseline_mean','N/A')}",
            })

        if "NDMI" in cop and cop["NDMI"].get("event_mean") is not None:
            val  = cop["NDMI"]["event_mean"]
            req  = sat_thresh.get("ndmi_threshold", -0.10)
            cond = val < req if self.event_type == "seca" else val > 0.10
            self._checks.append({
                "name":   "NDMI — umidade no dossel (SWIR)",
                "passed": cond,
                "weight": 2.0,
                "value":  f"NDMI evento: {val:.4f} (limiar: {req})",
                "detail": "Detecta déficit hídrico no tecido vegetal via infravermelho médio",
            })

        if "NDRE" in cop and cop["NDRE"].get("anomaly_pct") is not None:
            drop = -cop["NDRE"]["anomaly_pct"]
            req  = sat_thresh.get("ndre_drop_pct", 25)
            self._checks.append({
                "name":   "NDRE — estresse precoce (red-edge)",
                "passed": drop >= req,
                "weight": 2.0,
                "value":  f"Queda de {drop:.1f}% no NDRE",
                "detail": "Detecta alterações clorofilicas 2–3 semanas antes do NDVI",
            })

        if "BSI" in cop and cop["BSI"].get("anomaly_abs") is not None:
            delta = cop["BSI"]["anomaly_abs"]
            req   = sat_thresh.get("bsi_increase", 0.05)
            self._checks.append({
                "name":   "BSI — aumento de solo exposto",
                "passed": delta >= req,
                "weight": 1.5,
                "value":  f"BSI +{delta:.4f} (limiar: +{req})",
                "detail": "Indica falha de stand, erosão ou morte de plantas",
            })

        if "VHI" in cop and cop["VHI"].get("event_mean") is not None:
            vhi = cop["VHI"]["event_mean"]
            req = sat_thresh.get("vhi_critical", 40.0)
            self._checks.append({
                "name":   "VHI — índice de saúde da vegetação",
                "passed": vhi < req,
                "weight": 2.5,
                "value":  f"VHI: {vhi:.1f} ({'CRÍTICO 🔴' if vhi < 35 else 'BAIXO ⚠️' if vhi < req else 'NORMAL ✅'})",
                "detail": f"VCI: {cop['VHI'].get('vci','N/A')} | TCI: {cop['VHI'].get('tci','N/A')}",
            })

        if "NBR" in cop and cop["NBR"].get("anomaly_pct") is not None:
            drop = -cop["NBR"]["anomaly_pct"]
            self._checks.append({
                "name":   "NBR — dano severo / queima de tecido",
                "passed": drop >= sat_thresh.get("nbr_drop_pct", 15),
                "weight": 1.5,
                "value":  f"NBR queda de {drop:.1f}%",
                "detail": "Detecta danos severos por calor, seca ou fogo",
            })

        if "PSRI" in cop and cop["PSRI"].get("anomaly_abs") is not None:
            delta = cop["PSRI"]["anomaly_abs"]
            req   = sat_thresh.get("psri_increase", 0.05)
            self._checks.append({
                "name":   "PSRI — senescência vegetal acelerada",
                "passed": delta >= req,
                "weight": 1.5,
                "value":  f"PSRI Δ{delta:+.4f}",
                "detail": "Detecta degradação celular e morte precoce do tecido vegetal",
            })

        if "EVI" in cop and cop["EVI"].get("anomaly_pct") is not None:
            drop = -cop["EVI"]["anomaly_pct"]
            self._checks.append({
                "name":   "EVI — confirmação em alta biomassa",
                "passed": drop >= 20,
                "weight": 1.0,
                "value":  f"EVI queda {drop:.1f}%",
                "detail": "Enhanced Vegetation Index — robusto em alta densidade de copa",
            })

    #checks Poseidon
    def _check_poseidon_vote(self, vote: Dict) -> None:
        w_score      = vote.get("weighted_score", 0.0)
        signal_level = vote.get("signal_level", "desconhecido")
        passed       = vote.get("passed", False)

        self._checks.append({
            "name":   f"Sinal climático Poseidon — score IDW {w_score:.0f}/100 ({signal_level})",
            "passed": passed,
            "weight": 2.5,
            "value":  vote.get("description", "N/A"),
            "detail": "; ".join(
                f"{d}: {v.get('reason','N/A')}"
                for d, v in vote.get("votes", {}).items()
            ),
        })

    def _check_poseidon_summary(self, summary: Dict) -> None:
        if not summary:
            return
        pos_thresh = self.thresholds.get("poseidon", {})

        if self.event_type == "seca":
            total_prcp  = summary.get("prcp_total_mm")
            period_days = summary.get("period_days", 30)
            if total_prcp is not None:
                months      = period_days / 30
                mid_month   = self.start_date.month
                normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
                pct         = total_prcp / normal_prcp * 100 if normal_prcp else 100
                req         = pos_thresh.get("prcp_deficit_pct", 40)
                self._checks.append({
                    "name":   "Poseidon — precipitação acumulada vs normal",
                    "passed": pct < req,
                    "weight": 3.0,
                    "value":  f"{total_prcp:.1f} mm ({pct:.0f}% do normal {normal_prcp:.0f} mm)",
                    "detail": f"Limiar de seca: < {req}% do normal histórico",
                })
            tavg = summary.get("tavg_mean_c")
            if tavg is not None:
                mid_month   = self.start_date.month
                normal_tavg = CLIMATE_NORMALS_RS.get(mid_month, {}).get("tavg_c", 22)
                anomaly     = tavg - normal_tavg
                req         = pos_thresh.get("tavg_anomaly_c", 2.0)
                self._checks.append({
                    "name":   "Poseidon — anomalia positiva de temperatura",
                    "passed": anomaly > req,
                    "weight": 2.0,
                    "value":  f"Tméd: {tavg:.1f}°C | Anomalia: {anomaly:+.1f}°C (limiar: >{req}°C)",
                    "detail": f"Normal climatológica: {normal_tavg:.1f}°C",
                })

        elif self.event_type == "chuva":
            total_prcp  = summary.get("prcp_total_mm")
            period_days = summary.get("period_days", 30)
            if total_prcp is not None:
                months      = period_days / 30
                mid_month   = self.start_date.month
                normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
                pct         = total_prcp / normal_prcp * 100 if normal_prcp else 100
                req         = pos_thresh.get("prcp_excess_pct", 150)
                self._checks.append({
                    "name":   "Poseidon — excesso de precipitação",
                    "passed": pct > req,
                    "weight": 3.0,
                    "value":  f"{total_prcp:.1f} mm ({pct:.0f}% do normal)",
                    "detail": f"Limiar de chuva excessiva: > {req}% do normal",
                })

        elif self.event_type == "geada":
            tmin_abs = summary.get("tmin_abs_c")
            req      = pos_thresh.get("tmin_threshold", 2.0)
            if tmin_abs is not None:
                self._checks.append({
                    "name":   "Poseidon — temperatura mínima absoluta",
                    "passed": tmin_abs < req,
                    "weight": 3.0,
                    "value":  f"Tmin absoluta: {tmin_abs:.2f}°C (limiar: < {req}°C)",
                    "detail": "Temperatura de ponto de congelamento de tecidos vegetais",
                })

    def _check_cross_consistency(self, cop: Dict, summary: Dict) -> None:
        if not summary or not cop:
            return
        ndvi_drop = None
        if "NDVI" in cop and cop["NDVI"].get("anomaly_pct") is not None:
            ndvi_drop = -cop["NDVI"]["anomaly_pct"]
        prcp = summary.get("prcp_total_mm")
        if ndvi_drop is not None and prcp is not None:
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110)
            prcp_pct    = prcp / normal_prcp * 100 if normal_prcp else 100
            if self.event_type == "seca":
                consistent = ndvi_drop > 10 and prcp_pct < 80
            elif self.event_type == "chuva":
                consistent = ndvi_drop > 5 and prcp_pct > 120
            else:
                consistent = ndvi_drop > 10
            self._checks.append({
                "name":   "Consistência cruzada satélite ↔ estação meteorológica",
                "passed": consistent,
                "weight": 2.0,
                "value":  f"NDVI {'-' if ndvi_drop and ndvi_drop>0 else '+'}{abs(ndvi_drop or 0):.1f}% | Prcp {prcp_pct:.0f}% do normal",
                "detail": "Verifica coerência entre anomalia satelital e registro climático",
            })

    def _check_crop_phase(self) -> Dict:
        if not self.planting_date:
            return {"phase": "desconhecida", "sensitivity": 0.5, "description": "Data de plantio não informada"}
        event_mid  = self.start_date + (self.end_date - self.start_date) / 2
        days_after = (event_mid - self.planting_date).days
        crop_p     = self.crop_params
        for phase_name, (d_start, d_end) in crop_p.get("critical_phases", {}).items():
            if d_start <= days_after <= d_end:
                sensitivity = crop_p["yield_loss_factor"].get(phase_name, 0.5)
                self._checks.append({
                    "name":   f"Fase fenológica crítica: {phase_name.upper()}",
                    "passed": True,
                    "weight": 0.0,
                    "value":  f"{days_after} DAP — fase: {phase_name} (sensibilidade: {sensitivity*100:.0f}%)",
                    "detail": "Quanto maior a sensibilidade, maior o impacto no rendimento final",
                })
                return {
                    "phase":            phase_name,
                    "days_after_plant": days_after,
                    "sensitivity":      sensitivity,
                    "description":      f"{phase_name} ({d_start}–{d_end} DAP)",
                }
        return {
            "phase":       "fora do ciclo",
            "sensitivity": 0.1,
            "description": f"{days_after} DAP — fora das fases catalogadas",
        }

    #check the soil
    def _check_soil(self, soil_data: Dict) -> Dict:
        """
        Avalia aptidão do solo para o evento declarado.
        Retorna dict com resultado e, se pertinente, adiciona check à lista.
        """
        if not soil_data or soil_data.get("error"):
            return {"available": False, "error": soil_data.get("error", "Dados de solo indisponíveis")}

        dominant_class = soil_data.get("dominant_class")
        suitable       = soil_data.get("suitable_for_agriculture", True)
        water_props    = soil_data.get("water_props", SOIL_WATER_PROPERTIES["default"])
        retencao       = water_props.get("retencao", "média")
        awc            = water_props.get("AWC", 100)
        ks             = water_props.get("Ks", 20)
        apt_label      = soil_data.get("aptitude_label", "N/D")
        soil_name      = soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D")
        dom_pct        = soil_data.get("dominant_percentage", 0)

        #agricultural fitness check
        self._checks.append({
            "name":   f"Aptidão do Solo EMBRAPA — Classe {dominant_class} ({apt_label})",
            "passed": suitable,
            "weight": 1.0,
            "value":  f"{soil_name} ({dom_pct:.0f}% da área) — {'APTA' if suitable else 'INAPTA'} para lavouras",
            "detail": soil_data.get("aptitude_description", ""),
        })

        #soil vulnerability check for the declared event.
        amplifier_map = SOIL_EVENT_AMPLIFIER.get(self.event_type, {})
        amplifier     = amplifier_map.get(retencao, 1.0)

        if self.event_type == "seca":
            vulnerable = retencao in ("muito baixa", "baixa", "média-baixa")
            risk_label = (
                f"Solo com baixa retenção hídrica (AWC={awc} mm/m) — "
                f"{'amplifica déficit hídrico' if vulnerable else 'retenção adequada'}"
            )
            self._checks.append({
                "name":   "Solo — vulnerabilidade à seca",
                "passed": vulnerable,
                "weight": 1.5,
                "value":  f"AWC={awc} mm/m | Retenção: {retencao} | Fator de amplificação: {amplifier:.2f}x",
                "detail": risk_label,
            })

        elif self.event_type == "chuva":
            vulnerable = retencao in ("alta", "muito alta") or ks < 5
            risk_label = (
                f"Solo com alta retenção / baixa drenagem (Ks={ks} mm/h) — "
                f"{'risco de encharcamento' if vulnerable else 'drenagem adequada'}"
            )
            self._checks.append({
                "name":   "Solo — risco de encharcamento",
                "passed": vulnerable,
                "weight": 1.5,
                "value":  f"Ks={ks} mm/h | Retenção: {retencao} | Fator de amplificação: {amplifier:.2f}x",
                "detail": risk_label,
            })

        elif self.event_type == "geada":
            #moist/heavy soils offer greater protection against frost due to latent heat.
            self._checks.append({
                "name":   "Solo — capacidade de tamponamento térmico",
                "passed": retencao in ("alta", "muito alta"),
                "weight": 0.5,
                "value":  f"Textura: {water_props.get('textura','N/D')} | Retenção: {retencao}",
                "detail": "Solos mais úmidos liberam calor latente que pode atenuar geadas leves",
            })

        return {
            "available":       True,
            "soil_name":       soil_name,
            "dominant_class":  dominant_class,
            "suitable":        suitable,
            "apt_label":       apt_label,
            "retencao":        retencao,
            "AWC":             awc,
            "Ks":              ks,
            "amplifier":       amplifier,
            "textura":         water_props.get("textura", "N/D"),
        }

    #loss estimate
    def _estimate_yield_loss(
        self,
        cop:           Dict,
        summary:       Dict,
        phase_info:    Dict,
        hist_baseline: Dict = None,
        soil_data:     Dict = None,
    ) -> Dict:
        crop_p      = self.crop_params
        base_yield  = crop_p["yield_avg_sacas_ha"]
        sensitivity = phase_info.get("sensitivity", 0.5)
        price       = crop_p["price_brl_saca"]
        area        = self.area_ha

        #local history adjustment
        hist_yield_note = None
        if hist_baseline and hist_baseline.get("prcp_mean_mm"):
            hist_prcp   = hist_baseline["prcp_mean_mm"]
            period_days = summary.get("period_days", 90) if summary else 90
            months      = period_days / 30
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
            hist_ratio  = hist_prcp / normal_prcp if normal_prcp else 1.0
            local_yield_est = round(base_yield * min(max(hist_ratio, 0.7), 1.3), 1)
            n_years   = hist_baseline.get("n_years", 0)
            years_str = ", ".join(str(y) for y in hist_baseline.get("years_used", []))
            hist_yield_note = {
                "local_yield_est_sacas_ha": local_yield_est,
                "hist_prcp_mm":  hist_prcp,
                "hist_prcp_std": hist_baseline.get("prcp_std_mm", 0),
                "n_years":       n_years,
                "years_used":    years_str,
                "note": (
                    f"Com base em {n_years} anos anteriores neste ponto Poseidon "
                    f"({years_str}), a produtividade local esperada seria "
                    f"~{local_yield_est:.1f} sc/ha (vs média estadual de {base_yield} sc/ha)."
                ),
            }
            base_yield = local_yield_est

        #climate loss fraction
        climate_loss_frac = 0.0
        if self.event_type == "seca" and summary:
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
            total_prcp  = summary.get("prcp_total_mm", normal_prcp)
            deficit_pct = max(0, (normal_prcp - total_prcp) / normal_prcp) if normal_prcp else 0
            climate_loss_frac = min(deficit_pct * 0.8, 0.8)
        elif self.event_type == "chuva" and summary:
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
            total_prcp  = summary.get("prcp_total_mm", normal_prcp)
            excess_pct  = max(0, (total_prcp - normal_prcp) / normal_prcp) if normal_prcp else 0
            climate_loss_frac = min(excess_pct * 0.5, 0.6)
        elif self.event_type == "geada":
            climate_loss_frac = 0.50
        elif self.event_type == "granizo":
            climate_loss_frac = 0.45

        #satellite Loss Fraction (NDVI)
        ndvi_loss_frac = 0.0
        if "NDVI" in cop and cop["NDVI"].get("anomaly_pct") is not None:
            ndvi_drop      = -cop["NDVI"]["anomaly_pct"] / 100
            ndvi_loss_frac = max(0, ndvi_drop * 0.9)

        #weighted average + phenological sensitivity
        raw_loss_frac   = 0.40 * climate_loss_frac + 0.60 * ndvi_loss_frac
        final_loss_frac = min(raw_loss_frac * sensitivity * 2.0, 0.95)

        #soil amplification factor
        soil_amplifier = 1.0
        soil_amp_note  = None
        if soil_data and not soil_data.get("error"):
            water_props    = soil_data.get("water_props", {})
            retencao       = water_props.get("retencao", "média")
            amp_map        = SOIL_EVENT_AMPLIFIER.get(self.event_type, {})
            soil_amplifier = amp_map.get(retencao, 1.0)
            final_loss_frac = min(final_loss_frac * soil_amplifier, 0.95)
            soil_amp_note  = {
                "retencao":      retencao,
                "amplifier":     soil_amplifier,
                "soil_name":     soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D"),
                "AWC":           water_props.get("AWC", "N/D"),
            }

        expected_yield   = base_yield
        actual_yield_est = round(expected_yield * (1 - final_loss_frac), 1)
        yield_loss_sacas = round((expected_yield - actual_yield_est) * area, 0)
        expected_revenue = round(expected_yield * area * price, 2)
        actual_revenue   = round(actual_yield_est * area * price, 2)
        financial_loss   = round(expected_revenue - actual_revenue, 2)

        return {
            "expected_yield_sacas_ha":   base_yield,
            "estimated_yield_sacas_ha":  actual_yield_est,
            "yield_loss_pct":            round(final_loss_frac * 100, 1),
            "yield_loss_sacas_ha":       round(base_yield - actual_yield_est, 1),
            "yield_loss_total_sacas":    yield_loss_sacas,
            "area_ha":                   area,
            "price_brl_saca":            price,
            "expected_revenue_brl":      expected_revenue,
            "estimated_revenue_brl":     actual_revenue,
            "financial_loss_brl":        financial_loss,
            "hist_baseline":             hist_yield_note,
            "soil_amplifier":            soil_amp_note,
            "loss_frac_components": {
                "climate_loss":       round(climate_loss_frac * 100, 1),
                "ndvi_loss":          round(ndvi_loss_frac * 100, 1),
                "phase_sensitivity":  round(sensitivity * 100, 0),
                "soil_amplifier":     round(soil_amplifier, 2),
            },
        }
