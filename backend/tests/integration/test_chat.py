import asyncio
import json
from typing import Any

from fastapi import FastAPI
from sqlalchemy import update
from starlette.types import Message

from legallens.api.schemas import ChatRequest
from legallens.db.models import MessageRow
from legallens.ports.orchestrator import (
    CitationEvent,
    DoneEvent,
    IntentEvent,
    StatusEvent,
    TokenEvent,
)
from tests.conftest import RunApp, Running, parse_sse
from tests.factories import make_pdf
from tests.fakes import GatedPipeline, ScriptedOrchestrator, endless_tokens, simple_answer


def names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


def text_of(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(data["text"] for name, data in events if name == "token")


async def test_ask_streams_answer_with_citations_and_saves_the_turn(r: Running) -> None:
    doc = await r.ready_document()
    conversation = await r.new_conversation()

    res = await r.chat(
        conversation["id"], "How long does the agreement remain in effect?", [doc["id"]]
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache"
    events = parse_sse(res.text)

    assert events[0][0] == "intent"
    intent = events[0][1]
    assert intent["intent"] == "ask"
    assert set(intent) == {"intent", "message_id", "user_message_id"}
    assert "status" in names(events) and "token" in names(events)
    assert names(events)[-1] == "done"

    citations = [data for name, data in events if name == "citation"]
    assert citations and citations[0] == {
        "index": 1,
        "documentId": doc["id"],
        "documentName": "Mutual_NDA.pdf",
        "page": 2,
        "section": "2. Term",
        "quote": citations[0]["quote"],
    }
    assert "three (3) years" in citations[0]["quote"]

    done = events[-1][1]
    assert done == {
        "message_id": intent["message_id"],
        "user_message_id": intent["user_message_id"],
        "outcome": "answered",
        "suggestions": [],
        "title": "How long does the agreement remain in effect",
    }

    detail = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
    assert detail["title"] == done["title"]
    assert detail["documentId"] == doc["id"]
    user, assistant = detail["messages"]
    assert (user["id"], user["role"], user["status"]) == (
        done["user_message_id"],
        "user",
        "complete",
    )
    assert user["content"] == "How long does the agreement remain in effect?"
    assert assistant["id"] == done["message_id"]
    assert (assistant["status"], assistant["intent"], assistant["outcome"]) == (
        "complete",
        "ask",
        "answered",
    )
    assert assistant["content"] == text_of(events)
    assert assistant["citations"] == citations
    assert "error" not in assistant
    assert user["createdAt"] < assistant["createdAt"]


async def test_unanswerable_question_is_not_found(r: Running) -> None:
    doc = await r.ready_document()
    conversation = await r.new_conversation()
    events = parse_sse(
        (await r.chat(conversation["id"], "What is the capital of France?", [doc["id"]])).text
    )
    assert events[-1][1]["outcome"] == "not_found"
    assert "couldn't find this" in text_of(events)
    assert "citation" not in names(events)


async def test_summary_uses_the_fixed_template_with_citations(r: Running) -> None:
    doc = await r.ready_document()
    conversation = await r.new_conversation()
    events = parse_sse(
        (await r.chat(conversation["id"], "Summarize this document", [doc["id"]])).text
    )
    assert events[0][1]["intent"] == "summary"
    content = text_of(events)
    for heading in (
        "Document type & purpose",
        "Parties",
        "Key dates & deadlines",
        "Key terms & obligations",
        "Notable risks",
        "Plain-language overview",
    ):
        assert f"### {heading}" in content
    assert len([n for n in names(events) if n == "citation"]) >= 4


async def test_draft_memo_has_placeholders_and_quoted_facts(r: Running) -> None:
    doc = await r.ready_document()
    conversation = await r.new_conversation()
    events = parse_sse(
        (
            await r.chat(conversation["id"], "Draft a memo on the termination notice", [doc["id"]])
        ).text
    )
    content = text_of(events)
    assert events[0][1]["intent"] == "draft"
    assert content.startswith("**MEMORANDUM**")
    assert "[CONFIRM: recipient]" in content and "[CITATION NEEDED]" in content
    assert "**Re:** Memo on the termination notice" in content
    assert "citation" in names(events)


async def test_case_brief_without_a_document_is_all_placeholders(r: Running) -> None:
    conversation = await r.new_conversation()
    events = parse_sse((await r.chat(conversation["id"], "Draft a case brief")).text)
    content = text_of(events)
    assert content.startswith("**CASE BRIEF**")
    assert "[CONFIRM: key facts]" in content
    assert "citation" not in names(events)


async def test_clarify_and_needs_document(r: Running) -> None:
    conversation = await r.new_conversation()
    clarify = parse_sse((await r.chat(conversation["id"], "hello")).text)
    assert clarify[0][1]["intent"] == "clarify"
    assert clarify[-1][1]["outcome"] == "clarify"
    assert len(clarify[-1][1]["suggestions"]) == 3

    ask = parse_sse((await r.chat(conversation["id"], "What is the notice period?")).text)
    assert ask[-1][1]["outcome"] == "needs_document"

    detail = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
    assert len(detail["messages"]) == 4
    assert detail["messages"][1]["suggestions"] == clarify[-1][1]["suggestions"]


async def test_follow_up_questions_get_the_conversation_history(run_app: RunApp) -> None:
    orchestrator = ScriptedOrchestrator(simple_answer())
    async with run_app(orchestrator=orchestrator) as r:
        conversation = await r.new_conversation()
        await r.chat(conversation["id"], "first question")
        await r.chat(conversation["id"], "and then?")
        history = orchestrator.contexts[1].history
        assert [(t.role, t.content) for t in history] == [
            ("user", "first question"),
            ("assistant", "Hello there."),
        ]


async def test_rejections_before_streaming(run_app: RunApp) -> None:
    pipeline = GatedPipeline()
    async with run_app(pipeline=pipeline, max_message_chars=50) as r:
        conversation = await r.new_conversation()
        processing = (await r.upload(make_pdf())).json()
        await pipeline.started.wait()
        cases = [
            (await r.chat(conversation["id"], "   "), 422, "empty_message"),
            (await r.chat(conversation["id"], "x" * 51), 422, "message_too_long"),
            (await r.chat(conversation["id"], "hi there", ["a", "b"]), 422, "too_many_documents"),
            (await r.chat("conv_nope", "hi there"), 404, "conversation_not_found"),
            (await r.chat(conversation["id"], "hi there", ["doc_nope"]), 404, "document_not_found"),
            (
                await r.chat(conversation["id"], "hi there", [processing["id"]]),
                409,
                "document_not_ready",
            ),
        ]
        for res, status, code in cases:
            assert (res.status_code, res.json()["code"]) == (status, code), res.text
        detail = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
        assert detail["messages"] == []
        pipeline.gate.set()


async def test_model_offline_returns_503_and_saves_nothing(run_app: RunApp) -> None:
    async with run_app(standin_model_offline=True) as r:
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "What is the term?")
        assert (res.status_code, res.json()["code"]) == (503, "model_unavailable")
        assert "not responding" in res.json()["message"]
        detail = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
        assert detail["messages"] == []
        assert detail["title"] == "New conversation"


async def test_failure_midway_keeps_partial_text_and_error(run_app: RunApp) -> None:
    async with run_app(standin_fail_midstream=True) as r:
        conversation = await r.new_conversation()
        events = parse_sse((await r.chat(conversation["id"], "Draft a memo on leases")).text)
        assert names(events)[-1] == "error"
        assert "done" not in names(events)
        error = events[-1][1]
        assert error["code"] == "stream_interrupted"
        assert error["request_id"].startswith("req_")

        assistant = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()[
            "messages"
        ][1]
        assert assistant["status"] == "error"
        assert assistant["content"] == text_of(events) != ""
        assert assistant["error"] == error


async def test_orchestrator_that_never_finishes_is_an_error(run_app: RunApp) -> None:
    orchestrator = ScriptedOrchestrator([IntentEvent("ask"), TokenEvent("partial")])
    async with run_app(orchestrator=orchestrator) as r:
        conversation = await r.new_conversation()
        events = parse_sse((await r.chat(conversation["id"], "question here")).text)
        assert events[-1] == (
            "error",
            {
                "code": "incomplete_response",
                "message": "The model stopped before finishing its answer.",
                "request_id": events[-1][1]["request_id"],
            },
        )


async def test_first_event_timeout(run_app: RunApp) -> None:
    async def slow(_ctx: Any) -> Any:
        await asyncio.sleep(5)
        yield IntentEvent("ask")

    async with run_app(
        orchestrator=ScriptedOrchestrator(slow), stream_first_event_timeout_s=0.05
    ) as r:
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "question here")
        assert (res.status_code, res.json()["code"]) == (504, "model_timeout")


