from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def get_attachment_dir(workspace: str | Path) -> Path:
    path = Path(workspace).resolve() / ".evo-harness" / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def import_attachment_file(
    *,
    workspace: str | Path,
    source_path: str | Path,
    mime_type: str | None = None,
    file_name: str | None = None,
    source: str | None = None,
    delete_source: bool = False,
) -> dict[str, Any]:
    source_file = Path(source_path).expanduser().resolve()
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Attachment source not found: {source_file}")

    byte_count = source_file.stat().st_size
    if byte_count <= 0:
        raise ValueError("Attachment source is empty")
    if byte_count > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"Attachment is too large ({byte_count} bytes). Maximum supported size is {MAX_ATTACHMENT_BYTES} bytes."
        )

    detected_mime = _normalized_mime_type(mime_type or mimetypes.guess_type(source_file.name)[0])
    if detected_mime not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(
            "Unsupported attachment type. Only clipboard images in PNG, JPEG, GIF, WEBP, or BMP are supported."
        )

    attachment_id = f"att_{uuid4().hex}"
    extension = SUPPORTED_IMAGE_MIME_TYPES[detected_mime]
    target_path = get_attachment_dir(workspace) / f"{attachment_id}{extension}"
    shutil.copy2(source_file, target_path)

    width, height = _sniff_image_dimensions(target_path, detected_mime)
    attachment = {
        "id": attachment_id,
        "kind": "image",
        "file_name": _display_name(file_name, default=f"{attachment_id}{extension}"),
        "mime_type": detected_mime,
        "path": str(target_path),
        "byte_count": int(target_path.stat().st_size),
        "source": str(source or "clipboard"),
        **({"width": width, "height": height} if width and height else {}),
    }

    if delete_source:
        try:
            source_file.unlink()
        except OSError:
            pass
    return attachment


def discard_attachment(attachment: dict[str, Any]) -> None:
    path_text = str(attachment.get("path", "") or "").strip()
    if not path_text:
        return
    path = Path(path_text)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _normalized_mime_type(mime_type: str | None) -> str:
    text = str(mime_type or "").strip().lower()
    if text == "image/jpg":
        return "image/jpeg"
    return text


def _display_name(file_name: str | None, *, default: str) -> str:
    value = str(file_name or "").strip()
    if not value:
        return default
    return Path(value).name or default


def _sniff_image_dimensions(path: Path, mime_type: str) -> tuple[int | None, int | None]:
    try:
        with path.open("rb") as handle:
            header = handle.read(64)
            if mime_type == "image/png" and len(header) >= 24:
                width = int.from_bytes(header[16:20], "big")
                height = int.from_bytes(header[20:24], "big")
                return width or None, height or None
            if mime_type == "image/gif" and len(header) >= 10:
                width = int.from_bytes(header[6:8], "little")
                height = int.from_bytes(header[8:10], "little")
                return width or None, height or None
            if mime_type == "image/bmp" and len(header) >= 26:
                width = int.from_bytes(header[18:22], "little", signed=True)
                height = abs(int.from_bytes(header[22:26], "little", signed=True))
                return width or None, height or None
            if mime_type == "image/jpeg":
                return _sniff_jpeg_dimensions(path)
            if mime_type == "image/webp" and len(header) >= 30 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                chunk = header[12:16]
                if chunk == b"VP8X" and len(header) >= 30:
                    width = 1 + int.from_bytes(header[24:27], "little")
                    height = 1 + int.from_bytes(header[27:30], "little")
                    return width or None, height or None
    except OSError:
        return None, None
    return None, None


def _sniff_jpeg_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"\xff\xd8":
                return None, None
            while True:
                marker_prefix = handle.read(1)
                if not marker_prefix:
                    return None, None
                if marker_prefix != b"\xff":
                    continue
                marker = handle.read(1)
                while marker == b"\xff":
                    marker = handle.read(1)
                if not marker:
                    return None, None
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                block_length = int.from_bytes(handle.read(2), "big")
                if block_length < 2:
                    return None, None
                if marker in {
                    b"\xc0",
                    b"\xc1",
                    b"\xc2",
                    b"\xc3",
                    b"\xc5",
                    b"\xc6",
                    b"\xc7",
                    b"\xc9",
                    b"\xca",
                    b"\xcb",
                    b"\xcd",
                    b"\xce",
                    b"\xcf",
                }:
                    _precision = handle.read(1)
                    height = int.from_bytes(handle.read(2), "big")
                    width = int.from_bytes(handle.read(2), "big")
                    return width or None, height or None
                handle.seek(block_length - 2, 1)
    except OSError:
        return None, None
