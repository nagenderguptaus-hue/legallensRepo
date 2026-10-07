"""Writes the synthetic demo documents to a folder, e.g. for the frontend's end-to-end tests.

uv run python scripts/make_fixtures.py --out ../frontend/e2e/.fixtures
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_documents import all_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out: Path = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    for file in all_files():
        (out / file.name).write_bytes(file.content)
        print(f"wrote {out / file.name}")


if __name__ == "__main__":
    main()
