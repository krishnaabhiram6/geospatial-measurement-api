"""Unit tests for CRS handling and measurement computation."""
from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon

from app.services import crs as crs_service
from app.services.measurements import compute_measurement, measurement_for_type


def test_measurement_for_type():
    assert measurement_for_type("Polygon") == "area"
    assert measurement_for_type("MultiPolygon") == "area"
    assert measurement_for_type("LineString") == "length"
    assert measurement_for_type("MultiLineString") == "length"
    assert measurement_for_type("Point") is None
    assert measurement_for_type("GeometryCollection") is None


def test_parse_crs_handles_inputs():
    assert crs_service.parse_crs("EPSG:4326").to_epsg() == 4326
    assert crs_service.parse_crs(4326).to_epsg() == 4326
    assert crs_service.parse_crs(None) is None
    assert crs_service.parse_crs("garbage") is None


def test_is_geographic():
    assert crs_service.is_geographic(crs_service.parse_crs("EPSG:4326"))
    assert not crs_service.is_geographic(crs_service.parse_crs("EPSG:3857"))


def test_utm_zone_for_berlin():
    # Berlin ~13.38E, 52.52N -> UTM zone 33N (EPSG:32633)
    utm = crs_service._utm_crs_from_lonlat(13.38, 52.52)
    assert utm.to_epsg() == 32633


def test_polygon_area_in_metres_not_degrees():
    # A ~1 deg x 1 deg box near the equator would be ~12,300 km^2 in reality.
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    result = compute_measurement(polygon, "EPSG:4326")
    assert result["supported"] is True
    assert result["type"] == "area"
    assert result["unit"] == "m^2"
    # 1 deg square at equator ~ 12,390 km^2; allow generous tolerance.
    assert 11_000_000_000 < result["value"] < 13_000_000_000
    assert result["crs"].startswith("EPSG:326")  # northern UTM zone 31N


def test_line_length_in_metres_not_degrees():
    # One degree of longitude at the equator ~ 111 km.
    line = LineString([(0, 0), (1, 0)])
    result = compute_measurement(line, "EPSG:4326")
    assert result["type"] == "length"
    assert 100_000 < result["value"] < 120_000  # ~111 km
    assert result["value_km"] is not None


def test_point_not_supported():
    result = compute_measurement(Point(0, 0), "EPSG:4326")
    assert result["supported"] is False
    assert result["value"] is None


def test_already_projected_crs_is_kept():
    # EPSG:3857 is already in metres; a 1000m square should be 1,000,000 m^2.
    polygon = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)])
    result = compute_measurement(polygon, "EPSG:3857")
    assert result["supported"] is True
    assert abs(result["value"] - 1_000_000.0) < 1.0
    assert result["crs"] == "EPSG:3857"


def test_missing_crs_falls_back_to_4326():
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    result = compute_measurement(polygon, None)
    assert result["source_crs"] == "EPSG:4326"
    assert result["supported"] is True
