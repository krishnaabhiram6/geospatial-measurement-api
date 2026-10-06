"""API endpoints for uploading and inspecting geospatial files.

Endpoints
---------
POST /api/files/                  -> upload + process a .zip (shapefile) or .kml
GET  /api/files/{id}/             -> metadata for an uploaded file
GET  /api/files/{id}/measurements/-> per-feature measurements + summary
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.exceptions import InvalidFileError, UnsupportedFileTypeError
from app.models import UploadedFile
from app.routers._mappers import to_file_info, to_file_upload, to_measurements
from app.schemas import (
    FileInfoResponse,
    FileUploadResponse,
    MeasurementsResponse,
)
from app.services.file_processor import detect_file_type
from app.services.persistence import ingest_upload, require_file

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=201,
    summary="Upload and process a geospatial file",
)
async def upload_file(
    file: UploadFile = File(..., description="A .zip shapefile bundle or a .kml file"),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Accept a `.zip` (shapefile) or `.kml` upload, process it synchronously,
    and return the resulting file metadata.

    The file is read entirely into memory (size capped by ``MAX_UPLOAD_BYTES``),
    so very large files will be rejected before processing begins.
    """
    original_filename = file.filename or "upload"
    file_type = detect_file_type(original_filename)

    data = await file.read()
    if not data:
        raise InvalidFileError("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise UnsupportedFileTypeError(
            f"Uploaded file is too large ({len(data)} bytes). "
            f"Maximum allowed size is {settings.max_upload_bytes} bytes."
        )

    record = ingest_upload(
        db,
        upload_bytes=data,
        original_filename=original_filename,
        file_type=file_type,
    )
    return to_file_upload(record)


@router.get(
    "/{file_id}/",
    response_model=FileInfoResponse,
    summary="Get information about an uploaded file",
)
def get_file_info(file_id: str, db: Session = Depends(get_db)) -> FileInfoResponse:
    record = require_file(db, file_id)
    return to_file_info(record)


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get measurements for the features in an uploaded file",
)
def get_measurements(file_id: str, db: Session = Depends(get_db)) -> MeasurementsResponse:
    record = require_file(db, file_id)
    return to_measurements(record)
