"""Google results through the Serper.dev API (WEB_SEARCH_PROVIDER=serper), as an alternative to SearXNG.

Results are returned in SearXNG's shape ({url, title, content, engine, publishedDate}).
"""

from typing import Any

import httpx

from ai_service.app.core.http import tls_verify

SERPER_URL = "https://google.serper.dev/search"
_TIME_FILTERS = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}


class SerperError(RuntimeError):
    pass


class SerperClient:
    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

    async def search(
        self, query: str, *, client: httpx.AsyncClient | None = None, time_range: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise SerperError("SERPER_API_KEY is not configured")
        if client is not None:
            return await self._request(client, query, time_range)
        async with httpx.AsyncClient(timeout=self.timeout, verify=tls_verify()) as own_client:
            return await self._request(own_client, query, time_range)

    async def _request(self, client: httpx.AsyncClient, query: str, time_range: str | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"q": query, "num": 100}
        if time_range in _TIME_FILTERS:
            payload["tbs"] = _TIME_FILTERS[time_range]  # Google's "past day/week/month" filter
        response = await client.post(SERPER_URL, headers=self._headers(), json=payload, timeout=self.timeout)
        response.raise_for_status()
        return [
            {
                "url": item.get("link"),
                "title": item.get("title"),
                "content": item.get("snippet"),
                "engine": "serper",
                "publishedDate": item.get("date"),
            }
            for item in response.json().get("organic", [])
        ]

    async def healthcheck(self) -> bool:
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=tls_verify()) as client:
                response = await client.post(SERPER_URL, headers=self._headers(), json={"q": "test", "num": 1})
                return response.status_code == 200
        except httpx.HTTPError:
            return False
