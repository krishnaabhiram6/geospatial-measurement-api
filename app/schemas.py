"""Pydantic schemas for API request/response validation."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileUploadResponse(BaseModel):
    """Returned right after an upload completes (synchronous processing)."""

    id: str
    filename: str
    file_type: str
    crs: str | None = None
    feature_count: int
    status: str
    created_at: datetime


class FileInfoResponse(BaseModel):
    """Schema for GET /api/files/{id}/."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    crs: str | None = None
    feature_count: int
    status: str
    error: str | None = None
    created_at: datetime
    processed_at: datetime | None = None


class GeometryResponse(BaseModel):
    """GeoJSON-like geometry payload."""

    type: str
    coordinates: list | dict  # GeoJSON coordinates (varies by geometry type)


class FeatureMeasurementResponse(BaseModel):
    """Per-feature measurement + metadata."""

    feature_index: int
    feature_id: str | None = None
    geometry_type: str
    geometry: dict = Field(description="GeoJSON geometry")
    crs: str | None = None
    properties: dict = Field(default_factory=dict)
    measurement: dict | None = Field(
        default=None,
        description="Measurement details (area/length) or null if unsupported.",
    )


class MeasurementSummary(BaseModel):
    """Aggregate stats included in the measurements response."""

    total: int
    supported: int
    unsupported: int
    total_area_m2: float | None = None
    total_area_km2: float | None = None
    total_length_m: float | None = None
    total_length_km: float | None = None


class MeasurementsResponse(BaseModel):
    """Schema for GET /api/files/{id}/measurements/."""

    file_id: str
    filename: str
    crs: str | None = None
    summary: MeasurementSummary
    features: list[FeatureMeasurementResponse]


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None
