"""Upload validation: extension, size, file signature, encryption and safe names."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Literal

FileKind = Literal["pdf", "pptx", "ppt"]

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
# Password-protected OOXML files are OLE containers with this stream name.
ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")
ALLOWED_EXTENSIONS: dict[str, FileKind] = {".pdf": "pdf", ".pptx": "pptx", ".ppt": "ppt"}


class UploadError(Exception):
    """A user-facing problem with the uploaded file."""


def safe_filename(name: str, default: str = "deck") -> str:
    """Strip directories and unsafe characters; keep the extension."""
    base = Path(name.replace("\\", "/")).name
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or default
    ext = re.sub(r"[^A-Za-z0-9]", "", ext).lower()
    return f"{stem[:80]}.{ext}" if ext else stem[:80]


def detect_kind(filename: str, data: bytes, max_bytes: int) -> FileKind:
    """Return the validated file kind or raise UploadError with a clear message."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(
            f"Unsupported file type '{ext or 'none'}'. Upload a PDF, PPTX, or PPT pitch deck."
        )
    if not data:
        raise UploadError("The uploaded file is empty (0 bytes).")
    if len(data) > max_bytes:
        raise UploadError(
            f"The file is {len(data) / 1_048_576:.1f} MB; the limit is "
            f"{max_bytes / 1_048_576:.0f} MB. Compress images or export a smaller PDF."
        )
    kind = ALLOWED_EXTENSIONS[ext]

    if kind == "pdf":
        if b"%PDF-" not in data[:1024]:
            raise UploadError("This file has a .pdf extension but is not a valid PDF.")
        return kind

    if data.startswith(OLE_MAGIC):
        if ENCRYPTED_PACKAGE in data:
            raise UploadError(
                "This presentation is password-protected. Remove the password in "
                "PowerPoint (File > Info > Protect Presentation) and upload it again."
            )
        if kind == "pptx":
            raise UploadError(
                "This file is a legacy PowerPoint (.ppt) file saved with a .pptx extension. "
                "Rename it to .ppt or re-save it as .pptx."
            )
        return "ppt"

    if kind == "ppt":
        if data.startswith(ZIP_MAGIC):
            raise UploadError("This file looks like a .pptx saved with a .ppt extension. Rename it to .pptx.")
        raise UploadError("This file has a .ppt extension but is not a valid PowerPoint file.")

    if not data.startswith(ZIP_MAGIC):
        raise UploadError("This file has a .pptx extension but is not a valid PowerPoint file.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile as exc:
        raise UploadError("The PPTX file is corrupt or incomplete (invalid ZIP archive).") from exc
    if "ppt/presentation.xml" not in names:
        raise UploadError("The file is a ZIP archive but not a PowerPoint presentation.")
    return kind
