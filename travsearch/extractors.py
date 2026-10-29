# SPDX-FileCopyrightText: TravSearch | Copyright (c) 2026 Travis L. Seymour, PhD <nogard@ucsc.edu>
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
import re
import shutil
import subprocess
import zipfile

# Office formats that are zip-based; map suffix -> xml path inside the zip
OFFICE_SUFFIXES: dict[str, str] = {
    ".docx": "word/document.xml",
    ".odt": "content.xml",
    ".xlsx": "xl/sharedStrings.xml",
    ".ods": "content.xml",
    ".pptx": "ppt/slides/slide1.xml",
}

PDF_SUFFIXES = {".pdf"}

# Common binary file extensions to always exclude from content search
BINARY_SUFFIXES = {
    # Executables and libraries
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".msi",
    # Object/compiled files
    ".o",
    ".obj",
    ".a",
    ".lib",
    ".pyc",
    ".pyo",
    ".pyd",
    ".class",
    ".jar",
    ".wasm",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".cab",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".tiff",
    ".tif",
    ".svg",
    # Audio/Video
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".wav",
    ".flac",
    ".ogg",
    ".webm",
    ".wmv",
    # Databases
    ".db",
    ".sqlite",
    ".sqlite3",
    # Fonts
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    # Other
    ".dat",
    ".pak",
    ".iso",
    ".tc",
    ".dmg",
}

_TAG_RE = re.compile(r"<[^>]+>")


def extract_office_text(path: Path) -> str | None:
    """Extract plain text from a zip-based office document."""
    suffix = path.suffix.lower()
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if suffix == ".pptx":
                xml_names = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml", n))
            elif suffix in (".odt", ".ods"):
                xml_names = ["content.xml"]
            elif suffix == ".docx":
                xml_names = ["word/document.xml"]
            elif suffix == ".xlsx":
                xml_names = [n for n in names if n.startswith("xl/") and n.endswith(".xml")]
            else:
                xml_names = [OFFICE_SUFFIXES.get(suffix, "")]

            parts: list[str] = []
            for name in xml_names:
                if name in names:
                    raw = zf.read(name).decode("utf-8", errors="replace")
                    parts.append(_TAG_RE.sub(" ", raw))
            return "\n".join(parts) if parts else None
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError):
        return None


def extract_pdf_text(path: Path) -> str | None:
    """Extract plain text from a PDF using pdftotext."""
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        return None
    try:
        result = subprocess.run(
            [pdftotext, "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None
