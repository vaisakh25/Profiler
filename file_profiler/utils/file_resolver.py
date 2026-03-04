"""
File resolver — validates and resolves paths for MCP tool handlers.

All tool handlers call resolve_path() before passing to the pipeline.
This keeps path validation, security checks, and upload directory
management out of the tool handler code.
"""

from __future__ import annotations

import base64
import logging
import uuid
from pathlib import Path

from file_profiler.config.env import DATA_DIR, UPLOAD_DIR, MAX_UPLOAD_SIZE_MB

log = logging.getLogger(__name__)


class PathSecurityError(Exception):
    """Raised when a resolved path falls outside allowed directories."""


def resolve_path(path: str) -> Path:
    """
    Resolve a user-provided path string to a validated local Path.

    Security: the resolved path must be under DATA_DIR or UPLOAD_DIR.
    This prevents directory traversal attacks (../../etc/passwd).

    Raises:
        FileNotFoundError:  path does not exist.
        PathSecurityError:  path resolves outside allowed directories.
    """
    resolved = Path(path).resolve()

    allowed_roots = (DATA_DIR.resolve(), UPLOAD_DIR.resolve())
    if not any(_is_subpath(resolved, root) for root in allowed_roots):
        raise PathSecurityError(
            f"Access denied: '{path}' resolves outside allowed directories. "
            f"Files must be under {DATA_DIR} or {UPLOAD_DIR}."
        )

    if not resolved.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    return resolved


def save_upload(file_name: str, content_base64: str) -> Path:
    """
    Decode a base64-encoded file and write it to the upload directory.

    Each upload gets a UUID-isolated subdirectory to prevent name
    collisions and simplify cleanup.

    Returns:
        The server-side Path where the file was written.

    Raises:
        ValueError: content exceeds MAX_UPLOAD_SIZE_MB or base64 is invalid.
    """
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid base64 content: {exc}") from exc

    size_mb = len(raw) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise ValueError(
            f"Upload too large: {size_mb:.1f} MB exceeds limit of "
            f"{MAX_UPLOAD_SIZE_MB} MB"
        )

    upload_id = uuid.uuid4().hex[:12]
    dest_dir = UPLOAD_DIR / upload_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file_name
    dest.write_bytes(raw)

    log.info("Upload saved: %s (%d bytes)", dest, len(raw))
    return dest


def _is_subpath(child: Path, parent: Path) -> bool:
    """Check if child is equal to or a subpath of parent."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
