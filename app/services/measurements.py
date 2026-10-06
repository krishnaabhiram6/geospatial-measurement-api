"""Measurement computation for supported geometry types.

Supported measurements:
* Polygon (and MultiPolygon) -> area in m^2 (and km^2).
* LineString (and MultiLineString) -> length in m (and km).
* Point (and MultiPoint) -> no measurement (graceful "unsupported" handling).
* GeometryCollection -> measured per-component where possible; reported as
  partially supported.

All measurements are performed in a metre-based projected CRS chosen by the
CRS service. Geometries whose CRS is missing are assumed to be EPSG:4326.
"""
from __future__ import annotations

import logging
from typing import Literal

from shapely.geometry.base import BaseGeometry

from app.config import settings
from app.services import crs as crs_service
from app.services.crs import (
    CRS,
    ProjectionPlan,
    build_projection_plan,
    crs_to_string,
    parse_crs,
    project_geometry,
)

logger = logging.getLogger(__name__)

MeasurementType = Literal["area", "length"]

# Geometry types we can measure, mapped to the kind of measurement.
AREA_GEOMETRIES = {"Polygon", "MultiPolygon"}
LENGTH_GEOMETRIES = {"LineString", "LineRing", "MultiLineString"}
# Points / GeometryCollection / unknown -> not directly supported.


def measurement_for_type(geom_type: str) -> MeasurementType | None:
    """Return the measurement kind for a geometry type, or None if unsupported."""
    if geom_type in AREA_GEOMETRIES:
        return "area"
    if geom_type in LENGTH_GEOMETRIES:
        return "length"
    return None


def compute_measurement(
    geometry: BaseGeometry,
    source_crs_input: str | int | CRS | None,
) -> dict:
    """Compute a measurement for a single geometry.

    Returns a dict shaped for the API response. When the geometry type is not
    measurable we return ``{"supported": False}`` and never raise.

    The dict has the following keys:
        supported: bool
        type: "area" | "length" | null
        value: float | null         (in metres / square metres)
        value_km: float | null      (length in km, only for "length")
        value_km2: float | null     (area in km^2, only for "area")
        unit: "m" | "m^2" | null
        crs: str                    (the projected CRS used, e.g. "EPSG:32633")
        source_crs: str             (normalised source CRS, e.g. "EPSG:4326")
    """
    geom_type = geometry.geom_type
    kind = measurement_for_type(geom_type)

    source_crs = parse_crs(source_crs_input) or CRS.from_user_input(settings.default_source_crs)
    source_crs_str = crs_to_string(source_crs)

    base = {
        "supported": False,
        "type": None,
        "value": None,
        "value_km": None,
        "value_km2": None,
        "unit": None,
        "crs": None,
        "source_crs": source_crs_str,
    }

    if kind is None:
        base["supported"] = False
        base["message"] = f"No measurement is defined for geometry type '{geom_type}'."
        return base

    try:
        plan: ProjectionPlan = build_projection_plan(geometry, source_crs)
        projected = project_geometry(plan, geometry)
    except Exception as exc:  # noqa: BLE001 - projection failures should not 500
        logger.warning("Projection failed for %s geometry: %s", geom_type, exc)
        base["supported"] = False
        base["message"] = f"Could not project geometry for measurement: {exc}"
        return base

    projected_crs_str = plan.target_crs_string

    if kind == "area":
        # Guard against self-intersecting / degenerate polygons.
        if not projected.is_valid:
            projected = projected.buffer(0)
        value_m2 = float(projected.area)
        return {
            "supported": True,
            "type": "area",
            "value": value_m2,
            "value_km2": value_m2 / 1_000_000.0,
            "value_km": None,
            "unit": "m^2",
            "crs": projected_crs_str,
            "source_crs": source_crs_str,
        }

    # kind == "length"
    if not projected.is_valid:
        projected = projected.buffer(0)
    value_m = float(projected.length)
    return {
        "supported": True,
        "type": "length",
        "value": value_m,
        "value_km": value_m / 1000.0,
        "value_km2": None,
        "unit": "m",
        "crs": projected_crs_str,
        "source_crs": source_crs_str,
    }
