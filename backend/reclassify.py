"""Rebuild the reference library's category tree and facet index.

Run it after changing taxonomy rules, or after reorganising folders that were
already imported::

    .venv\\Scripts\\python.exe backend\\reclassify.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import db  # noqa: E402
from app.core import library  # noqa: E402


def main() -> None:
    db.init_db()
    started = time.perf_counter()
    with db.connect() as conn:
        result = library.rebuild_taxonomy(conn)
    elapsed = time.perf_counter() - started
    print(
        f"重新分类完成：{result['items']} 条素材，{result['facets']} 个分类标签"
        f"（{elapsed:.1f}s）"
    )


if __name__ == "__main__":
    main()
