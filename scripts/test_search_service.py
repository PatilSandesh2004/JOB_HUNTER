import asyncio

from backend.app.core.config import settings
from backend.app.integrations.search.searxng_client import SearXNGClient
from backend.app.services.search.search_service import SearchService


async def main():
    # Instantiate the SearXNG client using configuration settings
    client = SearXNGClient(base_url=settings.searxng_url)

    # Inject the client into SearchService
    service = SearchService(searxng_client=client)

    # Execute search query
    results = await service.search(query="AI Engineer Bengaluru")

    print("Number of results:", len(results))

    # Print details for top 5 results
    for result in results[:5]:
        print("\n-----------------------------")
        print("Title:", result.get("title"))
        print("URL:", result.get("url"))
        print("Engine:", result.get("engine"))


if __name__ == "__main__":
    asyncio.run(main())
