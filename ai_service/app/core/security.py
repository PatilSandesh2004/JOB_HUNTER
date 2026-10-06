"""API access token check shared by every router except /health."""

import hmac

from fastapi import HTTPException, Request, status

from ai_service.app.core.config import settings


def presented_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Token", "").strip()


async def require_token(request: Request) -> None:
    """Reject requests without the configured API_TOKEN. No-op when no token is configured."""
    expected = settings.api_token
    if not expected:
        return
    if not hmac.compare_digest(presented_token(request).encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or invalid API token", headers={"WWW-Authenticate": "Bearer"}
        )
