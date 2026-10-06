"""On-disk storage helpers for uploaded geospatial files."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.config import settings
from app.exceptions import InvalidFileError


def save_upload(upload_bytes: bytes, original_filename: str) -> tuple[str, Path]:
    """Persist uploaded bytes to the uploads dir with a unique name.

    Returns the generated file id and the path to the stored file.
    """
    file_id = uuid.uuid4().hex
    ext = Path(original_filename).suffix.lower() or ""
    stored_filename = f"{file_id}{ext}"
    stored_path = settings.upload_dir / stored_filename
    with open(stored_path, "wb") as fh:
        fh.write(upload_bytes)
    return file_id, stored_path


def remove_upload(stored_filename: str) -> None:
    """Best-effort removal of a stored upload and any extracted directory."""
    path = settings.upload_dir / stored_filename
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    # Remove extracted directory for shapefiles, if present.
    extracted = settings.upload_dir / Path(stored_filename).stem
    if extracted.exists() and extracted.is_dir():
        shutil.rmtree(extracted, ignore_errors=True)


def extract_zip(zip_path: Path) -> Path:
    """Extract a .zip archive into a sibling directory and return that dir.

    The directory is named after the zip stem. Caller inspects the extracted
    contents (a .shp shapefile bundle and/or a .kml). Raises InvalidFileError
    if the archive is corrupt.
    """
    import zipfile

    target_dir = settings.upload_dir / zip_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
    except zipfile.BadZipFile as exc:
        raise InvalidFileError(
            f"The uploaded file is not a valid zip archive. "
            f"If you uploaded a single .shp file, please zip all shapefile "
            f"components (.shp, .shx, .dbf, .prj) together and upload the .zip. "
            f"Detail: {exc}"
        ) from exc
    return target_dir


def cleanup_extracted(stored_filename: str) -> None:
    """Convenience wrapper to remove the extraction directory of a zip."""
    extracted = settings.upload_dir / Path(stored_filename).stem
    if extracted.exists() and extracted.is_dir():
        shutil.rmtree(extracted, ignore_errors=True)
