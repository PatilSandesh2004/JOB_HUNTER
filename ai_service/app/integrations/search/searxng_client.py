"""Thin async client for a SearXNG instance's JSON API (requires `search.formats: [html, json]`)."""

from typing import Any

import httpx


class SearXNGError(RuntimeError):
    pass


class SearXNGClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        language: str = "en",
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        """Return result dicts. Raises SearXNGError when nothing came back because engines are blocked."""
        params = {"q": query, "format": "json", "pageno": page, "language": language}
        if client is not None:
            return await self._request(client, params)
        async with httpx.AsyncClient(timeout=self.timeout) as own_client:
            return await self._request(own_client, params)

    async def _request(self, client: httpx.AsyncClient, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = await client.get(f"{self.base_url}/search", params=params, timeout=self.timeout)
        if response.status_code == 403:
            raise SearXNGError("SearXNG rejected format=json; add 'json' to search.formats in settings.yml")
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", [])
        unresponsive = payload.get("unresponsive_engines") or []
        if not results and unresponsive:
            reasons = ", ".join(f"{name} ({reason})" for name, reason in unresponsive)
            raise SearXNGError(f"no results, engines unavailable: {reasons}")
        return results

    async def healthcheck(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/healthz")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
