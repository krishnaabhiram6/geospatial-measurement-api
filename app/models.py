"""ORM models for uploaded files, extracted features, and measurements."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FileStatus(str, enum.Enum):
    """Lifecycle of an uploaded geospatial file."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)  # shapefile | kml
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus), default=FileStatus.PENDING, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    features: Mapped[list["FeatureRecord"]] = relationship(
        back_populates="uploaded_file",
        cascade="all, delete-orphan",
        order_by="FeatureRecord.feature_index",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UploadedFile id={self.id!r} filename={self.filename!r} status={self.status!r}>"


class FeatureRecord(Base):
    __tablename__ = "features"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("uploaded_files.id"), nullable=False, index=True
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    geometry_geojson: Mapped[dict] = mapped_column(JSON, nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    measurement_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    measurement_crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    measurement_supported: Mapped[bool] = mapped_column(
        Integer, default=0
    )  # stored as int for SQLite portability

    uploaded_file: Mapped["UploadedFile"] = relationship(back_populates="features")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FeatureRecord id={self.id!r} idx={self.feature_index} type={self.geometry_type!r}>"
