from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
import hashlib
import tempfile

from ingestion.document_loader import (
    SUPPORTED_EXTENSIONS,
    SourceDocumentLoadError,
    load_source_document,
)

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".txt",
    ".pdf",
    ".docx",
    ".csv",
}

TEXT_EXTENSIONS = {
    ".txt",
    ".csv",
}


class UnsupportedFileTypeError(ValueError):
    pass


class EmptyUploadFileError(ValueError):
    pass


class UploadFileTooLargeError(ValueError):
    pass


class DuplicateUploadFileError(ValueError):
    pass


class UnsafeFileNameError(ValueError):
    pass

class DuplicateUploadContentError(ValueError):
    pass

class DuplicateDocumentContentError(ValueError):
    pass


def normalize_document_content(
    content: str,
) -> str:
    return " ".join(
        content.split()
    ).casefold()


def calculate_sha256(
    content: bytes,
) -> str:
    return hashlib.sha256(content).hexdigest()

def find_duplicate_content_file(
    source_directory: Path,
    content: bytes,
) -> Path | None:
    if not source_directory.exists():
        return None

    uploaded_hash = calculate_sha256(
        content=content,
    )

    for existing_file in source_directory.iterdir():
        if not existing_file.is_file():
            continue

        if (
            existing_file.suffix.lower()
            not in ALLOWED_EXTENSIONS
        ):
            continue

        try:
            existing_content = (
                existing_file.read_bytes()
            )
        except OSError:
            continue

        existing_hash = calculate_sha256(
            content=existing_content,
        )

        if existing_hash == uploaded_hash:
            return existing_file

    return None

def validate_file_name(
    file_name: str,
) -> str:
    safe_file_name = Path(file_name).name

    if (
        safe_file_name != file_name
        or "/" in file_name
        or "\\" in file_name
    ):
        raise UnsafeFileNameError(
            "안전하지 않은 파일 이름입니다."
        )

    return safe_file_name


def validate_document_content(
    extension: str,
    content: bytes,
) -> None:
    if not content:
        raise EmptyUploadFileError(
            "빈 파일은 업로드할 수 없습니다."
        )

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise UploadFileTooLargeError(
            "파일 크기는 5MB를 초과할 수 없습니다."
        )

    if extension in TEXT_EXTENSIONS:
        try:
            text = content.decode(
                "utf-8-sig"
            )

        except UnicodeDecodeError as error:
            raise UnsupportedFileTypeError(
                "TXT와 CSV는 UTF-8 인코딩이어야 합니다."
            ) from error

        if not text.strip():
            raise EmptyUploadFileError(
                "내용이 없는 파일은 업로드할 수 없습니다."
            )

    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise UnsupportedFileTypeError(
                "올바른 PDF 파일이 아닙니다."
            )

    if extension == ".docx":
        try:
            with ZipFile(
                BytesIO(content)
            ) as archive:
                if (
                    "word/document.xml"
                    not in archive.namelist()
                ):
                    raise UnsupportedFileTypeError(
                        "올바른 DOCX 파일이 아닙니다."
                    )

        except BadZipFile as error:
            raise UnsupportedFileTypeError(
                "올바른 DOCX 파일이 아닙니다."
            ) from error


def save_uploaded_document(
    source_directory: Path,
    file_name: str,
    content: bytes,
) -> Path:
    safe_file_name = validate_file_name(
        file_name=file_name,
    )

    extension = Path(
        safe_file_name
    ).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            "TXT, PDF, DOCX, CSV 파일만 "
            "업로드할 수 있습니다."
        )

    validate_document_content(
        extension=extension,
        content=content,
    )

    source_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        source_directory / safe_file_name
    )

    if destination.exists():
        raise DuplicateUploadFileError(
            "같은 이름의 파일이 이미 존재합니다."
    )

    duplicate_file = find_duplicate_content_file(
    source_directory=source_directory,
    content=content,
)

    if duplicate_file is not None:
        raise DuplicateUploadContentError(
            "내용이 동일한 파일이 이미 존재합니다: "
        f"{duplicate_file.name}"
    )

    duplicate_document = (
        find_duplicate_document_content(
            source_directory=source_directory,
            file_name=safe_file_name,
            content=content,
    )
)

    if duplicate_document is not None:
        raise DuplicateDocumentContentError(
        "본문이 동일한 문서가 이미 존재합니다: "
        f"{duplicate_document.name}"
    )

# 여기에서 실제 파일 저장

    if extension in TEXT_EXTENSIONS:
        text = content.decode(
            "utf-8-sig"
        ).strip()

        destination.write_text(
            text,
            encoding="utf-8",
        )

    else:
        destination.write_bytes(content)

    return destination


# 기존 테스트 및 호출과의 호환성을 위한 함수
def save_uploaded_text_file(
    source_directory: Path,
    file_name: str,
    content: bytes,
) -> Path:
    return save_uploaded_document(
        source_directory=source_directory,
        file_name=file_name,
        content=content,
    )
    
def calculate_document_content_hash(
    content: str,
) -> str:
    normalized_content = (
        normalize_document_content(
            content=content,
        )
    )

    return hashlib.sha256(
        normalized_content.encode("utf-8")
    ).hexdigest()
    
    
def extract_uploaded_document_text(
    file_name: str,
    content: bytes,
) -> str:
    extension = Path(
        file_name
    ).suffix.lower()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True,) as temp_dir:
        temporary_path = (
            Path(temp_dir) / file_name
        )

        temporary_path.write_bytes(
            content
        )

        try:
            document = load_source_document(
                file_path=temporary_path,
                document_id=temporary_path.stem,
                title=temporary_path.stem,
            )
        except SourceDocumentLoadError as error:
            raise UnsupportedFileTypeError(
                "업로드 문서의 내용을 읽을 수 없습니다."
            ) from error

    return document.page_content

def find_duplicate_document_content(
    source_directory: Path,
    file_name: str,
    content: bytes,
) -> Path | None:
    if not source_directory.exists():
        return None

    uploaded_text = extract_uploaded_document_text(
        file_name=file_name,
        content=content,
    )

    uploaded_hash = (
        calculate_document_content_hash(
            content=uploaded_text,
        )
    )

    for existing_file in (
        source_directory.iterdir()
    ):
        if not existing_file.is_file():
            continue

        if (
            existing_file.suffix.lower()
            not in ALLOWED_EXTENSIONS
        ):
            continue

        try:
            existing_document = (
                load_source_document(
                    file_path=existing_file,
                    document_id=(
                        existing_file.stem
                    ),
                    title=existing_file.stem,
                )
            )
        except (
            SourceDocumentLoadError,
            OSError,
        ):
            continue

        existing_hash = (
            calculate_document_content_hash(
                content=(
                    existing_document.page_content
                ),
            )
        )

        if uploaded_hash == existing_hash:
            return existing_file
        
        


    return None
