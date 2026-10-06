"""Wires settings, storage, adapters and services together, and owns their lifecycle."""

import asyncio
from dataclasses import dataclass

import structlog

from legallens.adapters import load_ingestion_pipeline, load_orchestrator
from legallens.config import Settings
from legallens.db.engine import Database, run_migrations
from legallens.ingestion.job_runner import IngestionRunner
from legallens.ports.ingestion import IngestionPipeline
from legallens.ports.orchestrator import ChatOrchestrator
from legallens.services.chat_service import ChatService
from legallens.services.conversation_service import ConversationService
from legallens.services.document_service import DocumentService
from legallens.services.transaction_logger import TransactionLogger
from legallens.storage.file_store import FileStore

log = structlog.get_logger("legallens")


@dataclass
class Container:
    settings: Settings
    db: Database
    files: FileStore
    orchestrator: ChatOrchestrator
    pipeline: IngestionPipeline
    runner: IngestionRunner
    documents: DocumentService
    conversations: ConversationService
    chat: ChatService

    async def shutdown(self) -> None:
        await self.runner.stop()
        await self.db.dispose()
        log.info("shutdown_complete")


async def build_container(
    settings: Settings,
    *,
    orchestrator: ChatOrchestrator | None = None,
    pipeline: IngestionPipeline | None = None,
) -> Container:
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    files = FileStore(settings.uploads_dir, settings.tmp_dir)
    files.ensure_dirs()
    files.clear_tmp()
    await asyncio.to_thread(run_migrations, settings.db_path)

    db = Database(settings.db_path)
    orchestrator = orchestrator or load_orchestrator(settings)
    pipeline = pipeline or load_ingestion_pipeline(settings)
    tx = TransactionLogger(db)
    runner = IngestionRunner(db, pipeline, files, settings)
    container = Container(
        settings=settings,
        db=db,
        files=files,
        orchestrator=orchestrator,
        pipeline=pipeline,
        runner=runner,
        documents=DocumentService(db, files, runner, pipeline, tx, settings),
        conversations=ConversationService(db, tx),
        chat=ChatService(db, orchestrator, tx, settings),
    )

    interrupted = await container.chat.recover_interrupted()
    runner.start()
    requeued = await runner.recover()
    log.info(
        "startup_complete",
        orchestrator=settings.orchestrator,
        ingestion=settings.ingestion,
        interrupted_replies=interrupted,
        requeued_documents=requeued,
    )
    return container
