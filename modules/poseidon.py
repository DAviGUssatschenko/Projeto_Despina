"""
modules/poseidon.py
Conexão com PostgreSQL Poseidon, busca espacial de pontos vizinhos,
interpolação IDW e votação 3/4 para validação do evento.
"""

from __future__ import annotations
import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

from config import POSEIDON_TABLES, POSEIDON_GRID_STEP, CLIMATE_NORMALS_RS


# ─────────────────────────────────────────────────────────────────────────────
# Utilitários geométricos
# ─────────────────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância haversine em km entre dois pontos lat/lon."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _haversine_vec(lat: float, lon: float,
                   lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Haversine vetorizado: distância de 1 ponto para N pontos (km)."""
    R = 6371.0
    dlat = np.radians(lats - lat)
    dlon = np.radians(lons - lon)
    a = (np.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat)) * np.cos(np.radians(lats)) * np.sin(dlon / 2) ** 2)
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ─────────────────────────────────────────────────────────────────────────────
# Conector Poseidon
# ─────────────────────────────────────────────────────────────────────────────

class PoseidonConnector:
    """Acessa o banco Poseidon e fornece dados climáticos interpolados."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._points_cache: Optional[pd.DataFrame] = None

    # ── conexão ──────────────────────────────────────────────────────────────

    def connect(self) -> None:
        self._conn = psycopg2.connect(self.db_url)

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def _cursor(self):
        if not self._conn or self._conn.closed:
            self.connect()
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── cache de coordenadas ──────────────────────────────────────────────────

    def _load_points(self) -> pd.DataFrame:
        """Carrega todos os pontos do Poseidon em memória (cache)."""
        if self._points_cache is not None:
            return self._points_cache
        with self._cursor() as cur:
            cur.execute(f"SELECT point_id, latitude, longitude, elevation_m "
                        f"FROM {POSEIDON_TABLES['coordinates']}")
            rows = cur.fetchall()
        df = pd.DataFrame(rows)
        df["latitude"]  = df["latitude"].astype(float)
        df["longitude"] = df["longitude"].astype(float)
        self._points_cache = df
        return df

    # ── busca espacial ────────────────────────────────────────────────────────

    def find_nearest_point(self, lat: float, lon: float) -> Dict:
        """Retorna o ponto Poseidon mais próximo de (lat, lon)."""
        pts   = self._load_points()
        dists = _haversine_vec(lat, lon, pts["latitude"].values, pts["longitude"].values)
        return pts.iloc[int(np.argmin(dists))].to_dict()

    def find_cardinal_neighbors(self, lat: float, lon: float,
                                 grid_step: float = POSEIDON_GRID_STEP
                                 ) -> Dict[str, Optional[Dict]]:
        """
        Encontra os 4 vizinhos cardinais (N, S, L, O) do ponto central.
        Retorna o ponto Poseidon mais próximo de cada direção.
        """
        targets = {
            "N": (lat + grid_step, lon),
            "S": (lat - grid_step, lon),
            "L": (lat,             lon + grid_step),
            "O": (lat,             lon - grid_step),
        }
        pts      = self._load_points()
        lats_arr = pts["latitude"].values
        lons_arr = pts["longitude"].values
        max_dist = haversine_km(lat, lon, lat + grid_step * 1.5, lon)
        neighbors: Dict[str, Optional[Dict]] = {}

        for direction, (tlat, tlon) in targets.items():
            dists    = _haversine_vec(tlat, tlon, lats_arr, lons_arr)
            best_idx = int(np.argmin(dists))
            neighbors[direction] = (
                pts.iloc[best_idx].to_dict() if dists[best_idx] <= max_dist else None
            )

        return neighbors

    # ── dados climáticos ──────────────────────────────────────────────────────

    def get_weather_data(
        self,
        point_ids: List[int],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Busca dados meteorológicos diários para os point_ids e período."""
        if not point_ids:
            return pd.DataFrame()
        placeholders = ",".join(["%s"] * len(point_ids))
        query = f"""
            SELECT date, point_id,
                   tmin, tmax, tavg,
                   rh_min, rh_max, rh_avg,
                   prcp,
                   wspd_min, wspd_max, wspd_avg
            FROM   {POSEIDON_TABLES['weather']}
            WHERE  point_id IN ({placeholders})
              AND  date BETWEEN %s AND %s
            ORDER  BY date, point_id
        """
        with self._cursor() as cur:
            cur.execute(query, [*point_ids, start_date, end_date])
            rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        numeric_cols = ["tmin", "tmax", "tavg", "rh_min", "rh_max", "rh_avg",
                        "prcp", "wspd_min", "wspd_max", "wspd_avg"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        return df

    # ── interpolação IDW ──────────────────────────────────────────────────────

    def idw_interpolate(
        self,
        center_lat: float,
        center_lon: float,
        neighbors: Dict[str, Optional[Dict]],
        start_date: date,
        end_date: date,
        power: float = 2.0,
    ) -> pd.DataFrame:
        """
        Interpolação por distância inversa (IDW) dos 4 vizinhos cardinais
        para o ponto central da fazenda.
        """
        valid_neighbors = {k: v for k, v in neighbors.items() if v is not None}
        if not valid_neighbors:
            raise ValueError("Nenhum vizinho Poseidon encontrado na região.")

        point_ids = [v["point_id"] for v in valid_neighbors.values()]
        weather   = self.get_weather_data(point_ids, start_date, end_date)

        if weather.empty:
            return pd.DataFrame()

        numeric_cols = ["tmin", "tmax", "tavg", "rh_min", "rh_max", "rh_avg",
                        "prcp", "wspd_min", "wspd_max", "wspd_avg"]

        # Calcula pesos IDW por distância ao centróide da fazenda
        weights: Dict[int, float] = {}
        for v in valid_neighbors.values():
            pid  = v["point_id"]
            dist = max(haversine_km(center_lat, center_lon,
                                    v["latitude"], v["longitude"]), 0.1)
            weights[pid] = 1.0 / (dist ** power)

        total_weight = sum(weights.values())
        for pid in weights:
            weights[pid] /= total_weight

        # Peso de cada linha como coluna — evita iterrows
        weather["_w"] = weather["point_id"].map(weights).fillna(0.0)

        # Média ponderada vetorizada por data
        records = []
        for dt, grp in weather.groupby("date"):
            row: Dict = {"date": dt}
            w_arr = grp["_w"].values
            for col in numeric_cols:
                vals  = grp[col].values.astype(float)
                valid = ~np.isnan(vals)
                w_v   = w_arr[valid]
                w_sum = w_v.sum()
                row[col] = round(float(np.dot(w_v, vals[valid])) / w_sum, 4) if w_sum > 0 else 0.0
            records.append(row)

        weather.drop(columns=["_w"], inplace=True)
        return pd.DataFrame(records)

    # ── avaliação climática por score IDW ────────────────────────────────────

    def vote_3of4(
        self,
        neighbors: Dict[str, Optional[Dict]],
        start_date: date,
        end_date: date,
        event_type: str,
        thresholds: Dict,
        center_lat: Optional[float] = None,
        center_lon: Optional[float] = None,
    ) -> Dict:
        """
        Avalia o sinal climático via score de intensidade de anomalia (0–100)
        ponderado pelo inverso da distância ao centróide da fazenda (IDW).

        Substitui a votação binária 3/4 porque:
        - Eventos reais raramente fazem TODOS os vizinhos cruzar um limiar duro.
        - Um ponto com 60% do normal de chuva é evidência real — não deve ser
          descartado como "não confirma".
        - A intensidade da anomalia importa tanto quanto a contagem de pontos.

        Aprovado se weighted_score >= 35 (sinal fraco-a-moderado confirmado).
        """
        valid = {k: v for k, v in neighbors.items() if v is not None}
        if len(valid) < 2:
            return {
                "passed":         False,
                "votes":          {},
                "score":          0,
                "total":          len(valid),
                "weighted_score": 0.0,
                "signal_level":   "insuficiente",
                "description":    "Pontos insuficientes para análise climática.",
            }

        point_ids = [v["point_id"] for v in valid.values()]
        weather   = self.get_weather_data(point_ids, start_date, end_date)

        # Calcula intensidade por ponto e peso IDW
        votes: Dict[str, Dict] = {}
        idw_weights: Dict[str, float] = {}

        for direction, point in valid.items():
            pid     = point["point_id"]
            pt_data = weather[weather["point_id"] == pid]
            result  = self._evaluate_point_for_event(
                pt_data, event_type, thresholds, start_date, end_date
            )
            result["point_id"]  = pid
            result["lat"]       = round(point["latitude"], 5)
            result["lon"]       = round(point["longitude"], 5)
            result["direction"] = direction
            # Backward-compat: "confirmed" se intensidade >= 40
            result["confirmed"] = result.get("intensity", 0) >= 40
            votes[direction] = result

            # Peso IDW: usa centróide se disponível, senão peso uniforme
            if center_lat is not None and center_lon is not None:
                dist_km = max(haversine_km(center_lat, center_lon,
                                           point["latitude"], point["longitude"]), 0.1)
                idw_weights[direction] = 1.0 / (dist_km ** 2)
            else:
                idw_weights[direction] = 1.0

        # Score ponderado (0–100)
        total_w   = sum(idw_weights.values())
        w_score   = sum(
            idw_weights[d] * votes[d].get("intensity", 0)
            for d in votes
        ) / total_w if total_w > 0 else 0.0
        weighted_score = round(w_score, 1)

        # Nível de sinal
        if weighted_score >= 70:
            signal_level = "muito forte"
        elif weighted_score >= 50:
            signal_level = "forte"
        elif weighted_score >= 35:
            signal_level = "moderado"
        elif weighted_score >= 20:
            signal_level = "fraco"
        else:
            signal_level = "ausente"

        confirmed_count = sum(1 for v in votes.values() if v["confirmed"])
        passed          = weighted_score >= 35

        return {
            "passed":         passed,
            "votes":          votes,
            "score":          confirmed_count,
            "total":          len(votes),
            "weighted_score": weighted_score,
            "signal_level":   signal_level,
            "description": (
                f"Score climático IDW: {weighted_score:.0f}/100 — "
                f"sinal {signal_level} "
                f"({'✅ APROVADO' if passed else '❌ REPROVADO'})"
            ),
        }

    def _evaluate_point_for_event(
        self,
        df: pd.DataFrame,
        event_type: str,
        thresholds: Dict,
        start_date: date,
        end_date: date,
    ) -> Dict:
        """
        Calcula a INTENSIDADE da anomalia (0–100) para um único ponto Poseidon.

        Cada variável contribui com uma fração proporcional ao desvio em relação
        ao normal — quanto maior o desvio, maior a contribuição.

        Escala de referência:
          0–20  → sem anomalia significativa
          20–40 → anomalia fraca
          40–60 → anomalia moderada (antes exigia limiar binário)
          60–80 → anomalia forte
          80–100 → anomalia extrema
        """
        if df.empty:
            return {"confirmed": False, "intensity": 0, "reason": "Sem dados para o período."}

        period_days  = (end_date - start_date).days + 1
        pos_thresh   = thresholds.get("poseidon", {})
        center_month = (start_date.month + end_date.month) // 2 or start_date.month
        months_span  = max(period_days / 30, 1)

        if event_type == "seca":
            total_prcp   = df["prcp"].sum()
            normal_prcp  = CLIMATE_NORMALS_RS.get(center_month, {}).get("prcp_mm", 110) * months_span
            prcp_pct     = (total_prcp / normal_prcp * 100) if normal_prcp > 0 else 100
            tavg_mean    = df["tavg"].mean()
            normal_tavg  = CLIMATE_NORMALS_RS.get(center_month, {}).get("tavg_c", 22)
            tavg_anomaly = tavg_mean - normal_tavg
            rh_avg_mean  = df["rh_avg"].mean()

            # Déficit hídrico: 0% prcp = 60pts | 40% prcp = 36pts | 80% = 12pts | 100% = 0pts
            prcp_score = max(0.0, (100.0 - prcp_pct) / 100.0 * 60.0)
            # Temperatura acima do normal: +5°C = 25pts (linear)
            temp_score = min(max(tavg_anomaly, 0.0), 5.0) / 5.0 * 25.0
            # Umidade abaixo do normal: RH 40% = 15pts | RH 70% = 0pts
            rh_score   = max(0.0, min(70.0 - rh_avg_mean, 30.0)) / 30.0 * 15.0
            intensity  = round(prcp_score + temp_score + rh_score, 1)

            # Backward-compat: limiar original era prcp_pct < 40 AND (temp OR rh)
            confirmed_legacy = (
                prcp_pct < pos_thresh.get("prcp_deficit_pct", 40) and
                (tavg_anomaly > pos_thresh.get("tavg_anomaly_c", 2.0) or
                 rh_avg_mean  < pos_thresh.get("rh_avg_max",   60.0))
            )
            return {
                "confirmed":      confirmed_legacy,
                "intensity":      intensity,
                "prcp_total_mm":  round(total_prcp, 1),
                "prcp_normal_mm": round(normal_prcp, 1),
                "prcp_pct":       round(prcp_pct, 1),
                "tavg_mean_c":    round(tavg_mean, 2),
                "tavg_anomaly":   round(tavg_anomaly, 2),
                "rh_avg":         round(rh_avg_mean, 1),
                "reason": (
                    f"Prcp {prcp_pct:.0f}% do normal | "
                    f"Tmed anomalia {tavg_anomaly:+.1f}°C | "
                    f"UR {rh_avg_mean:.0f}% | Intensidade {intensity:.0f}/100"
                ),
            }

        elif event_type == "chuva":
            total_prcp   = df["prcp"].sum()
            normal_prcp  = CLIMATE_NORMALS_RS.get(center_month, {}).get("prcp_mm", 110) * months_span
            prcp_pct     = (total_prcp / normal_prcp * 100) if normal_prcp > 0 else 100
            rh_avg_mean  = df["rh_avg"].mean()
            wspd_max_max = df["wspd_max"].max()

            # Excesso de chuva: 150% excesso acima do normal = 65pts
            excess_pct  = max(0.0, prcp_pct - 100.0)
            prcp_score  = min(excess_pct / 150.0, 1.0) * 65.0
            # Umidade alta: RH 100% = 25pts (a partir de 75%)
            rh_score    = max(0.0, rh_avg_mean - 75.0) / 25.0 * 25.0
            # Vento: 80 km/h = 10pts
            wind_score  = min(max(wspd_max_max - 20.0, 0.0) / 60.0, 1.0) * 10.0
            intensity   = round(prcp_score + rh_score + wind_score, 1)

            confirmed_legacy = (
                prcp_pct > pos_thresh.get("prcp_excess_pct", 150) or
                (rh_avg_mean > pos_thresh.get("rh_avg_min", 85.0) and prcp_pct > 120)
            )
            return {
                "confirmed":     confirmed_legacy,
                "intensity":     intensity,
                "prcp_total_mm": round(total_prcp, 1),
                "prcp_pct":      round(prcp_pct, 1),
                "rh_avg":        round(rh_avg_mean, 1),
                "wspd_max":      round(wspd_max_max, 1),
                "reason": (
                    f"Prcp {prcp_pct:.0f}% do normal | "
                    f"UR {rh_avg_mean:.0f}% | Rajada {wspd_max_max:.1f} km/h | "
                    f"Intensidade {intensity:.0f}/100"
                ),
            }

        elif event_type == "geada":
            frost_days  = int((df["tmin"] < pos_thresh.get("tmin_threshold", 2.0)).sum())
            consecutive = self._max_consecutive(
                df["tmin"] < pos_thresh.get("tmin_threshold", 2.0)
            )
            tmin_abs = df["tmin"].min()

            # Dias de geada: 5+ dias = 50pts
            days_score  = min(frost_days / 5.0, 1.0) * 50.0
            # Consecutivos: 3+ dias = 30pts
            consec_score = min(consecutive / 3.0, 1.0) * 30.0
            # Profundidade: tmin -5°C = 20pts (de +2°C a -5°C = 7°C range)
            depth_score = max(0.0, min(2.0 - tmin_abs, 7.0)) / 7.0 * 20.0
            intensity   = round(days_score + consec_score + depth_score, 1)

            confirmed_legacy = consecutive >= pos_thresh.get("consecutive_days", 2)
            return {
                "confirmed":   confirmed_legacy,
                "intensity":   intensity,
                "frost_days":  frost_days,
                "consecutive": int(consecutive),
                "tmin_abs":    round(tmin_abs, 2),
                "reason": (
                    f"{frost_days} dias tmin < {pos_thresh.get('tmin_threshold',2)}°C | "
                    f"Consecutivos: {consecutive} | "
                    f"Tmin abs: {tmin_abs:.1f}°C | Intensidade {intensity:.0f}/100"
                ),
            }

        elif event_type == "granizo":
            heavy_rain_days = int((df["prcp"]     > pos_thresh.get("prcp_daily_max",     30)).sum())
            high_wind_days  = int((df["wspd_max"]  > pos_thresh.get("wspd_max_threshold", 40)).sum())
            wspd_max_max    = df["wspd_max"].max()

            # Chuva intensa: 2+ dias = 50pts
            rain_score  = min(heavy_rain_days / 2.0, 1.0) * 50.0
            # Vento forte: 2+ dias = 30pts
            wind_score  = min(high_wind_days  / 2.0, 1.0) * 30.0
            # Bônus intensidade: 80+ km/h = 20pts extras
            bonus_score = min(max(wspd_max_max - 40.0, 0.0) / 40.0, 1.0) * 20.0
            intensity   = round(rain_score + wind_score + bonus_score, 1)

            confirmed_legacy = heavy_rain_days >= 1 and high_wind_days >= 1
            return {
                "confirmed":       confirmed_legacy,
                "intensity":       intensity,
                "heavy_rain_days": heavy_rain_days,
                "high_wind_days":  high_wind_days,
                "prcp_max_day":    round(df["prcp"].max(), 1),
                "wspd_max":        round(wspd_max_max, 1),
                "reason": (
                    f"Chuva intensa: {heavy_rain_days}d | "
                    f"Vento forte: {high_wind_days}d | "
                    f"Rajada máx {wspd_max_max:.1f} km/h | "
                    f"Intensidade {intensity:.0f}/100"
                ),
            }

        return {"confirmed": False, "intensity": 0, "reason": "Tipo de evento não suportado."}

    def summarize_nearest(
        self,
        nearest: Dict,
        start_date: date,
        end_date: date,
    ) -> Dict:
        """Busca dados do ponto mais próximo (sem IDW). 1 query SQL."""
        pid = nearest["point_id"]
        df  = self.get_weather_data([pid], start_date, end_date)
        if df.empty:
            return {}
        return self.summarize_period(df, start_date, end_date)

    @staticmethod
    def _max_consecutive(bool_series) -> int:
        """Conta o máximo de dias consecutivos True em uma série booleana."""
        max_run = cur_run = 0
        for v in bool_series:
            if v:
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 0
        return max_run

    def get_historical_baseline(
        self,
        nearest: Dict,
        start_date: date,
        end_date: date,
        years_back: int = 4,
    ) -> Dict:
        """
        Busca dados históricos do mesmo ponto nos anos anteriores.
        Uma única query SQL batched (IN + BETWEEN por union) em vez de
        N queries sequenciais — reduz round-trips ao banco de ~4x.
        """
        from datetime import date as date_cls

        pid        = nearest["point_id"]
        periods    = []
        years_map  = {}   # year_label → ano real para legibilidade

        for delta in range(1, years_back + 1):
            try:
                ys = date_cls(start_date.year - delta, start_date.month, start_date.day)
                ye = date_cls(end_date.year   - delta, end_date.month,   end_date.day)
            except ValueError:
                continue
            periods.append((ys, ye))
            years_map[ys.year] = delta

        if not periods:
            return {}

        # ── Uma query com OR de períodos ───────────────────────────────────
        where_clauses = " OR ".join(
            f"(date BETWEEN %s AND %s)" for _ in periods
        )
        params: list = [pid]
        for ys, ye in periods:
            params += [ys, ye]

        query = f"""
            SELECT date, prcp, tavg
            FROM   {POSEIDON_TABLES['weather']}
            WHERE  point_id = %s
              AND  ({where_clauses})
            ORDER  BY date
        """
        with self._cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        if not rows:
            return {}

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df["prcp"] = pd.to_numeric(df["prcp"], errors="coerce")
        df["tavg"] = pd.to_numeric(df["tavg"], errors="coerce")

        # Agrupa por ano e descarta períodos com < 20 obs
        all_prcps  = []
        all_tavgs  = []
        years_used = []

        for ys, ye in periods:
            mask = (df["date"].dt.date >= ys) & (df["date"].dt.date <= ye)
            chunk = df[mask]
            if len(chunk) < 20:
                continue
            all_prcps.append(float(chunk["prcp"].sum()))
            all_tavgs.append(float(chunk["tavg"].mean()))
            years_used.append(ys.year)

        if not all_prcps:
            return {}

        return {
            "prcp_mean_mm":  round(float(np.mean(all_prcps)), 1),
            "prcp_std_mm":   round(float(np.std(all_prcps)),  1),
            "tavg_mean_c":   round(float(np.mean(all_tavgs)),  2),
            "years_used":    years_used,
            "n_years":       len(years_used),
        }

    # ── sumarização do período ────────────────────────────────────────────────

    def summarize_period(
        self,
        interpolated_df: pd.DataFrame,
        start_date: date,
        end_date: date,
    ) -> Dict:
        """Retorna estatísticas resumidas do período interpolado."""
        if interpolated_df.empty:
            return {}
        df = interpolated_df.copy()
        period_days = (end_date - start_date).days + 1

        return {
            "period_days":      period_days,
            "prcp_total_mm":    round(df["prcp"].sum(), 1),
            "prcp_max_day_mm":  round(df["prcp"].max(), 1),
            "prcp_days":        int((df["prcp"] > 1).sum()),
            "tavg_mean_c":      round(df["tavg"].mean(), 2),
            "tmax_abs_c":       round(df["tmax"].max(), 2),
            "tmin_abs_c":       round(df["tmin"].min(), 2),
            "rh_avg_mean_pct":  round(df["rh_avg"].mean(), 1),
            "wspd_max_kmh":     round(df["wspd_max"].max(), 1),
            "wspd_avg_kmh":     round(df["wspd_avg"].mean(), 1),
        }
