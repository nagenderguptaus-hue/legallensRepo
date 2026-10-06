"""The backend's JSON must match the frontend's TypeScript contract field for field.

Interfaces are read straight from ``frontend/src/api/types.ts``, so a change on either side
that breaks the other fails here. Skipped when the backend is checked out on its own.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from legallens.config import Settings
from legallens.main import create_app
from tests.conftest import Running, parse_sse

BACKEND = Path(__file__).resolve().parents[2]
TYPES_TS = BACKEND.parent / "frontend" / "src" / "api" / "types.ts"
OPENAPI_SNAPSHOT = BACKEND / "openapi.json"


def typescript_interfaces(source: str) -> dict[str, tuple[set[str], set[str]]]:
    """``{name: (required_fields, optional_fields)}``, following ``extends``."""
    raw: dict[str, tuple[str | None, set[str], set[str]]] = {}
    for match in re.finditer(
        r"export interface (\w+)(?: extends (\w+))? \{(.*?)\n\}", source, flags=re.DOTALL
    ):
        name, parent, body = match.groups()
        body = re.sub(r"/\*\*.*?\*/", "", body, flags=re.DOTALL)
        required: set[str] = set()
        optional: set[str] = set()
        for field, question in re.findall(r"^\s{2}(\w+)(\?)?:", body, flags=re.MULTILINE):
            (optional if question else required).add(field)
        raw[name] = (parent, required, optional)

    def resolve(name: str) -> tuple[set[str], set[str]]:
        parent, required, optional = raw[name]
        if parent:
            parent_required, parent_optional = resolve(parent)
            return required | parent_required, optional | parent_optional
        return required, optional

    return {name: resolve(name) for name in raw}


@pytest.fixture(scope="module")
def contract() -> dict[str, tuple[set[str], set[str]]]:
    if not TYPES_TS.exists():
        pytest.skip("frontend/src/api/types.ts not found (backend checked out alone)")
    return typescript_interfaces(TYPES_TS.read_text(encoding="utf-8"))


def assert_matches(payload: dict[str, Any], interface: str, contract: dict[str, Any]) -> None:
    required, optional = contract[interface]
    keys = set(payload)
    assert required <= keys, f"{interface}: missing {sorted(required - keys)}"
    assert keys <= required | optional, (
        f"{interface}: unexpected {sorted(keys - required - optional)}"
    )


async def test_rest_payloads_match_typescript(r: Running, contract: dict[str, Any]) -> None:
    doc = await r.ready_document()
    assert_matches(doc, "LegalDocument", contract)
    assert_matches(
        (await r.client.get(f"/api/documents/{doc['id']}/pages/1")).json(), "DocumentPage", contract
    )
    assert_matches((await r.client.get("/api/health")).json(), "Health", contract)

    conversation = await r.new_conversation()
    assert_matches(conversation, "Conversation", contract)
    await r.chat(conversation["id"], "How long does the agreement remain in effect?", [doc["id"]])
    detail = (await r.client.get(f"/api/conversations/{conversation['id']}")).json()
    assert_matches(detail, "ConversationDetail", contract)
    for message in detail["messages"]:
        assert_matches(message, "Message", contract)
        for citation in message["citations"]:
            assert_matches(citation, "Citation", contract)

    error = (await r.client.get("/api/documents/doc_missing")).json()
    assert_matches(error, "ApiErrorBody", contract)


async def test_sse_payloads_match_typescript(r: Running, contract: dict[str, Any]) -> None:
    doc = await r.ready_document()
    conversation = await r.new_conversation()
    res = await r.chat(
        conversation["id"], "How long does the agreement remain in effect?", [doc["id"]]
    )
    expected = {
        "intent": {"intent", "message_id", "user_message_id"},
        "status": {"label"},
        "token": {"text"},
        "done": {"message_id", "user_message_id", "outcome", "suggestions", "title"},
    }
    seen = set()
    for name, data in parse_sse(res.text):
        seen.add(name)
        if name == "citation":
            assert_matches(data, "Citation", contract)
        else:
            assert set(data) == expected[name], name
    assert seen == {"intent", "status", "token", "citation", "done"}

    # the ChatEvent union in types.ts lists exactly the events the backend can send
    union = re.search(
        r"export type ChatEvent =(.*?);\n\n", TYPES_TS.read_text(encoding="utf-8"), re.DOTALL
    )
    assert union is not None
    assert set(re.findall(r"event: '(\w+)'", union.group(1))) == {*expected, "citation", "error"}


def test_openapi_snapshot_is_current(tmp_path: Path) -> None:
    """``openapi.json`` is the published contract. Regenerate it with
    ``uv run python scripts/export_openapi.py`` after an intended API change."""
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, log_level="WARNING"))
    current = json.loads(json.dumps(app.openapi()))
    assert OPENAPI_SNAPSHOT.exists(), "run scripts/export_openapi.py"
    assert current == json.loads(OPENAPI_SNAPSHOT.read_text(encoding="utf-8")), (
        "API changed: review, then run `uv run python scripts/export_openapi.py`"
    )
