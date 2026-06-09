from __future__ import annotations

import asyncio

from backend.app.core.version import APP_VERSION, SCHEMA_VERSION
from backend.app.database.bootstrap import ensure_database


async def _main() -> None:
    await ensure_database()


def main() -> None:
    asyncio.run(_main())
    print(f"LLMBridge {APP_VERSION} | schema {SCHEMA_VERSION}")


if __name__ == "__main__":
    main()
