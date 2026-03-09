"""
modules/copernicus.py
Integration with Copernicus Data Space Ecosystem (CDSE) / Sentinel Hub.
"""

from __future__ import annotations
import time
import json
import hashlib
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
import numpy as np

#simple disk cache
_CACHE_DIR = Path(__file__).parent / ".copernicus_cache"
_CACHE_TTL  = 7 * 24 * 3600   #7 days in seconds

def _cache_key(*parts) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()

def _cache_get(key: str):
    path = _CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data["ts"] > _CACHE_TTL:
            path.unlink(missing_ok=True)
            return None
        return data["value"]
    except Exception:
        return None

def _cache_set(key: str, value) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _CACHE_DIR / f"{key}.json"
        path.write_text(json.dumps({"ts": time.time(), "value": value}))
    except Exception:
        pass  #caching is optional — it never blocks the main stream.

#imports EVERYTHING from the config, including credentials.
from config import (
    CDSE_CLIENT_ID,
    CDSE_CLIENT_SECRET,
    CDSE_TOKEN_URL,
    CDSE_STATS_URL,
    CDSE_CATALOG_URL,
    EVALSCRIPTS,
    SENTINEL2_RESOLUTION,
    MAX_CLOUD_COVER,
    BASELINE_LOOKBACK_DAYS,
)

log = logging.getLogger(__name__)


