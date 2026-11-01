#!/usr/bin/env python3
"""Probe the live GeoSphere API and record the test fixtures.

Not shipped with the integration. Run manually:

    python3 scripts/explore_api.py [--lat-lon LAT,LON] [--forecast-only]
                                   [--anchor YYYY-MM-DDTHH:MM]

Writes recorded responses to tests/fixtures/ and prints findings for:
  F-1  stamping of every forecast parameter: requested from the run's t0, a
       parameter that is null at index 0 covers the interval ENDING at its
       stamp; one with a value there is instantaneous
  F-2  tcc scale (0-1 vs 0-100)
  F-3  `sy` cloud classes against `tcc` at the same and the previous stamp
  F-4  ensemble tp percentiles: per-hour or run-accumulated
  F-5  `start` anchoring: unbounded, on-the-hour, mid-hour and before-t0
  F-6  out-of-domain error shape (Berlin)
  N-1  nowcast/INCA samples and metadata (skipped with --forecast-only)

The forecast fixtures are requested from the run's t0, so they keep the null
leading row that the stamping depends on. Every stamp of a forecast fixture is
then shifted by one offset, so that the deterministic run's `reference_time`
lands on `--anchor`: the test suite runs on a frozen clock against fixed
nowcast/INCA recordings, and the forecast has to line up with them. Values are
untouched, and the ensemble shifts by the same offset so the two stay aligned.
"""

from __future__ import annotations

import argparse
import itertools
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

BASE = "https://dataset.api.hub.geosphere.at/v1"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

NWP = "timeseries/forecast/nwp-v2-1h-1km"
ENSEMBLE = "timeseries/forecast/ensemble-v2-1h-1km"
NOWCAST = "timeseries/forecast/nowcast-v1-15min-1km"
INCA = "timeseries/historical/inca-v1-1h-1km"

# Mirrors AROME_PARAMETERS / ENSEMBLE_PARAMETERS in const.py.
NWP_PARAMS = "2t,2r,10u,10v,10fg,tcc,tp,sf,snowlmt,cape,sy"
ENSEMBLE_PARAMS = "tp_p10,tp_p50,tp_p90"
NOWCAST_PARAMS = "t2m,td,rh2m,rr,pt,dd,ff,fx"
INCA_PARAMS = "T2M,TD2M,RH2M,RR,P0,GL,UU,VV"

# The suite's frozen timeline: forecast runs are stamped 12:00Z on this day.
DEFAULT_ANCHOR = "2026-07-15T12:00"


def fetch(path: str, **query: str) -> tuple[int, dict]:
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
    return status, body


def save(body: dict, name: str) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(json.dumps(body, indent=2) + "\n")
    print(f"    saved tests/fixtures/{name}")


def restamp(body: dict, offset: timedelta) -> dict:
    """Shift every stamp of a forecast response by `offset`, values untouched."""

    def shift(value: str) -> str:
        moved = datetime.fromisoformat(value) + offset
        return moved.strftime("%Y-%m-%dT%H:%M+00:00")

    body = json.loads(json.dumps(body))
    body["reference_time"] = shift(body["reference_time"])
    body["timestamps"] = [shift(ts) for ts in body["timestamps"]]
    return body


def params_of(body: dict) -> dict:
    return body["features"][0]["properties"]["parameters"]


def series(body: dict, name: str) -> list:
    return params_of(body)[name]["data"]


def stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M")


