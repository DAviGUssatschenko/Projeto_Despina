"""
modules/storyteller.py
Generator of the complete narrative report in English.
Includes EMBRAPA soil data section integrated into the analysis.
"""

from __future__ import annotations
from datetime import date
from typing import Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.rule import Rule
from rich.columns import Columns

from config import CROP_PARAMS, CLIMATE_NORMALS_RS, SOIL_APTITUDE_CLASSES

console = Console()


def _brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _pct(value: float) -> str:
    return f"{value:.1f}%"

def _verdict_color(verdict: str) -> str:
    return {"CONFIRMED": "green", "INCONCLUSIVE": "yellow", "NOT CONFIRMED": "red"}.get(verdict, "white")

def _index_label(name, value, baseline, higher_is_bad=False):
    if value is None:
        return "[dim]N/D[/dim]"
    arrow = color = "white"
    if baseline is not None:
        diff = value - baseline
        if higher_is_bad:
            arrow = "⬆" if diff > 0.01 else "⬇" if diff < -0.01 else "→"
            color = "red" if diff > 0.01 else "green" if diff < -0.01 else "yellow"
        else:
            arrow = "⬆" if diff > 0.01 else "⬇" if diff < -0.01 else "→"
            color = "green" if diff > 0.01 else "red" if diff < -0.01 else "yellow"
    return f"[{color}]{value:.4f} {arrow}[/{color}]"


