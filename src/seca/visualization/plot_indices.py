"""
plot_indices.py
---------------
Gera imagens PNG por índice por data e painéis temporais comparativos.

Uso:
    python src/seca/visualization/plot_indices.py

Saída:
    reports/figures/case_*/
        imagens/
            NBR/  NBR_{data}.png  (1 imagem por índice por data)
            NDRE/ ...
            painel_NBR.png        (todas as datas lado a lado)
            painel_geral.png      (todos os índices × todas as datas)
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import rasterio
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

INPUT_DIR  = Path("data/processed/output_indices")
OUTPUT_DIR = Path("reports/figures")
ONLY_CASE  = None
DPI        = 150

INDEX_CONFIG = {
    "NBR":   {"band": 1, "vmin": -0.3, "vmax":  0.7, "cmap": "RdYlGn",
              "label": "NBR — Estresse severo / Saúde geral",
              "note":  "↑ saudável  |  ↓ seca/queimada  |  <0 = solo exposto"},
    "NDRE":  {"band": 2, "vmin":  0.0, "vmax":  0.6, "cmap": "YlGn",
              "label": "NDRE — Clorofila (Red-Edge)",
              "note":  "↑ clorofila alta  |  ↓ amarelamento  |  <0.15 = estresse"},
    "MSI":   {"band": 3, "vmin":  0.0, "vmax":  2.5, "cmap": "RdYlBu_r",
              "label": "MSI — Estresse Hídrico",
              "note":  "↑ mais SECO (!)  |  ↓ mais úmido  |  >1.2 = severo"},
    "GNDVI": {"band": 4, "vmin":  0.0, "vmax":  0.8, "cmap": "YlGn",
              "label": "GNDVI — Biomassa / N Foliar",
              "note":  "↑ vigor alto  |  ↓ estresse  |  <0.2 = solo nu"},
    "SAVI":  {"band": 5, "vmin":  0.0, "vmax":  0.6, "cmap": "RdYlGn",
              "label": "SAVI — Cobertura Vegetal (corr. solo)",
              "note":  "↑ lavoura fechada  |  ↓ solo exposto  |  <0.1 = falha"},
    "NDDI":  {"band": 6, "vmin": -0.2, "vmax":  0.8, "cmap": "RdYlBu_r",
              "label": "NDDI — Índice de Seca Combinado",
              "note":  "↑ seca intensa  |  ↓ úmido  |  >0.3 = estresse"},
}

# =============================================================================

def read_band(tif_path, band_idx, vmin, vmax):
    with rasterio.open(tif_path) as src:
        data   = src.read(band_idx).astype(np.float32)
        nodata = src.nodata
    if nodata is not None:
        data[data == nodata] = np.nan
    data[~np.isfinite(data)] = np.nan
    return np.clip(data, vmin - 0.5, vmax + 0.5)


def plot_single(data, title, cfg, out_path):
    fig, ax = plt.subplots(figsize=(5, 5), dpi=DPI)
    im = ax.imshow(data, cmap=cfg["cmap"], vmin=cfg["vmin"], vmax=cfg["vmax"],
                   interpolation="bilinear")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04).ax.tick_params(labelsize=8)
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)
    ax.set_xlabel(cfg["note"], fontsize=7, color="gray")
    ax.axis("off")
    plt.tight_layout()
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def plot_temporal_panel(tif_files, dates, idx_name, cfg, out_path, case_title):
    n = len(tif_files)
    fig, axes = plt.subplots(1, n, figsize=(4 * n, 5), dpi=DPI)
    if n == 1: axes = [axes]

    for ax, tif_path, date in zip(axes, tif_files, dates):
        data = read_band(tif_path, cfg["band"], cfg["vmin"], cfg["vmax"])
        im   = ax.imshow(data, cmap=cfg["cmap"], vmin=cfg["vmin"], vmax=cfg["vmax"],
                         interpolation="bilinear")
        ax.set_title(date, fontsize=9, fontweight="bold")
        ax.axis("off")
        valid = data[np.isfinite(data)]
        valid = valid[(valid >= cfg["vmin"]) & (valid <= cfg["vmax"])]
        if valid.size > 0:
            ax.text(0.02, 0.02,
                    f"med={np.nanmedian(valid):.3f}\nmean={np.nanmean(valid):.3f}",
                    transform=ax.transAxes, fontsize=7, color="white",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="black", alpha=0.5),
                    va="bottom")

    fig.subplots_adjust(right=0.88, wspace=0.05)
    cbar_ax = fig.add_axes([0.90, 0.15, 0.02, 0.7])
    sm = plt.cm.ScalarMappable(cmap=cfg["cmap"],
                               norm=mcolors.Normalize(cfg["vmin"], cfg["vmax"]))
    sm.set_array([])
    fig.colorbar(sm, cax=cbar_ax).ax.tick_params(labelsize=8)
    fig.suptitle(f"{case_title}\n{cfg['label']}", fontsize=12,
                 fontweight="bold", y=1.02)
    fig.text(0.5, -0.02, cfg["note"], ha="center", fontsize=8, color="gray")
    plt.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def plot_full_grid(tif_files, dates, out_path, case_title):
    n_dates = len(tif_files)
    n_idx   = len(INDEX_CONFIG)
    idx_list = list(INDEX_CONFIG.items())
    fig, axes = plt.subplots(n_idx, n_dates,
                             figsize=(3.5 * n_dates, 3.2 * n_idx),
                             dpi=max(72, DPI // 2))
    if n_idx == 1:  axes = axes[np.newaxis, :]
    if n_dates == 1: axes = axes[:, np.newaxis]

    for row, (idx_name, cfg) in enumerate(idx_list):
        for col, (tif_path, date) in enumerate(zip(tif_files, dates)):
            ax   = axes[row][col]
            data = read_band(tif_path, cfg["band"], cfg["vmin"], cfg["vmax"])
            ax.imshow(data, cmap=cfg["cmap"], vmin=cfg["vmin"], vmax=cfg["vmax"],
                      interpolation="bilinear")
            valid = data[np.isfinite(data)]
            valid = valid[(valid >= cfg["vmin"]) & (valid <= cfg["vmax"])]
            if valid.size > 0:
                ax.text(0.03, 0.03, f"p50={np.nanmedian(valid):.2f}",
                        transform=ax.transAxes, fontsize=6.5, color="white",
                        bbox=dict(boxstyle="round,pad=0.15", fc="black", alpha=0.55),
                        va="bottom")
            ax.axis("off")
            if row == 0: ax.set_title(date, fontsize=8, fontweight="bold", pad=4)
            if col == 0:
                ax.set_ylabel(idx_name, fontsize=9, fontweight="bold",
                              rotation=0, labelpad=40, va="center")
                ax.yaxis.set_label_position("left")

    fig.suptitle(f"{case_title}\nTodos os Índices × Todas as Datas",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout(h_pad=0.3, w_pad=0.1)
    plt.savefig(out_path, dpi=max(72, DPI // 2), bbox_inches="tight")
    plt.close(fig)
    print(f"  → Painel geral: {out_path.name}")


def process_case(case_dir: Path, out_case_dir: Path):
    tif_files = sorted(case_dir.glob("*.tif"))
    if not tif_files: return

    case_name = case_dir.name
    print(f"\n{'='*55}\n{case_name}  ({len(tif_files)} imagem(ns))")

    dates = []
    for f in tif_files:
        parts    = f.stem.split("_")
        date_str = next((p for p in parts if len(p) == 10 and p[4] == "-"), f.stem)
        dates.append(date_str)

    img_dir = out_case_dir / "imagens"
    img_dir.mkdir(parents=True, exist_ok=True)

    for idx_name, cfg in INDEX_CONFIG.items():
        idx_dir = img_dir / idx_name
        idx_dir.mkdir(exist_ok=True)
        for tif_path, date in zip(tif_files, dates):
            data = read_band(tif_path, cfg["band"], cfg["vmin"], cfg["vmax"])
            plot_single(data, f"{idx_name}  —  {date}", cfg,
                        idx_dir / f"{idx_name}_{date}.png")
        print(f"  ✓ {idx_name}: {len(tif_files)} PNG(s)")

    for idx_name, cfg in INDEX_CONFIG.items():
        plot_temporal_panel(tif_files, dates, idx_name, cfg,
                            img_dir / f"painel_{idx_name}.png", case_name)
    print(f"  ✓ 6 painéis temporais")

    plot_full_grid(tif_files, dates, img_dir / "painel_geral.png", case_name)


def main():
    print("=" * 55)
    print("Visualizador de Índices de Satélite")
    print("=" * 55)

    if ONLY_CASE:
        cases = [(INPUT_DIR / ONLY_CASE, OUTPUT_DIR / ONLY_CASE)]
    else:
        cases = [(d, OUTPUT_DIR / d.name)
                 for d in sorted(INPUT_DIR.iterdir())
                 if d.is_dir() and d.name.startswith("case_")]

    print(f"Casos: {len(cases)}")
    for in_dir, out_dir in cases:
        try: process_case(in_dir, out_dir)
        except Exception as e:
            import traceback
            print(f"[ERRO] {in_dir.name}: {e}"); traceback.print_exc()

    print("\nConcluído.")


if __name__ == "__main__":
    main()
