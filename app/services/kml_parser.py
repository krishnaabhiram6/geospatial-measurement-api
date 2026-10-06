"""Self-contained KML reader (no GDAL/OGR KML driver required).

Fiona/geopandas builds on Windows frequently ship without the OGR KML or
LIBKML drivers, so reading ``.kml`` via ``geopandas.read_file`` is unreliable.
This module parses KML with the standard-library XML parser and builds a
geopandas GeoDataFrame directly, using shapely to construct geometries.

KML is *always* encoded in WGS84 geographic coordinates (EPSG:4326), so the
resulting GeoDataFrame is assigned that CRS.

Supported geometry elements:
  - Point
  - LineString
  - LinearRing  (treated as a closed line; also usable as a polygon ring)
  - Polygon     (with optional inner rings / holes)
  - MultiGeometry (recursively, collapsed to a shapely collection)
  - GeometryCollection (rare in KML, handled via MultiGeometry path)

Placemark properties collected:
  - name, description, styleUrl, address, phoneNumber, visibility, snippet
  - ExtendedData/Data values
  - ExtendedData/SchemaData/SimpleData values
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
)
from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)

# KML is always WGS84 geographic.
KML_CRS = "EPSG:4326"

# Common KML namespaces (we strip them all for tolerant parsing).
_KML_NAMESPACES = (
    "http://www.opengis.net/kml/2.2",
    "http://earth.google.com/kml/2.2",
    "http://www.opengis.net/kml/2.3",
)


def _localname(tag: str) -> str:
    """Return the local part of an XML tag (drop namespace prefix)."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_coordinates(text: str | None) -> list[tuple[float, float, float]]:
    """Parse a KML <coordinates> string into a list of (lon, lat, z) tuples.

    KML coordinate tuples are comma-separated (lon,lat[,alt]) and whitespace
    separates the tuples. Trailing/leading whitespace and extra spaces are
    tolerated.
    """
    if not text:
        return []
    coords: list[tuple[float, float, float]] = []
    for chunk in text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0
        except ValueError:
            continue
        coords.append((lon, lat, alt))
    return coords


def _strip_z(coord_pairs: list[tuple[float, float, float]]) -> list[tuple[float, float]]:
    """Drop the altitude component for 2D shapely geometries."""
    return [(c[0], c[1]) for c in coord_pairs]


def _build_point(elem: ET.Element) -> Point:
    coords = _parse_coordinates(elem.findtext("coordinates"))
    if not coords:
        return Point()
    return Point(coords[0][0], coords[0][1])


def _build_linestring(elem: ET.Element) -> LineString:
    coords = _strip_z(_parse_coordinates(elem.findtext("coordinates")))
    return LineString(coords) if len(coords) >= 2 else LineString()


def _build_linearring(elem: ET.Element) -> LineString:
    coords = _strip_z(_parse_coordinates(elem.findtext("coordinates")))
    # A LinearRing is a closed line; keep it as a LineString for measurement
    # purposes (length), which matches the "ring" geometry type expectation.
    if len(coords) >= 2 and coords[0] != coords[-1]:
        coords.append(coords[0])
    return LineString(coords) if len(coords) >= 2 else LineString()


def _build_polygon(elem: ET.Element) -> Polygon:
    outer: list[tuple[float, float]] = []
    inners: list[list[tuple[float, float]]] = []
    for child in elem:
        name = _localname(child.tag)
        if name == "outerBoundaryIs":
            ring = child.find(".//LinearRing")
            if ring is not None:
                outer = _strip_z(_parse_coordinates(ring.findtext("coordinates")))
        elif name == "innerBoundaryIs":
            ring = child.find(".//LinearRing")
            if ring is not None:
                inners.append(_strip_z(_parse_coordinates(ring.findtext("coordinates"))))
    if not outer:
        return Polygon()
    return Polygon(shell=outer, holes=inners if inners else None)


def _build_geometry(elem: ET.Element) -> BaseGeometry | None:
    """Recursively build a shapely geometry from a KML geometry element."""
    name = _localname(elem.tag)
    if name == "Point":
        return _build_point(elem)
    if name == "LineString":
        return _build_linestring(elem)
    if name == "LinearRing":
        return _build_linearring(elem)
    if name == "Polygon":
        return _build_polygon(elem)
    if name in ("MultiGeometry", "GeometryCollection"):
        parts: list[BaseGeometry] = []
        for child in elem:
            g = _build_geometry(child)
            if g is not None and not g.is_empty:
                parts.append(g)
        return _collapse_to_multi(parts)
    logger.debug("Ignoring unsupported KML geometry element <%s>", name)
    return None


