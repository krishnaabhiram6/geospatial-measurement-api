"""CRS handling: detection of geographic CRS and selection of a projected CRS.

The golden rule of geospatial measurement: never compute planar area or length
in geographic coordinates (degrees). We must first transform geometries into a
projected coordinate system whose units are metres.

Strategy
--------
* If the source CRS is already projected (linear units), we keep it. If its unit
  is not metres (e.g. US survey feet) we additionally convert to metres.
* If the source CRS is geographic (such as EPSG:4326), we choose an appropriate
  projected CRS per geometry:
    - "auto" strategy  -> a UTM zone derived from the geometry's centroid.
      UTM zones provide good local accuracy and are a well-understood default.
      For sub-zone / global spans this is approximate; an equal-area alternative
      is noted in the README.
    - "web_mercator"   -> EPSG:3857 (convenient but distorted at high latitudes,
      included for demonstration of the strategy being configurable).

All transformations use pyproj. Geometries are handled via shapely.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pyproj
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

from app.config import settings

logger = logging.getLogger(__name__)

# EPSG code of the Web Mercator projection (used as the simple fallback).
WEB_MERCATOR_EPSG = 3857

# WGS84 geographic reference (used to derive UTM zones from lon/lat).
WGS84_GEOGRAPHIC = CRS.from_epsg(4326)


class CRSError(Exception):
    """Raised when a CRS cannot be interpreted or no projection can be chosen."""


@dataclass
class ProjectionPlan:
    """Describes how a geometry will be projected for measurement."""

    source_crs: CRS
    target_crs: CRS
    target_crs_string: str  # authoritative string to persist (EPSG:XXXX)
    transformer: Transformer
    unit_is_metres: bool


def parse_crs(crs_input: str | int | CRS | None) -> CRS | None:
    """Best-effort conversion of a CRS spec into a pyproj CRS.

    Accepts EPSG codes (int or "EPSG:4326"), WKT strings, or proj strings.
    Returns None when the input is empty/invalid (the caller may then fall
    back to a default).
    """
    if crs_input is None or crs_input == "":
        return None
    try:
        if isinstance(crs_input, CRS):
            return crs_input
        if isinstance(crs_input, int):
            return CRS.from_epsg(crs_input)
        return CRS.from_user_input(str(crs_input))
    except Exception as exc:  # noqa: BLE001 - pyproj raises RuntimeError subclasses
        logger.warning("Could not parse CRS %r: %s", crs_input, exc)
        return None


def is_geographic(crs: CRS) -> bool:
    """True if the CRS uses angular (lat/lon) coordinates."""
    return crs.is_geographic


def crs_to_string(crs: CRS) -> str:
    """Return a stable, human-readable identifier for a CRS (prefers EPSG)."""
    try:
        epsg = crs.to_epsg()
        if epsg is not None:
            return f"EPSG:{epsg}"
    except Exception:  # noqa: BLE001
        pass
    try:
        return crs.name
    except Exception:  # noqa: BLE001
        return str(crs)


def _utm_crs_for_geometry(geometry: BaseGeometry, source_crs: CRS) -> CRS:
    """Return the UTM CRS appropriate for the geometry's centroid.

    Handles the case where the source CRS is already geographic by using the
    centroid directly, and otherwise transforms the centroid to lat/lon first.
    """
    if source_crs.is_geographic:
        lonlat_crs = source_crs
        centroid = geometry.centroid
        lon, lat = centroid.x, centroid.y
    else:
        # Projected source: convert centroid to WGS84 lat/lon to find the zone.
        lonlat_crs = WGS84_GEOGRAPHIC
        to_wgs84 = Transformer.from_crs(source_crs, lonlat_crs, always_xy=True).transform
        cent = shp_transform(to_wgs84, geometry.centroid)
        lon, lat = cent.x, cent.y

    utm_crs = _utm_crs_from_lonlat(lon, lat)
    return utm_crs


def _utm_crs_from_lonlat(lon: float, lat: float) -> CRS:
    """Pick the UTM zone EPSG code for a given longitude/latitude (WGS84)."""
    zone = int((lon + 180.0) // 6.0) + 1
    if lat >= 0:
        epsg = 32600 + zone  # Northern hemisphere
    else:
        epsg = 32700 + zone  # Southern hemisphere
    return CRS.from_epsg(epsg)


def build_projection_plan(
    geometry: BaseGeometry,
    source_crs: CRS,
) -> ProjectionPlan:
    """Decide on and prepare a projected CRS for measuring ``geometry``.

    The returned plan contains a transformer whose output is in metres, ready
    for planar area/length computation.
    """
    if source_crs.is_geographic:
        if settings.crs_strategy == "web_mercator":
            target_crs = CRS.from_epsg(WEB_MERCATOR_EPSG)
        else:  # "auto" (default) -> UTM zone based on centroid
            target_crs = _utm_crs_for_geometry(geometry, source_crs)
    else:
        # Already projected. If the unit isn't metres we transform to a metre
        # equivalent by going via WGS84 + UTM (keeps things simple & consistent).
        unit_factor = _unit_to_metres_factor(source_crs)
        if abs(unit_factor - 1.0) < 1e-9:
            target_crs = source_crs
        else:
            target_crs = _utm_crs_for_geometry(geometry, source_crs)

    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True).transform
    return ProjectionPlan(
        source_crs=source_crs,
        target_crs=target_crs,
        target_crs_string=crs_to_string(target_crs),
        transformer=transformer,
        unit_is_metres=True,
    )


def _unit_to_metres_factor(crs: CRS) -> float:
    """Conversion factor from the linear unit of a projected CRS to metres."""
    try:
        unit = crs.axis_info[0].unit_name if crs.axis_info else "metre"
    except Exception:  # noqa: BLE001
        unit = "metre"
    unit = (unit or "metre").lower()
    factors = {
        "metre": 1.0,
        "meter": 1.0,
        "m": 1.0,
        "kilometre": 1000.0,
        "kilometer": 1000.0,
        "km": 1000.0,
        "foot": 0.3048,
        "ft": 0.3048,
        "us survey foot": 1200.0 / 3937.0,
        "us_survey_foot": 1200.0 / 3937.0,
    }
    return factors.get(unit, 1.0)


def project_geometry(plan: ProjectionPlan, geometry: BaseGeometry) -> BaseGeometry:
    """Apply the plan's transformer to a geometry, returning the projected copy."""
    return shp_transform(plan.transformer, geometry)
