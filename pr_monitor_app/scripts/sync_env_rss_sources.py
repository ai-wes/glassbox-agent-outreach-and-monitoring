from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pr_monitor_app.bootstrap.rss_sources import sync_rss_sources
from pr_monitor_app.db import session_scope


async def _main() -> None:
    async with session_scope() as session:
        result = await sync_rss_sources(session)
    print(result)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
