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
        self.crop_params   = CROP_PARAMS.get(crop_type, CROP_PARAMS["soybean"])
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
        if   idw_score >= 70: severity = "very severe"
        elif idw_score >= 50: severity = "severe"
        elif idw_score >= 35: severity = "moderate"
        elif idw_score >= 20: severity = "weak"
        else:                 severity = "absent / inconclusive"

        #loss estimate (now using soil)
        loss_estimate = self._estimate_yield_loss(
            copernicus_data,
            poseidon_summary,
            phase_info,
            hist_baseline or {},
            soil_data or {},
        )

        verdict = (
            "CONFIRMED"    if confidence >= 65 else
            "INCONCLUSIVE"  if confidence >= 40 else
            "NOT CONFIRMED"
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
                "name":   "NDVI — vegetation vigour drop",
                "passed": drop >= req,
                "weight": 3.0,
                "value":  f"Drop of {drop:.1f}% (minimum expected: {req}%)",
                "detail": f"Baseline: {cop['NDVI'].get('baseline_mean','N/A')} → Event: {cop['NDVI'].get('event_mean','N/A')}",
            })

        if "NDWI" in cop and cop["NDWI"].get("event_mean") is not None:
            val  = cop["NDWI"]["event_mean"]
            req  = sat_thresh.get("ndwi_threshold", -0.05 if self.event_type == "drought" else 0.20)
            cond = val < req if self.event_type == "drought" else val > req
            self._checks.append({
                "name":   "NDWI — canopy water status",
                "passed": cond,
                "weight": 2.5,
                "value":  f"NDWI event: {val:.4f} (threshold: {req})",
                "detail": f"Baseline: {cop['NDWI'].get('baseline_mean','N/A')}",
            })

        if "NDMI" in cop and cop["NDMI"].get("event_mean") is not None:
            val  = cop["NDMI"]["event_mean"]
            req  = sat_thresh.get("ndmi_threshold", -0.10)
            cond = val < req if self.event_type == "drought" else val > 0.10
            self._checks.append({
                "name":   "NDMI — canopy moisture (SWIR)",
                "passed": cond,
                "weight": 2.0,
                "value":  f"NDMI event: {val:.4f} (threshold: {req})",
                "detail": "Detects water deficit in plant tissue via mid-infrared",
            })

        if "NDRE" in cop and cop["NDRE"].get("anomaly_pct") is not None:
            drop = -cop["NDRE"]["anomaly_pct"]
            req  = sat_thresh.get("ndre_drop_pct", 25)
            self._checks.append({
                "name":   "NDRE — early stress (red-edge)",
                "passed": drop >= req,
                "weight": 2.0,
                "value":  f"Drop of {drop:.1f}% in NDRE",
                "detail": "Detects chlorophyll changes 2–3 weeks before NDVI",
            })

        if "BSI" in cop and cop["BSI"].get("anomaly_abs") is not None:
            delta = cop["BSI"]["anomaly_abs"]
            req   = sat_thresh.get("bsi_increase", 0.05)
            self._checks.append({
                "name":   "BSI — increase in bare soil",
                "passed": delta >= req,
                "weight": 1.5,
                "value":  f"BSI +{delta:.4f} (threshold: +{req})",
                "detail": "Indicates stand failure, erosion or plant death",
            })

        if "VHI" in cop and cop["VHI"].get("event_mean") is not None:
            vhi = cop["VHI"]["event_mean"]
            req = sat_thresh.get("vhi_critical", 40.0)
            self._checks.append({
                "name":   "VHI — vegetation health index",
                "passed": vhi < req,
                "weight": 2.5,
                "value":  f"VHI: {vhi:.1f} ({'CRITICAL 🔴' if vhi < 35 else 'LOW ⚠️' if vhi < req else 'NORMAL ✅'})",
                "detail": f"VCI: {cop['VHI'].get('vci','N/A')} | TCI: {cop['VHI'].get('tci','N/A')}",
            })

        if "NBR" in cop and cop["NBR"].get("anomaly_pct") is not None:
            drop = -cop["NBR"]["anomaly_pct"]
            self._checks.append({
                "name":   "NBR — severe damage / tissue burn",
                "passed": drop >= sat_thresh.get("nbr_drop_pct", 15),
                "weight": 1.5,
                "value":  f"NBR drop of {drop:.1f}%",
                "detail": "Detects severe damage from heat, drought or fire",
            })

        if "PSRI" in cop and cop["PSRI"].get("anomaly_abs") is not None:
            delta = cop["PSRI"]["anomaly_abs"]
            req   = sat_thresh.get("psri_increase", 0.05)
            self._checks.append({
                "name":   "PSRI — accelerated plant senescence",
                "passed": delta >= req,
                "weight": 1.5,
                "value":  f"PSRI Δ{delta:+.4f}",
                "detail": "Detects cellular degradation and premature plant tissue death",
            })

        if "EVI" in cop and cop["EVI"].get("anomaly_pct") is not None:
            drop = -cop["EVI"]["anomaly_pct"]
            self._checks.append({
                "name":   "EVI — high-biomass confirmation",
                "passed": drop >= 20,
                "weight": 1.0,
                "value":  f"EVI drop {drop:.1f}%",
                "detail": "Enhanced Vegetation Index — robust under high canopy density",
            })

    #checks Poseidon
    def _check_poseidon_vote(self, vote: Dict) -> None:
        w_score      = vote.get("weighted_score", 0.0)
        signal_level = vote.get("signal_level", "unknown")
        passed       = vote.get("passed", False)

        self._checks.append({
            "name":   f"Poseidon climate signal — IDW score {w_score:.0f}/100 ({signal_level})",
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

        if self.event_type == "drought":
            total_prcp  = summary.get("prcp_total_mm")
            period_days = summary.get("period_days", 30)
            if total_prcp is not None:
                months      = period_days / 30
                mid_month   = self.start_date.month
                normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
                pct         = total_prcp / normal_prcp * 100 if normal_prcp else 100
                req         = pos_thresh.get("prcp_deficit_pct", 40)
                self._checks.append({
                    "name":   "Poseidon — cumulative precipitation vs normal",
                    "passed": pct < req,
                    "weight": 3.0,
                    "value":  f"{total_prcp:.1f} mm ({pct:.0f}% of normal {normal_prcp:.0f} mm)",
                    "detail": f"Drought threshold: < {req}% of historical normal",
                })
            tavg = summary.get("tavg_mean_c")
            if tavg is not None:
                mid_month   = self.start_date.month
                normal_tavg = CLIMATE_NORMALS_RS.get(mid_month, {}).get("tavg_c", 22)
                anomaly     = tavg - normal_tavg
                req         = pos_thresh.get("tavg_anomaly_c", 2.0)
                self._checks.append({
                    "name":   "Poseidon — positive temperature anomaly",
                    "passed": anomaly > req,
                    "weight": 2.0,
                    "value":  f"Tmean: {tavg:.1f}°C | Anomaly: {anomaly:+.1f}°C (threshold: >{req}°C)",
                    "detail": f"Climatological normal: {normal_tavg:.1f}°C",
                })

        elif self.event_type == "rainfall":
            total_prcp  = summary.get("prcp_total_mm")
            period_days = summary.get("period_days", 30)
            if total_prcp is not None:
                months      = period_days / 30
                mid_month   = self.start_date.month
                normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
                pct         = total_prcp / normal_prcp * 100 if normal_prcp else 100
                req         = pos_thresh.get("prcp_excess_pct", 150)
                self._checks.append({
                    "name":   "Poseidon — excess precipitation",
                    "passed": pct > req,
                    "weight": 3.0,
                    "value":  f"{total_prcp:.1f} mm ({pct:.0f}% of normal)",
                    "detail": f"Excess rainfall threshold: > {req}% of normal",
                })

        elif self.event_type == "frost":
            tmin_abs = summary.get("tmin_abs_c")
            req      = pos_thresh.get("tmin_threshold", 2.0)
            if tmin_abs is not None:
                self._checks.append({
                    "name":   "Poseidon — absolute minimum temperature",
                    "passed": tmin_abs < req,
                    "weight": 3.0,
                    "value":  f"Absolute Tmin: {tmin_abs:.2f}°C (threshold: < {req}°C)",
                    "detail": "Freezing point temperature of plant tissue",
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
            if self.event_type == "drought":
                consistent = ndvi_drop > 10 and prcp_pct < 80
            elif self.event_type == "rainfall":
                consistent = ndvi_drop > 5 and prcp_pct > 120
            else:
                consistent = ndvi_drop > 10
            self._checks.append({
                "name":   "Cross-consistency satellite ↔ weather station",
                "passed": consistent,
                "weight": 2.0,
                "value":  f"NDVI {'-' if ndvi_drop and ndvi_drop>0 else '+'}{abs(ndvi_drop or 0):.1f}% | Prcp {prcp_pct:.0f}% of normal",
                "detail": "Checks consistency between satellite anomaly and climate record",
            })

    def _check_crop_phase(self) -> Dict:
        if not self.planting_date:
            return {"phase": "unknown", "sensitivity": 0.5, "description": "Planting date not provided"}
        event_mid  = self.start_date + (self.end_date - self.start_date) / 2
        days_after = (event_mid - self.planting_date).days
        crop_p     = self.crop_params
        for phase_name, (d_start, d_end) in crop_p.get("critical_phases", {}).items():
            if d_start <= days_after <= d_end:
                sensitivity = crop_p["yield_loss_factor"].get(phase_name, 0.5)
                self._checks.append({
                    "name":   f"Critical phenological phase: {phase_name.upper()}",
                    "passed": True,
                    "weight": 0.0,
                    "value":  f"{days_after} DAP — phase: {phase_name} (sensitivity: {sensitivity*100:.0f}%)",
                    "detail": "Higher sensitivity means greater impact on final yield",
                })
                return {
                    "phase":            phase_name,
                    "days_after_plant": days_after,
                    "sensitivity":      sensitivity,
                    "description":      f"{phase_name} ({d_start}–{d_end} DAP)",
                }
        return {
            "phase":       "outside cycle",
            "sensitivity": 0.1,
            "description": f"{days_after} DAP — outside catalogued phases",
        }

    #check the soil
    def _check_soil(self, soil_data: Dict) -> Dict:
        """
        Evaluates soil suitability for the declared event.
        Returns a dict with the result and, where relevant, appends a check to the list.
        """
        if not soil_data or soil_data.get("error"):
            return {"available": False, "error": soil_data.get("error", "Soil data unavailable")}

        dominant_class = soil_data.get("dominant_class")
        suitable       = soil_data.get("suitable_for_agriculture", True)
        water_props    = soil_data.get("water_props", SOIL_WATER_PROPERTIES["default"])
        retention      = water_props.get("retention", "medium")
        awc            = water_props.get("AWC", 100)
        ks             = water_props.get("Ks", 20)
        apt_label      = soil_data.get("aptitude_label", "N/D")
        soil_name      = soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D")
        dom_pct        = soil_data.get("dominant_percentage", 0)

        #agricultural fitness check
        self._checks.append({
            "name":   f"EMBRAPA Soil Suitability — Class {dominant_class} ({apt_label})",
            "passed": suitable,
            "weight": 1.0,
            "value":  f"{soil_name} ({dom_pct:.0f}% of area) — {'SUITABLE' if suitable else 'UNSUITABLE'} for crops",
            "detail": soil_data.get("aptitude_description", ""),
        })

        #soil vulnerability check for the declared event.
        amplifier_map = SOIL_EVENT_AMPLIFIER.get(self.event_type, {})
        amplifier     = amplifier_map.get(retention, 1.0)

        if self.event_type == "drought":
            vulnerable = retention in ("very low", "low", "medium-low")
            risk_label = (
                f"Low water-retention soil (AWC={awc} mm/m) — "
                f"{'amplifies water deficit' if vulnerable else 'adequate retention'}"
            )
            self._checks.append({
                "name":   "Soil — drought vulnerability",
                "passed": vulnerable,
                "weight": 1.5,
                "value":  f"AWC={awc} mm/m | Retention: {retention} | Amplification factor: {amplifier:.2f}x",
                "detail": risk_label,
            })

        elif self.event_type == "rainfall":
            vulnerable = retention in ("high", "very high") or ks < 5
            risk_label = (
                f"High-retention / low-drainage soil (Ks={ks} mm/h) — "
                f"{'waterlogging risk' if vulnerable else 'adequate drainage'}"
            )
            self._checks.append({
                "name":   "Soil — waterlogging risk",
                "passed": vulnerable,
                "weight": 1.5,
                "value":  f"Ks={ks} mm/h | Retention: {retention} | Amplification factor: {amplifier:.2f}x",
                "detail": risk_label,
            })

        elif self.event_type == "frost":
            #moist/heavy soils offer greater protection against frost due to latent heat.
            self._checks.append({
                "name":   "Soil — thermal buffering capacity",
                "passed": retention in ("high", "very high"),
                "weight": 0.5,
                "value":  f"Texture: {water_props.get('texture','N/D')} | Retention: {retention}",
                "detail": "Wetter soils release latent heat that can buffer light frosts",
            })

        return {
            "available":       True,
            "soil_name":       soil_name,
            "dominant_class":  dominant_class,
            "suitable":        suitable,
            "apt_label":       apt_label,
            "retention":       retention,
            "AWC":             awc,
            "Ks":              ks,
            "amplifier":       amplifier,
            "texture":         water_props.get("texture", "N/D"),
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
        base_yield  = crop_p["yield_avg_bags_ha"]
        sensitivity = phase_info.get("sensitivity", 0.5)
        price       = crop_p["price_brl_bag"]
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
                "local_yield_est_bags_ha": local_yield_est,
                "hist_prcp_mm":  hist_prcp,
                "hist_prcp_std": hist_baseline.get("prcp_std_mm", 0),
                "n_years":       n_years,
                "years_used":    years_str,
                "note": (
                    f"Based on {n_years} previous years at this Poseidon point "
                    f"({years_str}), expected local yield would be "
                    f"~{local_yield_est:.1f} bags/ha (vs state average of {base_yield} bags/ha)."
                ),
            }
            base_yield = local_yield_est

        #climate loss fraction
        climate_loss_frac = 0.0
        if self.event_type == "drought" and summary:
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
            total_prcp  = summary.get("prcp_total_mm", normal_prcp)
            deficit_pct = max(0, (normal_prcp - total_prcp) / normal_prcp) if normal_prcp else 0
            climate_loss_frac = min(deficit_pct * 0.8, 0.8)
        elif self.event_type == "rainfall" and summary:
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
            total_prcp  = summary.get("prcp_total_mm", normal_prcp)
            excess_pct  = max(0, (total_prcp - normal_prcp) / normal_prcp) if normal_prcp else 0
            climate_loss_frac = min(excess_pct * 0.5, 0.6)
        elif self.event_type == "frost":
            climate_loss_frac = 0.50
        elif self.event_type == "hail":
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
            retention      = water_props.get("retention", "medium")
            amp_map        = SOIL_EVENT_AMPLIFIER.get(self.event_type, {})
            soil_amplifier = amp_map.get(retention, 1.0)
            final_loss_frac = min(final_loss_frac * soil_amplifier, 0.95)
            soil_amp_note  = {
                "retention":     retention,
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
            "expected_yield_bags_ha":   base_yield,
            "estimated_yield_bags_ha":  actual_yield_est,
            "yield_loss_pct":            round(final_loss_frac * 100, 1),
            "yield_loss_bags_ha":       round(base_yield - actual_yield_est, 1),
            "yield_loss_total_bags":    yield_loss_sacas,
            "area_ha":                   area,
            "price_brl_bag":             price,
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
        }"""
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
        if   idw_score >= 70: severity = "Very Severe"
        elif idw_score >= 50: severity = "Severe"
        elif idw_score >= 35: severity = "Moderate"
        elif idw_score >= 20: severity = "Weak"
        else:                 severity = "Absent / Inconclusive"

        #loss estimate (now using soil)
        loss_estimate = self._estimate_yield_loss(
            copernicus_data,
            poseidon_summary,
            phase_info,
            hist_baseline or {},
            soil_data or {},
        )

        verdict = (
            "CONFIRMED"   if confidence >= 65 else
            "INCONCLUSIVE"  if confidence >= 40 else
            "NOT CONFIRMED"
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
                "name":   "NDVI — decline in vegetative vigor",
                "passed": drop >= req,
                "weight": 3.0,
                "value":  f"decline of {drop:.1f}% (minimum expected: {req}%)",
                "detail": f"Baseline: {cop['NDVI'].get('baseline_mean','N/A')} → Event: {cop['NDVI'].get('event_mean','N/A')}",
            })

        if "NDWI" in cop and cop["NDWI"].get("event_mean") is not None:
            val  = cop["NDWI"]["event_mean"]
            req  = sat_thresh.get("ndwi_threshold", -0.05 if self.event_type == "drought" else 0.20)
            cond = val < req if self.event_type == "drought" else val > req
            self._checks.append({
                "name":   "NDWI — vegetation water status",
                "passed": cond,
                "weight": 2.5,
                "value":  f"NDWI event: {val:.4f} (threshold: {req})",
                "detail": f"Baseline: {cop['NDWI'].get('baseline_mean','N/A')}",
            })

        if "NDMI" in cop and cop["NDMI"].get("event_mean") is not None:
            val  = cop["NDMI"]["event_mean"]
            req  = sat_thresh.get("ndmi_threshold", -0.10)
            cond = val < req if self.event_type == "drought" else val > 0.10
            self._checks.append({
                "name":   "NDMI — vegetation moisture (SWIR)",
                "passed": cond,
                "weight": 2.0,
                "value":  f"NDMI event: {val:.4f} (threshold: {req})",
                "detail": "Detects water deficit in the vegetative tissue via medium infrared reflectance",
            })

        if "NDRE" in cop and cop["NDRE"].get("anomaly_pct") is not None:
            drop = -cop["NDRE"]["anomaly_pct"]
            req  = sat_thresh.get("ndre_drop_pct", 25)
            self._checks.append({
                "name":   "NDRE — early stress (red-edge)",
                "passed": drop >= req,
                "weight": 2.0,
                "value":  f"decline of {drop:.1f}% in NDRE",
                "detail": "Detects chlorophyll changes 2–3 weeks before NDVI",
            })

        if "BSI" in cop and cop["BSI"].get("anomaly_abs") is not None:
            delta = cop["BSI"]["anomaly_abs"]
            req   = sat_thresh.get("bsi_increase", 0.05)
            self._checks.append({
                "name":   "BSI — exposed soil increase",
                "passed": delta >= req,
                "weight": 1.5,
                "value":  f"BSI +{delta:.4f} (threshold: +{req})",
                "detail": "Indicates stand failure, erosion, or plant mortality",
            })

        if "VHI" in cop and cop["VHI"].get("event_mean") is not None:
            vhi = cop["VHI"]["event_mean"]
            req = sat_thresh.get("vhi_critical", 40.0)
            self._checks.append({
                "name":   "VHI — vegetation health index",  
                "passed": vhi < req,
                "weight": 2.5,
                "value":  f"VHI: {vhi:.1f} ({'CRITICAL 🔴' if vhi < 35 else 'LOW ⚠️' if vhi < req else 'NORMAL ✅'})",
                "detail": f"VCI: {cop['VHI'].get('vci','N/A')} | TCI: {cop['VHI'].get('tci','N/A')}",
            })

        if "NBR" in cop and cop["NBR"].get("anomaly_pct") is not None:
            drop = -cop["NBR"]["anomaly_pct"]
            self._checks.append({
                "name":   "NBR — severe damage / tissue burning",
                "passed": drop >= sat_thresh.get("nbr_drop_pct", 15),
                "weight": 1.5,
                "value":  f"NBR decline of {drop:.1f}%",
                "detail": "Detects severe damage by heat, drought or fire",
            })

        if "PSRI" in cop and cop["PSRI"].get("anomaly_abs") is not None:
            delta = cop["PSRI"]["anomaly_abs"]
            req   = sat_thresh.get("psri_increase", 0.05)
            self._checks.append({
                "name":   "PSRI — accelerated plant senescence",
                "passed": delta >= req,
                "weight": 1.5,
                "value":  f"PSRI Δ{delta:+.4f}",
                "detail": "Detects cellular degradation and premature death of plant tissue",
            })

        if "EVI" in cop and cop["EVI"].get("anomaly_pct") is not None:
            drop = -cop["EVI"]["anomaly_pct"]
            self._checks.append({
                "name":   "EVI — confirmation in high biomass",
                "passed": drop >= 20,
                "weight": 1.0,
                "value":  f"EVI decline {drop:.1f}%",
                "detail": "Enhanced Vegetation Index — robust in high canopy density",
            })

    #checks Poseidon
    def _check_poseidon_vote(self, vote: Dict) -> None:
        w_score      = vote.get("weighted_score", 0.0)
        signal_level = vote.get("signal_level", "unknown")
        passed       = vote.get("passed", False)

        self._checks.append({
            "name":   f"Poseidon climate signal — IDW score {w_score:.0f}/100 ({signal_level})",
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

        if self.event_type == "drought":
            total_prcp  = summary.get("prcp_total_mm")
            period_days = summary.get("period_days", 30)
            if total_prcp is not None:
                months      = period_days / 30
                mid_month   = self.start_date.month
                normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
                pct         = total_prcp / normal_prcp * 100 if normal_prcp else 100
                req         = pos_thresh.get("prcp_deficit_pct", 40)
                self._checks.append({
                    "name":   "Poseidon — accumulated precipitation vs normal",
                    "passed": pct < req,
                    "weight": 3.0,
                    "value":  f"{total_prcp:.1f} mm ({pct:.0f}% of normal {normal_prcp:.0f} mm)",
                    "detail": f"Drought threshold: < {req}% of historical normal",
                })
            tavg = summary.get("tavg_mean_c")
            if tavg is not None:
                mid_month   = self.start_date.month
                normal_tavg = CLIMATE_NORMALS_RS.get(mid_month, {}).get("tavg_c", 22)
                anomaly     = tavg - normal_tavg
                req         = pos_thresh.get("tavg_anomaly_c", 2.0)
                self._checks.append({
                    "name":   "Poseidon — positive temperature anomaly",
                    "passed": anomaly > req,
                    "weight": 2.0,
                    "value":  f"Tméd: {tavg:.1f}°C | Anomalia: {anomaly:+.1f}°C (threshold: >{req}°C)",
                    "detail": f"Climatological normal: {normal_tavg:.1f}°C",
                })

        elif self.event_type == "rain":
            total_prcp  = summary.get("prcp_total_mm")
            period_days = summary.get("period_days", 30)
            if total_prcp is not None:
                months      = period_days / 30
                mid_month   = self.start_date.month
                normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
                pct         = total_prcp / normal_prcp * 100 if normal_prcp else 100
                req         = pos_thresh.get("prcp_excess_pct", 150)
                self._checks.append({
                    "name":   "Poseidon — excess precipitation vs normal",
                    "passed": pct > req,
                    "weight": 3.0,
                    "value":  f"{total_prcp:.1f} mm ({pct:.0f}% of normal)",
                    "detail": f"Excessive rainfall threshold: > {req}% of normal",
                })

        elif self.event_type == "frost":
            tmin_abs = summary.get("tmin_abs_c")
            req      = pos_thresh.get("tmin_threshold", 2.0)
            if tmin_abs is not None:
                self._checks.append({
                    "name":   "Poseidon — absolute minimum temperature",
                    "passed": tmin_abs < req,
                    "weight": 3.0,
                    "value":  f"Tmin absoluta: {tmin_abs:.2f}°C (threshold: < {req}°C)",
                    "detail": "Temperature at which plant tissues freeze",
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
                "name":   "Cross-consistency satellite ↔ meteorological station",
                "passed": consistent,
                "weight": 2.0,
                "value":  f"NDVI {'-' if ndvi_drop and ndvi_drop>0 else '+'}{abs(ndvi_drop or 0):.1f}% | Prcp {prcp_pct:.0f}% of normal",
                "detail": "Checks consistency between satellite anomaly and climate record",
            })

    def _check_crop_phase(self) -> Dict:
        if not self.planting_date:
            return {"phase": "unknown", "sensitivity": 0.5, "description": "Planting date not provided"}
        event_mid  = self.start_date + (self.end_date - self.start_date) / 2
        days_after = (event_mid - self.planting_date).days
        crop_p     = self.crop_params
        for phase_name, (d_start, d_end) in crop_p.get("critical_phases", {}).items():
            if d_start <= days_after <= d_end:
                sensitivity = crop_p["yield_loss_factor"].get(phase_name, 0.5)
                self._checks.append({
                    "name":   f"Critical phenological phase: {phase_name.upper()}",
                    "passed": True,
                    "weight": 0.0,
                    "value":  f"{days_after} DAP — phase: {phase_name} (sensitivity: {sensitivity*100:.0f}%)",
                    "detail": "The higher the sensitivity, the greater the impact on final yield",
                })
                return {
                    "phase":            phase_name,
                    "days_after_plant": days_after,
                    "sensitivity":      sensitivity,
                    "description":      f"{phase_name} ({d_start}–{d_end} DAP)",
                }
        return {
            "phase":       "outside the cycle",
            "sensitivity": 0.1,
            "description": f"{days_after} DAP — outside the cataloged phases",
        }

    #check the soil
    def _check_soil(self, soil_data: Dict) -> Dict:
        """
        Evaluates soil suitability for the declared event.
        Returns a dictionary with the result and, if relevant, adds a checkmark to the list.
        """
        if not soil_data or soil_data.get("error"):
            return {"available": False, "error": soil_data.get("error", "Soil data unavailable.")}

        dominant_class = soil_data.get("dominant_class")
        suitable       = soil_data.get("suitable_for_agriculture", True)
        water_props    = soil_data.get("water_props", SOIL_WATER_PROPERTIES["default"])
        retencao       = water_props.get("retention", "mean")
        awc            = water_props.get("AWC", 100)
        ks             = water_props.get("Ks", 20)
        apt_label      = soil_data.get("aptitude_label", "N/D")
        soil_name      = soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D")
        dom_pct        = soil_data.get("dominant_percentage", 0)

        #agricultural fitness check
        self._checks.append({
            "name":   f"EMBRAPA Soil Suitability — Class {dominant_class} ({apt_label})",
            "passed": suitable,
            "weight": 1.0,
            "value":  f"{soil_name} ({dom_pct:.0f}% of area) — {'Suitable' if suitable else 'Not Suitable'} for agriculture",
            "detail": soil_data.get("aptitude_description", ""),
        })

        #soil vulnerability check for the declared event.
        amplifier_map = SOIL_EVENT_AMPLIFIER.get(self.event_type, {})
        amplifier     = amplifier_map.get(retencao, 1.0)

        if self.event_type == "seca":
            vulnerable = retencao in ("very low", "low", "medium-low")
            risk_label = (
                f"Soil with low water retention (AWC={awc} mm/m) — "
                f"{'amplifies water deficit' if vulnerable else 'adequate retention'}"
            )
            self._checks.append({
                "name":   "Soil — vulnerability to drought",
                "passed": vulnerable,
                "weight": 1.5,
                "value":  f"AWC={awc} mm/m | Retention: {retencao} | Amplification Factor: {amplifier:.2f}x",
                "detail": risk_label,
            })

        elif self.event_type == "rain":
            vulnerable = retencao in ("high", "very high") or ks < 5
            risk_label = (
                f"Soil with high water retention / poor drainage (Ks={ks} mm/h) — "
                f"{'risk of waterlogging' if vulnerable else 'adequate drainage'}"
            )
            self._checks.append({
                "name":   "Soil — risk of waterlogging",
                "passed": vulnerable,
                "weight": 1.5,
                "value":  f"Ks={ks} mm/h | Retention: {retencao} | Amplification Factor: {amplifier:.2f}x",
                "detail": risk_label,
            })

        elif self.event_type == "frost":
            #moist/heavy soils offer greater protection against frost due to latent heat.
            self._checks.append({
                "name":   "Soil — thermal buffering capacity",
                "passed": retencao in ("high", "very high"),
                "weight": 0.5,
                "value":  f"Texture: {water_props.get('textura','N/D')} | Retention: {retencao}",
                "detail": "Soils with higher moisture content release latent heat that can mitigate light frosts",
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
            "textura":         water_props.get("texture", "N/D"),
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
                    f"Based on {n_years} In previous years at this spot, Poseidon "
                    f"({years_str}), the expected local productivity would be "
                    f"~{local_yield_est:.1f} sc/ha (vs média estadual de {base_yield} sc/ha)."
                ),
            }
            base_yield = local_yield_est

        #climate loss fraction
        climate_loss_frac = 0.0
        if self.event_type == "drought" and summary:
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
            total_prcp  = summary.get("prcp_total_mm", normal_prcp)
            deficit_pct = max(0, (normal_prcp - total_prcp) / normal_prcp) if normal_prcp else 0
            climate_loss_frac = min(deficit_pct * 0.8, 0.8)
        elif self.event_type == "rain" and summary:
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            mid_month   = self.start_date.month
            normal_prcp = CLIMATE_NORMALS_RS.get(mid_month, {}).get("prcp_mm", 110) * months
            total_prcp  = summary.get("prcp_total_mm", normal_prcp)
            excess_pct  = max(0, (total_prcp - normal_prcp) / normal_prcp) if normal_prcp else 0
            climate_loss_frac = min(excess_pct * 0.5, 0.6)
        elif self.event_type == "frost":
            climate_loss_frac = 0.50
        elif self.event_type == "hail":
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
            retention       = water_props.get("retention", "média")
            amp_map        = SOIL_EVENT_AMPLIFIER.get(self.event_type, {})
            soil_amplifier = amp_map.get(retention, 1.0)
            final_loss_frac = min(final_loss_frac * soil_amplifier, 0.95)
            soil_amp_note  = {
                "retention":     retention,
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
