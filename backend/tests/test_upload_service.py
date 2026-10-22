from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
import pytest

from services.upload_service import (
    DuplicateUploadContentError,
    save_uploaded_document,
    DuplicateDocumentContentError,
)

from services.upload_service import (
    DuplicateUploadFileError,
    EmptyUploadFileError,
    UnsupportedFileTypeError,
    UploadFileTooLargeError,
    save_uploaded_text_file,
)

from services import (
    upload_service as upload_service_module,
)


def test_save_uploaded_text_file(
    tmp_path: Path,
) -> None:
    saved_path = save_uploaded_text_file(
        source_directory=tmp_path,
        file_name="remote-policy.txt",
        content=(
            "원격 접속에는 VPN과 "
            "다중 인증이 필요합니다."
        ).encode("utf-8"),
    )

    assert saved_path == (
        tmp_path / "remote-policy.txt"
    )

    assert saved_path.read_text(
        encoding="utf-8",
    ) == (
        "원격 접속에는 VPN과 "
        "다중 인증이 필요합니다."
    )


def test_save_uploaded_text_file_rejects_empty_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        EmptyUploadFileError,
    ):
        save_uploaded_text_file(
            source_directory=tmp_path,
            file_name="empty.txt",
            content=b"   ",
        )


def test_save_uploaded_text_file_rejects_wrong_type(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        UnsupportedFileTypeError,
    ):
        save_uploaded_text_file(
            source_directory=tmp_path,
            file_name="policy.exe",
            content=b"content",
        )


def test_save_uploaded_text_file_rejects_large_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        UploadFileTooLargeError,
    ):
        save_uploaded_text_file(
            source_directory=tmp_path,
            file_name="large.txt",
            content=(
                b"a" * (
                    5 * 1024 * 1024 + 1
                )
            ),
        )


def test_save_uploaded_text_file_rejects_duplicate(
    tmp_path: Path,
) -> None:
    save_uploaded_text_file(
        source_directory=tmp_path,
        file_name="policy.txt",
        content=b"first",
    )

    with pytest.raises(
        DuplicateUploadFileError,
    ):
        save_uploaded_text_file(
            source_directory=tmp_path,
            file_name="policy.txt",
            content=b"second",
        )
        
def test_save_uploaded_csv_file(
    tmp_path: Path,
) -> None:
    saved_path = save_uploaded_document(
        source_directory=tmp_path,
        file_name="policy.csv",
        content=(
            "policy,value\n"
            "password-change,90 days\n"
        ).encode("utf-8"),
    )

    assert saved_path.exists()
    assert saved_path.suffix == ".csv"
    
def test_save_uploaded_pdf_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    
    monkeypatch.setattr(
        upload_service_module,
        "find_duplicate_document_content",
        lambda **kwargs: None,
    )
    content = b"%PDF-1.4 test content"

    saved_path = save_uploaded_document(
        source_directory=tmp_path,
        file_name="policy.pdf",
        content=content,
    )

    assert saved_path.exists()
    assert saved_path.read_bytes() == content
    
def test_save_uploaded_docx_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    
    monkeypatch.setattr(
        upload_service_module,
        "find_duplicate_document_content",
        lambda **kwargs: None,
    )
    buffer = BytesIO()

    with ZipFile(
        buffer,
        mode="w",
    ) as archive:
        archive.writestr(
            "word/document.xml",
            "<document>test</document>",
        )

    content = buffer.getvalue()

    saved_path = save_uploaded_document(
        source_directory=tmp_path,
        file_name="policy.docx",
        content=content,
    )

    assert saved_path.exists()
    assert saved_path.read_bytes() == content

def test_save_uploaded_document_rejects_duplicate_content(
    tmp_path: Path,
) -> None:
    content = (
        "로그인에 5회 연속 실패하면 "
        "계정을 30분 동안 잠급니다."
    ).encode("utf-8")

    save_uploaded_document(
        source_directory=tmp_path,
        file_name="account-policy.txt",
        content=content,
    )

    with pytest.raises(
        DuplicateUploadContentError,
        match=(
            "내용이 동일한 파일이 "
            "이미 존재합니다"
        ),
    ):
        save_uploaded_document(
            source_directory=tmp_path,
            file_name="renamed-policy.txt",
            content=content,
        )

    assert not (
        tmp_path / "renamed-policy.txt"
    ).exists()
    
def test_save_uploaded_document_rejects_same_text(
    tmp_path: Path,
) -> None:
    save_uploaded_document(
        source_directory=tmp_path,
        file_name="original.txt",
        content=(
            "로그인에 5회 실패하면 "
            "계정이 잠깁니다."
        ).encode("utf-8"),
    )

    with pytest.raises(
        DuplicateDocumentContentError,
        match=(
            "본문이 동일한 문서가 "
            "이미 존재합니다"
        ),
    ):
        save_uploaded_document(
            source_directory=tmp_path,
            file_name="renamed.txt",
            content=(
                "로그인에   5회\n"
                "실패하면 계정이 잠깁니다."
            ).encode("utf-8"),
        )

    assert not (
        tmp_path / "renamed.txt"
    ).exists()
    
def test_save_uploaded_document_accepts_different_text(
    tmp_path: Path,
) -> None:
    save_uploaded_document(
        source_directory=tmp_path,
        file_name="first.txt",
        content=(
            "비밀번호는 90일마다 변경합니다."
        ).encode("utf-8"),
    )

    destination = save_uploaded_document(
        source_directory=tmp_path,
        file_name="second.txt",
        content=(
            "로그인에 5회 실패하면 "
            "계정을 잠급니다."
        ).encode("utf-8"),
    )

    assert destination.exists()