def classify(body: dict) -> None:
    for name, param in params_of(body).items():
        kind = "interval-ending" if param["data"][0] is None else "instantaneous"
        if name == "sy":
            # Null at t0 like the interval fields, but its cloud classes follow
            # `tcc` at its own stamp (F-3), so it is read there.
            kind += " (null at t0; read at its own stamp, see F-3)"
        print(f"  {name:8} {param['unit']:15} index0={param['data'][0]!s:8} {kind}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat-lon", default="46.63,14.15")
    parser.add_argument("--forecast-only", action="store_true")
    parser.add_argument("--anchor", default=DEFAULT_ANCHOR)
    args = parser.parse_args()
    lat_lon = args.lat_lon
    anchor = datetime.fromisoformat(args.anchor).replace(tzinfo=UTC)
    print(
        f"Probing {lat_lon}; forecast fixtures re-stamped to {anchor:%Y-%m-%dT%H:%MZ}"
    )

    _, nwp_meta = fetch(f"{NWP}/metadata")
    save(nwp_meta, "arome_metadata.json")
    _, ens_meta = fetch(f"{ENSEMBLE}/metadata")
    print(f"nwp reftimes: {nwp_meta['available_forecast_reftimes']}")
    print(f"ensemble reftimes: {ens_meta['available_forecast_reftimes']}")
    print(f"nwp bbox_outer: {nwp_meta['bbox_outer']}")

    # --- F-1, F-2, F-3: the newest run from its own t0 ---------------------
    reftime = datetime.fromisoformat(nwp_meta["last_forecast_reftime"])
    _, nwp = fetch(NWP, parameters=NWP_PARAMS, lat_lon=lat_lon, start=stamp(reftime))
    offset = anchor - datetime.fromisoformat(nwp["reference_time"])
    save(restamp(nwp, offset), "arome.json")
    print(f"\n=== F-1: stamping (run {nwp['reference_time']}) ===")
    classify(nwp)

    print("\n=== F-2: tcc scale ===")
    tcc = [v for v in series(nwp, "tcc") if v is not None]
    print(f"tcc min={min(tcc)} max={max(tcc)}")

    print("\n=== F-3: sy cloud classes vs tcc ===")
    same: dict[int, list[float]] = defaultdict(list)
    prev: dict[int, list[float]] = defaultdict(list)
    sy, tcc_all = series(nwp, "sy"), series(nwp, "tcc")
    for i in range(1, len(sy)):
        if sy[i] is not None:
            same[int(sy[i])].append(tcc_all[i])
            prev[int(sy[i])].append(tcc_all[i - 1])
    for code in sorted(same):
        print(
            f"  sy {code:3}: tcc@i {min(same[code])}..{max(same[code])}  "
            f"tcc@i-1 {min(prev[code])}..{max(prev[code])}"
        )

    _, nwp_prev = fetch(
        NWP,
        parameters=NWP_PARAMS,
        lat_lon=lat_lon,
        forecast_offset="1",
        start=stamp(reftime - timedelta(hours=3)),
    )
    save(restamp(nwp_prev, offset), "arome_prev_run.json")
    print(f"prev run reference_time={nwp_prev['reference_time']}")

    # --- F-4: ensemble ------------------------------------------------------
    ens_reftime = datetime.fromisoformat(ens_meta["last_forecast_reftime"])
    _, ensemble = fetch(
        ENSEMBLE,
        parameters=ENSEMBLE_PARAMS,
        lat_lon=lat_lon,
        start=stamp(ens_reftime),
    )
    save(restamp(ensemble, offset), "ensemble.json")
    print(f"\n=== F-4: ensemble (run {ensemble['reference_time']}) ===")
    classify(ensemble)
    p90 = series(ensemble, "tp_p90")
    falls = sum(
        1
        for a, b in itertools.pairwise(p90[1:])
        if a is not None and b is not None and b < a
    )
    print(f"tp_p90 decreases {falls}x -> {'per-hour' if falls else 'accumulated?'}")

    # --- F-5: start anchoring ----------------------------------------------
    print("\n=== F-5: start anchoring ===")
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    for label, start in (
        ("unbounded", None),
        ("top of hour", stamp(hour - timedelta(hours=1))),
        ("mid-hour", stamp(hour - timedelta(minutes=30))),
        ("before t0", stamp(reftime - timedelta(hours=2))),
    ):
        query = {"parameters": "2t", "lat_lon": lat_lon}
        if start:
            query["start"] = start
        _, body = fetch(NWP, **query)
        print(f"  {label:12} start={start} -> first stamp {body['timestamps'][0]}")

    # --- F-6: out of domain ------------------------------------------------
    print("\n=== F-6: out-of-domain error shape (Berlin 52.52,13.405) ===")
    status, body = fetch(NWP, parameters="2t", lat_lon="52.52,13.405")
    save(body, "arome_out_of_domain.json")
    print(f"    HTTP {status} body={json.dumps(body)[:400]}")

    if args.forecast_only:
        print("\nDone (forecast fixtures only).")
        return

    # --- N-1: nowcast + INCA -------------------------------------------------
    for path, name in (
        (NOWCAST, "nowcast_metadata.json"),
        (INCA, "inca_metadata.json"),
    ):
        _, meta = fetch(f"{path}/metadata")
        save(meta, name)
    _, nowcast = fetch(NOWCAST, parameters=NOWCAST_PARAMS, lat_lon=lat_lon)
    save(nowcast, "nowcast.json")
    now = datetime.now(UTC)
    _, inca = fetch(
        INCA,
        parameters=INCA_PARAMS,
        lat_lon=lat_lon,
        start=stamp(now - timedelta(hours=3)),
        end=stamp(now),
    )
    save(inca, "inca.json")
    _, body = fetch(NOWCAST, parameters=NOWCAST_PARAMS, lat_lon="52.52,13.405")
    save(body, "nowcast_out_of_domain.json")

    print("\nDone. Fixtures recorded in tests/fixtures/.")


if __name__ == "__main__":
    main()
