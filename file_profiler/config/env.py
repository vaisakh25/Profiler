"""
Environment-based configuration for the MCP server layer.

Pipeline-internal settings remain in config/settings.py (they are tuning
constants, not deployment knobs).  This module covers deployment config
that changes between local dev, Docker, and cloud.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- File system ---------------------------------------------------------
DATA_DIR = Path(os.getenv("PROFILER_DATA_DIR", "/data"))
UPLOAD_DIR = Path(os.getenv("PROFILER_UPLOAD_DIR", str(DATA_DIR / "uploads")))
OUTPUT_DIR = Path(os.getenv("PROFILER_OUTPUT_DIR", str(DATA_DIR / "output")))

# --- Upload limits -------------------------------------------------------
MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500"))
UPLOAD_TTL_HOURS: int = int(os.getenv("UPLOAD_TTL_HOURS", "1"))

# --- Server --------------------------------------------------------------
DEFAULT_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio")
DEFAULT_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
DEFAULT_PORT: int = int(os.getenv("MCP_PORT", "8080"))

# --- Logging -------------------------------------------------------------
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = os.getenv(
    "LOG_FORMAT",
    "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
