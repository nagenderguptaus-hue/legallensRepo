"""Upload checks that run inside the upload request, so the user gets an immediate answer
(FR-2, NFR-3, NFR-5). The type is decided by file content, never by extension.
"""

import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docx
from pypdf import PasswordType, PdfReader

from legallens.errors import AppError, unprocessable

FileType = Literal["pdf", "docx"]

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
# Compound File Binary: legacy .doc, and password-protected Office files.
CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_UNPACKED_DOCX_BYTES = 512 * 1024 * 1024  # zip-bomb guard
WORDS_PER_PAGE = 500

UNSUPPORTED = "Only PDF and Word (.docx) files are supported."
UNREADABLE = "This file could not be read. It may be corrupted."


@dataclass(frozen=True)
class FileInfo:
    type: FileType
    pages: int | None


def unsupported(message: str = UNSUPPORTED) -> AppError:
    return AppError(415, "unsupported_type", message)


def inspect_file(path: Path, display_name: str, max_pages: int) -> FileInfo:
    """Detects the real type and checks encryption, readability and page count.

    Blocking (parses the file); call it via ``asyncio.to_thread``.
    """
    with path.open("rb") as fh:
        head = fh.read(1024)

    if PDF_MAGIC in head:
        info = FileInfo("pdf", _pdf_pages(path))
    elif head.startswith(ZIP_MAGIC):
        info = FileInfo("docx", _docx_pages(path))
    elif head.startswith(CFB_MAGIC):
        if display_name.lower().endswith(".docx"):
            raise unprocessable(
                "encrypted_file",
                "This Word file is password-protected. Remove the password and upload it again.",
            )
        raise unsupported(
            "Older Word (.doc) files aren't supported. Save it as .docx and upload again."
        )
    else:
        raise unsupported()

    if info.pages is not None and info.pages > max_pages:
        raise unprocessable(
            "too_many_pages",
            f"This document has {info.pages} pages. The limit is {max_pages} pages.",
        )
    return info


def _pdf_pages(path: Path) -> int:
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            raise unprocessable(
                "encrypted_file",
                "This PDF is password-protected. Remove the password and upload it again.",
            )
        return len(reader.pages)
    except AppError:
        raise
    except Exception as exc:
        raise unprocessable("unreadable_file", UNREADABLE) from exc


def _docx_pages(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise unsupported()
            if sum(item.file_size for item in archive.infolist()) > MAX_UNPACKED_DOCX_BYTES:
                raise unprocessable("unreadable_file", UNREADABLE)
            app_xml = (
                archive.read("docProps/app.xml").decode("utf-8", "replace")
                if "docProps/app.xml" in names
                else ""
            )
        document = docx.Document(str(path))
    except AppError:
        raise
    except Exception as exc:
        raise unprocessable("unreadable_file", UNREADABLE) from exc

    match = re.search(r"<Pages>(\d+)</Pages>", app_xml)
    if match and int(match.group(1)) > 0:
        return int(match.group(1))
    words = sum(len(p.text.split()) for p in document.paragraphs)
    return max(1, math.ceil(words / WORDS_PER_PAGE))


def clean_display_name(raw: str | None, file_type: FileType) -> str:
    """Display name only (never used in paths): no directories, no control characters."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r"\s+", " ", name).strip()
    if not name or name in {".", ".."}:
        name = f"document.{file_type}"
    if len(name) > 255:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 254 - len(ext)] + dot + ext) if dot and len(ext) <= 10 else name[:255]
    return name
