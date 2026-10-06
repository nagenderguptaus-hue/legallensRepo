import asyncio

from sqlalchemy import select

from legallens.adapters.standin.basic_ingestion import SCANNED_MESSAGE
from legallens.db.models import IngestionJobRow, TransactionRow
from tests.conftest import RunApp, Running
from tests.factories import make_blank_pdf, make_docx, make_pdf
from tests.fakes import FlakyPipeline, GatedPipeline, SlowPipeline


async def test_upload_pdf_runs_ingestion_to_ready(r: Running) -> None:
    res = await r.upload(make_pdf())
    assert res.status_code == 201
    created = res.json()
    assert created["status"] == "processing"
    assert created["stage"] == "validating"
    assert created["type"] == "pdf"
    assert created["pages"] == 3
    assert created["name"] == "Mutual_NDA.pdf"

    await r.container.runner.wait_idle()
    doc = (await r.client.get(f"/api/documents/{created['id']}")).json()
    assert doc["status"] == "ready"
    assert (doc["stage"], doc["progress"], doc["error"], doc["warnings"]) == (None, None, None, [])

    page = (await r.client.get(f"/api/documents/{doc['id']}/pages/2")).json()
    assert page["documentId"] == doc["id"]
    assert (page["page"], page["totalPages"], page["ocr"]) == (2, 3, False)
    assert any("three (3) years" in p for p in page["paragraphs"])

    library = (await r.client.get("/api/documents")).json()
    assert [d["id"] for d in library] == [doc["id"]]


async def test_upload_docx_is_split_into_pages(r: Running) -> None:
    doc = await r.ready_document(make_docx(), "Mutual_NDA.docx")
    assert doc["type"] == "docx"
    assert doc["pages"] == 3


async def test_library_is_newest_first(r: Running) -> None:
    first = await r.ready_document(make_pdf(), "a.pdf")
    second = await r.ready_document(make_docx(), "b.docx")
    ids = [d["id"] for d in (await r.client.get("/api/documents")).json()]
    assert ids == [second["id"], first["id"]]


async def test_live_progress_is_visible_while_processing(run_app: RunApp) -> None:
    pipeline = GatedPipeline()
    async with run_app(pipeline=pipeline) as r:
        doc = (await r.upload(make_pdf())).json()
        await pipeline.started.wait()
        polled = (await r.client.get(f"/api/documents/{doc['id']}")).json()
        assert polled["status"] == "processing"
        assert polled["stage"] == "extracting"
        assert polled["progress"] == {"current": 1, "total": 3}

        page = await r.client.get(f"/api/documents/{doc['id']}/pages/1")
        assert (page.status_code, page.json()["code"]) == (409, "document_not_ready")

        pipeline.gate.set()
        await r.container.runner.wait_idle()
        assert (await r.client.get(f"/api/documents/{doc['id']}")).json()["status"] == "ready"


async def test_scanned_pdf_fails_with_clear_message_and_can_be_retried(r: Running) -> None:
    doc = (await r.upload(make_blank_pdf(), "scan.pdf")).json()
    await r.container.runner.wait_idle()
    failed = (await r.client.get(f"/api/documents/{doc['id']}")).json()
    assert failed["status"] == "failed"
    assert failed["error"] == SCANNED_MESSAGE

    retried = await r.client.post(f"/api/documents/{doc['id']}/retry")
    assert retried.status_code == 200
    assert (retried.json()["status"], retried.json()["error"]) == ("processing", None)
    await r.container.runner.wait_idle()
    assert (await r.client.get(f"/api/documents/{doc['id']}")).json()["status"] == "failed"


async def test_only_failed_documents_can_be_retried(r: Running) -> None:
    doc = await r.ready_document()
    res = await r.client.post(f"/api/documents/{doc['id']}/retry")
    assert (res.status_code, res.json()["code"]) == (409, "document_not_failed")


async def test_transient_pipeline_errors_are_retried(run_app: RunApp) -> None:
    pipeline = FlakyPipeline(failures=1)
    async with run_app(pipeline=pipeline) as r:
        doc = await r.ready_document()
        assert pipeline.calls == 2
        async with r.container.db.session() as s:
            job = await s.scalar(
                select(IngestionJobRow).where(IngestionJobRow.document_id == doc["id"])
            )
        assert job is not None
        assert (job.state, job.attempts) == ("succeeded", 2)


async def test_pipeline_that_keeps_failing_ends_failed(run_app: RunApp) -> None:
    async with run_app(pipeline=FlakyPipeline(failures=99), ingestion_max_retries=1) as r:
        doc = (await r.upload(make_pdf())).json()
        await r.container.runner.wait_idle()
        failed = (await r.client.get(f"/api/documents/{doc['id']}")).json()
        assert failed["status"] == "failed"
        assert "after 2 attempts" in failed["error"]


