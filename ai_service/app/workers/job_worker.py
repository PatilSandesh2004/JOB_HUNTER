"""Periodic job discovery for the active profile, as a standalone process.

python -m ai_service.app.workers.job_worker --once
python -m ai_service.app.workers.job_worker --interval 3600 --roles "AI Engineer" --locations Remote

The AI service can do the same by itself: set DISCOVERY_INTERVAL_HOURS in .env.
"""

import argparse
import asyncio
import logging

from ai_service.app.api.deps import get_discovery_service
from ai_service.app.core.config import settings
from ai_service.app.core.logging import configure_logging
from ai_service.app.database.session import init_db

logger = logging.getLogger("jobpilot.worker")


async def main() -> None:
    parser = argparse.ArgumentParser(description="JobPilot periodic job discovery")
    parser.add_argument("--roles", nargs="*", help="defaults to the profile's preferred roles")
    parser.add_argument("--locations", nargs="*", help="defaults to the profile's preferred locations")
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--interval", type=int, default=3600, help="seconds between cycles")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args()

    configure_logging(settings.log_level)
    await init_db()
    discovery = get_discovery_service()
    while True:
        try:
            await discovery.run_once(args.roles, args.locations, args.remote_only)
        except Exception:
            logger.exception("Discovery cycle failed")
        if args.once:
            return
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
