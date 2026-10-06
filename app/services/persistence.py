"""Persistence/orchestration: persist an uploaded file and its features.

This layer sits between the API routers and the geospatial services. It owns:
  * writing the upload to disk,
  * kicking off synchronous processing,
  * storing the file + features + measurements in the database,
  * reading them back for the GET endpoints.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.exceptions import FileNotFoundError_, ProcessingError
from app.models import FeatureRecord, FileStatus, UploadedFile
from app.services.file_processor import process_file
from app.storage import cleanup_extracted, remove_upload, save_upload

logger = logging.getLogger(__name__)


def get_file(db: Session, file_id: str) -> UploadedFile | None:
    return db.get(UploadedFile, file_id)


def require_file(db: Session, file_id: str) -> UploadedFile:
    obj = get_file(db, file_id)
    if obj is None:
        raise FileNotFoundError_(f"No uploaded file found with id '{file_id}'.")
    return obj


def ingest_upload(
    db: Session,
    *,
    upload_bytes: bytes,
    original_filename: str,
    file_type: str,
) -> UploadedFile:
    """Persist + process an uploaded geospatial file synchronously.

    The file is marked PROCESSING during the (short) processing step, then
    COMPLETED or FAILED depending on the outcome. On failure the partial
    database record is kept (with status=FAILED) so the client can read the
    error message, and the stored bytes are removed to save space.
    """
    file_id, stored_path = save_upload(upload_bytes, original_filename)
    stored_filename = stored_path.name

    record = UploadedFile(
        id=file_id,
        filename=original_filename,
        stored_filename=stored_filename,
        file_type=file_type,
        status=FileStatus.PROCESSING,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    try:
        processed = process_file(stored_path, original_filename, file_type)
    except Exception as exc:  # noqa: BLE001 - surface any processing failure to client
        logger.exception("Processing failed for file %s", file_id)
        record.status = FileStatus.FAILED
        record.error = str(exc)
        record.processed_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
        # Clean up the stored bytes; the failed record remains for diagnostics.
        remove_upload(stored_filename)
        raise ProcessingError(f"File processing failed: {exc}") from exc

    record.crs = processed.crs
    record.file_type = processed.file_type
    record.feature_count = processed.feature_count
    record.status = FileStatus.COMPLETED
    record.processed_at = datetime.utcnow()

    for feat in processed.features:
        m = feat.measurement or {}
        record.features.append(
            FeatureRecord(
                id=str(uuid.uuid4()),
                file_id=record.id,
                feature_index=feat.feature_index,
                feature_id=feat.feature_id,
                geometry_type=feat.geometry_type,
                geometry_geojson=feat.geometry_geojson,
                properties=feat.properties,
                crs=feat.crs,
                measurement_type=m.get("type"),
                measurement_value=m.get("value"),
                measurement_unit=m.get("unit"),
                measurement_crs=m.get("crs"),
                measurement_supported=1 if m.get("supported") else 0,
            )
        )

    db.commit()
    db.refresh(record)

    # Free disk: drop the raw upload + extracted shapefile dir now that we have
    # persisted the normalized features. Keep them if you'd rather re-process.
    remove_upload(stored_filename)
    if file_type == "shapefile":
        cleanup_extracted(stored_filename)

    return record
