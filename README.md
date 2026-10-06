# Geospatial File Measurement API

A backend service (FastAPI) that accepts a geospatial file — a **Shapefile** (`.zip` bundle) or a **KML** (`.kml`) — extracts its features, and returns measurement information (area for polygons, length for lines) with **correct CRS handling**: geographic coordinates are projected into a metre-based coordinate system before any measurement is calculated.

---

## Table of Contents
1. [Features](#features)
2. [Tech Stack](#tech-stack)
3. [Setup](#setup)
4. [Running the App](#running-the-app)
5. [API Reference](#api-reference)
6. [Architecture](#architecture)
7. [CRS Handling](#crs-handling)
8. [Design Decisions](#design-decisions)
9. [Testing](#testing)
10. [Learnings](#learnings)
11. [Future Scope](#future-scope)

---

## Features
- **Upload** a `.zip` (Shapefile bundle) or `.kml` file via a REST endpoint.
- **Extracts** every feature: index/id, geometry type, GeoJSON geometry, CRS, and properties/attributes.
- **Measures** supported geometries:
  - `Polygon` / `MultiPolygon` → **Area** (m² and km²)
  - `LineString` / `MultiLineString` → **Length** (m and km)
  - `Point` / `MultiPoint` → no measurement (handled gracefully, never crashes).
- **Unsupported geometry types** (e.g. `GeometryCollection`) are reported per-feature as `supported: false` rather than aborting the upload.
- **CRS-safe measurement**: never measures in lat/lon degrees. Geographic geometries (e.g. EPSG:4326) are reprojected to a UTM zone (chosen from each geometry's centroid) before area/length computation. Missing CRS defaults to EPSG:4326.
- **Persistence**: file metadata, features, and measurements are stored in SQLite so the read endpoints stay fast and the heavy processing happens once at upload time.
- **Interactive docs** at `/docs` (Swagger UI) and `/redoc`.

## Tech Stack
- **FastAPI** + **Uvicorn** (ASGI)
- **GeoPandas** / **Fiona** (Shapefile reading)
- **Shapely** (geometry operations)
- **pyproj** (CRS parsing & transformation)
- **SQLAlchemy 2.0** + **SQLite** (persistence)
- **Pydantic v2** (request/response validation)
- **pytest** + **httpx** (testing)

> **KML note:** Fiona's Windows builds frequently ship *without* the OGR/LIBKML driver, so KML is parsed with a self-contained, namespace-tolerant stdlib XML parser + Shapely (see `app/services/kml_parser.py`). This removes a fragile platform dependency while remaining spec-correct (KML is always EPSG:4326).

---

## Setup

### Prerequisites
- Python 3.10+ (developed on 3.11)
- `pip`

### Install
```bash
cd geospatial-measurement-api
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

> The geospatial stack (`fiona`, `shapely`, `pyproj`) ships pre-built wheels for Windows, macOS and manylinux — no GDAL system install is required. If you pin `pandas`, keep it on **2.x**; `pandas 3.0` is not yet compatible with `geopandas 0.14`.

### Generate sample test data (optional)
Sample fixtures are committed under `tests/data/`. To regenerate them:
```bash
python tests/generate_fixtures.py
# -> tests/data/sample.kml        (Polygon + LineString + Point, EPSG:4326)
# -> tests/data/sample_shapefile.zip  (3 Polygons, EPSG:4326)
```

---

## Running the App

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:
- Swagger UI → http://localhost:8000/docs
- ReDoc → http://localhost:8000/redoc
- Health → http://localhost:8000/health

### Configuration (environment variables / `.env`)
| Variable | Default | Description |
|---|---|---|
| `UPLOAD_DIR` | `./uploads` | Where uploaded files are stored. |
| `DATABASE_URL` | `sqlite:///./geospatial.db` | SQLAlchemy URL. |
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Max upload size. |
| `CRS_STRATEGY` | `auto` | `auto` → UTM zone per geometry; `web_mercator` → force EPSG:3857. |
| `DEFAULT_SOURCE_CRS` | `EPSG:4326` | Assumed CRS when a file declares none. |
| `DEBUG` | `false` | Verbose logging. |

---

## API Reference

Base URL: `http://localhost:8000`

### 1. Upload + process a file
**`POST /api/files/`**

`multipart/form-data` field `file` — a `.zip` (Shapefile) or `.kml`.

**Example (curl)**
```bash
curl -X POST http://localhost:8000/api/files/ \
  -F "file=@sample.kml;type=application/vnd.google-earth.kml+xml"
```

**Response `201 Created`**
```json
{
  "id": "614ef91674f24607b635f233f2a3d7c6",
  "filename": "survey.kml",
  "file_type": "kml",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "status": "COMPLETED",
  "created_at": "2026-10-06T20:56:17.244918"
}
```

Error codes: `415 UNSUPPORTED_FILE_TYPE` (bad extension), `422 INVALID_FILE` (empty/corrupt/no `.shp` in zip), `422 PROCESSING_ERROR` (read/processing failure).

### 2. File information
**`GET /api/files/{id}/`**

**Response `200 OK`**
```json
{
  "id": "614ef91674f24607b635f233f2a3d7c6",
  "filename": "survey.kml",
  "file_type": "kml",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "status": "COMPLETED",
  "error": null,
  "created_at": "2026-10-06T20:56:17.244918",
  "processed_at": "2026-10-06T20:56:17.654594"
}
```
`404 FILE_NOT_FOUND` if the id is unknown.

### 3. Measurements
**`GET /api/files/{id}/measurements/`**

Returns per-feature measurements plus an aggregate `summary`.

**Response `200 OK`** (abbreviated)
```json
{
  "file_id": "614ef91674f24607b635f233f2a3d7c6",
  "filename": "survey.kml",
  "crs": "EPSG:4326",
  "summary": {
    "total": 3,
    "supported": 2,
    "unsupported": 1,
    "total_area_m2": 754945.4072,
    "total_area_km2": 0.754945,
    "total_length_m": 1303.1294,
    "total_length_km": 1.303129
  },
  "features": [
    {
      "feature_index": 0,
      "feature_id": "berlin_block",
      "geometry_type": "Polygon",
      "geometry": { "type": "Polygon", "coordinates": [[[13.377,52.516], ...]] },
      "crs": "EPSG:4326",
      "properties": { "name": "berlin_block", "value": "42", "category": "residential" },
      "measurement": {
        "supported": true,
        "type": "area",
        "value": 754945.4072,
        "value_km2": 0.754945,
        "value_km": null,
        "unit": "m^2",
        "crs": "EPSG:32633",
        "source_crs": "EPSG:4326"
      }
    },
    {
      "feature_index": 2,
      "feature_id": "centre_point",
      "geometry_type": "Point",
      "geometry": { "type": "Point", "coordinates": [13.382, 52.521] },
      "crs": "EPSG:4326",
      "properties": { "name": "centre_point", "value": "0" },
      "measurement": {
        "supported": false,
        "type": null,
        "value": null,
        "unit": null,
        "crs": null,
        "source_crs": "EPSG:4326",
        "message": "No measurement is defined for geometry type 'Point'."
      }
    }
  ]
}
```

The `measurement.crs` field reports the **projected** CRS actually used for that feature's computation (e.g. `EPSG:32633` = UTM zone 33N), while the top-level `crs` is the file's source CRS.

### Health
- `GET /` → service metadata
- `GET /health` → `{"status": "ok"}`

---

## Architecture

### Project structure
```
geospatial-measurement-api/
├── app/
│   ├── main.py              # FastAPI app factory + lifespan (DB init)
│   ├── config.py            # Pydantic settings (env-driven)
│   ├── database.py          # SQLAlchemy engine, session, init_db
│   ├── models.py            # ORM: UploadedFile, FeatureRecord
│   ├── schemas.py           # Pydantic response models
│   ├── exceptions.py        # Domain exceptions + handlers
│   ├── storage.py           # Upload persistence + zip extraction
│   ├── routers/
│   │   ├── files.py         # POST/GET endpoints
│   │   └── _mappers.py       # ORM -> response schema mappers
│   └── services/
│       ├── crs.py            # CRS parsing, projection-plan builder (UTM)
│       ├── measurements.py   # area/length computation
│       ├── file_processor.py  # read + normalize features
│       ├── kml_parser.py      # dependency-free KML reader
│       └── persistence.py     # ingest_upload orchestration
├── tests/
│   ├── conftest.py          # isolated DB/uploads per test, fixtures
│   ├── generate_fixtures.py # builds sample.kml + sample_shapefile.zip
│   ├── test_api.py          # endpoint integration tests
│   └── test_measurements.py # unit tests for CRS + measurement logic
├── uploads/                 # runtime upload dir (git-ignored)
├── requirements.txt
└── README.md
```

### Layering
```
HTTP routers (app/routers)
        │  uses Pydantic schemas (app/schemas)
        ▼
Orchestration (services/persistence)  ── storage (disk)
        │
        ▼
Domain services (file_processor → measurements → crs)
        │
        ▼
ORM (models) ── SQLAlchemy ── SQLite
```
Routers are thin: they validate input, delegate to `services/persistence.ingest_upload`, and map ORM rows to response schemas via `routers/_mappers.py`. The geospatial domain logic (CRS, measurement, parsing) lives in `services/` and has no HTTP/DB coupling, which keeps it unit-testable.

### File-processing flow
1. **Upload** — the router streams the file into memory (size-capped), detects the type from the extension, and rejects unsupported types (`415`).
2. **Persist** — `storage.save_upload` writes the bytes to `UPLOAD_DIR/<id>.<ext>`. A database row is created with status `PROCESSING`.
3. **Read**
   - Shapefile → extract the zip to a sibling dir, locate the `.shp`, read via GeoPandas/Fiona.
   - KML → parse with the built-in `kml_parser` (stdlib XML + Shapely), assigned EPSG:4326.
4. **Normalize** — each row becomes a feature: `feature_index`, `feature_id` (from `id`/`fid`/`name` attributes), `geometry_type`, GeoJSON geometry, normalised CRS string, and JSON-safe properties.
5. **Measure** — per feature, `measurements.compute_measurement` decides support and computes area/length (see CRS handling below).
6. **Store** — features + measurements are persisted to `FeatureRecord` rows; the file row moves to `COMPLETED` (or `FAILED` with the error message). The raw upload + extracted dir are then deleted to free disk (the normalized data is now in the DB).
7. **Read endpoints** — `GET /api/files/{id}/` and `GET /api/files/{id}/measurements/` read straight from the DB; no reprocessing.

### Measurement calculation flow
```
geometry + source CRS
      │
      ▼
measurement_for_type() ── unsupported? ──► { supported: false }  (Point/unknown)
      │ supported
      ▼
build_projection_plan(source CRS, geometry)  ──► ProjectionPlan(transformer, target CRS)
      │
      ▼
project_geometry() ── reproject to metres
      │
      ▼
shapely .area / .length   ──► value (m² or m) + km/km² + unit + projected CRS
```
Degenerate/self-intersecting geometries are repaired with `.buffer(0)` before measuring, and any projection failure is caught and reported as `supported: false` per feature (never a 500).

### CRS handling
The single most important correctness rule in geospatial work: **never measure planar area or length in geographic (lat/lon) coordinates** — degrees are angular, not linear, so an "area" computed in degrees is meaningless. The pipeline:

1. **Parse** the source CRS with `pyproj.CRS.from_user_input`. If a file declares no CRS, assume `DEFAULT_SOURCE_CRS` (EPSG:4326) and log a warning.
2. **Decide a target CRS** (`services/crs.build_projection_plan`):
   - If the source CRS is **geographic** (e.g. EPSG:4326) → pick a **UTM zone** from the geometry's centroid (`auto` strategy, default). Northern hemisphere → EPSG:326xx, southern → EPSG:327xx. This gives good local accuracy.
   - If the source CRS is **already projected** in metres → keep it. If its unit is feet/etc., reproject via UTM for metre-based output.
   - `CRS_STRATEGY=web_mercator` forces EPSG:3857 instead (less accurate at high latitude; included to show the strategy is pluggable).
3. **Transform** the geometry with `pyproj.Transformer` (always `always_xy=True`) via `shapely.ops.transform`.
4. **Measure** the projected geometry with Shapely's `.area`/`.length` (now in metres).
5. **Report** both the source CRS and the projected CRS used, so results are auditable.

---

## Design Decisions

| Decision | Rationale | Alternatives considered |
|---|---|---|
| **FastAPI** over Django/DRF | Async-native, first-class OpenAPI, lighter-weight for a file-processing API. | Django REST Framework would add an ORM/admin we don't need; equally valid. |
| **Synchronous upload processing** | For typical shapefile/KML sizes the processing is sub-second; a synchronous flow is far simpler to reason about and test than a background worker. | Celery/RQ + a `PROCESSING`→`COMPLETED` poll would scale to very large files; documented in Future Scope. |
| **SQLite + SQLAlchemy** | Zero-config, self-contained, good enough for the workload; SQLAlchemy keeps the door open to Postgres/PostGIS. | PostGIS would enable DB-side `ST_Area`/`ST_Length` with `geography` casting, removing the projection step — overkill for this scope. |
| **Persist features + measurements at upload** | Read endpoints stay O(1)-ish DB reads; no reprocessing; supports filtering/pagination later. | Recompute on demand would be stateless but wastes CPU and re-reads the file. |
| **Self-contained KML parser** | Fiona Windows wheels often lack the OGR/LIBKML driver; a stdlib-XML + Shapely parser is portable, dependency-free, and ~150 lines. | `pykml` (extra dependency, requires lxml); enabling the KML driver in a custom GDAL build (heavy). |
| **UTM-per-geometry (`auto`)** | UTM zones give the best local metric accuracy for arbitrary inputs without knowing the AOI; each geometry gets the zone matching its centroid. | A single global equal-area CRS (e.g. EPSG:6933) avoids zone-edge seams but distorts distances; `geopandas`' `estimate_utm_crs` (needs `pyproj >= 3.3`) could replace the manual centroid logic. |
| **Per-feature graceful handling** | A single unsupported/empty geometry never fails the whole upload — each feature carries its own `measurement.supported` flag. | Rejecting the file on the first bad feature is hostile to real-world data. |
| **Delete raw uploads after processing** | Disk-efficient; the normalized data is already in the DB. | Keeping raw files would allow re-processing at the cost of disk. |

---

## Testing

```bash
python -m pytest -v
```

17 tests cover:
- **Endpoint integration** (`tests/test_api.py`): KML upload, Shapefile upload, unsupported type, empty file, file-not-found, invalid zip, measurements summary + per-feature correctness (area in m² with a UTM `EPSG:326xx` CRS; length in m; Point reported unsupported).
- **Unit tests** (`tests/test_measurements.py`): geometry-type mapping, CRS parsing, UTM zone selection, area-in-metres (not degrees), length-in-metres, already-projected CRS kept, missing-CRS fallback.

Tests run against an isolated temp SQLite DB + temp upload dir per test (`conftest.py`), so they're fully hermetic and parallel-safe.

A live end-to-end check against a running server:
```bash
uvicorn app.main:app --port 8000 &
python -c "import httpx, pathlib; r=httpx.post('http://localhost:8000/api/files/', files={'file':('s.kml', pathlib.Path('tests/data/sample.kml').read_bytes())}); print(r.status_code, r.json())"
```

---

## Learnings

- **Geographic ≠ projected CRS.** The core lesson: degrees are angular, so computing area/length directly on EPSG:4326 yields nonsense. Reprojecting to a metre-based CRS (UTM here) before measuring is mandatory for correct results.
- **Platform fragility of geospatial drivers.** Fiona's supported-driver list varies by build; relying on `driver="KML"` made the app non-portable. A small purpose-built parser removed that risk entirely and deepened my understanding of the KML/GeoJSON geometry model.
- **Shapefiles are single-geometry-type.** A `.shp` cannot mix Polygon + LineString + Point, which shaped the test fixtures (the KML covers mixed types; the shapefile is polygon-only).
- **Library version coupling.** `pandas 3.0` breaks `geopandas 0.14`'s schema inference (`StringDtype` handling). Pinning `pandas <2.3` was necessary — a reminder to test the whole stack, not just app code.
- **XML namespaces bite.** ElementTree's `.find("LinearRing")` silently returns `None` against namespaced tags; stripping namespaces up front is a clean, robust fix.
- **Defensive measurement.** `.buffer(0)` to repair self-intersecting polygons and catching projection errors per-feature keeps one bad feature from failing an otherwise-valid file.

---

## Future Scope
- **Background processing** for large files: move ingest into a Celery/RQ task and expose a status-pollable lifecycle (`PENDING → PROCESSING → COMPLETED/FAILED`) with a webhook or SSE notification.
- **Streaming uploads** (chunked / resumable) and a hard pre-flight size guard without loading the whole file into memory.
- **More file formats**: GeoJSON, GeoPackage, GeoParquet, and KMZ (zip-wrapped KML).
- **More measurements**: perimeter for polygons, bearing for lines, bounding-box area, and `GeometryCollection` decomposition to measure each component.
- **Equal-area fallback** for very large / cross-zone geometries (e.g. auto-pick EPSG:6933 when the geometry spans multiple UTM zones), plus `geopandas.estimate_utm_crs` once on a `pyproj >= 3.3` baseline.
- **Spatial indexing & filtering**: add `GET /api/files/{id}/features/?geometry_type=Polygon` and bounding-box queries, backed by PostGIS if scaled.
- **Authentication, rate limiting, and per-user quotas**; upload virus scanning; signed download URLs for the raw file.
- **Reprojection endpoint**: return feature geometries reprojected to a caller-specified CRS.
- **Dockerize** the service (multi-stage image with the geospatial wheels) and add a `docker-compose` with PostGIS for production.
- **CI**: GitHub Actions matrix (Windows + Linux) running the test suite and a lint/type-check gate.