async def test_protocol_violation_is_a_500_envelope(run_app: RunApp) -> None:
    orchestrator = ScriptedOrchestrator([TokenEvent("no intent first"), DoneEvent("answered")])
    async with run_app(orchestrator=orchestrator) as r:
        conversation = await r.new_conversation()
        res = await r.chat(conversation["id"], "question here")
        assert res.status_code == 500
        assert res.json() == {
            "code": "internal_error",
            "message": "Something went wrong on our side. Try again.",
            "request_id": res.headers["x-request-id"],
        }
        # the conversation is not left locked
        assert (await r.chat(conversation["id"], "question here")).status_code == 500


async def test_citation_guard_drops_invalid_citations(run_app: RunApp) -> None:
    holder: dict[str, str] = {}

    async def citing(ctx: Any) -> Any:
        doc_id = holder["doc"]
        yield IntentEvent("ask")
        yield StatusEvent("Searching")
        yield TokenEvent("Answer [1] [2] [3] [4].")
        yield CitationEvent(index=1, document_id=doc_id, page=2, quote="  three   years  ")
        yield CitationEvent(index=1, document_id=doc_id, page=2, quote="duplicate index")
        yield CitationEvent(index=2, document_id="doc_other", page=1, quote="wrong document")
        yield CitationEvent(index=3, document_id=doc_id, page=99, quote="no such page")
        yield CitationEvent(index=4, document_id=doc_id, page=1, quote="   ")
        yield DoneEvent("answered")

    async with run_app(orchestrator=ScriptedOrchestrator(citing)) as r:
        doc = await r.ready_document()
        holder["doc"] = doc["id"]
        conversation = await r.new_conversation()
        events = parse_sse((await r.chat(conversation["id"], "question", [doc["id"]])).text)
        citations = [data for name, data in events if name == "citation"]
        assert [(c["index"], c["quote"]) for c in citations] == [(1, "three years")]


