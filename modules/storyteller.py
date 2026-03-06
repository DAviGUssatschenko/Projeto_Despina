"""
modules/storyteller.py
Gerador do relatório narrativo completo (storytelling) em português.
Inclui seção de dados de solo EMBRAPA integrada à análise.
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
    return {"CONFIRMADO": "green", "INCONCLUSIVO": "yellow", "NÃO CONFIRMADO": "red"}.get(verdict, "white")

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
        "NDVI":  {"full": "Índice de Vegetação por Diferença Normalizada",  "higher_is_bad": False},
        "NDRE":  {"full": "NDVI Red-Edge (estresse precoce)",               "higher_is_bad": False},
        "EVI":   {"full": "Índice de Vegetação Aprimorado",                 "higher_is_bad": False},
        "NDWI":  {"full": "Índice de Água na Vegetação",                    "higher_is_bad": False},
        "NDMI":  {"full": "Índice de Umidade por Diferença Normalizada",    "higher_is_bad": False},
        "BSI":   {"full": "Índice de Solo Exposto",                         "higher_is_bad": True},
        "NBR":   {"full": "Razão de Queima Normalizada",                    "higher_is_bad": False},
        "PSRI":  {"full": "Índice de Senescência Vegetal",                  "higher_is_bad": True},
        "CRI1":  {"full": "Índice de Reflectância de Carotenóides",         "higher_is_bad": True},
        "VHI":   {"full": "Índice de Saúde da Vegetação (VCI+TCI)",         "higher_is_bad": False},
    }

    EVENT_LABELS = {
        "seca":    "Seca / Déficit Hídrico",
        "chuva":   "Excesso de Chuva / Alagamento",
        "geada":   "Geada",
        "granizo": "Granizo / Tempestade",
    }

    def __init__(
        self,
        event_type:    str,
        crop_type:     str,
        start_date:    date,
        end_date:      date,
        area_ha:       float,
        farm_name:     str = "Propriedade Rural",
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
        self.crop_params   = CROP_PARAMS.get(crop_type, CROP_PARAMS["soja"])

    # ── ponto de entrada ──────────────────────────────────────────────────────

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
        console.print(Rule("[bold cyan]SISTEMA DE VALIDAÇÃO DE SINISTROS AGRÍCOLAS[/bold cyan]"))
        console.print(Rule("[dim]Poseidon Climate Network  ✦  Copernicus Sentinel-2  ✦  EMBRAPA Solo[/dim]"))
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

    # ── cabeçalho ─────────────────────────────────────────────────────────────

    def _header_block(self) -> None:
        lat = self.centroid.get("lat", "N/D")
        lon = self.centroid.get("lon", "N/D")
        info = Table.grid(padding=(0, 2))
        info.add_column(style="bold cyan",  justify="right")
        info.add_column(style="white")
        info.add_row("📍 Propriedade",  self.farm_name)
        info.add_row("🌱 Cultura",       self.crop_params["name_pt"])
        info.add_row("⚠️  Alegação",      self.EVENT_LABELS.get(self.event_type, self.event_type))
        info.add_row("📅 Período",        f"{self.start_date.strftime('%d/%m/%Y')} → {self.end_date.strftime('%d/%m/%Y')}")
        info.add_row("📐 Área",           f"{self.area_ha:.1f} hectares")
        info.add_row("📌 Centróide",      f"Lat {lat} | Lon {lon}")
        if self.planting_date:
            info.add_row("🌾 Plantio",    self.planting_date.strftime("%d/%m/%Y"))
        console.print(Panel(info, title="[bold]IDENTIFICAÇÃO DO SINISTRO[/bold]", border_style="cyan"))
        console.print()

    # ── contexto ──────────────────────────────────────────────────────────────

    def _context_narrative(self) -> None:
        cp        = self.crop_params
        event_lbl = self.EVENT_LABELS.get(self.event_type, self.event_type)
        avg_yield = cp["yield_avg_sacas_ha"]
        min_yield = cp["yield_min_sacas_ha"]
        max_yield = cp["yield_max_sacas_ha"]
        price     = cp["price_brl_saca"]
        area      = self.area_ha
        rev_min   = min_yield * area * price
        rev_max   = max_yield * area * price
        rev_proj  = avg_yield * area * price
        n_days    = (self.end_date - self.start_date).days + 1
        text = (
            f"[bold white]📖  HISTÓRICO E CONTEXTO[/bold white]\n\n"
            f"Lavoura de [bold]{cp['name_pt'].lower()}[/bold] com produtividade histórica entre "
            f"[bold]{min_yield}[/bold] e [bold]{max_yield} sacas/ha[/bold], "
            f"com média histórica de [bold]{avg_yield} sc/ha[/bold].\n\n"
            f"Para uma área de [bold]{area:.1f} ha[/bold] com o preço médio de "
            f"[bold]{_brl(price)}/saca[/bold] (referência CEPEA), a receita bruta esperada varia entre "
            f"[bold]{_brl(rev_min)}[/bold] e [bold]{_brl(rev_max)}[/bold], "
            f"com receita projetada para a safra corrente de [bold]{_brl(rev_proj)}[/bold].\n\n"
            f"O produtor alega ocorrência de [bold red]{event_lbl}[/bold red] entre "
            f"[bold]{self.start_date.strftime('%d/%m/%Y')}[/bold] e "
            f"[bold]{self.end_date.strftime('%d/%m/%Y')}[/bold] "
            f"— período de [bold]{n_days} dias[/bold]. "
            f"A seguir, os dados satelitais e meteorológicos são cruzados para "
            f"[bold]validar ou refutar[/bold] esta alegação."
        )
        console.print(Panel(text, border_style="blue"))
        console.print()

    # ── Copernicus ────────────────────────────────────────────────────────────

    def _satellite_section(self, cop: Dict) -> None:
        console.print(Rule("[bold yellow]📡  DADOS SATELITAIS — COPERNICUS / SENTINEL-2[/bold yellow]"))
        console.print()

        tbl = Table(
            title="Índices Espectrais — Comparativo Baseline vs Evento",
            box=box.ROUNDED, show_header=True, header_style="bold magenta",
        )
        tbl.add_column("Índice",    style="bold")
        tbl.add_column("Descrição",               min_width=36)
        tbl.add_column("Baseline",  justify="right")
        tbl.add_column("Evento",    justify="right")
        tbl.add_column("Δ%",        justify="right")
        tbl.add_column("Obs",       justify="center")
        tbl.add_column("Status",    justify="center")

        def _status_label(apct, higher_is_bad):
            if apct is None:
                return "[dim]N/D[/dim]"
            # Effective drop: positive = going in "bad" direction
            effective_drop = -apct if not higher_is_bad else apct
            if   effective_drop >= 20: return "[red]🔴 CRÍTICO[/red]"
            elif effective_drop >= 10: return "[yellow]🟡 ALERTA[/yellow]"
            else:                      return "[green]🟢 NORMAL[/green]"

        for idx_name, meta in self.INDEX_META.items():
            if idx_name == "VHI":
                continue  # VHI handled separately below
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

        # VHI row in main table
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

        # VHI panel separado
        if "VHI" in cop and cop["VHI"].get("event_mean") is not None:
            vhi = cop["VHI"]["event_mean"]
            vci = cop["VHI"].get("vci", "N/D")
            tci = cop["VHI"].get("tci", "N/D")
            if   vhi < 35: vhi_color, vhi_lbl, vhi_icon = "red",    "ESTRESSE SEVERO",   "🔴"
            elif vhi < 50: vhi_color, vhi_lbl, vhi_icon = "yellow", "ESTRESSE MODERADO", "🟡"
            else:          vhi_color, vhi_lbl, vhi_icon = "green",  "VEGETAÇÃO SAUDÁVEL","🟢"
            console.print(Panel(
                f"[bold {vhi_color}]VHI = {vhi:.1f} — {vhi_lbl} {vhi_icon}[/bold {vhi_color}]\n"
                f"  VCI (condição vegetação): {vci}  |  TCI (condição térmica): {tci}\n\n"
                f"  O VHI combina o estado da vegetação (VCI, derivado do NDVI) com a condição "
                f"térmica (TCI, derivado do NDMI/temperatura). Valores < 40 indicam estresse "
                f"hídrico severo com impacto significativo na produtividade.",
                title="[bold]⭐  Vegetation Health Index[/bold]",
                border_style=vhi_color,
            ))
            console.print()

        # Narrativa satelital
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
                    f"• O NDVI registrou queda de [bold red]{drop_pct:.1f}%[/bold red] "
                    f"({ndvi_b:.3f} → {ndvi_e:.3f}) — "
                    f"{'severo comprometimento' if drop_pct > 30 else 'redução significativa'} "
                    f"da biomassa ativa."
                )
        if ndwi_e is not None and self.event_type == "seca" and ndwi_e < -0.05:
            narrative_lines.append(
                f"• NDWI [bold red]{ndwi_e:.4f}[/bold red] — déficit hídrico severo confirmado."
            )
        if ndmi_e is not None and ndmi_e < 0.0:
            narrative_lines.append(
                f"• NDMI [bold red]{ndmi_e:.4f}[/bold red] via SWIR — baixo conteúdo de água no dossel."
            )
        if bsi_d and bsi_d > 0.03:
            narrative_lines.append(
                f"• BSI +{bsi_d:.4f} — [bold yellow]aumento de solo exposto[/bold yellow] "
                f"(falha de stand, morte de plantas ou erosão)."
            )
        if psri_d and psri_d > 0.02:
            narrative_lines.append(
                f"• PSRI +{psri_d:.4f} — [bold orange1]senescência acelerada[/bold orange1] detectada."
            )
        if narrative_lines:
            console.print(Panel(
                "\n".join(narrative_lines),
                title="[bold]Interpretação Satelital[/bold]",
                border_style="yellow",
            ))
        console.print()

    # ── Poseidon ──────────────────────────────────────────────────────────────

    def _poseidon_section(self, summary: Dict, vote: Dict, neighbors: Dict) -> None:
        console.print(Rule("[bold blue]🌡️   DADOS METEOROLÓGICOS — REDE POSEIDON[/bold blue]"))
        console.print()

        if summary:
            tbl = Table(
                title="Resumo Meteorológico do Período (Interpolação IDW)",
                box=box.SIMPLE_HEAVY, header_style="bold blue",
            )
            tbl.add_column("Variável",  style="cyan")
            tbl.add_column("Valor",     justify="right")
            tbl.add_column("Contexto",  style="dim")

            mid_month   = self.start_date.month
            normals     = CLIMATE_NORMALS_RS.get(mid_month, {})
            period_days = summary.get("period_days", 30)
            months      = period_days / 30
            normal_prcp = normals.get("prcp_mm", 110) * months
            prcp_total  = summary.get("prcp_total_mm", 0)
            prcp_pct    = prcp_total / normal_prcp * 100 if normal_prcp else 0
            prcp_color  = "red" if prcp_pct < 50 else "yellow" if prcp_pct < 80 else "green"

            tbl.add_row("Precip. acumulada",
                        f"[{prcp_color}]{prcp_total:.1f} mm[/{prcp_color}]",
                        f"{prcp_pct:.0f}% da normal ({normal_prcp:.0f} mm)")
            tbl.add_row("Temp. média",     f"{summary.get('tavg_mean_c',0):.2f}°C", f"Normal: {normals.get('tavg_c','N/D')}°C")
            tbl.add_row("Temp. máx. abs.", f"{summary.get('tmax_abs_c',0):.2f}°C",  "")
            tbl.add_row("Temp. mín. abs.", f"{summary.get('tmin_abs_c',0):.2f}°C",  "")
            tbl.add_row("UR média",        f"{summary.get('rh_avg_mean_pct',0):.1f}%", "")
            tbl.add_row("Dias com chuva",  str(summary.get("prcp_days", "N/D")),       "dias > 1mm")
            tbl.add_row("Vento máx.",      f"{summary.get('wspd_max_kmh',0):.1f} km/h", "")
            console.print(tbl)
            console.print()

        w_score  = vote.get("weighted_score", 0.0)
        sig_lvl  = vote.get("signal_level", "desconhecido")
        passed   = vote.get("passed", False)
        votes    = vote.get("votes", {})
        v_color  = "green" if passed else "red"
        icon     = "✅" if passed else "❌"
        if   w_score >= 70: sev_txt = "[red]muito severo[/red]"
        elif w_score >= 50: sev_txt = "[orange1]severo[/orange1]"
        elif w_score >= 35: sev_txt = "[yellow]moderado[/yellow]"
        elif w_score >= 20: sev_txt = "[dim]fraco[/dim]"
        else:               sev_txt = "[dim]ausente[/dim]"

        console.print(Panel(
            f"[bold {v_color}]Score climático IDW: {w_score:.0f}/100 — sinal {sig_lvl}[/bold {v_color}]\n"
            f"Severidade estimada: {sev_txt}\n"
            f"{icon} {'SINAL CLIMÁTICO APROVADO' if passed else 'SINAL CLIMÁTICO INSUFICIENTE'}",
            title="[bold]Score IDW — Vizinhos Cardinais[/bold]",
            border_style=v_color,
        ))
        if votes:
            vtbl = Table(box=box.SIMPLE, header_style="bold")
            vtbl.add_column("Dir.",     style="bold", justify="center", min_width=5)
            vtbl.add_column("Ponto",    justify="center")
            vtbl.add_column("Lat/Lon",  justify="center", style="dim")
            vtbl.add_column("Resultado", justify="center")
            vtbl.add_column("Detalhe",  style="dim")
            dir_icons = {"N": "⬆ N", "S": "⬇ S", "L": "➡ L", "O": "⬅ O"}
            for direction, v in votes.items():
                ok = v.get("confirmed", False)
                vtbl.add_row(
                    dir_icons.get(direction, direction),
                    str(v.get("point_id", "N/D")),
                    f"{v.get('lat','N/D')} / {v.get('lon','N/D')}",
                    "[green]✅ CONFIRMA[/green]" if ok else "[red]❌ NÃO CONFIRMA[/red]",
                    v.get("reason", "")[:70],
                )
            console.print(vtbl)
        console.print()

    # ── Solo EMBRAPA ──────────────────────────────────────────────────────────

    def _soil_section(self, soil_data: Dict, analysis: Dict) -> None:
        console.print(Rule("[bold green]🪱  ANÁLISE DE SOLO — EMBRAPA / APTIDÃO AGRÍCOLA[/bold green]"))
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

        # Tabela de aptidão
        apt_tbl = Table.grid(padding=(0, 3))
        apt_tbl.add_column(style="bold cyan",  justify="right")
        apt_tbl.add_column(style="white")
        apt_tbl.add_row("Classe de Aptidão:",
                        f"[bold {'green' if suitable else 'red'}]Classe {dominant_class} — {apt_label}[/bold {'green' if suitable else 'red'}] "
                        f"({'✅ APTA' if suitable else '❌ INAPTA'} para lavouras)")
        apt_tbl.add_row("Solo Dominante:",     f"{soil_code} | {soil_name} ({dom_pct:.0f}% da área)")
        apt_tbl.add_row("Descrição EMBRAPA:",  apt_desc)
        apt_tbl.add_row("Área classificada:",  f"{classified_pct:.0f}%")
        console.print(Panel(apt_tbl, title="[bold]Aptidão Agrícola (EMBRAPA)[/bold]", border_style="green"))
        console.print()

        # Propriedades hídricas
        if water:
            h_tbl = Table(
                title="Propriedades Hídricas do Solo Dominante",
                box=box.ROUNDED, header_style="bold cyan",
            )
            h_tbl.add_column("Propriedade",       style="cyan")
            h_tbl.add_column("Valor",             justify="right")
            h_tbl.add_column("Interpretação",     style="dim")

            awc  = water.get("AWC", "N/D")
            ks   = water.get("Ks",  "N/D")
            fc   = water.get("fc",  "N/D")
            wp   = water.get("wp",  "N/D")
            ret  = water.get("retencao",  "N/D")
            tex  = water.get("textura",   "N/D")

            awc_color = "red" if isinstance(awc, (int, float)) and awc < 60 else "yellow" if isinstance(awc, (int, float)) and awc < 100 else "green"
            ks_color  = "yellow" if isinstance(ks, (int, float)) and ks > 30 else "green"

            h_tbl.add_row("AWC (água disponível)",    f"[{awc_color}]{awc} mm/m[/{awc_color}]",
                          "Capacidade de armazenamento de água para as plantas")
            h_tbl.add_row("Ks (condutividade hid.)", f"[{ks_color}]{ks} mm/h[/{ks_color}]",
                          "Velocidade de drenagem — alto = drena rápido")
            h_tbl.add_row("Capacidade de campo",     f"{fc}%",  "Teor de água na capacidade de campo")
            h_tbl.add_row("Ponto de murcha",         f"{wp}%",  "Teor mínimo para sobrevivência das plantas")
            h_tbl.add_row("Retenção hídrica",        f"[bold]{ret}[/bold]",  "Classificação geral de retenção")
            h_tbl.add_row("Textura",                 tex,       "Granulometria dominante")
            console.print(h_tbl)
            console.print()

        # Lista de solos encontrados (top-5)
        soil_types = soil_data.get("soil_types", [])
        if len(soil_types) > 1:
            st_tbl = Table(
                title="Solos Encontrados no Talhão",
                box=box.SIMPLE, header_style="bold",
            )
            st_tbl.add_column("Código",    style="bold")
            st_tbl.add_column("Solo",      min_width=30)
            st_tbl.add_column("% Área",    justify="right")
            st_tbl.add_column("Apt.",      justify="center")
            st_tbl.add_column("AWC",       justify="right")
            st_tbl.add_column("Retenção",  style="dim")
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
                    st["water_props"].get("retencao", "N/D"),
                )
            console.print(st_tbl)
            console.print()

        # Interpretação do solo para o evento
        soil_check = analysis.get("soil_check", {})
        amplifier  = soil_check.get("amplifier", 1.0) if soil_check else 1.0
        retencao   = soil_check.get("retencao", "média") if soil_check else "média"

        interp_lines = []
        if self.event_type == "seca":
            if retencao in ("muito baixa", "baixa"):
                interp_lines.append(
                    f"⚠️  Solo com baixa retenção hídrica (AWC = {water.get('AWC','N/D')} mm/m) "
                    f"[bold red]amplifica o déficit hídrico[/bold red] durante períodos secos — "
                    f"as plantas esgotam a reserva disponível mais rapidamente."
                )
            elif retencao in ("alta", "muito alta"):
                interp_lines.append(
                    f"✅ Solo com alta retenção (AWC = {water.get('AWC','N/D')} mm/m) "
                    f"[bold green]atenua parcialmente o déficit hídrico[/bold green] — "
                    f"maior reserva disponível no perfil."
                )
        elif self.event_type == "chuva":
            if retencao in ("alta", "muito alta") or water.get("Ks", 20) < 5:
                interp_lines.append(
                    f"⚠️  Solo com baixa drenagem (Ks = {water.get('Ks','N/D')} mm/h) "
                    f"[bold red]aumenta risco de encharcamento e asfixia radicular[/bold red] — "
                    f"água acumula no perfil com facilidade."
                )
        if amplifier != 1.0:
            interp_lines.append(
                f"🔢 Fator de amplificação de dano pelo solo: [bold cyan]{amplifier:.2f}x[/bold cyan] "
                f"(incorporado na estimativa de perda de produtividade)."
            )
        if interp_lines:
            console.print(Panel(
                "\n".join(interp_lines),
                title="[bold]Solo × Evento — Interação[/bold]",
                border_style="cyan",
            ))
        console.print()

    # ── análise cruzada ───────────────────────────────────────────────────────

    def _cross_analysis_section(
        self, analysis: Dict, cop: Dict, summary: Dict, soil_data: Dict = None
    ) -> None:
        console.print(Rule("[bold green]🔬  ANÁLISE INTEGRADA — SATÉLITE + ESTAÇÃO + SOLO[/bold green]"))
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
                f"[1] NDVI recuou [bold]{drop:.1f}%[/bold] vs baseline, enquanto precipitação "
                f"atingiu [bold]{prcp:.1f} mm[/bold] ({pct:.0f}% do esperado) — "
                f"[bold]sinais convergentes[/bold]."
            )

        ndwi_e = cop.get("NDWI", {}).get("event_mean")
        ndmi_e = cop.get("NDMI", {}).get("event_mean")
        if ndwi_e is not None and ndmi_e is not None:
            if self.event_type == "seca" and ndwi_e < 0 and ndmi_e < 0:
                lines.append(
                    f"[2] NDWI ({ndwi_e:.4f}) e NDMI ({ndmi_e:.4f}) negativos simultaneamente — "
                    f"padrão diagnóstico de déficit hídrico real."
                )

        if phase_name not in ("desconhecida", "fora do ciclo"):
            lines.append(
                f"[3] Evento na fase [bold]{phase_name}[/bold] "
                f"({phase.get('description','')}) — "
                f"sensibilidade [bold]{sensitivity*100:.0f}%[/bold]."
            )

        vhi_e = cop.get("VHI", {}).get("event_mean")
        if vhi_e is not None:
            lines.append(
                f"[4] VHI = [bold {'red' if vhi_e < 40 else 'yellow'}]{vhi_e:.1f}[/bold {'red' if vhi_e < 40 else 'yellow'}] — "
                f"{'estresse severo confirmado (< 40)' if vhi_e < 40 else 'zona de alerta'}."
            )

        # Solo na análise cruzada
        if soil_data and not soil_data.get("error"):
            soil_check = analysis.get("soil_check", {})
            amplifier  = soil_check.get("amplifier", 1.0) if soil_check else 1.0
            sname      = soil_data.get("resolved_name") or soil_data.get("soil_name", "N/D")
            retencao   = soil_data.get("water_props", {}).get("retencao", "média")
            if amplifier > 1.0:
                lines.append(
                    f"[5] Solo [bold]{sname}[/bold] (retenção: {retencao}) "
                    f"[bold red]amplifica[/bold red] o dano em {amplifier:.2f}x — "
                    f"incorporado na estimativa de perda."
                )
            elif amplifier < 1.0:
                lines.append(
                    f"[5] Solo [bold]{sname}[/bold] (retenção: {retencao}) "
                    f"[bold green]atenua[/bold green] o dano em {amplifier:.2f}x — "
                    f"incorporado na estimativa de perda."
                )

        console.print(Panel(
            "\n\n".join(lines),
            title="[bold]Cruzamento de Evidências[/bold]",
            border_style="green",
        ))
        console.print()

    # ── checklist ─────────────────────────────────────────────────────────────

    def _checks_section(self, analysis: Dict) -> None:
        console.print(Rule("[bold]🔎  CHECKLIST DE VALIDAÇÃO[/bold]"))
        console.print()
        tbl = Table(box=box.ROUNDED, show_header=True, header_style="bold")
        tbl.add_column("#",        justify="right", style="dim", min_width=3)
        tbl.add_column("Critério", min_width=45)
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
            f"  Critérios: [bold]{sm.get('checks_total',0)}[/bold]  |  "
            f"Aprovados: [bold green]{sm.get('checks_passed',0)}[/bold green]  |  "
            f"Score: [bold]{sm.get('score_raw','N/D')}[/bold] ({sm.get('pct_score','N/D')})  |  "
            f"Cumpridos: [bold cyan]{sm.get('pct_criteria',0)}%[/bold cyan]"
        )
        console.print()

    # ── perdas ────────────────────────────────────────────────────────────────

    def _loss_section(self, analysis: Dict, hist_baseline: Dict = None) -> None:
        loss = analysis.get("loss_estimate", {})
        if not loss:
            return
        console.print(Rule("[bold red]📉  ESTIMATIVA DE PERDAS ECONÔMICAS[/bold red]"))
        console.print()

        tbl = Table.grid(padding=(0, 4))
        tbl.add_column(justify="left",  style="dim")
        tbl.add_column(justify="right", style="bold")
        tbl.add_row("Área total:",                   f"{loss.get('area_ha','N/D'):.1f} ha")
        tbl.add_row("Produtividade esperada:",        f"{loss.get('expected_yield_sacas_ha','N/D')} sc/ha")

        hist = loss.get("hist_baseline") or hist_baseline
        if hist and hist.get("local_yield_est_sacas_ha"):
            ly  = hist["local_yield_est_sacas_ha"]
            ny  = hist.get("n_years", "?")
            yrs = hist.get("years_used", "")
            tbl.add_row("[cyan]Referência histórica local:[/cyan]",
                        f"[cyan]~{ly} sc/ha[/cyan] [dim](base: {ny} anos — {yrs})[/dim]")

        # Solo amplificador
        soil_amp = loss.get("soil_amplifier")
        if soil_amp:
            amp_color = "red" if soil_amp["amplifier"] > 1.0 else "green"
            tbl.add_row(
                "[cyan]Fator de amplificação do solo:[/cyan]",
                f"[{amp_color}]{soil_amp['amplifier']:.2f}x[/{amp_color}] "
                f"[dim]({soil_amp['soil_name']} — AWC {soil_amp['AWC']} mm/m)[/dim]"
            )

        tbl.add_row("Produtividade estimada real:",  f"{loss.get('estimated_yield_sacas_ha','N/D')} sc/ha")
        tbl.add_row("Perda de produtividade:",        f"[red]{_pct(loss.get('yield_loss_pct',0))}[/red]")
        tbl.add_row("Perda total (sacas):",           f"[red]{loss.get('yield_loss_total_sacas',0):,.0f} sacas[/red]")
        tbl.add_row("Preço referência:",              f"{_brl(loss.get('price_brl_saca',0))}/saca")
        tbl.add_row("", "")
        tbl.add_row("Receita esperada:",              f"[green]{_brl(loss.get('expected_revenue_brl',0))}[/green]")
        tbl.add_row("Receita estimada real:",         f"[yellow]{_brl(loss.get('estimated_revenue_brl',0))}[/yellow]")
        tbl.add_row("[bold red]PERDA FINANCEIRA ESTIMADA:[/bold red]",
                    f"[bold red]{_brl(loss.get('financial_loss_brl',0))}[/bold red]")

        comp   = loss.get("loss_frac_components", {})
        amp_v  = comp.get("soil_amplifier", 1.0)
        detail = (
            f"\n  Componentes da estimativa:\n"
            f"    • Déficit climático (Poseidon): {comp.get('climate_loss','N/D')}%\n"
            f"    • Anomalia satelital (NDVI):   {comp.get('ndvi_loss','N/D')}%\n"
            f"    • Sensibilidade fenológica:    {comp.get('phase_sensitivity','N/D')}%\n"
            f"    • Amplificador solo:           {amp_v:.2f}x"
        )
        console.print(Panel(tbl, title="[bold]Impacto Econômico Estimado[/bold]",
                            border_style="red", subtitle="[dim]Valores estimativos — ref. CEPEA[/dim]"))
        console.print(f"[dim]{detail}[/dim]")
        console.print()

    # ── veredicto ─────────────────────────────────────────────────────────────

    def _verdict_section(self, analysis: Dict) -> None:
        verdict    = analysis.get("verdict", "INCONCLUSIVO")
        confidence = analysis.get("confidence", 0)
        color      = _verdict_color(verdict)
        icons      = {"CONFIRMADO": "✅", "INCONCLUSIVO": "⚠️", "NÃO CONFIRMADO": "❌"}
        icon       = icons.get(verdict, "❓")
        loss       = analysis.get("loss_estimate", {})
        loss_pct   = loss.get("yield_loss_pct", 0)
        loss_fin   = loss.get("financial_loss_brl", 0)
        phase_info = analysis.get("phase_info", {})

        justification = self._build_justification(verdict, confidence, loss_pct, loss_fin, phase_info, analysis)
        verdict_text  = (
            f"[bold {color}]{icon}  VEREDITO: {verdict}[/bold {color}]\n"
            f"[bold]Nível de Confiança: {confidence:.0f}%[/bold]"
            + (f"  |  [bold]Severidade: {analysis.get('severity','N/D')} "
               f"(IDW {analysis.get('idw_score',0):.0f}/100)[/bold]"
               if analysis.get("idw_score") else "")
            + f"\n\n{justification}"
        )
        console.print(Panel(
            verdict_text,
            title="[bold white]RESULTADO FINAL[/bold white]",
            border_style=color, padding=(1, 2),
        ))
        console.print()
        console.print(Rule("[dim]Relatório gerado pelo sistema Poseidon-Copernicus-EMBRAPA Validator[/dim]"))
        console.print()

    def _build_justification(
        self, verdict, confidence, loss_pct, loss_fin, phase_info, analysis
    ) -> str:
        event_lbl   = self.EVENT_LABELS.get(self.event_type, self.event_type)
        crop        = self.crop_params["name_pt"]
        phase       = phase_info.get("phase", "desconhecida")
        sens        = phase_info.get("sensitivity", 0) * 100
        soil_check  = analysis.get("soil_check", {})
        soil_note   = ""
        if soil_check and soil_check.get("available"):
            amp = soil_check.get("amplifier", 1.0)
            soil_note = (
                f" O solo {soil_check.get('soil_name','N/D')} "
                f"({'amplificou' if amp > 1.0 else 'atenuou'} o dano em {amp:.2f}x)."
            )

        if verdict == "CONFIRMADO":
            return (
                f"Dados satelitais (Copernicus/Sentinel-2) e rede meteorológica Poseidon "
                f"apresentam evidências convergentes de [bold]{event_lbl}[/bold]. "
                f"Fase fenológica: [bold]{phase}[/bold] (sensibilidade {sens:.0f}%).{soil_note} "
                f"Perda estimada: [bold red]{loss_pct:.1f}%[/bold red] "
                f"([bold red]{_brl(loss_fin)}[/bold red]). "
                f"[bold]SINISTRO VALIDADO com {confidence:.0f}% de confiança.[/bold]"
            )
        elif verdict == "INCONCLUSIVO":
            return (
                f"Sinais parciais de [bold]{event_lbl}[/bold] detectados, porém sem evidência "
                f"suficiente para confirmação definitiva ({confidence:.0f}%)."
                f"{soil_note} Recomenda-se análise complementar e vistoria presencial."
            )
        else:
            return (
                f"Dados não corroboram a alegação de [bold]{event_lbl}[/bold] "
                f"({confidence:.0f}% de confiança).{soil_note} [bold]SINISTRO NÃO VALIDADO.[/bold]"
            )