def _collapse_to_multi(parts: list[BaseGeometry]) -> BaseGeometry | None:
    """Collapse a list of geometries into a typed Multi* / GeometryCollection."""
    if not parts:
        return None
    types = {g.geom_type for g in parts}
    if len(types) == 1 and len(parts) > 1:
        only = parts[0].geom_type
        if only == "Point":
            return MultiPoint([g.coords[0] for g in parts])
        if only == "LineString":
            return MultiLineString([list(g.coords) for g in parts])
        if only == "Polygon":
            return MultiPolygon([g for g in parts])
    if len(parts) == 1:
        return parts[0]
    return GeometryCollection(parts)


def _extract_extended_data(placemark: ET.Element) -> dict:
    """Pull ExtendedData/Data and SchemaData/SimpleData into a flat dict."""
    props: dict[str, str] = {}
    extended = placemark.find("ExtendedData")
    if extended is None:
        # Handle namespaced variants.
        extended = next((c for c in placemark if _localname(c.tag) == "ExtendedData"), None)
    if extended is not None:
        # <Data name="x"><value>y</value></Data>
        for data in extended.iter():
            if _localname(data.tag) == "Data":
                key = data.get("name")
                val = data.findtext("value")
                if key is not None:
                    props[key] = val if val is not None else ""
            elif _localname(data.tag) == "SimpleData":
                key = data.get("name")
                if key is not None:
                    props[key] = data.text or ""
    return props


def _extract_properties(placemark: ET.Element) -> dict:
    """Collect non-geometry properties from a Placemark."""
    props: dict[str, object] = {}
    scalar_keys = ("name", "description", "styleUrl", "address", "phoneNumber", "snippet")
    for key in scalar_keys:
        text = placemark.findtext(key)
        if text is not None:
            props[key] = text
    # visibility is a numeric boolean
    vis = placemark.findtext("visibility")
    if vis is not None:
        try:
            props["visibility"] = int(vis)
        except ValueError:
            props["visibility"] = vis
    props.update(_extract_extended_data(placemark))
    return props


def _iter_placemarks(root: ET.Element) -> Iterable[ET.Element]:
    """Yield all Placemark elements anywhere in the tree (folders, docs, etc.)."""
    for elem in root.iter():
        if _localname(elem.tag) == "Placemark":
            yield elem


def _first_geometry(placemark: ET.Element) -> BaseGeometry | None:
    """Find the first geometry-bearing child of a Placemark."""
    for child in placemark:
        name = _localname(child.tag)
        if name in ("Point", "LineString", "LinearRing", "Polygon", "MultiGeometry", "GeometryCollection"):
            return _build_geometry(child)
    return None


def _strip_namespaces(root: ET.Element) -> ET.Element:
    """Remove XML namespace prefixes from every element in the tree.

    ElementTree's ``.find()``/``.findtext()`` won't match a bare tag name against
    a namespaced tag (e.g. ``find('coordinates')`` won't match
    ``{http://...}coordinates``). Stripping the namespace from every tag up
    front lets the rest of the parser use simple bare-name lookups and is
    robust to different KML namespace versions.
    """
    for elem in root.iter():
        if isinstance(elem.tag, str) and "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def read_kml(path: Path):
    """Parse a KML file and return a geopandas GeoDataFrame (EPSG:4326).

    Returns a GeoDataFrame with a ``geometry`` column and one column per
    collected property. Placemarks without a parseable geometry are skipped
    (with a debug log) so a single bad placemark never fails the whole file.
    """
    import geopandas as gpd

    tree = ET.parse(str(path))
    root = _strip_namespaces(tree.getroot())

    records: list[dict] = []
    all_keys: list[str] = []
    for placemark in _iter_placemarks(root):
        geometry = _first_geometry(placemark)
        if geometry is None or geometry.is_empty:
            logger.debug("Skipping Placemark without a usable geometry.")
            continue
        props = _extract_properties(placemark)
        record = dict(props)
        record["geometry"] = geometry
        records.append(record)
        for k in props:
            if k not in all_keys:
                all_keys.append(k)

    if not records:
        # Return an empty frame so the caller can decide what to do.
        return gpd.GeoDataFrame(geometry=[], crs=KML_CRS)

    # Normalise columns so every row has the same keys (fill missing with None).
    normalised: list[dict] = []
    for rec in records:
        row = {k: rec.get(k) for k in all_keys}
        row["geometry"] = rec["geometry"]
        normalised.append(row)

    gdf = gpd.GeoDataFrame(normalised, geometry="geometry", crs=KML_CRS)
    return gdf