class StoryTeller:

    INDEX_META = {
        "NDVI":  {"full": "Normalised Difference Vegetation Index",  "higher_is_bad": False},
        "NDRE":  {"full": "NDVI Red-Edge (early stress)",               "higher_is_bad": False},
        "EVI":   {"full": "Enhanced Vegetation Index",                 "higher_is_bad": False},
        "NDWI":  {"full": "Normalised Difference Water Index",                    "higher_is_bad": False},
        "NDMI":  {"full": "Normalised Difference Moisture Index",    "higher_is_bad": False},
        "BSI":   {"full": "Bare Soil Index",                         "higher_is_bad": True},
        "NBR":   {"full": "Normalised Burn Ratio",                    "higher_is_bad": False},
        "PSRI":  {"full": "Plant Senescence Reflectance Index",                  "higher_is_bad": True},
        "CRI1":  {"full": "Carotenoid Reflectance Index",         "higher_is_bad": True},
        "VHI":   {"full": "Vegetation Health Index (VCI+TCI)",         "higher_is_bad": False},
    }

    EVENT_LABELS = {
        "drought":  "Drought / Water Deficit",
        "rainfall": "Excess Rainfall / Flooding",
        "frost":    "Frost",
        "hail":     "Hail / Severe Storm",
    }

    def __init__(
        self,
        event_type:    str,
        crop_type:     str,
        start_date:    date,
        end_date:      date,
        area_ha:       float,
        farm_name:     str = "Rural Property",
        planting_date: Optional[date] = None,
        centroid:      Optional[Dict] = None,
    ):
        self.event_type    = event_type
        self.crop_type     = crop_type
        self.start_date    = start_date
        self.end_date      = end_date
        self.area_ha       = area_ha
        self.farm_name     = farm_name
        self.planting_date = planting_date
        self.centroid      = centroid or {}
        self.crop_params   = CROP_PARAMS.get(crop_type, CROP_PARAMS["soybean"])

    #entry point
    def generate(
        self,
        analysis:         Dict,
        copernicus_data:  Dict,
        poseidon_summary: Dict,
        poseidon_vote:    Dict,
        neighbors:        Dict,
        hist_baseline:    Dict = None,
        soil_data:        Dict = None,
    ) -> None:
        console.print()
        console.print(Rule("[bold cyan]AGRICULTURAL INSURANCE CLAIM VALIDATION SYSTEM[/bold cyan]"))
        console.print(Rule("[dim]Poseidon Climate Network  ✦  Copernicus Sentinel-2  ✦  EMBRAPA Soil[/dim]"))
        console.print()

        self._header_block()
        self._context_narrative()
        self._satellite_section(copernicus_data)
        self._poseidon_section(poseidon_summary, poseidon_vote, neighbors)
        if soil_data and not soil_data.get("error"):
            self._soil_section(soil_data, analysis)
        self._cross_analysis_section(analysis, copernicus_data, poseidon_summary, soil_data)
        self._checks_section(analysis)
        self._loss_section(analysis, hist_baseline or {})
        self._verdict_section(analysis)

    #header
    def _header_block(self) -> None:
        lat = self.centroid.get("lat", "N/D")
        lon = self.centroid.get("lon", "N/D")
        info = Table.grid(padding=(0, 2))
        info.add_column(style="bold cyan",  justify="right")
        info.add_column(style="white")
        info.add_row("📍 Farm",  self.farm_name)
        info.add_row("🌱 Crop",       self.crop_params["name_en"])
        info.add_row("⚠️  Claim",      self.EVENT_LABELS.get(self.event_type, self.event_type))
        info.add_row("📅 Period",        f"{self.start_date.strftime('%d/%m/%Y')} → {self.end_date.strftime('%d/%m/%Y')}")
        info.add_row("📐 Area",           f"{self.area_ha:.1f} hectares")
        info.add_row("📌 Centroid",      f"Lat {lat} | Lon {lon}")
        if self.planting_date:
            info.add_row("🌾 Planting",    self.planting_date.strftime("%d/%m/%Y"))
        console.print(Panel(info, title="[bold]CLAIM IDENTIFICATION[/bold]", border_style="cyan"))
        console.print()

    #context
    def _context_narrative(self) -> None:
        cp        = self.crop_params
        event_lbl = self.EVENT_LABELS.get(self.event_type, self.event_type)
        avg_yield = cp["yield_avg_bags_ha"]
        min_yield = cp["yield_min_bags_ha"]
        max_yield = cp["yield_max_bags_ha"]
        price     = cp["price_brl_bag"]
        area      = self.area_ha
        rev_min   = min_yield * area * price
        rev_max   = max_yield * area * price
        rev_proj  = avg_yield * area * price
        n_days    = (self.end_date - self.start_date).days + 1
        text = (
            f"[bold white]📖  BACKGROUND & CONTEXT[/bold white]\n\n"
            f"[bold]{cp['name_en']}[/bold] crop with historical yield between "
            f"[bold]{min_yield}[/bold] and [bold]{max_yield} bags/ha[/bold], "
            f"historical average of [bold]{avg_yield} bags/ha[/bold].\n\n"
            f"For an area of [bold]{area:.1f} ha[/bold] at a reference price of "
            f"[bold]{_brl(price)}/bag[/bold] (CEPEA reference), expected gross revenue ranges from "
            f"[bold]{_brl(rev_min)}[/bold] to [bold]{_brl(rev_max)}[/bold], "
            f"projected revenue for the current season: [bold]{_brl(rev_proj)}[/bold].\n\n"
            f"The insured alleges [bold red]{event_lbl}[/bold red] between "
            f"[bold]{self.start_date.strftime('%d/%m/%Y')}[/bold] and "
            f"[bold]{self.end_date.strftime('%d/%m/%Y')}[/bold] "
            f"— a period of [bold]{n_days} days[/bold]. "
            f"Satellite and meteorological data are cross-referenced below to "
            f"[bold]confirm or refute[/bold] this claim."
        )
        console.print(Panel(text, border_style="blue"))
        console.print()

    #copernicus
    def _satellite_section(self, cop: Dict) -> None:
        console.print(Rule("[bold yellow]📡  SATELLITE DATA — COPERNICUS / SENTINEL-2[/bold yellow]"))
        console.print()

        tbl = Table(
            title="Spectral Indices — Baseline vs Event Comparison",
            box=box.ROUNDED, show_header=True, header_style="bold magenta",
        )
        tbl.add_column("Index",    style="bold")
        tbl.add_column("Description",               min_width=36)
        tbl.add_column("Baseline",  justify="right")
        tbl.add_column("Event",    justify="right")
        tbl.add_column("Δ%",        justify="right")
        tbl.add_column("Obs",       justify="center")
        tbl.add_column("Status",    justify="center")

        def _status_label(apct, higher_is_bad):
            if apct is None:
                return "[dim]N/D[/dim]"
            #effective drop: positive = going in "bad" direction
            effective_drop = -apct if not higher_is_bad else apct
            if   effective_drop >= 20: return "[red]🔴 CRITICAL[/red]"
            elif effective_drop >= 10: return "[yellow]🟡 WARNING[/yellow]"
            else:                      return "[green]🟢 NORMAL[/green]"

        for idx_name, meta in self.INDEX_META.items():
            if idx_name == "VHI":
                continue  #VHI handled separately below
            if idx_name not in cop or "error" in cop[idx_name]:
                continue
            d     = cop[idx_name]
            b     = d.get("baseline_mean")
            e     = d.get("event_mean")
            apct  = d.get("anomaly_pct")
            obs   = d.get("observations", 0)
            b_lbl = _index_label(idx_name, b, None)
            e_lbl = _index_label(idx_name, e, b, higher_is_bad=meta["higher_is_bad"])
            if apct is not None:
                color = "red" if apct < -15 else "yellow" if apct < 0 else "green"
                p_lbl = f"[{color}]{apct:+.1f}%[/{color}]"
            else:
                p_lbl = "[dim]N/D[/dim]"
            status = _status_label(apct, meta["higher_is_bad"])
            tbl.add_row(idx_name, meta["full"], b_lbl, e_lbl, p_lbl, str(obs), status)

        #VHI row in main table
        if "VHI" in cop and cop["VHI"].get("event_mean") is not None:
            vhi = cop["VHI"]["event_mean"]
            vhi_color = "red" if vhi < 35 else "yellow" if vhi < 50 else "green"
            tbl.add_row(
                "VHI", self.INDEX_META["VHI"]["full"],
                "[dim]N/D[/dim]",
                f"[{vhi_color}]{vhi:.4f}[/{vhi_color}]",
                "[dim]N/D[/dim]",
                str(cop["VHI"].get("observations", 0)),
                "[dim]N/D[/dim]",
            )
        console.print(tbl)
        console.print()

        #VHI panel separado
        if "VHI" in cop and cop["VHI"].get("event_mean") is not None:
            vhi = cop["VHI"]["event_mean"]
            vci = cop["VHI"].get("vci", "N/D")
            tci = cop["VHI"].get("tci", "N/D")
            if   vhi < 35: vhi_color, vhi_lbl, vhi_icon = "red",    "SEVERE STRESS",   "🔴"
            elif vhi < 50: vhi_color, vhi_lbl, vhi_icon = "yellow", "MODERATE STRESS", "🟡"
            else:          vhi_color, vhi_lbl, vhi_icon = "green",  "HEALTHY VEGETATION","🟢"
            console.print(Panel(
                f"[bold {vhi_color}]VHI = {vhi:.1f} — {vhi_lbl} {vhi_icon}[/bold {vhi_color}]\n"
                f"  VCI (vegetation condition): {vci}  |  TCI (thermal condition): {tci}\n\n"
                f"  VHI combines vegetation condition (VCI, derived from NDVI) with thermal condition "
                f"(TCI, derived from NDMI/temperature). Values < 40 indicate severe "
                f"water stress with significant impact on yield.",
                title="[bold]⭐  Vegetation Health Index (VHI)[/bold]",
                border_style=vhi_color,
            ))
            console.print()

        #satellite narrative
        narrative_lines = []
        ndvi_b = cop.get("NDVI", {}).get("baseline_mean")
        ndvi_e = cop.get("NDVI", {}).get("event_mean")
        ndwi_e = cop.get("NDWI", {}).get("event_mean")
        ndmi_e = cop.get("NDMI", {}).get("event_mean")
        bsi_d  = cop.get("BSI",  {}).get("anomaly_abs")
        psri_d = cop.get("PSRI", {}).get("anomaly_abs")

        if ndvi_b and ndvi_e and ndvi_b != 0:
            chg_pct = (ndvi_e - ndvi_b) / abs(ndvi_b) * 100
            if chg_pct < -10:
                drop_pct = abs(chg_pct)
                narrative_lines.append(
                    f"• NDVI dropped by [bold red]{drop_pct:.1f}%[/bold red] "
                    f"({ndvi_b:.3f} → {ndvi_e:.3f}) — "
                    f"{'severe impairment' if drop_pct > 30 else 'significant reduction'} "
                    f"of active biomass."
                )
        if ndwi_e is not None and self.event_type == "drought" and ndwi_e < -0.05:
            narrative_lines.append(
                f"• NDWI [bold red]{ndwi_e:.4f}[/bold red] — severe water deficit confirmed."
            )
        if ndmi_e is not None and ndmi_e < 0.0:
            narrative_lines.append(
                f"• NDMI [bold red]{ndmi_e:.4f}[/bold red] via SWIR — low canopy water content."
            )
        if bsi_d and bsi_d > 0.03:
            narrative_lines.append(
                f"• BSI +{bsi_d:.4f} — [bold yellow]increase in bare soil[/bold yellow] "
                f"(stand failure, plant death or erosion)."
            )
        if psri_d and psri_d > 0.02:
            narrative_lines.append(
                f"• PSRI +{psri_d:.4f} — [bold orange1]accelerated senescence[/bold orange1] detected."
            )
        if narrative_lines:
            console.print(Panel(
                "\n".join(narrative_lines),
                title="[bold]Satellite Interpretation[/bold]",
                border_style="yellow",
            ))
        console.print()

    #poseidon
    def _poseidon_section(self, summary: Dict, vote: Dict, neighbors: Dict) -> None:
        console.print(Rule("[bold blue]🌡️   WEATHER DATA — POSEIDON NETWORK[/bold blue]"))
        console.print()

        if summary:
            tbl = Table(
                title="Weather Summary for the Period (IDW Interpolation)",
                box=box.SIMPLE_HEAVY, header_style="bold blue",
            )
            tbl.add_column("Variable",  style="cyan")
            tbl.add_column("Value",     justify="right")
            tbl.add_column("Context",   style="dim")

            mid_month   = self.start_date.month
            normals     = CLIMATE_NORMALS_RS.get(mid_month, {})
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            normal_prcp = normals.get("prcp_mm", 110) * months
            prcp_total  = summary.get("prcp_total_mm", 0)
            prcp_pct    = prcp_total / normal_prcp * 100 if normal_prcp else 0
            prcp_color  = "red" if prcp_pct < 50 else "yellow" if prcp_pct < 80 else "green"

            tbl.add_row("Accum. rainfall",
                        f"[{prcp_color}]{prcp_total:.1f} mm[/{prcp_color}]",
                        f"{prcp_pct:.0f}% of normal ({normal_prcp:.0f} mm)")
            tbl.add_row("Avg. temp.",     f"{summary.get('tavg_mean_c',0):.2f}°C", f"Normal: {normals.get('tavg_c','N/D')}°C")
            tbl.add_row("Abs. max. temp.", f"{summary.get('tmax_abs_c',0):.2f}°C",  "")
            tbl.add_row("Abs. min. temp.", f"{summary.get('tmin_abs_c',0):.2f}°C",  "")
            tbl.add_row("Avg. humidity",        f"{summary.get('rh_avg_mean_pct',0):.1f}%", "")
            tbl.add_row("Rainy days",  str(summary.get("prcp_days", "N/D")),       "days > 1mm")
            tbl.add_row("Max. wind",      f"{summary.get('wspd_max_kmh',0):.1f} km/h", "")
            console.print(tbl)
            console.print()

        w_score  = vote.get("weighted_score", 0.0)
        sig_lvl  = vote.get("signal_level", "unknown")
        passed   = vote.get("passed", False)
        votes    = vote.get("votes", {})
        v_color  = "green" if passed else "red"
        icon     = "✅" if passed else "❌"
        if   w_score >= 70: sev_txt = "[red]very severe[/red]"
        elif w_score >= 50: sev_txt = "[orange1]severe[/orange1]"
        elif w_score >= 35: sev_txt = "[yellow]moderate[/yellow]"
        elif w_score >= 20: sev_txt = "[dim]weak[/dim]"
        else:               sev_txt = "[dim]absent[/dim]"

        console.print(Panel(
            f"[bold {v_color}]IDW Climate Score: {w_score:.0f}/100 — signal {sig_lvl}[/bold {v_color}]\n"
            f"Estimated severity: {sev_txt}\n"
            f"{icon} {'CLIMATE SIGNAL APPROVED' if passed else 'CLIMATE SIGNAL INSUFFICIENT'}",
            title="[bold]IDW Score — Cardinal Neighbours[/bold]",
            border_style=v_color,
        ))
        if votes:
            vtbl = Table(box=box.SIMPLE, header_style="bold")
            vtbl.add_column("Dir.",     style="bold", justify="center", min_width=5)
            vtbl.add_column("Point",    justify="center")
            vtbl.add_column("Lat/Lon",  justify="center", style="dim")
            vtbl.add_column("Result",   justify="center")
            vtbl.add_column("Detail",   style="dim")
            dir_icons = {"N": "⬆ N", "S": "⬇ S", "E": "➡ E", "W": "⬅ W"}
            for direction, v in votes.items():
                ok = v.get("confirmed", False)
                vtbl.add_row(
                    dir_icons.get(direction, direction),
                    str(v.get("point_id", "N/D")),
                    f"{v.get('lat','N/D')} / {v.get('lon','N/D')}",
                    "[green]✅ CONFIRMED[/green]" if ok else "[red]❌ NOT CONFIRMED[/red]",
                    v.get("reason", "")[:70],
                )
            console.print(vtbl)
        console.print()

    #soil EMBRAPA

    def _soil_section(self, soil_data: Dict, analysis: Dict) -> None:
        console.print(Rule("[bold green]🪱  SOIL ANALYSIS — EMBRAPA / AGRICULTURAL SUITABILITY[/bold green]"))
        console.print()

        dominant_class = soil_data.get("dominant_class")
        soil_name      = soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D")
        soil_code      = soil_data.get("soil_code", "N/D")
        suitable       = soil_data.get("suitable_for_agriculture", True)
        apt_label      = soil_data.get("aptitude_label", "N/D")
        apt_desc       = soil_data.get("aptitude_description", "")
        dom_pct        = soil_data.get("dominant_percentage", 0)
        water          = soil_data.get("water_props", {})
        classified_pct = soil_data.get("classified_area_percentage", 0)

        #fitness table
        apt_tbl = Table.grid(padding=(0, 3))
        apt_tbl.add_column(style="bold cyan",  justify="right")
        apt_tbl.add_column(style="white")
        apt_tbl.add_row("Suitability Class:",
                        f"[bold {'green' if suitable else 'red'}]Class {dominant_class} — {apt_label}[/bold {'green' if suitable else 'red'}] "
                        f"({'✅ SUITABLE' if suitable else '❌ UNSUITABLE'} for crops)")
        apt_tbl.add_row("Dominant Soil:",     f"{soil_code} | {soil_name} ({dom_pct:.0f}% of area)")
        apt_tbl.add_row("EMBRAPA Description:", apt_desc)
        apt_tbl.add_row("Classified area:",    f"{classified_pct:.0f}%")
        console.print(Panel(apt_tbl, title="[bold]Agricultural Suitability (EMBRAPA)[/bold]", border_style="green"))
        console.print()

        #water properties
        if water:
            h_tbl = Table(
                title="Hydraulic Properties of Dominant Soil",
                box=box.ROUNDED, header_style="bold cyan",
            )
            h_tbl.add_column("Property",          style="cyan")
            h_tbl.add_column("Value",             justify="right")
            h_tbl.add_column("Interpretation",    style="dim")

            awc  = water.get("AWC", "N/D")
            ks   = water.get("Ks",  "N/D")
            fc   = water.get("fc",  "N/D")
            wp   = water.get("wp",  "N/D")
            ret  = water.get("retention", "N/D")
            tex  = water.get("texture",  "N/D")

            awc_color = "red" if isinstance(awc, (int, float)) and awc < 60 else "yellow" if isinstance(awc, (int, float)) and awc < 100 else "green"
            ks_color  = "yellow" if isinstance(ks, (int, float)) and ks > 30 else "green"

            h_tbl.add_row("AWC (plant-available water)",    f"[{awc_color}]{awc} mm/m[/{awc_color}]",
                          "Water storage capacity available to plants")
            h_tbl.add_row("Ks (hydraulic conductivity)", f"[{ks_color}]{ks} mm/h[/{ks_color}]",
                          "Drainage speed — high = drains fast")
            h_tbl.add_row("Field capacity",     f"{fc}%",  "Water content at field capacity")
            h_tbl.add_row("Wilting point",         f"{wp}%",  "Minimum water content for plant survival")
            h_tbl.add_row("Water retention",        f"[bold]{ret}[/bold]",  "General retention classification")
            h_tbl.add_row("Texture",                 tex,       "Dominant granulometry")
            console.print(h_tbl)
            console.print()

        #list of soils found (top-5)
        soil_types = soil_data.get("soil_types", [])
        if len(soil_types) > 1:
            st_tbl = Table(
                title="Soils Found in Field",
                box=box.SIMPLE, header_style="bold",
            )
            st_tbl.add_column("Code",      style="bold")
            st_tbl.add_column("Soil",      min_width=30)
            st_tbl.add_column("% Area",    justify="right")
            st_tbl.add_column("Apt.",      justify="center")
            st_tbl.add_column("AWC",       justify="right")
            st_tbl.add_column("Retention", style="dim")
            for st in soil_types:
                apt_c = st.get("apt_class")
                apt_s = SOIL_APTITUDE_CLASSES.get(apt_c, {})
                apt_ok = apt_s.get("suitable", True)
                st_tbl.add_row(
                    st["code"],
                    st["name"][:35],
                    f"{st['pct_area']:.1f}%",
                    f"[{'green' if apt_ok else 'red'}]Cls {apt_c}[/{'green' if apt_ok else 'red'}]" if apt_c else "N/D",
                    f"{st['water_props'].get('AWC','N/D')} mm/m",
                    st["water_props"].get("retention", "N/D"),
                )
            console.print(st_tbl)
            console.print()

        #soil interpretation for the event
        soil_check = analysis.get("soil_check", {})
        amplifier  = soil_check.get("amplifier", 1.0) if soil_check else 1.0
        retention   = soil_check.get("retention", "medium") if soil_check else "medium"

        interp_lines = []
        if self.event_type == "drought":
            if retention in ("very low", "low"):
                interp_lines.append(
                    f"⚠️  Low water-retention soil (AWC = {water.get('AWC','N/D')} mm/m) "
                    f"[bold red]amplifies water deficit[/bold red] during dry periods — "
                    f"plants exhaust the available soil water reserve faster."
                )
            elif retention in ("high", "very high"):
                interp_lines.append(
                    f"✅ High-retention soil (AWC = {water.get('AWC','N/D')} mm/m) "
                    f"[bold green]partially buffers water deficit[/bold green] — "
                    f"larger water reserve available in the soil profile."
                )
        elif self.event_type == "rainfall":
            if retention in ("high", "very high") or water.get("Ks", 20) < 5:
                interp_lines.append(
                    f"⚠️  Low-drainage soil (Ks = {water.get('Ks','N/D')} mm/h) "
                    f"[bold red]increases waterlogging and root asphyxiation risk[/bold red] — "
                    f"water accumulates easily in the soil profile."
                )
        if amplifier != 1.0:
            interp_lines.append(
                f"🔢 Soil damage amplification factor: [bold cyan]{amplifier:.2f}x[/bold cyan] "
                f"(incorporated into yield loss estimate)."
            )
        if interp_lines:
            console.print(Panel(
                "\n".join(interp_lines),
                title="[bold]Soil × Event — Interaction[/bold]",
                border_style="cyan",
            ))
        console.print()

    #cross analysis
    def _cross_analysis_section(
        self, analysis: Dict, cop: Dict, summary: Dict, soil_data: Dict = None
    ) -> None:
        console.print(Rule("[bold green]🔬  INTEGRATED ANALYSIS — SATELLITE + STATION + SOIL[/bold green]"))
        console.print()

        phase = analysis.get("phase_info", {})
        phase_name  = phase.get("phase", "N/D")
        sensitivity = phase.get("sensitivity", 0)
        lines = []

        ndvi_e = cop.get("NDVI", {}).get("event_mean")
        ndvi_b = cop.get("NDVI", {}).get("baseline_mean")
        prcp   = summary.get("prcp_total_mm") if summary else None
        if ndvi_e and ndvi_b and prcp is not None:
            drop   = abs((ndvi_e - ndvi_b) / ndvi_b * 100) if ndvi_b else 0
            period = (self.end_date - self.start_date).days + 1
            months = period / 30
            mid_m  = self.start_date.month
            normal = CLIMATE_NORMALS_RS.get(mid_m, {}).get("prcp_mm", 110) * months
            pct    = prcp / normal * 100 if normal else 100
            lines.append(
                f"[1] NDVI declined by [bold]{drop:.1f}%[/bold] vs baseline, while precipitation "
                f"reached [bold]{prcp:.1f} mm[/bold] ({pct:.0f}% of expected) — "
                f"[bold]converging signals[/bold]."
            )

        ndwi_e = cop.get("NDWI", {}).get("event_mean")
        ndmi_e = cop.get("NDMI", {}).get("event_mean")
        if ndwi_e is not None and ndmi_e is not None:
            if self.event_type == "drought" and ndwi_e < 0 and ndmi_e < 0:
                lines.append(
                    f"[2] NDWI ({ndwi_e:.4f}) and NDMI ({ndmi_e:.4f}) simultaneously negative — "
                    f"diagnostic pattern of real water deficit."
                )

        if phase_name not in ("unknown", "outside cycle"):
            lines.append(
                f"[3] Evento na fase [bold]{phase_name}[/bold] "
                f"({phase.get('description','')}) — "
                f"sensitivity [bold]{sensitivity*100:.0f}%[/bold]."
            )

        vhi_e = cop.get("VHI", {}).get("event_mean")
        if vhi_e is not None:
            lines.append(
                f"[4] VHI = [bold {'red' if vhi_e < 40 else 'yellow'}]{vhi_e:.1f}[/bold {'red' if vhi_e < 40 else 'yellow'}] — "
                f"{'severe stress confirmed (< 40)' if vhi_e < 40 else 'warning zone'}."
            )

        #soil in cross analysis
        if soil_data and not soil_data.get("error"):
            soil_check = analysis.get("soil_check", {})
            amplifier  = soil_check.get("amplifier", 1.0) if soil_check else 1.0
            sname      = soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D")
            retention   = soil_data.get("water_props", {}).get("retention", "medium")
            if amplifier > 1.0:
                lines.append(
                    f"[5] Soil [bold]{sname}[/bold] (retention: {retention}) "
                    f"[bold red]amplifies[/bold red] damage by {amplifier:.2f}x — "
                    f"incorporated into the yield loss estimate."
                )
            elif amplifier < 1.0:
                lines.append(
                    f"[5] Soil [bold]{sname}[/bold] (retention: {retention}) "
                    f"[bold green]mitigates[/bold green] damage by {amplifier:.2f}x — "
                    f"incorporated into the yield loss estimate."
                )

        console.print(Panel(
            "\n\n".join(lines),
            title="[bold]Evidence Cross-Reference[/bold]",
            border_style="green",
        ))
        console.print()

    #checklist
    def _checks_section(self, analysis: Dict) -> None:
        console.print(Rule("[bold]🔎  VALIDATION CHECKLIST[/bold]"))
        console.print()
        tbl = Table(box=box.ROUNDED, show_header=True, header_style="bold")
        tbl.add_column("#",        justify="right", style="dim", min_width=3)
        tbl.add_column("Criterion", min_width=45)
        tbl.add_column("Resultado", min_width=35)
        tbl.add_column("Peso",     justify="center")
        tbl.add_column("OK",       justify="center")
        for i, chk in enumerate(analysis.get("checks", []), 1):
            w = chk.get("weight", 0)
            if w == 0:
                continue
            ok = chk.get("passed", False)
            tbl.add_row(
                str(i),
                chk.get("name", ""),
                chk.get("value", ""),
                f"{w:.1f}",
                "[green]✅[/green]" if ok else "[red]❌[/red]",
            )
        console.print(tbl)
        sm = analysis.get("summary", {})
        console.print(
            f"  Criteria: [bold]{sm.get('checks_total',0)}[/bold]  |  "
            f"Passed: [bold green]{sm.get('checks_passed',0)}[/bold green]  |  "
            f"Score: [bold]{sm.get('score_raw','N/D')}[/bold] ({sm.get('pct_score','N/D')})  |  "
            f"Met: [bold cyan]{sm.get('pct_criteria',0)}%[/bold cyan]"
        )
        console.print()

    #casualty
    def _loss_section(self, analysis: Dict, hist_baseline: Dict = None) -> None:
        loss = analysis.get("loss_estimate", {})
        if not loss:
            return
        console.print(Rule("[bold red]📉  ESTIMATED ECONOMIC LOSSES[/bold red]"))
        console.print()

        tbl = Table.grid(padding=(0, 4))
        tbl.add_column(justify="left",  style="dim")
        tbl.add_column(justify="right", style="bold")
        tbl.add_row("Total area:",                   f"{loss.get('area_ha','N/D'):.1f} ha")
        tbl.add_row("Expected yield:",        f"{loss.get('expected_yield_bags_ha','N/D')} sc/ha")

        hist = loss.get("hist_baseline") or hist_baseline
        if hist and hist.get("local_yield_est_bags_ha"):
            ly  = hist["local_yield_est_bags_ha"]
            ny  = hist.get("n_years", "?")
            yrs = hist.get("years_used", "")
            tbl.add_row("[cyan]Local historical reference:[/cyan]",
                        f"[cyan]~{ly} bags/ha[/cyan] [dim](base: {ny} years — {yrs})[/dim]")

        # soil amplifier
        soil_amp = loss.get("soil_amplifier")
        if soil_amp:
            amp_color = "red" if soil_amp["amplifier"] > 1.0 else "green"
            tbl.add_row(
                "[cyan]Soil amplification factor:[/cyan]",
                f"[{amp_color}]{soil_amp['amplifier']:.2f}x[/{amp_color}] "
                f"[dim]({soil_amp['soil_name']} — AWC {soil_amp['AWC']} mm/m)[/dim]"
            )

        tbl.add_row("Estimated actual yield:",  f"{loss.get('estimated_yield_bags_ha','N/D')} sc/ha")
        tbl.add_row("Yield loss:",        f"[red]{_pct(loss.get('yield_loss_pct',0))}[/red]")
        tbl.add_row("Total loss (bags):",           f"[red]{loss.get('yield_loss_total_bags',0):,.0f} bags[/red]")
        tbl.add_row("Reference price:",              f"{_brl(loss.get('price_brl_bag',0))}/bag")
        tbl.add_row("", "")
        tbl.add_row("Expected revenue:",              f"[green]{_brl(loss.get('expected_revenue_brl',0))}[/green]")
        tbl.add_row("Estimated actual revenue:",         f"[yellow]{_brl(loss.get('estimated_revenue_brl',0))}[/yellow]")
        tbl.add_row("[bold red]ESTIMATED FINANCIAL LOSS:[/bold red]",
                    f"[bold red]{_brl(loss.get('financial_loss_brl',0))}[/bold red]")

        comp   = loss.get("loss_frac_components", {})
        amp_v  = comp.get("soil_amplifier", 1.0)
        detail = (
            f"\n  Componentes da estimativa:\n"
            f"    • Climate deficit (Poseidon):  {comp.get('climate_loss','N/D')}%\n"
            f"    • Satellite anomaly (NDVI):    {comp.get('ndvi_loss','N/D')}%\n"
            f"    • Phenological sensitivity:   {comp.get('phase_sensitivity','N/D')}%\n"
            f"    • Soil amplifier:              {amp_v:.2f}x"
        )
        console.print(Panel(tbl, title="[bold]Estimated Economic Impact[/bold]",
                            border_style="red", subtitle="[dim]Estimated values — ref. CEPEA[/dim]"))
        console.print(f"[dim]{detail}[/dim]")
        console.print()

    #verdict
    def _verdict_section(self, analysis: Dict) -> None:
        verdict    = analysis.get("verdict", "INCONCLUSIVE")
        confidence = analysis.get("confidence", 0)
        color      = _verdict_color(verdict)
        icons      = {"CONFIRMED": "✅", "INCONCLUSIVE": "⚠️", "NOT CONFIRMED": "❌"}
        icon       = icons.get(verdict, "❓")
        loss       = analysis.get("loss_estimate", {})
        loss_pct   = loss.get("yield_loss_pct", 0)
        loss_fin   = loss.get("financial_loss_brl", 0)
        phase_info = analysis.get("phase_info", {})

        justification = self._build_justification(verdict, confidence, loss_pct, loss_fin, phase_info, analysis)
        verdict_text  = (
            f"[bold {color}]{icon}  VERDICT: {verdict}[/bold {color}]\n"
            f"[bold]Confidence Level: {confidence:.0f}%[/bold]"
            + (f"  |  [bold]Severidade: {analysis.get('severity','N/D')} "
               f"(IDW {analysis.get('idw_score',0):.0f}/100)[/bold]"
               if analysis.get("idw_score") else "")
            + f"\n\n{justification}"
        )
        console.print(Panel(
            verdict_text,
            title="[bold white]FINAL RESULT[/bold white]",
            border_style=color, padding=(1, 2),
        ))
        console.print()
        console.print(Rule("[dim]Report generated by the Poseidon-Copernicus-EMBRAPA Validator system[/dim]"))
        console.print()

    def _build_justification(
        self, verdict, confidence, loss_pct, loss_fin, phase_info, analysis
    ) -> str:
        event_lbl   = self.EVENT_LABELS.get(self.event_type, self.event_type)
        crop        = self.crop_params["name_en"]
        phase       = phase_info.get("phase", "unknown")
        sens        = phase_info.get("sensitivity", 0) * 100
        soil_check  = analysis.get("soil_check", {})
        soil_note   = ""
        if soil_check and soil_check.get("available"):
            amp = soil_check.get("amplifier", 1.0)
            soil_note = (
                f" Soil {soil_check.get('soil_name','N/D')} "
                f"({'amplified' if amp > 1.0 else 'mitigated'} damage by {amp:.2f}x)."
            )

        if verdict == "CONFIRMED":
            return (
                f"Satellite data (Copernicus/Sentinel-2) and Poseidon weather network "
                f"present converging evidence of [bold]{event_lbl}[/bold]. "
                f"Phenological phase: [bold]{phase}[/bold] (sensitivity {sens:.0f}%).{soil_note} "
                f"Estimated loss: [bold red]{loss_pct:.1f}%[/bold red] "
                f"([bold red]{_brl(loss_fin)}[/bold red]). "
                f"[bold]CLAIM VALIDATED with {confidence:.0f}% confidence.[/bold]"
            )
        elif verdict == "INCONCLUSIVE":
            return (
                f"Partial signals of [bold]{event_lbl}[/bold] detected, but without sufficient evidence "
                f"for a definitive confirmation ({confidence:.0f}%)."
                f"{soil_note} Supplementary analysis and on-site inspection recommended."
            )
        else:
            return (
                f"Data do not corroborate the claim of [bold]{event_lbl}[/bold] "
                f"({confidence:.0f}% confidence).{soil_note} [bold]CLAIM NOT VALIDATED.[/bold]"
            )
