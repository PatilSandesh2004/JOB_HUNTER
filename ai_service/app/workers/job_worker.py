"""Periodic job discovery for the active profile.

python -m ai_service.app.workers.job_worker --once
python -m ai_service.app.workers.job_worker --interval 3600 --roles "AI Engineer" --locations Remote
"""

import argparse
import asyncio
import logging

from ai_service.app.api.deps import get_notifier, get_search_agent
from ai_service.app.core.config import settings
from ai_service.app.core.logging import configure_logging
from ai_service.app.database.session import AsyncSessionLocal, init_db
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.search import SearchQueryRequest

logger = logging.getLogger("jobpilot.worker")


async def run_discovery_cycle(roles: list[str] | None, locations: list[str] | None, remote_only: bool) -> int:
    async with AsyncSessionLocal() as session:
        candidate = await CandidateRepository(session).get_active()
        prefs = candidate.preferences if candidate else None
        if not roles and prefs:
            roles = prefs.preferred_roles or ([candidate.current_role] if candidate.current_role else [])
        if not roles:
            logger.error("No roles given and the profile has no preferred roles; nothing to search")
            return 0
        request = SearchQueryRequest(
            roles=roles,
            locations=locations or (prefs.preferred_locations if prefs else []),
            remote_only=remote_only,
            sponsorship_required=bool(prefs and prefs.visa_sponsorship_required),
        )
        response = await get_search_agent().run(request, candidate)
        await JobRepository(session).upsert_many(response.results)
        sent = await get_notifier().notify_high_matches(response.results)
        logger.info(
            "Discovery cycle: %d raw -> %d jobs stored, %d alerts sent, %d source errors",
            response.total_raw,
            response.total_results,
            sent,
            len(response.errors),
        )
        return response.total_results


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
    while True:
        try:
            await run_discovery_cycle(args.roles, args.locations, args.remote_only)
        except Exception:
            logger.exception("Discovery cycle failed")
        if args.once:
            return
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