def _get_token(client_id: str, client_secret: str) -> str:
    resp = requests.post(
        CDSE_TOKEN_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


class CopernicusClient:

    INDICES = list(EVALSCRIPTS.keys())

    def __init__(self):
        #credentials read directly from config.py — no environment variables required.
        self.client_id     = CDSE_CLIENT_ID
        self.client_secret = CDSE_CLIENT_SECRET
        self._token: Optional[str] = None
        self._token_ts: float      = 0.0
        self._token_ttl: float     = 3300.0

    def _auth_headers(self) -> Dict[str, str]:
        now = time.time()
        if not self._token or (now - self._token_ts) > self._token_ttl:
            if not self.client_id or not self.client_secret:
                raise RuntimeError(
                    "Credenciais Copernicus não encontradas em config.py.\n"
                    "Verifique CDSE_CLIENT_ID e CDSE_CLIENT_SECRET no arquivo config.py."
                )
            self._token    = _get_token(self.client_id, self.client_secret)
            self._token_ts = now
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type":  "application/json",
        }

    def get_index_timeseries(
        self,
        geometry: Dict,
        start_date: date,
        end_date: date,
        index_name: str,
        aggregation_days: int = 5,
    ) -> List[Dict]:
        if index_name not in EVALSCRIPTS:
            raise ValueError(f"Índice desconhecido: {index_name}")

        #cache hit
        ck = _cache_key(geometry, str(start_date), str(end_date), index_name, aggregation_days)
        cached = _cache_get(ck)
        if cached is not None:
            return cached

        payload = {
            "input": {
                "bounds": {
                    "geometry": geometry,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "mosaickingOrder": "leastCC",
                        "maxCloudCoverage": MAX_CLOUD_COVER,
                    },
                }],
            },
            "aggregation": {
                "timeRange": {
                    "from": f"{start_date.isoformat()}T00:00:00Z",
                    "to":   f"{end_date.isoformat()}T23:59:59Z",
                },
                "aggregationInterval": {"of": f"P{aggregation_days}D"},
                "evalscript": EVALSCRIPTS[index_name],
                #EPSG:4326 uses degrees as the unit — converts meters to degrees.
                #1 degree ≈ 111,320 m; maintains resolution below the 1500 m/pixel limit.
                "resx": round(SENTINEL2_RESOLUTION / 111_320, 7),
                "resy": round(SENTINEL2_RESOLUTION / 111_320, 7),
            },
            "calculations": {"default": {"statistics": {"default": {
                "percentiles": {"k": [10, 25, 75, 90]}
            }}}},
        }

        resp = requests.post(
            CDSE_STATS_URL,
            headers=self._auth_headers(),
            json=payload,
            timeout=120,
        )

        if resp.status_code == 200:
            result = self._parse_stats_response(resp.json(), index_name)
            _cache_set(ck, result)
            return result
        elif resp.status_code == 429:
            log.warning("Rate limit — aguardando 10s...")
            time.sleep(10)
            return self.get_index_timeseries(geometry, start_date, end_date, index_name, aggregation_days)
        else:
            log.error("Stats API %s: %s", resp.status_code, resp.text[:300])
            return []

    @staticmethod
    def _parse_stats_response(raw: Dict, index_name: str) -> List[Dict]:
        results = []
        for interval in raw.get("data", []):
            stats = (interval.get("outputs", {})
                              .get("default", {})
                              .get("bands", {})
                              .get("B0", {})
                              .get("stats", {}))
            if not stats or stats.get("sampleCount", 0) == 0:
                continue

            def _f(v):
                """Safely converts to float — API can return 'NaN' as a string."""
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return float("nan")

            results.append({
                "index":        index_name,
                "from":         interval["interval"]["from"][:10],
                "to":           interval["interval"]["to"][:10],
                "mean":         round(_f(stats.get("mean")),  5),
                "stdev":        round(_f(stats.get("stdev")), 5),
                "min":          round(_f(stats.get("min")),   5),
                "max":          round(_f(stats.get("max")),   5),
                "p10":          round(_f(stats.get("percentiles", {}).get("10.0")), 5),
                "p90":          round(_f(stats.get("percentiles", {}).get("90.0")), 5),
                "sample_count": stats.get("sampleCount", 0),
            })
        return results

    def _get_cloud_cover_stats(
        self,
        geometry: Dict,
        start_date: date,
        end_date:   date,
    ) -> Dict:
        """Check average cloud cover via the Statistics API (SCL band)."""

        ck = _cache_key("cloud", geometry, str(start_date), str(end_date))
        cached = _cache_get(ck)
        if cached is not None:
            return cached
        evalscript = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["SCL","dataMask"] }],
    output: [
      { id: "cloud_mask", bands: 1, sampleType: "UINT8" },
      { id: "dataMask",   bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  // SCL classes 8=cloud medium, 9=cloud high, 3=shadow
  let is_cloud = (s.SCL == 8 || s.SCL == 9 || s.SCL == 3) ? 1 : 0;
  return { cloud_mask: [is_cloud * s.dataMask], dataMask: [s.dataMask] };
}"""
        payload = {
            "input": {
                "bounds": {
                    "geometry": geometry,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [{"type": "sentinel-2-l2a",
                          "dataFilter": {"mosaickingOrder": "leastCC"}}],
            },
            "aggregation": {
                "timeRange": {
                    "from": f"{start_date.isoformat()}T00:00:00Z",
                    "to":   f"{end_date.isoformat()}T23:59:59Z",
                },
                "aggregationInterval": {"of": "P5D"},
                "evalscript": evalscript,
                "resx": round(60 / 111_320, 7),
                "resy": round(60 / 111_320, 7),
            },
            "calculations": {"default": {"statistics": {"default": {}}}},
        }
        try:
            resp = requests.post(CDSE_STATS_URL, headers=self._auth_headers(),
                                 json=payload, timeout=60)
            if resp.status_code != 200:
                return {}
            intervals = resp.json().get("data", [])
            means = []
            for iv in intervals:
                stats = (iv.get("outputs", {}).get("cloud_mask", {})
                           .get("bands", {}).get("B0", {}).get("stats", {}))
                if stats and stats.get("sampleCount", 0) > 0:
                    means.append(float(stats.get("mean", 0)) * 100)
            if not means:
                return {}
            result = {
                "mean_pct":   round(float(np.mean(means)), 1),
                "max_pct":    round(float(np.max(means)),  1),
                "n_intervals": len(means),
            }
            _cache_set(ck, result)
            return result
        except Exception:
            return {}

    def collect_all_indices(
        self,
        geometry: Dict,
        start_date: date,
        end_date: date,
        baseline_days: int = BASELINE_LOOKBACK_DAYS,
    ) -> Dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        baseline_start = start_date - timedelta(days=baseline_days)
        baseline_end   = start_date - timedelta(days=1)

        print(f"   Coletando {len(self.INDICES)} índices do Sentinel-2 (paralelo)...")
        print(f"   Baseline : {baseline_start} → {baseline_end}")
        print(f"   Evento   : {start_date} → {end_date}")

        #cloud cover
        cloud = self._get_cloud_cover_stats(geometry, start_date, end_date)
        if cloud:
            cloud_mean = cloud["mean_pct"]
            cloud_max  = cloud["max_pct"]
            flag = " ⚠️  ALTA" if cloud_mean > MAX_CLOUD_COVER else ""
            print(f"   ☁  Nuvens período evento: média {cloud_mean:.1f}%  |  máx {cloud_max:.1f}%"
                  f"  |  limiar configurado: {MAX_CLOUD_COVER}%{flag}")
            if cloud_mean > MAX_CLOUD_COVER:
                print(f"   ⚠  Cobertura de nuvens acima do limiar — índices espectrais podem"
                      f" ter baixa qualidade ou N/D nesse período.")

        def _fetch_index(idx_name: str):
            base_series  = self.get_index_timeseries(geometry, baseline_start, baseline_end, idx_name)
            event_series = self.get_index_timeseries(geometry, start_date, end_date, idx_name)
            b = _safe_mean([r["mean"] for r in base_series])
            e = _safe_mean([r["mean"] for r in event_series])
            return idx_name, {
                "baseline_series": base_series,
                "event_series":    event_series,
                "baseline_mean":   b,
                "event_mean":      e,
                "event_min":       _safe_min([r["mean"] for r in event_series]),
                "event_max":       _safe_max([r["mean"] for r in event_series]),
                "observations":    len(event_series),
                "anomaly_abs":     round(e - b, 5) if b and e else None,
                "anomaly_pct":     round((e - b) / abs(b) * 100, 2) if b and e and b != 0 else None,
            }

        results: Dict = {}
        #maximum 8 workers — balances parallelism vs API rate-limit
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_index, idx): idx for idx in self.INDICES}
            for future in as_completed(futures):
                idx_name = futures[future]
                try:
                    name, data = future.result()
                    results[name] = data
                    print(f"   └─ {name}... ✓")
                except Exception as exc:
                    print(f"   └─ {idx_name}... ⚠ {exc}")
                    results[idx_name] = {"error": str(exc)}

        #calculated VHI
        if "NDVI" in results and "NDMI" in results:
            ndvi_e = results["NDVI"].get("event_mean")
            ndmi_e = results["NDMI"].get("event_mean")
            if ndvi_e is not None and ndmi_e is not None:
                vci = _norm100(ndvi_e, 0.1, 0.8)
                tci = _norm100(ndmi_e, -0.3, 0.5)
                results["VHI"] = {
                    "vci": round(vci, 2),
                    "tci": round(tci, 2),
                    "event_mean":    round(0.5 * vci + 0.5 * tci, 2),
                    "baseline_mean": None,
                    "anomaly_abs":   None,
                    "anomaly_pct":   None,
                    "observations":  results["NDVI"].get("observations", 0),
                }

        return results


#helpers
def _safe_mean(values):
    v = [x for x in values if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return round(float(np.mean(v)), 5) if v else None

def _safe_min(values):
    v = [x for x in values if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return round(float(np.min(v)), 5) if v else None

def _safe_max(values):
    v = [x for x in values if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return round(float(np.max(v)), 5) if v else None

def _norm100(value: float, vmin: float, vmax: float) -> float:
    if vmax == vmin:
        return 50.0
    return max(0.0, min(100.0, (value - vmin) / (vmax - vmin) * 100))

def _geom_to_bbox(geometry: Dict) -> List[float]:
    coords = []
    def _flatten(obj):
        if isinstance(obj, list):
            if obj and isinstance(obj[0], (int, float)):
                coords.append(obj)
            else:
                for item in obj:
                    _flatten(item)
    _flatten(geometry.get("coordinates", []))
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return [min(lons), min(lats), max(lons), max(lats)]
