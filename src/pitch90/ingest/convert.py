"""LibreOffice (soffice) discovery and headless conversion."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INSTALL_HELP = (
    "Legacy .ppt files need LibreOffice for conversion. Install it from "
    "https://www.libreoffice.org/download/ (Windows/macOS) or with your package manager "
    "(e.g. `sudo apt install libreoffice-impress`), then restart the app. If it is installed "
    "in a non-standard location, set PITCH90_SOFFICE_PATH to the soffice executable. "
    "Alternatively, open the file in PowerPoint and save it as .pptx or export it as PDF."
)

_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/snap/bin/libreoffice",
]


class ConversionUnavailable(Exception):
    """LibreOffice is not installed or could not be found."""


class ConversionFailed(Exception):
    """LibreOffice ran but did not produce the expected output."""


def find_soffice(configured: str | None = None) -> str | None:
    if configured:
        return configured if Path(configured).is_file() else None
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return next((c for c in _CANDIDATES if Path(c).is_file()), None)


def convert(src: Path, target_ext: str, soffice: str | None, timeout: int = 180) -> Path:
    """Convert ``src`` to ``target_ext`` (e.g. 'pptx' or 'pdf') next to it."""
    if not soffice:
        raise ConversionUnavailable(INSTALL_HELP)
    outdir = src.parent
    # A private profile directory avoids clashing with a running LibreOffice instance.
    with tempfile.TemporaryDirectory(prefix="pitch90_lo_") as profile:
        profile_url = Path(profile).resolve().as_uri()
        cmd = [
            soffice,
            f"-env:UserInstallation={profile_url}",
            "--headless",
            "--norestore",
            "--convert-to",
            target_ext,
            "--outdir",
            str(outdir),
            str(src),
        ]
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(
                cmd, capture_output=True, timeout=timeout, check=False,
                env={**os.environ, "HOME": os.environ.get("HOME", profile)}, **kwargs,
            )
        except FileNotFoundError as exc:
            raise ConversionUnavailable(INSTALL_HELP) from exc
        except subprocess.TimeoutExpired as exc:
            raise ConversionFailed(
                f"LibreOffice did not finish converting within {timeout} seconds."
            ) from exc
    out = outdir / f"{src.stem}.{target_ext}"
    if not out.is_file() or out.stat().st_size == 0:
        raise ConversionFailed(
            "LibreOffice could not convert the file. It may be corrupt or password-protected; "
            "try re-saving it as .pptx or exporting it as PDF."
        )
    return out
