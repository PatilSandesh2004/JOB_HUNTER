"""Render HTML to PDF with the Chromium that Playwright already installs (no extra PDF dependency)."""

from pathlib import Path

from ai_service.app.integrations.browser.runtime import in_browser_thread

_MARGIN = {"top": "14mm", "bottom": "14mm", "left": "15mm", "right": "15mm"}


async def render_pdf(html: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    async def job() -> Path:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                # The document is self-contained; block any network access it might attempt.
                await page.route("**/*", lambda route: route.abort())
                await page.set_content(html, wait_until="domcontentloaded")
                await page.pdf(
                    path=str(path), format="A4", print_background=True, margin=_MARGIN, prefer_css_page_size=True
                )
            finally:
                await browser.close()
        return path

    return await in_browser_thread(job)
