import logging
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright

logger = logging.getLogger("jobpilot.playwright")


class PlaywrightBrowserClient:
    """
    Automated Playwright Browser Agent for job application form filling and submission.
    Supports both Human-in-the-Loop review mode and Full Auto-Apply mode.
    """

    async def fill_job_application(
        self,
        application_url: str,
        applicant_data: Dict[str, Any],
        auto_submit: bool = False,
        headless: bool = True
    ) -> Dict[str, Any]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()
            
            try:
                logger.info(f"Playwright Agent navigating to application URL: {application_url}")
                await page.goto(application_url, timeout=30000)
                
                # 1. Fill Candidate Name
                if "name" in applicant_data and applicant_data["name"]:
                    name_input = page.locator("input[name*='name' i], input[id*='name' i]").first
                    if await name_input.count() > 0:
                        await name_input.fill(applicant_data["name"])
                        
                # 2. Fill Email
                if "email" in applicant_data and applicant_data["email"]:
                    email_input = page.locator("input[type='email'], input[name*='email' i]").first
                    if await email_input.count() > 0:
                        await email_input.fill(applicant_data["email"])
                        
                # 3. Fill Phone
                if "phone" in applicant_data and applicant_data["phone"]:
                    phone_input = page.locator("input[type='tel'], input[name*='phone' i]").first
                    if await phone_input.count() > 0:
                        await phone_input.fill(applicant_data["phone"])

                # 4. Fill Cover Letter Textarea if present
                if "cover_letter" in applicant_data and applicant_data["cover_letter"]:
                    cl_input = page.locator("textarea[name*='cover' i], textarea[id*='cover' i], textarea").first
                    if await cl_input.count() > 0:
                        await cl_input.fill(applicant_data["cover_letter"])

                page_title = await page.title()
                
                # 5. Auto-Submit Mode Handling
                if auto_submit:
                    submit_btn = page.locator(
                        "button[type='submit'], input[type='submit'], button:has-text('Submit'), button:has-text('Apply')"
                    ).first
                    if await submit_btn.count() > 0:
                        await submit_btn.click()
                        await page.wait_for_timeout(3000)
                        await browser.close()
                        return {
                            "status": "APPLIED",
                            "auto_submitted": True,
                            "confirmation": f"Successfully auto-submitted application on '{page_title}'.",
                            "url": application_url,
                        }

                await browser.close()
                return {
                    "status": "PENDING_APPROVAL",
                    "auto_submitted": False,
                    "message": f"Successfully loaded application page '{page_title}' and filled known fields.",
                    "url": application_url,
                }
            except Exception as e:
                logger.error(f"Playwright application filling error: {e}")
                await browser.close()
                return {
                    "status": "FAILED",
                    "error": str(e),
                    "url": application_url,
                }
