import asyncio

from tests.conftest import Running


async def test_create_defaults_and_list_order(r: Running) -> None:
    first = await r.new_conversation()
    assert first["title"] == "New conversation"
    assert (first["documentId"], first["documentDeleted"]) == (None, False)
    assert first["createdAt"] == first["updatedAt"]

    await asyncio.sleep(0.002)
    second = await r.new_conversation(title="  Lease   review  ")
    assert second["title"] == "Lease review"

    listed = (await r.client.get("/api/conversations")).json()
    assert [c["id"] for c in listed] == [second["id"], first["id"]]


async def test_open_conversation_with_no_messages(r: Running) -> None:
    conversation = await r.new_conversation()
    detail = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
    assert detail == {**conversation, "messages": []}


async def test_rename_and_relink(r: Running) -> None:
    doc = await r.ready_document()
    conversation = await r.new_conversation(documentId=doc["id"])
    assert conversation["documentId"] == doc["id"]

    renamed = await r.client.patch(
        f"/api/conversations/{conversation['id']}", json={"title": "x" * 200}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "x" * 120
    assert renamed.json()["documentId"] == doc["id"]  # untouched field stays

    cleared = await r.client.patch(
        f"/api/conversations/{conversation['id']}", json={"documentId": None}
    )
    assert cleared.json()["documentId"] is None
    assert cleared.json()["title"] == "x" * 120


async def test_validation_errors(r: Running) -> None:
    conversation = await r.new_conversation()
    url = f"/api/conversations/{conversation['id']}"

    empty = await r.client.patch(url, json={"title": "   "})
    assert (empty.status_code, empty.json()["code"]) == (422, "invalid_title")

    bad_doc = await r.client.patch(url, json={"documentId": "doc_nope"})
    assert (bad_doc.status_code, bad_doc.json()["code"]) == (404, "document_not_found")

    create_bad_doc = await r.client.post("/api/conversations", json={"documentId": "doc_nope"})
    assert create_bad_doc.status_code == 404

    wrong_type = await r.client.patch(url, json={"title": 5})
    assert (wrong_type.status_code, wrong_type.json()["code"]) == (422, "validation_error")
    assert wrong_type.json()["message"].startswith("title:")


async def test_delete_and_not_found(r: Running) -> None:
    conversation = await r.new_conversation()
    await r.chat(conversation["id"], "hello")
    url = f"/api/conversations/{conversation['id']}"
    assert (await r.client.delete(url)).status_code == 204

    for res in (
        await r.client.get(url),
        await r.client.patch(url, json={"title": "x"}),
        await r.client.delete(url),
    ):
        body = res.json()
        assert (res.status_code, body["code"]) == (404, "conversation_not_found")
        assert body["request_id"] == res.headers["x-request-id"]
