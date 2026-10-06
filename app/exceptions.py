"""Application-specific exceptions and FastAPI exception handlers."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class GeospatialError(Exception):
    """Base class for geospatial processing errors."""

    error_code = "GEOSPATIAL_ERROR"


class UnsupportedFileTypeError(GeospatialError):
    error_code = "UNSUPPORTED_FILE_TYPE"


class InvalidFileError(GeospatialError):
    error_code = "INVALID_FILE"


class FileNotFoundError_(GeospatialError):
    error_code = "FILE_NOT_FOUND"


class ProcessingError(GeospatialError):
    error_code = "PROCESSING_ERROR"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(FileNotFoundError_)
    async def file_not_found_handler(request: Request, exc: FileNotFoundError_):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @app.exception_handler(UnsupportedFileTypeError)
    async def unsupported_file_type_handler(request: Request, exc: UnsupportedFileTypeError):
        return JSONResponse(
            status_code=415,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @app.exception_handler(InvalidFileError)
    async def invalid_file_handler(request: Request, exc: InvalidFileError):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @app.exception_handler(ProcessingError)
    async def processing_error_handler(request: Request, exc: ProcessingError):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "error_code": exc.error_code},
        )
