from fastapi import APIRouter

from legallens.api.routes import chat, conversations, documents, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(conversations.router)
api_router.include_router(chat.router)
