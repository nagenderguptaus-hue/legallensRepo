from typing import Any

from fastapi import APIRouter, Response

from legallens.api.deps import ContainerDep
from legallens.api.schemas import (
    ApiErrorBody,
    Conversation,
    ConversationCreate,
    ConversationDetail,
    ConversationPatch,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])

ERRORS: dict[int | str, dict[str, object]] = {
    status: {"model": ApiErrorBody} for status in (404, 422)
}


@router.get("", response_model=list[Conversation], summary="Conversations, most recent first")
async def list_conversations(c: ContainerDep) -> list[Conversation]:
    return [Conversation.from_row(row) for row in await c.conversations.list()]


@router.post("", status_code=201, response_model=Conversation, responses=ERRORS, summary="New chat")
async def create_conversation(body: ConversationCreate, c: ContainerDep) -> Conversation:
    row = await c.conversations.create(body.title, body.document_id)
    return Conversation.from_row(row)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    responses=ERRORS,
    summary="Open a conversation with its messages and citations",
)
async def get_conversation(conversation_id: str, c: ContainerDep) -> ConversationDetail:
    return ConversationDetail.from_row_with_messages(
        await c.conversations.get_detail(conversation_id)
    )


@router.patch(
    "/{conversation_id}",
    response_model=Conversation,
    responses=ERRORS,
    summary="Rename, or change the linked document",
)
async def update_conversation(
    conversation_id: str, body: ConversationPatch, c: ContainerDep
) -> Conversation:
    changes: dict[str, Any] = {
        field: getattr(body, field) for field in body.model_fields_set & {"title", "document_id"}
    }
    row = await c.conversations.update(conversation_id, **changes)
    return Conversation.from_row(row)


@router.delete(
    "/{conversation_id}",
    status_code=204,
    response_class=Response,
    responses=ERRORS,
    summary="Delete a conversation and its messages",
)
async def delete_conversation(conversation_id: str, c: ContainerDep) -> Response:
    await c.conversations.delete(conversation_id)
    return Response(status_code=204)
