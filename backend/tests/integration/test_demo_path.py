"""BRD §7 demo, end to end: upload → Ask with citations → unanswerable question refused →
Summary → Draft with placeholders → restart → reopen the conversation → delete the document."""

from tests.conftest import RunApp, parse_sse
from tests.factories import make_pdf


async def test_brd_demo_path(run_app: RunApp) -> None:
    async with run_app() as r:
        doc = await r.ready_document(make_pdf(), "Mutual_NDA.pdf")
        conversation = await r.new_conversation()
        cid, docs = conversation["id"], [doc["id"]]

        ask = parse_sse(
            (await r.chat(cid, "How long does the agreement remain in effect?", docs)).text
        )
        assert ask[-1][1]["outcome"] == "answered"
        assert any(name == "citation" and data["page"] == 2 for name, data in ask)

        refused = parse_sse((await r.chat(cid, "Who won the 1998 World Cup?", docs)).text)
        assert refused[-1][1]["outcome"] == "not_found"

        summary = parse_sse((await r.chat(cid, "Summarize this document", docs)).text)
        assert summary[0][1]["intent"] == "summary"

        draft = parse_sse((await r.chat(cid, "Draft a memo on termination rights", docs)).text)
        draft_text = "".join(d["text"] for n, d in draft if n == "token")
        assert "[CONFIRM:" in draft_text and "[CITATION NEEDED]" in draft_text

    async with run_app() as r:  # restart: everything was persisted
        detail = (await r.client.get(f"/api/conversations/{cid}")).json()
        assert len(detail["messages"]) == 8
        assert [m["intent"] for m in detail["messages"][1::2]] == ["ask", "ask", "summary", "draft"]
        assert all(m["status"] == "complete" for m in detail["messages"])

        assert (await r.client.delete(f"/api/documents/{doc['id']}")).status_code == 204
        after = (await r.client.get(f"/api/conversations/{cid}")).json()
        assert after["documentDeleted"] is True
        assert after["messages"][1]["citations"], "citations survive the document's deletion"
        assert (await r.client.get("/api/documents")).json() == []
