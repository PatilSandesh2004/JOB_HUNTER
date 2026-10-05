from typing import Any, Dict
import httpx


class SearXNGClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
    
    async def search(self, query: str, page: int = 1, language: str = "en") -> Dict[str, Any]:
        params = {
            "q": query,
            "format": "json",
            "pageno": page,
            "language": language,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/search",
                params=params,
            )
            response.raise_for_status()
            return response.json()