async def test_ingestion_timeout_marks_document_failed(run_app: RunApp) -> None:
    async with run_app(pipeline=SlowPipeline(), ingestion_timeout_s=0.05) as r:
        doc = (await r.upload(make_pdf())).json()
        await r.container.runner.wait_idle()
        failed = (await r.client.get(f"/api/documents/{doc['id']}")).json()
        assert failed["status"] == "failed"
        assert "took too long" in failed["error"]


async def test_upload_rejections(run_app: RunApp) -> None:
    async with run_app(max_upload_mb=1, max_documents=1) as r:
        cases = [
            (await r.upload(b"plain text", "notes.pdf"), 415, "unsupported_type"),
            (await r.upload(b"", "empty.pdf"), 422, "empty_file"),
            (await r.upload(b"%PDF-" + b"0" * (2 * 1024 * 1024)), 413, "file_too_large"),
            (await r.client.post("/api/documents", data={"other": "x"}), 400, "missing_file"),
            (await r.client.post("/api/documents", json={"file": "x"}), 400, "missing_file"),
        ]
        for res, status, code in cases:
            assert (res.status_code, res.json()["code"]) == (status, code), res.text
            assert res.json()["request_id"] == res.headers["x-request-id"]

        await r.ready_document()
        dup = await r.upload(make_pdf(), "copy.pdf")
        assert (dup.status_code, dup.json()["code"]) == (409, "duplicate_document")
        full = await r.upload(make_docx(), "another.docx")
        assert (full.status_code, full.json()["code"]) == (409, "library_full")
        # rejected uploads leave no files behind
        assert list(r.settings.tmp_dir.iterdir()) == []
        assert len(list(r.settings.uploads_dir.iterdir())) == 1


async def test_page_errors(r: Running) -> None:
    doc = await r.ready_document()
    for page in ("0", "4", "abc"):
        res = await r.client.get(f"/api/documents/{doc['id']}/pages/{page}")
        assert (res.status_code, res.json()["code"]) == (404, "page_not_found")
    res = await r.client.get("/api/documents/doc_missing/pages/1")
    assert (res.status_code, res.json()["code"]) == (404, "document_not_found")


async def test_delete_removes_everything_but_keeps_conversations(r: Running) -> None:
    doc = await r.ready_document()
    conversation = await r.new_conversation()
    chat = await r.chat(
        conversation["id"], "How long does the agreement remain in effect?", [doc["id"]]
    )
    assert chat.status_code == 200

    res = await r.client.delete(f"/api/documents/{doc['id']}")
    assert res.status_code == 204
    assert (await r.client.get(f"/api/documents/{doc['id']}")).status_code == 404
    assert not (r.settings.uploads_dir / doc["id"]).exists()

    detail = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
    assert detail["documentDeleted"] is True
    assert detail["documentId"] == doc["id"]
    citations = detail["messages"][1]["citations"]
    assert citations and citations[0]["documentName"] == "Mutual_NDA.pdf"

    again = await r.client.delete(f"/api/documents/{doc['id']}")
    assert (again.status_code, again.json()["code"]) == (404, "document_not_found")


async def test_delete_while_processing_cancels_the_job(run_app: RunApp) -> None:
    pipeline = GatedPipeline()
    async with run_app(pipeline=pipeline) as r:
        doc = (await r.upload(make_pdf())).json()
        await pipeline.started.wait()
        res = await r.client.delete(f"/api/documents/{doc['id']}")
        assert res.status_code == 204
        assert pipeline.cancelled
        assert pipeline.purged == [doc["id"]]
        # the worker keeps serving later uploads
        pipeline.gate.set()
        await r.ready_document(make_docx(), "next.docx")


async def test_restart_requeues_documents_left_processing(run_app: RunApp) -> None:
    pipeline = GatedPipeline()
    async with run_app(pipeline=pipeline) as r:
        doc = (await r.upload(make_pdf())).json()
        await pipeline.started.wait()
    # "crash": the app stopped mid-ingestion; the next start must finish the job
    async with run_app() as r2:
        await r2.container.runner.wait_idle()
        assert (await r2.client.get(f"/api/documents/{doc['id']}")).json()["status"] == "ready"


async def test_actions_are_written_to_the_transactions_table(r: Running) -> None:
    doc = await r.ready_document()
    await r.upload(b"nope", "x.pdf")
    await r.client.delete(f"/api/documents/{doc['id']}")
    await asyncio.sleep(0)
    async with r.container.db.session() as s:
        rows = (await s.scalars(select(TransactionRow).order_by(TransactionRow.id))).all()
    summary = [(t.action, t.status, t.error_code) for t in rows]
    assert summary == [
        ("document.upload", "ok", None),
        ("document.upload", "error", "unsupported_type"),
        ("document.delete", "ok", None),
    ]
    assert all(t.request_id.startswith("req_") and t.latency_ms >= 0 for t in rows)
