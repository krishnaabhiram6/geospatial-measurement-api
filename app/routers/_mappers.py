"""Mappers from ORM models to API response schemas."""
from __future__ import annotations

from app.models import FeatureRecord, UploadedFile
from app.schemas import (
    FeatureMeasurementResponse,
    FileInfoResponse,
    FileUploadResponse,
    MeasurementSummary,
    MeasurementsResponse,
)


def _measurement_dict(feat: FeatureRecord) -> dict | None:
    """Reconstruct the measurement dict persisted across columns."""
    if not feat.measurement_supported and feat.measurement_type is None:
        # No measurement was computed (Point/empty/unsupported). Return the
        # minimal unsupported payload that the API contract expects.
        return {
            "supported": False,
            "type": None,
            "value": None,
            "value_km": None,
            "value_km2": None,
            "unit": None,
            "crs": feat.measurement_crs,
            "source_crs": feat.crs,
            "message": f"No measurement is defined for geometry type '{feat.geometry_type}'.",
        }
    return {
        "supported": bool(feat.measurement_supported),
        "type": feat.measurement_type,
        "value": feat.measurement_value,
        "value_km": (
            feat.measurement_value / 1000.0
            if feat.measurement_type == "length" and feat.measurement_value is not None
            else None
        ),
        "value_km2": (
            feat.measurement_value / 1_000_000.0
            if feat.measurement_type == "area" and feat.measurement_value is not None
            else None
        ),
        "unit": feat.measurement_unit,
        "crs": feat.measurement_crs,
        "source_crs": feat.crs,
    }


def to_file_upload(record: UploadedFile) -> FileUploadResponse:
    return FileUploadResponse(
        id=record.id,
        filename=record.filename,
        file_type=record.file_type,
        crs=record.crs,
        feature_count=record.feature_count,
        status=record.status.value if hasattr(record.status, "value") else str(record.status),
        created_at=record.created_at,
    )


def to_file_info(record: UploadedFile) -> FileInfoResponse:
    return FileInfoResponse(
        id=record.id,
        filename=record.filename,
        file_type=record.file_type,
        crs=record.crs,
        feature_count=record.feature_count,
        status=record.status.value if hasattr(record.status, "value") else str(record.status),
        error=record.error,
        created_at=record.created_at,
        processed_at=record.processed_at,
    )


def to_measurements(record: UploadedFile) -> MeasurementsResponse:
    features = [
        FeatureMeasurementResponse(
            feature_index=f.feature_index,
            feature_id=f.feature_id,
            geometry_type=f.geometry_type,
            geometry=f.geometry_geojson,
            crs=f.crs,
            properties=f.properties or {},
            measurement=_measurement_dict(f),
        )
        for f in record.features
    ]

    total = len(features)
    supported = sum(1 for f in features if (f.measurement or {}).get("supported"))
    unsupported = total - supported

    total_area_m2 = 0.0
    total_length_m = 0.0
    has_area = False
    has_length = False
    for f in features:
        m = f.measurement or {}
        if not m.get("supported"):
            continue
        if m.get("type") == "area":
            has_area = True
            total_area_m2 += m.get("value") or 0.0
        elif m.get("type") == "length":
            has_length = True
            total_length_m += m.get("value") or 0.0

    summary = MeasurementSummary(
        total=total,
        supported=supported,
        unsupported=unsupported,
        total_area_m2=round(total_area_m2, 4) if has_area else None,
        total_area_km2=round(total_area_m2 / 1_000_000.0, 6) if has_area else None,
        total_length_m=round(total_length_m, 4) if has_length else None,
        total_length_km=round(total_length_m / 1000.0, 6) if has_length else None,
    )

    return MeasurementsResponse(
        file_id=record.id,
        filename=record.filename,
        crs=record.crs,
        summary=summary,
        features=features,
    )
