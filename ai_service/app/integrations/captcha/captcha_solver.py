import logging
import asyncio
import httpx
from typing import Optional

logger = logging.getLogger("jobpilot.captcha")


class CaptchaSolverService:
    """
    Integrates 2Captcha / Anti-Captcha API to solve reCAPTCHA v2/v3 and Cloudflare
    turnstile challenges on complex corporate job portals (Workday, Taleo, Greenhouse).
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or ""

    async def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        if not self.api_key:
            logger.info("Captcha solver API key not set; bypassing via Playwright standard DOM submit.")
            return None

        # 2Captcha API Request
        in_url = f"https://2captcha.com/in.php?key={self.api_key}&method=userrecaptcha&googlekey={site_key}&pageurl={page_url}&json=1"
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                res = await client.get(in_url)
                data = res.json()
                if data.get("status") != 1:
                    return None
                
                request_id = data.get("request")
                res_url = f"https://2captcha.com/res.php?key={self.api_key}&action=get&id={request_id}&json=1"
                
                # Poll for token resolution
                for _ in range(12):
                    await asyncio.sleep(5)
                    token_res = await client.get(res_url)
                    token_data = token_res.json()
                    if token_data.get("status") == 1:
                        return token_data.get("request")
        except Exception as e:
            logger.warning(f"Captcha solver API exception: {e}")

        return None
