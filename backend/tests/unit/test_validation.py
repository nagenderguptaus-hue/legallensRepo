import io
import zipfile
from pathlib import Path

import pytest

from legallens.errors import AppError
from legallens.ingestion.validation import CFB_MAGIC, clean_display_name, inspect_file
from tests.factories import make_docx, make_encrypted_pdf, make_pdf


def write(tmp_path: Path, data: bytes, name: str = "f.bin") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def error_code(path: Path, name: str = "file.pdf", max_pages: int = 300) -> tuple[int, str]:
    with pytest.raises(AppError) as info:
        inspect_file(path, name, max_pages)
    return info.value.status, info.value.code


def test_pdf_is_detected_by_content_with_page_count(tmp_path: Path) -> None:
    info = inspect_file(write(tmp_path, make_pdf()), "renamed.docx", 300)
    assert (info.type, info.pages) == ("pdf", 3)


def test_test_pdfs_are_deterministic() -> None:
    assert make_pdf() == make_pdf()  # duplicate-detection tests rely on identical bytes


def test_docx_is_detected_by_content(tmp_path: Path) -> None:
    info = inspect_file(write(tmp_path, make_docx()), "contract.docx", 300)
    assert info.type == "docx"
    assert info.pages is not None and info.pages >= 1


def test_text_file_renamed_to_pdf_is_rejected(tmp_path: Path) -> None:
    assert error_code(write(tmp_path, b"just some text")) == (415, "unsupported_type")


def test_encrypted_pdf_is_rejected(tmp_path: Path) -> None:
    assert error_code(write(tmp_path, make_encrypted_pdf())) == (422, "encrypted_file")


def test_corrupt_pdf_is_rejected(tmp_path: Path) -> None:
    assert error_code(write(tmp_path, b"%PDF-1.7\n garbage without structure")) == (
        422,
        "unreadable_file",
    )


def test_page_limit_is_enforced(tmp_path: Path) -> None:
    status, code = error_code(write(tmp_path, make_pdf()), max_pages=2)
    assert (status, code) == (422, "too_many_pages")


def test_password_protected_word_file(tmp_path: Path) -> None:
    path = write(tmp_path, CFB_MAGIC + b"\x00" * 512)
    assert error_code(path, "secret.docx") == (422, "encrypted_file")
    assert error_code(path, "old.doc") == (415, "unsupported_type")


def test_zip_that_is_not_a_word_document(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("hello.txt", "hi")
    assert error_code(write(tmp_path, buf.getvalue()), "x.docx") == (415, "unsupported_type")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Lease.pdf", "Lease.pdf"),
        ("C:\\Users\\maya\\Client A\\Lease.pdf", "Lease.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("bad\x00name\x07.pdf", "badname.pdf"),
        ("   spaced    out .pdf  ", "spaced out .pdf"),
        ("", "document.pdf"),
        (None, "document.pdf"),
        ("..", "document.pdf"),
    ],
)
def test_display_name_is_cleaned(raw: str | None, expected: str) -> None:
    assert clean_display_name(raw, "pdf") == expected


def test_long_display_name_keeps_extension() -> None:
    name = clean_display_name("a" * 400 + ".docx", "docx")
    assert len(name) == 255
    assert name.endswith(".docx")
