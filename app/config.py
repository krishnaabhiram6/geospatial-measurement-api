"""Application configuration loaded from environment variables."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Geospatial File Measurement API"
    app_version: str = "1.0.0"
    debug: bool = False

    # Storage
    upload_dir: Path = Field(default=BASE_DIR / "uploads")
    database_url: str = f"sqlite:///{BASE_DIR / 'geospatial.db'}"

    # Limits
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    allowed_content_types: tuple[str, ...] = (
        "application/zip",
        "application/x-zip-compressed",
        "application/vnd.google-earth.kml+xml",
        "application/octet-stream",
        "text/xml",
        "application/xml",
    )

    # CRS strategy for measurement projection.
    # "auto"  -> pick a UTM zone (or a suitable equal-area fallback) per geometry.
    # "web_mercator" -> force EPSG:3857 (less accurate for area, simple).
    crs_strategy: Literal["auto", "web_mercator"] = "auto"

    # When the source CRS is missing we assume this geographic CRS.
    default_source_crs: str = "EPSG:4326"


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
