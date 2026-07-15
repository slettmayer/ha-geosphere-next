#!/usr/bin/env python3
"""Phase 0 spike: resolve empirical unknowns E-1..E-7 against the live GeoSphere API.

Not shipped with the integration. Run manually:

    python3 scripts/explore_api.py [LAT LON]

Writes recorded responses to tests/fixtures/ and prints findings for:
  E-1  AROME tcc scale (0-1 vs 0-100)
  E-2  nowcast pt (precipitation type) code table
  E-3  INCA P0 unit (Pa vs hPa)
  E-4  AROME grad semantics (instant W/m2 vs accumulated J/m2)
  E-5  timestamp format / timezone
  E-6  out-of-domain error shape (nowcast/INCA at Berlin)
  E-7  accumulation reset across model-run boundary (forecast_offset=0 vs 1)
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

BASE = "https://dataset.api.hub.geosphere.at/v1"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

AROME = "timeseries/forecast/nwp-v1-1h-2500m"
NOWCAST = "timeseries/forecast/nowcast-v1-15min-1km"
INCA = "timeseries/historical/inca-v1-1h-1km"

AROME_PARAMS = (
    "t2m,mnt2m,mxt2m,rh2m,sp,u10m,v10m,ugust,vgust,tcc,"
    "rr_acc,rain_acc,snow_acc,snowlmt,sundur_acc,grad,cape,cin,sy"
)
NOWCAST_PARAMS = "t2m,td,rh2m,rr,pt,dd,ff,fx"
INCA_PARAMS = "T2M,TD2M,RH2M,RR,P0,GL,UU,VV"


def fetch(path: str, save_as: str | None = None, **query: str) -> tuple[int, dict]:
    url = f"{BASE}/{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query, safe=",:")
    print(f"\n>>> GET {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = json.loads(resp.read())
            status = resp.status
    except urllib.error.HTTPError as err:
        status = err.code
        try:
            body = json.loads(err.read())
        except Exception:
            body = {"raw": "unparseable"}
    print(f"    HTTP {status}")
    if save_as:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / save_as).write_text(json.dumps(body, indent=2) + "\n")
        print(f"    saved tests/fixtures/{save_as}")
    return status, body


def params_of(body: dict) -> dict:
    return body["features"][0]["properties"]["parameters"]


def series(body: dict, name: str) -> list:
    return params_of(body)[name]["data"]


def main() -> None:
    lat, lon = (
        (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else ("48.2208", "16.3738")
    )
    lat_lon = f"{lat},{lon}"
    print(f"Spiking against {lat_lon} (Vienna Ottakring default)")

    # --- metadata: E-2, E-3, E-4 ---------------------------------------
    _, arome_meta = fetch(f"{AROME}/metadata", save_as="arome_metadata.json")
    _, nowcast_meta = fetch(f"{NOWCAST}/metadata", save_as="nowcast_metadata.json")
    _, inca_meta = fetch(f"{INCA}/metadata", save_as="inca_metadata.json")

    def meta_param(meta: dict, name: str) -> dict:
        for p in meta.get("parameters", []):
            if p.get("name") == name:
                return p
        return {}

    print("\n=== E-2: nowcast pt parameter metadata ===")
    print(json.dumps(meta_param(nowcast_meta, "pt"), indent=2))
    print("\n=== E-3: INCA P0 parameter metadata ===")
    print(json.dumps(meta_param(inca_meta, "P0"), indent=2))
    print("\n=== E-4: AROME grad parameter metadata ===")
    print(json.dumps(meta_param(arome_meta, "grad"), indent=2))
    print("\n=== AROME tcc + sy metadata (E-1 context) ===")
    print(
        json.dumps(
            [meta_param(arome_meta, "tcc"), meta_param(arome_meta, "sy")], indent=2
        )
    )

    # --- live data: E-1, E-5 -------------------------------------------
    _, arome = fetch(
        AROME, save_as="arome.json", parameters=AROME_PARAMS, lat_lon=lat_lon
    )
    print("\n=== E-5: timestamp format ===")
    print(f"reference_time: {arome['reference_time']}")
    print(f"timestamps[0..2]: {arome['timestamps'][:3]}")
    print(f"snapped grid point: {arome['features'][0]['geometry']['coordinates']}")

    print("\n=== E-1: tcc scale ===")
    tcc = [v for v in series(arome, "tcc") if v is not None]
    print(f"tcc first 12 values: {tcc[:12]}")
    print(
        f"tcc min={min(tcc)} max={max(tcc)}  -> {'0-100 scale' if max(tcc) > 1.5 else '0-1 scale'}"
    )

    print(
        "\n=== E-4: grad live values (instant W/m2 would be 0-1000ish, accumulated grows) ==="
    )
    grad = [v for v in series(arome, "grad") if v is not None]
    print(f"grad first 12: {grad[:12]}")

    print("\n=== E-7: accumulation behavior ===")
    rr = series(arome, "rr_acc")
    print(
        f"reference_time={arome['reference_time']}, timestamps[0]={arome['timestamps'][0]}"
    )
    print(f"rr_acc first 12: {rr[:12]}")
    _, arome_prev = fetch(
        AROME,
        save_as="arome_prev_run.json",
        parameters=AROME_PARAMS,
        lat_lon=lat_lon,
        forecast_offset="1",
    )
    print(f"prev run reference_time={arome_prev['reference_time']}")
    print(f"prev run timestamps[0]={arome_prev['timestamps'][0]}")
    print(f"prev run rr_acc first 12: {series(arome_prev, 'rr_acc')[:12]}")
    print(
        "(differencing must be per-response; step0 hourly value only valid if "
        "timestamps[0] == reference_time + 1h)"
    )

    # --- nowcast + INCA live -------------------------------------------
    _, nowcast = fetch(
        NOWCAST, save_as="nowcast.json", parameters=NOWCAST_PARAMS, lat_lon=lat_lon
    )
    print("\n=== nowcast sample ===")
    print(
        f"reference_time={nowcast['reference_time']} timestamps={nowcast['timestamps'][:4]}"
    )
    for name in ("t2m", "rr", "pt", "dd", "ff", "fx"):
        print(
            f"  {name}: unit={params_of(nowcast)[name]['unit']} data[:4]={series(nowcast, name)[:4]}"
        )

    now = datetime.now(UTC)
    start = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    end = now.strftime("%Y-%m-%dT%H:%M")
    _, inca = fetch(
        INCA,
        save_as="inca.json",
        parameters=INCA_PARAMS,
        lat_lon=lat_lon,
        start=start,
        end=end,
    )
    print("\n=== INCA sample (E-3 live check) ===")
    print(f"timestamps={inca['timestamps']}")
    for name in ("T2M", "P0", "GL", "RR"):
        print(
            f"  {name}: unit={params_of(inca)[name]['unit']} data={series(inca, name)}"
        )

    # --- E-6: out of domain ----------------------------------------------
    print("\n=== E-6: out-of-domain error shapes (Berlin 52.52,13.405) ===")
    for path, params, name in (
        (NOWCAST, NOWCAST_PARAMS, "nowcast_out_of_domain.json"),
        (AROME, "t2m", "arome_out_of_domain.json"),
    ):
        status, body = fetch(
            path, save_as=name, parameters=params, lat_lon="52.52,13.405"
        )
        print(f"    {path}: HTTP {status} body={json.dumps(body)[:400]}")

    print("\nDone. Fixtures recorded in tests/fixtures/.")


if __name__ == "__main__":
    main()
