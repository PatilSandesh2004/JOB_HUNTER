import httpx
from typing import Any

class SerperClient:
    def __init__(self, api_key: str, timeout: float = 10.0):
        self.api_key = api_key
        self.timeout = timeout

    async def search(self, query: str, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("Serper API key not configured")
        
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        
        # If no client passed, create our own temporary one
        own_client = None
        if client is None:
            own_client = httpx.AsyncClient(timeout=self.timeout, verify=False)
            client = own_client
            
        try:
            response = await client.post(
                "https://google.serper.dev/search",
                headers=headers,
                json={"q": query, "num": 100}
            )
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("organic", []):
                results.append({
                    "url": item.get("link"),
                    "title": item.get("title"),
                    "content": item.get("snippet"),
                    "engine": "serper",
                    "publishedDate": item.get("date")
                })
            return results
        finally:
            if own_client is not None:
                await own_client.aclose()

    async def healthcheck(self) -> bool:
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                    json={"q": "test"}
                )
                return response.status_code == 200
        except Exception:
            return False
