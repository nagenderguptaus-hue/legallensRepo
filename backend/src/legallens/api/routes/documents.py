from fastapi import APIRouter, Request, Response
from starlette.datastructures import UploadFile

from legallens.api.deps import ContainerDep
from legallens.api.schemas import ApiErrorBody, DocumentPage, LegalDocument
from legallens.errors import AppError, not_found

router = APIRouter(prefix="/documents", tags=["documents"])

ERRORS: dict[int | str, dict[str, object]] = {
    status: {"model": ApiErrorBody} for status in (400, 404, 409, 413, 415, 422)
}
MULTIPART_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}
MULTIPART_OVERHEAD_BYTES = 64 * 1024


@router.get("", response_model=list[LegalDocument], summary="Document library, newest first")
async def list_documents(c: ContainerDep) -> list[LegalDocument]:
    return [LegalDocument.from_row(d) for d in await c.documents.list()]


@router.post(
    "",
    status_code=201,
    response_model=LegalDocument,
    responses=ERRORS,
    openapi_extra=MULTIPART_BODY,
    summary="Upload a PDF or DOCX (multipart field `file`)",
)
async def upload_document(request: Request, c: ContainerDep) -> LegalDocument:
    limit = c.settings.max_upload_bytes
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit + MULTIPART_OVERHEAD_BYTES:
        # Reject honest oversized uploads before reading them. The size is enforced again
        # while streaming, because Content-Length can't be trusted.
        raise AppError(
            413, "file_too_large", f"Files must be {c.settings.max_upload_mb} MB or smaller."
        )
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise AppError(
            400, "missing_file", 'Send the file as multipart/form-data in a field named "file".'
        )

    async with request.form(max_files=1, max_fields=10) as form:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise AppError(400, "missing_file", "No file was uploaded.")
        doc = await c.documents.upload(file, file.filename)
    return LegalDocument.from_row(doc)


@router.get(
    "/{document_id}", response_model=LegalDocument, responses=ERRORS, summary="Document status"
)
async def get_document(document_id: str, c: ContainerDep) -> LegalDocument:
    return LegalDocument.from_row(await c.documents.get(document_id))


@router.post(
    "/{document_id}/retry",
    response_model=LegalDocument,
    responses=ERRORS,
    summary="Re-run ingestion for a failed document",
)
async def retry_document(document_id: str, c: ContainerDep) -> LegalDocument:
    return LegalDocument.from_row(await c.documents.retry(document_id))


@router.get(
    "/{document_id}/pages/{page}",
    response_model=DocumentPage,
    responses=ERRORS,
    summary="Extracted text of one page (Source Viewer)",
)
async def get_page(document_id: str, page: str, c: ContainerDep) -> DocumentPage:
    if not page.isdigit() or int(page) < 1:
        raise not_found("page_not_found", f"Page {page} does not exist in this document.")
    doc, row = await c.documents.page(document_id, int(page))
    return DocumentPage(
        document_id=doc.id,
        page=row.page,
        total_pages=doc.pages or row.page,
        paragraphs=row.paragraphs,
        ocr=row.ocr,
        ocr_confidence=row.ocr_confidence,
    )


@router.delete(
    "/{document_id}",
    status_code=204,
    response_class=Response,
    responses=ERRORS,
    summary="Delete the file, its text, index entries and vectors",
)
async def delete_document(document_id: str, c: ContainerDep) -> Response:
    await c.documents.delete(document_id)
    return Response(status_code=204)
