"""Integration tests for the Geospatial File Measurement API."""
from __future__ import annotations


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_upload_kml(client, kml_bytes):
    res = client.post(
        "/api/files/",
        files={"file": ("survey.kml", kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["filename"] == "survey.kml"
    assert body["file_type"] == "kml"
    assert body["feature_count"] == 3
    assert body["status"] == "COMPLETED"
    assert body["crs"] == "EPSG:4326"
    file_id = body["id"]

    # GET /api/files/{id}/
    info = client.get(f"/api/files/{file_id}/")
    assert info.status_code == 200
    info_body = info.json()
    assert info_body["id"] == file_id
    assert info_body["feature_count"] == 3
    assert info_body["status"] == "COMPLETED"

    # GET /api/files/{id}/measurements/
    meas = client.get(f"/api/files/{file_id}/measurements/")
    assert meas.status_code == 200
    meas_body = meas.json()
    assert meas_body["file_id"] == file_id
    summary = meas_body["summary"]
    assert summary["total"] == 3
    # Polygon + LineString are supported, Point is not -> supported == 2
    assert summary["supported"] == 2
    assert summary["unsupported"] == 1
    assert summary["total_area_m2"] is not None and summary["total_area_m2"] > 0
    assert summary["total_length_m"] is not None and summary["total_length_m"] > 0

    types = {f["geometry_type"] for f in meas_body["features"]}
    assert types == {"Polygon", "LineString", "Point"}

    by_type = {f["geometry_type"]: f for f in meas_body["features"]}
    # Polygon -> area in m^2 with a projected CRS (UTM zone 33N for Berlin).
    poly = by_type["Polygon"]
    assert poly["measurement"]["supported"] is True
    assert poly["measurement"]["type"] == "area"
    assert poly["measurement"]["unit"] == "m^2"
    assert poly["measurement"]["value"] > 0
    assert poly["measurement"]["value_km2"] is not None
    assert poly["measurement"]["crs"].startswith("EPSG:326")  # UTM northern

    # LineString -> length in m.
    line = by_type["LineString"]
    assert line["measurement"]["supported"] is True
    assert line["measurement"]["type"] == "length"
    assert line["measurement"]["unit"] == "m"
    assert line["measurement"]["value"] > 0
    assert line["measurement"]["value_km"] is not None

    # Point -> unsupported, graceful.
    point = by_type["Point"]
    assert point["measurement"]["supported"] is False
    assert point["measurement"]["value"] is None


def test_upload_shapefile_zip(client, shapefile_zip_bytes):
    res = client.post(
        "/api/files/",
        files={"file": ("sample.zip", shapefile_zip_bytes, "application/zip")},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["file_type"] == "shapefile"
    assert body["feature_count"] == 3
    assert body["status"] == "COMPLETED"

    meas = client.get(f"/api/files/{body['id']}/measurements/")
    assert meas.status_code == 200
    meas_body = meas.json()
    summary = meas_body["summary"]
    # Shapefiles hold a single geometry type; the fixture is 3 polygons.
    assert summary["total"] == 3
    assert summary["supported"] == 3
    assert summary["unsupported"] == 0
    assert summary["total_area_m2"] is not None and summary["total_area_m2"] > 0
    assert summary["total_length_m"] is None  # no line features
    # Every feature is an area measurement.
    for feat in meas_body["features"]:
        assert feat["geometry_type"] == "Polygon"
        assert feat["measurement"]["type"] == "area"


def test_unsupported_file_type(client):
    res = client.post(
        "/api/files/",
        files={"file": ("data.geojson", b"{}", "application/json")},
    )
    assert res.status_code == 415
    assert res.json()["error_code"] == "UNSUPPORTED_FILE_TYPE"


def test_empty_file_rejected(client):
    res = client.post(
        "/api/files/",
        files={"file": ("empty.kml", b"", "application/vnd.google-earth.kml+xml")},
    )
    assert res.status_code == 422


def test_file_not_found(client):
    res = client.get("/api/files/does-not-exist/")
    assert res.status_code == 404
    assert res.json()["error_code"] == "FILE_NOT_FOUND"


def test_measurements_not_found(client):
    res = client.get("/api/files/does-not-exist/measurements/")
    assert res.status_code == 404


def test_invalid_zip_rejected(client):
    res = client.post(
        "/api/files/",
        files={"file": ("not-a-shapefile.zip", b"not a zip", "application/zip")},
    )
    assert res.status_code == 422  # InvalidFileError
