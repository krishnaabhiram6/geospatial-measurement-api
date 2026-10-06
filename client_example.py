"""Demo client: upload sample files to the running API and print results.

Prerequisites:
  1. pip install -r requirements.txt
  2. uvicorn app.main:app --reload --port 8000   (in a separate terminal)
  3. python client_example.py

This script uploads the sample KML and sample zipped Shapefile that ship with
the repo (tests/data/*) and prints the upload, file-info, and measurements
responses. It's a quick way to see the API working end-to-end without curl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
DATA_DIR = Path(__file__).resolve().parent / "tests" / "data"


def pretty(label: str, status: int, body: dict) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"  HTTP {status}")
    print(f"{'=' * 70}")
    print(json.dumps(body, indent=2))


def upload_and_inspect(filepath: Path, content_type: str) -> None:
    print(f"\n>>> Uploading {filepath.name} ...")
    with open(filepath, "rb") as f:
        resp = httpx.post(
            f"{BASE_URL}/api/files/",
            files={"file": (filepath.name, f, content_type)},
            timeout=60,
        )

    if resp.status_code != 201:
        print(f"  Upload FAILED: HTTP {resp.status_code}")
        print(json.dumps(resp.json(), indent=2))
        return

    upload = resp.json()
    pretty(f"POST /api/files/  (upload {filepath.name})", resp.status_code, upload)

    file_id = upload["id"]

    info = httpx.get(f"{BASE_URL}/api/files/{file_id}/")
    pretty(f"GET /api/files/{file_id}/  (file info)", info.status_code, info.json())

    meas = httpx.get(f"{BASE_URL}/api/files/{file_id}/measurements/")
    body = meas.json()
    pretty(f"GET /api/files/{file_id}/measurements/  (summary)", meas.status_code, body["summary"])

    print("\n  --- Per-feature measurements ---")
    for feat in body["features"]:
        m = feat["measurement"]
        if m["supported"]:
            print(
                f"  [{feat['feature_index']}] {feat['geometry_type']:12s} "
                f"id={feat['feature_id']!s:20s} -> {m['type']}: "
                f"{m['value']:,.2f} {m['unit']}  (CRS: {m['crs']})"
            )
        else:
            print(
                f"  [{feat['feature_index']}] {feat['geometry_type']:12s} "
                f"id={feat['feature_id']!s:20s} -> unsupported ({m.get('message', '')})"
            )


def main() -> int:
    print("=== Geospatial File Measurement API - Demo Client ===")
    print(f"Server: {BASE_URL}")

    health = httpx.get(f"{BASE_URL}/health", timeout=10)
    if health.status_code != 200:
        print(f"Server is not running at {BASE_URL}. Start it with:")
        print("  uvicorn app.main:app --reload --port 8000")
        return 1

    print("Server is healthy.")

    kml = DATA_DIR / "sample.kml"
    zsh = DATA_DIR / "sample_shapefile.zip"

    if kml.exists():
        upload_and_inspect(kml, "application/vnd.google-earth.kml+xml")
    else:
        print(f"\nSample KML not found at {kml}. Run: python tests/generate_fixtures.py")

    if zsh.exists():
        upload_and_inspect(zsh, "application/zip")
    else:
        print(f"\nSample shapefile zip not found at {zsh}. Run: python tests/generate_fixtures.py")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
