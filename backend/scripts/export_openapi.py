"""Writes the API contract to ``backend/openapi.json``.

Run after an intended API change:  uv run python scripts/export_openapi.py
The contract test fails until the snapshot matches the code.
"""

import json
import tempfile
from pathlib import Path

from legallens.config import Settings
from legallens.main import create_app

TARGET = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Settings(_env_file=None, data_dir=Path(tmp), log_level="WARNING"))
        spec = app.openapi()
    TARGET.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