async def test_one_reply_at_a_time_per_conversation(run_app: RunApp) -> None:
    async with run_app(orchestrator=ScriptedOrchestrator(endless_tokens)) as r:
        conversation = await r.new_conversation()
        request = ChatRequest(conversation_id=conversation["id"], message="first")
        stream = await r.container.chat.start(request)

        busy = await r.chat(conversation["id"], "second")
        assert (busy.status_code, busy.json()["code"]) == (409, "conversation_busy")

        await stream.aclose()  # e.g. the client went away before streaming started
        again = await r.container.chat.start(request)
        await again.aclose()
        messages = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()[
            "messages"
        ]
        assert [m["status"] for m in messages] == ["complete", "stopped", "complete", "stopped"]


async def stream_until_disconnect(app: FastAPI, body: dict[str, Any], after_bytes: bytes) -> bytes:
    """Drives the ASGI app like a real server: the client disconnects (presses Stop) as soon
    as ``after_bytes`` has been received."""
    payload = json.dumps(body).encode()
    disconnect = asyncio.Event()
    request_sent = False
    received = bytearray()

    async def receive() -> Message:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body":
            received.extend(message.get("body", b""))
            if after_bytes in received:
                disconnect.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat/stream",
        "raw_path": b"/api/chat/stream",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    return bytes(received)


async def test_client_disconnect_stops_and_saves_partial_reply(run_app: RunApp) -> None:
    async with run_app(orchestrator=ScriptedOrchestrator(endless_tokens)) as r:
        conversation = await r.new_conversation()
        body = {"conversation_id": conversation["id"], "message": "go", "document_ids": []}
        raw = await stream_until_disconnect(r.app, body, b"word3 ")
        assert b"event: intent" in raw

        messages = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()[
            "messages"
        ]
        assistant = messages[1]
        assert assistant["status"] == "stopped"
        assert assistant["content"].startswith("word1 word2 word3 ")

        # the conversation is usable again right away
        raw2 = await stream_until_disconnect(r.app, body, b"word1 ")
        assert b"event: token" in raw2


async def test_restart_marks_interrupted_replies_as_errors(run_app: RunApp) -> None:
    async with run_app() as r:
        conversation = await r.new_conversation()
        await r.chat(conversation["id"], "hello")
        async with r.container.db.session() as s:  # simulate a crash mid-reply
            await s.execute(
                update(MessageRow).where(MessageRow.role == "assistant").values(status="streaming")
            )
    async with run_app() as r2:
        messages = (await r2.client.get(f"/api/conversations/{conversation['id']}")).json()[
            "messages"
        ]
        assert messages[1]["status"] == "error"
        assert messages[1]["error"]["code"] == "stream_interrupted"
