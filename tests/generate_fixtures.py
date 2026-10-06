"""Generate sample geospatial test fixtures (a KML and a zipped Shapefile).

Run directly:  python tests/generate_fixtures.py
Creates tests/data/sample.kml and tests/data/sample_shapefile.zip without any
network access. The KML is written by hand (no GDAL KML driver needed) and the
shapefile via the ESRI Shapefile driver bundled with fiona.
"""
from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Coordinates near Berlin (EPSG:4326).
POLY_COORDS = [
    (13.3770, 52.5160),
    (13.3870, 52.5160),
    (13.3870, 52.5260),
    (13.3770, 52.5260),
    (13.3770, 52.5160),  # close ring
]
LINE_START = (13.3770, 52.5160)
LINE_END = (13.3870, 52.5260)
POINT_COORD = (13.3820, 52.5210)


def _coord(p) -> str:
    return f"{p[0]},{p[1]},0"


def _coords_list(points) -> str:
    return " ".join(_coord(p) for p in points)


def write_kml(path: Path) -> None:
    """Write a hand-crafted KML with a Polygon, LineString, and Point."""
    polygon_coords = _coords_list(POLY_COORDS)
    line_coords = _coords_list([LINE_START, LINE_END])
    point_coords = _coord(POINT_COORD)

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Sample Survey</name>
    <Placemark>
      <name>berlin_block</name>
      <description>A roughly 1km x 1km block near Berlin</description>
      <ExtendedData>
        <Data name="value"><value>42</value></Data>
        <Data name="category"><value>residential</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{polygon_coords}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>diagonal</name>
      <ExtendedData>
        <Data name="value"><value>7</value></Data>
      </ExtendedData>
      <LineString>
        <coordinates>{line_coords}</coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>centre_point</name>
      <ExtendedData>
        <Data name="value"><value>0</value></Data>
      </ExtendedData>
      <Point>
        <coordinates>{point_coords}</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""
    path.write_text(kml, encoding="utf-8")


def write_shapefile_zip(path: Path) -> None:
    """Build three polygon features as a zipped ESRI Shapefile.

    ESRI Shapefiles can only contain a single geometry type, so we use three
    polygons here. The KML fixture covers the mixed-type (polygon/line/point)
    case that exercises the unsupported-geometry handling path.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon

    poly1 = Polygon(POLY_COORDS)  # ~1km block near Berlin
    poly2 = Polygon(  # a smaller block to the east
        [
            (13.390, 52.516),
            (13.395, 52.516),
            (13.395, 52.520),
            (13.390, 52.520),
            (13.390, 52.516),
        ]
    )
    poly3 = Polygon(  # a triangle
        [
            (13.377, 52.527),
            (13.382, 52.530),
            (13.387, 52.527),
            (13.377, 52.527),
        ]
    )

    gdf = gpd.GeoDataFrame(
        {
            "name": ["berlin_block", "small_block", "triangle"],
            "value": [42, 7, 3],
            "category": ["residential", "commercial", "park"],
            "geometry": [poly1, poly2, poly3],
        },
        crs="EPSG:4326",
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "sample.shp"
            gdf.to_file(tmp_path, driver="ESRI Shapefile")
            for part in Path(tmp).glob("sample.*"):
                zf.write(part, arcname=part.name)
    path.write_bytes(buf.getvalue())


def main() -> None:
    kml_path = DATA_DIR / "sample.kml"
    zip_path = DATA_DIR / "sample_shapefile.zip"
    write_kml(kml_path)
    write_shapefile_zip(zip_path)
    print(f"Wrote {kml_path} ({kml_path.stat().st_size} bytes)")
    print(f"Wrote {zip_path} ({zip_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
