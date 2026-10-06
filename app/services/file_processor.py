"""File processing: read a geospatial file and extract normalized features.

Responsibilities:
* Detect file type from the upload (.zip -> shapefile, .kml -> KML).
* Use geopandas/fiona to read the file (KML requires the LIBKML/OGR KML driver).
* Normalize each feature into a common in-memory representation:
    - feature index + id
    - geometry type
    - GeoJSON geometry (WGS84 / EPSG:4326 for consistency in the API payload)
    - source CRS string
    - properties dict
* Measurements are computed here too, so upload is a single synchronous step.

The reader is defensive: empty files, missing CRS, and unsupported geometry
types are reported per-feature rather than aborting the whole upload.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.exceptions import InvalidFileError, UnsupportedFileTypeError
from app.services import crs as crs_service
from app.services.crs import CRS, crs_to_string, parse_crs
from app.services.measurements import compute_measurement

logger = logging.getLogger(__name__)


@dataclass
class ProcessedFeature:
    feature_index: int
    feature_id: str | None
    geometry_type: str
    geometry_geojson: dict
    crs: str | None
    properties: dict
    measurement: dict


@dataclass
class ProcessedFile:
    file_type: str  # "shapefile" | "kml"
    crs: str | None
    feature_count: int
    features: list[ProcessedFeature]


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------

def detect_file_type(filename: str) -> str:
    """Determine the geospatial file type from the extension.

    Returns one of "shapefile", "kml", or "kmz".
    Raises UnsupportedFileTypeError for anything else.
    """
    name = (filename or "").lower()
    if name.endswith(".zip"):
        return "shapefile"
    if name.endswith(".kml"):
        return "kml"
    if name.endswith(".kmz"):
        return "kmz"
    # Common mistakes with a helpful message.
    if name.endswith((".shp", ".shx", ".dbf", ".prj")):
        raise UnsupportedFileTypeError(
            f"You uploaded a single '{Path(filename).suffix}' component. "
            "A shapefile is a bundle of files (.shp + .shx + .dbf + optional .prj). "
            "Please zip the shapefile components together and upload the .zip file."
        )
    raise UnsupportedFileTypeError(
        f"Unsupported file type for '{filename}'. "
        "Accepted types are a .zip shapefile bundle, a .kml file, or a .kmz file."
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _read_geodataframe(path: Path, file_type: str):
    """Read the file into a geopandas GeoDataFrame.

    Shapefiles are read via geopandas/fiona. KML is parsed with our built-in
    ``kml_parser`` because fiona Windows builds commonly lack the OGR KML
    driver (keeps the service dependency-free and portable).
    """
    import geopandas as gpd

    if file_type == "shapefile":
        shp_path = _find_shp(path)
        return gpd.read_file(shp_path)

    from app.services.kml_parser import read_kml

    return read_kml(path)


def _find_shp(extracted_dir: Path) -> Path:
    """Locate the .shp inside an extracted shapefile directory."""
    shp_files = sorted(extracted_dir.rglob("*.shp"))
    if not shp_files:
        raise InvalidFileError("The uploaded zip does not contain a .shp file.")
    # Prefer the shallowest match in case of nested archives.
    shp_files.sort(key=lambda p: len(p.parts))
    return shp_files[0]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_crs(gdf) -> CRS:
    """Resolve the GeoDataFrame CRS, falling back to EPSG:4326 when missing."""
    crs = parse_crs(getattr(gdf, "crs", None))
    if crs is None:
        logger.warning("File has no CRS; assuming %s.", settings.default_source_crs)
        crs = CRS.from_user_input(settings.default_source_crs)
    return crs


def _geometry_to_geojson(geom) -> dict:
    """Convert a shapely geometry to a plain GeoJSON dict (for JSON storage)."""
    if geom is None or geom.is_empty:
        return {"type": "GeometryCollection", "geometries": []}
    return json.loads(json.dumps(geom.__geo_interface__))


def _get_feature_id(properties: dict, index: int) -> str | None:
    """Pick a stable feature id from common id-like attributes, else index."""
    for key in ("id", "ID", "fid", "FID", "name", "Name"):
        if key in properties and properties[key] is not None:
            return str(properties[key])
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def process_file(stored_path: Path, original_filename: str, file_type: str) -> ProcessedFile:
    """Read a geospatial file and compute per-feature measurements.

    This is the single synchronous processing step invoked at upload time.
    It returns a fully-normalized ProcessedFile ready to be persisted.
    """
    import geopandas as gpd  # noqa: F401 - ensure import works early

    inner_type = file_type  # may be overridden by what's actually inside a zip

    if file_type in ("shapefile", "kmz"):
        from app.storage import extract_zip

        extracted_dir = extract_zip(stored_path)
        # A zip might contain a shapefile (.shp) OR a KML (.kml, e.g. a .kmz).
        shp_files = sorted(extracted_dir.rglob("*.shp"))
        kml_files = sorted(extracted_dir.rglob("*.kml"))
        if file_type == "shapefile" and shp_files:
            inner_type = "shapefile"
            source_path = extracted_dir
        elif kml_files:
            # KMZ or a zip that happened to contain a KML.
            inner_type = "kml"
            source_path = kml_files[0]
        elif shp_files:
            inner_type = "shapefile"
            source_path = extracted_dir
        else:
            raise InvalidFileError(
                "The uploaded zip contains neither a .shp (shapefile) nor a .kml file. "
                "Please ensure the archive is a valid shapefile bundle or a KMZ."
            )
    else:
        source_path = stored_path

    try:
        gdf = _read_geodataframe(source_path, inner_type)
    except InvalidFileError:
        raise
    except Exception as exc:  # noqa: BLE001 - any read failure becomes a 422
        raise InvalidFileError(f"Could not read the geospatial file: {exc}") from exc

    if gdf is None or len(gdf) == 0:
        raise InvalidFileError("The file contains no features.")

    source_crs = _normalize_crs(gdf)
    crs_str = crs_to_string(source_crs)

    features: list[ProcessedFeature] = []
    for index, row in gdf.iterrows():
        geom = row.geometry
        geom_type = geom.geom_type if geom is not None else "Unknown"
        properties = {k: _json_safe(v) for k, v in row.items() if k != gdf.geometry.name}
        feature_id = _get_feature_id(properties, int(index))
        geometry_geojson = _geometry_to_geojson(geom)

        measurement: dict
        if geom is None or geom.is_empty:
            measurement = {
                "supported": False,
                "type": None,
                "value": None,
                "value_km": None,
                "value_km2": None,
                "unit": None,
                "crs": None,
                "source_crs": crs_str,
                "message": "Empty/missing geometry; no measurement computed.",
            }
        else:
            measurement = compute_measurement(geom, source_crs)

        features.append(
            ProcessedFeature(
                feature_index=int(index),
                feature_id=feature_id,
                geometry_type=geom_type,
                geometry_geojson=geometry_geojson,
                crs=crs_str,
                properties=properties,
                measurement=measurement,
            )
        )

    return ProcessedFile(
        file_type=inner_type,
        crs=crs_str,
        feature_count=len(features),
        features=features,
    )


def _json_safe(value: Any) -> Any:
    """Make a value JSON-serializable (handles numpy scalars, arrays, etc.)."""
    import numpy as np
    import pandas as pd

    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.ndarray, pd.Series, list, tuple)):
        return [_json_safe(v) for v in list(value)]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    # Fall back to string for datetimes, decimals, etc.
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)
